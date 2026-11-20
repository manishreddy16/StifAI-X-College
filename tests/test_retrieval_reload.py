"""Retrieval cache, reload, last-known-good and concurrency tests (synthetic data)."""

from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from tests._support import BM25_STUBBED, make_chunks, stage, write_chunks

from api import retrieval
from ingestion.index_publisher import CHUNKS_FILENAME, publish_index

QUERY = "library timings"


class RetrievalCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.fast_dir = root / "data" / "index_fast"
        self.old_dir = root / "data" / "index"
        self.fast = self.fast_dir / CHUNKS_FILENAME
        self.old = self.old_dir / CHUNKS_FILENAME
        for name, value in (("FAST_CHUNKS_PATH", self.fast), ("OLD_CHUNKS_PATH", self.old)):
            p = mock.patch.object(retrieval, name, value)
            p.start()
            self.addCleanup(p.stop)
        retrieval._reset_state_for_tests()
        self.addCleanup(retrieval._reset_state_for_tests)

    def served_markers(self):
        return {c["chunk_id"].split("-")[0] for c in retrieval.load_chunks()}


class MissingAndEmptyTests(RetrievalCase):
    def test_no_index_files(self):
        self.assertEqual(retrieval.load_chunks(), [])
        self.assertEqual(retrieval.retrieve(QUERY), [])
        status = retrieval.get_index_status()
        self.assertFalse(status["index_ready"])
        self.assertEqual(status["chunks_loaded"], 0)
        self.assertIsNone(status["source"])

    def test_empty_file_is_never_treated_as_valid_index(self):
        self.old_dir.mkdir(parents=True)
        self.old.write_text("", encoding="utf-8")
        self.assertEqual(retrieval.load_chunks(), [])
        status = retrieval.get_index_status()
        self.assertFalse(status["index_ready"])
        self.assertIn("valid chunks", status["last_error"])

    def test_garbage_only_file_rejected(self):
        self.old_dir.mkdir(parents=True)
        self.old.write_text("nonsense\n{broken\n", encoding="utf-8")
        self.assertFalse(retrieval.get_index_status()["index_ready"])

    def test_status_is_fresh_without_prior_query(self):
        write_chunks(self.old, make_chunks("old"))
        self.assertTrue(retrieval.get_index_status()["index_ready"])


class PriorityAndCompatibilityTests(RetrievalCase):
    def test_old_index_path_alone_works(self):
        write_chunks(self.old, make_chunks("old"))
        self.assertEqual(self.served_markers(), {"old"})
        self.assertEqual(retrieval.get_index_status()["serving_index"], "index")
        self.assertTrue(retrieval.retrieve(QUERY))

    def test_fast_index_path_alone_works(self):
        write_chunks(self.fast, make_chunks("fast"))
        self.assertEqual(self.served_markers(), {"fast"})
        self.assertEqual(retrieval.get_index_status()["serving_index"], "fast")

    def test_fast_preferred_when_both_valid(self):
        write_chunks(self.old, make_chunks("old"))
        write_chunks(self.fast, make_chunks("fast"))
        self.assertEqual(self.served_markers(), {"fast"})

    def test_cold_start_invalid_fast_falls_back_but_reports_error(self):
        write_chunks(self.old, make_chunks("old"))
        self.fast_dir.mkdir(parents=True)
        self.fast.write_text("", encoding="utf-8")
        self.assertEqual(self.served_markers(), {"old"})
        status = retrieval.get_index_status()
        self.assertTrue(status["index_ready"])
        self.assertIn("index_fast", status["last_error"])  # rejection not hidden

    def test_old_active_then_valid_fast_appears_switches(self):
        write_chunks(self.old, make_chunks("old"))
        self.assertEqual(self.served_markers(), {"old"})
        write_chunks(self.fast, make_chunks("fast"))
        self.assertEqual(self.served_markers(), {"fast"})

    def test_active_fast_turns_invalid_does_not_fall_back_to_old(self):
        write_chunks(self.old, make_chunks("old"))
        write_chunks(self.fast, make_chunks("fast"))
        self.assertEqual(self.served_markers(), {"fast"})
        self.fast.write_text("", encoding="utf-8")
        self.assertEqual(self.served_markers(), {"fast"})  # last known-good, not stale old
        self.assertTrue(retrieval.get_index_status()["serving_stale"])


