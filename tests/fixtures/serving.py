"""Helpers that point api.retrieval at a chosen chunks file without touching real data."""

from __future__ import annotations

import contextlib
import json
import tempfile
from pathlib import Path
from unittest import mock

from api import retrieval


def write_jsonl(path: Path, rows) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return path


@contextlib.contextmanager
def serving(chunks_path: Path, *, old_path: Path | None = None):
    """Serve ``chunks_path`` as the fast index (and ``old_path`` as the fallback index)."""
    none_path = Path(chunks_path).with_name("__no_such_index__.jsonl")
    with mock.patch.object(retrieval, "FAST_CHUNKS_PATH", Path(chunks_path)), \
            mock.patch.object(retrieval, "OLD_CHUNKS_PATH", Path(old_path) if old_path else none_path):
        retrieval._reset_state_for_tests()
        try:
            yield retrieval
        finally:
            retrieval._reset_state_for_tests()


@contextlib.contextmanager
def tmpdir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)
