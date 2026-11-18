"""End-to-end backend -> LLM flow tests (SYNTHETIC data, no network, no real keys).

``requests.post`` is replaced by a recorder, so we can assert exactly what the LLM
would have received. Two entry points are exercised:

* ``answer_question`` (always runs);
* ``POST /api/v1/chat`` through FastAPI's ``TestClient`` (skipped automatically when
  fastapi / httpx / python-multipart are not installed).
"""

from __future__ import annotations

import json
import os
import unittest
from unittest import mock

import requests

from tests import _support  # noqa: F401
from tests.fixtures.heuristic_index import HEURISTIC_CHUNKS
from tests.fixtures.serving import serving, tmpdir, write_jsonl

from api import retrieval

FAKE_ENV = {"LLM_API_KEY": "test-key-not-real", "LLM_MODEL": "test-model", "LLM_BASE_URL": "https://llm.invalid/v1"}

LIB_CHUNKS = [
    {"chunk_id": "lib-0", "doc_id": "lib", "title": "Library", "url": "https://example.test/library",
     "verification_status": "VERIFIED",
     "text": "Library borrowing period is fourteen days. Students may borrow three books at a time. MARKER-LIB-TEXT."},
    {"chunk_id": "hos-0", "doc_id": "hos", "title": "Hostel", "url": "https://example.test/hostel",
     "text": "Hostel mess timings and rules for residents. MARKER-HOSTEL-TEXT."},
] + [
    {"chunk_id": f"pad-{i}", "doc_id": f"pad-{i}", "title": f"Notice {i}", "url": f"https://example.test/n/{i}",
     "text": f"Home | Campus Life | Quick Links | Contact. Unrelated notice {i} regarding gardens and seminars."}
    for i in range(10)
]


class FakeLLM:
    """Records every call; returns a canned completion (or raises)."""

    def __init__(self, content="Fourteen days, per the library page.", exc=None, status=200, body=None):
        self.calls = []
        self.content, self.exc, self.status, self.body = content, exc, status, body

    def __call__(self, url, headers=None, json=None, timeout=None, **kw):
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        if self.exc:
            raise self.exc
        resp = requests.Response()
        resp.status_code = self.status
        payload = self.body if self.body is not None else {"choices": [{"message": {"content": self.content}}]}
        resp._content = __import__("json").dumps(payload).encode()
        return resp

    @property
    def prompt(self):
        return self.calls[-1]["json"]["messages"][1]["content"]


class FlowCase(unittest.TestCase):
    chunks = LIB_CHUNKS
    env = FAKE_ENV

    def setUp(self):
        self._tmp = tmpdir()
        d = self._tmp.__enter__()
        self.addCleanup(self._tmp.__exit__, None, None, None)
        self.path = write_jsonl(d / "chunks.jsonl", self.chunks)
        cm = serving(self.path)
        cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)
        envp = mock.patch.dict(os.environ, self.env, clear=False)
        envp.start()
        self.addCleanup(envp.stop)
        os.environ.pop("RETRIEVAL_MODE", None)
        self.fake = FakeLLM()
        post = mock.patch.object(retrieval.requests, "post", self.fake)
        post.start()
        self.addCleanup(post.stop)


