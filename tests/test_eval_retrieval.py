from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._eval_support import chunk, rec, verified, write_chunks, write_dataset

from evaluation import __main__ as cli
from evaluation.dataset import load_dataset
from evaluation.report import compare_reports, render_comparison_markdown, render_markdown, write_reports
from evaluation.retrieval_eval import bm25_backend, run_retrieval_evaluation, serve_index_file

LIB, HOST, PLC = "https://example.test/library", "https://example.test/hostel", "https://example.test/placements"
READY = {"index_ready": True, "source": "fake", "sha256": "ab" * 32, "chunks_loaded": 5, "serving_index": "index"}

CHUNKS = [
    chunk(LIB, "Library", "The library timings and reading room rules are listed here. " * 3),
    chunk(HOST, "Hostel", "Hostel allotment, mess and warden contact information for students. " * 3),
    chunk(PLC, "Placements", "Placement statistics with packages 12 LPA recruiters 45 listed. " * 3),
    chunk("https://example.test/about", "About", "General college information and history of the campus. " * 3),
    chunk("https://example.test/news", "News", "Latest news and events at the campus this month. " * 3),
    chunk("https://example.test/sports", "Sports", "Sports ground facilities and annual sports meet details. " * 3),
]


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def dataset(self, records):
        return load_dataset(write_dataset(self.dir / "d.jsonl", records))

    def fake_retrieve(self, mapping):
        def fn(query, limit=5):
            return [dict(c) for c in mapping.get(query, [])][:limit]
        return fn

    def run_eval(self, records, mapping, **kw):
        return run_retrieval_evaluation(
            self.dataset(records), retrieve_fn=self.fake_retrieve(mapping),
            chunk_provider=lambda: CHUNKS, index_status=READY, **kw)


