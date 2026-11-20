from __future__ import annotations

import logging
import os
import re
import threading
from pathlib import Path
from io import BytesIO
from typing import Any
from urllib.parse import urlsplit

from dotenv import load_dotenv
from fastapi import FastAPI, BackgroundTasks, UploadFile, File, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from api import db
from api.artifact_storage import (
    StorageError,
    get_storage,
    storage_backend,
)
from api.retrieval import (
    DEFAULT_OPENROUTER_MODEL,
    MAX_USER_DOCUMENT_CHARS,
    answer_question,
    describe_serving,
    get_index_status,
    load_latest_report,
    reload_index,
)
from api.startup_diagnostics import startup_phase
from ingestion.run_ingestion import run_ingestion
from api.campus import ADMIN_ONLY, install_campus_routes

load_dotenv()
ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIST = ROOT / "frontend" / "dist"

app = FastAPI(title="STIF.ai SVCE College Assistant", version="0.1.0")
LOGGER = logging.getLogger(__name__)


def configured_cors_origins() -> list[str]:
    """Exact browser origins allowed to use credentialed API requests."""
    raw = os.getenv("STIF_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    origins = [item.strip().rstrip("/") for item in raw.split(",") if item.strip()]
    for origin in origins:
        try:
            parsed = urlsplit(origin)
            valid_local = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}
            valid_https = parsed.scheme == "https" and bool(parsed.hostname)
            valid_shape = bool(parsed.netloc) and not parsed.username and not parsed.password and not parsed.path and not parsed.query and not parsed.fragment
            _ = parsed.port
        except ValueError:
            valid_local = valid_https = valid_shape = False
        if not (valid_shape and (valid_local or valid_https)):
            raise RuntimeError("STIF_CORS_ORIGINS must contain explicit HTTPS origins or local development origins.")
    return origins


def configured_allowed_hosts() -> list[str]:
    """Return explicit Host header names; proxy host wildcards are not accepted."""
    raw = os.getenv("STIF_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver")
    hosts = [item.strip().lower() for item in raw.split(",") if item.strip()]
    pattern = re.compile(r"(?:[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?)")
    if not hosts or any(not pattern.fullmatch(host) or ".." in host for host in hosts):
        raise RuntimeError("STIF_ALLOWED_HOSTS must contain explicit hostnames; wildcard hosts are not allowed.")
    return hosts


app.add_middleware(TrustedHostMiddleware, allowed_hosts=configured_allowed_hosts())


def enforce_production_database() -> None:
    """Prevent a deployment explicitly marked production from silently using SQLite."""
    if os.getenv("STIF_ENV", "").strip().lower() in {"prod", "production"} and db.database_backend() != "postgres":
        raise RuntimeError("STIF_ENV=production requires PostgreSQL through STIF_DATABASE_URL.")


@app.on_event("startup")
def _check_production_database() -> None:
    enforce_production_database()
    if storage_backend() == "r2":
        try:
            with startup_phase(LOGGER, "s3.materialize_active") as phase:
                result = get_storage().materialize_active()
                for key in ("files", "bytes"):
                    value = result.get(key)
                    if isinstance(value, int):
                        phase[key] = value
        except StorageError:
            raise RuntimeError("Persistent knowledge-artifact storage is unavailable.") from None
        if not result.get("generation"):
            raise RuntimeError("Persistent knowledge-artifact storage has no active generation.")
        with startup_phase(LOGGER, "retrieval.reload_index") as phase:
            index_status = reload_index()
            chunks = index_status.get("chunks_loaded")
            if isinstance(chunks, int):
                phase["chunks"] = chunks

# Permit the local Vite frontend to call this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=configured_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
)

# Student enquiries, authentication and admin dashboard APIs (see api/campus.py).
install_campus_routes(app)

if (FRONTEND_DIST / "assets").is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=str(FRONTEND_DIST / "assets")),
        name="frontend-assets",
    )

_ingest_lock = threading.Lock()
_ingest_state: dict[str, Any] = {
    "status": "idle",
    "message": "No ingestion job started in this process.",
}


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=3000)
    attachment_text: str | None = Field(default=None, max_length=MAX_USER_DOCUMENT_CHARS)
    attachment_name: str | None = Field(default=None, max_length=255)


