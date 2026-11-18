"""Run the dataset through the existing retrieval pipeline (read-only) and score it."""

from __future__ import annotations

import contextlib
import hashlib
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

from evaluation.dataset import CATEGORIES, Dataset, EvalRecord
from evaluation.grounding import check_grounding
from evaluation.metrics import DEFAULT_KS, QuestionScore, aggregate, score_question
from evaluation.weakness import analyze_question, observe_question, summarize_weaknesses

SCHEMA_VERSION = 1
DEEP_LIMIT = 50


def bm25_backend() -> str:
    """'real' only when the installed rank_bm25 package is in use; else 'substitute'/'missing'."""
    module = sys.modules.get("rank_bm25")
    if module is None:
        try:
            import rank_bm25 as module  # type: ignore
        except ImportError:
            return "missing"
    if getattr(module, "__stub__", False) or not getattr(module, "__file__", None):
        return "substitute"
    return "real"


@contextlib.contextmanager
def serve_index_file(chunks_path: Path | None) -> Iterator[None]:
    """Point retrieval at ``chunks_path`` for the duration (files are only read).

    With ``None`` the normally configured index paths are used unchanged.
    """
    from api import retrieval

    if chunks_path is None:
        retrieval._reset_state_for_tests()
        yield
        return
    chunks_path = Path(chunks_path)
    saved = (retrieval.FAST_CHUNKS_PATH, retrieval.OLD_CHUNKS_PATH)
    retrieval.FAST_CHUNKS_PATH = chunks_path
    retrieval.OLD_CHUNKS_PATH = chunks_path.with_name("__no_such_index__.jsonl")
    retrieval._reset_state_for_tests()
    try:
        yield
    finally:
        retrieval.FAST_CHUNKS_PATH, retrieval.OLD_CHUNKS_PATH = saved
        retrieval._reset_state_for_tests()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _result_view(chunk: dict[str, Any]) -> dict[str, Any]:
    return {
        "chunk_id": chunk.get("chunk_id", ""),
        "doc_id": chunk.get("doc_id", ""),
        "url": chunk.get("url", ""),
        "title": chunk.get("title", ""),
        "score": chunk.get("retrieval_score"),
        "snippet": " ".join(str(chunk.get("text", "")).split())[:160],
    }


