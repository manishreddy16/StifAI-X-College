"""Helpers for evaluation tests (synthetic data only)."""

from __future__ import annotations

import json
from pathlib import Path

from tests._support import write_chunks  # noqa: F401  (also sets sys.path / BM25 stub)


def rec(**kw):
    base = {"id": "T-001", "question": "What are the library timings?", "category": "General college information",
            "verification_status": "needs_ground_truth"}
    base.update(kw)
    return base


def verified(**kw):
    base = rec(answerable="yes", verification_status="verified", verified_by="tester",
               verified_on="2026-01-31", expected_sources=["https://example.test/library"])
    base.update(kw)
    return base


def write_dataset(path: Path, records: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


def chunk(url, title, text, doc_id=None, **extra):
    return {"chunk_id": f"{doc_id or url}-0", "doc_id": doc_id or url, "url": url, "title": title, "text": text, **extra}
