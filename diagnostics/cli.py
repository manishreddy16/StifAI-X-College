"""``python -m diagnostics`` - read-only retrieval diagnostic (see diagnostics/__init__.py)."""

from __future__ import annotations

import argparse
import contextlib
import importlib
import json
import os
import re
import socket
import sys
from pathlib import Path
from typing import Any
from unittest import mock

from diagnostics import EXIT_ERRORS, EXIT_OK, EXIT_USAGE, EXIT_WARNINGS
from diagnostics import checks

ROOT = Path(__file__).resolve().parents[1]
_SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)", re.I)
FAKE_LLM_ENV = {
    "OPENROUTER_API_KEY": "diagnostic-fake-key",
    "OPENROUTER_MODEL": "diagnostic-fake-model",
}


# ----------------------------------------------------------------------- environment


def import_retrieval(use_env: bool):
    """Import ``api.retrieval`` with ``load_dotenv`` neutralised unless ``use_env``.

    ``api.retrieval`` calls ``load_dotenv()`` at import time, which would read ``.env``
    (including LLM secrets). By default it is replaced with a no-op first.
    With ``--use-env`` the file is loaded, then every variable whose name looks like a
    secret is removed from this process so it can never reach the report.
    """
    state = {"dotenv_called": False, "already_imported": "api.retrieval" in sys.modules}
    if state["already_imported"]:  # only in tests/embedding: the import-time load_dotenv already ran
        return sys.modules["api.retrieval"], state
    if use_env:
        import dotenv

        real = dotenv.load_dotenv

        def load_and_scrub(*args, **kwargs):
            state["dotenv_called"] = True
            before = set(os.environ)
            result = real(*args, **kwargs)
            for name in list(os.environ):
                if name not in before and _SECRET_NAME.search(name):
                    del os.environ[name]
            return result

        patcher = mock.patch("dotenv.load_dotenv", load_and_scrub)
    else:
        patcher = mock.patch("dotenv.load_dotenv", lambda *a, **k: False)
    with patcher:
        module = importlib.import_module("api.retrieval")
    return module, state


@contextlib.contextmanager
def no_network():
    """Any socket connection attempt raises: the diagnostic can never reach a real service."""
    def blocked(self, *args, **kwargs):
        raise OSError("network access is disabled by the diagnostic")

    with mock.patch.object(socket.socket, "connect", blocked), \
            mock.patch.object(socket.socket, "connect_ex", blocked):
        yield


class FakeLLM:
    """Replaces ``requests.post``: records the payload and returns a canned completion."""

    def __init__(self):
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url, headers=None, json=None, timeout=None, **kwargs):
        import requests

        self.calls.append({"url": url, "payload": json})
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"choices": [{"message": {"content": "(diagnostic canned answer)"}}]}'
        return response


# ------------------------------------------------------------------------------ run


def collect(args: argparse.Namespace) -> dict[str, Any]:
    data_dir = Path(args.data_dir).resolve() if args.data_dir else ROOT / "data"
    before = checks.fingerprint_tree(data_dir)

    retrieval, env_state = import_retrieval(args.use_env)
    fast_path = data_dir / "index_fast" / "chunks.jsonl"
    old_path = data_dir / "index" / "chunks.jsonl"
    report: dict[str, Any] = {
        "tool": "python -m diagnostics",
        "read_only": True,
        "data_dir": str(data_dir),
        "dotenv_loaded": env_state["dotenv_called"],
        "api_retrieval_preimported": env_state["already_imported"],
        "network": "blocked",
        "claim": "Reports facts about the files found here. It does not measure answer accuracy.",
        "warnings": [],
        "errors": [],
    }
    warn, err = report["warnings"], report["errors"]

    # ---- candidates
    candidates = [("fast (data/index_fast)", fast_path), ("published (data/index)", old_path)]
    report["candidates"] = []
    for label, path in candidates:
        info = checks.describe_file(path)
        info["role"] = label
        report["candidates"].append(info)
    fast_info, old_info = report["candidates"]

    # ---- what the backend would serve (same loader as production)
    with mock.patch.object(retrieval, "FAST_CHUNKS_PATH", fast_path), \
            mock.patch.object(retrieval, "OLD_CHUNKS_PATH", old_path):
        retrieval._reset_state_for_tests()  # fresh process state; touches memory only
        status = retrieval.get_index_status()
        state = retrieval._ensure_state()
        report["serving"] = {k: status.get(k) for k in (
            "index_ready", "chunks_loaded", "source", "serving_index", "sha256", "serving_stale",
            "last_error", "retrieval_mode", "improved_index_ready", "improved_index_error")}
        report["serving"]["why"] = _why(status, fast_info, old_info)

        _health_warnings(report, fast_info, old_info, status)

        if state is not None and state.quality is not None:
            report["term_profile"] = checks.term_frequency_profile(state.quality)
            _profile_warnings(report)

        questions = list(args.questions_list)
        if state is None:
            err.append("NO_USABLE_INDEX: the backend would answer every question with 'index_unavailable'.")
            report["questions"] = []
            report["llm_flow"] = []
        else:
            report["questions"] = _compare_modes(retrieval, questions, args.top)
            _question_warnings(report)
            report["llm_flow"] = [] if args.no_llm_check else _llm_flow(retrieval, questions)
            _flow_warnings(report)
        retrieval._reset_state_for_tests()

    after = checks.fingerprint_tree(data_dir)
    report["read_only_verified"] = before == after
    if before != after:
        changed = sorted(set(before) ^ set(after) | {k for k in before if k in after and before[k] != after[k]})
        err.append(f"DATA_DIR_CHANGED: {changed[:5]} - the diagnostic must never change data. Investigate.")
    return report


