"""Publishing, validation, rollback, locking and builder integration tests."""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tests._support import make_chunks, stage, write_chunks  # noqa: F401  (sets sys.path)

from ingestion import index_publisher as pub
from ingestion.index_publisher import (
    CHUNKS_FILENAME,
    IndexPublishError,
    IndexValidationError,
    list_backups,
    publish_index,
    read_publish_status,
    rollback_index,
)


class TempIndexCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.index_dir = self.root / "index"
        self.live = self.index_dir / CHUNKS_FILENAME

    def seed_live(self, marker="old", count=8) -> bytes:
        write_chunks(self.live, make_chunks(marker, count))
        return self.live.read_bytes()

    def staging_dirs(self):
        base = self.root / ".staging"
        return list(base.iterdir()) if base.exists() else []


class PublishTests(TempIndexCase):
    def test_publish_into_empty_dir_creates_live_index(self):
        staged = stage(self.index_dir, make_chunks("new"))
        result = publish_index(staged, self.index_dir)
        self.assertEqual(result.status, "published")
        self.assertEqual(result.chunks, 8)
        self.assertIsNone(result.previous_chunks)
        self.assertIsNone(result.backup)
        self.assertTrue(self.live.is_file())
        self.assertEqual(self.staging_dirs(), [])
        status = read_publish_status(self.index_dir)
        self.assertEqual(status["status"], "published")
        self.assertTrue(status["live_index_modified"])

    def test_publish_replaces_live_and_backs_up_previous(self):
        old_bytes = self.seed_live("old")
        result = publish_index(stage(self.index_dir, make_chunks("new")), self.index_dir)
        self.assertEqual(result.previous_chunks, 8)
        backups = list_backups(self.index_dir)
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), old_bytes)
        self.assertIn(b'"new-0"', self.live.read_bytes())
        self.assertNotIn(b'"old-0"', self.live.read_bytes())

    def test_empty_candidate_is_rejected_and_live_untouched(self):
        before = self.seed_live()
        staged = stage(self.index_dir, None, raw="")
        with self.assertRaises(IndexValidationError):
            publish_index(staged, self.index_dir)
        self.assertEqual(self.live.read_bytes(), before)
        self.assertEqual(self.staging_dirs(), [])
        status = read_publish_status(self.index_dir)
        self.assertEqual(status["status"], "rejected")
        self.assertFalse(status["live_index_modified"])
        self.assertEqual(list_backups(self.index_dir), [])

    def test_whitespace_only_and_text_less_rows_rejected(self):
        before = self.seed_live()
        raw = "\n\n" + json.dumps({"text": "   "}) + "\n" + json.dumps({"title": "x"}) + "\n"
        with self.assertRaises(IndexValidationError):
            publish_index(stage(self.index_dir, None, raw=raw), self.index_dir)
        self.assertEqual(self.live.read_bytes(), before)

    def test_missing_candidate_rejected(self):
        before = self.seed_live()
        with self.assertRaises(IndexValidationError):
            publish_index(self.root / "nope" / CHUNKS_FILENAME, self.index_dir)
        self.assertEqual(self.live.read_bytes(), before)

    def test_corrupt_candidate_rejected(self):
        before = self.seed_live()
        with self.assertRaises(IndexValidationError):
            publish_index(stage(self.index_dir, None, raw="{not json\n[1,2]\n"), self.index_dir)
        self.assertEqual(self.live.read_bytes(), before)

    def test_invalid_utf8_candidate_rejected(self):
        before = self.seed_live()
        staged = stage(self.index_dir, make_chunks("x"))
        staged.write_bytes(b"\xff\xfe\x00bad")
        with self.assertRaises(IndexValidationError):
            publish_index(staged, self.index_dir)
        self.assertEqual(self.live.read_bytes(), before)

    def test_too_many_invalid_lines_rejected_but_few_tolerated(self):
        rows = make_chunks("new", 20)
        good = "\n".join(json.dumps(r) for r in rows)
        publish_index(stage(self.index_dir, None, raw=good + "\nGARBAGE\n"), self.index_dir)  # 1/21 ok
        before = self.live.read_bytes()
        bad = good + "\n" + "\n".join(["GARBAGE"] * 10)  # 10/30 > 10%
        with self.assertRaises(IndexValidationError):
            publish_index(stage(self.index_dir, None, raw=bad), self.index_dir)
        self.assertEqual(self.live.read_bytes(), before)

    def test_min_chunks_enforced(self):
        before = self.seed_live()
        with self.assertRaises(IndexValidationError):
            publish_index(stage(self.index_dir, make_chunks("tiny", 2)), self.index_dir, min_chunks=5)
        self.assertEqual(self.live.read_bytes(), before)

    def test_shrink_guard_blocks_partial_build_unless_allowed(self):
        before = self.seed_live("old", 10)
        with self.assertRaises(IndexValidationError) as ctx:
            publish_index(stage(self.index_dir, make_chunks("tiny", 2)), self.index_dir)
        self.assertIn("partial", str(ctx.exception))
        self.assertEqual(self.live.read_bytes(), before)
        result = publish_index(
            stage(self.index_dir, make_chunks("tiny", 2)), self.index_dir, allow_shrink=True
        )
        self.assertEqual(result.chunks, 2)

    def test_failure_during_swap_leaves_live_index_intact(self):
        before = self.seed_live()
        staged = stage(self.index_dir, make_chunks("new"))
        real = pub._replace_with_retry

        def fail_only_live_swap(src, dst):
            if Path(dst) == self.live:
                raise IndexPublishError("disk")
            return real(src, dst)  # status-file writes etc. still work

        with mock.patch.object(pub, "_replace_with_retry", side_effect=fail_only_live_swap):
            with self.assertRaises(IndexPublishError):
                publish_index(staged, self.index_dir)
        self.assertEqual(self.live.read_bytes(), before)
        self.assertEqual(self.staging_dirs(), [])
        self.assertEqual(read_publish_status(self.index_dir)["status"], "failed")
        self.assertFalse(read_publish_status(self.index_dir)["live_index_modified"])

    def test_oserror_during_backup_aborts_before_swap(self):
        before = self.seed_live()
        staged = stage(self.index_dir, make_chunks("new"))
        with mock.patch.object(pub, "_make_backup", side_effect=OSError("no space")):
            with self.assertRaises(IndexPublishError):
                publish_index(staged, self.index_dir)
        self.assertEqual(self.live.read_bytes(), before)

    def test_post_publish_verification_failure_restores_previous(self):
        before = self.seed_live()
        staged = stage(self.index_dir, make_chunks("new"))
        real = pub.sha256_of
        calls = {"n": 0}

        def flaky(path):
            calls["n"] += 1
            # 1st call validates the candidate; 2nd verifies the published file.
            return real(path) if calls["n"] == 1 else "0" * 64

        with mock.patch.object(pub, "sha256_of", side_effect=flaky):
            with self.assertRaises(IndexPublishError) as ctx:
                publish_index(staged, self.index_dir)
        self.assertIn("restored", str(ctx.exception))
        self.assertEqual(self.live.read_bytes(), before)
        self.assertFalse(read_publish_status(self.index_dir)["live_index_modified"])

    def test_post_publish_verification_failure_without_previous_removes_bad_file(self):
        staged = stage(self.index_dir, make_chunks("new"))
        real = pub.sha256_of
        calls = {"n": 0}

        def flaky(path):
            calls["n"] += 1
            return real(path) if calls["n"] == 1 else "0" * 64

        with mock.patch.object(pub, "sha256_of", side_effect=flaky):
            with self.assertRaises(IndexPublishError):
                publish_index(staged, self.index_dir)
        self.assertFalse(self.live.exists())

    def test_old_backups_are_pruned(self):
        self.seed_live("v0")
        for i in range(1, 6):
            publish_index(stage(self.index_dir, make_chunks(f"v{i}")), self.index_dir, keep_backups=3)
            time.sleep(0.002)
        self.assertEqual(len(list_backups(self.index_dir)), 3)

    def test_publish_lock_blocks_concurrent_publish(self):
        before = self.seed_live()
        self.index_dir.joinpath(pub.LOCK_FILENAME).write_text("held")
        with self.assertRaises(IndexPublishError):
            publish_index(stage(self.index_dir, make_chunks("new")), self.index_dir)
        self.assertEqual(self.live.read_bytes(), before)
        self.assertTrue(self.index_dir.joinpath(pub.LOCK_FILENAME).exists())  # not ours to remove

    def test_stale_lock_is_cleared(self):
        self.seed_live()
        lock = self.index_dir / pub.LOCK_FILENAME
        lock.write_text("dead process")
        old = time.time() - pub.STALE_LOCK_SECONDS - 60
        os.utime(lock, (old, old))
        result = publish_index(stage(self.index_dir, make_chunks("new")), self.index_dir)
        self.assertEqual(result.status, "published")
        self.assertFalse(lock.exists())

    def test_lock_released_after_publish_and_after_failure(self):
        self.seed_live()
        publish_index(stage(self.index_dir, make_chunks("new")), self.index_dir)
        self.assertFalse((self.index_dir / pub.LOCK_FILENAME).exists())
        with self.assertRaises(IndexValidationError):
            publish_index(stage(self.index_dir, None, raw=""), self.index_dir)
        self.assertFalse((self.index_dir / pub.LOCK_FILENAME).exists())


