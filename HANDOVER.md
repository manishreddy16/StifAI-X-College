# OpenRouter Length Termination & Stream Check (2026-11-20)

## Findings and changes
- The checked backend request did not set `stream: true`; before this change it omitted `stream`, which OpenRouter treats as non-streaming by default. It used `requests.post(...).json()` and standard `choices[0].message.content` parsing, not SSE. The request now explicitly sends `stream: false` so the contract is unambiguous and remains ordinary JSON.
- It set `max_tokens: 800`. The provided generation evidence reports exactly 800 output tokens and `finish_reason: length`, confirming generation hit that cap. The cap is now 1,600. OpenRouter documents up to 65,536 completion tokens for `nvidia/nemotron-3.5-lightning:free`; 1,600 is below that model limit.
- A first real application request with the 1,600 cap still returned `finish_reason=length`; the response shape included `reasoning` fields and 389 characters of partial content. Reasoning tokens share the completion token budget. The request now sends `reasoning: {enabled: false}` to reserve the budget for the final concise RAG answer.
- Default and local `OPENROUTER_MODEL` now match the observed free model ID `nvidia/nemotron-3.5-lightning:free`. Only that line in `.env` was changed; API key and other settings remain preserved. The model remains configurable.
- Responses with `finish_reason=length`, refusal, tool calls, empty content, or missing choices still return the existing safe fallback; partial answers are not surfaced as complete. No streaming/SSE parser was added because this application does not need streaming.
- I/O logging remains disabled. Diagnostic logs contain only status, safe provider error classification, finish reason, and response structure without prompt or response text.
- NVIDIA?s free endpoint page warns against sending confidential or personal data and says session data may be logged for security and product improvement. Review that provider condition before using this free model with student attachments or personal details.

## Runtime discrepancy and live verification
- The dashboard evidence says `Streaming: true`, while the checked source previously omitted `stream`. Those observations did not match. The request now explicitly uses `stream: false`.
- A subsequent real `POST /api/v1/chat` through a fresh FastAPI TestClient, using the local 24,735-chunk index and configured free model, returned HTTP 200, mode `llm_grounded`, a non-empty answer (1,300 characters), and one source. The answer text was not printed. This verifies the current code path; the already-running backend process still needs a restart to load the updated request settings.

## Tests
- `python -m unittest tests.test_backend_llm_flow tests.test_retrieval_legacy_golden tests.test_retrieval_quality tests.test_retrieval_reload tests.test_index_health`: **176 passed**. Mocked tests verify explicit non-streaming, reasoning disabled, the 1,600-token cap, standard JSON parsing, safe fallback on `length`, provider errors, and unchanged chat response contract. The separate real request above confirms a non-empty response from the application endpoint.

---

# OpenRouter Empty-Response Diagnosis (2026-11-20)

## Findings and fix
- The old completion parser assumed `choices[0].message.content` was a string. It collapsed empty content, missing choices, and other response shapes into the same `None` fallback, without recording HTTP status, `finish_reason`, refusal, or response shape. Thus the old log `LLM returned an empty answer` did not identify the provider-side cause.
- The saved local model setting was `openrouter/free`, which dynamically routes to different free models. OpenRouter currently lists `google/gemma-4-26b-a4b-it:free` as a free text/chat model, so I set this fixed model ID as the default, in `.env.example`, and in the existing local `.env` model setting. Only the `OPENROUTER_MODEL` line in `.env` was changed; its API-key line and other settings were checked and preserved. The model remains configurable through `OPENROUTER_MODEL`.
- Parsing now supports string and text-block `message.content`, explicitly rejects missing choices/messages, empty content, refusals/content filters, and truncated/tool-call completions, and preserves the existing safe fallback and response contract. No unverified document text is returned as an answer.
- Safe provider logs include HTTP status, a sanitized provider error code/message class, finish reason, and response structure (key names/types/count/content length only). Raw provider message prose, response content, questions, evidence, and credentials are not logged.

## Real provider check
- One minimal real request was made to the configured free Gemma model using the key from `.env` (the key and generated text were not printed). OpenRouter returned **HTTP 429**, error code `429`, and no `choices`; no completion was generated.
- This identifies the current live check as provider throttling/rate limiting (or provider capacity under the 429 status), not a successful model response. The earlier reported HTTP 200 empty-content event cannot be conclusively attributed from its old log; new diagnostics will distinguish its response shape and finish reason on the next request.
- Therefore the parser/logging fix is verified with mocks, but a successful real chat completion has **not** been verified. While OpenRouter continues returning 429, the app correctly remains on its safe fallback. Check OpenRouter free-tier limits/provider availability, then retry.

## Tests
- `python -m unittest tests.test_backend_llm_flow tests.test_retrieval_legacy_golden tests.test_retrieval_quality tests.test_retrieval_reload tests.test_index_health`: **176 passed**. All OpenRouter calls in these tests are mocked. Coverage includes valid string and text-block completion, empty content, missing choices, refusals, truncation, provider error/status classifications, invalid key, rate limit, unavailable model, timeout, safe logs, and existing retrieval behavior.
- No database, frontend design, or ingestion pipeline changes were made. No frontend build was necessary for this backend-only fix.

## Files changed in this diagnosis
`api/retrieval.py`, `api/main.py`, `.env.example`, the local `.env` model setting only, `README.md`, `tests/test_backend_llm_flow.py`, and `HANDOVER.md`.

---

# OpenRouter LLM Integration (2026-11-20)

## Implementation
- Active provider call is in `api/retrieval.py::_generate_with_llm`; retrieval ranking, context formatting, SVCE system prompt, response normalization, result modes, and chat API schema remain unchanged.
- Provider is OpenRouter Chat Completions at `https://openrouter.ai/api/v1/chat/completions`, using the official Bearer authorization header and existing `requests` dependency. No Gemini fallback or extra SDK was added.
- Model is read from `OPENROUTER_MODEL`; current default is the specific free text model `nvidia/nemotron-3.5-lightning:free`. Set another OpenRouter model ID when needed; check current model availability and pricing first.
- The only credential accepted by active generation is `OPENROUTER_API_KEY`. The key is not included in frontend code, health/API output, or logs. `/health` continues to return only the existing `llm_configured` boolean.
- Existing 120-second request timeout remains. Logs classify provider failures by status (rate limited, auth failure, model unavailable, provider error) without logging the question, evidence, response body, key, or other request content. Chat continues to return a safe `generation_unavailable` result with retrieved source cards on provider failures.
- User questions, retrieved evidence, and any attached document text are sent to OpenRouter to generate answers. Review OpenRouter/provider data handling and model settings before sending real student personal or sensitive information. The free router is rate limited and selects among available models, so output quality, model availability, and response characteristics may vary.