class GroundedAnswerTests(FlowCase):
    def test_context_urls_and_question_reach_the_llm(self):
        out = retrieval.answer_question("What is the library borrowing period?")
        self.assertEqual(len(self.fake.calls), 1)
        prompt = self.fake.prompt
        self.assertIn("What is the library borrowing period?", prompt)
        self.assertIn("MARKER-LIB-TEXT", prompt)
        self.assertIn("https://example.test/library", prompt)
        self.assertIn("Title: Library", prompt)
        self.assertIn("Verification: VERIFIED", prompt)
        self.assertEqual(out["mode"], "llm_grounded")
        self.assertEqual(out["answer"], "Fourteen days, per the library page.")

    def test_irrelevant_pages_are_not_sent_to_the_llm(self):
        retrieval.answer_question("What is the library borrowing period?")
        self.assertNotIn("MARKER-HOSTEL-TEXT", self.fake.prompt)
        self.assertNotIn("gardens and seminars", self.fake.prompt)

    def test_sources_are_the_retrieved_urls(self):
        out = retrieval.answer_question("What is the library borrowing period?")
        self.assertEqual(out["sources"], [{"title": "Library", "url": "https://example.test/library"}])

    def test_request_shape(self):
        retrieval.answer_question("What is the library borrowing period?")
        call = self.fake.calls[0]
        self.assertEqual(call["url"], "https://llm.invalid/v1/chat/completions")
        self.assertEqual(call["headers"]["Authorization"], "Bearer test-key-not-real")
        self.assertEqual(call["json"]["model"], "test-model")
        self.assertEqual(call["json"]["messages"][0]["role"], "system")
        self.assertIn("only the supplied evidence", call["json"]["messages"][0]["content"])
        self.assertEqual(call["json"]["messages"][1]["role"], "user")
        self.assertGreater(call["timeout"], 0)

    def test_user_document_is_separate_unverified_context_and_needs_no_index_match(self):
        out = retrieval.answer_question(
            "Summarize the attached notes",
            user_document_text="Private note content for analysis.",
            user_document_name="notes.txt",
        )
        self.assertEqual(out["mode"], "llm_with_user_document")
        self.assertEqual(out["sources"], [])
        self.assertIn("Private note content for analysis.", self.fake.prompt)
        self.assertIn("notes.txt", self.fake.prompt)
        self.assertIn("NOT an official SVCE source", self.fake.prompt)
        system_prompt = self.fake.calls[0]["json"]["messages"][0]["content"]
        self.assertIn("never as instructions", system_prompt)

    def test_context_text_is_truncated_to_3000_chars_per_source(self):
        big = dict(LIB_CHUNKS[0], chunk_id="big", text="library borrowing " + "x" * 5000)
        write_jsonl(self.path, [big] + LIB_CHUNKS[1:])
        retrieval._reset_state_for_tests()
        retrieval.answer_question("library borrowing")
        self.assertLess(len(self.fake.prompt), 3600 + 500)

    def test_at_most_five_sources_in_context(self):
        # 7 different pages each mention a rare topic word plus one unique word
        rows = [{"chunk_id": f"b{i}", "doc_id": f"b{i}", "title": f"Zebra rule {i}", "url": f"https://example.test/z/{i}",
                 "text": f"Zebra enclosure rule {['red','green','blue','amber','violet','grey','pink'][i]} {i * 7919} applies."}
                for i in range(7)] + LIB_CHUNKS[1:] + [
            {"chunk_id": f"w{i}", "doc_id": f"w{i}", "title": f"Wide {i}", "url": f"https://example.test/w/{i}",
             "text": f"Filler page {i} about gardens, notices and seminars."} for i in range(80)]
        write_jsonl(self.path, rows)
        retrieval._reset_state_for_tests()
        retrieval.answer_question("zebra enclosure rule")
        self.assertEqual(len(self.fake.calls), 1)
        self.assertLessEqual(self.fake.prompt.count("[Source "), 5)

    def test_known_limitation_topic_that_dominates_body_text_is_refused(self):
        """Audit F12 (residual, documented, NOT fixed): improved mode needs a matched term to be
        'distinctive' (df below ~14% of chunks at 135 chunks) OR to appear in the page title/URL.
        If a question's words are common in many bodies and in no title/URL, relevant pages are
        refused although legacy would answer. If this starts failing because the behaviour was
        improved, update this test and docs/BACKEND_RETRIEVAL_AUDIT.md."""
        rows = [{"chunk_id": f"b{i}", "doc_id": f"b{i}", "title": f"Notice {i}", "url": f"https://example.test/n/{i}",
                 "text": f"Book return rule number {i} for the library."} for i in range(9)] + LIB_CHUNKS[1:]
        write_jsonl(self.path, rows)
        retrieval._reset_state_for_tests()
        with mock.patch.dict(os.environ, {"RETRIEVAL_MODE": "improved"}):
            improved = retrieval.answer_question("library book return rule")
        self.assertEqual(improved["mode"], "insufficient_evidence")
        self.assertEqual(self.fake.calls, [])
        with mock.patch.dict(os.environ, {"RETRIEVAL_MODE": "legacy"}):
            legacy = retrieval.answer_question("library book return rule")
        self.assertEqual(legacy["mode"], "llm_grounded")

    def test_topic_word_repeated_in_site_navigation_is_still_answered_via_title(self):
        """Audit F12 fix: 'Placements' is in the nav text of every page, but the placement page
        is *titled* Placements, so a question on that topic must reach the LLM."""
        nav = "Home | About | Admissions | Placements | Contact Us | Campus Life."
        rows = [{"chunk_id": "pl", "doc_id": "pl", "title": "Training and Placement Cell",
                 "url": "https://example.test/placements", "text": nav + " Recruiters visit every year. MARKER-PLACEMENT-TEXT."}] + [
            {"chunk_id": f"x{i}", "doc_id": f"x{i}", "title": f"Page {i}", "url": f"https://example.test/x/{i}",
             "text": nav + f" Unrelated content number {i} about gardens."} for i in range(40)]
        write_jsonl(self.path, rows)
        retrieval._reset_state_for_tests()
        for question in ("Tell me about placements", "placements"):
            self.fake.calls.clear()
            out = retrieval.answer_question(question)
            self.assertEqual(out["mode"], "llm_grounded", question)
            self.assertIn("MARKER-PLACEMENT-TEXT", self.fake.prompt)
            self.assertEqual([s["url"] for s in out["sources"]], ["https://example.test/placements"])
        # ...while nav-only pages are not evidence for an off-topic question
        self.fake.calls.clear()
        self.assertEqual(retrieval.answer_question("Best pizza near campus")["mode"], "insufficient_evidence")
        self.assertEqual(self.fake.calls, [])

    def test_markdown_year_normalisation_applies_to_llm_answer(self):
        self.fake.content = "Package in 2023–2024 was high."
        out = retrieval.answer_question("What is the library borrowing period?")
        self.assertNotEqual(out["answer"], "")
        self.assertEqual(out["mode"], "llm_grounded")