class ChatResponse(BaseModel):
    answer: str
    sources: list[dict[str, str]] = []
    mode: str = "retrieval"


MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".pdf", ".docx", ".png", ".jpg", ".jpeg", ".webp"}

def _extract_uploaded_text(filename: str, content: bytes) -> tuple[str, str]:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Unsupported file type.")
    if suffix in {".txt", ".md", ".csv", ".json"}:
        return content.decode("utf-8-sig", errors="replace"), suffix[1:]
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(BytesIO(content))
            return "\n\n".join(page.extract_text() or "" for page in reader.pages), "pdf"
        except Exception as exc:
            raise HTTPException(status_code=422, detail="Could not read this PDF. It may be invalid or password-protected.") from exc
    if suffix == ".docx":
        try:
            from docx import Document
            doc = Document(BytesIO(content))
            parts = [p.text for p in doc.paragraphs if p.text.strip()]
            for table in doc.tables:
                for row in table.rows: parts.append(" | ".join(cell.text.strip() for cell in row.cells))
            return "\n".join(parts), "docx"
        except Exception as exc:
            raise HTTPException(status_code=422, detail="Could not read this DOCX document.") from exc
    if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        try:
            from PIL import Image
            import pytesseract
            return pytesseract.image_to_string(Image.open(BytesIO(content)).convert("RGB")), "image-ocr"
        except ImportError as exc:
            raise HTTPException(status_code=503, detail="Image OCR needs Pillow, pytesseract, and the Tesseract OCR application installed on the backend computer.") from exc
        except Exception as exc:
            raise HTTPException(status_code=422, detail="Could not read text from this image. Try a clearer image.") from exc
    raise HTTPException(status_code=415, detail="Unsupported file type.")


@app.get("/", response_class=HTMLResponse)
def home():
    built_index = FRONTEND_DIST / "index.html"
    if not built_index.is_file():
        return HTMLResponse(
            "<main><h1>STIF Campus AI</h1><p>The production frontend has not been built. "
            "For development, start the Vite frontend with <code>npm run dev</code>; "
            "for production, run <code>npm run build</code> in the frontend directory.</p></main>",
            status_code=503,
        )
    return built_index.read_text(encoding="utf-8")


