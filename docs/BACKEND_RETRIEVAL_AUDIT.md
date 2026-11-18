# Backend retrieval audit — STIF Campus AI

Scope: data flow from a student's question to the LLM and back, retrieval quality, index health handling, and the changes made.
Date: 2026-11-18. Base: `Stif-Campus-ai-PHASE1B-final.zip` → Checkpoint 2 → this delivery.

> **Real SVCE retrieval quality was NOT measured.** No production index (`data/index*/chunks.jsonl`) was included, so every
> number below comes from a **synthetic, fictional** corpus (`evaluation/synthetic/`). The synthetic expected answers were written
> *after* the defects were found: they show that the identified defect classes are fixed, not how accurate the system is on college
> data. Run `python -m diagnostics` against the real indexes (section 8) before trusting any of this on real data.

## 1. Verification status of this delivery

| Item | Status |
|---|---|
| Sandbox used for this session | Python 3.12, **no network**, **no** `pytest`, `fastapi`, `httpx`, `python-multipart`, `rank_bm25` |
| How tests were run | `python -m unittest discover -s tests -t .` (all tests are `unittest`-style); `rank_bm25` replaced by the small stand-in in `tests/_support.py` |
| Result here | **285 tests: 277 pass, 3 fail, 5 skipped** |
| The 3 failures | `tests/test_retrieval_legacy_golden.py` (all 3). They compare legacy scores to numbers frozen from the *real* BM25; the stand-in produces different scores. They are expected to pass with `rank_bm25==0.2.2` (checkpoint 2 reported them passing); **that was not re-verified here** |
| The 5 skipped | `HttpEndpointTests` (FastAPI `TestClient`) — skip automatically without fastapi/httpx/python-multipart. **Never executed in this session.** The same flow is covered without HTTP by calling `answer_question` directly |
| Earlier claims (122 passed, benchmark numbers) | From checkpoint 2 with real BM25. Not reproducible in this sandbox |

Action for you: `pip install -r requirements-local.txt pytest httpx python-multipart`, then `python -m pytest -q`. Expect 0 failures and 0 skips; if any
golden test fails, tell me — it would mean legacy behaviour changed.

## 2. Actual data flow (traced by calling the code)

`POST /api/v1/chat` (`api/main.py`, validates 1–3000 chars) → `answer_question` → `retrieve(query, limit=5)` →
`_ensure_state` (picks `data/index_fast/chunks.jsonl`, else `data/index/chunks.jsonl`; cheap stat-signature check, rebuild on change,
last-known-good kept on failure) → score every chunk → per-document cap (2 chunks) → `_build_sources` →
contact shortcut (`_answer_contact_from_official_page`) → `_generate_with_llm` (`_filter_admission_evidence`, context = up to 5 chunks ×
3000 chars with title/URL/verification, `requests.post(.../chat/completions)`, `max_tokens=300`) → answer + `sources` + `mode`.

Modes returned: `llm_grounded`, `insufficient_evidence`, `generation_unavailable`, `official_contact_source`, `contact_not_verified`, and (new) `index_unavailable`.
The frontend reads `answer`/`sources` and never branches on `mode`, so adding a mode is frontend-safe (frontend not changed).

## 3. Findings

| ID | Finding | Evidence | Status |
|---|---|---|---|
| F1 | Hindi/Telugu text produced zero tokens (ASCII-only tokenizer), so such queries never matched, even same-script pages | tests `UnicodeTests`, `DefectFixTests.test_f1_*` | **Fixed** (improved mode) for keyword queries |
| F2 | Any single shared word gave score > 0 → off-topic questions ("Best pizza near campus") sent 5 irrelevant pages to the LLM and returned them as sources | `test_f2_*`, flow test `test_legacy_rollback_sends_irrelevant_context` | **Fixed** (relevance floor); residual limit below |
| F3 | `B.Tech`/`M.Tech` both became token `tech`; `btech` never matched `B.Tech` | `test_f3_*` | **Fixed** (degree normalisation) |
| F4 | Every chunk's text re-tokenized on every query | synthetic latency: 5.0 → 0.6 ms median at 135 chunks, 215 → 19 ms at 5 400 chunks | **Fixed** (per-chunk token sets built once per index) |
| F5 | No plural stemming (`fees`/`fee`), no abbreviations (`CSE`, `ECE`, `HOD`) | `test_f5_*` | **Fixed** (conservative plural stemmer + synonym groups, extensible via `data/retrieval_synonyms.json`) |
| F6 | Missing index looked identical to "no match" | `tests/test_index_health.py::MissingIndexTests` | **Fixed**: mode `index_unavailable` |
| F7 | Admission questions keep only `svce.edu.in/admission.php` as source; if not retrieved, the answer had `sources: []` | `AdmissionSourcesTests` | **Fixed** (falls back to retrieved pages) |
| F8 | JSON `null` url/title became the literal URL `"None"` | `NullMetadataFlowTests`, `MetadataNormalisationTests` | **Fixed** |
| F9 | Contact answer is a hard-coded literal, only gated on the contact page being retrieved → can go stale | code reading | **Not changed.** Facts not verified |
| F10 | `data/index_fast` always outranks a newer `data/index`; a freshly published index is never served while the fast index exists | `StaleIndexTests.test_fast_index_shadows_newer_published_index` | **Not changed.** The diagnostic warns (`PUBLISHED_INDEX_SHADOWED`) |
| F11 | LLM `max_tokens=300` can truncate answers; "generation_unavailable" is shown both on LLM failure and when no LLM is configured | code reading, `LLMNotConfiguredTests` | **Not changed** |
| F12 | Improved mode's "distinctive term" floor rejected questions whose words occur in many chunks — e.g. navigation text ("Placements", "Admissions", "Contact Us") repeated on every page | found by running the diagnostic on the synthetic corpus: *"Tell me about placements"*, *"admissions"*, *"examination"* all returned nothing although matching pages had coverage 1.0 | **Fixed in part** (below) |

