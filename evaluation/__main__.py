"""CLI: python -m evaluation [options]. Read-only; no crawling; no LLM calls by default."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.dataset import DatasetError, load_dataset  # noqa: E402
from evaluation.report import (  # noqa: E402
    compare_reports, render_comparison_markdown, write_reports,
)
from evaluation.retrieval_eval import run_retrieval_evaluation, serve_index_file  # noqa: E402

DEFAULT_DATASET = ROOT / "evaluation" / "dataset" / "svce_eval_questions.jsonl"


def _load_answers(path: Path) -> dict:
    answers = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            item = json.loads(line)
            answers[str(item["id"])] = item
    return answers


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Evaluate SVCE retrieval and answer grounding (read-only).")
    p.add_argument("--dataset", default=str(DEFAULT_DATASET))
    p.add_argument("--chunks", default=None, help="Evaluate this chunks.jsonl instead of the configured index (read-only).")
    p.add_argument("--output-dir", default=str(ROOT / "evaluation" / "reports"))
    p.add_argument("--name", default=None, help="Report file stem.")
    p.add_argument("--answers", default=None, help="JSONL of {id, answer[, evidence, mode]} to grounding-check.")
    p.add_argument("--run-answers", action="store_true",
                   help="Generate answers with api.retrieval.answer_question (may call the configured LLM).")
    p.add_argument("--allow-llm-calls", action="store_true",
                   help="Required with --run-answers when an LLM is configured (paid calls).")
    p.add_argument("--save-baseline", default=None, metavar="LABEL", help="Also save the JSON report to evaluation/baselines/LABEL.json")
    p.add_argument("--compare", default=None, metavar="BASELINE_JSON")
    args = p.parse_args(argv)

    try:
        dataset = load_dataset(args.dataset)
    except DatasetError as exc:
        print("Invalid dataset:", file=sys.stderr)
        for err in exc.errors:
            print(f"  - {err}", file=sys.stderr)
        return 2

    try:
        import rank_bm25  # noqa: F401
    except ImportError:
        print("The 'rank_bm25' package is not installed, so retrieval cannot be evaluated. "
              "Install requirements-local.txt first (no substitute is used by the CLI).", file=sys.stderr)
        return 4

    answers = _load_answers(Path(args.answers)) if args.answers else None
    with serve_index_file(Path(args.chunks) if args.chunks else None):
        if args.run_answers:
            from api import retrieval
            if retrieval.llm_calls_configured() and not args.allow_llm_calls:
                print("An LLM is configured; --run-answers would make paid calls. "
                      "Re-run with --allow-llm-calls to confirm.", file=sys.stderr)
                return 3
            answers = {}
            for r in dataset.records:
                res = retrieval.answer_question(r.question)
                answers[r.id] = {"id": r.id, "answer": res["answer"], "mode": res.get("mode")}
        report = run_retrieval_evaluation(dataset, answers=answers)

    json_path, md_path = write_reports(report, args.output_dir, args.name)
    print(f"JSON report: {json_path}\nMarkdown report: {md_path}")
    print(f"Evaluated {report['dataset']['evaluated']} of {report['dataset']['total']} questions "
          f"({report['dataset']['verified']} verified).")
    for w in report["warnings"]:
        print("WARNING:", w)
    if args.save_baseline:
        base_dir = ROOT / "evaluation" / "baselines"
        base_dir.mkdir(parents=True, exist_ok=True)
        (base_dir / f"{args.save_baseline}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Baseline saved: evaluation/baselines/{args.save_baseline}.json")
    if args.compare:
        base = json.loads(Path(args.compare).read_text(encoding="utf-8"))
        cmp_md = render_comparison_markdown(compare_reports(base, report))
        cmp_path = Path(args.output_dir) / f"{json_path.stem}_comparison.md"
        cmp_path.write_text(cmp_md, encoding="utf-8")
        print(f"Comparison: {cmp_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