class NoEvidenceTests(FlowCase):
    def test_offtopic_question_never_calls_llm(self):
        out = retrieval.answer_question("Best pizza near campus")
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(out["mode"], "insufficient_evidence")
        self.assertEqual(out["sources"], [])
        self.assertIn("couldn't find", out["answer"])

    def test_empty_and_whitespace_question(self):
        for q in ("", "   \n"):
            out = retrieval.answer_question(q)
            self.assertEqual(out["mode"], "insufficient_evidence")
            self.assertEqual(out["sources"], [])
        self.assertEqual(self.fake.calls, [])

    def test_legacy_rollback_sends_irrelevant_context(self):
        """Documents why the default changed: legacy fed unrelated pages to the model."""
        rows = LIB_CHUNKS + [{"chunk_id": "nav", "doc_id": "nav", "title": "Home", "url": "https://example.test/",
                              "text": "Home | Campus Life | Quick Links | Contact"}]
        write_jsonl(self.path, rows)
        retrieval._reset_state_for_tests()
        with mock.patch.dict(os.environ, {"RETRIEVAL_MODE": "legacy"}):
            retrieval.answer_question("Best pizza near campus")
        self.assertEqual(len(self.fake.calls), 1)
        self.fake.calls.clear()
        with mock.patch.dict(os.environ, {"RETRIEVAL_MODE": "improved"}):
            out = retrieval.answer_question("Best pizza near campus")
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(out["mode"], "insufficient_evidence")


class LLMFailureTests(FlowCase):
    def _assert_unavailable(self, out):
        self.assertEqual(out["mode"], "generation_unavailable")
        self.assertEqual(out["sources"], [{"title": "Library", "url": "https://example.test/library"}])
        # raw chunk text is never shown to students
        self.assertNotIn("MARKER-LIB-TEXT", out["answer"])
        self.assertNotIn("fourteen days", out["answer"].lower())

    def test_timeout(self):
        self.fake.exc = requests.exceptions.Timeout()
        self._assert_unavailable(retrieval.answer_question("What is the library borrowing period?"))

    def test_connection_error(self):
        self.fake.exc = requests.exceptions.ConnectionError()
        self._assert_unavailable(retrieval.answer_question("What is the library borrowing period?"))

    def test_http_error_status(self):
        self.fake.status = 429
        self._assert_unavailable(retrieval.answer_question("What is the library borrowing period?"))

    def test_unexpected_exception(self):
        self.fake.exc = ValueError("weird")
        self._assert_unavailable(retrieval.answer_question("What is the library borrowing period?"))

    def test_empty_completion(self):
        self.fake.content = "   "
        self._assert_unavailable(retrieval.answer_question("What is the library borrowing period?"))

    def test_malformed_completion_body(self):
        self.fake.body = {"unexpected": True}
        self._assert_unavailable(retrieval.answer_question("What is the library borrowing period?"))

    def test_error_logs_do_not_contain_the_api_key(self):
        self.fake.exc = requests.exceptions.ConnectionError("boom")
        with self.assertLogs("api.retrieval", level="WARNING") as logs:
            retrieval.answer_question("What is the library borrowing period?")
        self.assertNotIn("test-key-not-real", "\n".join(logs.output))


