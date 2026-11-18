"""Retrieval-quality unit tests (SYNTHETIC data only - no real college index).

Two layers:
* pure unit tests of ``api/retrieval_quality.py`` (tokeniser, stemmer, synonyms,
  coverage, phrase and near-duplicate logic) - no index, no BM25 needed;
* behaviour tests of ``retrieve(..., mode=...)`` on the synthetic corpus
  (``evaluation/synthetic``), asserting each defect class found in the audit is fixed
  and that the known, documented limitations are still limitations.

Assertions are deliberately limited to rank-1 / membership-in-top-k so they hold with
the real ``rank_bm25`` and with the small BM25 stand-in from ``tests/_support``.
A passing result proves behaviour on the synthetic corpus, NOT accuracy on SVCE data.
"""

from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from tests import _support  # noqa: F401  (installs the BM25 stand-in only if rank_bm25 is absent)
from tests.fixtures.serving import serving, tmpdir, write_jsonl

from api import retrieval
from api import retrieval_quality as rq
from evaluation.synthetic.corpus import BASE, QUERIES, build_chunks_file

Q = {q.id: q for q in QUERIES}


def urls(hits):
    return [h["url"].replace(BASE, "") for h in hits]


class NormalisationTests(unittest.TestCase):
    def test_degree_names_are_distinct_tokens(self):
        self.assertEqual(rq.tokenize("B.Tech"), ["btech"])
        self.assertEqual(rq.tokenize("M.Tech"), ["mtech"])
        self.assertNotEqual(rq.tokenize("B.Tech"), rq.tokenize("M.Tech"))

    def test_degree_spelling_variants_agree(self):
        for variant in ("B.Tech", "B Tech", "b-tech", "BTech", "B. Tech."):
            self.assertEqual(rq.tokenize(variant), ["btech"], variant)

    def test_multi_dot_degrees(self):
        self.assertEqual(rq.tokenize("M.B.A. and Ph.D."), ["mba", "phd"])

    def test_email_wifi_joined(self):
        self.assertEqual(rq.tokenize("e-mail"), ["email"])
        self.assertEqual(rq.tokenize("Wi-Fi"), ["wifi"])

    def test_normalisation_can_be_disabled(self):
        cfg = rq.QualityConfig(normalize_degrees=False)
        self.assertNotIn("btech", rq.tokenize("B.Tech", cfg))

    def test_stop_words_and_single_letters_dropped(self):
        self.assertEqual(rq.tokenize("What is the library?"), ["library"])
        self.assertEqual(rq.tokenize("a b c"), [])

    def test_keep_stop(self):
        self.assertIn("the", rq.tokenize("the library", keep_stop=True))


class StemTests(unittest.TestCase):
    def test_plurals(self):
        self.assertEqual(rq.stem("fees"), "fee")
        self.assertEqual(rq.stem("scholarships"), "scholarship")
        self.assertEqual(rq.stem("facilities"), "facility")
        self.assertEqual(rq.stem("classes"), "class")
        self.assertEqual(rq.stem("branches"), "branch")

    def test_conservative_no_overstemming(self):
        for word in ("campus", "class", "analysis", "bus", "gas", "mess", "ece", "cse"):
            self.assertEqual(rq.stem(word), word, word)

    def test_stem_is_idempotent_enough_for_both_sides(self):
        # the same function is applied to query and document, so equal inputs stay equal
        self.assertEqual(rq.stem("fees"), rq.stem("fee"))

    def test_non_ascii_and_digits_untouched(self):
        self.assertEqual(rq.stem("హాస్టల్"), "హాస్టల్")
        self.assertEqual(rq.stem("2024s"), "2024s")


class UnicodeTests(unittest.TestCase):
    def test_hindi_and_telugu_queries_yield_tokens(self):
        self.assertTrue(rq.tokenize("छात्रावास शुल्क"))
        self.assertEqual(len(rq.tokenize("హాస్టల్ ఫీజు")), 2)

    def test_combining_marks_do_not_split_words(self):
        self.assertEqual(rq.tokenize("प्रवेश"), ["प्रवेश"])
        self.assertEqual(rq.tokenize("ప్రవేశాలు"), ["ప్రవేశాలు"])

    def test_legacy_tokenizer_loses_indic_text(self):
        # documents the defect the quality layer fixes
        self.assertEqual(retrieval._tokens("छात्रावास शुल्क హాస్టల్ ఫీజు"), [])
        self.assertEqual(rq.tokenize("छात्रावास शुल्क", rq.QualityConfig(unicode_tokens=False)), [])

    def test_mixed_script_text(self):
        self.assertEqual(rq.tokenize("hostel హాస్టల్ fee"), ["hostel", "హాస్టల్", "fee"])