### F12 in detail (found late; the earlier benchmark did not contain topic-only questions)
Before the fix, improved mode returned **no chunks** for `placements`, `Tell me about placements`, `Tell me about admissions`, `examination`
on the synthetic corpus. Fix (`QualityConfig.meta_match_distinctive`, default on): a matched query term that is also in the chunk's **title or URL path** counts as
distinctive, because the page is then actually about that topic. Before/after on 48 synthetic questions (38 benchmark + 10 topic probes), improved mode:
the 4 refused topic questions are now answered; all 8 unanswerable/off-topic benchmark queries return exactly what they returned before; two
department questions gained one loosely related extra page (`/departments/civil`, shares the word "department" in its title).

**Residual limits (pinned by tests so they are not forgotten):**
- If a question's words are frequent in page *bodies* and absent from all titles/URLs, improved mode still refuses
  (`test_known_limitation_topic_that_dominates_body_text_is_refused`; legacy would answer).
- On a one-chunk index with no title match, improved mode refuses everything (`test_single_chunk_index_body_only_match_is_a_known_limitation`).
- A single topical word shared with an unrelated page ("cricket world cup" vs a sports page) cannot be separated lexically (`test_documented_limitation_*`).
- Not stemmed: Indic inflection, irregular English forms. **Cross-language retrieval is impossible** (English question for a Telugu-only page, or reverse): `test_cross_script_is_a_documented_limitation`. A Hindi/Telugu *question* only works when the index contains Hindi/Telugu text; whether SVCE's index does is unknown to me.

## 4. What changed

New: `api/retrieval_quality.py` (lexical layer: degree normalisation, Unicode tokenizer, plural stemmer, synonyms, title/URL field, phrase bonus, relevance floor,
near-duplicate skip — each switchable via `QualityConfig`), `diagnostics/` (read-only CLI), tests (below), `evaluation/synthetic/` (corpus + benchmark), docs.
Modified: `api/retrieval.py` (BOM + CRLF preserved): `RETRIEVAL_MODE` = `legacy|improved` (default `improved`, read per call — no restart), dispatcher, `_retrieve_legacy`
(unchanged logic), `_retrieve_improved`, `index_unavailable`, `_build_sources` fallback, metadata normalisation, new status keys. `api/main.py`, frontend, ingestion: **unchanged**.
No embeddings, vector DB or external service were added.

**Rollback:** set `RETRIEVAL_MODE=legacy` (no restart). Legacy is proven identical to the original on 13 heuristic + 38 synthetic queries by `tests/test_retrieval_legacy_golden.py` (needs real BM25 to pass).

## 5. Synthetic results (SYNTHETIC; real BM25; produced at checkpoint 2, i.e. BEFORE the F12 fix; not regenerated here)

135 chunks, 38 queries (30 answerable, 8 unanswerable), `evaluation/synthetic/results/benchmark_results.json`:

| | legacy | improved |
|---|---|---|
| hit@1 / hit@3 / hit@5 (answerable) | 0.67 / 0.77 / 0.80 | 0.93 / 0.97 / 0.97 |
| MRR | 0.72 | 0.95 |
| answerable questions returning nothing | 5 | 0 |
| unanswerable questions still returning pages | 3 of 8 | 1 of 8 |
| median latency, 135 / 1 350 / 5 400 chunks | 5.0 / 54 / 215 ms | 0.6 / 4.7 / 19 ms |