class LLMNotConfiguredTests(FlowCase):
    env = {"LLM_API_KEY": "", "LLM_MODEL": ""}

    def test_no_key_means_no_call_and_generation_unavailable(self):
        out = retrieval.answer_question("What is the library borrowing period?")
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(out["mode"], "generation_unavailable")
        self.assertEqual(len(out["sources"]), 1)


class IndexUnavailableTests(unittest.TestCase):
    def test_missing_index_is_reported_distinctly_from_no_match(self):
        with tmpdir() as d, serving(d / "missing.jsonl"):
            fake = FakeLLM()
            with mock.patch.object(retrieval.requests, "post", fake), mock.patch.dict(os.environ, FAKE_ENV):
                out = retrieval.answer_question("What is the library borrowing period?")
        self.assertEqual(out["mode"], "index_unavailable")
        self.assertEqual(out["sources"], [])
        self.assertEqual(fake.calls, [])
        self.assertIn("not available", out["answer"])


class AdmissionSourcesTests(unittest.TestCase):
    """F7: the admission-source filter must not erase every citation."""

    def test_admission_question_cites_official_page_when_retrieved(self):
        with tmpdir() as d, serving(write_jsonl(d / "h.jsonl", HEURISTIC_CHUNKS)):
            fake = FakeLLM("Admission is through counselling.")
            with mock.patch.object(retrieval.requests, "post", fake), mock.patch.dict(os.environ, FAKE_ENV):
                out = retrieval.answer_question("What is the admission process?")
        self.assertEqual(out["mode"], "llm_grounded")
        self.assertEqual([s["url"] for s in out["sources"]], ["https://svce.edu.in/admission.php"])

    def test_admission_question_without_official_page_keeps_retrieved_sources(self):
        rows = [{"chunk_id": "a", "doc_id": "a", "title": "Lateral entry rules", "url": "https://example.test/lateral",
                 "text": "Lateral entry admission for diploma holders follows merit."}] + [
            {"chunk_id": f"p{i}", "doc_id": f"p{i}", "title": f"N{i}", "url": f"https://example.test/p/{i}",
             "text": f"Unrelated notice {i}."} for i in range(8)]
        with tmpdir() as d, serving(write_jsonl(d / "a.jsonl", rows)):
            fake = FakeLLM("Merit based.")
            with mock.patch.object(retrieval.requests, "post", fake), mock.patch.dict(os.environ, FAKE_ENV):
                out = retrieval.answer_question("lateral entry admission")
        self.assertEqual(out["mode"], "llm_grounded")
        self.assertEqual([s["url"] for s in out["sources"]], ["https://example.test/lateral"])

    def test_build_sources_helper(self):
        hits = [{"url": "https://example.test/x", "title": "X"}]
        self.assertEqual(retrieval._build_sources(hits, "admission"), [{"title": "X", "url": "https://example.test/x"}])
        self.assertEqual(retrieval._build_sources([], "admission"), [])


class NullMetadataFlowTests(unittest.TestCase):
    def test_null_url_never_becomes_the_string_None(self):
        rows = [{"chunk_id": "n", "doc_id": "n", "title": None, "url": None,
                 "text": "Library borrowing period is fourteen days for students."}] + [
            {"chunk_id": f"p{i}", "doc_id": f"p{i}", "title": f"N{i}", "url": f"https://example.test/p/{i}",
             "text": f"Unrelated notice {i}."} for i in range(8)]
        with tmpdir() as d, serving(write_jsonl(d / "n.jsonl", rows)):
            fake = FakeLLM()
            with mock.patch.object(retrieval.requests, "post", fake), mock.patch.dict(os.environ, FAKE_ENV):
                out = retrieval.answer_question("library borrowing period")
        self.assertNotIn("URL: None", fake.prompt)
        self.assertNotIn("None", [s["url"] for s in out["sources"]])
        self.assertEqual(out["sources"], [])  # no URL to cite -> no fabricated source