class UrlTokenTests(unittest.TestCase):
    def test_path_words(self):
        self.assertEqual(rq.url_tokens("https://example.test/placements/statistics-2023-24"),
                         ["placement", "statistic", "2023", "24"])

    def test_extensions_and_host_ignored(self):
        self.assertEqual(rq.url_tokens("https://svce.edu.in/contactus.php"), ["contactus"])
        self.assertNotIn("php", rq.url_tokens("https://svce.edu.in/contactus.php"))
        self.assertNotIn("svce", rq.url_tokens("https://svce.edu.in/contactus.php"))

    def test_empty_and_none_like(self):
        self.assertEqual(rq.url_tokens(""), [])
        self.assertEqual(rq.url_tokens(None), [])

    def test_query_and_fragment_handled(self):
        toks = rq.url_tokens("https://example.test/fees/structure?print=1#top")
        self.assertIn("fee", toks)
        self.assertNotIn("top", toks)


class SynonymTests(unittest.TestCase):
    def setUp(self):
        self.cfg = rq.QualityConfig()
        self.map = rq.SynonymMap(rq.DEFAULT_SYNONYM_GROUPS, self.cfg)

    def test_abbreviation_expands_to_phrase(self):
        exp = self.map.expand(rq.tokenize("CSE labs", self.cfg))
        self.assertTrue(any(("computer", "science") in e.alternatives for e in exp))

    def test_phrase_expands_to_abbreviation(self):
        exp = self.map.expand(rq.tokenize("computer science department", self.cfg))
        self.assertTrue(any(("cse",) in e.alternatives for e in exp))

    def test_unrelated_query_has_no_expansion(self):
        self.assertEqual(self.map.expand(rq.tokenize("pizza", self.cfg)), [])

    def test_custom_file_extends_defaults(self):
        with tmpdir() as d:
            f = d / "syn.json"
            f.write_text(json.dumps([["cafeteria", "canteen"]]), encoding="utf-8")
            groups = rq.load_synonym_groups(f)
        self.assertIn(("cafeteria", "canteen"), groups)
        self.assertEqual(groups[: len(rq.DEFAULT_SYNONYM_GROUPS)], rq.DEFAULT_SYNONYM_GROUPS)

    def test_missing_synonym_file_is_fine(self):
        with tmpdir() as d:
            self.assertEqual(rq.load_synonym_groups(d / "nope.json"), rq.DEFAULT_SYNONYM_GROUPS)

    def test_malformed_synonym_file_ignored(self):
        with tmpdir() as d:
            for body in ("{not json", json.dumps({"a": 1}), json.dumps([["only-one"], "str", [1, 2]])):
                f = d / "bad.json"
                f.write_text(body, encoding="utf-8")
                with self.assertLogs("api.retrieval_quality", level="WARNING"):
                    groups = rq.load_synonym_groups(f)
                self.assertEqual(groups, rq.DEFAULT_SYNONYM_GROUPS)

    def test_env_var_selects_file(self):
        with tmpdir() as d:
            f = d / "syn.json"
            f.write_text(json.dumps([["aaa", "bbb"]]), encoding="utf-8-sig")  # BOM tolerated
            with mock.patch.dict(os.environ, {rq.SYNONYMS_FILE_ENV: str(f)}):
                self.assertIn(("aaa", "bbb"), rq.load_synonym_groups())