def run_retrieval_evaluation(
    dataset: Dataset,
    *,
    ks: Sequence[int] = DEFAULT_KS,
    retrieve_fn: Callable[..., list[dict[str, Any]]] | None = None,
    chunk_provider: Callable[[], list[dict[str, Any]]] | None = None,
    index_status: dict[str, Any] | None = None,
    answers: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Evaluate ``dataset``. Unverified questions are observed, never scored."""
    from api import retrieval

    retrieve_fn = retrieve_fn or retrieval.retrieve
    chunk_provider = chunk_provider or retrieval.load_chunks
    status = index_status if index_status is not None else retrieval.get_index_status()
    index_ready = bool(status.get("index_ready"))
    backend = bm25_backend()
    kmax = max(ks)

    warnings: list[str] = []
    if not index_ready:
        warnings.append("No index is available: no retrieval was executed and nothing was scored.")
    if backend != "real":
        warnings.append(
            f"BM25 backend is '{backend}', not the real rank_bm25 package: scores in this report "
            "must NOT be presented as real retrieval performance."
        )

    all_chunks = chunk_provider() if index_ready else []
    evaluated: list[dict[str, Any]] = []
    observed: list[dict[str, Any]] = []
    scores: list[QuestionScore] = []
    not_run: list[str] = []

    for record in dataset.records:
        if not index_ready:
            if record.is_retrieval_scorable:
                not_run.append(record.id)
            observed.append(_base(record) | {"retrieval_executed": False})
            continue
        deep = retrieve_fn(record.question, limit=max(DEEP_LIMIT, kmax))
        top = deep[:kmax]
        if record.is_retrieval_scorable:
            score = score_question(record, deep[:kmax])
            scores.append(score)
            evaluated.append(
                _base(record)
                | {
                    "expected_sources": list(record.expected_sources),
                    "expected_doc_ids": list(record.expected_doc_ids),
                    "ranks": list(score.ranks),
                    "first_relevant_rank": score.first_rank,
                    **{f"recall@{k}": score.recall_at(k) for k in ks},
                    **{f"hit@{k}": score.hit_at(k) for k in ks},
                    "reciprocal_rank": score.reciprocal_rank,
                    "top_results": [_result_view(c) for c in top],
                    "diagnostics": analyze_question(record, deep, all_chunks, kmax),
                }
            )
        else:
            entry = _base(record) | observe_question(top)
            entry["retrieval_executed"] = True
            entry["top_results"] = [_result_view(c) for c in top]
            observed.append(entry)

    by_category: dict[str, Any] = {}
    for cat in CATEGORIES:
        cat_scores = [s for s in scores if s.category == cat]
        cat_records = [r for r in dataset.records if r.category == cat]
        by_category[cat] = {
            "total_questions": len(cat_records),
            "evaluated": len(cat_scores),
            "not_evaluated": len(cat_records) - len(cat_scores),
            "metrics": aggregate(cat_scores, ks),
        }

    counts = {
        "total": len(dataset.records),
        "verified": sum(r.is_verified for r in dataset.records),
        "needs_ground_truth": sum(r.verification_status == "needs_ground_truth" for r in dataset.records),
        "unverified": sum(r.verification_status == "unverified" for r in dataset.records),
        "retrieval_scorable": sum(r.is_retrieval_scorable for r in dataset.records),
        "verified_unanswerable": sum(r.is_verified_unanswerable for r in dataset.records),
        "evaluated": len(scores),
        "not_run_index_unavailable": len(not_run),
    }
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": {"path": dataset.path, "sha256": dataset.sha256, **counts},
        "index": {
            "available": index_ready,
            "source": status.get("source"),
            "sha256": status.get("sha256"),
            "chunks": status.get("chunks_loaded"),
            "serving_index": status.get("serving_index"),
        },
        "environment": {
            "bm25_backend": backend,
            "valid_as_retrieval_performance": bool(index_ready and backend == "real"),
            "retrieval_code_sha256": _file_sha(Path(retrieval.__file__)),
        },
        "warnings": warnings,
        "ks": list(ks),
        "metrics": {"overall": aggregate(scores, ks), "by_category": by_category},
        "evaluated": evaluated,
        "unverified_or_unscored": observed,
        "weaknesses": summarize_weaknesses(evaluated),
    }
    if answers is not None:
        report["grounding"] = evaluate_grounding(dataset, answers, retrieve_fn=retrieve_fn if index_ready else None)
    return report


def evaluate_grounding(
    dataset: Dataset,
    answers: dict[str, dict[str, Any]],
    *,
    retrieve_fn: Callable[..., list[dict[str, Any]]] | None,
    limit: int = 5,
) -> dict[str, Any]:
    """Grounding checks for supplied answers (never calls an LLM).

    Evidence is taken from the answer entry when present, otherwise re-retrieved
    with the same pipeline. Runs for every question regardless of ground-truth
    status because it checks support by evidence, not correctness.
    """
    items, skipped = [], []
    for record in dataset.records:
        entry = answers.get(record.id)
        if entry is None:
            skipped.append(record.id)
            continue
        evidence = entry.get("evidence")
        if evidence is None:
            evidence = retrieve_fn(record.question, limit=limit) if retrieve_fn else []
        expect = record.expect_official_referral
        if record.is_verified_unanswerable:
            expect = True
        result = check_grounding(
            str(entry.get("answer", "")), evidence, question=record.question, expect_referral=expect
        )
        items.append({
            "id": record.id, "category": record.category, "mode": entry.get("mode"),
            "verdict": result.verdict, "is_referral": result.is_referral,
            "evidence_count": result.evidence_count,
            "findings": [f.__dict__ for f in result.findings],
        })
    verdicts = Counter(i["verdict"] for i in items)
    codes = Counter(f["code"] for i in items for f in i["findings"])
    from evaluation.grounding import DISCLAIMER
    return {
        "disclaimer": DISCLAIMER,
        "checked": len(items),
        "no_answer_supplied": skipped,
        "verdicts": dict(verdicts),
        "finding_codes": dict(codes),
        "items": items,
    }


def _base(record: EvalRecord) -> dict[str, Any]:
    return {
        "id": record.id, "question": record.question, "category": record.category,
        "verification_status": record.verification_status, "question_kind": record.question_kind,
        "candidate_sources": list(record.candidate_sources),
    }