class EvaluationTests(Base):
    def test_unverified_questions_are_neither_success_nor_failure(self):
        report = self.run_eval([rec(id="U1"), rec(id="U2", verification_status="unverified")],
                               {"What are the library timings?": [CHUNKS[0]]})
        self.assertEqual(report["dataset"]["evaluated"], 0)
        self.assertEqual(report["evaluated"], [])
        self.assertEqual(len(report["unverified_or_unscored"]), 2)
        self.assertIsNone(report["metrics"]["overall"]["mrr"])
        self.assertIsNone(report["metrics"]["overall"]["recall@5"])

    def test_metrics_overall_and_by_category(self):
        q1, q2, q3 = "q library", "q hostel", "q placement"
        records = [
            verified(id="V1", question=q1, expected_sources=[LIB]),
            verified(id="V2", question=q2, category="Hostel and transport", expected_sources=[HOST]),
            verified(id="V3", question=q3, category="Placements", expected_sources=[PLC]),
            rec(id="U1", question="unverified one", category="Placements"),
        ]
        mapping = {q1: [CHUNKS[0], CHUNKS[3]],                 # rank 1
                   q2: [CHUNKS[3], CHUNKS[1]],                 # rank 2
                   q3: [CHUNKS[3], CHUNKS[4], CHUNKS[5]],      # miss
                   "unverified one": [CHUNKS[2]]}
        report = self.run_eval(records, mapping)
        ov = report["metrics"]["overall"]
        self.assertEqual(ov["n"], 3)
        self.assertAlmostEqual(ov["mrr"], (1 + 0.5 + 0) / 3)
        self.assertAlmostEqual(ov["recall@1"], 1 / 3)
        self.assertAlmostEqual(ov["recall@3"], 2 / 3)
        cats = report["metrics"]["by_category"]
        self.assertEqual(cats["Hostel and transport"]["metrics"]["mrr"], 0.5)
        self.assertEqual(cats["Placements"]["evaluated"], 1)       # U1 not counted
        self.assertEqual(cats["Placements"]["total_questions"], 2)
        self.assertEqual(cats["Placements"]["metrics"]["mrr"], 0.0)
        self.assertIsNone(cats["Admissions"]["metrics"]["mrr"])    # nothing evaluated -> n/a, not 0
        self.assertEqual(report["dataset"]["verified"], 3)
        self.assertEqual(report["dataset"]["needs_ground_truth"], 1)

    def test_verified_unanswerable_not_scored(self):
        report = self.run_eval([verified(id="N1", answerable="no", expected_sources=[], question="nothing")],
                               {"nothing": [CHUNKS[0]]})
        self.assertEqual(report["dataset"]["evaluated"], 0)
        self.assertEqual(report["dataset"]["verified_unanswerable"], 1)

    def test_no_index_means_not_run_not_failed(self):
        ds = self.dataset([verified(id="V1"), rec(id="U1")])
        report = run_retrieval_evaluation(
            ds, retrieve_fn=lambda *a, **k: self.fail("retrieval must not run"), chunk_provider=lambda: [],
            index_status={"index_ready": False})
        self.assertFalse(report["index"]["available"])
        self.assertEqual(report["dataset"]["not_run_index_unavailable"], 1)
        self.assertEqual(report["dataset"]["evaluated"], 0)
        self.assertIsNone(report["metrics"]["overall"]["mrr"])
        self.assertFalse(report["environment"]["valid_as_retrieval_performance"])
        self.assertTrue(any("No index" in w for w in report["warnings"]))

    def test_substitute_backend_is_flagged_not_real(self):
        report = self.run_eval([verified(id="V1", question="q1", expected_sources=[LIB])], {"q1": [CHUNKS[0]]})
        with mock.patch("evaluation.retrieval_eval.bm25_backend", return_value="substitute"):
            report = self.run_eval([verified(id="V1", question="q1", expected_sources=[LIB])], {"q1": [CHUNKS[0]]})
        self.assertEqual(report["environment"]["bm25_backend"], "substitute")
        self.assertFalse(report["environment"]["valid_as_retrieval_performance"])
        self.assertTrue(any("NOT be presented as real" in w for w in report["warnings"]))
        self.assertIn("**False**", render_markdown(report))

    def test_backend_detection_recognises_stub(self):
        import sys
        stub = getattr(sys.modules.get("rank_bm25"), "__stub__", False)
        self.assertEqual(bm25_backend(), "substitute" if stub else "real")

    def test_weakness_diagnostics(self):
        q = "library timings rules"
        absent = verified(id="W1", question=q, expected_sources=["https://example.test/not-indexed"])
        below = verified(id="W2", question="hostel mess", category="Hostel and transport", expected_sources=[HOST])
        mapping = {q: [CHUNKS[3], CHUNKS[4]],
                   "hostel mess": [CHUNKS[3], CHUNKS[4], CHUNKS[5], CHUNKS[0], CHUNKS[2], CHUNKS[1]]}
        report = self.run_eval([absent, below], mapping)
        flags = {e["id"]: e["diagnostics"]["flags"] for e in report["evaluated"]}
        self.assertIn("relevant_missing_from_top_k", flags["W1"])
        self.assertIn("expected_source_absent_from_index", flags["W1"])
        self.assertIn("relevant_ranked_below_top_k", flags["W2"])
        self.assertIn("irrelevant_ranked_above_relevant", flags["W2"])
        self.assertEqual(report["weaknesses"]["flag_counts"]["relevant_missing_from_top_k"], 2)

    def test_title_terminology_numeric_and_diversity_flags(self):
        # expected doc title/text share nothing with the query; outranking chunk title matches
        numeric = chunk("https://example.test/fees", "Charges", "Item 12000 | 15000 | 18000 | 22000 | 25000 | 30000 per year")
        outrank = [chunk("https://example.test/x1", "Admission process", "text a " * 30),
                   chunk("https://example.test/x1", "Admission process", "text b " * 30),
                   chunk("https://example.test/x1", "Admission process", "text c " * 30)]
        records = [verified(id="F1", question="admission process fee", category="Fees and scholarships",
                            expected_sources=["https://example.test/fees"], expected_keywords=["12000"])]
        report = run_retrieval_evaluation(
            self.dataset(records), retrieve_fn=self.fake_retrieve({"admission process fee": outrank}),
            chunk_provider=lambda: CHUNKS + [numeric], index_status=READY)
        flags = report["evaluated"][0]["diagnostics"]["flags"]
        for expected in ("outranked_by_better_title_match", "query_terminology_mismatch",
                         "numeric_or_table_content_not_top_ranked", "low_source_diversity"):
            self.assertIn(expected, flags)

    def test_grounding_section_requires_supplied_answers_and_never_calls_llm(self):
        records = [rec(id="G1", question="lib?"), rec(id="G2", question="what?"),
                   verified(id="G3", answerable="no", expected_sources=[], question="nothing published")]
        answers = {"G1": {"answer": "The library timings are 9 to 5."},
                   "G3": {"answer": "Please check the official website to verify.", "evidence": []}}
        report = self.run_eval(records, {"lib?": [CHUNKS[0]]}, answers=answers)
        g = report["grounding"]
        self.assertEqual(g["checked"], 2)
        self.assertEqual(g["no_answer_supplied"], ["G2"])
        by_id = {i["id"]: i for i in g["items"]}
        self.assertEqual(by_id["G1"]["verdict"], "warnings")      # 9 and 5 absent: generic numbers are medium
        self.assertIn("unsupported_number", {f["code"] for f in by_id["G1"]["findings"]})
        self.assertEqual(by_id["G3"]["verdict"], "no_issues_found")
        self.assertIn("not mean the answer is correct", g["disclaimer"])
        self.assertIn("Answer grounding", render_markdown(report))


