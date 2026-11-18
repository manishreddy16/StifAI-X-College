"""Legacy retrieval must keep reproducing the original (Phase 1B) behaviour exactly.

``tests/fixtures/legacy_golden.json`` was frozen from the ORIGINAL retrieval code
before any change (see make_legacy_golden.py). Synthetic data only.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests.fixtures.heuristic_index import HEURISTIC_CHUNKS, HEURISTIC_QUERIES
from tests.fixtures.serving import serving, tmpdir, write_jsonl
from evaluation.synthetic.corpus import QUERIES, build_chunks_file

GOLDEN = json.loads((Path(__file__).parent / "fixtures" / "legacy_golden.json").read_text(encoding="utf-8"))


def _run(mod, queries, mode):
    return {q: [[h["chunk_id"], h["retrieval_score"]] for h in mod.retrieve(q, limit=10, mode=mode)] for q in queries}


class LegacyGoldenTests(unittest.TestCase):
    def test_heuristic_fixture_identical_to_original(self):
        with tmpdir() as d, serving(write_jsonl(d / "h.jsonl", HEURISTIC_CHUNKS)) as mod:
            got = _run(mod, HEURISTIC_QUERIES, "legacy")
        self.assertEqual(got, GOLDEN["heuristic"])

    def test_synthetic_corpus_identical_to_original(self):
        with tmpdir() as d:
            chunks = build_chunks_file(d / "syn")
            with serving(chunks) as mod:
                got = _run(mod, [q.text for q in QUERIES], "legacy")
        self.assertEqual(got, GOLDEN["synthetic"])

    def test_env_switch_selects_legacy_for_default_calls(self):
        import os
        from unittest import mock
        with tmpdir() as d, serving(write_jsonl(d / "h.jsonl", HEURISTIC_CHUNKS)) as mod:
            with mock.patch.dict(os.environ, {"RETRIEVAL_MODE": "legacy"}):
                self.assertEqual(mod.get_retrieval_mode(), "legacy")
                got = {q: [[h["chunk_id"], h["retrieval_score"]] for h in mod.retrieve(q, limit=10)]
                       for q in HEURISTIC_QUERIES}
        self.assertEqual(got, GOLDEN["heuristic"])


if __name__ == "__main__":
    unittest.main()
