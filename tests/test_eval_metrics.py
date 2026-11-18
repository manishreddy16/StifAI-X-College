from __future__ import annotations

import unittest

from tests._eval_support import verified

from evaluation.dataset import load_dataset  # noqa: F401
from evaluation.dataset import _parse_record
from evaluation.metrics import aggregate, score_question


def R(**kw):
    return _parse_record(verified(**kw))


def results(*urls):
    return [{"url": u, "doc_id": f"d{i}"} for i, u in enumerate(urls)]


A, B, C = "https://example.test/a", "https://example.test/b", "https://example.test/c"


class MetricTests(unittest.TestCase):
    def test_rank_one(self):
        s = score_question(R(expected_sources=[A]), results(A, B, C))
        self.assertEqual((s.first_rank, s.recall_at(1), s.hit_at(1), s.reciprocal_rank), (1, 1.0, 1.0, 1.0))

    def test_rank_three(self):
        s = score_question(R(expected_sources=[A]), results(B, C, A))
        self.assertEqual(s.first_rank, 3)
        self.assertEqual((s.recall_at(1), s.recall_at(3), s.recall_at(5)), (0.0, 1.0, 1.0))
        self.assertAlmostEqual(s.reciprocal_rank, 1 / 3)

    def test_rank_five_and_miss(self):
        s = score_question(R(expected_sources=[A]), results(B, C, B, C, A))
        self.assertEqual((s.recall_at(3), s.recall_at(5)), (0.0, 1.0))
        miss = score_question(R(expected_sources=[A]), results(B, C))
        self.assertEqual((miss.first_rank, miss.recall_at(5), miss.reciprocal_rank), (None, 0.0, 0.0))

    def test_multiple_expected_sources_fractional_recall(self):
        s = score_question(R(expected_sources=[A, B]), results(A, C, B))
        self.assertEqual(s.recall_at(1), 0.5)
        self.assertEqual(s.recall_at(3), 1.0)
        self.assertEqual(s.hit_at(1), 1.0)
        partial = score_question(R(expected_sources=[A, B]), results(A, C, C))
        self.assertEqual(partial.recall_at(5), 0.5)

    def test_url_normalisation_in_matching(self):
        s = score_question(R(expected_sources=["https://www.example.test/a/"]), results("http://example.test/a"))
        self.assertEqual(s.first_rank, 1)

    def test_doc_id_matching(self):
        s = score_question(R(expected_sources=[], expected_doc_ids=["d1"]), results(A, B))
        self.assertEqual(s.first_rank, 2)

    def test_empty_results(self):
        s = score_question(R(expected_sources=[A]), [])
        self.assertEqual(s.first_rank, None)

    def test_aggregate_mrr_and_means(self):
        scores = [score_question(R(id="1", expected_sources=[A]), results(A)),
                  score_question(R(id="2", expected_sources=[A]), results(B, A)),
                  score_question(R(id="3", expected_sources=[A]), results(B, C))]
        agg = aggregate(scores)
        self.assertEqual(agg["n"], 3)
        self.assertAlmostEqual(agg["mrr"], (1 + 0.5 + 0) / 3)
        self.assertAlmostEqual(agg["recall@1"], 1 / 3)
        self.assertAlmostEqual(agg["recall@3"], 2 / 3)
        self.assertAlmostEqual(agg["hit@5"], 2 / 3)

    def test_aggregate_of_nothing_is_none_not_zero(self):
        agg = aggregate([])
        self.assertEqual(agg["n"], 0)
        self.assertTrue(all(v is None for k, v in agg.items() if k != "n"))

    def test_unscorable_record_rejected(self):
        with self.assertRaises(ValueError):
            score_question(R(answerable="no", expected_sources=[]), results(A))


if __name__ == "__main__":
    unittest.main()