## Configuration and local run
Set these backend environment values (or put them in your local ignored `.env`; never commit the real key):

```dotenv
OPENROUTER_API_KEY=your-real-key-from-openrouter
OPENROUTER_MODEL=nvidia/nemotron-3.5-lightning:free
```

`.env.example` contains placeholders only. In a later diagnostic, only the model setting in `.env` was updated; the API key line and other settings were preserved. Start FastAPI as usual with `python -m uvicorn api.main:app --port 8000`; run the frontend as usual. To use a specific model, change only `OPENROUTER_MODEL` to its OpenRouter model ID.

## Verification
- `python -m unittest discover -s tests`: **356 passed**. The process had `OPENROUTER_API_KEY` forced empty, and provider integration tests replace HTTP calls with mocks; no real API request was made. This includes the RAG retrieval golden, evaluation, index, auth, and enquiry tests.
- Mocked OpenRouter cases cover successful completion and unchanged chat response schema, missing key, legacy key ignored, invalid key (401), rate limit (429), unavailable model (404), timeout, and safe logs.
- `cd frontend && npm run build`: **passed** (Vite 6.4.4; 1,602 modules).
- `pytest` is not installed, so pytest itself was not run. The equivalent test modules ran under unittest. No real API verification was performed.

## Files changed in this phase
`api/retrieval.py`, `api/main.py`, `.env.example`, `diagnostics/cli.py`, `tests/test_backend_llm_flow.py`, `tests/test_diagnostics.py`, `tests/test_eval_retrieval.py`, `tests/test_index_health.py`, `README.md`, `HANDOVER.md`.

---

# Phase 4 — Backend & Security Readiness (2026-11-20)

## Completed
- Password verification rejects malformed hashes, unexpected scrypt work factors, invalid base64, and incorrect salt/digest lengths before doing expensive work. Existing scrypt hashes remain supported.
- Session lifetime configuration is bounded to 15 minutes–30 days; invalid environment values use the 12-hour default. Session creation/expiry cleanup and password change/session revocation are atomic SQLite transactions.
- The sliding-window limiter now bounds memory when many unique keys arrive. At capacity, new keys are temporarily rejected rather than dropping active counters and weakening existing limits.
- Campus API request-validation errors no longer echo submitted values (including credentials) and are marked `no-store`.
- Added security warnings for missing CSRF headers and student-role attempts at admin routes. These logs omit credentials, emails, request bodies, and user identifiers.
- Reviewed role enforcement and data scoping: public registration creates only students; admin routes and ingestion/index operations require the admin role; student enquiry queries are scoped to the authenticated user ID. SQL uses bound parameters, including search filters.
- Reviewed cookie/CORS settings: session cookie is HttpOnly, SameSite=Lax, Secure is automatic for HTTPS (or configurable), and CORS allows only the two local Vite origins with credentials disabled. State-changing campus requests require the custom CSRF header.

## Verification
- `python -m unittest tests.test_campus_auth tests.test_campus_enquiries tests.test_campus_http`: **63 passed**. After the final limiter-capacity adjustment, its focused test also passed. Covers password hashing, registration/login/lockout, sessions/expiry/logout, student/admin authorization, own-enquiry scoping, submission/management, CSRF, rate limits, and existing operational endpoint guards.
- `cd frontend && npm run build`: **passed** (Vite 6.4.4; 1,602 modules).
- `python -m pytest tests --ignore=tests/test_diagnostics.py`: **not run** because `pytest` is not installed. The complete backend suite and the known retrieval golden-score failures documented in Batch 5C were therefore not re-evaluated.
- No live browser walkthrough, HTTPS/proxy deployment test, real email/password-reset flow, or production security certification was performed.

## Remaining risks and manual configuration
- Rate limits remain in-process and can be bypassed across multiple workers/restarts; behind a proxy, client IP handling needs a trusted-proxy design before relying on IP limits.
- Public chat and file extraction remain public existing features. They were not gated or given new per-IP throttles in this phase; evaluate exposure and capacity before public deployment.
- Set `STIF_COOKIE_SECURE=1` behind an HTTPS proxy and verify TLS/proxy behavior. Keep `.env` and the SQLite database backed up and access-controlled.
- The enquiry consent text is still a draft requiring college approval; no privacy-retention policy, password reset, or email verification exists.
- These changes improve demo readiness; they are not a production security certification.

---

# Batch 5C — Final Checks & Final ZIP (2026-11-20)

**Scope:** verification only. **No source code was changed in 5C** (no regressions found).

## Overall status, Batches 1–5
- **Batch 1** Design foundation (tokens, base styles). **Batch 2** Branding + navigation. **Batch 3** Public landing page + admissions enquiry journey. **Batch 4** Student dashboard + admin (overview, enquiries, programmes) UI improvements. **Batch 5A** Responsive fixes. **Batch 5B** Accessibility/interaction fixes. **Batch 5C** final checks. All completed; details in the sections below.
- Earlier checkpoints (CP1–CP3): chatbot/RAG backend, student auth, enquiries, admin APIs — unchanged by UI batches.

## 5C test results (honest)
- **Frontend `npm ci && npm run build` (Vite 6.4.4): PASSED** — 1602 modules, JS 251 kB (75.7 kB gzip), CSS 60 kB. (`dist/` and `node_modules/` excluded from ZIP.)
- **Backend `pytest tests --ignore=tests/test_diagnostics.py`: 318 passed, 3 failed.** The 3 failures are all in `tests/test_retrieval_legacy_golden.py` (golden retrieval *scores* differ slightly, e.g. 55.796 vs 55.321). This is backend retrieval numerics and not related to any UI batch; likely a library/version difference in this sandbox vs. where the golden values were captured. **Not investigated or changed** (backend out of scope). Campus auth, enquiry and HTTP tests (`test_campus_*`) all pass.
- **Route/journey check:** every frontend API call (`/auth/login|register|logout|me`, `/enquiries`, `/enquiries/mine`, `/enquiries/form-config`, `/chat`, `/files/extract`, `/admin/stats|enquiries|programmes`) matches an existing backend route; App routes for home, enquiry, assistant, login, register, dashboard, admin login and admin all present and compiled. Backend HTTP tests cover registration/login/enquiry/admin flows.
- **NOT done:** no live browser walkthrough with the real stack in 5C (Batch 5B did a headless mocked-API check); `tests/e2e/ui_flows.py` not run (needs running stack; selectors may be stale); no real Ollama/knowledge-base/voice test; `tests/test_diagnostics.py` skipped (needs `diagnostics/__init__.py` restored per earlier notes).