class ConfigTests(unittest.TestCase):
    def test_min_coverage_env(self):
        with mock.patch.dict(os.environ, {"RETRIEVAL_MIN_COVERAGE": "0.4"}):
            self.assertEqual(rq.QualityConfig.from_env().min_coverage, 0.4)

    def test_min_coverage_env_invalid_values_ignored(self):
        for raw in ("abc", "1.5", "-0.1"):
            with mock.patch.dict(os.environ, {"RETRIEVAL_MIN_COVERAGE": raw}):
                with self.assertLogs("api.retrieval_quality", level="WARNING"):
                    self.assertEqual(rq.QualityConfig.from_env().min_coverage, rq.QualityConfig().min_coverage)

    def test_baseline_lexical_turns_everything_off(self):
        cfg = rq.QualityConfig.baseline_lexical()
        for flag in ("normalize_degrees", "unicode_tokens", "stemming", "synonyms",
                     "field_weighting", "phrase_bonus", "relevance_floor", "diversity"):
            self.assertFalse(getattr(cfg, flag), flag)


CHUNKS = [
    {"chunk_id": "a", "doc_id": "a", "title": "Library", "url": "https://x.test/library",
     "text": "Library borrowing period is fourteen days. Students may borrow books."},
    {"chunk_id": "b", "doc_id": "b", "title": "Hostel", "url": "https://x.test/hostel",
     "text": "Hostel fees are payable each semester. Mess charges apply."},
    {"chunk_id": "c", "doc_id": "c", "title": "Home", "url": "https://x.test/",
     "text": "Home campus life nav links welcome to the campus"},
    {"chunk_id": "d", "doc_id": "d", "title": "Library copy", "url": "https://x.test/library?print=1",
     "text": "Library borrowing period is fourteen days. Students may borrow books."},
] + [
    {"chunk_id": f"f{i}", "doc_id": f"f{i}", "title": f"Filler {i}", "url": f"https://x.test/filler/{i}",
     "text": f"Unrelated filler paragraph number {i} about gardens, seminars and notices."}
    for i in range(12)
]


class QualityIndexTests(unittest.TestCase):
    def setUp(self):
        self.qi = rq.QualityIndex.build(CHUNKS, _bm25(), rq.QualityConfig(), synonym_groups=())

    def test_build_sizes(self):
        self.assertEqual(self.qi.n_chunks, len(CHUNKS))
        self.assertEqual(len(self.qi.doc_sets), len(CHUNKS))

    def test_analyze_dedups_and_orders(self):
        a = self.qi.analyze("library library borrowing")
        self.assertEqual(a.tokens, ("library", "borrowing"))
        self.assertEqual(a.bigrams, (("library", "library"), ("library", "borrowing")))

    def test_empty_query_has_no_tokens(self):
        self.assertEqual(self.qi.analyze("the of and").tokens, ())

    def test_coverage_full_and_partial(self):
        a = self.qi.analyze("library borrowing")
        cov, distinctive = self.qi.coverage(0, a)
        self.assertAlmostEqual(cov, 1.0)
        self.assertTrue(distinctive)
        cov_b, _ = self.qi.coverage(1, a)
        self.assertLess(cov_b, 0.15)

    def test_coverage_ignores_filler_words(self):
        a = self.qi.analyze("best library")
        cov, _ = self.qi.coverage(0, a)
        self.assertAlmostEqual(cov, 1.0)

    def test_unknown_term_gets_max_idf(self):
        a = self.qi.analyze("zzzunknown library")
        cov, _ = self.qi.coverage(0, a)
        self.assertLess(cov, 0.6)  # an unmatched rare term weighs heavily

    def test_phrase_match_counts_adjacent_words(self):
        a = self.qi.analyze("borrowing period")
        self.assertEqual(self.qi.phrase_matches(0, a), 1)
        a2 = self.qi.analyze("period borrowing")
        self.assertEqual(self.qi.phrase_matches(0, a2), 0)

    def test_phrase_bonus_off(self):
        qi = rq.QualityIndex.build(CHUNKS, _bm25(), rq.QualityConfig(phrase_bonus=False), synonym_groups=())
        self.assertEqual(qi.phrase_matches(0, qi.analyze("borrowing period")), 0)

    def test_near_duplicate(self):
        self.assertTrue(self.qi.near_duplicate(0, 3))
        self.assertFalse(self.qi.near_duplicate(0, 1))

    def test_base_scores_non_negative_and_sized(self):
        scores = self.qi.base_scores(self.qi.analyze("library borrowing"))
        self.assertEqual(len(scores), len(CHUNKS))
        self.assertTrue(all(s >= 0 for s in scores))

    def test_empty_text_chunk_does_not_break_build(self):
        rows = CHUNKS + [{"chunk_id": "e", "doc_id": "e", "title": "", "url": "", "text": ""}]
        qi = rq.QualityIndex.build(rows, _bm25(), rq.QualityConfig(), synonym_groups=())
        self.assertEqual(qi.n_chunks, len(CHUNKS) + 1)

    def test_synonym_expansion_matches_without_literal_term(self):
        rows = [{"chunk_id": "x", "doc_id": "x", "title": "Computer Science and Engineering",
                 "url": "https://x.test/d", "text": "Laboratories of the computer science department."},
                {"chunk_id": "y", "doc_id": "y", "title": "Other", "url": "https://x.test/o",
                 "text": "Other unrelated words entirely here."}]
        qi = rq.QualityIndex.build(rows, _bm25(), rq.QualityConfig())
        a = qi.analyze("CSE laboratories")
        cov, distinctive = qi.coverage(0, a)
        self.assertGreater(cov, 0.9)
        self.assertTrue(distinctive)