@app.get("/health")
def health():
    index = get_index_status()  # also picks up a newly published index
    return {
        "status": "ok",
        "project": "STIF.ai SVCE College Assistant",
        "college": os.getenv(
            "COLLEGE_NAME",
            "Sri Venkateswara College of Engineering, Tirupati",
        ),
        "chunks_loaded": index["chunks_loaded"],
        "index_ready": index["index_ready"],
        "llm_configured": bool(
            os.getenv("OPENROUTER_API_KEY", "").strip()
            and os.getenv("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL).strip()
        ),
    }


@app.get("/ready")
def readiness(response: Response):
    """Readiness probe: liveness remains separate; database details are never returned."""
    response.headers["Cache-Control"] = "no-store"
    try:
        with db.session() as conn:
            conn.execute("SELECT 1").fetchone()
        if storage_backend() == "r2" and not get_storage().check_ready():
            raise RuntimeError("Artifact storage unavailable")
    except Exception:
        response.status_code = 503
        return {"status": "not_ready"}
    return {"status": "ready"}


@app.post("/api/v1/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    result = answer_question(
        request.message.strip(),
        user_document_text=request.attachment_text,
        user_document_name=request.attachment_name,
    )
    return ChatResponse(**result)


@app.post("/api/v1/files/extract")
async def extract_uploaded_file(file: UploadFile = File(...)):
    filename = Path(file.filename or "upload").name
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if not content: raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(content) > MAX_UPLOAD_BYTES: raise HTTPException(status_code=413, detail="Maximum upload size is 10 MB.")
    text, file_type = _extract_uploaded_text(filename, content)
    if len(text) > MAX_USER_DOCUMENT_CHARS:
        raise HTTPException(
            status_code=413,
            detail=(
                f"This file contains more than {MAX_USER_DOCUMENT_CHARS:,} characters of extracted text. "
                "No text was discarded. Split the document into smaller files and try again."
            ),
        )
    return {"filename": filename, "file_type": file_type, "text": text}


@app.get("/api/v1/ingest/status", dependencies=ADMIN_ONLY)
def ingestion_status():
    return {
        "job": dict(_ingest_state),
        "last_report": load_latest_report(),
        # What is actually being served now, independent of the job outcome.
        "serving": get_index_status(),
    }


@app.get("/api/v1/index/status")
def index_status():
    """State of the index currently served (not of the last ingestion job)."""
    return get_index_status()


@app.post("/api/v1/index/reload", dependencies=ADMIN_ONLY)
def index_reload():
    """Load the latest published index without restarting.

    If the new files are missing, empty or invalid, the last known-good index
    keeps serving and ``last_error`` explains why.
    """
    try:
        if storage_backend() == "r2":
            get_storage().materialize_active()
    except StorageError:
        raise HTTPException(status_code=503, detail="Knowledge index storage is temporarily unavailable.") from None
    return reload_index()


def _run_ingest_task(start_url: str, max_pages: int):
    global _ingest_state
    try:
        _ingest_state.update(status="running", message="Ingestion is running.")
        report = run_ingestion(start_url=start_url, max_pages=max_pages)
        if not report.get("published"):
            # Build finished but failed validation: the live index is unchanged.
            _ingest_state.update(
                status="unpublished",
                message=(
                    "Ingestion finished but the new index was NOT published; "
                    "the previous index is still active. "
                    f"Reason: {report.get('reason', 'unknown')}"
                ),
                report=report,
            )
            return
        if storage_backend() == "r2":
            try:
                get_storage().publish_local()
            except Exception as exc:
                # Driver/transaction failures also need to restore the local
                # index; never surface third-party or database error details.
                import logging
                logging.getLogger("api.artifact_storage").error(
                    "Artifact generation publication failed (error_type=%s).", type(exc).__name__
                )
                # Do not report the new index as active when its durable generation
                # was not switched. Restore the prior known-good index locally.
                from ingestion.index_publisher import IndexPublishError, rollback_index
                try:
                    rollback_index(ROOT / "data" / "index", report.get("backup"))
                    reload_index()
                except (IndexPublishError, OSError):
                    pass
                _ingest_state.update(
                    status="failed",
                    message="Could not confirm durable knowledge-generation publication; synchronize the active generation before retrying.",
                    report=report,
                )
                return
        reload_index()
        published_path = ROOT / "data" / "index" / "chunks.jsonl"
        serving = describe_serving(published_path, report.get("sha256"))
        if serving["serving_published_index"]:
            status, message = "completed", (
                "Ingestion finished and the new index was published and is being served."
            )
        else:
            status, message = "published_not_serving", (
                "Ingestion finished and the new index was published to data/index, "
                f"but it is NOT the index being served. {serving['serving_reason']}"
            )
        _ingest_state.update(
            status=status,
            message=message,
            serving_published_index=serving["serving_published_index"],
            serving_source=serving["serving_source"],
            serving_reason=serving["serving_reason"],
            serving_last_error=serving["last_error"],
            report=report,
        )
    except Exception as exc:
        _ingest_state.update(status="failed", message=str(exc))


@app.post("/api/v1/ingest/run", dependencies=ADMIN_ONLY)
def start_ingestion(
    background_tasks: BackgroundTasks,
    max_pages: int | None = None,
):
    global _ingest_state

    if _ingest_state.get("status") in {"queued", "running"}:
        return {
            "status": "running",
            "message": "An ingestion job is already running.",
        }

    if not _ingest_lock.acquire(blocking=False):
        return {
            "status": "running",
            "message": "An ingestion job is already running.",
        }

    def wrapped():
        try:
            _run_ingest_task(
                os.getenv("START_URL", "https://svce.edu.in/"),
                max_pages or int(os.getenv("MAX_PAGES", "500")),
            )
        finally:
            _ingest_lock.release()

    _ingest_state = {"status": "queued", "message": "Ingestion job queued."}
    background_tasks.add_task(wrapped)
    return {
        "status": "queued",
        "message": "Ingestion job queued. Check /api/v1/ingest/status.",
    }