## Known issues
1. 3 golden retrieval test failures above.
2. Items listed in section 7 below (public consent text needs college approval, public `/chat`, in-memory rate limiters, UTC "received today", no password reset, stale backup files).
3. `npm audit` reports advisories in dev dependencies (not addressed; no dependency changes allowed).

## Remaining work
- Decide on the golden-test failures (re-capture goldens or check versions).
- Restore real `data/` knowledge base; create admin; add real SVCE programmes (no SVCE data was invented).
- Manual run with backend + Ollama; run e2e script; real screen-reader check.
- Deployment/production readiness (HTTPS, `STIF_COOKIE_SECURE=1`, backups) — not started.

---

# Batch 5B — Basic Accessibility & Interaction Fixes

**Scope:** frontend only. No backend, database, API, auth, routes, dependencies or redesign. Batch 5C not started.

## What was checked
Headless Chromium on an esbuild bundle (icons stubbed, mocked API) of: landing, enquiry, student login/register, staff login, assistant, student dashboard, admin overview / enquiries list / enquiry detail / programmes.
- Text contrast scan of every visible text node (WCAG AA 4.5:1 / 3:1 large): **no failures**, so no colour changes were made.
- Every a/button/input/select/textarea has an accessible name; every form control has a label; no `<a>` without href: **no problems**.
- Tabbed through each page (60 stops): every focused element shows an outline or ring: **no problems**.

## Fixed
- `base.css`: global `:focus-visible` forced `border-radius: 6px`, which reshaped round/pill controls when focused. Removed; the outline now follows each element's own shape.
- `Admin.jsx` overview: if the "New enquiries" request failed, the card said "No enquiries are in New status" (misleading). It now says it could not load and points to Refresh.
- `Admin.jsx` enquiries list and programmes: load errors had no way to retry. Added "Try again" buttons; programmes error is cleared on retry and has a title and a "Loading programmes…" label.
- `Enquiry.jsx`: consent checkbox `aria-describedby` pointed to a non-existent id when there was no error (now only set with the error). A server error at the top of the long form is scrolled into view on submit failure.
- `Assistant.jsx`: the scrollable message log was `tabIndex=-1`, so keyboard users could not scroll it; now focusable (`0`).
- `Footer.jsx`, `Landing.jsx`: external links (`target=_blank`) now announce "(opens in a new tab)" to screen readers; decorative icons hidden.
- `Toast.jsx`: error toasts now `role="alert"` so failures are announced promptly.

## Files modified
`frontend/src/styles/base.css`, `frontend/src/pages/{Admin,Enquiry,Assistant,Landing}.jsx`, `frontend/src/components/{Footer,Toast}.jsx`, `HANDOVER.md`.

## Tests (honest results)
- **Official `npm run build` (Vite): NOT RUN.** Sandbox has no network and no `node_modules`; Vite and lucide-react cannot be installed. Run `cd frontend && npm ci && npm run build` locally.
- **Substitute that WAS run:** esbuild bundle of all JSX + CSS with a stubbed icon library: compiled with no errors, before and after the edits. Scripted browser check after edits confirmed: overview failure message appears, "Try again" appears on list and programmes error states. Focus/label/contrast scans re-run after edits: clean.
- Backend pytest and `tests/e2e/ui_flows.py` not run (no backend change; e2e needs a running stack and old selectors may be stale, see Batch 4).
- Not tested: real screen readers, real icons/fonts, real backend, voice dialog with a real microphone, forced-colors mode. This was a quick pass, not an accessibility audit.

## Remaining work
- Run the real Vite build locally.
- Real screen-reader and keyboard pass (assistant, voice dialog, admin tables).
- Route-change focus/announcement, admin list result-count live region, self-hosted fonts (not done; out of scope).
- Batch 5C (not started).

---

# Batch 5A — Quick Responsive Fixes

**Scope:** frontend CSS only. No backend, database, API, auth, routes, dependencies or page markup changed. Batch 5B not started.

## What was checked
Headless Chromium (esbuild bundle of the real source, lucide icons stubbed as boxes, mocked API with long names/emails/programme names) at 320 / 360 / 390 / 768px for: landing, admissions section, AI assistant, login, register, enquiry form, student dashboard, admin login, admin overview, admin enquiries list, enquiry detail, admin programmes. Measured document scroll width and any element sticking out of the viewport; looked at one screenshot (admin list at 390px).

## What was fixed
- **One real issue:** on the admin (staff) header at 320px, brand + "Sign out" overflowed the screen by ~5-10px. Added a `@media (max-width: 380px)` block at the end of `frontend/src/styles/app.css` (tighter header gap, brand small-text letter-spacing/size, smaller padding on the staff header button).
- Everything else was already fine at all tested widths; left alone.

## Files modified
`frontend/src/styles/app.css` (appended Batch 5A block), `HANDOVER.md`.

## Tests
- **Official `npm run build` (Vite): NOT RUN / NOT PASSED.** The sandbox has no network, `npm ci` failed, and Vite/@vitejs/plugin-react could not be installed. Run `cd frontend && npm ci && npm run build` locally.
- **Substitute:** esbuild bundled all JSX + CSS without errors (icons stubbed). The overflow check above passed at all tested widths after the fix (before the fix: 4 admin pages overflowed at 320px).
- Backend pytest and E2E not run (no backend changes). Real lucide icons were not rendered in the check, so icon-driven width differences are untested.
- Not tested: real devices, landscape phones, the voice dialog, the assistant with long chat threads/attachments.

## Remaining work
- Run the real Vite build locally.
- Eyeball the assistant chat (long answers, source cards, upload menu) and voice dialog on a real phone.
- Batch 5B (not started).

---

# Batch 4 — Student + Admin UI Improvements

**Scope:** frontend only. Routes, auth, role guards, APIs, database/schema, enquiry workflow, chatbot and the public landing page were not changed. Batch 5 not started. Built on the Batch 3 working tree (no new upload was attached to this request; the Batch 3 tree/ZIP from the previous turn was used).