def _bm25():
    from api.retrieval import BM25Okapi
    return BM25Okapi


NAV_ROWS = [{"chunk_id": "t", "doc_id": "t", "title": "Training and Placement Cell", "url": "https://x.test/placements",
             "text": "Home | Admissions | Placements | Contact. Recruiters visit the campus every year."}] + [
    {"chunk_id": f"n{i}", "doc_id": f"n{i}", "title": f"Page {i}", "url": f"https://x.test/p/{i}",
     "text": f"Home | Admissions | Placements | Contact. Unrelated gardens text {i}."} for i in range(30)]


class MetaDistinctiveTests(unittest.TestCase):
    """Audit F12 fix: a title/URL match makes a frequent (navigation) word count as distinctive."""

    def _cov(self, cfg, index, query="placements"):
        qi = rq.QualityIndex.build(NAV_ROWS, _bm25(), cfg, synonym_groups=())
        return qi.coverage(index, qi.analyze(query))

    def test_nav_word_is_not_distinctive_without_title_match(self):
        cov, distinctive = self._cov(rq.QualityConfig(), 1)       # nav-only page
        self.assertEqual(cov, 1.0)
        self.assertFalse(distinctive)

    def test_title_or_url_match_is_distinctive(self):
        cov, distinctive = self._cov(rq.QualityConfig(), 0)       # page titled Placement
        self.assertEqual(cov, 1.0)
        self.assertTrue(distinctive)

    def test_switch_off_restores_previous_behaviour(self):
        _, distinctive = self._cov(rq.QualityConfig(meta_match_distinctive=False), 0)
        self.assertFalse(distinctive)

    def test_no_effect_without_field_weighting(self):
        _, distinctive = self._cov(rq.QualityConfig(field_weighting=False), 0)
        self.assertFalse(distinctive)

    def test_url_only_match_counts(self):
        rows = [dict(NAV_ROWS[0], title="Cell")] + NAV_ROWS[1:]
        qi = rq.QualityIndex.build(rows, _bm25(), rq.QualityConfig(), synonym_groups=())
        self.assertTrue(qi.coverage(0, qi.analyze("placements"))[1])


class _CorpusCase(unittest.TestCase):
    """Builds the synthetic index once per class (real chunker, temp dir)."""

    @classmethod
    def setUpClass(cls):
        import tempfile
        cls._tmp = tempfile.TemporaryDirectory()
        cls.chunks_path = build_chunks_file(cls._tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        cm = serving(self.chunks_path)
        self.mod = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)

    def imp(self, qid, limit=5):
        return urls(self.mod.retrieve(Q[qid].text, limit=limit, mode="improved"))

    def leg(self, qid, limit=5):
        return urls(self.mod.retrieve(Q[qid].text, limit=limit, mode="legacy"))


