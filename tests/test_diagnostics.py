"""Tests for the read-only diagnostic CLI (``python -m diagnostics``). Synthetic data only."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import _support  # noqa: F401
from tests.fixtures.serving import write_jsonl

from diagnostics import EXIT_ERRORS, EXIT_OK, EXIT_USAGE, EXIT_WARNINGS, checks
from diagnostics import cli

ROOT = Path(__file__).resolve().parents[1]

NAV = "Home | About | Admissions | Placements | Contact Us | Campus Life."
GOOD_ROWS = [
    {"chunk_id": "pl", "doc_id": "pl", "title": "Training and Placement Cell", "url": "https://example.test/placements",
     "text": NAV + " Recruiters visit every year."},
    {"chunk_id": "lib", "doc_id": "lib", "title": "Library", "url": "https://example.test/library",
     "text": NAV + " Library borrowing period is fourteen days."},
] + [{"chunk_id": f"x{i}", "doc_id": f"x{i}", "title": f"Page {i}", "url": f"https://example.test/x/{i}",
      "text": NAV + f" Unrelated content number {i} about gardens."} for i in range(40)]


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


def snapshot(root: Path):
    """Complete content+metadata snapshot of a directory tree."""
    snap = {}
    for current, dirs, files in os.walk(root):
        for name in dirs + files:
            p = Path(current) / name
            st = p.stat()
            digest = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
            snap[str(p.relative_to(root))] = (st.st_size, st.st_mtime_ns, digest)
    return snap


class DataDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data = Path(self._tmp.name) / "data"
        (self.data / "index_fast").mkdir(parents=True)
        (self.data / "index").mkdir(parents=True)
        (self.data / "reports").mkdir()
        self.fast = self.data / "index_fast" / "chunks.jsonl"
        self.old = self.data / "index" / "chunks.jsonl"
        from api import retrieval
        self.retrieval = retrieval
        self.addCleanup(retrieval._reset_state_for_tests)

    def report(self, *extra):
        code, out, err = run(["--data-dir", str(self.data), "--json", *extra])
        return code, json.loads(out), err


class HealthyIndexTests(DataDirCase):
    def setUp(self):
        super().setUp()
        write_jsonl(self.fast, GOOD_ROWS)

    def test_report_contents(self):
        code, rep, _ = self.report()
        self.assertIn(code, (EXIT_OK, EXIT_WARNINGS))
        self.assertTrue(rep["read_only"])
        self.assertTrue(rep["read_only_verified"])
        fast, old = rep["candidates"]
        self.assertTrue(fast["exists"])
        self.assertEqual(fast["valid_chunks"], len(GOOD_ROWS))
        self.assertEqual(fast["sha256"], hashlib.sha256(self.fast.read_bytes()).hexdigest())
        self.assertFalse(old["exists"])
        self.assertEqual(rep["serving"]["serving_index"], "fast")
        self.assertEqual(rep["serving"]["chunks_loaded"], len(GOOD_ROWS))
        self.assertTrue(rep["serving"]["improved_index_ready"])
        self.assertIn("term_profile", rep)
        self.assertEqual(len(rep["questions"]), len(checks.DEFAULT_QUESTIONS))
        self.assertEqual(len(rep["llm_flow"]), len(checks.DEFAULT_QUESTIONS))

    def test_never_modifies_anything_in_the_data_directory(self):
        (self.data / "reports" / "fast_index_report.json").write_text("{}", encoding="utf-8")
        write_jsonl(self.old, GOOD_ROWS[:5])
        before = snapshot(self.data)
        for extra in ([], ["--no-llm-check"], ["--top", "5"]):
            self.report(*extra)
            run(["--data-dir", str(self.data)])  # text mode too
        self.assertEqual(snapshot(self.data), before)

    def test_no_files_are_created_even_for_a_missing_index(self):
        self.fast.unlink()
        for d in (self.data / "index_fast", self.data / "index"):
            d.rmdir()
        before = snapshot(self.data)
        code, rep, _ = self.report()
        self.assertEqual(code, EXIT_ERRORS)
        self.assertEqual(snapshot(self.data), before)
        self.assertFalse((self.data / "index_fast").exists())

    def test_text_output_has_the_sections_and_the_accuracy_disclaimer(self):
        code, out, _ = run(["--data-dir", str(self.data), "--top", "2"])
        for needle in ("READ-ONLY", "== Index candidates ==", "== What the backend would serve ==",
                       "== Sample questions: legacy vs improved", "== Backend -> LLM flow", "== Checks ==",
                       "NOT a measure of answer accuracy"):
            self.assertIn(needle, out)

    def test_topic_in_navigation_and_title_is_answered_not_flagged(self):
        _, rep, _ = self.report("--questions", self._q(["Tell me about placements"]))
        row = rep["questions"][0]
        self.assertTrue(row["improved"])
        self.assertEqual(row["improved"][0]["url"], "https://example.test/placements")
        self.assertNotIn("improved_returns_nothing_legacy_returns_hits", row["flags"])

    def test_llm_flow_reports_context_and_sources(self):
        _, rep, _ = self.report("--questions", self._q(["What is the library borrowing period?", "Best pizza near campus"]))
        lib, pizza = rep["llm_flow"]
        self.assertEqual(lib["mode"], "llm_grounded")
        self.assertTrue(lib["llm_called"])
        self.assertEqual(lib["context_urls"], ["https://example.test/library"])
        self.assertEqual(lib["returned_source_urls"], ["https://example.test/library"])
        self.assertEqual(lib["context_urls_not_cited"], [])
        self.assertEqual(pizza["mode"], "insufficient_evidence")
        self.assertFalse(pizza["llm_called"])

    def test_no_llm_check_flag(self):
        _, rep, _ = self.report("--no-llm-check")
        self.assertEqual(rep["llm_flow"], [])

    def _q(self, lines):
        f = Path(self._tmp.name) / "q.txt"
        f.write_text("\n".join(lines), encoding="utf-8")
        return str(f)


class WarningTests(DataDirCase):
    def codes(self, rep):
        return {w.split(":")[0] for w in rep["warnings"]} | {e.split(":")[0] for e in rep["errors"]}

    def test_no_index_files(self):
        code, rep, _ = self.report()
        self.assertEqual(code, EXIT_ERRORS)
        self.assertIn("NO_INDEX_FILES", self.codes(rep))
        self.assertIn("NO_USABLE_INDEX", self.codes(rep))
        self.assertFalse(rep["serving"]["index_ready"])

    def test_empty_index(self):
        self.fast.write_text("", encoding="utf-8")
        code, rep, _ = self.report()
        self.assertEqual(code, EXIT_ERRORS)
        self.assertIn("EMPTY_INDEX", self.codes(rep))

    def test_invalid_utf8_is_reported_not_raised(self):
        self.fast.write_bytes(b'{"text": "caf\xe9"}\n')
        code, rep, _ = self.report()
        self.assertEqual(code, EXIT_ERRORS)
        self.assertIn("UNREADABLE_INDEX", self.codes(rep))

    def test_invalid_lines_null_urls_titles_duplicates(self):
        rows = [dict(GOOD_ROWS[1], url=None, title=None)] + GOOD_ROWS[2:] + [GOOD_ROWS[2]] * 6
        self.fast.write_text("broken\n" + "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        code, rep, _ = self.report()
        codes = self.codes(rep)
        for expected in ("INVALID_LINES", "MISSING_URLS", "MISSING_TITLES", "DUPLICATE_CHUNKS"):
            self.assertIn(expected, codes)
        self.assertEqual(code, EXIT_WARNINGS)

    def test_published_index_newer_than_fast_is_flagged(self):
        write_jsonl(self.fast, GOOD_ROWS)
        write_jsonl(self.old, GOOD_ROWS)
        os.utime(self.fast, (1_000_000_000, 1_000_000_000))
        _, rep, _ = self.report()
        self.assertIn("PUBLISHED_INDEX_SHADOWED", self.codes(rep))
        self.assertEqual(rep["serving"]["serving_index"], "fast")

    def test_fast_older_than_published_not_flagged_when_fast_is_newer(self):
        write_jsonl(self.old, GOOD_ROWS)
        os.utime(self.old, (1_000_000_000, 1_000_000_000))
        write_jsonl(self.fast, GOOD_ROWS)
        _, rep, _ = self.report()
        self.assertNotIn("PUBLISHED_INDEX_SHADOWED", self.codes(rep))

    def test_rejected_fast_falls_back_and_is_reported(self):
        self.fast.write_text("garbage\n", encoding="utf-8")
        write_jsonl(self.old, GOOD_ROWS)
        code, rep, _ = self.report()
        self.assertEqual(rep["serving"]["serving_index"], "index")
        self.assertIn("CANDIDATE_REJECTED", self.codes(rep))

    def test_small_index_warning(self):
        write_jsonl(self.fast, GOOD_ROWS[:10])
        _, rep, _ = self.report()
        self.assertIn("SMALL_INDEX", self.codes(rep))

    def test_dominant_terms_warning_names_frequent_words(self):
        write_jsonl(self.fast, GOOD_ROWS)
        _, rep, _ = self.report()
        profile = rep["term_profile"]
        self.assertGreater(profile["non_distinctive_terms"], 0)
        self.assertIn("placement", {t["term"] for t in profile["most_common_non_distinctive"]})
        self.assertIn("DOMINANT_TERMS", self.codes(rep))

    def test_body_only_dominance_is_reported_as_false_refusal_candidate(self):
        rows = [{"chunk_id": f"b{i}", "doc_id": f"b{i}", "title": f"Notice {i}", "url": f"https://example.test/n/{i}",
                 "text": f"Book return rule number {i} for the library."} for i in range(9)] + GOOD_ROWS[2:12]
        write_jsonl(self.fast, rows)
        q = Path(self._tmp.name) / "q.txt"
        q.write_text("library book return rule\n", encoding="utf-8")
        _, rep, _ = self.report("--questions", str(q))
        self.assertIn("improved_returns_nothing_legacy_returns_hits", rep["questions"][0]["flags"])
        self.assertTrue(any(w.startswith("IMPROVED_REFUSES") for w in rep["warnings"]))

    def test_indic_query_without_match_is_flagged(self):
        write_jsonl(self.fast, GOOD_ROWS)
        _, rep, _ = self.report()
        self.assertIn("INDIC_QUERY_NO_MATCH", self.codes(rep))


class UsageTests(DataDirCase):
    def test_bad_arguments_exit_3(self):
        for argv in (["--top", "0"], ["--top", "99"], ["--top", "abc"], ["--bogus"],
                     ["--data-dir", str(self.data / "nope")], ["--questions", str(self.data / "nope.txt")]):
            code, _, _ = run(argv)
            self.assertEqual(code, EXIT_USAGE, argv)

    def test_empty_questions_file_exit_3(self):
        f = Path(self._tmp.name) / "empty.txt"
        f.write_text("# only a comment\n\n", encoding="utf-8")
        self.assertEqual(run(["--data-dir", str(self.data), "--questions", str(f)])[0], EXIT_USAGE)

    def test_help_exits_zero(self):
        self.assertEqual(run(["--help"])[0], EXIT_OK)

    def test_questions_file_formats(self):
        f = Path(self._tmp.name) / "q.txt"
        f.write_text('# comment\nPlain question?\n{"question": "Json question?"}\n{"query": "Query field"}\n{"other": 1}\n\n',
                     encoding="utf-8-sig")
        self.assertEqual(checks.read_questions(f), ["Plain question?", "Json question?", "Query field"])  # unknown JSON shape is skipped


class SafetyTests(DataDirCase):
    def test_network_is_blocked_during_the_run(self):
        with cli.no_network():
            with self.assertRaises(OSError):
                socket.create_connection(("127.0.0.1", 9), timeout=0.2)
        # and restored afterwards (a refused connection is a ConnectionError, not our OSError message)
        with self.assertRaises(OSError) as ctx:
            socket.create_connection(("127.0.0.1", 9), timeout=0.2)
        self.assertNotIn("disabled by the diagnostic", str(ctx.exception))

    def test_real_llm_credentials_are_never_used_or_printed(self):
        write_jsonl(self.fast, GOOD_ROWS)
        recorded = []

        class Spy(cli.FakeLLM):
            def __call__(self, url, headers=None, json=None, timeout=None, **kw):
                recorded.append((url, headers))
                return super().__call__(url, headers=headers, json=json, timeout=timeout)

        env = {"LLM_API_KEY": "REAL-SECRET-SENTINEL", "LLM_MODEL": "real-model", "LLM_BASE_URL": "https://real.example/v1"}
        with mock.patch.dict(os.environ, env), mock.patch.object(cli, "FakeLLM", Spy):
            code, out, err = run(["--data-dir", str(self.data), "--json"])
            self.assertEqual(os.environ["LLM_API_KEY"], "REAL-SECRET-SENTINEL")  # restored
        self.assertTrue(recorded)
        for url, headers in recorded:
            self.assertTrue(url.startswith("https://llm.diagnostic.invalid/"))
            self.assertNotIn("REAL-SECRET-SENTINEL", json.dumps(headers))
        self.assertNotIn("REAL-SECRET-SENTINEL", out + err)
        self.assertNotIn("real.example", out + err)

    def test_dotenv_is_not_read_by_default_and_secrets_are_scrubbed_with_use_env(self):
        import dotenv.main
        original = sys.modules.get("api.retrieval")
        api_pkg = sys.modules["api"]
        calls = []

        def fake_set_env(self, *a, **k):
            calls.append(1)
            os.environ["LLM_API_KEY"] = "DOTENV-SENTINEL"
            os.environ["DIAG_HARMLESS_SETTING"] = "ok"
            return True

        try:
            with mock.patch.object(dotenv.main.DotEnv, "set_as_environment_variables", fake_set_env), \
                    mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("LLM_API_KEY", None)
                sys.modules.pop("api.retrieval")
                cli.import_retrieval(False)
                self.assertEqual(calls, [])
                self.assertNotIn("LLM_API_KEY", os.environ)

                sys.modules.pop("api.retrieval")
                _, state = cli.import_retrieval(True)
                self.assertEqual(calls, [1])
                self.assertTrue(state["dotenv_called"])
                self.assertNotIn("LLM_API_KEY", os.environ)         # secret-named variable removed
                self.assertEqual(os.environ.get("DIAG_HARMLESS_SETTING"), "ok")
        finally:
            os.environ.pop("DIAG_HARMLESS_SETTING", None)
            sys.modules["api.retrieval"] = original
            api_pkg.retrieval = original

    def test_help_runs_in_a_clean_interpreter(self):
        proc = subprocess.run([sys.executable, "-m", "diagnostics", "--help"], cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Read-only diagnostic", proc.stdout)

    def test_bad_args_in_a_clean_interpreter_exit_3(self):
        proc = subprocess.run([sys.executable, "-m", "diagnostics", "--top", "0"], cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, EXIT_USAGE)


class ChecksTests(unittest.TestCase):
    def test_fingerprint_detects_changes(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "a.txt").write_text("x")
            first = checks.fingerprint_tree(root)
            self.assertEqual(first, checks.fingerprint_tree(root))
            (root / "b.txt").write_text("y")
            self.assertNotEqual(first, checks.fingerprint_tree(root))

    def test_snippet(self):
        self.assertEqual(checks.snippet("a  b\n c"), "a b c")
        self.assertTrue(checks.snippet("x" * 500).endswith("…"))
        self.assertEqual(checks.snippet(None), "")

    def test_corpus_stats_non_ascii_share(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_jsonl(Path(d) / "c.jsonl", [{"text": "hostel fee"}, {"text": "హాస్టల్ ఫీజు"}])
            stats = checks.corpus_stats(p)
        self.assertEqual(stats["valid_chunks"], 2)
        self.assertGreater(stats["non_ascii_letter_share"], 0.3)
        self.assertGreater(stats["indic_character_count"], 0)
        self.assertEqual(stats["chunks_without_url"], 2)


if __name__ == "__main__":
    unittest.main()