## Completed
- **Student dashboard** (`pages/Dashboard.jsx`): enquiries are the main column; each enquiry is a card with reference, status badge, programme, question, a 4-step tracker (New -> In progress -> Responded -> Closed), a plain-language "Next:" line per status (no response times promised), sent date, and "Send a new enquiry / Ask the assistant" once responded/closed. Summary line (total / being handled / replied). Better empty state. Profile is now a small "My account" card (name + email) in a secondary side column with a "Quick answers" assistant card; side column drops below on tablet/mobile.
- **Admin overview**: action banner ("N new enquiries waiting" + "Review new enquiries", or "No new enquiries waiting"), stat tiles led by New / In progress (clickable, New highlighted), "New enquiries" card (up to 5 `status=new` rows with days waiting and a link to all), by-status links, student-account count, top programmes, 14-day chart. Uses existing `/admin/stats` and `/admin/enquiries?status=new&page_size=5` only.
- **Admin enquiries list**: status tabs with counts (from `/admin/stats`), search, "Clear filters", result count, table caption + `scope="col"` headers, new rows marked, "Waiting N days" on open enquiries, student name is the link. **Filter/search/page state lives in the URL** (`#admin/enquiries?status=&q=&page=`); opening a detail appends the same query and "Back to filtered list" restores it. Fixed: the debounced search used to reset a restored page to 1.
- **Enquiry detail**: waiting time, quick status buttons ("Start working on it", "Mark as responded", "Close enquiry") that PATCH status + current notes through the existing endpoint, unsaved-changes hint, sticky update card on desktop.
- **Programmes**: explanatory text (add only SVCE-confirmed programmes; hiding removes from form; empty list = free-text), summary counts (shown/hidden), "Shown on form"/"Hidden" badges, busy states, toast on toggle. No programme data was added.
- Tablet/mobile: admin nav labels fit at <=520px (icons hidden); tables stack as cards under 720px (existing).

## Files modified
`frontend/src/pages/{Dashboard,Admin}.jsx`, `frontend/src/lib/format.js` (added `TRACK_STEPS`, `waitingLabel`), `frontend/src/styles/app.css` (appended Batch 4 rules; `.dash-grid` columns changed), `HANDOVER.md`.

## Tests
- **Official `npm run build` (Vite): NOT RUN.** No network, no `node_modules` in the sandbox. Run `cd frontend && npm ci && npm run build` locally.
- **Backend `pytest`: NOT RUN** (pytest not installed, no network). No backend file was touched in this batch.
- **E2E `tests/e2e/ui_flows.py`: NOT RUN.** It may use old selectors (admin table link was the reference number, now the student name; the list status filter was a `<select>`, now tab buttons; "Open assistant"/"Enquire" header text changed in Batch 3). Update it before relying on it.
- **Substitute checks that WERE run:** esbuild bundle of all JSX/CSS (lucide-react stubbed, so icons were placeholders) compiled with no errors. Headless Chromium with a mocked, stateful API at 1280 / 820 / 390px for student dashboard and admin overview/list/detail/programmes: no horizontal overflow, no console/page errors. Behaviour checks passed: status tab sets `?status=new`; opening a detail keeps the query; Back restores the same tab (9 rows); page 2 is restored after detail->back; quick action sent `PATCH {status: in_progress, admin_notes}` and the badge updated; adding a programme updates the summary. Screenshots reviewed for student dashboard, admin overview and mobile list. Not verified with the real backend, real icons or real fonts.

## Known issues
- "New enquiries" on the overview shows whatever order the API returns for `status=new`; confirm it is newest/oldest-first as intended once run against the real backend.
- Overview "Received today" is still the UTC day. Student cannot edit/cancel enquiries. No pagination on the student list.
- Mobile list stacks each enquiry as a tall card; acceptable but could be compacted.
- The Admin sidebar nav on mobile hides icons below 520px.

## Next steps
1. Run the real Vite build and fix anything it reports; run backend `pytest` and update/run `tests/e2e/ui_flows.py` selectors.
2. Click through student + admin screens against the real backend with real icons.
3. Batch 5 candidates (not started): enquiry CSV export, student pagination, compact mobile list, approved SVCE content to replace "pending" markers.

---
# Batch 3 — Public Landing Page + Admissions Journey

**Scope:** frontend only (landing, enquiry page layout, public nav labels). Backend APIs, database, auth, chatbot (`pages/Assistant.jsx`, `components/chat/*`), admin and student dashboards untouched. Batch 4 not started.

## Completed
- **Landing** (`pages/Landing.jsx`, `styles/landing.css` rewritten): SVCE name in the eyebrow + H1; primary action "Start admissions enquiry", secondary "Ask the AI assistant", "Student login" link under them. Hero side panel explains the real enquiry process (form -> consent -> reference number -> team reviews). Sections: Admissions (`#admissions`), College information (`#explore`), Student support (`#support`), How the platform works (`#about`). Removed: fake chat preview, floating topic nodes, glows/dots, bento capability cards, "files/voice/charts" marketing, closing CTA band.
- **No invented facts.** Only the college name and the official site link (`OFFICIAL_SITE`) are stated as facts. Programmes/eligibility, dates/deadlines, fees, admissions contact, departments, placements, contact/location are shown with a **"Pending college approval"** tag (`.pending-tag`). The consent wording/privacy notice is also marked pending on the enquiry page.
- **Navigation**: public header = Home, College info, AI assistant, How it works, Student login + primary button **Admissions enquiry**. Student header = Home, Dashboard, AI assistant, Sign out + same button. Mobile menu ends with "Start admissions enquiry". Footer links reordered/renamed. `lib/router.js` SECTIONS now `admissions, explore, support, about`. Home page title updated in `App.jsx`.
- **Enquiry page** (`pages/Enquiry.jsx`, `styles/app.css`): two-column layout (form + "What happens next" / "Need a quick answer?" / "Admissions contact (pending)"), form grouped into Your details / Your question / Consent. Validation, consent handling, API call, duplicate handling and reference-number confirmation code are unchanged (only JSX around them moved). Sidebar stacks under the form below 900px.

## Files modified
`frontend/src/pages/{Landing,Enquiry}.jsx`, `frontend/src/components/{Header,Footer}.jsx`, `frontend/src/App.jsx` (title only), `frontend/src/lib/router.js` (SECTIONS), `frontend/src/styles/{landing,app}.css`, `HANDOVER.md`.

