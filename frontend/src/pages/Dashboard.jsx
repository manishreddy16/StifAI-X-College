import React, { useCallback, useEffect, useState } from "react";
import { ArrowRight, Check, Inbox, MessageCircle, RefreshCw, UserRound } from "lucide-react";
import { api } from "../lib/api.js";
import { useAuth } from "../lib/auth.jsx";
import { formatDate, STATUS_LABELS, TRACK_STEPS } from "../lib/format.js";
import { Alert, EmptyState, PageHead, Spinner, StatusBadge } from "../components/ui/index.jsx";

/** Plain-language "what happens next" for each status. No response times are promised. */
const NEXT = {
  new: "Nothing to do right now. The admissions team has your enquiry and will contact you using the email and phone number you gave.",
  in_progress: "The admissions team is working on your enquiry. Please keep your phone and email available.",
  responded: "A reply has been sent. Check your email and phone. If you have another question, send a new enquiry or ask the assistant.",
  closed: "This enquiry is closed. If you still need help, send a new enquiry.",
};

function Tracker({ status }) {
  const at = TRACK_STEPS.indexOf(status);
  return (
    <ol className="tracker" aria-label={`Progress: step ${at + 1} of ${TRACK_STEPS.length}, ${STATUS_LABELS[status]}`}>
      {TRACK_STEPS.map((s, i) => (
        <li key={s} className={i < at ? "is-done" : i === at ? "is-current" : ""} aria-current={i === at ? "step" : undefined}>
          <span className="tracker-dot" aria-hidden="true">{i < at ? <Check size={14} /> : i + 1}</span>
          <span className="tracker-label">{STATUS_LABELS[s]}</span>
        </li>
      ))}
    </ol>
  );
}

/** The server decides which enquiries are "mine" from the session cookie — the browser cannot ask for someone else's. */
export default function Dashboard({ navigate }) {
  const { user, expire } = useAuth();
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setError(""); setItems(null);
    api("/api/v1/enquiries/mine")
      .then((d) => setItems(d.items))
      .catch((e) => { if (e.status === 401) expire(); else setError(e.message); });
  }, [expire]);
  useEffect(load, [load]);

  const go = (t) => (e) => { e.preventDefault(); navigate(t); };
  const waiting = items ? items.filter((e) => e.status === "new" || e.status === "in_progress").length : 0;
  const replied = items ? items.filter((e) => e.status === "responded").length : 0;

  return (
    <main id="main" tabIndex={-1} className="container section">
      <PageHead eyebrow="Student dashboard" title={`Hello, ${user.full_name.split(" ")[0]}`}
        actions={<a className="btn btn--primary btn--sm" href="#enquiry" onClick={go("enquiry")}>New enquiry <ArrowRight size={16} className="btn-arrow" /></a>}>
        Track your admissions enquiries and see what happens next.
      </PageHead>

      <div className="dash-grid">
        <section aria-labelledby="enq-h" className="dash-main">
          <div className="section-bar">
            <h2 id="enq-h" className="h-md">My enquiries</h2>
            <button type="button" className="icon-btn" onClick={load} aria-label="Refresh enquiries" data-tip="Refresh" data-tip-pos="bottom"><RefreshCw size={17} /></button>
          </div>

          {error && <Alert kind="error" title="Could not load your enquiries">{error}</Alert>}
          {!items && !error && <Spinner label="Loading your enquiries…" />}

          {items && items.length > 0 && (
            <>
              <p className="sd-summary" role="status">
                <b>{items.length}</b> enquir{items.length === 1 ? "y" : "ies"}
                {waiting > 0 && <> · <b>{waiting}</b> being handled</>}
                {replied > 0 && <> · <b>{replied}</b> replied</>}
              </p>
              <ul className="enq-list">
                {items.map((e) => (
                  <li key={e.reference} className={`card sd-card sd-card--${e.status}`}>
                    <div className="enq-top">
                      <span className="mono ref">{e.reference}</span>
                      <StatusBadge status={e.status} />
                    </div>
                    <h3 className="enq-prog">{e.programme}</h3>
                    <p className="enq-msg">{e.message}</p>
                    <Tracker status={e.status} />
                    <p className="sd-next"><b>Next:</b> {NEXT[e.status]}</p>
                    <p className="muted small">Sent {formatDate(e.created_at)}</p>
                    {(e.status === "responded" || e.status === "closed") && (
                      <div className="btn-row btn-row--tight">
                        <a className="btn btn--secondary btn--sm" href="#enquiry" onClick={go("enquiry")}>Send a new enquiry</a>
                        <a className="btn btn--quiet btn--sm" href="#assistant" onClick={go("assistant")}>Ask the assistant</a>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </>
          )}

          {items && items.length === 0 && (
            <div className="card pad">
              <EmptyState icon={Inbox} title="No enquiries yet"
                action={<a className="btn btn--primary btn--sm" href="#enquiry" onClick={go("enquiry")}>Send your first enquiry <ArrowRight size={16} className="btn-arrow" /></a>}>
                Send an admissions enquiry while signed in and it will appear here with its status, so you can follow it from “New” to “Responded”. Enquiries sent without signing in are not listed here.
              </EmptyState>
            </div>
          )}
        </section>

        <aside className="dash-side" aria-label="Account and help">
          <section className="card pad card--ask" aria-labelledby="ask-h">
            <h2 id="ask-h" className="h-sm"><MessageCircle size={18} className="inline-icon" /> Quick answers</h2>
            <p className="muted small">Ask the campus assistant about the college. Answers show sources when available.</p>
            <a className="btn btn--secondary btn--sm" href="#assistant" onClick={go("assistant")}>Open assistant <ArrowRight size={16} className="btn-arrow" /></a>
          </section>
          <section className="card pad sd-profile" aria-labelledby="profile-h">
            <h2 id="profile-h" className="h-sm"><UserRound size={18} className="inline-icon" /> My account</h2>
            <dl className="kv kv--stack">
              <div><dt>Name</dt><dd>{user.full_name}</dd></div>
              <div><dt>Email</dt><dd className="break">{user.email}</dd></div>
            </dl>
          </section>
        </aside>
      </div>
    </main>
  );
}
