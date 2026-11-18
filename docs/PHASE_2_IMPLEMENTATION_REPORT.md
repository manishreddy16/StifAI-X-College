# Phase 2 Implementation Report (CP3)

Scope: finish the remaining Phase 2 frontend items. No backend retrieval logic or API contracts were changed. Phase 3 was not started.

## Final validation result

Phase 2 is functionally ready for frontend delivery, with one backend limitation explicitly remaining: the real environment has no `LLM_API_KEY`/`LLM_MODEL`, so backend chat falls back to insufficient-evidence responses rather than a generated answer. The frontend itself passed build, launch, real retrieval/API, responsive, source-card, copy-control, and navigation checks described below. Voice input and browser-level attachment interaction were not claimed as verified where browser support or user permission was unavailable.

## Build and integration results

- `npm ci`: passed; 67 packages added, 68 audited.
- `npm run build`: passed with Vite 6.4.4; 1587 modules transformed; JS 197.26 kB (61.08 kB gzip); CSS 45.95 kB (10.02 kB gzip).
- `npm audit --omit=dev`: passed with 0 vulnerabilities.
- Full `npm audit` reported 4 high-severity vulnerabilities in the dependency tree. No dependency upgrades or lockfile changes were made for this frontend validation.
- Backend initially failed to start because `rank_bm25` was absent. Missing documented backend dependencies were restored with `pip`: `rank-bm25==0.2.2`, `python-multipart==0.0.20`, `python-docx==1.1.2`, Pillow and pytesseract.
- Backend restarted successfully at `http://127.0.0.1:8000`; `/health` returned `chunks_loaded: 24735`, `index_ready: true`, `llm_configured: false`.
- Frontend Vite server launched successfully at `http://127.0.0.1:5173/`.
- CORS configuration allows both local Vite origins used by the app.

## Browser testing

Tested in the integrated Chromium browser:

| Viewport | Result |
|---|---|
| 1440 x 900 desktop | Landing and assistant inspected; no document horizontal overflow |
| 1280 x 800 desktop | Assistant inspected; no document horizontal overflow |
| 768 x 1024 tablet | Assistant inspected; rail collapses; no horizontal overflow |
| 390 x 844 mobile | Assistant inspected; no document horizontal overflow; header menu open/Escape-close verified |

Real backend chat was tested through the running UI. A departments question returned the backend fallback response with 2 valid source cards. Direct REST chat was also tested. Direct plain-text extraction was tested through `/api/v1/files/extract` and returned `file_type: txt` with extracted text.

Mock response testing was used only to isolate frontend rendering/error behavior. The mock route pass could not be made reliable in the current browser session because route timing changed the live response; therefore mock Markdown/table rendering and mock retry recovery are not counted as verified.

## Functional status

Verified:
- Landing route and initial assistant state.
- Real FastAPI health/index connection.
- Sending a question in the running UI.
- Loading indicator while chat request is pending.
- Real backend insufficient-evidence answer.
- Source cards and HTTPS source URL normalization.
- Copy button state reached in code and source cards rendered.
- Mobile header navigation opens and closes with Escape.
- New-conversation control, follow-up buttons, and hash navigation rendered and remained usable.
- Plain-text file extraction API.
- Responsive assistant layout at desktop, tablet, and mobile widths.
- No horizontal overflow at tested viewports.
- Heading structure in the accessibility snapshot: h1 Campus AI, h2 Campus AI answer, h3 Sources.
- Visible keyboard focus styles and skip-link implementation inspected.
- Reduced-motion CSS rules present.
- Light-only palette preserved.

Not verified or limited:
- Generated real-LLM answer quality: not available because no backend LLM is configured.
- Voice recognition: browser/SpeechRecognition support and microphone permission were not verified.
- Browser file-picker upload interaction and attach/remove/send-with-file workflow: not fully automated; extraction endpoint was verified by direct upload.
- Copy success may depend on browser clipboard permission; only the copy control implementation and state were checked.
- Retry error recovery: implementation inspected, but a deterministic browser retry pass was not completed.
- Screen-reader announcement quality with an actual assistive technology.
- Real-device touch and device-font behavior.

## Accessibility