class DefectFixTests(_CorpusCase):
    def test_f1_indic_keyword_queries_find_same_script_pages(self):
        for qid in ("L01", "L02", "L03", "L04"):
            self.assertEqual(self.leg(qid), [], f"{qid} legacy returned something")
            self.assertEqual(self.imp(qid)[:1], [Q[qid].expected[0].replace(BASE, "")], qid)

    def test_f2_offtopic_pizza_no_longer_retrieves_navigation_pages(self):
        self.assertTrue(self.leg("U02"), "legacy was expected to return irrelevant pages")
        self.assertEqual(self.imp("U02"), [])

    def test_f2_unanswerable_topical_question_returns_nothing(self):
        self.assertEqual(self.imp("U08"), [])

    def test_offtopic_queries_return_nothing_except_documented_limit(self):
        for qid in ("U03", "U04", "U05", "U06", "U07"):
            self.assertEqual(self.imp(qid), [], qid)

    def test_documented_limit_single_shared_topical_word_cannot_be_separated(self):
        # "cricket" appears on a sports page: lexical retrieval cannot know it is not an answer.
        self.assertEqual(self.imp("U01"), ["/campus/sports"])

    def test_f3_mtech_question_ranks_mtech_page_first_and_not_btech(self):
        got = self.imp("D01")
        self.assertEqual(got[0], "/programmes/mtech")
        self.assertNotIn("/programmes/btech", got)

    def test_f3_btech_question_ranks_btech_page_first(self):
        self.assertEqual(self.imp("D02")[0], "/programmes/btech")
        self.assertEqual(self.imp("D03")[0], "/programmes/btech")

    def test_f3_spaced_and_joined_degree_spellings_agree(self):
        self.assertEqual(self.imp("D04")[0], "/programmes/mtech")

    def test_f5_plural_forms_match(self):
        self.assertEqual(self.imp("P02")[0], "/fees/scholarships")
        self.assertIn("/hostel/fee", self.imp("P01")[:2])
        self.assertEqual(self.imp("P03")[0], "/hostel/facilities")

    def test_f5_abbreviations_match(self):
        self.assertEqual(self.imp("S01")[0], "/departments/cse")
        self.assertIn("/departments/ece", self.imp("S02")[:2])
        self.assertEqual(self.leg("S02"), [])  # legacy found nothing
        self.assertEqual(self.imp("S04")[0], "/departments/eee")

    def test_phrase_queries_put_the_specific_page_first(self):
        self.assertEqual(self.imp("H01")[0], "/admissions/management-quota")
        self.assertEqual(self.imp("H02")[0], "/admissions/lateral-entry")

    def test_diversity_two_distinct_pages_both_present(self):
        got = self.imp("R01")
        self.assertIn("/admissions", got)
        self.assertIn("/admissions/lateral-entry", got)

    def test_diversity_printer_friendly_copy_is_dropped(self):
        got = self.imp("R02")
        self.assertNotIn("/fees/structure?print=1", got)
        self.assertIn("/fees/structure", got)

    def test_diversity_off_keeps_the_duplicate(self):
        import dataclasses
        state = self.mod._ensure_state()
        patched = rq.QualityIndex.build(list(state.chunks), self.mod.BM25Okapi, rq.QualityConfig(diversity=False))
        no_div = dataclasses.replace(state, quality=patched)
        got = urls(self.mod._retrieve_improved(no_div, Q["R02"].text, 5))
        self.assertIn("/fees/structure?print=1", got)

    def test_controls_still_answered(self):
        for qid in ("C01", "C03", "C04", "C05", "C06", "C07", "C08"):
            self.assertEqual(self.imp(qid)[0], Q[qid].expected[0].replace(BASE, ""), qid)

    def test_cross_script_is_a_documented_limitation(self):
        # English query for a Hindi-only page: expected page is NOT retrieved (honest limit).
        self.assertNotIn("/hi/hostel", self.imp("X01"))