class ReloadTests(RetrievalCase):
    def test_cache_reload_after_publish_without_restart(self):
        write_chunks(self.old, make_chunks("old"))
        self.assertEqual(self.served_markers(), {"old"})
        publish_index(stage(self.old_dir, make_chunks("new", 9)), self.old_dir)
        self.assertEqual(self.served_markers(), {"new"})
        self.assertEqual(retrieval.get_index_status()["chunks_loaded"], 9)
        self.assertIsNone(retrieval.get_index_status()["last_error"])

    def test_cache_not_rebuilt_when_unchanged(self):
        write_chunks(self.old, make_chunks("old"))
        retrieval.load_chunks()
        with mock.patch.object(retrieval, "_build_state", side_effect=AssertionError("rebuilt")):
            retrieval.load_chunks()
            retrieval.retrieve(QUERY)

    def test_explicit_reload_endpoint_logic(self):
        write_chunks(self.old, make_chunks("old"))
        first = retrieval.reload_index()
        self.assertTrue(first["reloaded"])
        publish_index(stage(self.old_dir, make_chunks("new")), self.old_dir)
        second = retrieval.reload_index()
        self.assertTrue(second["reloaded"])
        self.assertEqual(second["serving_index"], "index")
        self.assertEqual(self.served_markers(), {"new"})

    def test_failed_reload_keeps_last_known_good(self):
        write_chunks(self.old, make_chunks("old"))
        self.assertEqual(self.served_markers(), {"old"})
        self.old.write_text("{corrupt\n", encoding="utf-8")  # simulate a bad in-place write
        result = retrieval.reload_index()
        self.assertFalse(result["reloaded"])
        self.assertTrue(result["index_ready"])
        self.assertEqual(self.served_markers(), {"old"})
        self.assertTrue(retrieval.retrieve(QUERY))
        self.assertTrue(result["last_error"])
        self.assertTrue(retrieval.get_index_status()["serving_stale"])

    def test_empty_file_after_good_load_keeps_serving(self):
        write_chunks(self.old, make_chunks("old"))
        self.assertEqual(self.served_markers(), {"old"})
        self.old.write_text("", encoding="utf-8")
        self.assertEqual(self.served_markers(), {"old"})
        self.assertTrue(retrieval.get_index_status()["last_error"])

    def test_deleted_file_after_good_load_keeps_serving(self):
        write_chunks(self.old, make_chunks("old"))
        self.assertEqual(self.served_markers(), {"old"})
        self.old.unlink()
        self.assertEqual(self.served_markers(), {"old"})
        self.assertTrue(retrieval.reload_index()["index_ready"])

    def test_bad_content_is_not_reparsed_on_every_request(self):
        write_chunks(self.old, make_chunks("old"))
        retrieval.load_chunks()
        self.old.write_text("{corrupt\n", encoding="utf-8")
        retrieval.load_chunks()  # records the failure once
        with mock.patch.object(retrieval, "_build_state", side_effect=AssertionError("retry")):
            retrieval.load_chunks()
            retrieval.retrieve(QUERY)

    def test_recovers_and_clears_error_when_fixed(self):
        write_chunks(self.old, make_chunks("old"))
        retrieval.load_chunks()
        self.old.write_text("{corrupt\n", encoding="utf-8")
        retrieval.load_chunks()
        self.assertTrue(retrieval.get_index_status()["last_error"])
        publish_index(stage(self.old_dir, make_chunks("fixed")), self.old_dir)
        self.assertEqual(self.served_markers(), {"fixed"})
        status = retrieval.get_index_status()
        self.assertIsNone(status["last_error"])
        self.assertFalse(status["serving_stale"])

    def test_failed_build_exception_keeps_state(self):
        write_chunks(self.old, make_chunks("old"))
        retrieval.load_chunks()
        write_chunks(self.old, make_chunks("new"))
        with mock.patch.object(retrieval, "BM25Okapi", side_effect=RuntimeError("bm25 boom")):
            result = retrieval.reload_index()
        self.assertFalse(result["reloaded"])
        self.assertEqual(self.served_markers(), {"old"})
        self.assertIn("bm25 boom", result["last_error"])


