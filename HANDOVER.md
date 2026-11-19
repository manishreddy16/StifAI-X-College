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
