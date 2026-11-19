# SVCE evaluation dataset

`svce_eval_questions.jsonl` — one JSON object per line. Currently the 20 starter questions from
`docs/EXAMPLE_QUESTIONS.md`, **all `needs_ground_truth`**: no production index is in the project, so no
expected source or answer has been verified. `candidate_sources` are hints taken from project files
(`docs/SOURCE_REVIEW.md`, `data/sitemap_urls.txt`); they are **never scored**.

## Fields
| Field | Meaning |
|---|---|
| `id` | Unique, letters/digits/`_-.` only |
| `question`, `category` | One of the 8 categories (see `evaluation/dataset.py`) |
| `question_kind` | `retrieval` (scored), `context_dependent` (needs earlier context; not scored), `verification_behavior` |
| `answerable` | `yes` / `no` / `unknown` — must be `unknown` unless verified |
| `expected_sources` | Verified source URLs (compared after normalising scheme, `www.`, trailing `/`; query string kept) |
| `expected_doc_ids` | Alternative: verified `doc_id` values from the index |
| `expected_keywords` | Verified facts/terms (used for diagnostics only) |
| `candidate_sources` | Unconfirmed hints; ignored by metrics |
| `expect_official_referral` | `true` if the answer must point the user to an official place to verify |
| `verification_status` | `verified` / `needs_ground_truth` / `unverified` |
| `verified_by`, `verified_on` | Required when verified (`YYYY-MM-DD`) |
| `notes` | Free text; record academic year/date for time-sensitive facts |

## Adding verified ground truth
1. Open the live page/PDF yourself and confirm the answer and the exact URL.
2. Edit the record: set `answerable` (`yes`/`no`), fill `expected_sources` (and `expected_keywords`),
   set `verification_status` to `verified`, fill `verified_by` and `verified_on`.
3. Run `python -m evaluation` — the loader rejects incomplete verified records, and rejects expected
   sources on non-verified records.

Example (fictional URL, not a college fact):
```json
{"id":"EXAMPLE-001","question":"Where is the sample policy?","category":"General college information","answerable":"yes","expected_sources":["https://example.test/policy"],"expected_keywords":["sample"],"verification_status":"verified","verified_by":"your name","verified_on":"2026-01-31"}
```
`answerable: "no"` (verified) means the website does not publish the answer; no expected sources are
allowed and the grounding check then expects an official-verification referral.

`template_record.jsonl` is a blank, valid starting record (not part of the dataset).

---

## Running the full application (CP2: students, enquiries, admin)

```bash
# 1. Backend (from the project root)
pip install -r requirements-local.txt -r requirements-additions.txt
cp .env.example .env          # then edit; never commit .env
python -m api.manage create-admin --email you@example.com --name "Your Name"   # prompts for a password
python -m api.manage add-programme "<a programme SVCE really offers>"           # or use Admin > Programmes
python -m uvicorn api.main:app --port 8000

# 2. Frontend, development (hot reload, proxies /api to port 8000)
cd frontend && npm install && npm run dev        # http://127.0.0.1:5173

# 3. Frontend, production (FastAPI serves the built files at http://127.0.0.1:8000)
cd frontend && npm run build
```

Pages (hash routes): `#home`, `#assistant`, `#enquiry`, `#register`, `#login`, `#dashboard` (students),
`#admin/login`, `#admin`, `#admin/enquiries`, `#admin/enquiries/<id>`, `#admin/programmes` (administrators).
Tests: `python -m pytest tests` (backend) and `tests/e2e/ui_flows.py` (browser; see its docstring).