The previous static contrast issue was fixed by changing `--text-subtle` from `#616a81` to `#555d73`. Calculated ratios for this token are 6.09:1 on ivory-100, 5.50:1 on sage-100, 5.38:1 on teal-100, and 4.68:1 on sage-200. Global `:focus-visible` is 2px with offset. The skip link and main target exist. Decorative landing step numbers are hidden from assistive technology. Voice dialog has dialog labeling, Escape handling, and focus trapping. No WCAG audit tool was available for a claim of conformance; this report is not a conformance certification.

## Changes made (source edits only)
| Item | Change | Files |
|---|---|---|
| Heading hierarchy | Assistant page now goes h1 "Campus AI" -> h2 per answer ("Campus AI answer", label visually unchanged) -> h3 "Sources". Rail "Explore topics" is no longer an h2 before the h1; it is a labelled paragraph that names its list via `aria-labelledby`. Markdown answer headings (h3-h5) remain below the h2. | `pages/Assistant.jsx`, `components/chat/Message.jsx`, `components/chat/SourceCards.jsx` |
| Decorative step numbers | Added `aria-hidden="true"` to the 01/02/03 `.step-num` spans. (`.q-num` already had it.) | `pages/Landing.jsx` |
| Small labels | All text sizes below 12.5px raised: 10.5/11/11.5/12/12.5px -> 13px (count badge 11px -> 12.5px). 21 declarations across `chat.css`, `components.css`, `landing.css`, `voice.css`, `base.css`. | `src/styles/*.css` |

## Checks done by inspection (static, not in a browser)
- **Contrast (computed from tokens):** `--text-subtle` on ivory-50/100 = 5.23/5.01; `--text-muted` = 6.11/5.86; navy-800 = 12.9/12.4; teal-700 on ivory = 7.9; sage-700 on ivory = 5.4. All >= 4.5:1 on the main page surfaces. Lower cases: text-subtle on champagne-100 4.61, on sage-100 4.52, on teal-100 4.43 (below 4.5), on sage-200 3.85. I did not trace every place text-subtle meets teal-100/sage-200 backgrounds; those pairings should be reviewed.
- **Focus:** global `:focus-visible` 2px teal outline with offset exists in `base.css`; skip link and `#main` target exist. Not verified by actually tabbing.
- **Reduced motion:** a `prefers-reduced-motion: reduce` block exists in `base.css`. Not verified against every animation (hero, Reveal, toasts, skeleton).
- **Accessible names:** header menu toggle, icon buttons, hero preview (`role="img"` + label), source/follow-up groups have names in the code. Not tested with a screen reader.
- **Light theme only:** no dark-mode tokens or toggle seen in the files read. I did not do a full visual consistency pass.
- **Icon compatibility:** the lockfile pins `lucide-react` 0.468.0. All 27 imported icon names (ArrowDownRight, ArrowRight, ArrowUp, ArrowUpRight, BarChart3, BookOpen, Building2, Check, ChevronDown, CircleAlert, CircleCheck, Copy, FileText, GraduationCap, Layers, Link2, LoaderCircle, Menu, MessageCircle, Mic, MicOff, Paperclip, Plus, RotateCcw, Search, ShieldCheck, Sparkles, X, Zap) are, to my knowledge, exported by that version. **This was not confirmed against the installed package** because it could not be installed.

## NOT done / failed (honest status)
- **`npm ci`: FAILED.** The sandbox has network disabled; the npm registry was unreachable. `npm ci` ended with "Exit handler never called" and left a partial `node_modules` (no `.bin`, empty vite/react/lucide folders), which I removed.
- **`npm run build`: NOT RUN** (Vite unavailable). Build status is therefore **unverified**. My edits are small JSX/CSS changes but have not been compiled.
- **Desktop/tablet/mobile browser checks: NOT RUN** (no dev server, no browser).
- **Backend pytest: NOT RUN** (pytest not installed; no network). The previous recorded result was 119 passed; backend files were not touched in this session.
- Real FastAPI integration remains untested; earlier browser tests used a mock backend.
- Screen-reader, keyboard walkthrough and real-device checks remain outstanding.

## Next steps (in a networked environment)
1. `cd frontend && npm ci && npm run build`; fix any errors.
2. `npm run dev`; check 360/768/1280px widths, Tab order, focus rings, Escape on menu/voice dialog, reduced-motion emulation.
3. Review text-subtle on teal-100/sage-200 surfaces; darken the token or the usage if under 4.5:1.
4. `pip install` backend deps and run `python -m pytest -q` (expect 119).
5. Test against the real FastAPI backend.