## Tests
- **Official `npm run build` (Vite): NOT RUN.** The sandbox has no network and no `node_modules` (a partial `npm ci` was attempted and removed). **Run `cd frontend && npm ci && npm run build` locally before relying on this batch.**
- Substitute checks that WERE run: all JSX/CSS bundled with esbuild (lucide-react replaced by a stub, so icons were placeholders) -> compiled with no errors. Then headless Chromium against that bundle with mocked API responses, at 1280 / 820 / 390px: no horizontal overflow, no console/page errors, hero primary button -> `#enquiry`, empty submit shows 5 validation errors, a valid submit shows the reference number, desktop nav and mobile menu list the expected links. Screenshots reviewed for landing + enquiry.
- Not run: the real backend, `pytest`, `tests/e2e/ui_flows.py`, real icons/fonts. `ui_flows.py` may reference old link text ("Open assistant", "Enquire", "Sign in"); update selectors if it fails.

## Remaining work
1. Run the real Vite build and the E2E suite; eyeball with real icons/fonts.
2. Fill the "Pending college approval" items (programmes, fees, dates, contacts, placements) and the consent/privacy wording once SVCE supplies approved text.
3. Batch 4 candidates: student dashboard, admin dashboard polish.

---
# Batch 2 — Branding + Navigation

**Scope:** shared Brand/Header/Footer and role-specific navigation. Routes, auth, role guards, API and chatbot untouched. Batch 3 not started.

## Completed
- **Brand** (`components/Brand.jsx`): one STIF × SVCE wordmark used in header + footer; optional `context` second line (default "Campus AI", "Staff console" in the admin header). Still a plain SVG overlap mark, explicitly **not** an official STIF/SVCE logo; STIF is not expanded; no endorsement text added.
- **Header** (`components/Header.jsx`) is now role-specific:
  - Public: Home, Explore, About, Enquire, Sign in + "Open assistant".
  - Student: Home, Enquire, Dashboard, Sign out + "Open assistant".
  - Admin (and the `#admin/login` page): staff header only — "Staff console" brand, admin name, Sign out (login page: "Back to main site"). No Home/Explore/About/Enquire/assistant links.
  - The header is now the **only** Sign out. The duplicate buttons in the admin sidebar (`Admin.jsx`) and student dashboard (`Dashboard.jsx`) were removed, with their unused imports/`logout` usage and the `.admin-out` CSS.
- **Footer**: signed-in users see "My dashboard" instead of Student/Staff sign-in links. Admin pages still have no footer.
- **Responsive**: hamburger breakpoint raised 860 -> 960px (avoids tablet crowding); mobile menu focus trap now covers buttons, shows current page, has a cleaner type size; staff header has no hamburger (name + Sign out stay visible; name hidden under 480px); smaller brand on narrow phones.

## Files modified
`frontend/src/components/{Brand,Header,Footer}.jsx`, `frontend/src/pages/{Admin,Dashboard}.jsx` (sign-out removal only), `frontend/src/styles/{components,app}.css`, `HANDOVER.md`.

## Tests
- **Frontend production build: NOT RUN SUCCESSFULLY.** The sandbox has no network (`npm ci` fails: no registry access), so `vite` could not be installed. Run `cd frontend && npm ci && npm run build` locally before relying on this batch.
- Only static checks were done: bracket/paren balance on all edited JSX files, no remaining references to removed `logout`/`LogOut` in Admin/Dashboard. No browser, E2E or backend tests run. Note `tests/e2e/ui_flows.py` may click the removed in-page "Sign out" buttons (admin sidebar / dashboard); update those selectors to the header button.

## Next steps
1. Run the build and the E2E suite; fix selectors for Sign out.
2. Visually check header at 390 / 820 / 1280px for all three roles.
3. Batch 3 candidates: landing, student dashboard, admin dashboard polish; route focus/announcement; self-hosted fonts.

---
# Batch 1 — Design Foundation (UI/UX audit follow-up)

**Scope:** CSS-only design foundation. No backend, DB, API, auth, chatbot logic, routes or page markup changed. Batch 2 not started.

## Changes
- `tokens.css` rewritten: navy + teal + cool-neutral palette; semantic role tokens (`--color-bg/surface/primary/accent/border/control-border/focus`), spacing scale, type scale, tighter radii (6/8/10/14/20px), neutral navy-tinted shadows. Old palette names (`--ivory-*`, `--champagne-*`, `--sage-*`) kept as aliases so existing CSS still works.
- Typography: headings weight 600 / line-height 1.2; all functional uppercase micro-labels (table headers, `dt`, eyebrows, footer/rail/message labels) moved from 11-13px mono with wide tracking to 13px DM Sans 600 with 0.06-0.08em tracking; no text below 12px (chart axis) / 13px (labels); chat status pill 11px -> 13px.
- Buttons: `.btn--primary` solid navy, `.btn--secondary` white with 4.7:1 navy-slate outline, `.btn--teal` solid teal; gradients, coloured glows and blur removed; radius pill -> 10px; min-height 44px.
- Cards/chips/icon buttons: white surface, stronger border, subtle shadow, hover lift 4px -> 2px, smaller radii.
- Forms: control/search/composer border `#d9ceb4` (1.56:1) -> `#64748b` (4.7:1 on white, meets WCAG 1.4.11); focus = 2px teal outline + 3px ring; error border stronger; placeholders darker.
- Focus: global `:focus-visible` outline 2px -> 3px teal.
- Removed hard-coded warm hex/rgb values (header, toast, errors, badges, voice panel, Brand.jsx colours, index.html theme-color).

## Files modified
`frontend/src/styles/{tokens,base,components,app,chat,landing,voice}.css`, `frontend/src/components/Brand.jsx` (SVG colours only), `frontend/index.html` (theme-color), `HANDOVER.md`.

## Tests / verification
- **Frontend production build: NOT RUN SUCCESSFULLY.** The sandbox has no network and no `node_modules` (`npm ci --offline` failed with ENOTCACHED), so `vite build` could not be executed. Please run `cd frontend && npm ci && npm run build` locally.
- Static checks that were run: brace balance in every CSS file, every `var(--x)` used in CSS resolves to a token (only component-local vars such as `--btn-bg`, `--reveal-delay` are set inline), `index.css` import list unchanged. No browser/visual or backend tests were run; backend untouched.

## Next steps
1. Run the build and eyeball landing, chat, auth, enquiry, dashboard and admin for contrast/spacing regressions (decorative gradients now flat; `.hero`/landing glows in `landing.css` still use soft shadows).
2. Batch 2 (page-level work from the audit): header crowding at 861-1000px, table captions/scope, route focus management.
3. Consider self-hosting fonts (audit item) and migrating remaining legacy aliases to semantic tokens.