class RollbackTests(TempIndexCase):
    def test_rollback_restores_previous_and_is_itself_reversible(self):
        old_bytes = self.seed_live("old")
        publish_index(stage(self.index_dir, make_chunks("new")), self.index_dir)
        new_bytes = self.live.read_bytes()
        result = rollback_index(self.index_dir)
        self.assertEqual(result.status, "rolled_back")
        self.assertEqual(self.live.read_bytes(), old_bytes)
        status = read_publish_status(self.index_dir)
        self.assertEqual(status["status"], "rolled_back")
        # the index replaced by the rollback was backed up, so we can go forward again
        rollback_index(self.index_dir)
        self.assertEqual(self.live.read_bytes(), new_bytes)

    def test_rollback_without_backups_fails_and_keeps_live(self):
        before = self.seed_live()
        with self.assertRaises(IndexPublishError):
            rollback_index(self.index_dir)
        self.assertEqual(self.live.read_bytes(), before)

    def test_rollback_to_named_backup(self):
        self.seed_live("v0")
        first = self.live.read_bytes()
        publish_index(stage(self.index_dir, make_chunks("v1")), self.index_dir)
        time.sleep(0.002)
        publish_index(stage(self.index_dir, make_chunks("v2")), self.index_dir)
        oldest = list_backups(self.index_dir)[0]
        rollback_index(self.index_dir, backup=oldest.name)
        self.assertEqual(self.live.read_bytes(), first)

    def test_corrupt_backup_is_not_activated(self):
        before = self.seed_live("old")
        publish_index(stage(self.index_dir, make_chunks("new")), self.index_dir)
        current = self.live.read_bytes()
        list_backups(self.index_dir)[-1].write_text("", encoding="utf-8")  # corrupt latest backup
        with self.assertRaises(IndexValidationError):
            rollback_index(self.index_dir)
        self.assertEqual(self.live.read_bytes(), current)
        self.assertNotEqual(current, before)

    def test_unknown_backup_name_rejected(self):
        self.seed_live()
        with self.assertRaises(IndexPublishError):
            rollback_index(self.index_dir, backup="chunks-does-not-exist.jsonl")