class ReadOnlyIndexTests(Base):
    def test_evaluating_a_chunks_file_does_not_modify_it(self):
        from api import retrieval
        idx = self.dir / "idx"
        path = write_chunks(idx / "chunks.jsonl", [
            {"chunk_id": f"c{i}", "doc_id": f"d{i}", "url": u["url"], "title": u["title"], "text": u["text"]}
            for i, u in enumerate(CHUNKS)])
        before_bytes, before_mtime = path.read_bytes(), path.stat().st_mtime_ns
        before_listing = sorted(p.name for p in idx.rglob("*"))
        ds = self.dataset([verified(id="V1", question="library timings", expected_sources=[LIB]), rec(id="U1")])
        saved = (retrieval.FAST_CHUNKS_PATH, retrieval.OLD_CHUNKS_PATH)
        with serve_index_file(path):
            report = run_retrieval_evaluation(ds)
        self.assertEqual((retrieval.FAST_CHUNKS_PATH, retrieval.OLD_CHUNKS_PATH), saved)  # restored
        self.assertTrue(report["index"]["available"])
        self.assertEqual(report["index"]["sha256"], hashlib.sha256(before_bytes).hexdigest())
        self.assertEqual(report["dataset"]["evaluated"], 1)
        self.assertEqual(report["evaluated"][0]["first_relevant_rank"], 1)
        self.assertEqual(path.read_bytes(), before_bytes)
        self.assertEqual(path.stat().st_mtime_ns, before_mtime)
        self.assertEqual(sorted(p.name for p in idx.rglob("*")), before_listing)


class ReportTests(Base):
    def make_report(self, rank_url=LIB):
        return self.run_eval([verified(id="V1", question="q1", expected_sources=[LIB]), rec(id="U1")],
                             {"q1": [CHUNKS[3], CHUNKS[0]] if rank_url == LIB else [CHUNKS[0]]})

    def test_json_and_markdown_reports_written(self):
        report = self.make_report()
        jp, mp = write_reports(report, self.dir / "out" / "nested", "r1")
        loaded = json.loads(jp.read_text(encoding="utf-8"))
        self.assertEqual(loaded["metrics"]["overall"]["mrr"], 0.5)
        md = mp.read_text(encoding="utf-8")
        for text in ("## Question counts", "## Metrics (evaluated questions only)", "Unverified questions are **not** counted",
                     "## Unverified / unscored questions", "| Overall | 1 |", "General college information"):
            self.assertIn(text, md)

    def test_markdown_shows_na_for_empty_scopes(self):
        md = render_markdown(self.make_report())
        self.assertIn("n/a", md)
        self.assertIn("| Admissions (0 of 0 evaluated) | 0 | n/a", md)

    def test_report_without_evaluated_questions_renders(self):
        md = render_markdown(self.run_eval([rec(id="U1")], {}))
        self.assertIn("Add verified ground truth", md)

    def test_compare_reports(self):
        base = self.make_report()
        new = self.make_report(rank_url="other")
        cmp = compare_reports(base, new)
        self.assertEqual(cmp["overall"]["mrr"]["baseline"], 0.5)
        self.assertEqual(cmp["overall"]["mrr"]["delta"], 0.5)
        self.assertEqual(cmp["rank_changes"], [{"id": "V1", "baseline_rank": 2, "new_rank": 1}])
        self.assertTrue(any("identical" in c for c in cmp["caveats"]))
        self.assertIn("V1: 2 -> 1", render_comparison_markdown(cmp))