Per defect class, improved fixed Indic keyword (recall@3 0 → 1.0), degree names (hit@1 0.5 → 1.0), plurals (hit@1 0.75 → 1.0), partly synonyms (0.375 → 0.875 recall@3).
Ablations: removing the relevance floor raises unanswerable-with-pages 1 → 3; removing Unicode tokens costs 4 answerable queries; the other techniques each matter 0–1 queries here.
`min_coverage` sweep: 0.25 removes the last unanswerable hit with no loss, 0.35 loses one control query; default stays 0.15 (not tuned on real data).
Cross-script (X01) is 0 in both modes. Treat all numbers as demonstrations on invented data.

## 6. Tests added in this delivery

| File | Tests | Covers |
|---|---|---|
| `tests/test_retrieval_quality.py` | 76 | tokenizer, degrees, stemming, Unicode, URL tokens, synonyms (+ bad/missing files), config/env, `QualityIndex` (coverage, phrase, duplicates, empty chunks), defect-fix behaviour per class on the synthetic corpus, result shape, mode switching, fallback when the quality index fails, title/URL distinctiveness |
| `tests/test_backend_llm_flow.py` | 31 (5 skipped without fastapi) | question → retrieval → LLM payload (context, URLs, verification, 3000-char cut, ≤5 sources, auth header/model/URL), sources returned, no LLM call on no-match, timeouts/HTTP errors/empty or malformed completions, key never logged, LLM not configured, missing index, admission sources, null URLs, contact path, legacy vs improved |
| `tests/test_index_health.py` | 28 | missing/empty/whitespace/all-invalid/bad-UTF-8/BOM/null metadata/duplicate ids/one-chunk/huge or Indic chunks, BM25 or quality-layer failure, stale (corrupt update, deleted file, recovery, reload, fast-shadows-published) |
| `tests/test_diagnostics.py` | 30 | report contents, **index bytes/mtime/listing unchanged**, no files created, exit codes, every warning code, usage errors, network blocked, real credentials never used or printed, `.env` not read by default (secret-named variables scrubbed with `--use-env`), clean-interpreter `--help` |

## 7. Index-health behaviour (as tested)

Missing, empty, all-invalid or undecodable files are rejected and never become "valid empty" state; with no usable index every question gets `index_unavailable` (not "no match").
Valid lines survive invalid neighbours; a UTF-8 BOM only costs the first line. A bad update leaves the last-known-good index serving, `serving_stale=true` and `last_error` set, and it recovers when fixed.
A failure of the improved layer never rejects an otherwise valid index (legacy scoring is used; `improved_index_error` says why).

## 8. Diagnostic CLI — run this on your real indexes

```
python -m diagnostics                       # uses <project>/data
python -m diagnostics --data-dir D:\path\to\data --top 5
python -m diagnostics --questions my_questions.txt --json > report.json
```
Read-only: reports selected index and why, size/mtime/sha256, chunk and data-quality counts (invalid lines, missing URL/title, duplicates, non-ASCII/Indic share),
term-frequency profile, legacy-vs-improved top hits with score/coverage/URL/snippet, and the backend→LLM flow with a **fake LLM** (shows which pages would be sent and cited).
`.env` is not read unless `--use-env`; network is blocked; it fingerprints the data directory before and after and fails if anything changed.
Exit codes: 0 clean, 1 warnings, 2 errors (or data changed), 3 usage. Reading a file may update its access time (OS behaviour); contents and modification times are untouched.

What to look for: `IMPROVED_REFUSES_*` (questions that legacy answered and improved does not — decide whether noise was removed or a real question was lost),
`DOMINANT_TERMS`, `PUBLISHED_INDEX_SHADOWED`, `MISSING_URLS` (such chunks can never be cited), `ANSWER_WITHOUT_SOURCES`, `INDIC_QUERY_NO_MATCH`.
The default questions are generic probes, not facts; supply real student questions with `--questions`.

## 9. Default mode — my judgement

`improved` stays the default: on synthetic data it removes the proven defects (Indic queries, degree names, plurals, abbreviations, irrelevant pages sent to the LLM) and is much faster.
But F12 was only caught late and shows synthetic benchmarks can miss false refusals on real, boilerplate-heavy pages. **Before relying on it, run the diagnostic with ~30 real student questions
and read the `IMPROVED_REFUSES` flags. If legitimate questions are refused, set `RETRIEVAL_MODE=legacy` and send me the report.** This is a recommendation, not a measured result.

## 10. Not done / open

- Real-index accuracy; real BM25 and HTTP-level test runs in this session; regenerating the benchmark after the F12 fix (needs `rank_bm25`: `python -m evaluation.synthetic.benchmark`).
- F9 (hard-coded contact text), F10 (fast index shadowing), F11 (token limit) — documented only; no college facts were verified or changed.
- Old `api/*_before_*.py` / `*_backup.py` copies and `docs/wip/*` remain as development leftovers; they are unused by the app.
- Not touched, per instructions: production indexes, `.env`, frontend, Git.