class LazyLegacyIndexTests(RetrievalCase):
    def test_improved_mode_does_not_build_legacy_bm25(self):
        write_chunks(self.old, make_chunks("improved"))
        original_bm25 = retrieval.BM25Okapi
        builds = []

        def build(corpus, *args, **kwargs):
            builds.append(1)
            return original_bm25(corpus, *args, **kwargs)

        with mock.patch.object(retrieval, "BM25Okapi", side_effect=build):
            retrieval.load_chunks()
            self.assertTrue(retrieval.retrieve(QUERY, mode="improved"))
            self.assertEqual(len(builds), 2)

    def test_legacy_mode_builds_once_and_remains_available(self):
        write_chunks(self.old, make_chunks("legacy"))
        original_bm25 = retrieval.BM25Okapi
        builds = []

        def build(corpus, *args, **kwargs):
            builds.append(1)
            return original_bm25(corpus, *args, **kwargs)

        with mock.patch.object(retrieval, "BM25Okapi", side_effect=build):
            retrieval.load_chunks()
            self.assertTrue(retrieval.retrieve(QUERY, mode="legacy"))
            self.assertEqual(len(builds), 3)
            self.assertTrue(retrieval.retrieve(QUERY, mode="legacy"))
            self.assertEqual(len(builds), 3)

    def test_improved_mode_fallback_builds_legacy_index_once(self):
        write_chunks(self.old, make_chunks("fallback"))
        original_bm25 = retrieval.BM25Okapi
        builds = []

        def build(corpus, *args, **kwargs):
            builds.append(1)
            return original_bm25(corpus, *args, **kwargs)

        with (
            mock.patch.object(retrieval.quality.QualityIndex, "build",
                              side_effect=RuntimeError("improved index unavailable")),
            mock.patch.object(retrieval, "BM25Okapi", side_effect=build),
        ):
            retrieval.load_chunks()
            self.assertFalse(retrieval.get_index_status()["improved_index_ready"])
            self.assertEqual(len(builds), 1)
            self.assertTrue(retrieval.retrieve(QUERY, mode="improved"))
            self.assertEqual(len(builds), 1)
            self.assertTrue(retrieval.retrieve(QUERY, mode="improved"))
            self.assertEqual(len(builds), 1)

    def test_concurrent_legacy_requests_build_index_once(self):
        write_chunks(self.old, make_chunks("concurrent"))
        retrieval.load_chunks()
        original_bm25 = retrieval.BM25Okapi
        builds = []
        build_lock = threading.Lock()
        barrier = threading.Barrier(8)
        results = []
        errors = []

        def build(corpus, *args, **kwargs):
            with build_lock:
                builds.append(1)
            return original_bm25(corpus, *args, **kwargs)

        def retrieve():
            try:
                barrier.wait(timeout=5)
                results.append(retrieval.retrieve(QUERY, mode="legacy"))
            except BaseException as exc:
                errors.append(exc)

        with mock.patch.object(retrieval, "BM25Okapi", side_effect=build):
            workers = [threading.Thread(target=retrieve) for _ in range(8)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=20)

        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 8)
        self.assertTrue(all(results))
        self.assertEqual(len(builds), 1)