def _why(status, fast_info, old_info) -> str:
    if not status["index_ready"]:
        return "No candidate could be loaded."
    if status["serving_index"] == "fast":
        extra = " (data/index also exists but is never served while the fast index is valid)" if old_info["exists"] else ""
        return "data/index_fast outranks data/index" + extra
    if fast_info["exists"]:
        return "data/index_fast exists but was rejected; fell back to data/index"
    return "only data/index exists"


def _health_warnings(report, fast_info, old_info, status):
    warn = report["warnings"]
    if not fast_info["exists"] and not old_info["exists"]:
        report["errors"].append("NO_INDEX_FILES: neither data/index_fast/chunks.jsonl nor data/index/chunks.jsonl exists.")
    for info in (fast_info, old_info):
        if not info["exists"]:
            continue
        name = info["role"]
        if info.get("readable") is False:
            warn.append(f"UNREADABLE_INDEX: {name}: {info.get('read_error')}")
            continue
        if info.get("valid_chunks", 0) == 0:
            warn.append(f"EMPTY_INDEX: {name} has no valid chunks.")
        if info.get("invalid_lines"):
            warn.append(f"INVALID_LINES: {name} has {info['invalid_lines']} invalid line(s) of {info['non_blank_lines']}.")
        if info.get("chunks_without_url"):
            warn.append(f"MISSING_URLS: {name}: {info['chunks_without_url']} chunk(s) have no URL, so they can never be cited as sources.")
        if info.get("chunks_without_title"):
            warn.append(f"MISSING_TITLES: {name}: {info['chunks_without_title']} chunk(s) have no title.")
        n = info.get("valid_chunks", 0)
        if n and info.get("duplicate_text_chunks", 0) / n > 0.05:
            warn.append(f"DUPLICATE_CHUNKS: {name}: {info['duplicate_text_chunks']} of {n} chunks repeat other chunks' text.")
        if 0 < n < 50:
            warn.append(f"SMALL_INDEX: {name} has only {n} chunks; improved mode's relevance floor behaves badly on tiny indexes (audit F12).")
    if fast_info["exists"] and old_info["exists"] and old_info["mtime"] > fast_info["mtime"] and status["serving_index"] == "fast":
        warn.append("PUBLISHED_INDEX_SHADOWED: data/index is NEWER than data/index_fast but the fast index is the one being served (audit F10). "
                    "Retire or refresh data/index_fast to serve the newer data.")
    if status["last_error"] and status["index_ready"]:
        warn.append(f"CANDIDATE_REJECTED: {status['last_error']}")
    if status["index_ready"] and not status["improved_index_ready"]:
        warn.append(f"IMPROVED_INDEX_NOT_BUILT: legacy scoring is used. {status['improved_index_error']}")
    if status["serving_stale"]:
        warn.append("SERVING_STALE: files changed on disk since the served index was built.")


def _profile_warnings(report):
    p = report["term_profile"]
    if p["non_distinctive_terms"]:
        top = ", ".join(f"{t['term']} ({t['share']:.0%})" for t in p["most_common_non_distinctive"][:6])
        report["warnings"].append(
            f"DOMINANT_TERMS: {p['non_distinctive_terms']} term(s) appear in more than {p['distinctive_max_df_share']:.0%} of chunks "
            f"and cannot count as 'distinctive' by body text alone (audit F12). Improved mode still answers when such a word is also in the page title/URL; "
            f"a question whose words are frequent in bodies and absent from titles/URLs is refused. "
            f"Most common: {top}.")


