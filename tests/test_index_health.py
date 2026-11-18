"""Missing / empty / invalid / stale index behaviour, observed through the public API
(``answer_question``, ``retrieve``, ``get_index_status``). Synthetic data only.

Complements tests/test_retrieval_reload.py (cache/priority/concurrency) by asserting what
a *student* would see and what an operator can read from the status, for every kind of
bad index file.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import _support  # noqa: F401

from api import retrieval

LIB = {"chunk_id": "lib-0", "doc_id": "lib", "title": "Library", "url": "https://example.test/library",
       "text": "Library borrowing period is fourteen days for students."}
FILLER = [{"chunk_id": f"p{i}", "doc_id": f"p{i}", "title": f"Notice {i}", "url": f"https://example.test/p/{i}",
           "text": f"Unrelated notice {i} about gardens."} for i in range(10)]
GOOD = [LIB] + FILLER
Q = "What is the library borrowing period?"


def jl(rows):
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


class IndexCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.fast = root / "data" / "index_fast" / "chunks.jsonl"
        self.old = root / "data" / "index" / "chunks.jsonl"
        self.fast.parent.mkdir(parents=True)
        self.old.parent.mkdir(parents=True)
        for name, value in (("FAST_CHUNKS_PATH", self.fast), ("OLD_CHUNKS_PATH", self.old)):
            p = mock.patch.object(retrieval, name, value)
            p.start()
            self.addCleanup(p.stop)
        e = mock.patch.dict(os.environ, {"LLM_API_KEY": "", "LLM_MODEL": ""})  # no LLM: retrieval only
        e.start()
        self.addCleanup(e.stop)
        os.environ.pop("RETRIEVAL_MODE", None)
        retrieval._reset_state_for_tests()
        self.addCleanup(retrieval._reset_state_for_tests)

    def write(self, path, text, raw=False):
        path.write_bytes(text if raw else text.encode("utf-8"))

    def serve(self, rows=None):
        self.write(self.fast, jl(rows or GOOD))
        return retrieval.get_index_status()


class MissingIndexTests(IndexCase):
    def test_status_and_answer(self):
        status = retrieval.get_index_status()
        self.assertFalse(status["index_ready"])
        self.assertEqual(status["chunks_loaded"], 0)
        self.assertIsNone(status["source"])
        self.assertEqual(retrieval.retrieve(Q), [])
        out = retrieval.answer_question(Q)
        self.assertEqual(out["mode"], "index_unavailable")
        self.assertEqual(out["sources"], [])

    def test_missing_directory_does_not_raise(self):
        import shutil
        shutil.rmtree(self.fast.parent)
        shutil.rmtree(self.old.parent)
        self.assertEqual(retrieval.answer_question(Q)["mode"], "index_unavailable")
        self.assertEqual(retrieval.load_chunks(), [])

    def test_index_appearing_later_is_picked_up_without_restart(self):
        self.assertEqual(retrieval.answer_question(Q)["mode"], "index_unavailable")
        self.serve()
        out = retrieval.answer_question(Q)
        self.assertEqual(out["mode"], "generation_unavailable")  # retrieved, LLM not configured
        self.assertEqual(out["sources"][0]["url"], "https://example.test/library")

    def test_legacy_mode_also_reports_unavailable(self):
        with mock.patch.dict(os.environ, {"RETRIEVAL_MODE": "legacy"}):
            self.assertEqual(retrieval.answer_question(Q)["mode"], "index_unavailable")


class EmptyIndexTests(IndexCase):
    def test_zero_byte_file(self):
        self.write(self.fast, "")
        self.assertEqual(retrieval.answer_question(Q)["mode"], "index_unavailable")
        status = retrieval.get_index_status()
        self.assertFalse(status["index_ready"])
        self.assertTrue(status["last_error"])

    def test_whitespace_and_blank_lines_only(self):
        self.write(self.fast, "\n\n   \n\t\n")
        self.assertFalse(retrieval.get_index_status()["index_ready"])

    def test_every_line_invalid(self):
        self.write(self.fast, "not json\n[1,2]\n{\"text\": \"\"}\n{\"text\": 5}\n{\"no_text\": 1}\n")
        status = retrieval.get_index_status()
        self.assertFalse(status["index_ready"])
        self.assertIn("0 valid chunks", status["last_error"])

    def test_empty_fast_falls_back_to_old_and_reports_the_rejection(self):
        self.write(self.fast, "")
        self.write(self.old, jl(GOOD))
        status = retrieval.get_index_status()
        self.assertTrue(status["index_ready"])
        self.assertEqual(status["serving_index"], "index")
        self.assertIn("index_fast", status["last_error"])


class InvalidContentTests(IndexCase):
    def test_bad_lines_are_skipped_good_lines_served(self):
        body = "garbage line\n" + jl([LIB]) + "[1, 2]\n" + '{"chunk_id": "x", "text": ""}\n' + jl(FILLER)
        self.write(self.fast, body)
        status = retrieval.get_index_status()
        self.assertTrue(status["index_ready"])
        self.assertEqual(status["chunks_loaded"], 1 + len(FILLER))
        self.assertEqual(retrieval.retrieve(Q)[0]["chunk_id"], "lib-0")

    def test_invalid_utf8_rejects_the_file_without_crashing(self):
        self.write(self.fast, jl(GOOD).encode("utf-8") + b'{"text": "caf\xe9 \xff\xfe"}\n', raw=True)
        self.assertFalse(retrieval.get_index_status()["index_ready"])
        self.assertEqual(retrieval.answer_question(Q)["mode"], "index_unavailable")
        self.assertIn("codec", retrieval.get_index_status()["last_error"].lower())

    def test_invalid_utf8_in_fast_falls_back_to_old(self):
        self.write(self.fast, b"\xff\xfe\x00bad", raw=True)
        self.write(self.old, jl(GOOD))
        status = retrieval.get_index_status()
        self.assertEqual(status["serving_index"], "index")
        self.assertTrue(status["last_error"])

    def test_utf8_bom_on_first_line_only_costs_that_line(self):
        self.write(self.fast, b"\xef\xbb\xbf" + jl(GOOD).encode("utf-8"), raw=True)
        status = retrieval.get_index_status()
        self.assertTrue(status["index_ready"])
        self.assertEqual(status["chunks_loaded"], len(GOOD) - 1)  # first record unreadable, rest fine

    def test_null_and_nonstring_metadata_are_normalised(self):
        rows = [dict(LIB, title=None, url=None, doc_id=None)] + FILLER
        self.serve(rows)
        chunk = retrieval.load_chunks()[0]
        self.assertEqual((chunk["title"], chunk["url"], chunk["doc_id"]), ("Untitled", "", ""))
        hit = retrieval.retrieve(Q)[0]
        self.assertEqual(hit["url"], "")
        sources = retrieval._build_sources([hit], Q)
        self.assertEqual(sources, [])  # never "None"

    def test_missing_optional_fields(self):
        rows = [{"text": "Library borrowing period is fourteen days for students."}] + FILLER
        self.serve(rows)
        self.assertTrue(retrieval.retrieve(Q))

    def test_very_long_chunk_and_unicode_text_are_accepted(self):
        rows = [dict(LIB, text="library borrowing " + "é" * 20000)] + FILLER + [
            {"chunk_id": "te", "doc_id": "te", "title": "హాస్టల్", "url": "https://example.test/te", "text": "హాస్టల్ ఫీజు వివరాలు"}]
        status = self.serve(rows)
        self.assertTrue(status["index_ready"])
        self.assertEqual(retrieval.retrieve("హాస్టల్ ఫీజు")[0]["chunk_id"], "te")

    def test_duplicate_chunk_ids_do_not_break_serving(self):
        self.serve([LIB, LIB] + FILLER)
        self.assertTrue(retrieval.retrieve(Q))

    def test_single_chunk_index(self):
        self.serve([LIB])
        self.assertEqual(retrieval.get_index_status()["chunks_loaded"], 1)
        # The title ("Library") matches, so improved mode answers even on a one-chunk index.
        self.assertTrue(retrieval.retrieve("library borrowing", mode="improved"))

    def test_single_chunk_index_body_only_match_is_a_known_limitation(self):
        """Same root cause as audit F12: with one chunk no body term can be 'distinctive'."""
        self.serve([{"chunk_id": "o", "doc_id": "o", "title": "Notice", "url": "https://example.test/n",
                     "text": "Borrowing period is fourteen days for students."}])
        self.assertEqual(retrieval.retrieve("borrowing period", mode="improved"), [])
        self.assertTrue(retrieval.retrieve("borrowing period", mode="legacy"))

    def test_quality_layer_failure_does_not_reject_a_valid_index(self):
        with mock.patch.object(retrieval.quality.QualityIndex, "build", side_effect=ValueError("bad")):
            with self.assertLogs("api.retrieval", level="WARNING"):
                status = self.serve()
        self.assertTrue(status["index_ready"])
        self.assertFalse(status["improved_index_ready"])
        self.assertIn("bad", status["improved_index_error"])
        self.assertTrue(retrieval.retrieve(Q))  # legacy scoring still answers

    def test_bm25_build_failure_rejects_candidate_and_is_reported(self):
        with mock.patch.object(retrieval, "BM25Okapi", side_effect=RuntimeError("bm25 down")):
            self.write(self.fast, jl(GOOD))
            status = retrieval.get_index_status()
        self.assertFalse(status["index_ready"])
        self.assertIn("bm25 down", status["last_error"])


class StaleIndexTests(IndexCase):
    def test_corrupted_update_keeps_serving_last_known_good(self):
        self.serve()
        self.assertTrue(retrieval.retrieve(Q))
        self.write(self.fast, "###corrupted###\n")
        status = retrieval.get_index_status()
        self.assertTrue(status["index_ready"])
        self.assertTrue(status["serving_stale"])
        self.assertEqual(status["chunks_loaded"], len(GOOD))
        self.assertTrue(status["last_error"])
        self.assertTrue(status["last_error_at"])
        self.assertEqual(retrieval.retrieve(Q)[0]["chunk_id"], "lib-0")

    def test_answer_still_works_while_stale(self):
        self.serve()
        retrieval.retrieve(Q)
        self.write(self.fast, "")
        out = retrieval.answer_question(Q)
        self.assertEqual(out["mode"], "generation_unavailable")  # retrieval worked; LLM off in this test
        self.assertEqual(out["sources"][0]["url"], "https://example.test/library")

    def test_deleted_file_keeps_serving(self):
        self.serve()
        retrieval.retrieve(Q)
        self.fast.unlink()
        self.assertTrue(retrieval.get_index_status()["index_ready"])
        self.assertTrue(retrieval.retrieve(Q))

    def test_recovery_clears_error_and_stale_flag(self):
        self.serve()
        retrieval.retrieve(Q)
        self.write(self.fast, "bad\n")
        self.assertTrue(retrieval.get_index_status()["serving_stale"])
        self.write(self.fast, jl(GOOD + [dict(LIB, chunk_id="lib-1", text="Library fines are charged per day late.")]))
        status = retrieval.get_index_status()
        self.assertFalse(status["serving_stale"])
        self.assertIsNone(status["last_error"])
        self.assertEqual(status["chunks_loaded"], len(GOOD) + 1)

    def test_new_valid_content_replaces_old_content(self):
        self.serve()
        new = [dict(LIB, text="Library borrowing period is TWENTY-ONE days now for students.")] + FILLER
        self.write(self.fast, jl(new))
        self.assertIn("TWENTY-ONE", retrieval.retrieve(Q)[0]["text"])

    def test_reload_index_forces_rebuild_and_reports(self):
        self.serve()
        result = retrieval.reload_index()
        self.assertTrue(result["index_ready"])
        self.assertTrue(result["reloaded"])

    def test_improved_state_rebuilt_on_reload(self):
        self.serve()
        first = retrieval._ensure_state()
        self.write(self.fast, jl(GOOD + [dict(LIB, chunk_id="n", text="Extra library borrowing rule text here.")]))
        second = retrieval._ensure_state()
        self.assertIsNot(first, second)
        self.assertEqual(second.quality.n_chunks, len(GOOD) + 1)

    def test_fast_index_shadows_newer_published_index(self):
        """Audit F10: data/index_fast always outranks data/index, even when data/index is newer."""
        self.write(self.fast, jl([dict(LIB, text="Library borrowing period is FAST-OLD days for students.")] + FILLER))
        os.utime(self.fast, (1_000_000_000, 1_000_000_000))
        self.write(self.old, jl([dict(LIB, text="Library borrowing period is PUBLISHED-NEW days for students.")] + FILLER))
        status = retrieval.get_index_status()
        self.assertEqual(status["serving_index"], "fast")
        self.assertIn("FAST-OLD", retrieval.retrieve(Q)[0]["text"])
        self.assertTrue(os.path.getmtime(self.old) > os.path.getmtime(self.fast))
        serving = retrieval.describe_serving(self.old)
        self.assertFalse(serving["serving_published_index"])


if __name__ == "__main__":
    unittest.main()
