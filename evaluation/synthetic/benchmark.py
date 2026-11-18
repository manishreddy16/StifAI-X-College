"""Reproducible SYNTHETIC benchmark: legacy vs improved retrieval.

    python -m evaluation.synthetic.benchmark                # print markdown report
    python -m evaluation.synthetic.benchmark --json out.json

IMPORTANT - what these numbers are and are not:
* The corpus is fictional ("Northfield Institute of Technology") and the 38 queries
  were written AFTER the legacy defects were found. The results show that each
  defect is fixed and what each technique costs. They are NOT an estimate of
  accuracy on SVCE data. Real-data quality has not been measured (no production
  index was available) - run ``python -m diagnostics`` on the real index.
* Everything is deterministic: fixed corpus, fixed queries, default synonym groups
  (no env var or data file can change the result), real ``rank_bm25``.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rank_bm25 import BM25Okapi  # noqa: E402

from api import retrieval, retrieval_quality as rq  # noqa: E402
from evaluation.dataset import EvalRecord, VERIFIED  # noqa: E402
from evaluation.metrics import aggregate, score_question  # noqa: E402
from evaluation.synthetic.corpus import BASE, QUERIES, build_chunks_file  # noqa: E402
from tests.fixtures.serving import serving, write_jsonl  # noqa: E402

LIMIT = 5
TECHNIQUES = (
    "normalize_degrees", "unicode_tokens", "stemming", "synonyms",
    "field_weighting", "phrase_bonus", "relevance_floor", "diversity",
)
COVERAGE_SWEEP = (0.0, 0.05, 0.10, 0.15, 0.25, 0.35, 0.50)


class Runner:
    """Runs legacy or an improved-mode configuration against one served index."""

    def __init__(self, state: retrieval._RetrievalState):
        self.state = state
        self._cache: dict[rq.QualityConfig, retrieval._RetrievalState] = {}

    def _state_for(self, cfg: rq.QualityConfig) -> retrieval._RetrievalState:
        if cfg not in self._cache:
            qi = rq.QualityIndex.build(
                self.state.chunks, BM25Okapi, cfg, synonym_groups=rq.DEFAULT_SYNONYM_GROUPS
            )
            self._cache[cfg] = dataclasses.replace(self.state, quality=qi)
        return self._cache[cfg]

    def legacy(self, query: str) -> list[dict[str, Any]]:
        return retrieval._retrieve_legacy(self.state, query, LIMIT)

    def improved(self, cfg: rq.QualityConfig, query: str) -> list[dict[str, Any]]:
        return retrieval._retrieve_improved(self._state_for(cfg), query, LIMIT)


def _records() -> tuple[list[tuple[Any, EvalRecord]], list[Any]]:
    answerable, unanswerable = [], []
    for q in QUERIES:
        if q.answerable and q.expected:
            rec = EvalRecord(
                id=q.id, question=q.text, category=q.kind, answerable="yes",
                expected_sources=q.expected, verification_status=VERIFIED,
            )
            answerable.append((q, rec))
        elif not q.answerable:
            unanswerable.append(q)
    return answerable, unanswerable


def evaluate(fn) -> dict[str, Any]:
    """Metrics for one retrieval function ``fn(query_text) -> hits``."""
    answerable, unanswerable = _records()
    scores, per_query, zero_answerable = [], {}, 0
    for q, rec in answerable:
        hits = fn(q.text)
        score = score_question(rec, hits)
        scores.append(score)
        zero_answerable += 0 if hits else 1
        per_query[q.id] = {
            "kind": q.kind, "n_hits": len(hits), "first_rank": score.first_rank,
            "urls": [h["url"].replace(BASE, "") for h in hits],
        }
    false_answers = 0
    for q in unanswerable:
        hits = fn(q.text)
        false_answers += 1 if hits else 0
        per_query[q.id] = {
            "kind": q.kind, "n_hits": len(hits), "first_rank": None,
            "urls": [h["url"].replace(BASE, "") for h in hits],
        }
    agg = aggregate(scores)
    by_kind: dict[str, dict[str, Any]] = {}
    for kind in sorted({s.category for s in scores}):
        by_kind[kind] = aggregate([s for s in scores if s.category == kind])
    return {
        "answerable_n": len(scores),
        "hit@1": agg["hit@1"], "hit@3": agg["hit@3"], "hit@5": agg["hit@5"],
        "recall@3": agg["recall@3"], "recall@5": agg["recall@5"], "mrr": agg["mrr"],
        "answerable_returning_nothing": zero_answerable,
        "unanswerable_n": len(unanswerable),
        "unanswerable_returning_hits": false_answers,
        "by_kind": by_kind,
        "per_query": per_query,
    }


def latency(chunks: list[dict], copies: int, queries: list[str], repeats: int = 3) -> dict[str, Any]:
    """Median per-query latency on the synthetic chunks replicated ``copies`` times."""
    scaled = []
    for c in range(copies):
        for ch in chunks:
            scaled.append(dict(
                ch, chunk_id=f"{ch.get('chunk_id', 'x')}-c{c}", doc_id=f"{ch.get('doc_id', 'd')}-c{c}",
                url=f"{ch.get('url', '')}#c{c}" if ch.get("url") else "",
            ))
    out: dict[str, Any] = {"chunks": len(scaled)}
    with tempfile.TemporaryDirectory() as d:
        path = write_jsonl(Path(d) / "chunks.jsonl", scaled)
        with serving(path) as mod:
            t0 = time.perf_counter()
            state = mod._ensure_state(force=True)
            out["load_and_index_seconds"] = round(time.perf_counter() - t0, 3)
            for name in ("legacy", "improved"):
                times = []
                for _ in range(repeats):
                    for q in queries:
                        t = time.perf_counter()
                        mod.retrieve(q, limit=LIMIT, mode=name)
                        times.append((time.perf_counter() - t) * 1000)
                out[name] = {
                    "median_ms": round(statistics.median(times), 2),
                    "p95_ms": round(sorted(times)[int(0.95 * (len(times) - 1))], 2),
                }
            out["improved_index_ready"] = state.quality is not None
    return out


def run() -> dict[str, Any]:
    import rank_bm25

    with tempfile.TemporaryDirectory() as d:
        chunks_path = build_chunks_file(Path(d) / "syn")
        with serving(chunks_path) as mod:
            state = mod._ensure_state()
            assert state is not None and state.quality is not None
            runner = Runner(state)
            full = rq.QualityConfig()
            results: dict[str, Any] = {
                "meta": {
                    "kind": "SYNTHETIC (fictional institute; NOT SVCE data; NOT real-index results)",
                    "bm25_real": not getattr(rank_bm25, "__stub__", False),
                    "chunks": len(state.chunks),
                    "queries": len(QUERIES),
                    "limit": LIMIT,
                },
                "legacy": evaluate(runner.legacy),
                "improved": evaluate(lambda q: runner.improved(full, q)),
                "baseline_lexical": evaluate(lambda q: runner.improved(rq.QualityConfig.baseline_lexical(), q)),
                "ablation_one_off": {},
                "ablation_add_one": {},
                "min_coverage_sweep": {},
            }
            for tech in TECHNIQUES:
                cfg = dataclasses.replace(full, **{tech: False})
                results["ablation_one_off"][tech] = evaluate(lambda q, c=cfg: runner.improved(c, q))
            plain = rq.QualityConfig.baseline_lexical()
            for tech in TECHNIQUES:
                cfg = dataclasses.replace(plain, **{tech: True})
                results["ablation_add_one"][tech] = evaluate(lambda q, c=cfg: runner.improved(c, q))
            for value in COVERAGE_SWEEP:
                cfg = dataclasses.replace(full, min_coverage=value)
                results["min_coverage_sweep"][str(value)] = evaluate(lambda q, c=cfg: runner.improved(c, q))
            chunk_list = [dict(c) for c in state.chunks]
    qs = [q.text for q in QUERIES]
    results["latency"] = {
        "1x": latency(chunk_list, 1, qs),
        "10x": latency(chunk_list, 10, qs),
        "40x": latency(chunk_list, 40, qs, repeats=1),
    }
    return results


def _fmt(x) -> str:
    return "-" if x is None else f"{x:.3f}"


def markdown(res: dict[str, Any]) -> str:
    L: list[str] = []
    m = res["meta"]
    L.append(f"# Synthetic retrieval benchmark ({m['kind']})")
    L.append(f"{m['chunks']} chunks, {m['queries']} queries, top-{m['limit']}, real BM25: {m['bm25_real']}\n")
    head = "| variant | hit@1 | hit@3 | hit@5 | recall@3 | MRR | answerable with 0 hits | unanswerable returning hits |"
    sep = "|---|---|---|---|---|---|---|---|"

    def row(name, r):
        return (f"| {name} | {_fmt(r['hit@1'])} | {_fmt(r['hit@3'])} | {_fmt(r['hit@5'])} | {_fmt(r['recall@3'])} | "
                f"{_fmt(r['mrr'])} | {r['answerable_returning_nothing']}/{r['answerable_n']} | "
                f"{r['unanswerable_returning_hits']}/{r['unanswerable_n']} |")

    L += ["## Legacy vs improved", head, sep, row("legacy", res["legacy"]),
          row("plain BM25 (improved plumbing, all techniques off)", res["baseline_lexical"]),
          row("improved (all techniques)", res["improved"]), ""]
    L += ["## Ablation: improved with ONE technique switched off", head, sep]
    for tech, r in res["ablation_one_off"].items():
        L.append(row(f"- {tech}", r))
    L += ["", "## Ablation: plain BM25 plus ONE technique switched on", head, sep]
    for tech, r in res["ablation_add_one"].items():
        L.append(row(f"+ {tech}", r))
    L += ["", "## min_coverage sweep (improved)", head, sep]
    for v, r in res["min_coverage_sweep"].items():
        L.append(row(f"min_coverage={v}", r))
    L += ["", "## hit@1 by query kind (legacy -> improved)", "| kind | n | legacy | improved |", "|---|---|---|---|"]
    for kind, lg in res["legacy"]["by_kind"].items():
        im = res["improved"]["by_kind"][kind]
        L.append(f"| {kind} | {lg['n']} | {_fmt(lg['hit@1'])} | {_fmt(im['hit@1'])} |")
    miss = [f"{qid} ({v['kind']}, first_rank={v['first_rank']})"
            for qid, v in res["improved"]["per_query"].items()
            if v["kind"] not in ("off-topic", "unanswerable-topical") and v["first_rank"] != 1]
    wrong = [qid for qid, v in res["improved"]["per_query"].items()
             if v["kind"] in ("off-topic", "unanswerable-topical") and v["n_hits"]]
    L += ["", "Improved mode, answerable queries NOT ranked first: " + (", ".join(miss) or "none"),
          "Improved mode, unanswerable queries that still return hits: " + (", ".join(wrong) or "none")]
    L += ["", "## Latency (median / p95 ms per query, this sandbox, single thread)",
          "| chunks | index load+build s | legacy | improved |", "|---|---|---|---|"]
    for lat in res["latency"].values():
        L.append(f"| {lat['chunks']} | {lat['load_and_index_seconds']} | "
                 f"{lat['legacy']['median_ms']} / {lat['legacy']['p95_ms']} | "
                 f"{lat['improved']['median_ms']} / {lat['improved']['p95_ms']} |")
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", help="also write full results (incl. per-query) to this file")
    args = ap.parse_args(argv)
    res = run()
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    print(markdown(res))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
