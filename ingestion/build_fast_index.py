import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # allow `python ingestion/build_fast_index.py`
    sys.path.insert(0, str(ROOT))

from ingestion.index_publisher import (  # noqa: E402
    CHUNKS_FILENAME,
    IndexPublishError,
    IndexValidationError,
    discard_staging,
    new_staging_dir,
    publish_index,
    settings_from_env,
)

SOURCE_DIR = ROOT / "data" / "processed_fast"
INDEX_DIR = ROOT / "data" / "index_fast"
REPORT_DIR = ROOT / "data" / "reports"

CHUNK_SIZE = 1800
CHUNK_OVERLAP = 250


def clean_text(text):
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_text(text):
    chunks = []
    start = 0

    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))

        if end < len(text):
            boundary = max(
                text.rfind(". ", start, end),
                text.rfind("\n", start, end),
            )

            if boundary > start + CHUNK_SIZE // 2:
                end = boundary + 1

        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)

        if end >= len(text):
            break

        start = max(start + 1, end - CHUNK_OVERLAP)

    return chunks


def build_index(source_dir=None, index_dir=None, report_dir=None, **publish_options):
    """Build chunks into a staging directory, then validate and publish.

    The live ``index_dir/chunks.jsonl`` is only replaced after the staged
    build passes validation. Chunking and deduplication are unchanged.
    Raises IndexValidationError / IndexPublishError when nothing was published.
    """
    source_dir = Path(source_dir or SOURCE_DIR)
    index_dir = Path(index_dir or INDEX_DIR)
    report_dir = Path(report_dir or REPORT_DIR)
    report_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(source_dir.glob("*.json"))

    if not files:
        raise IndexValidationError(f"No JSON documents found in {source_dir}")

    staging_dir = new_staging_dir(index_dir)
    chunks_path = staging_dir / CHUNKS_FILENAME
    seen_chunks = set()
    document_stats = []
    total_chunks = 0
    duplicate_chunks = 0
    empty_documents = 0

    try:
        with chunks_path.open("w", encoding="utf-8") as output:
            for file in files:
                try:
                    doc = json.loads(file.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    print(f"SKIP {file.name}: {exc}")
                    continue

                text = clean_text(doc.get("text", ""))

                if not text:
                    empty_documents += 1
                    continue

                doc_id = doc.get("doc_id") or file.stem
                url = doc.get("url", "")
                title = doc.get("title", url or file.stem)

                chunks = split_text(text)
                written_for_document = 0

                for position, chunk in enumerate(chunks):
                    normalized = re.sub(r"\s+", " ", chunk).strip().casefold()
                    chunk_hash = hashlib.sha256(
                        normalized.encode("utf-8")
                    ).hexdigest()

                    if chunk_hash in seen_chunks:
                        duplicate_chunks += 1
                        continue

                    seen_chunks.add(chunk_hash)

                    record = {
                        "chunk_id": f"{doc_id}_{position:05d}",
                        "doc_id": doc_id,
                        "title": title,
                        "url": url,
                        "content_type": doc.get("content_type", ""),
                        "verification_status": doc.get(
                            "verification_status", "NEEDS_VERIFICATION"
                        ),
                        "text": chunk,
                    }

                    output.write(
                        json.dumps(record, ensure_ascii=False) + "\n"
                    )

                    total_chunks += 1
                    written_for_document += 1

                document_stats.append({
                    "doc_id": doc_id,
                    "title": title,
                    "url": url,
                    "characters": len(text),
                    "chunks_written": written_for_document,
                })

                if len(document_stats) % 50 == 0:
                    print(
                        f"Processed {len(document_stats)} documents; "
                        f"written {total_chunks} chunks",
                        flush=True,
                    )
    except BaseException:
        discard_staging(staging_dir)
        raise

    report = {
        "source_directory": str(source_dir),
        "documents_found": len(files),
        "documents_with_text": len(document_stats),
        "empty_documents": empty_documents,
        "unique_chunks_written": total_chunks,
        "duplicate_chunks_skipped": duplicate_chunks,
        "chunk_size_characters": CHUNK_SIZE,
        "chunk_overlap_characters": CHUNK_OVERLAP,
        "index_file": str(index_dir / CHUNKS_FILENAME),
        "documents": document_stats,
    }

    options = {**settings_from_env(), **publish_options}
    try:
        result = publish_index(chunks_path, index_dir, **options)
    except (IndexValidationError, IndexPublishError) as exc:
        # publish_index already removed the staging directory and left the
        # live index untouched. Record the failed attempt WITHOUT overwriting
        # the report that describes the live index.
        attempt = {
            **report,
            "status": "not_published",
            "published": False,
            "reason": str(exc),
            "attempted_at": datetime.now(timezone.utc).isoformat(),
        }
        (report_dir / "fast_index_last_attempt.json").write_text(
            json.dumps(attempt, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        raise

    report.update(
        status="published",
        published=True,
        published_at=result.published_at,
        previous_chunks=result.previous_chunks,
        backup=result.backup,
    )
    report_path = report_dir / "fast_index_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def main():
    try:
        report = build_index()
    except (IndexValidationError, IndexPublishError) as exc:
        print(f"\nINDEX NOT PUBLISHED: {exc}")
        print("The existing live index was left unchanged.")
        raise SystemExit(1)

    print("\nINDEX BUILD COMPLETE (published)")
    print("Documents found:", report["documents_found"])
    print("Documents with text:", report["documents_with_text"])
    print("Empty documents:", report["empty_documents"])
    print("Unique chunks:", report["unique_chunks_written"])
    print("Duplicate chunks skipped:", report["duplicate_chunks_skipped"])
    print("Index:", report["index_file"])
    print("Previous backup:", report["backup"])


if __name__ == "__main__":
    main()