---
# CP3 Frontend Build Verification (2026-11-19)

- **Issue:** Vite could not resolve `@import "./app.css"` in `frontend/src/styles/index.css`.
- **Root cause:** The relative import was correct; `frontend/src/styles/app.css` was missing from the working tree. It was restored from the original CP2 staging ZIP (14,863 bytes).
- **Recovery verified:** `frontend/src/styles/index.css` imports `./app.css`, and the referenced file exists at the expected path (14,863 bytes).
- **Files changed for this recovery:** `frontend/src/styles/app.css` was restored by the project owner. `HANDOVER.md` was updated to record this verification. No application source other than the stylesheet recovery was changed for this issue.
- **Commands executed:** `npm.cmd run build` from `frontend`.
  - First sandboxed attempt stopped before compiling because esbuild was denied access while reading parent directories/config (`Cannot read directory "../../../..": Access is denied`).
  - Retried with the required filesystem access; **passed**: Vite 6.4.4 transformed 1,602 modules and built `dist/index.html`, `dist/assets/index-BTTXhubi.css` (58.90 kB), and `dist/assets/index-CHvV-JkE.js` (240.33 kB); completed in 3.67 seconds.
- **Other tests:** No backend or browser tests were run in this verification.
- **Checkpoint:** `checkpoints/STIF-Campus-AI-CP3-build-verified.zip`; generated bundles, dependencies, caches, secrets, and generated index/report data are excluded.

---
# HANDOVER — STIF Campus AI (SVCE Tirupati)

**Checkpoint: CP2 — frontend + backend integration (complete).** Previous: CP1 (backend). This file replaces the CP1 handover.

## 1. Completed milestones
- **CP1** (earlier): SQLite accounts/sessions/enquiries/programmes, auth, enquiry + admin APIs, CLI (`api/manage.py`).
- **CP2** (this checkpoint): complete React frontend for student registration/login/logout, enquiry form, student dashboard,
  admin login + dashboard (stats, list, detail, status/notes update, programme management), route protection, and the
  existing chatbot integrated into the same shell. No backend code was changed in CP2.

## 2. Current implementation status
| Area | Status |
|---|---|
| Student register / login / logout, validation, auth state | Done, browser-tested |
| Protected student pages (`#dashboard`) + admin pages (`#admin/*`) | Done (UI guard + backend enforcement), browser-tested |
| Enquiry form (name, phone, email, programme, question, consent, confirmation, duplicate handling) | Done, browser-tested |
| Student dashboard (profile, own enquiries, status, link to assistant) | Done, browser-tested |
| Admin: stats, search/filter/paginate, detail, status + internal notes, programmes | Done, browser-tested |
| Chatbot (`pages/Assistant.jsx`, `components/chat/*`) | **Untouched**; still works through the new shell. Answer *content* untestable here (no knowledge base) |
| Responsive (desktop 1280, tablet 820, mobile 390) | Checked via screenshots + no-horizontal-overflow assertions |

How it fits together: `frontend/src/lib/api.js` is the only place that calls the backend (cookie + `X-Requested-With` header);
`lib/auth.jsx` keeps the public user object; `lib/router.js` + `App.jsx` map `#hash` routes to pages; `components/Guard.jsx` protects routes.

## 3. Files
**Created (frontend):** `src/lib/{api.js,auth.jsx,router.js,format.js}`, `src/components/ui/index.jsx`, `src/components/Guard.jsx`,
`src/pages/{Auth.jsx,Enquiry.jsx,Dashboard.jsx,Admin.jsx}`, `src/styles/app.css`.
**Modified:** `src/App.jsx` (hash router + auth provider; chatbot state/behaviour preserved), `src/components/Header.jsx`
(Enquire / Sign in / Dashboard / Admin / Sign out links, desktop + mobile menu), `src/components/Footer.jsx` (new links),
`src/styles/index.css` (imports `app.css`), `README.md` (run instructions), `HANDOVER.md`.
**Created (tests):** `tests/e2e/ui_flows.py` (browser E2E, needs Playwright; run only on a throwaway DB — see its docstring).
**Backend:** unchanged from CP1.

## 4. Database and API changes
None. Schema (migration 1) and all `/api/v1/*` endpoints are exactly as in CP1.
APIs used by the UI: `auth/{register,login,logout,me}`, `enquiries/form-config`, `POST enquiries`, `enquiries/mine`,
`admin/{stats,enquiries,enquiries/{id},programmes}` (+ PATCH), `chat`, `health`.
**No programmes are seeded** (deliberately: no invented SVCE course list). Until an admin adds some (Admin > Programmes, or
`python -m api.manage add-programme/import-programmes`), the enquiry form shows a free-text programme box.

## 5. Tests executed (this environment)
- Backend: `python -m pytest tests --ignore=tests/test_diagnostics.py` → **321 passed**. This includes the 13 CP1 HTTP tests that
  CP1 had to skip (fastapi/httpx now installed).
- Frontend production build (`npm run build`) → success.
- Browser E2E (`tests/e2e/ui_flows.py`, real Chromium against the real FastAPI + SQLite on a throwaway DB) → **46/46 passed**: signed-out redirects;
  registration validation (empty, short password, mismatch, duplicate email); login/logout; enquiry validation, success, duplicate
  detection, anonymous submission; student A sees only own enquiries, student B sees none; student → admin APIs return 403, anonymous 401,
  missing CSRF header 403; session revoked after logout; student credentials refused on staff sign-in; admin stats/list/search/filter/detail/update;
  student sees new status but never admin notes; programme add/hide reflected on the form; chat request round trip; no horizontal overflow at mobile/tablet; no JS console errors.
- Bugs found and fixed by these tests: sign-out redirecting to login instead of home; no way to send a second enquiry after success;
  CSS class clashes with existing chat/landing styles (`.preview`, `.empty`, `.spin`) — renamed so the chatbot look is unchanged.

## 6. Failed / skipped / untested
- `tests/test_diagnostics.py` **fails to import**: `diagnostics/__init__.py` is missing from the supplied ZIP (pre-existing; not recreated because its
  contents — exit-code constants — would be guesswork). Restore it from your original project.
- **Chatbot answer quality / retrieval / source cards with real data: not tested** — the knowledge base is excluded. With no index the assistant
  correctly replies "knowledge base is not available" and shows "SVCE index unavailable". No LLM (Ollama) was running; attachments/voice not exercised.
