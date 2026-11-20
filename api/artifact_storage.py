"""Local-first storage for public SVCE knowledge and retrieval artifacts.

Local mode is a no-op boundary over the existing ``data/`` layout. The opt-in R2
mode publishes immutable generations and switches a small active manifest last.
SQLite databases, chat attachments, secrets, and reports are never included.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"
MANIFEST_VERSION = 1
ALLOWED_DIRECTORIES = frozenset({
    "index", "index_fast", "raw", "raw_fast", "processed", "processed_fast", "sources",
})
ALLOWED_ROOT_FILES = frozenset({"sitemap_urls.txt", "fast_discovered_urls.txt"})
MAX_MANIFEST_FILES = 100_000

_LOGGER = logging.getLogger("api.artifact_storage")
_LOCAL_STORAGE: "LocalArtifactStorage | None" = None
_S3_STORAGE: dict[str, "S3ArtifactStorage"] = {}


class StorageError(RuntimeError):
    """Safe object-storage error suitable for an operator-facing message."""


class StorageConfigurationError(StorageError):
    """Invalid explicit artifact-storage configuration."""


class ArtifactStorage(Protocol):
    def materialize_active(self) -> dict[str, Any]: ...
    def publish_local(self) -> dict[str, Any]: ...
    def check_ready(self) -> bool: ...


class LocalArtifactStorage:
    """Keep the existing local ``data/`` tree as the default storage backend."""

    def materialize_active(self) -> dict[str, Any]:
        return {"backend": "local", "materialized": False}

    def publish_local(self) -> dict[str, Any]:
        return {"backend": "local", "published": False}

    def check_ready(self) -> bool:
        return True


@dataclass(frozen=True)
class _ManifestFile:
    path: str
    key: str
    size: int
    sha256: str


class S3ArtifactStorage:
    """Private S3-compatible generation storage (configured for Cloudflare R2)."""

    def __init__(self, client: Any, *, bucket: str, prefix: str, data_root: Path = DATA_ROOT):
        self._client = client
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.data_root = Path(data_root).resolve()
        self.active_key = f"{self.prefix}/active.json"
        self._current_generation: str | None = None

    def _client_call(self, operation: str, call):
        try:
            return call()
        except Exception as exc:
            _LOGGER.error("Artifact storage request failed (operation=%s, error_type=%s).",
                          operation, type(exc).__name__)
            raise StorageError("Persistent artifact storage is unavailable.") from None

    def check_ready(self) -> bool:
        try:
            self._client.head_object(Bucket=self.bucket, Key=self.active_key)
            return True
        except Exception as exc:
            _LOGGER.error("Artifact storage readiness check failed (error_type=%s).", type(exc).__name__)
            return False

    def _manifest_is_missing(self) -> bool:
        """Distinguish an empty bucket from an unavailable or misconfigured bucket."""
        try:
            self._client.head_object(Bucket=self.bucket, Key=self.active_key)
            return False
        except Exception as exc:
            response = getattr(exc, "response", {})
            error = response.get("Error", {}) if isinstance(response, dict) else {}
            code = str(error.get("Code", ""))
            status = response.get("ResponseMetadata", {}).get("HTTPStatusCode") if isinstance(response, dict) else None
            if code in {"404", "NoSuchKey", "NotFound"} or status == 404:
                return True
            _LOGGER.error("Artifact manifest check failed (error_type=%s).", type(exc).__name__)
            raise StorageError("Persistent artifact storage is unavailable.") from None

    @staticmethod
    def _allowed_path(relative: str) -> PurePosixPath:
        if not isinstance(relative, str) or "\\" in relative:
            raise StorageError("Artifact manifest contains an invalid path.")
        parsed = PurePosixPath(relative)
        if parsed.is_absolute() or not parsed.parts or any(part in {"", ".", ".."} for part in parsed.parts):
            raise StorageError("Artifact manifest contains an invalid path.")
        if parsed.parts[0] not in ALLOWED_DIRECTORIES and not (
            len(parsed.parts) == 1 and parsed.parts[0] in ALLOWED_ROOT_FILES
        ):
            raise StorageError("Artifact manifest contains a path outside the allowed knowledge data.")
        if any(part in {".staging", ".publish.lock"} for part in parsed.parts):
            raise StorageError("Artifact manifest contains a temporary path.")
        suffix = parsed.name.lower()
        if suffix.endswith((".db", ".sqlite", ".sqlite3", ".db-wal", ".db-shm")):
            raise StorageError("Database files are not supported as stored artifacts.")
        return parsed

    def _collect_local_files(self) -> list[tuple[str, Path, int, str]]:
        files: list[tuple[str, Path, int, str]] = []
        try:
            for directory in sorted(ALLOWED_DIRECTORIES):
                base = self.data_root / directory
                if not base.is_dir():
                    continue
                for path in sorted(base.rglob("*")):
                    if not path.is_file() or path.is_symlink():
                        continue
                    relative = path.relative_to(self.data_root).as_posix()
                    try:
                        self._allowed_path(relative)
                    except StorageError:
                        continue
                    size, digest = _file_digest(path)
                    files.append((relative, path, size, digest))
            for name in sorted(ALLOWED_ROOT_FILES):
                path = self.data_root / name
                if path.is_file() and not path.is_symlink():
                    size, digest = _file_digest(path)
                    files.append((name, path, size, digest))
        except OSError:
            raise StorageError("Could not read local knowledge artifacts.") from None
        if not files:
            raise StorageError("No approved local knowledge artifacts were found to publish.")
        if not any(name in {"index/chunks.jsonl", "index_fast/chunks.jsonl"} for name, *_ in files):
            raise StorageError("No validated retrieval index file was found to publish.")
        if len(files) > MAX_MANIFEST_FILES:
            raise StorageError("There are too many knowledge artifacts to publish safely.")
        return files

    def publish_local(self, *, allow_initial: bool = False) -> dict[str, Any]:
        """Upload an immutable generation; switch the active manifest only after all uploads."""
        from api import db

        if db.database_backend() != "postgres":
            raise StorageError("Shared artifact publication requires the configured PostgreSQL backend.")
        local_files = self._collect_local_files()
        generation = uuid.uuid4().hex
        generation_prefix = f"{self.prefix}/generations/{generation}"
        entries: list[dict[str, Any]] = []
        total_bytes = 0
        # Hold the advisory lock through generation upload and manifest switch,
        # preventing concurrent writers from activating stale local snapshots.
        with db.session() as conn:
            with db.transaction(conn):
                conn.lock_key("stif-campus-ai:artifact-manifest")
                if self._manifest_is_missing():
                    if not allow_initial or self._current_generation is not None:
                        raise StorageError("No active artifact generation exists; seed it explicitly first.")
                    current = None
                else:
                    current, _ = self._load_manifest()
                if current != self._current_generation:
                    raise StorageError("The active artifact generation changed; synchronize before publishing.")
                for relative, path, size, digest in local_files:
                    key = f"{generation_prefix}/{relative}"
                    self._client_call("upload", lambda path=path, key=key: self._client.upload_file(
                        str(path), self.bucket, key,
                    ))
                    current_size, current_digest = _file_digest(path)
                    if current_size != size or current_digest != digest:
                        raise StorageError("A knowledge artifact changed during publication; retry after indexing is idle.")
                    total_bytes += size
                    entries.append({"path": relative, "key": key, "size": size, "sha256": digest})
                manifest = {"version": MANIFEST_VERSION, "generation": generation, "files": entries}
                body = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
                self._client_call("activate_generation", lambda: self._client.put_object(
                    Bucket=self.bucket, Key=self.active_key, Body=body, ContentType="application/json",
                ))
                self._current_generation = generation
        return {"backend": "r2", "generation": generation, "files": len(entries), "bytes": total_bytes}

    def _load_manifest(self) -> tuple[str, list[_ManifestFile]]:
        response = self._client_call("read_manifest", lambda: self._client.get_object(
            Bucket=self.bucket, Key=self.active_key,
        ))
        body = response.get("Body")
        try:
            raw = body.read()
        finally:
            if body is not None:
                body.close()
        try:
            manifest = json.loads(raw)
        except (TypeError, ValueError):
            raise StorageError("The active knowledge-artifact manifest is invalid.") from None
        if not isinstance(manifest, dict):
            raise StorageError("The active knowledge-artifact manifest is invalid.")
        generation = manifest.get("generation")
        files = manifest.get("files")
        if (manifest.get("version") != MANIFEST_VERSION or not isinstance(generation, str)
                or not re.fullmatch(r"[0-9a-f]{32}", generation) or not isinstance(files, list)
                or len(files) > MAX_MANIFEST_FILES):
            raise StorageError("The active knowledge-artifact manifest is invalid.")
        generation_prefix = f"{self.prefix}/generations/{generation}/"
        entries: list[_ManifestFile] = []
        seen: set[str] = set()
        for item in files:
            if not isinstance(item, dict):
                raise StorageError("The active knowledge-artifact manifest is invalid.")
            relative = item.get("path")
            path = self._allowed_path(relative)
            key, size, digest = item.get("key"), item.get("size"), item.get("sha256")
            if (relative in seen or key != generation_prefix + path.as_posix()
                    or not isinstance(size, int) or size < 0
                    or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
                raise StorageError("The active knowledge-artifact manifest is invalid.")
            seen.add(relative)
            entries.append(_ManifestFile(relative, key, size, digest))
        if not any(item.path in {"index/chunks.jsonl", "index_fast/chunks.jsonl"} for item in entries):
            raise StorageError("The active generation does not contain a retrieval index.")
        return generation, entries

    def materialize_active(self) -> dict[str, Any]:
        """Download and verify the active generation before atomically replacing local artifacts."""
        generation, entries = self._load_manifest()
        staging = self.data_root / ".staging" / f"cloud-sync-{uuid.uuid4().hex}"
        staged: list[tuple[Path, Path]] = []
        replaced: list[tuple[Path, Path | None]] = []
        try:
            for item in entries:
                relative = self._allowed_path(item.path)
                temp = staging.joinpath(*relative.parts)
                temp.parent.mkdir(parents=True, exist_ok=True)
                self._client_call("download", lambda item=item, temp=temp: self._client.download_file(
                    self.bucket, item.key, str(temp),
                ))
                size, digest = _file_digest(temp)
                if size != item.size or digest != item.sha256:
                    raise StorageError("A downloaded knowledge artifact failed its integrity check.")
                target = self.data_root.joinpath(*relative.parts).resolve()
                if not target.is_relative_to(self.data_root):
                    raise StorageError("The active manifest contains a path outside the data directory.")
                staged.append((temp, target))

            backup_root = staging / "previous"
            try:
                for index, (temp, target) in enumerate(staged):
                    target.parent.mkdir(parents=True, exist_ok=True)
                    backup: Path | None = None
                    if target.exists():
                        backup = backup_root / str(index)
                        backup.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(target, backup)
                    os.replace(temp, target)
                    replaced.append((target, backup))
            except OSError:
                for target, backup in reversed(replaced):
                    try:
                        if backup is not None and backup.exists():
                            os.replace(backup, target)
                        elif target.exists():
                            target.unlink()
                    except OSError:
                        _LOGGER.error("Could not restore a local artifact after sync failure.")
                raise
        except StorageError:
            raise
        except Exception as exc:
            _LOGGER.error("Artifact materialization failed (error_type=%s).", type(exc).__name__)
            raise StorageError("Could not materialize the active knowledge artifacts.") from None
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
        self._current_generation = generation
        return {"backend": "r2", "generation": generation, "files": len(entries)}


def _file_digest(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            size += len(block)
            digest.update(block)
    return size, digest.hexdigest()


def storage_backend() -> str:
    configured = os.getenv("STIF_STORAGE_BACKEND", "local").strip().lower() or "local"
    if configured in {"local", "r2", "s3"}:
        return "r2" if configured in {"r2", "s3"} else "local"
    raise StorageConfigurationError("STIF_STORAGE_BACKEND must be 'local' or 'r2'.")


def get_storage() -> ArtifactStorage:
    """Return the configured adapter; explicit remote selection never falls back to local."""
    global _LOCAL_STORAGE
    backend = storage_backend()
    if backend == "local":
        if _LOCAL_STORAGE is None:
            _LOCAL_STORAGE = LocalArtifactStorage()
        return _LOCAL_STORAGE

    bucket = os.getenv("STIF_STORAGE_BUCKET", "").strip()
    endpoint = os.getenv("STIF_STORAGE_ENDPOINT", "").strip()
    access_key = os.getenv("STIF_STORAGE_ACCESS_KEY_ID", "").strip()
    secret_key = os.getenv("STIF_STORAGE_SECRET_ACCESS_KEY", "").strip()
    prefix = os.getenv("STIF_STORAGE_PREFIX", "stif-campus-ai").strip("/")
    region = os.getenv("STIF_STORAGE_REGION", "auto").strip() or "auto"
    if not bucket or not endpoint or not access_key or not secret_key:
        raise StorageConfigurationError("R2 requires STIF_STORAGE_BUCKET, STIF_STORAGE_ENDPOINT, and private access credentials.")
    try:
        parsed_endpoint = urlsplit(endpoint)
        _ = parsed_endpoint.port
        endpoint_valid = (parsed_endpoint.scheme == "https" and bool(parsed_endpoint.hostname)
                          and not parsed_endpoint.username and not parsed_endpoint.password
                          and not parsed_endpoint.path and not parsed_endpoint.query and not parsed_endpoint.fragment)
    except ValueError:
        endpoint_valid = False
    if not endpoint_valid or not re.fullmatch(r"[A-Za-z0-9/_-]+", prefix):
        raise StorageConfigurationError("R2 storage endpoint or prefix is invalid.")
    cache_key = hashlib.sha256("\0".join((bucket, endpoint, access_key, secret_key, prefix, region)).encode()).hexdigest()
    if cache_key in _S3_STORAGE:
        return _S3_STORAGE[cache_key]
    try:
        import boto3
        from botocore.config import Config
        client = boto3.client(
            "s3", endpoint_url=endpoint, aws_access_key_id=access_key,
            aws_secret_access_key=secret_key, region_name=region,
            config=Config(connect_timeout=5, read_timeout=30, retries={"max_attempts": 3}),
        )
    except ImportError:
        raise StorageConfigurationError("R2 was selected but the pinned Boto3 dependency is unavailable.") from None
    except Exception:
        raise StorageConfigurationError("Could not configure the R2 storage client.") from None
    storage = S3ArtifactStorage(client, bucket=bucket, prefix=prefix)
    _S3_STORAGE[cache_key] = storage
    return storage