class CliTests(Base):
    def test_invalid_dataset_returns_2(self):
        bad = self.dir / "bad.jsonl"
        bad.write_text("{oops\n", encoding="utf-8")
        self.assertEqual(cli.main(["--dataset", str(bad), "--output-dir", str(self.dir)]), 2)

    def test_empty_dataset_returns_2(self):
        empty = self.dir / "e.jsonl"
        empty.write_text("", encoding="utf-8")
        self.assertEqual(cli.main(["--dataset", str(empty), "--output-dir", str(self.dir)]), 2)

    def test_run_answers_refuses_paid_calls_without_flag(self):
        ds = write_dataset(self.dir / "d.jsonl", [rec(id="A")])
        env = {
            "OPENROUTER_API_KEY": "dummy-not-a-real-key", "OPENROUTER_MODEL": "dummy",
            "LLM_API_KEY": "", "LLM_MODEL": "",
        }
        with mock.patch.dict(os.environ, env), \
             mock.patch("api.retrieval.answer_question", side_effect=AssertionError("LLM path used")) as aq:
            code = cli.main(["--dataset", str(ds), "--run-answers", "--output-dir", str(self.dir)])
        self.assertEqual(code, 3)
        aq.assert_not_called()

    def test_run_answers_with_permission_allows_openrouter_generation(self):
        ds = write_dataset(self.dir / "d.jsonl", [rec(id="A")])
        env = {
            "OPENROUTER_API_KEY": "dummy-not-a-real-key", "OPENROUTER_MODEL": "dummy",
            "LLM_API_KEY": "", "LLM_MODEL": "",
        }
        result = {"answer": "mock answer", "mode": "llm_grounded", "sources": []}
        with mock.patch.dict(os.environ, env), \
             mock.patch("api.retrieval.answer_question", return_value=result) as aq:
            code = cli.main([
                "--dataset", str(ds), "--run-answers", "--allow-llm-calls",
                "--output-dir", str(self.dir),
            ])
        self.assertEqual(code, 0)
        aq.assert_called_once()

    def test_run_answers_refuses_legacy_config_without_permission(self):
        ds = write_dataset(self.dir / "d.jsonl", [rec(id="A")])
        env = {
            "OPENROUTER_API_KEY": "", "OPENROUTER_MODEL": "",
            "LLM_API_KEY": "legacy-dummy-key", "LLM_MODEL": "legacy-model",
        }
        with mock.patch.dict(os.environ, env), \
             mock.patch("api.retrieval.answer_question", side_effect=AssertionError("LLM path used")) as aq:
            code = cli.main(["--dataset", str(ds), "--run-answers", "--output-dir", str(self.dir)])
        self.assertEqual(code, 3)
        aq.assert_not_called()

    def test_run_answers_without_provider_keeps_existing_retrieval_behavior(self):
        ds = write_dataset(self.dir / "d.jsonl", [rec(id="A")])
        env = {
            "OPENROUTER_API_KEY": "", "OPENROUTER_MODEL": "",
            "LLM_API_KEY": "", "LLM_MODEL": "",
        }
        result = {"answer": "retrieval fallback", "mode": "retrieval", "sources": []}
        with mock.patch.dict(os.environ, env), \
             mock.patch("api.retrieval.answer_question", return_value=result) as aq:
            code = cli.main(["--dataset", str(ds), "--run-answers", "--output-dir", str(self.dir)])
        self.assertEqual(code, 0)
        aq.assert_called_once()

    def test_cli_end_to_end_on_temp_index(self):
        idx = write_chunks(self.dir / "i" / "chunks.jsonl", [
            {"chunk_id": f"c{i}", "doc_id": f"d{i}", "url": c["url"], "title": c["title"], "text": c["text"]}
            for i, c in enumerate(CHUNKS)])
        ds = write_dataset(self.dir / "d.jsonl", [verified(id="V1", question="library timings", expected_sources=[LIB]), rec(id="U1")])
        out = self.dir / "out"
        code = cli.main(["--dataset", str(ds), "--chunks", str(idx), "--output-dir", str(out), "--name", "t"])
        self.assertEqual(code, 0)
        report = json.loads((out / "t.json").read_text(encoding="utf-8"))
        self.assertEqual(report["dataset"]["evaluated"], 1)
        self.assertTrue((out / "t.md").is_file())


if __name__ == "__main__":
    unittest.main()
