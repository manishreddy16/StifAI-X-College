"""Retrieval metrics. Pure functions, no I/O.

Ranks are 1-based positions in the chunk list returned by the retrieval
pipeline. For a question with N expected sources:
  recall@k = (expected sources found within the first k chunks) / N
  hit@k    = 1 if at least one expected source is within the first k chunks
  RR       = 1 / rank of the first chunk from any expected source (0 if none)
MRR is the mean RR. Only questions with verified ground truth may be passed in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from evaluation.dataset import EvalRecord, normalize_url

DEFAULT_KS = (1, 3, 5)


@dataclass(frozen=True)
class QuestionScore:
    id: str
    category: str
    n_expected: int
    ranks: tuple[int | None, ...]  # best rank per expected item, None = not retrieved
    first_rank: int | None

    def recall_at(self, k: int) -> float:
        found = sum(1 for r in self.ranks if r is not None and r <= k)
        return found / self.n_expected

    def hit_at(self, k: int) -> float:
        return 1.0 if self.first_rank is not None and self.first_rank <= k else 0.0

    @property
    def reciprocal_rank(self) -> float:
        return 1.0 / self.first_rank if self.first_rank else 0.0


def expected_items(record: EvalRecord) -> list[tuple[str, str]]:
    return [("url", normalize_url(u)) for u in record.expected_sources] + [
        ("doc_id", d) for d in record.expected_doc_ids
    ]


def chunk_matches(chunk: dict[str, Any], item: tuple[str, str]) -> bool:
    kind, value = item
    if kind == "url":
        return normalize_url(str(chunk.get("url", ""))) == value
    return str(chunk.get("doc_id", "")) == value


def score_question(record: EvalRecord, results: Sequence[dict[str, Any]]) -> QuestionScore:
    items = expected_items(record)
    if not items:
        raise ValueError(f"{record.id}: no expected sources; cannot score")
    ranks: list[int | None] = []
    for item in items:
        rank = next((i for i, c in enumerate(results, start=1) if chunk_matches(c, item)), None)
        ranks.append(rank)
    found = [r for r in ranks if r is not None]
    return QuestionScore(record.id, record.category, len(items), tuple(ranks), min(found) if found else None)


def aggregate(scores: Iterable[QuestionScore], ks: Sequence[int] = DEFAULT_KS) -> dict[str, Any]:
    """Mean metrics. With no scored questions every metric is ``None`` (never 0)."""
    scores = list(scores)
    out: dict[str, Any] = {"n": len(scores)}
    for k in ks:
        out[f"recall@{k}"] = sum(s.recall_at(k) for s in scores) / len(scores) if scores else None
    for k in ks:
        out[f"hit@{k}"] = sum(s.hit_at(k) for s in scores) / len(scores) if scores else None
    out["mrr"] = sum(s.reciprocal_rank for s in scores) / len(scores) if scores else None
    return out
