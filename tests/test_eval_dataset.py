from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests._eval_support import rec, verified, write_dataset

from evaluation.dataset import CATEGORIES, DatasetError, load_dataset, normalize_url

ROOT = Path(__file__).resolve().parents[1]
SHIPPED = ROOT / "evaluation" / "dataset" / "svce_eval_questions.jsonl"


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def load(self, records):
        return load_dataset(write_dataset(self.dir / "d.jsonl", records))

    def errors(self, records):
        with self.assertRaises(DatasetError) as ctx:
            self.load(records)
        return ctx.exception.errors

    def test_valid_mixed_dataset(self):
        ds = self.load([rec(id="A"), verified(id="B")])
        self.assertEqual([r.id for r in ds.records], ["A", "B"])
        self.assertFalse(ds.by_id()["A"].is_verified)
        self.assertTrue(ds.by_id()["B"].is_retrieval_scorable)
        self.assertEqual(len(ds.sha256), 64)

    def test_unverified_records_are_never_scorable(self):
        for status in ("needs_ground_truth", "unverified"):
            r = self.load([rec(verification_status=status)]).records[0]
            self.assertFalse(r.is_retrieval_scorable)
            self.assertFalse(r.is_verified)

    def test_expected_sources_rejected_on_unverified(self):
        errs = self.errors([rec(expected_sources=["https://example.test/x"])])
        self.assertTrue(any("only verified records" in e for e in errs))

    def test_expected_keywords_rejected_on_unverified(self):
        self.assertTrue(self.errors([rec(expected_keywords=["x"])]))

    def test_unverified_must_keep_answerable_unknown(self):
        self.assertTrue(any("answerable" in e for e in self.errors([rec(answerable="yes")])))

    def test_verified_requires_metadata_and_sources(self):
        self.assertTrue(self.errors([verified(verified_by="")]))
        self.assertTrue(self.errors([verified(verified_on="31/01/2026")]))
        self.assertTrue(self.errors([verified(answerable="unknown")]))
        self.assertTrue(self.errors([verified(expected_sources=[])]))

    def test_verified_unanswerable_has_no_sources_and_is_not_scorable(self):
        r = self.load([verified(answerable="no", expected_sources=[])]).records[0]
        self.assertTrue(r.is_verified_unanswerable)
        self.assertFalse(r.is_retrieval_scorable)
        self.assertTrue(self.errors([verified(answerable="no")]))

    def test_context_dependent_verified_is_not_scorable(self):
        r = self.load([verified(question_kind="context_dependent")]).records[0]
        self.assertFalse(r.is_retrieval_scorable)

    def test_bad_category_kind_status_id(self):
        self.assertTrue(self.errors([rec(category="Sports")]))
        self.assertTrue(self.errors([rec(question_kind="x")]))
        self.assertTrue(self.errors([rec(verification_status="maybe")]))
        self.assertTrue(self.errors([rec(id="bad id!")]))
        self.assertTrue(self.errors([rec(question="  ")]))

    def test_duplicate_ids(self):
        self.assertTrue(any("duplicate" in e for e in self.errors([rec(id="A"), rec(id="A")])))

    def test_invalid_json_and_all_errors_reported(self):
        path = self.dir / "bad.jsonl"
        path.write_text('{"id": "A"\n[1]\n' + '{"id":"B","question":"q","category":"Nope"}\n', encoding="utf-8")
        with self.assertRaises(DatasetError) as ctx:
            load_dataset(path)
        self.assertGreaterEqual(len(ctx.exception.errors), 3)

    def test_empty_and_missing_dataset(self):
        empty = self.dir / "e.jsonl"
        empty.write_text("\n\n# only comments\n", encoding="utf-8")
        with self.assertRaises(DatasetError):
            load_dataset(empty)
        with self.assertRaises(DatasetError):
            load_dataset(self.dir / "missing.jsonl")

    def test_non_object_and_bad_list_types(self):
        self.assertTrue(self.errors(["just a string"]))
        self.assertTrue(self.errors([rec(candidate_sources="not-a-list")]))

    def test_normalize_url(self):
        self.assertEqual(normalize_url("HTTPS://www.Example.test/a/"), "example.test/a")
        self.assertEqual(normalize_url("http://example.test/a?id=1"), "example.test/a?id=1")
        self.assertNotEqual(normalize_url("https://e.test/a?id=1"), normalize_url("https://e.test/a?id=2"))
        self.assertEqual(normalize_url(""), "")


class ShippedDatasetTests(unittest.TestCase):
    def test_shipped_dataset_valid_and_honest(self):
        ds = load_dataset(SHIPPED)
        self.assertEqual(len(ds.records), 20)
        self.assertEqual(len({r.id for r in ds.records}), 20)
        self.assertTrue(all(r.category in CATEGORIES for r in ds.records))
        # No ground truth has been verified: nothing may be scorable or carry expected answers.
        self.assertEqual(sum(r.is_verified for r in ds.records), 0)
        self.assertTrue(all(not r.expected_sources and not r.expected_keywords for r in ds.records))
        self.assertEqual(set(r.category for r in ds.records), set(CATEGORIES))

    def test_template_record_is_valid(self):
        ds = load_dataset(ROOT / "evaluation" / "dataset" / "template_record.jsonl")
        self.assertEqual(ds.records[0].verification_status, "needs_ground_truth")


if __name__ == "__main__":
    unittest.main()