class ResultShapeTests(_CorpusCase):
    def test_hits_have_scores_and_coverage_and_original_fields(self):
        hits = self.mod.retrieve("What is the library borrowing period?", limit=3, mode="improved")
        self.assertTrue(hits)
        for hit in hits:
            for key in ("chunk_id", "doc_id", "title", "url", "text", "retrieval_score", "retrieval_coverage"):
                self.assertIn(key, hit)
            self.assertGreater(hit["retrieval_score"], 0)
            self.assertTrue(0 < hit["retrieval_coverage"] <= 1.0)

    def test_hits_sorted_by_score_descending(self):
        hits = self.mod.retrieve("hostel fees", limit=5, mode="improved")
        scores = [h["retrieval_score"] for h in hits]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_limit_respected(self):
        for limit in (1, 2, 3):
            self.assertLessEqual(len(self.mod.retrieve("hostel", limit=limit, mode="improved")), limit)

    def test_at_most_two_chunks_per_url(self):
        hits = self.mod.retrieve("btech syllabus", limit=10, mode="improved")
        counts = {}
        for h in hits:
            counts[h["url"]] = counts.get(h["url"], 0) + 1
        self.assertTrue(all(c <= 2 for c in counts.values()))

    def test_empty_and_stopword_only_queries(self):
        for q in ("", "   ", "the of and", "???"):
            self.assertEqual(self.mod.retrieve(q, limit=5, mode="improved"), [], repr(q))

    def test_retrieval_is_deterministic(self):
        a = self.mod.retrieve("hostel fees", limit=5, mode="improved")
        b = self.mod.retrieve("hostel fees", limit=5, mode="improved")
        self.assertEqual([(h["chunk_id"], h["retrieval_score"]) for h in a],
                         [(h["chunk_id"], h["retrieval_score"]) for h in b])

    def test_returned_dicts_are_copies(self):
        hit = self.mod.retrieve("library", limit=1, mode="improved")[0]
        hit["text"] = "MUTATED"
        again = self.mod.retrieve("library", limit=1, mode="improved")[0]
        self.assertNotEqual(again["text"], "MUTATED")


class ModeSelectionTests(_CorpusCase):
    def test_default_mode_is_improved(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RETRIEVAL_MODE", None)
            self.assertEqual(self.mod.get_retrieval_mode(), "improved")

    def test_env_switch_rolls_back_to_legacy_without_restart(self):
        q = Q["U02"].text
        with mock.patch.dict(os.environ, {"RETRIEVAL_MODE": "legacy"}):
            self.assertTrue(self.mod.retrieve(q, limit=5))      # legacy: irrelevant pages
        with mock.patch.dict(os.environ, {"RETRIEVAL_MODE": "improved"}):
            self.assertEqual(self.mod.retrieve(q, limit=5), [])

    def test_invalid_mode_falls_back_to_default(self):
        with mock.patch.dict(os.environ, {"RETRIEVAL_MODE": "turbo"}):
            self.assertEqual(self.mod.get_retrieval_mode(), "improved")

    def test_mode_argument_overrides_env(self):
        with mock.patch.dict(os.environ, {"RETRIEVAL_MODE": "legacy"}):
            self.assertEqual(self.mod.retrieve(Q["U02"].text, limit=5, mode="improved"), [])

    def test_status_reports_mode_and_improved_index(self):
        status = self.mod.get_index_status()
        self.assertTrue(status["improved_index_ready"])
        self.assertIsNone(status["improved_index_error"])
        self.assertIn(status["retrieval_mode"], ("legacy", "improved"))

    def test_improved_falls_back_to_legacy_if_quality_index_fails_to_build(self):
        with mock.patch.object(retrieval.quality.QualityIndex, "build", side_effect=RuntimeError("boom")):
            self.mod._reset_state_for_tests()
            with self.assertLogs("api.retrieval", level="WARNING"):
                hits = self.mod.retrieve("What is the library borrowing period?", limit=3, mode="improved")
            status = self.mod.get_index_status()
        self.assertTrue(hits)  # index not rejected, legacy scoring used
        self.assertTrue(status["index_ready"])
        self.assertFalse(status["improved_index_ready"])
        self.assertIn("boom", status["improved_index_error"])


class MetadataNormalisationTests(unittest.TestCase):
    def test_null_url_and_title_become_usable_strings(self):
        rows = [{"chunk_id": "n", "doc_id": None, "title": None, "url": None, "text": "library borrowing period"},
                {"chunk_id": "m", "doc_id": 5, "title": 7, "url": " https://x.test/m ", "text": "hostel fee"}]
        for row in rows:
            retrieval._normalise_metadata(row)
        self.assertEqual((rows[0]["title"], rows[0]["url"], rows[0]["doc_id"]), ("Untitled", "", ""))
        self.assertEqual((rows[1]["title"], rows[1]["url"], rows[1]["doc_id"]), ("7", "https://x.test/m", "5"))


if __name__ == "__main__":
    unittest.main()
