"""Diagnostics that explain *why* a verified question ranked poorly.

Flags are measurements, not fixes. They only run on questions with verified
ground truth; unverified questions get neutral observations (no relevance claim).
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Sequence

from evaluation.dataset import EvalRecord
from evaluation.metrics import chunk_matches, expected_items
from evaluation.dataset import normalize_url


def _tokens(text: str) -> list[str]:
    from api import retrieval

    return retrieval._tokens(text)


def observe_question(top: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Neutral observations for questions without ground truth (no relevance judgement)."""
    urls = [normalize_url(str(c.get("url", ""))) for c in top]
    distinct = len(set(urls))
    return {
        "results_returned": len(top),
        "no_results": not top,
        "distinct_urls": distinct,
        "diversity_ratio": round(distinct / len(top), 3) if top else None,
    }


def analyze_question(
    record: EvalRecord,
    deep_results: Sequence[dict[str, Any]],
    all_chunks: Sequence[dict[str, Any]],
    top_k: int,
) -> dict[str, Any]:
    items = expected_items(record)
    top = list(deep_results[:top_k])
    query_tokens = set(_tokens(record.question))
    flags: list[str] = []
    info: dict[str, Any] = {}

    expected_chunks = [c for c in all_chunks if any(chunk_matches(c, it) for it in items)]
    info["expected_source_chunks_in_index"] = len(expected_chunks)

    def rank_of(results: Sequence[dict[str, Any]]) -> int | None:
        return next((i for i, c in enumerate(results, 1) if any(chunk_matches(c, it) for it in items)), None)

    top_rank = rank_of(top)
    deep_rank = rank_of(deep_results)
    info["first_rank_top_k"] = top_rank
    info["first_rank_deep"] = deep_rank

    if top_rank is None:
        flags.append("relevant_missing_from_top_k")
        if not expected_chunks:
            flags.append("expected_source_absent_from_index")  # data/coverage issue, not scoring
        elif deep_rank is not None:
            flags.append("relevant_ranked_below_top_k")
        else:
            flags.append("relevant_not_retrieved_at_all")

    # Irrelevant chunks ranked above the first relevant one (or all of top-k on a miss).
    limit = (top_rank - 1) if top_rank else len(top)
    above = [c for c in top[:limit] if not any(chunk_matches(c, it) for it in items)]
    if above and (top_rank is None or top_rank > 1):
        flags.append("irrelevant_ranked_above_relevant")
        info["outranking"] = [
            {"url": c.get("url", ""), "title": c.get("title", ""), "score": c.get("retrieval_score")}
            for c in above
        ]

    # Title matching.
    if expected_chunks and above:
        exp_title_overlap = max(len(query_tokens & set(_tokens(str(c.get("title", ""))))) for c in expected_chunks)
        above_title_overlap = max(len(query_tokens & set(_tokens(str(c.get("title", ""))))) for c in above)
        info["title_overlap"] = {"expected": exp_title_overlap, "outranking": above_title_overlap}
        if above_title_overlap > exp_title_overlap:
            flags.append("outranked_by_better_title_match")
        elif exp_title_overlap == 0:
            flags.append("expected_title_shares_no_query_terms")

    # Query terminology vs expected-source vocabulary.
    if expected_chunks:
        vocab: set[str] = set()
        for c in expected_chunks:
            vocab |= set(_tokens(f"{c.get('title', '')} {c.get('text', '')}"))
        missing = sorted(query_tokens - vocab)
        info["query_terms_absent_from_expected_source"] = missing
        if query_tokens and len(missing) / len(query_tokens) >= 0.5 and top_rank != 1:
            flags.append("query_terminology_mismatch")

    # Numerical / table-like content.
    numeric_kw = any(re.search(r"\d", k) for k in record.expected_keywords)
    if expected_chunks:
        text = " ".join(str(c.get("text", "")) for c in expected_chunks)
        digit_ratio = sum(ch.isdigit() for ch in text) / max(1, len(text))
        tabular = text.count("|") + text.count("\t") >= 5
        info["expected_digit_ratio"] = round(digit_ratio, 3)
        if (numeric_kw or digit_ratio > 0.12 or tabular) and top_rank != 1:
            flags.append("numeric_or_table_content_not_top_ranked")

    # Source diversity within top-k.
    urls = [normalize_url(str(c.get("url", ""))) for c in top]
    if top:
        counts = Counter(urls)
        info["distinct_urls_in_top_k"] = len(counts)
        info["top_url_share"] = round(counts.most_common(1)[0][1] / len(top), 3)
        if len(top) >= 3 and (len(counts) / len(top) <= 0.5):
            flags.append("low_source_diversity")
    return {"flags": flags, **info}


def summarize_weaknesses(evaluated: Sequence[dict[str, Any]]) -> dict[str, Any]:
    by_flag: dict[str, list[str]] = defaultdict(list)
    by_cat: dict[str, Counter] = defaultdict(Counter)
    for entry in evaluated:
        for flag in entry["diagnostics"]["flags"]:
            by_flag[flag].append(entry["id"])
            by_cat[entry["category"]][flag] += 1
    return {
        "questions_analyzed": len(evaluated),
        "flag_counts": {f: len(ids) for f, ids in sorted(by_flag.items())},
        "flag_question_ids": {f: ids for f, ids in sorted(by_flag.items())},
        "by_category": {c: dict(v) for c, v in sorted(by_cat.items())},
        "note": "Flags are diagnostics for human review; no scoring change is implied by them alone.",
    }