def _compare_modes(retrieval, questions: list[str], top: int) -> list[dict[str, Any]]:
    rows = []
    with no_network():
        for q in questions:
            row: dict[str, Any] = {"question": q}
            for mode in ("legacy", "improved"):
                hits = retrieval.retrieve(q, limit=max(top, 1), mode=mode)
                row[mode] = [
                    {"rank": i, "score": h.get("retrieval_score"), "coverage": h.get("retrieval_coverage"),
                     "url": h.get("url"), "title": h.get("title"), "snippet": checks.snippet(h.get("text"))}
                    for i, h in enumerate(hits, 1)
                ]
            leg, imp = row["legacy"], row["improved"]
            row["flags"] = []
            if leg and not imp:
                row["flags"].append("improved_returns_nothing_legacy_returns_hits")
            if imp and not leg:
                row["flags"].append("improved_returns_hits_legacy_returns_nothing")
            if leg and imp and leg[0]["url"] != imp[0]["url"]:
                row["flags"].append("top1_differs")
            rows.append(row)
    return rows


def _question_warnings(report):
    qs = report["questions"]
    refused = [r["question"] for r in qs if "improved_returns_nothing_legacy_returns_hits" in r["flags"]]
    if refused:
        report["warnings"].append(
            f"IMPROVED_REFUSES_{len(refused)}_QUESTION(S): improved returns nothing where legacy returned pages "
            f"(either noise removed or a false refusal - review these): {refused[:5]}")
    none_both = [r["question"] for r in qs if not r["legacy"] and not r["improved"]]
    if none_both and len(none_both) == len(qs):
        report["warnings"].append("NOTHING_RETRIEVED: no sample question returned any chunk in either mode.")


def _llm_flow(retrieval, questions: list[str]) -> list[dict[str, Any]]:
    """Run the full answer path with a fake LLM: shows exactly which pages would be sent."""
    rows = []
    fake = FakeLLM()
    with mock.patch.dict(os.environ, FAKE_LLM_ENV), mock.patch.object(retrieval.requests, "post", fake), no_network():
        for q in questions:
            before = len(fake.calls)
            result = retrieval.answer_question(q)
            called = len(fake.calls) > before
            context = fake.calls[-1]["payload"]["messages"][1]["content"] if called else ""
            ctx_urls = re.findall(r"^URL: (.*)$", context, flags=re.M)
            src_urls = [s.get("url") for s in result.get("sources", [])]
            rows.append({
                "question": q,
                "mode": result.get("mode"),
                "llm_called": called,
                "context_sources": context.count("[Source "),
                "context_chars": len(context),
                "context_urls": ctx_urls,
                "returned_source_urls": src_urls,
                "context_urls_not_cited": [u for u in ctx_urls if u and u not in src_urls],
                "empty_context_urls": sum(1 for u in ctx_urls if not u.strip() or u.strip() == "None"),
            })
    return rows


def _flow_warnings(report):
    flow = report["llm_flow"]
    no_cite = [r["question"] for r in flow if r["llm_called"] and not r["returned_source_urls"]]
    if no_cite:
        report["warnings"].append(f"ANSWER_WITHOUT_SOURCES: the LLM would be called but no source is returned for: {no_cite[:5]}")
    bad = [r["question"] for r in flow if r["empty_context_urls"]]
    if bad:
        report["warnings"].append(f"EMPTY_CONTEXT_URLS: evidence without a URL would be sent to the LLM for: {bad[:5]}")
    hindi = [r for r in flow if re.search(r"[\u0900-\u097f\u0c00-\u0c7f]", r["question"]) and r["mode"] == "insufficient_evidence"]
    if hindi:
        report["warnings"].append("INDIC_QUERY_NO_MATCH: Hindi/Telugu sample question(s) matched nothing; lexical retrieval cannot match across scripts.")


# ---------------------------------------------------------------------------- output


