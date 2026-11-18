"""Shared helpers for the index publishing / reload tests (synthetic data only)."""

from __future__ import annotations

import json
import math
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _install_bm25_stub_if_missing() -> bool:
    """Provide a tiny BM25Okapi stand-in ONLY when ``rank_bm25`` is not installed.

    The stub exists so the reload/concurrency logic can be exercised in
    environments without the dependency. When the real package is present it
    is always used.
    """
    try:
        import rank_bm25  # noqa: F401
        return False
    except ImportError:
        pass

    class BM25Okapi:  # minimal, positive-score BM25
        def __init__(self, corpus, k1=1.5, b=0.75):
            self.corpus = [list(doc) for doc in corpus]
            self.k1, self.b = k1, b
            self.n = len(self.corpus)
            self.avgdl = (sum(len(d) for d in self.corpus) / self.n) if self.n else 0.0
            self.df: dict[str, int] = {}
            for doc in self.corpus:
                for term in set(doc):
                    self.df[term] = self.df.get(term, 0) + 1

        def get_scores(self, query):
            scores = []
            for doc in self.corpus:
                total = 0.0
                for term in query:
                    df = self.df.get(term, 0)
                    if not df:
                        continue
                    idf = math.log(1 + (self.n - df + 0.5) / (df + 0.5))
                    tf = doc.count(term)
                    denom = tf + self.k1 * (1 - self.b + self.b * len(doc) / (self.avgdl or 1))
                    total += idf * tf * (self.k1 + 1) / (denom or 1)
                scores.append(total)
            return scores

    module = types.ModuleType("rank_bm25")
    module.__stub__ = True  # lets the evaluator report 'substitute', never 'real'
    module.BM25Okapi = BM25Okapi
    sys.modules["rank_bm25"] = module
    return True


BM25_STUBBED = _install_bm25_stub_if_missing()


def make_chunks(marker: str, count: int = 8) -> list[dict]:
    """Synthetic chunks. ``marker`` appears in exactly two chunks of each index."""
    rows = []
    for i in range(count):
        extra = f"{marker} library timings and rules" if i < 2 else f"unrelated topic number {i} hostel mess"
        rows.append(
            {
                "chunk_id": f"{marker}-{i}",
                "doc_id": f"{marker}-doc-{i}",
                "title": f"{marker} page {i}",
                "url": f"https://example.test/{marker}/{i}",
                "text": f"Synthetic {marker} content {i}. {extra}.",
            }
        )
    return rows


def write_chunks(path: Path, rows: list[dict]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def stage(index_dir: Path, rows: list[dict] | None, raw: str | None = None) -> Path:
    """Create a staged candidate file the way builders do."""
    from ingestion.index_publisher import CHUNKS_FILENAME, new_staging_dir

    staging = new_staging_dir(index_dir)
    target = staging / CHUNKS_FILENAME
    if raw is not None:
        target.write_text(raw, encoding="utf-8")
    else:
        write_chunks(target, rows or [])
    return target
