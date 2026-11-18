"""JSON/Markdown report writing and baseline comparison."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

METRIC_KEYS = ("recall@1", "recall@3", "recall@5", "hit@1", "hit@3", "hit@5", "mrr")


def _fmt(value: Any) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _cell(text: Any) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def render_markdown(report: dict[str, Any]) -> str:
    d, idx, env = report["dataset"], report["index"], report["environment"]
    ks = report["ks"]
    cols = [f"recall@{k}" for k in ks] + [f"hit@{k}" for k in ks] + ["mrr"]
    out = ["# SVCE retrieval evaluation report", "", f"Generated: {report['generated_at']}", ""]
    if report["warnings"]:
        out += ["## Warnings", ""] + [f"- **{w}**" for w in report["warnings"]] + [""]
    out += [
        "## Run context", "",
        f"- Dataset: `{d['path']}` (sha256 `{d['sha256'][:12]}`)",
        f"- Index available: {idx['available']}; source: `{idx['source']}`; chunks: {idx['chunks']}; "
        f"sha256: `{(idx['sha256'] or 'n/a')[:12]}`",
        f"- BM25 backend: **{env['bm25_backend']}**; valid as real retrieval performance: "
        f"**{env['valid_as_retrieval_performance']}**",
        f"- retrieval.py sha256: `{env['retrieval_code_sha256'][:12]}`", "",
        "## Question counts", "",
        "| Measure | Count |", "|---|---|",
        f"| Total questions | {d['total']} |",
        f"| Verified ground truth | {d['verified']} |",
        f"| needs_ground_truth | {d['needs_ground_truth']} |",
        f"| unverified | {d['unverified']} |",
        f"| Scorable for retrieval (verified, answerable, has expected sources) | {d['retrieval_scorable']} |",
        f"| Verified unanswerable (abstention expected) | {d['verified_unanswerable']} |",
        f"| **Evaluated (scored)** | **{d['evaluated']}** |",
        f"| Scorable but not run (no index) | {d['not_run_index_unavailable']} |", "",
        "Unverified questions are **not** counted as successes or failures.", "",
        "## Metrics (evaluated questions only)", "",
        "| Scope | n | " + " | ".join(cols) + " |", "|---|---|" + "---|" * len(cols),
    ]
    ov = report["metrics"]["overall"]
    out.append(f"| Overall | {ov['n']} | " + " | ".join(_fmt(ov.get(c)) for c in cols) + " |")
    for cat, info in report["metrics"]["by_category"].items():
        m = info["metrics"]
        out.append(
            f"| {cat} ({info['evaluated']} of {info['total_questions']} evaluated) | {m['n']} | "
            + " | ".join(_fmt(m.get(c)) for c in cols) + " |"
        )
    out += ["", "`n/a` means no verified question in that scope was evaluated (not zero performance).", ""]

    out += ["## Evaluated questions", ""]
    if report["evaluated"]:
        out += ["| ID | Category | First relevant rank | RR | Flags |", "|---|---|---|---|---|"]
        for e in report["evaluated"]:
            out.append(
                f"| {e['id']} | {_cell(e['category'])} | {e['first_relevant_rank'] or 'not in top-k'} | "
                f"{e['reciprocal_rank']:.3f} | {_cell(', '.join(e['diagnostics']['flags']) or '-')} |"
            )
    else:
        out.append("_None. Add verified ground truth to the dataset (see evaluation/dataset/README.md)._")

    out += ["", "## Weakness diagnostics (verified questions only)", ""]
    w = report["weaknesses"]
    if w["flag_counts"]:
        out += ["| Flag | Questions | IDs |", "|---|---|---|"]
        for flag, n in w["flag_counts"].items():
            out.append(f"| {flag} | {n} | {', '.join(w['flag_question_ids'][flag])} |")
    else:
        out.append("_No flags (or no evaluated questions)._")

    un = report["unverified_or_unscored"]
    out += ["", f"## Unverified / unscored questions ({len(un)}) — observations only", ""]
    out += ["| ID | Category | Status | Kind | Results | Distinct URLs |", "|---|---|---|---|---|---|"]
    for u in un:
        out.append(
            f"| {u['id']} | {_cell(u['category'])} | {u['verification_status']} | {u['question_kind']} | "
            f"{u.get('results_returned', 'not run')} | {u.get('distinct_urls', '-')} |"
        )

    g = report.get("grounding")
    if g:
        out += ["", "## Answer grounding (deterministic checks)", "", f"_{g['disclaimer']}_", "",
                f"- Answers checked: {g['checked']}; verdicts: {g['verdicts']}",
                f"- Finding codes: {g['finding_codes']}"]
        for item in g["items"]:
            if item["findings"]:
                out.append(f"- **{item['id']}** ({item['verdict']}): " +
                           "; ".join(f"{f['code']}: {f['detail']}" for f in item["findings"]))
    return "\n".join(out) + "\n"


def write_reports(report: dict[str, Any], out_dir: str | Path, name: str | None = None) -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = name or "retrieval_eval_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path, md_path = out_dir / f"{stem}.json", out_dir / f"{stem}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def compare_reports(base: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Before/after comparison. Warns when the runs are not like-for-like."""
    caveats = []
    if base["dataset"]["sha256"] != new["dataset"]["sha256"]:
        caveats.append("Dataset differs between runs.")
    if base["index"]["sha256"] != new["index"]["sha256"]:
        caveats.append("Index content differs between runs; deltas may reflect data, not scoring.")
    for label, rep in (("baseline", base), ("new", new)):
        if not rep["environment"]["valid_as_retrieval_performance"]:
            caveats.append(f"The {label} run is not valid as real retrieval performance.")
    if base["environment"]["retrieval_code_sha256"] == new["environment"]["retrieval_code_sha256"]:
        caveats.append("retrieval.py is identical in both runs.")
    deltas = {}
    for key in METRIC_KEYS:
        b, n = base["metrics"]["overall"].get(key), new["metrics"]["overall"].get(key)
        deltas[key] = {"baseline": b, "new": n, "delta": None if b is None or n is None else round(n - b, 6)}
    b_rank = {e["id"]: e["first_relevant_rank"] for e in base["evaluated"]}
    changes = []
    for e in new["evaluated"]:
        if e["id"] in b_rank and b_rank[e["id"]] != e["first_relevant_rank"]:
            changes.append({"id": e["id"], "baseline_rank": b_rank[e["id"]], "new_rank": e["first_relevant_rank"]})
    return {
        "caveats": caveats, "overall": deltas, "rank_changes": changes,
        "evaluated": {"baseline": base["metrics"]["overall"]["n"], "new": new["metrics"]["overall"]["n"]},
    }


def render_comparison_markdown(cmp: dict[str, Any]) -> str:
    out = ["# Baseline comparison", ""]
    out += [f"- **Caveat:** {c}" for c in cmp["caveats"]] or ["- No caveats."]
    out += ["", f"Evaluated questions: baseline {cmp['evaluated']['baseline']}, new {cmp['evaluated']['new']}", "",
            "| Metric | Baseline | New | Delta |", "|---|---|---|---|"]
    for k, v in cmp["overall"].items():
        out.append(f"| {k} | {_fmt(v['baseline'])} | {_fmt(v['new'])} | {_fmt(v['delta'])} |")
    out += ["", "## Per-question rank changes", ""]
    out += [f"- {c['id']}: {c['baseline_rank']} -> {c['new_rank']}" for c in cmp["rank_changes"]] or ["_None._"]
    return "\n".join(out) + "\n"