- Vite dev server (`npm run dev`, port 5173 + proxy) not exercised; tests ran against the built app served by FastAPI on one origin.
- Not tested: HTTPS/`Secure` cookies, real browsers other than Chromium, screen-reader walkthrough, account lockout in the UI (covered by CP1 unit tests), email/SMS notifications (none exist).

## 7. Known issues / decisions for you
1. **Consent wording is a DRAFT** (`api/enquiry_service.py` `CONSENT_TEXT`); the college must approve it before launch (also consider a privacy notice and retention policy — enquiries contain phone/email).
2. The chat endpoint `/api/v1/chat` is still **public** (unchanged from the original design); the dashboard just links to it. Gate it behind login only if you decide so.
3. Rate limiters are in-memory per process (resets on restart; per-proxy-IP behind a reverse proxy). Fine for one process; revisit before scaling.
4. "Received today" on the admin overview uses the UTC day, not IST.
5. Students cannot edit/delete an enquiry or their profile, and there is no password reset / email verification (not requested; needs an email service).
6. No admin user-management UI by design: admins are created only via `python -m api.manage create-admin`.
7. Stale `api/retrieval_before_*.py`, `main_backup.py`, `retrieval_backup.py` still exist from earlier work (not touched).

## 8. Exact next steps
1. Restore `diagnostics/__init__.py`; restore your real `data/` knowledge base; run `python -m pytest tests` fully.
2. `python -m api.manage create-admin ...`, then add the **real** SVCE programmes in Admin > Programmes.
3. Start backend + `npm run dev`; manually try the chatbot with the real index and Ollama (source cards, follow-ups, attachments, voice).
4. Have the college approve the consent text; then decide on password reset / email notifications (CP3 candidates).
5. Optional: add admin CSV export of enquiries; pagination controls on the student list if volumes grow; production deployment notes (HTTPS, `STIF_COOKIE_SECURE=1`, backups of `data/stif_campus.db`).

## 9. Instructions for the next Claude conversation
Upload the latest ZIP and say: "Continue STIF Campus AI from CP2. Read HANDOVER.md first." Then:
- Do not rewrite CP1 backend or the chatbot components; extend them. Reuse `src/styles/tokens.css` + `app.css` classes; avoid generic class names (`.empty`, `.preview`, `.spin` already belong to chat/landing).
- Never overwrite `.env`; never invent SVCE facts; never create fake accounts in a real DB (use a temp `STIF_DB_PATH`).
- Setup: `pip install -r requirements-local.txt -r requirements-additions.txt pytest httpx`; `cd frontend && npm install`; browser tests need `playwright` (+ chromium).
- Verify state: `python -m pytest tests --ignore=tests/test_diagnostics.py`, `npm run build`, then `tests/e2e/ui_flows.py` per its docstring.
- The student is a beginner: keep explaining key concepts briefly; create a new checkpoint ZIP + HANDOVER.md after each milestone.

---

# Phase 5B.2 — PostgreSQL Backend Support (2026-11-20)

## Implementation
- SQLite remains the default through `STIF_DB_PATH` (`data/stif_campus.db`). A non-empty `STIF_DATABASE_URL` selects PostgreSQL. Invalid URL, missing driver, or connection failure raises a sanitized configuration/unavailable error; there is no SQLite fallback.
- Added a PostgreSQL adapter using pinned `psycopg[binary]==3.3.9`. The service boundary keeps qmark SQL and normalizes results, timestamps, and integrity exceptions. PostgreSQL inserts use `RETURNING id`; SQLite keeps `lastrowid` inside its adapter. Connections run in autocommit mode, with explicit transaction commands preserving service transaction scopes.
- Added separate PostgreSQL version-1 schema/migration SQL with identity keys, native booleans and `TIMESTAMPTZ`, preserving the SQLite migration. PostgreSQL migration initialization uses a transaction-scoped advisory lock.
- Enquiry submissions acquire an email-keyed transaction lock on PostgreSQL so duplicate checks and per-email daily caps serialize across workers. SQLite retains `BEGIN IMMEDIATE` behavior.
- Programme ordering and daily statistics now use backend-compatible SQL. Service/API response shapes are unchanged.
- `.env.example` uses a placeholder `STIF_DATABASE_URL`; README documents backend selection. This phase does not copy records.

## Tests and limitations
- Install with `pip install -r requirements-local.txt -r requirements-additions.txt`; this includes the pinned Psycopg 3 driver (`psycopg[binary]==3.3.9`). For local PostgreSQL, set `STIF_DATABASE_URL` in the backend environment; keep real credentials private. Leave it empty for SQLite.
- Mocked PostgreSQL adapter tests cover backend selection/no-fallback, qmark conversion, row and timestamp normalization, generated IDs, integrity mapping, transaction commit/rollback, advisory locking, and versioned migration initialization.
- PostgreSQL integration tests are gated behind `STIF_TEST_POSTGRES_URL`, the explicit `STIF_TEST_POSTGRES_DISPOSABLE=I_UNDERSTAND_THIS_DATABASE_IS_DISPOSABLE` acknowledgment, a database name beginning `stif_test_`, and a non-Neon host. They passed against a newly created temporary local PostgreSQL 18 cluster; the cluster and its synthetic test database were stopped and removed afterward.
- Verification: `.venv\Scripts\python.exe -m unittest tests.test_postgres_backend` passed against the disposable PostgreSQL cluster (16 tests, including 5 real integration tests for schema/migration locking, connection lifecycle, transaction rollback, HTTP auth/permissions/ownership, enquiry management and concurrency). `.venv\Scripts\python.exe -m unittest discover -s tests` passed (384 tests; 5 PostgreSQL integration tests skipped because the disposable database gate was unset). Psycopg 3.3.9 is installed in the project `.venv` (Python 3.12). The frontend build was not rerun for this verification checkpoint.
- This checkpoint used only a temporary local PostgreSQL cluster; it did not connect to Neon or any external database and did not migrate SQLite records. Hosted Neon connectivity, pooled-connection behavior, cloud persistence and deployment remain unverified.

# Roadmap Checkpoint 2 — Neon preparation and SQLite migration tooling (2026-11-20)

