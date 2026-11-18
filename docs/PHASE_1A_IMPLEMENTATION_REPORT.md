# Phase 1A Implementation Report - safe index publishing

## Fixes made in this session (review of checkpoint 1)
1. **Hidden fallback failure** (`api/retrieval.py`): when an invalid `index_fast` was rejected and `data/index` loaded instead, `last_error` was cleared. Rejections are now kept in `last_error`.
2. **Status could say "not ready"** before any query: `get_index_status()` now runs the cheap change check first. It also reports `serving_index` (fast/index), `sha256`, `serving_stale` and candidate paths.
3. **Ingestion status accuracy**: `api/main.py` compared path strings only. New `describe_serving()` compares resolved path AND content hash with the published index. Job status is `completed` only if the new index is served, otherwise `published_not_serving` with a reason (higher-priority fast index, or failed reload). `/api/v1/ingest/status` also returns a live `serving` block; `/health` uses the refreshed status.
4. **Publisher** (`ingestion/index_publisher.py`): a failed post-publish verification with no previous index left the bad file live; it is now removed (or the backup restored). `live_index_modified` in `.last_publish.json` is now truthful (`IndexPublishError.live_modified`). `sha256_of` made public.
5. `run_ingestion` report now includes `sha256` of the published index.

## Fast pipeline integration
- `build_fast_index.build_index()` (already staged in checkpoint 1) verified by tests: stages, validates, backs up, atomically publishes; failed/empty/partial builds raise and leave `data/index_fast` and `fast_index_report.json` untouched (attempt goes to `fast_index_last_attempt.json`).
- `fast_ingestion.py` never wrote the index; it now has `--build-index` (publishes only via `build_index`, skipped with exit 1 if zero documents were collected). Default behaviour unchanged.
- Both index paths (`data/index`, `data/index_fast`) keep their locations; fast is preferred when valid. Chunk sizes and scoring untouched.

## Tests added (`tests/`, unittest-style, also run under pytest)
- `test_index_publisher.py` (31): publish, backup, empty/missing/corrupt/invalid-UTF-8/whitespace candidates, invalid ratio, min chunks, shrink guard, swap failure, backup failure, post-verify failure (with/without previous), pruning, locks (fresh/stale/released), rollback (reversible, named, none, corrupt, unknown), fast builder (success, empty source, blank docs, partial, mid-build crash), `run_ingestion` with a fake crawler (good, empty, blank).
- `test_retrieval_reload.py` (23): missing/empty/garbage index, old-only, fast-only, priority, fallback error visibility, no fallback when active fast breaks, reload without restart, no rebuild when unchanged, failed/empty/deleted reload keeps last-known-good, no re-parse of known-bad content, recovery, BM25 failure, `describe_serving` cases, concurrent readers during 12 publishes + a rejected publish (no errors, no mixed-index results), single build on concurrent cold start.

## Exact results
Command: `python3 -m unittest discover -s tests -t .`
Result: `Ran 56 tests ... OK` (31 publisher + 23 retrieval + 2 existing `test_text_processing`). Also run from the extracted checkpoint ZIP: 56 OK.

## Limitations (please read)
- Sandbox had **no network, no pytest, no `rank_bm25`, no fastapi/pydantic**. Tests used `unittest`; `tests/_support.py` installs a small BM25 stand-in **only when `rank_bm25` is missing**. Retrieval logic was therefore tested against the stub, not real BM25 scores. Re-run on your machine: `python -m pytest -q`.
- `api/main.py` endpoints could not be executed (FastAPI absent); changes were syntax-checked and the logic they use (`describe_serving`, `get_index_status`) is tested directly. Please smoke-test `/api/v1/index/status`, `/api/v1/ingest/status` locally.
- No live crawl, no real indexes, no `.env` read; all fixtures synthetic in temp dirs.
- Multi-process note: each uvicorn worker has its own cache; each reloads on file change automatically, but `/index/reload` only affects the worker that handles it.

## Correction (added in Phase 1B)
The test split above is wrong: the 56 passing unittest tests are 31 (`test_index_publisher`) + 25 (`test_retrieval_reload`).
The 2 existing pytest-style tests in `tests/test_text_processing.py` are not collected by `unittest` and were not part of that
count; they were run directly in Phase 1B and pass.