class ServingStatusTests(RetrievalCase):
    """describe_serving backs the ingestion status: is the published index really served?"""

    def test_published_index_is_served(self):
        write_chunks(self.old, make_chunks("old"))
        retrieval.load_chunks()
        result = publish_index(stage(self.old_dir, make_chunks("new")), self.old_dir)
        retrieval.reload_index()
        info = retrieval.describe_serving(self.old, result.sha256)
        self.assertTrue(info["serving_published_index"])
        self.assertIsNone(info["serving_reason"])

    def test_higher_priority_fast_index_means_not_serving_published(self):
        write_chunks(self.fast, make_chunks("fast"))
        result = publish_index(stage(self.old_dir, make_chunks("new")), self.old_dir)
        retrieval.reload_index()
        info = retrieval.describe_serving(self.old, result.sha256)
        self.assertFalse(info["serving_published_index"])
        self.assertIn("higher-priority", info["serving_reason"])

    def test_failed_reload_means_not_serving_published(self):
        write_chunks(self.old, make_chunks("old"))
        retrieval.load_chunks()
        result = publish_index(stage(self.old_dir, make_chunks("new")), self.old_dir)
        with mock.patch.object(retrieval, "BM25Okapi", side_effect=RuntimeError("boom")):
            retrieval.reload_index()
        info = retrieval.describe_serving(self.old, result.sha256)
        self.assertFalse(info["serving_published_index"])
        self.assertIn("differs", info["serving_reason"])
        self.assertIn("boom", info["last_error"])

    def test_nothing_served(self):
        info = retrieval.describe_serving(self.old, "x")
        self.assertFalse(info["serving_published_index"])
        self.assertEqual(info["serving_reason"], "No index is being served.")


class ConcurrencyTests(RetrievalCase):
    def test_concurrent_retrieval_during_repeated_publishes(self):
        write_chunks(self.old, make_chunks("alpha"))
        retrieval.load_chunks()
        stop = threading.Event()
        errors: list[BaseException] = []
        inconsistent: list[set] = []
        counts = {"queries": 0, "nonempty": 0}
        lock = threading.Lock()

        def reader():
            try:
                while not stop.is_set():
                    results = retrieval.retrieve(QUERY, limit=5)
                    markers = {r["chunk_id"].split("-")[0] for r in results}
                    with lock:
                        counts["queries"] += 1
                        counts["nonempty"] += bool(results)
                        if len(markers) > 1:  # chunks from two indexes in one answer
                            inconsistent.append(markers)
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        def publisher():
            try:
                for i in range(12):
                    marker = "beta" if i % 2 == 0 else "alpha"
                    publish_index(stage(self.old_dir, make_chunks(marker)), self.old_dir, allow_shrink=True)
                    if i == 5:  # a rejected build mid-run must not disturb readers
                        try:
                            publish_index(stage(self.old_dir, None, raw=""), self.old_dir)
                        except Exception:  # noqa: BLE001
                            pass
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        readers = [threading.Thread(target=reader) for _ in range(6)]
        writer = threading.Thread(target=publisher)
        for t in readers:
            t.start()
        writer.start()
        writer.join(timeout=60)
        stop.set()
        for t in readers:
            t.join(timeout=10)

        self.assertFalse(writer.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(inconsistent, [])
        self.assertGreater(counts["queries"], 20)
        self.assertGreater(counts["nonempty"], 0)
        self.assertTrue(retrieval.get_index_status()["index_ready"])

    def test_concurrent_cold_start_builds_once(self):
        write_chunks(self.old, make_chunks("old"))
        real = retrieval._build_state
        builds = []

        def counting(*a, **k):
            builds.append(1)
            return real(*a, **k)

        errors = []
        with mock.patch.object(retrieval, "_build_state", side_effect=counting):
            def go():
                try:
                    retrieval.load_chunks()
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)

            threads = [threading.Thread(target=go) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=20)
        self.assertEqual(errors, [])
        self.assertEqual(len(builds), 1)


if __name__ == "__main__":
    unittest.main()