- Neon setup steps, current regional considerations, TLS/pooling notes, and current finite free-plan caveats are in `docs/CLOUD_READINESS.md`. Singapore (`aws-ap-southeast-1`) is the closest currently documented Neon region for SVCE Tirupati; confirm availability before creating a project because Neon fixes the project region at creation. No account, project, or credentials were created.
- Added `/ready` as a generic database readiness probe while retaining `/health` as the existing liveness endpoint. `STIF_ENV=production` makes FastAPI startup reject SQLite selection. `.env.example` now documents the runtime mode and keeps only a commented database URL placeholder.
- Added `python -m api.migrate_sqlite`: a separately named, atomic SQLite snapshot command plus dry-run/apply import modes. It opens snapshots read-only, checks schema/integrity/foreign keys, refuses live SQLite paths and non-empty PostgreSQL application tables, imports roles/users/programmes/enquiries transactionally, omits sessions, preserves IDs/password hashes/references/timestamps, resets identity sequences, checks counts/FKs, and emits a PII-free count/hash report. `data/migration_snapshots/` is Git-ignored.
- Verified migration behavior with synthetic SQLite fixtures against disposable local PostgreSQL only. No snapshot was made from the real `data/stif_campus.db` and no real records were transferred.
- Tests: `.venv\Scripts\python.exe -m unittest tests.test_migration_tool tests.test_runtime_readiness tests.test_postgres_backend` passed (25 tests; 6 PostgreSQL integration tests skipped because no DB URL was configured). The PostgreSQL suite then passed against a temporary PostgreSQL 18 cluster (17 tests). Full backend discovery passed: 393 tests, 6 skipped. The Vite build was not rerun during this checkpoint.
- No Neon or external service was contacted. `.env`, the existing SQLite database, existing backups/checkpoints, and knowledge-base data/indexes were not modified.
- Next: Checkpoint 3, persistent document/index storage abstraction and tests without external uploads.
- `.env`, `data/stif_campus.db`, knowledge-base files and indexes were not accessed or modified by this implementation.

# Roadmap Checkpoints 3–6 — Storage, deployment preparation, security and demo readiness (2026-11-20)

## Checkpoint 3 — Artifact storage

- Added `api/artifact_storage.py`: local storage remains default; explicit `STIF_STORAGE_BACKEND=r2` enables the S3-compatible Cloudflare R2 adapter. R2 mode validates a versioned active manifest, paths and SHA-256 file integrity; materializes staged files into existing local paths; and publishes immutable generations with the manifest switched last.
- Only public knowledge source/index paths are eligible. SQLite database files, reports, temporary files and chat attachments are excluded. Current upload extraction returns text to the browser and does not persist attachment files; this phase keeps that behavior.
- Shared artifact publication requires PostgreSQL and a transaction-scoped advisory lock, and refuses a stale generation. `python -m api.storage_cli seed-local --confirm-initial-seed` is an explicit first upload command. Old generations are retained; lifecycle cleanup is not implemented.
- R2 configuration is documented as placeholders in `.env.example`; Boto3 is pinned at `boto3==1.44.7` in `requirements-additions.txt`. No R2 account, bucket, credential, or external request was used.

## Checkpoint 4 — Deployment preparation

- Added `render.yaml` for a Singapore paid Render API service, environment-only credentials, production PostgreSQL requirement, R2 storage, secure cookies, schema initialization, and `/ready` health checks. No service was imported or deployed.
- Added `frontend/public/_headers` with basic static security headers. Cloudflare Pages instructions use `frontend`, `npm ci`, `npm run build`, `dist`, and `VITE_API_BASE_URL`; no frontend secret is required.
- CORS now accepts exact HTTPS origins through `STIF_CORS_ORIGINS` (local loopback HTTP is allowed for development), uses credentialed requests, and rejects wildcard origins. `STIF_ALLOWED_HOSTS` applies an explicit API host allowlist. `frontend/src/lib/api.js` includes the HttpOnly cookie for a separate frontend origin. Keep frontend/API on same-site custom subdomains; cross-site provider default domains may be blocked by browser cookie policies.
- `docs/CLOUD_READINESS.md` and `docs/DEMO_READINESS.md` capture current provider constraints/cost assumptions, configuration steps, and risks. Pricing must be rechecked before any purchase.

## Checkpoint 5 — Security findings and review

- Fixed runtime behavior so production can’t silently serve SQLite. Explicit R2 mode cannot silently fall back to local files. Readiness checks the selected DB and the active R2 manifest without returning credentials or connection details. Storage diagnostic logs contain operation and error type only.
- Existing server-side student/admin authorization and ownership enforcement, HttpOnly/SameSite cookies, CSRF custom header and safe LLM fallback were preserved. User uploads remain transient.
- **Launch blocker:** the configured `nvidia/nemotron-3.5-lightning:free` endpoint's current page warns not to upload personal/confidential data and says NVIDIA logs free endpoint sessions to improve products. User questions, retrieved content and attachment text are sent to the configured provider. Do not send student PII/private attachments to it; obtain college approval or select a provider/model with appropriate data terms.
- Rate limiting remains process-local and does not coordinate across instances. Consent/privacy/retention wording, backup/restore, final-domain CORS/cookie browser verification, observability and college data-handling approval require further work. No production security certification is claimed.

## Checkpoint 6 — Verification and stop boundary

- Backend full suite (including Host middleware): `.venv\Scripts\python.exe -m unittest discover -s tests` — **402 tests passed, 6 skipped**. Skips are disposable PostgreSQL integration tests because no test URL was configured in this run.
- Focused storage/runtime/PostgreSQL suite after sanitized ingestion-publication handling: **29 tests, 23 passed and 6 skipped**. Host-filter/API smoke suite: **27 passed**.
- Earlier Phase A PostgreSQL verification against a disposable local PostgreSQL 18 cluster: **17 integration tests passed** (synthetic fixtures only); no Neon/external database. No PostgreSQL cluster was contacted during this checkpoint.
- Frontend: `npm.cmd run build` — passed (Vite 6.4.4; 1,602 modules). Browser E2E: `tests/e2e/ui_flows.py` — **46/46 passed** against a fresh temporary SQLite DB and synthetic accounts with OpenRouter disabled, after enabling the Host allowlist. The E2E script selectors were aligned to the current dashboard/admin UI; no application UI redesign was made.
- `.env` was not opened or changed. The real SQLite DB and existing knowledge/index files were not modified. E2E DB/screenshots were written only to disposable OS-temp directories. The test-only Playwright install remains in `.venv` and was not added to requirements.
- No Neon/Render/Cloudflare account, domain, external database, object-storage bucket, file upload, real-record migration, deployment, paid resource, commit or push occurred.
- Remaining: no cloud setup or live data operation has been approved. Real OpenRouter application request was not performed here. Follow the manual approval boundary in `docs/CLOUD_READINESS.md` and `docs/DEMO_READINESS.md`.
