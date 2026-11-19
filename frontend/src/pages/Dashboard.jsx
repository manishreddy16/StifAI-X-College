import React, { useCallback, useEffect, useState } from "react";
import { ArrowRight, Inbox, LogOut, MessageCircle, RefreshCw, UserRound } from "lucide-react";
import { api } from "../lib/api.js";
import { useAuth } from "../lib/auth.jsx";
import { formatDate } from "../lib/format.js";
import { Alert, EmptyState, PageHead, Spinner, StatusBadge } from "../components/ui/index.jsx";

const STATUS_HELP = {
  new: "We have received your enquiry.",
  in_progress: "The admissions team is working on it.",
  responded: "A reply has been sent — check your phone or email.",
  closed: "This enquiry has been closed.",
};

/** The server decides which enquiries are "mine" from the session cookie — the browser cannot ask for someone else's. */
export default function Dashboard({ navigate, notify }) {
  const { user, logout, expire } = useAuth();
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
  const onLogout = async () => { navigate("home"); await logout(); notify("You have been signed out."); };

  return (
    <main id="main" tabIndex={-1} className="container section">
      <PageHead eyebrow="Student dashboard" title={`Hello, ${user.full_name.split(" ")[0]}`}
        actions={<a className="btn btn--primary btn--sm" href="#enquiry" onClick={go("enquiry")}>New enquiry <ArrowRight size={16} className="btn-arrow" /></a>}>
        Your profile, your enquiries and quick access to the campus assistant.
      </PageHead>

      <div className="dash-grid">
        <div className="dash-side">
          <section className="card pad" aria-labelledby="profile-h">
            <span className="icon-tile icon-tile--champagne"><UserRound size={22} /></span>
            <h2 id="profile-h" className="h-sm">My profile</h2>
            <dl className="kv kv--stack">
              <div><dt>Name</dt><dd>{user.full_name}</dd></div>
              <div><dt>Email</dt><dd className="break">{user.email}</dd></div>
              <div><dt>Account type</dt><dd>Student</dd></div>
            </dl>
            <button type="button" className="btn btn--quiet btn--sm" onClick={onLogout}><LogOut size={16} /> Sign out</button>
          </section>

          <section className="card pad card--ask" aria-labelledby="ask-h">
            <span className="icon-tile icon-tile--teal"><MessageCircle size={22} /></span>
            <h2 id="ask-h" className="h-sm">Campus assistant</h2>
            <p className="muted">Ask about admissions, departments, placements or contacts. Answers show their sources.</p>
            <a className="btn btn--teal btn--sm" href="#assistant" onClick={go("assistant")}>Open assistant <ArrowRight size={16} className="btn-arrow" /></a>
          </section>
        </div>

        <section aria-labelledby="enq-h">
          <div className="section-bar">
            <h2 id="enq-h" className="h-md">My enquiries</h2>
            <button type="button" className="icon-btn" onClick={load} aria-label="Refresh enquiries" data-tip="Refresh" data-tip-pos="bottom"><RefreshCw size={17} /></button>
          </div>
          {error && <Alert kind="error" title="Could not load your enquiries">{error}</Alert>}
          {!items && !error && <Spinner label="Loading your enquiries…" />}
          {items && items.length === 0 && (
            <div className="card pad">
              <EmptyState icon={Inbox} title="No enquiries yet"
                action={<a className="btn btn--primary btn--sm" href="#enquiry" onClick={go("enquiry")}>Send your first enquiry</a>}>
                Enquiries you send while signed in will appear here with their status.
              </EmptyState>
            </div>
          )}
          {items && items.length > 0 && (
            <ul className="enq-list">
              {items.map((e) => (
                <li key={e.reference} className="card pad enq-item">
                  <div className="enq-top">
                    <span className="mono ref">{e.reference}</span>
                    <StatusBadge status={e.status} />
                  </div>
                  <p className="enq-prog">{e.programme}</p>
                  <p className="enq-msg">{e.message}</p>
                  <p className="muted small">{STATUS_HELP[e.status]} · Sent {formatDate(e.created_at)}</p>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </main>
  );
}
