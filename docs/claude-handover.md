# PHASE 2 / CP3 STATUS (latest — read this first; the older Phase 1 notes below are historical)

## Current CP3 status

Phase 2 frontend validation was completed at the build and browser level. `npm ci` passed, `npm run build` passed, Vite launched at `127.0.0.1:5173`, and FastAPI launched at `127.0.0.1:8000` after restoring missing documented backend dependencies.

Real backend health: 24,735 chunks loaded, index ready, LLM not configured. Real UI chat, source cards, landing/assistant navigation, mobile navigation/Escape-close, responsive overflow checks, and direct file extraction were exercised. The real chat backend returned insufficient-evidence fallbacks because no LLM credentials are configured. Mock retry/Markdown recovery was not counted as verified.

CP3 source change: darkened `--text-subtle` from `#616a81` to `#555d73`, raising the weakest checked sage-200 pairing from 3.85:1 to 4.68:1.

Modified files: `frontend/src/styles/tokens.css`, `docs/PHASE_2_IMPLEMENTATION_REPORT.md`, this file.
Known limits: voice/microphone, browser file-picker/send-with-file, deterministic retry mock recovery, actual screen-reader testing, real-device testing, and final real-LLM answer quality remain outstanding.
Do not start Phase 3; see `docs/PHASE_2_IMPLEMENTATION_REPORT.md` for exact commands and results.

---

<!-- PHASE2:BEGIN -->
# PHASE 2 — PREMIUM LIGHT-THEME UI/UX REDESIGN (frontend only)
**Latest checkpoint: `stif-campus-ai_CP2_main-ui_v0.2.zip`** (read this block first)