class ContactFlowTests(unittest.TestCase):
    def test_contact_question_uses_official_page_only(self):
        with tmpdir() as d, serving(write_jsonl(d / "h.jsonl", HEURISTIC_CHUNKS)):
            fake = FakeLLM()
            with mock.patch.object(retrieval.requests, "post", fake), mock.patch.dict(os.environ, FAKE_ENV):
                hits = retrieval.retrieve("college contact phone number", limit=5)
        self.assertTrue(hits)
        self.assertEqual({h["url"].rstrip("/") for h in hits}, {"https://svce.edu.in/contactus.php"})


@unittest.skipUnless(
    all(__import__("importlib").util.find_spec(m) for m in ("fastapi", "httpx", "multipart", "pydantic")),
    "fastapi/httpx/python-multipart not installed in this environment",
)
class HttpEndpointTests(FlowCase):
    def setUp(self):
        super().setUp()
        with mock.patch("dotenv.load_dotenv", lambda *a, **k: False):  # never read a real .env
            from fastapi.testclient import TestClient
            from api import main
        self.client = TestClient(main.app)

    def test_chat_roundtrip(self):
        r = self.client.post("/api/v1/chat", json={"message": "What is the library borrowing period?"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(set(body), {"answer", "sources", "mode"})
        self.assertEqual(body["mode"], "llm_grounded")
        self.assertEqual(body["sources"][0]["url"], "https://example.test/library")
        self.assertIn("MARKER-LIB-TEXT", self.fake.prompt)

    def test_chat_no_match(self):
        body = self.client.post("/api/v1/chat", json={"message": "Best pizza near campus"}).json()
        self.assertEqual(body["mode"], "insufficient_evidence")
        self.assertEqual(self.fake.calls, [])

    def test_chat_validation(self):
        self.assertEqual(self.client.post("/api/v1/chat", json={"message": ""}).status_code, 422)
        self.assertEqual(self.client.post("/api/v1/chat", json={}).status_code, 422)
        self.assertEqual(self.client.post("/api/v1/chat", json={"message": "x" * 3001}).status_code, 422)

    def test_chat_attachment_has_independent_limit_and_is_not_truncated(self):
        content = ("student-provided context " * 600).strip()
        response = self.client.post("/api/v1/chat", json={
            "message": "Summarize the attached document",
            "attachment_name": "notes.txt",
            "attachment_text": content,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mode"], "llm_with_user_document")
        self.assertIn(content, self.fake.prompt)
        self.assertEqual(self.client.post("/api/v1/chat", json={
            "message": "Summarize the attached document",
            "attachment_text": "x" * 30001,
        }).status_code, 422)

    def test_file_extraction_rejects_oversized_extracted_text_without_truncating(self):
        response = self.client.post(
            "/api/v1/files/extract",
            files={"file": ("notes.txt", b"x" * 30001, "text/plain")},
        )
        self.assertEqual(response.status_code, 413)
        self.assertIn("No text was discarded", response.json()["detail"])

    def test_root_serves_built_frontend_and_asset_path(self):
        from api import main
        if not (main.FRONTEND_DIST / "assets").is_dir():
            self.skipTest("frontend build assets are not present")
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("/assets/", response.text)
        self.assertNotIn("/src/main.jsx", response.text)

    def test_chat_unicode_message(self):
        r = self.client.post("/api/v1/chat", json={"message": "హాస్టల్ ఫీజు"})
        self.assertEqual(r.status_code, 200)

    def test_health_and_status(self):
        health = self.client.get("/health").json()
        self.assertTrue(health["index_ready"])
        self.assertEqual(health["chunks_loaded"], len(LIB_CHUNKS))
        status = self.client.get("/api/v1/index/status").json()
        self.assertTrue(status["improved_index_ready"])
        self.assertIn("retrieval_mode", status)


if __name__ == "__main__":
    unittest.main()
