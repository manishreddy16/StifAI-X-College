"""Safe publishing of ``chunks.jsonl`` indexes.

Builders write a candidate index into a *staging* directory. Nothing touches
the live index until the candidate has been validated. Publishing is a single
``os.replace`` of the staged file onto ``<index_dir>/chunks.jsonl``, which is
atomic on the same filesystem, so readers see either the old file or the new
file, never a partial one. The previous file is copied to
``<index_dir>/.backups/`` first so it can be restored with ``rollback_index``.

Standard library only, so both the API and the ingestion scripts can use it.

Layout (existing index paths are unchanged)::

    data/index/chunks.jsonl            <- live file the API reads
    data/index/.backups/chunks-*.jsonl <- previous versions (newest kept)
    data/index/.last_publish.json      <- outcome of the most recent attempt
    data/.staging/index-<ts>-<id>/     <- temporary build area

CLI::

    python -m ingestion.index_publisher status --target fast
    python -m ingestion.index_publisher list-backups --target index
    python -m ingestion.index_publisher rollback --target fast [--backup NAME]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

CHUNKS_FILENAME = "chunks.jsonl"
BACKUP_DIRNAME = ".backups"
STATUS_FILENAME = ".last_publish.json"
LOCK_FILENAME = ".publish.lock"

DEFAULT_MIN_CHUNKS = 1
DEFAULT_MAX_INVALID_RATIO = 0.10
# A new index smaller than this fraction of the live one is treated as a
# probable failed/partial build unless the caller explicitly allows shrinking.
DEFAULT_MIN_SIZE_RATIO = 0.5
DEFAULT_KEEP_BACKUPS = 5
STALE_LOCK_SECONDS = 30 * 60

_REPLACE_RETRIES = 8
_REPLACE_RETRY_DELAY = 0.15


class IndexValidationError(Exception):
    """The candidate index is not acceptable for publishing."""


class IndexPublishError(Exception):
    """Publishing could not be completed.

    ``live_modified`` is True only if the live file was changed and could not
    be restored (never the case for validation rejections).
    """

    def __init__(self, message: str, *, live_modified: bool = False) -> None:
        super().__init__(message)
        self.live_modified = live_modified


@dataclass
class ValidationResult:
    path: str
    total_lines: int
    valid_chunks: int
    invalid_lines: int
    size_bytes: int
    sha256: str


@dataclass
class PublishResult:
    status: str  # "published" | "rolled_back"
    index_dir: str
    chunks: int
    sha256: str
    previous_chunks: int | None
    backup: str | None
    published_at: str


# ----------------------------------------------------------------- reading


def read_chunks(path: Path) -> tuple[list[dict[str, Any]], int, int]:
    """Parse a chunks.jsonl file.

    Returns ``(valid_chunks, invalid_line_count, non_blank_line_count)``.
    A chunk is valid when the line is a JSON object with a non-empty string
    ``text``. This is the single definition of "valid" shared by the API
    loader and the publisher so they can never disagree.
    """
    chunks: list[dict[str, Any]] = []
    invalid = 0
    total = 0
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            total += 1
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                invalid += 1
                continue
            if not isinstance(item, dict):
                invalid += 1
                continue
            text = item.get("text", "")
            if not isinstance(text, str) or not text.strip():
                invalid += 1
                continue
            chunks.append(item)
    return chunks, invalid, total


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_chunks_file(
    path: Path,
    *,
    min_chunks: int = DEFAULT_MIN_CHUNKS,
    max_invalid_ratio: float = DEFAULT_MAX_INVALID_RATIO,
) -> ValidationResult:
    """Validate a candidate chunks file; raise ``IndexValidationError``."""
    path = Path(path)
    if not path.is_file():
        raise IndexValidationError(f"Index file not found: {path}")
    try:
        chunks, invalid, total = read_chunks(path)
    except UnicodeDecodeError as exc:
        raise IndexValidationError(f"Index file is not valid UTF-8: {exc}") from exc
    except OSError as exc:
        raise IndexValidationError(f"Index file could not be read: {exc}") from exc

    if total == 0:
        raise IndexValidationError("Index file is empty.")
    if len(chunks) < max(1, min_chunks):
        raise IndexValidationError(
            f"Index has {len(chunks)} valid chunks; at least "
            f"{max(1, min_chunks)} required."
        )
    if invalid / total > max_invalid_ratio:
        raise IndexValidationError(
            f"{invalid} of {total} lines are invalid "
            f"(limit {max_invalid_ratio:.0%})."
        )
    return ValidationResult(
        path=str(path),
        total_lines=total,
        valid_chunks=len(chunks),
        invalid_lines=invalid,
        size_bytes=path.stat().st_size,
        sha256=sha256_of(path),
    )


# ----------------------------------------------------------------- staging


def new_staging_dir(index_dir: Path) -> Path:
    """Create a fresh staging directory next to ``index_dir``.

    It lives in the same parent (same filesystem) so the final replace is
    atomic.
    """
    index_dir = Path(index_dir)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    staging = (
        index_dir.parent / ".staging" / f"{index_dir.name}-{stamp}-{uuid.uuid4().hex[:8]}"
    )
    staging.mkdir(parents=True, exist_ok=False)
    return staging


def discard_staging(staging_dir: Path) -> None:
    shutil.rmtree(staging_dir, ignore_errors=True)


# ----------------------------------------------------------------- helpers


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _replace_with_retry(src: Path, dst: Path) -> None:
    """``os.replace`` with retries (Windows can briefly lock a file a reader has open)."""
    last: Exception | None = None
    for _ in range(_REPLACE_RETRIES):
        try:
            os.replace(src, dst)
            return
        except PermissionError as exc:
            last = exc
            time.sleep(_REPLACE_RETRY_DELAY)
    raise IndexPublishError(f"Could not replace {dst}: {last}") from last


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_name(path.name + f".{uuid.uuid4().hex[:6]}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _replace_with_retry(tmp, path)


def _record_status(index_dir: Path, payload: dict[str, Any]) -> None:
    try:
        _write_json_atomic(Path(index_dir) / STATUS_FILENAME, payload)
    except Exception:  # status is informational; never fail a publish over it
        pass


def read_publish_status(index_dir: Path) -> dict[str, Any]:
    path = Path(index_dir) / STATUS_FILENAME
    if not path.is_file():
        return {"status": "none", "message": "No publish attempt recorded."}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"status": "unreadable", "message": "Publish status file unreadable."}


@contextmanager
def _publish_lock(index_dir: Path) -> Iterator[None]:
    index_dir.mkdir(parents=True, exist_ok=True)
    lock_path = index_dir / LOCK_FILENAME
    for attempt in range(2):
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            try:
                age = time.time() - lock_path.stat().st_mtime
            except OSError:
                age = 0
            if attempt == 0 and age > STALE_LOCK_SECONDS:
                try:
                    lock_path.unlink()
                except OSError:
                    pass
                continue
            raise IndexPublishError(
                "Another index publish is in progress (lock file present)."
            )
    try:
        os.write(fd, f"pid={os.getpid()} at={_now()}".encode("utf-8"))
        os.close(fd)
        yield
    finally:
        try:
            lock_path.unlink()
        except OSError:
            pass


def list_backups(index_dir: Path) -> list[Path]:
    """Backups, oldest first (names embed a UTC timestamp)."""
    backup_dir = Path(index_dir) / BACKUP_DIRNAME
    if not backup_dir.is_dir():
        return []
    return sorted(backup_dir.glob("chunks-*.jsonl"), key=lambda p: p.name)


def _prune_backups(index_dir: Path, keep: int) -> None:
    backups = list_backups(index_dir)
    for old in backups[: max(0, len(backups) - max(1, keep))]:
        try:
            old.unlink()
        except OSError:
            pass


def _make_backup(live: Path, index_dir: Path, label: str = "") -> Path:
    backup_dir = index_dir / BACKUP_DIRNAME
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    suffix = f"-{label}" if label else ""
    target = backup_dir / f"chunks-{stamp}{suffix}.jsonl"
    tmp = target.with_name(target.name + ".tmp")
    shutil.copy2(live, tmp)
    os.replace(tmp, target)
    return target


def _previous_valid_count(live: Path) -> int | None:
    if not live.is_file():
        return None
    try:
        chunks, _, _ = read_chunks(live)
        return len(chunks)
    except Exception:
        return 0  # unreadable live file must not block a good replacement


# --------------------------------------------------------------- publishing


def publish_index(
    staged_file: Path,
    index_dir: Path,
    *,
    min_chunks: int = DEFAULT_MIN_CHUNKS,
    allow_shrink: bool = False,
    min_size_ratio: float = DEFAULT_MIN_SIZE_RATIO,
    max_invalid_ratio: float = DEFAULT_MAX_INVALID_RATIO,
    keep_backups: int = DEFAULT_KEEP_BACKUPS,
    cleanup_staging: bool = True,
) -> PublishResult:
    """Validate ``staged_file`` and atomically publish it as the live index.

    On any rejection or error the live index is left exactly as it was and
    ``IndexValidationError`` / ``IndexPublishError`` is raised. The outcome is
    recorded in ``<index_dir>/.last_publish.json``.
    """
    staged_file = Path(staged_file)
    index_dir = Path(index_dir)
    live = index_dir / CHUNKS_FILENAME
    staging_dir = staged_file.parent

    def fail(exc: Exception) -> Exception:
        _record_status(
            index_dir,
            {
                "status": "rejected" if isinstance(exc, IndexValidationError) else "failed",
                "reason": str(exc),
                "attempted_at": _now(),
                "live_index_modified": bool(getattr(exc, "live_modified", False)),
            },
        )
        if cleanup_staging:
            discard_staging(staging_dir)
        return exc

    try:
        validation = validate_chunks_file(
            staged_file,
            min_chunks=min_chunks,
            max_invalid_ratio=max_invalid_ratio,
        )
        with _publish_lock(index_dir):
            previous = _previous_valid_count(live)
            if (
                previous
                and not allow_shrink
                and validation.valid_chunks < previous * min_size_ratio
            ):
                raise IndexValidationError(
                    f"New index has {validation.valid_chunks} chunks versus "
                    f"{previous} in the live index (below {min_size_ratio:.0%}). "
                    "Looks like a partial build; pass allow_shrink / set "
                    "INDEX_ALLOW_SHRINK=1 if this is intended."
                )

            backup: Path | None = None
            if live.is_file():
                try:
                    backup = _make_backup(live, index_dir)
                except OSError as exc:
                    raise IndexPublishError(
                        f"Could not back up the live index; aborting: {exc}"
                    ) from exc

            _replace_with_retry(staged_file, live)

            if sha256_of(live) != validation.sha256:  # paranoia: undo on mismatch
                restored = False
                try:
                    if backup is not None:
                        _replace_with_retry(_copy_to_staging(backup, index_dir), live)
                        restored = True
                    else:
                        live.unlink()  # no previous index existed; do not leave a bad one
                        restored = True
                except Exception:  # noqa: BLE001
                    restored = False
                raise IndexPublishError(
                    "Published file failed post-publish verification"
                    + ("; previous state restored." if restored else "; RESTORE FAILED."),
                    live_modified=not restored,
                )

            _prune_backups(index_dir, keep_backups)
    except (IndexValidationError, IndexPublishError) as exc:
        raise fail(exc)
    except OSError as exc:
        raise fail(IndexPublishError(f"Publish failed: {exc}")) from exc

    result = PublishResult(
        status="published",
        index_dir=str(index_dir),
        chunks=validation.valid_chunks,
        sha256=validation.sha256,
        previous_chunks=previous,
        backup=str(backup) if backup else None,
        published_at=_now(),
    )
    _record_status(index_dir, {**asdict(result), "live_index_modified": True})
    if cleanup_staging:
        discard_staging(staging_dir)
    return result


def _copy_to_staging(source: Path, index_dir: Path) -> Path:
    staging = new_staging_dir(index_dir)
    target = staging / CHUNKS_FILENAME
    shutil.copy2(source, target)
    return target


def rollback_index(
    index_dir: Path,
    backup: str | Path | None = None,
    *,
    keep_backups: int = DEFAULT_KEEP_BACKUPS,
) -> PublishResult:
    """Restore a previous backup (latest by default) as the live index.

    The current live file is itself backed up first, so a rollback can be
    undone. The backup is validated before it is activated.
    """
    index_dir = Path(index_dir)
    live = index_dir / CHUNKS_FILENAME
    backups = list_backups(index_dir)
    if backup is None:
        if not backups:
            raise IndexPublishError(f"No backups available in {index_dir / BACKUP_DIRNAME}.")
        source = backups[-1]
    else:
        source = Path(backup)
        if not source.is_absolute():
            source = index_dir / BACKUP_DIRNAME / source.name
        if not source.is_file():
            raise IndexPublishError(f"Backup not found: {source}")

    validation = validate_chunks_file(source)
    staged = _copy_to_staging(source, index_dir)
    try:
        with _publish_lock(index_dir):
            previous = _previous_valid_count(live)
            safety = _make_backup(live, index_dir, "pre-rollback") if live.is_file() else None
            _replace_with_retry(staged, live)
            _prune_backups(index_dir, keep_backups)
    finally:
        discard_staging(staged.parent)

    result = PublishResult(
        status="rolled_back",
        index_dir=str(index_dir),
        chunks=validation.valid_chunks,
        sha256=validation.sha256,
        previous_chunks=previous,
        backup=str(safety) if safety else None,
        published_at=_now(),
    )
    _record_status(
        index_dir,
        {**asdict(result), "restored_from": source.name, "live_index_modified": True},
    )
    return result


# ------------------------------------------------------------- env settings


def settings_from_env() -> dict[str, Any]:
    """Publisher options from environment variables (all optional)."""

    def _int(name: str, default: int) -> int:
        try:
            return int(os.getenv(name, default))
        except ValueError:
            return default

    return {
        "min_chunks": _int("INDEX_MIN_CHUNKS", DEFAULT_MIN_CHUNKS),
        "keep_backups": _int("INDEX_KEEP_BACKUPS", DEFAULT_KEEP_BACKUPS),
        "allow_shrink": os.getenv("INDEX_ALLOW_SHRINK", "").strip().lower()
        in {"1", "true", "yes"},
    }


# --------------------------------------------------------------------- CLI

_ROOT = Path(__file__).resolve().parents[1]
_TARGETS = {"index": _ROOT / "data" / "index", "fast": _ROOT / "data" / "index_fast"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect or roll back a published index.")
    parser.add_argument("command", choices=["status", "list-backups", "rollback"])
    parser.add_argument("--target", choices=sorted(_TARGETS), required=True)
    parser.add_argument("--backup", default=None, help="Backup file name (default: latest).")
    args = parser.parse_args(argv)
    index_dir = _TARGETS[args.target]

    if args.command == "status":
        print(json.dumps(read_publish_status(index_dir), indent=2))
    elif args.command == "list-backups":
        for item in list_backups(index_dir):
            print(item.name)
    else:
        try:
            result = rollback_index(index_dir, args.backup)
        except (IndexPublishError, IndexValidationError) as exc:
            print(f"Rollback failed: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(asdict(result), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
