# Phase 1B Implementation Report - retrieval and answer-grounding evaluation

## Summary
Evaluation infrastructure is built and tested. **No retrieval accuracy numbers exist yet**: the project has no
production index and no verified ground truth, so the shipped dataset has 0 verified questions and the evaluator
scores 0 of 20. No retrieval scoring or answer generation code was changed (nothing in the data justifies it).

## Evaluation architecture (`evaluation/`)
| Module | Role |
|---|---|
| `dataset.py` | JSONL loader + strict validation (all errors reported); URL normalisation |
| `metrics.py` | Recall@K, Hit@K, MRR (pure functions) |
| `retrieval_eval.py` | Runs questions through the existing `api.retrieval.retrieve` (top-5, plus a 50-deep run for diagnostics); `serve_index_file()` points retrieval at any chunks file read-only |
| `weakness.py` | Per-question diagnostics for verified questions; neutral observations for unverified ones |
| `grounding.py` | Deterministic answer-vs-evidence checks |
| `report.py` | JSON + Markdown reports, baseline comparison |
| `__main__.py` | CLI: `python -m evaluation [--chunks FILE] [--answers FILE] [--save-baseline L] [--compare JSON]` |

Safety: reads indexes only (a test checks bytes, mtime and directory listing are unchanged); no crawl; no network;
no LLM call unless `--run-answers --allow-llm-calls` is given (refused with exit 3 when an LLM is configured); `.env` is
never read by the evaluation code. The CLI refuses to run (exit 4) without the real `rank_bm25` package. Reports
mark `valid_as_retrieval_performance` false when no index exists or the BM25 backend is not the real package.

## Dataset
`evaluation/dataset/svce_eval_questions.jsonl` - the 20 starter questions from `docs/EXAMPLE_QUESTIONS.md`.
| Category | Questions |
|---|---|
| General college information | 7 (incl. 4 context-dependent/behavioural meta questions) |
| Examinations and academic regulations | 4 |
| Admissions | 2 |
| Faculty and contact | 2 |
| Fees and scholarships | 2 |
| Courses and departments | 1 |
| Placements | 1 |
| Hostel and transport | 1 |

Ground truth: **verified 0, needs_ground_truth 20, unverified 0**. Retrieval-scorable: 0. The loader forbids expected
sources/keywords on non-verified records, so unverified questions can never be scored. `candidate_sources` (5 records:
Q1, Q2, Q5, Q6, Q8) hold URLs that appear in project files (`SOURCE_REVIEW.md`, `sitemap_urls.txt`); they are hints and
are never scored. Q16-Q19 are marked `context_dependent` (need earlier context), Q20 `verification_behavior`.
Template and instructions: `evaluation/dataset/README.md`, `template_record.jsonl`.

## Metrics
Per question with N verified expected sources (ranks over the returned chunk list): Recall@K = found within top K / N
(K = 1, 3, 5); Hit@K; reciprocal rank; MRR = mean RR. Reported overall and per category; scopes with no evaluated
question show `n/a` (never 0). Reports separate evaluated questions from unverified ones, which get observations only
(result count, distinct URLs).

## Answer grounding (deterministic)
Findings: unsupported numbers/year ranges (high severity when the sentence concerns fees, placements or admissions,
otherwise medium), unsupported phone/email/URL, low lexical support of a sentence, answer without evidence that does
not refer the user to official verification, missing referral where expected (verified-unanswerable questions, Q20),
time-sensitive question without a verification pointer (low). Verdicts: `fail` / `warnings` / `no_issues_found`.
`no_issues_found` does **not** mean correct. Answers come from `--answers FILE` or `--run-answers` (guarded).
An LLM-based evaluator was **not** implemented (optional; avoids paid calls and unverifiable judgements).
Limits: lexical only; paraphrases and number words are not understood; evidence may itself be outdated.

## Retrieval weaknesses
Measured automatically on verified questions (flags): relevant missing from top-K / ranked below top-K / not retrieved /
source absent from index (a data problem, not scoring); irrelevant chunks above the relevant one; outranked by a better
title match; query terminology absent from the expected source; numeric/table content not ranked first; low source
diversity. **With no ground truth none of these has been measured, so no tuning was made.**

Code-reading hypotheses to test once real data exists (not changes, not evidence):
1. `TOPIC_TERMS` has no topics for examinations/regulations, faculty or hostel (hostel/transport sit under "fees").
2. Large hard-coded boosts (+12 admission-process text, +5 placement title/url, +50 contact URL) can dominate BM25.
3. Hard-coded placement years (2023-24 to 2025-26) will go stale.
4. `_build_sources` limits admission questions to a single URL, reducing source diversity.
5. `_tokens` drops one-character tokens, so "B.Tech"-style terms and numbers need checking on table content.
Test each against the diagnostics flags before changing anything.

## Changes to retrieval / answer generation
None. `api/retrieval.py` and `api/main.py` are unchanged (sha256 of retrieval.py recorded in `evaluation/baselines/README.md`).
Only `tests/_support.py` (stub marks itself `__stub__`) and `.gitignore` were modified.

## Tests and exact results
Command: `python3 -m unittest discover -s tests -t .` -> `Ran 117 tests ... OK`.
- Phase 1B new: 61 = `test_eval_dataset` 16 (incl. shipped dataset and template checks) + `test_eval_metrics` 10 +
  `test_eval_grounding` 17 + `test_eval_retrieval` 18 (evaluation, read-only index, reports, comparison, CLI).
- Phase 1A regression: 31 (`test_index_publisher`) + 25 (`test_retrieval_reload`) = 56 passed.
- Existing `tests/test_text_processing.py` (2 pytest-style functions) are not collected by `unittest`; they were
  called directly and both passed.
**Correction to the Phase 1A report:** it said 56 = 31 + 23 + 2. The correct split is 31 + 25 under unittest; the 2
existing tests were not part of that run.

**Retrieval tests ran against a BM25 stand-in** because `rank_bm25` (and pytest/fastapi) are not installed in this sandbox
and there is no network. These tests verify plumbing and logic, not retrieval quality. Re-run with pytest/real
`rank-bm25` on your machine: `python -m pytest -q`.

## Known limitations
- No real retrieval results; CLI could not be run against the real backend here.
- Ground truth must be verified by a human against the live site; none was invented.
- Diagnostics use the existing tokenizer and one retrieval run per question; per-document limits in `retrieve()` shape ranks.
- Evidence for `--run-answers` is re-retrieved (top 5) and is a superset of what the LLM sees after admission filtering.
- `api/main.py` endpoints still untested here (FastAPI absent).

## Next recommended task
Verify ground truth for the highest-value questions (Q2, Q5, Q8, Q11) by reading the live pages, build the real index,
run `python -m evaluation --save-baseline before_change`, then use the diagnostics flags to choose a single, evidence-backed
scoring change and compare with `--compare`.