def render_text(report: dict[str, Any], top: int) -> str:
    out: list[str] = []
    add = out.append
    add("STIF Campus AI - retrieval diagnostic (READ-ONLY)")
    add(f"data dir : {report['data_dir']}")
    add(f".env read: {'yes (--use-env, secret-named variables removed)' if report['dotenv_loaded'] else 'no'}   network: {report['network']}")
    if report.get("api_retrieval_preimported"):
        add("note     : api.retrieval was already imported in this process, so .env handling could not be controlled.")
    add(f"note     : {report['claim']}")
    add("")
    add("== Index candidates ==")
    for c in report["candidates"]:
        add(f"- {c['role']}: {c['path']}")
        if not c["exists"]:
            add("    missing")
            continue
        add(f"    size {c['size_bytes']:,} B   modified {c['mtime_iso']}   sha256 {str(c.get('sha256'))[:16]}…")
        if c.get("readable") is False:
            add(f"    UNREADABLE: {c.get('read_error')}")
            continue
        tl = c["text_length"]
        add(f"    valid chunks {c['valid_chunks']} / lines {c['non_blank_lines']} (invalid {c['invalid_lines']})   distinct URLs {c['distinct_urls']}")
        add(f"    no url {c['chunks_without_url']}   no title {c['chunks_without_title']}   duplicate-text chunks {c['duplicate_text_chunks']}")
        add(f"    text length min/median/max {tl['min']}/{tl['median']}/{tl['max']}   non-ASCII letters {c['non_ascii_letter_share']:.1%}   Indic characters {c['indic_character_count']}")
    s = report["serving"]
    add("")
    add("== What the backend would serve ==")
    add(f"index_ready={s['index_ready']}  serving={s['serving_index']}  chunks={s['chunks_loaded']}  mode={s['retrieval_mode']}  improved_index_ready={s['improved_index_ready']}")
    add(f"why: {s['why']}")
    if s["last_error"]:
        add(f"last_error: {s['last_error']}")
    if "term_profile" in report:
        p = report["term_profile"]
        add("")
        add("== Term frequency (improved-mode relevance floor) ==")
        add(f"vocabulary {p['vocabulary']} terms over {p['chunks']} chunks; a term is 'distinctive' only if it appears in <= {p['distinctive_max_df']} chunks ({p['distinctive_max_df_share']:.0%}).")
        add(f"non-distinctive terms: {p['non_distinctive_terms']} ({p['non_distinctive_share_of_vocabulary']:.1%} of vocabulary)")
    if report["questions"]:
        add("")
        add(f"== Sample questions: legacy vs improved (top {top}) ==")
        for row in report["questions"]:
            flags = f"   [{', '.join(row['flags'])}]" if row["flags"] else ""
            add(f"Q: {row['question']}{flags}")
            for mode in ("legacy", "improved"):
                hits = row[mode]
                add(f"  {mode}: " + ("no chunks" if not hits else ""))
                for h in hits[:top]:
                    cov = "" if h["coverage"] is None else f" cov={h['coverage']}"
                    add(f"    {h['rank']}. score={h['score']}{cov} {h['url'] or '(no url)'}")
                    add(f"       {h['title']} - {h['snippet']}")
    if report["llm_flow"]:
        add("")
        add("== Backend -> LLM flow (fake LLM, no network) ==")
        for r in report["llm_flow"]:
            add(f"- {r['question']}\n    mode={r['mode']} llm_called={r['llm_called']} context_sources={r['context_sources']} "
                f"context_chars={r['context_chars']} cited_sources={len(r['returned_source_urls'])}")
            if r["context_urls_not_cited"]:
                add(f"    sent to LLM but not cited: {r['context_urls_not_cited']}")
    add("")
    add("== Checks ==")
    add(f"read-only verified (data dir unchanged): {report['read_only_verified']}")
    for e in report["errors"]:
        add(f"ERROR   {e}")
    for w in report["warnings"]:
        add(f"WARNING {w}")
    if not report["errors"] and not report["warnings"]:
        add("No warnings.")
    add("")
    add("This report describes the index files and retrieval behaviour only. It is NOT a measure of answer accuracy.")
    return "\n".join(out)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m diagnostics", description="Read-only diagnostic of the backend retrieval over the real index files.")
    p.add_argument("--data-dir", help="data directory containing index_fast/ and index/ (default: <project>/data)")
    p.add_argument("--questions", metavar="FILE", help="questions file: one per line or JSONL with a 'question' field")
    p.add_argument("--top", type=int, default=3, help="hits to show per question and mode (default 3)")
    p.add_argument("--json", action="store_true", help="print the report as JSON")
    p.add_argument("--no-llm-check", action="store_true", help="skip the fake-LLM flow check")
    p.add_argument("--use-env", action="store_true", help="allow python-dotenv to load .env (secret-named variables are removed afterwards). Off by default.")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return EXIT_OK if exc.code in (0, None) else EXIT_USAGE
    if args.top < 1 or args.top > 20:
        print("--top must be between 1 and 20", file=sys.stderr)
        return EXIT_USAGE
    if args.data_dir and not Path(args.data_dir).is_dir():
        print(f"--data-dir {args.data_dir!r} is not a directory", file=sys.stderr)
        return EXIT_USAGE
    if args.questions:
        try:
            args.questions_list = checks.read_questions(args.questions)
        except (OSError, UnicodeDecodeError) as exc:
            print(f"cannot read --questions file: {exc}", file=sys.stderr)
            return EXIT_USAGE
        if not args.questions_list:
            print("--questions file contains no questions", file=sys.stderr)
            return EXIT_USAGE
    else:
        args.questions_list = list(checks.DEFAULT_QUESTIONS)
    try:
        report = collect(args)
    except ModuleNotFoundError as exc:
        print(f"Missing dependency: {exc.name}. Install the backend requirements first (pip install -r requirements-local.txt).", file=sys.stderr)
        return EXIT_ERRORS
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    else:
        print(render_text(report, args.top))
    if report["errors"]:
        return EXIT_ERRORS
    return EXIT_WARNINGS if report["warnings"] else EXIT_OK