## Completed (CP2)
Frontend fully rewritten and WIRED. Backend, API contracts, retrieval, tests and docs untouched.
- `frontend/src/main.jsx` (entry) -> `App.jsx` (hash router: #home/#assistant + scroll to #explore/#about; conversation state lives in App so it survives navigation; toasts; skip link).
- Pages: `pages/Landing.jsx` (hero w/ CSS-only illustrative preview, suggested-question cards, capabilities bento, how-it-works, CTA), `pages/Assistant.jsx` (rail, chat, composer, attach, voice, retry).
- Components: `components/{Brand,Header,Footer,Toast}.jsx`, `components/chat/{Markdown,DataChart,SourceCards,Message,VoiceDialog}.jsx`, `hooks/useVoiceInput.js`, `lib/{config.js,followups.js,Reveal.jsx}`.
- Styles: `styles/{tokens,base,components,landing,chat,voice,index}.css`. Old `styles.css` removed (replaced).
- Light theme only (no dark mode anywhere; voice dialog + hero + footer were dark before and are now ivory/champagne).
- NEW user-visible behaviour: source cards from the real `sources` field (baseline never showed them; non-http(s) URLs filtered); Retry button on failed chat; copy-answer button + toast; file "Reading…" state; autosize textarea; ordered lists / fenced code / block quotes in answers; focus-trapped voice dialog; fixed baseline literal `\n` bug.
- Preserved: POST /api/v1/chat body+usage, /api/v1/files/extract flow, attachment text injection (18k chars), voice logic (en-IN, continuous, auto-restart), follow-up logic, data-chart logic, suggested questions text, VITE_API_BASE_URL, hash routes.
- Removed: hero background video (`/assets/campus-background.mp4`, `/assets/campus-poster.jpg` never existed in the ZIP; dark video conflicts with light brief). Footer hidden on the assistant page (app-shell layout).

## Verification done so far (sandbox: no network, real vite/lucide not installable)
esbuild bundle (React 19 + react-icons Lucide shim, kept outside the project) + test-only mock backend + Playwright/Chromium: 4 viewports (1440/1180/768/390) no horizontal overflow, no console errors; 23/24 interaction checks passed (menu, Esc, section scroll, prefill, error->retry w/o duplicate user message, sources, copy, chart, attach menu/pill/remove, bad file type, voice dialog with fake SpeechRecognition, new conversation, nav persistence); the one failing check (skip link) was a test artefact and passes on a fresh page load. NOT yet verified: real `vite build` with the project lockfile (React 18.3.1, lucide-react 0.468.0, Vite 6.4.4), real FastAPI end-to-end, real fonts (Google Fonts unreachable in sandbox).

## Remaining
1. CP3: accessibility pass (axe-like checks: contrast, labels, heading order), keyboard-only walk-through, tablet screenshots review, reduced-motion check, light-theme sweep on every state, lucide icon-name sanity vs 0.468.0.
2. Implementation report `docs/PHASE_2_IMPLEMENTATION_REPORT.md`, final ZIP, update this block.

## Next exact step
Run a11y/contrast checks with Playwright, fix findings, write the report, pack CP3 + FINAL. On the user's machine: `cd frontend && npm ci && npm run build` (expected to succeed; icons used are all in lucide-react 0.468) then `npm run dev` with backend running.
<!-- PHASE2:END -->

---- (Phase 1 / retrieval-task notes below; backend is unchanged by Phase 2) ----

---- (Phase 1 / retrieval-task notes below; backend is unchanged by Phase 2) ----

# SESSION 3 FINAL STATE
ALL listed tasks done. Final sandbox run: 285 tests = 277 pass, 3 fail (legacy golden; need real rank_bm25), 5 skip (TestClient; need fastapi/httpx/python-multipart).
Read docs/BACKEND_RETRIEVAL_AUDIT.md first: it states what is verified vs not. Real SVCE accuracy NOT measured (no production index).
NEXT (user machine): pip install -r requirements-local.txt pytest httpx python-multipart; python -m pytest -q (expect all pass); python -m evaluation.synthetic.benchmark (regenerate after F12 fix);
python -m diagnostics --questions <real student questions> on the REAL data dir; review IMPROVED_REFUSES flags; rollback = RETRIEVAL_MODE=legacy.
Open: F9 contact text hard-coded, F10 fast index shadows data/index, F11 max_tokens=300, residual F12 limits (body-only dominance).

# SESSION 3 PROGRESS (after diagnostic)
DONE: diagnostics/ (__init__, __main__, cli, checks) + tests/test_diagnostics.py (30). Sandbox: 285 tests, 3 failures (stub-BM25 golden tests), 5 skipped (TestClient, no fastapi).
FIX APPLIED (found by the diagnostic): improved mode refused single-topic questions ('placements','admissions','examination') because nav words are in every chunk (F12). Now a query term matching the chunk TITLE/URL counts as distinctive (QualityConfig.meta_match_distinctive, default True). Off-topic synthetic queries unchanged. benchmark_results.json was NOT regenerated (needs real rank_bm25) and predates this fix.
TODO: docs/BACKEND_RETRIEVAL_AUDIT.md, final run + FINAL zip.

# SESSION 3 PROGRESS (after tests)
DONE: tests/test_retrieval_quality.py (71), tests/test_backend_llm_flow.py (30; 5 TestClient tests skip without fastapi), tests/test_index_health.py (27).
Sandbox result (stub BM25, no fastapi): 248 tests, 3 failures = the 3 legacy golden tests (they need REAL rank_bm25 scores), 5 skipped. NOT 'all green': re-run in a real env.
NEW FINDING F12: improved mode's 'distinctive term' floor refuses questions whose matched terms each appear in >~14% of chunks (and every question on a 1-chunk index). Pinned by tests as known limitation, not fixed.
TODO: diagnostics/ CLI + tests, docs/BACKEND_RETRIEVAL_AUDIT.md, final run + FINAL zip.

# SESSION 3 NOTE (CHECKPOINT 2 -> continuing)
- Sandbox in this session has NO network and NO pytest/fastapi/httpx/rank_bm25/python-multipart (numpy, requests, dotenv, bs4, pypdf present).
  The 122-test baseline could NOT be re-run here. Everything added this session is verified only as far as stated in the delivery notes.
- Checkpoint-2 ZIP is re-delivered unchanged as the 'after reading handover' checkpoint.

# Claude handover - Backend Data Flow & Retrieval Quality task (CHECKPOINT 2 - integration done)

## PROGRESS SINCE CHECKPOINT 1 (read this first)
DONE in this session (all synthetic-data only, no real index in the ZIP):
- `api/retrieval.py` PATCHED (BOM + CRLF preserved; original kept at `docs/wip/retrieval_phase1b_original.py.txt`):
  `get_retrieval_mode()` (env `RETRIEVAL_MODE` legacy|improved, default improved), `retrieve(query, limit, mode=None)`
  dispatcher, `_retrieve_legacy` (unchanged Phase 1B logic), `_retrieve_improved`, `_apply_heuristics` (tail of the old
  `_chunk_score`, same float order), `_normalise_metadata` (F8), `QualityIndex` built in `_build_state` (failure never rejects an
  index), status keys `retrieval_mode/improved_index_ready/improved_index_error`, mode `index_unavailable` (F6), `_build_sources`
  fallback (F7).
- `tests/test_retrieval_legacy_golden.py` (3 tests) proves legacy == original on 13 heuristic + 38 synthetic queries; `tests/fixtures/serving.py` helper.
- `evaluation/synthetic/benchmark.py` (+ `evaluation/synthetic/results/benchmark_results.json`): legacy vs improved, ablations, coverage sweep, latency.
- Test status at this checkpoint: 122 passed.
STILL TO DO (in order): quality-module unit tests; end-to-end flow tests (TestClient + faked requests.post); missing/empty/invalid/stale
index tests; `diagnostics/` CLI + tests; `docs/BACKEND_RETRIEVAL_AUDIT.md`; final run + FINAL zip. Then decide the default mode
honestly from the benchmark (default currently `improved`; rollback = `RETRIEVAL_MODE=legacy`).

---- (older checkpoint-1 notes below; the "REMAINING WORK" list there is superseded by the list above) ----

# Claude handover - Backend Data Flow & Retrieval Quality task (CHECKPOINT 1)

Base: `Stif-Campus-ai-PHASE1B-final.zip` (never restart from the original). Date of checkpoint: 2026-11-18.
Remaining usage: **cannot be measured by me**; this checkpoint was requested by the user, not triggered by a limit.

## STATE IN ONE LINE
Audit evidence gathered, synthetic corpus + golden fixture + new quality module written. **`api/retrieval.py` and
`api/main.py` are still UNMODIFIED** (verified byte-identical to Phase 1B). The patch to retrieval.py is only drafted.

## Completed
1. Environment: real `rank-bm25 0.2.2`, fastapi, pytest, httpx, python-multipart, pypdf, bs4 installed in the sandbox.
   `python-multipart` is needed for `api.main` to import under TestClient (Phase 1B could not test main.py; now possible).
2. Baseline: `python3 -m pytest -q` -> **119 passed** (real BM25). Re-verified at checkpoint time.
3. Audit by actual call tracing (`docs/wip/audit_trace.py.txt`, run over HTTP with `requests.post` faked, no network).
   Real call order: `chat -> answer_question -> retrieve -> _ensure_state -> _current_signature -> _tokens/_token_set
   -> _detect_topics -> _chunk_score (x135, one per chunk) -> _topic_title_bonus -> _build_sources ->
   _answer_contact_from_official_page -> _generate_with_llm -> _filter_admission_evidence -> requests.post`.
4. Findings PROVEN on a synthetic index (fictional institute; NOT SVCE data, NOT real-index results):
   - F1 Hindi/Telugu queries return 0 chunks although matching same-script pages exist (`_tokens` is ASCII-only).
   - F2 "Best pizza near campus" -> `llm_grounded`, 5 irrelevant pages sent to the LLM AND returned as `sources`
        (matches nav text "Campus Life"). No relevance floor: any 1 shared token gives score > 0.
   - F3 "duration of M.Tech" ranks the B.Tech page 2nd and cites it (`B.Tech`/`M.Tech` both -> token `tech`; `btech` never matches `B.Tech`).
   - F4 `_chunk_score`/`_tokens` run over every chunk's full text on every query (135 chunks -> 272 `_tokens` calls).
   - F5 (from code reading, still to be demonstrated by test) no stemming (`fees` vs `fee`); no synonyms (`CSE`).
   - F6 (code reading + probe) with no index, `/api/v1/chat` returns the same "couldn't find relevant information" text
        as a genuine no-match (mode `insufficient_evidence`); callers cannot tell "index missing" from "no match".
   - F7 (code reading, to be tested) `_build_sources`: admission questions keep only `svce.edu.in/admission.php`; if no hit is that URL
        the LLM answer is returned with `sources: []`.
   - F8 (code reading, to be tested) `item.setdefault("url","")` leaves JSON `null`; `str(None)` then yields source URL "None".
   - F9 contact answer is a hard-coded literal (not derived from retrieved chunk text) -> can go stale; only gated on the contact page being retrieved. Documented only; facts NOT verified/changed.
   - F10 Fast index (`data/index_fast`) always outranks `data/index`; a newly published `data/index` is never served while the fast index exists (Phase 1B reports `published_not_serving`; diagnostic should warn).
   - F11 LLM `max_tokens` is 300 (answers can truncate); "generation_unavailable" message also appears when the LLM is simply not configured. Documented only.
   - Frontend reads `data.answer` (and sources) but never branches on `mode`, so adding a new mode value is frontend-safe.
5. New files (all synthetic / test-only except the module):
   - `api/retrieval_quality.py` - NEW, **untested beyond a smoke test**: degree-name normalisation (B.Tech/M.Tech/e-mail/wi-fi),
     Unicode (Devanagari U+0900-097F, Telugu U+0C00-0C7F) tokenizer, conservative plural stemming, synonym groups (+ optional
     `data/retrieval_synonyms.json` / env `RETRIEVAL_SYNONYMS_FILE`), `QualityIndex` (body + title/url BM25 fields, per-chunk token sets,
     idf, IDF-weighted coverage, distinctive-term check, bigram phrase matches, Jaccard near-duplicate), `QualityConfig` with per-technique toggles and `from_env()` (`RETRIEVAL_MIN_COVERAGE`).
   - `evaluation/synthetic/{__init__,corpus}.py` - 124 docs -> 135 chunks built with the real `build_fast_index.build_index` into a temp dir;
     38 queries (controls, degree-name, plural, synonym, phrase, diversity, Indic keyword, off-topic, cross-script) with SYNTHETIC ground truth.
     Caveat: expected answers were authored after the defects were found -> demonstrates defect fixes, NOT real accuracy.
   - `tests/fixtures/heuristic_index.py` (SVCE-shaped URLs, fictional text, exercises admission/contact/placement boosts),
     `tests/fixtures/make_legacy_golden.py`, `tests/fixtures/legacy_golden.json` (golden top-10 ids+scores from the ORIGINAL code:
     13 heuristic queries + 38 synthetic queries), `tests/fixtures/__init__.py`.
   - `docs/wip/retrieval_stage1_partial_NOT_APPLIED.py.txt` - draft of retrieval.py (LF endings) with: import of quality, `_RetrievalState.quality/quality_error`,
     `_build_state` building `QualityIndex` (failure must not reject the index) + `_normalise_metadata` (fixes F8), status keys `retrieval_mode`, `improved_index_ready`, `improved_index_error`.
     It references `get_retrieval_mode()` which does NOT exist yet. Do not copy it blindly.
   - `docs/wip/audit_trace.py.txt` - the tracing script used above.

## Modified existing files
None of the Phase 1A/1B source files. (`tests/fixtures/*`, `evaluation/synthetic/*`, `api/retrieval_quality.py`, `docs/*` are new.)

## Exact test results at checkpoint
`python3 -W ignore -m pytest -q` -> `119 passed` (Phase 1A 56 + Phase 1B 61 + 2 text-processing). Real rank_bm25 0.2.2.
No tests yet exist for the new module, the golden fixture, the diagnostic or the end-to-end flow.

## Known issues / design points discovered
- `rank_bm25` returns all-zero scores on tiny corpora (idf = 0 when df = N/2). Improved mode must choose candidates by token overlap
  (`doc_sets`), NOT `base_scores > 0`. Legacy is unaffected because it adds coverage bonuses.
- Files are CRLF (retrieval.py also has a UTF-8 BOM). Patch by reading bytes, stripping BOM, `\r\n`->`\n`, editing, then writing BOM + CRLF back.
- Shell is `/bin/sh` (no `<(...)`).
- Coverage floor is a risky lever: legitimate questions contain words the page never uses. Keep `min_coverage` low (0.15), require a distinctive matched term, report threshold sensitivity honestly. Single-term overlap with an unrelated topic (e.g. "cricket" vs a sports page) cannot be separated lexically.

## REMAINING WORK (in order)
1. Apply the retrieval.py patch properly: stage-1 content + (a) extract `_heuristic_bonus(query,title,url,text,topics)` from `_chunk_score` (legacy score = gate + bm25 + coverage*2 + title_overlap*.8 + .5 + bonus; keep arithmetic order),
   (b) rename old `retrieve` body to `_retrieve_legacy(state, query, limit)`; add `get_retrieval_mode()` (env `RETRIEVAL_MODE` legacy|improved, default improved) and `_retrieve_improved`
   (candidates by overlap, coverage/distinctive floor, base + coverage*2 + phrase bonus + `_heuristic_bonus`, same contact +50 / contact-only rules, per-doc/url cap 2, near-duplicate skip),
   (c) `answer_question`: new mode `index_unavailable` when `get_index_status()["index_ready"]` is False (F6); `_build_sources` falls back to unfiltered sources when the admission filter removes everything (F7).
   Legacy must reproduce `tests/fixtures/legacy_golden.json` exactly (score rounded to 3 dp, same order).
2. Tests: golden legacy equivalence; quality unit tests; full flow via `TestClient` with faked `requests.post` (context + URLs reach the LLM payload, sources preserved, insufficient evidence);
   missing / empty / invalid (bad JSON lines, null url/title, bad UTF-8) / stale index (Phase 1A last-known-good, `serving_stale`); real-BM25 assertion; rollback env switch.
3. Benchmark runner `evaluation/synthetic/benchmark.py`: legacy vs improved + ablations (one technique off at a time) + min_coverage sweep, using `evaluation.metrics.QuestionScore/aggregate`;
   also false-answer rate on unanswerable queries, false-refusal rate on answerable ones, per-query latency on a scaled synthetic corpus. Label everything SYNTHETIC; report losses honestly.
4. Diagnostic CLI `diagnostics/` (`python -m diagnostics`): read-only; selected index path + why, candidates (size/mtime/sha256), chunk count, validation, corpus stats, warnings (data/index newer than index_fast, null urls, duplicates, non-ASCII share),
   sample questions (default list + `--questions FILE`), top-N hits with score/coverage/URL/snippet, legacy vs improved, LLM-context check by faking `requests.post` with a fake key/model/base URL (no network, real keys never read or printed),
   `load_dotenv` patched to a no-op unless `--use-env` (so `.env` is not read), `--json`, exit codes. Test that index bytes/mtime/dir listing are unchanged.
5. `docs/BACKEND_RETRIEVAL_AUDIT.md` (actual data flow, problems, changes, synthetic vs real results, limitations incl. Telugu/Hindi, "real retrieval quality NOT measured: no production index in the ZIP").
6. Final full test run, final ZIP (`Stif-Campus-ai-RETRIEVAL-FINAL.zip`), checkpoint 2 after step 3.

## Continuation instructions
Unzip the checkpoint, `pip install rank-bm25==0.2.2 fastapi pytest httpx python-multipart pypdf beautifulsoup4 python-dotenv requests`, run `python3 -m pytest -q` (expect 119), then start at REMAINING WORK step 1.
Boundaries still apply: no frontend changes, no real index rebuild/overwrite, never read `.env`, no git commit/push, do not verify or invent college facts.