class BuildFastIndexTests(TempIndexCase):
    """build_fast_index.build_index must never overwrite a live index unsafely."""

    def setUp(self):
        super().setUp()
        from ingestion import build_fast_index

        self.bfi = build_fast_index
        self.source = self.root / "processed_fast"
        self.source.mkdir()
        self.reports = self.root / "reports"
        self.index_dir = self.root / "index_fast"
        self.live = self.index_dir / CHUNKS_FILENAME

    def add_docs(self, n, text=None):
        for i in range(n):
            body = text if text is not None else f"Synthetic document {i} about hostel and library. " * 20 + f" unique {i}"
            (self.source / f"d{i}.json").write_text(
                json.dumps({"doc_id": f"d{i}", "url": f"https://example.test/{i}", "title": f"T{i}", "text": body}),
                encoding="utf-8",
            )

    def build(self, **kw):
        return self.bfi.build_index(self.source, self.index_dir, self.reports, **kw)

    def test_builds_and_publishes(self):
        self.add_docs(4)
        report = self.build()
        self.assertTrue(report["published"])
        self.assertTrue(self.live.is_file())
        self.assertTrue((self.reports / "fast_index_report.json").is_file())

    def test_no_source_documents_does_not_touch_live_index(self):
        self.add_docs(3)
        self.build()
        before = self.live.read_bytes()
        report_before = (self.reports / "fast_index_report.json").read_bytes()
        for f in self.source.glob("*.json"):
            f.unlink()
        with self.assertRaises(IndexValidationError):
            self.build()
        self.assertEqual(self.live.read_bytes(), before)
        self.assertEqual((self.reports / "fast_index_report.json").read_bytes(), report_before)

    def test_all_empty_documents_produce_no_publish(self):
        self.add_docs(3)
        self.build()
        before = self.live.read_bytes()
        for f in self.source.glob("*.json"):
            f.unlink()
        self.add_docs(3, text="   ")
        with self.assertRaises(IndexValidationError):
            self.build()
        self.assertEqual(self.live.read_bytes(), before)
        attempt = json.loads((self.reports / "fast_index_last_attempt.json").read_text(encoding="utf-8"))
        self.assertFalse(attempt["published"])
        self.assertEqual(attempt["status"], "not_published")
        self.assertEqual(list((self.root / ".staging").iterdir()), [])

    def test_partial_build_blocked_by_shrink_guard(self):
        self.add_docs(10)
        self.build()
        before = self.live.read_bytes()
        for f in list(self.source.glob("*.json"))[:-1]:
            f.unlink()
        with self.assertRaises(IndexValidationError):
            self.build()
        self.assertEqual(self.live.read_bytes(), before)

    def test_crash_mid_build_leaves_live_index_and_cleans_staging(self):
        self.add_docs(3)
        self.build()
        before = self.live.read_bytes()
        with mock.patch.object(self.bfi, "split_text", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.build()
        self.assertEqual(self.live.read_bytes(), before)
        self.assertEqual(list((self.root / ".staging").iterdir()), [])


class RunIngestionPublishTests(TempIndexCase):
    """run_ingestion with a fake crawler: no network, synthetic pages only."""

    def setUp(self):
        super().setUp()
        from ingestion import run_ingestion as ri

        self.ri = ri
        data = self.root / "data"
        patches = {
            "DATA": data, "RAW": data / "raw", "PROCESSED": data / "processed",
            "INDEX": data / "index", "SOURCES": data / "sources", "REPORTS": data / "reports",
        }
        for name, value in patches.items():
            p = mock.patch.object(ri, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(ri, "ROOT", self.root)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(ri, "download_pdfs", return_value=[])
        p.start()
        self.addCleanup(p.stop)
        self.index_dir = data / "index"
        self.live = self.index_dir / CHUNKS_FILENAME

    def run_with_pages(self, pages):
        class FakeCrawler:
            errors = []

            def __init__(self, *a, **k):
                pass

            def crawl(self):
                for page in pages:
                    yield dict(page)

        with mock.patch.object(self.ri, "SiteCrawler", FakeCrawler):
            return self.ri.run_ingestion("https://example.test/", 5)

    def page(self, i, text=None):
        return {"url": f"https://example.test/{i}", "title": f"P{i}", "content_type": "text/html",
                "text": text if text is not None else f"Synthetic page {i}. " * 40, "links": []}

    def test_good_run_publishes_with_sha(self):
        report = self.run_with_pages([self.page(i) for i in range(3)])
        self.assertTrue(report["published"])
        self.assertTrue(report["sha256"])
        self.assertTrue(self.live.is_file())

    def test_empty_crawl_does_not_destroy_existing_index(self):
        self.run_with_pages([self.page(i) for i in range(3)])
        before = self.live.read_bytes()
        report = self.run_with_pages([])
        self.assertFalse(report["published"])
        self.assertEqual(report["status"], "not_published")
        self.assertEqual(self.live.read_bytes(), before)
        self.assertTrue((self.root / "data" / "reports" / "ingestion_last_attempt.json").is_file())

    def test_blank_pages_do_not_destroy_existing_index(self):
        self.run_with_pages([self.page(i) for i in range(3)])
        before = self.live.read_bytes()
        report = self.run_with_pages([self.page(i, text="  ") for i in range(3)])
        self.assertFalse(report["published"])
        self.assertEqual(self.live.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
