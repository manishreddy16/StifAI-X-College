import React, { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, BookOpen, ChevronLeft, ChevronRight, ClipboardList, Inbox, LayoutDashboard, Loader2, Plus, RefreshCw, Search, X } from "lucide-react";
import { api, qs } from "../lib/api.js";
import { useAuth } from "../lib/auth.jsx";
import { formatDate, STATUSES, STATUS_LABELS, waitingLabel } from "../lib/format.js";
import { Alert, EmptyState, Field, PageHead, Spinner, StatusBadge } from "../components/ui/index.jsx";

/** Wrap admin API calls: a 401 means the session ended, so clear the user (the Guard then redirects to sign-in). */
function useAdminApi() {
  const { expire } = useAuth();
  return useCallback(async (path, options) => {
    try { return await api(path, options); }
    catch (e) { if (e.status === 401) expire(); throw e; }
  }, [expire]);
}

const NAV = [
  { to: "admin", label: "Overview", icon: LayoutDashboard },
  { to: "admin/enquiries", label: "Enquiries", icon: ClipboardList },
  { to: "admin/programmes", label: "Programmes", icon: BookOpen },
];

export default function Admin({ route, navigate, notify }) {
  const { user } = useAuth();
  const [section, id] = route.parts;
  const current = section === "enquiries" ? "admin/enquiries" : section === "programmes" ? "admin/programmes" : "admin";
  const go = (t) => (e) => { e.preventDefault(); navigate(t); };

  let body;
  if (!section) body = <Overview navigate={navigate} />;
  else if (section === "enquiries" && id) body = <EnquiryDetail id={id} route={route} navigate={navigate} notify={notify} />;
  else if (section === "enquiries") body = <EnquiryList key={JSON.stringify(route.params)} route={route} navigate={navigate} />;
  else if (section === "programmes") body = <Programmes notify={notify} />;
  else body = <EmptyState icon={Inbox} title="Page not found">That admin page does not exist.</EmptyState>;

  return (
    <main id="main" tabIndex={-1} className="container admin">
      <aside className="admin-nav" aria-label="Admin navigation">
        <div className="admin-who">
          <small>Signed in as</small>
          <b>{user.full_name}</b>
        </div>
        <nav>
          {NAV.map(({ to, label, icon: Icon }) => (
            <a key={to} href={`#${to}`} onClick={go(to)} aria-current={current === to ? "page" : undefined}><Icon size={18} /> {label}</a>
          ))}
        </nav>
      </aside>
      <div className="admin-body">{body}</div>
    </main>
  );
}

/* ------------------------------------------------------------------ Overview */
function Overview({ navigate }) {
  const call = useAdminApi();
  const [stats, setStats] = useState(null);
  const [fresh, setFresh] = useState(null); // newest enquiries still in "new" status
  const [freshError, setFreshError] = useState(false);
  const [error, setError] = useState("");
  const load = useCallback(() => {
    setError(""); setStats(null); setFresh(null); setFreshError(false);
    call("/api/v1/admin/stats").then(setStats).catch((e) => setError(e.message));
    call(`/api/v1/admin/enquiries${qs({ status: "new", page: 1, page_size: 5 })}`).then(setFresh).catch(() => { setFresh({ items: [], total: 0 }); setFreshError(true); });
  }, [call]);
  useEffect(load, [load]);

  const link = (to) => ({ href: `#${to}`, onClick: (e) => { e.preventDefault(); navigate(to); } });
  const max = stats ? Math.max(1, ...stats.daily.map((d) => d.count)) : 1;
  const newCount = stats?.by_status.new ?? 0;
  const tiles = stats && [
    { label: "New", value: newCount, to: "admin/enquiries?status=new", hot: newCount > 0 },
    { label: "In progress", value: stats.by_status.in_progress, to: "admin/enquiries?status=in_progress" },
    { label: "Received today (UTC)", value: stats.today },
    { label: "Last 7 days", value: stats.last_7_days },
    { label: "Total enquiries", value: stats.total, to: "admin/enquiries" },
  ];

  return (
    <>
      <PageHead eyebrow="Administration" title="Enquiry overview"
        actions={<button type="button" className="icon-btn" onClick={load} aria-label="Refresh" data-tip="Refresh" data-tip-pos="bottom"><RefreshCw size={17} /></button>}>
        What needs attention now, and how enquiries are moving.
      </PageHead>
      {error && <Alert kind="error" title="Could not load statistics">{error}</Alert>}
      {!stats && !error && <Spinner label="Loading statistics…" />}
      {stats && (
        <>
          <section className={`card attn ${newCount === 0 ? "attn--clear" : ""}`} aria-labelledby="attn-h">
            <div>
              <h2 id="attn-h">{newCount === 0 ? "No new enquiries waiting" : `${newCount} new enquir${newCount === 1 ? "y" : "ies"} waiting for a first response`}</h2>
              <p>{newCount === 0
                ? `Everything received has been picked up.${stats.by_status.in_progress ? ` ${stats.by_status.in_progress} still in progress.` : ""}`
                : `${stats.by_status.in_progress} more in progress. Open the new ones first and set a status so students can see progress.`}</p>
            </div>
            {newCount > 0 && <a className="btn btn--primary" {...link("admin/enquiries?status=new")}>Review new enquiries <ArrowRight size={18} className="btn-arrow" /></a>}
          </section>

          <div className="stat-grid stat-grid--main">
            {tiles.map((t) => {
              const inner = <><b>{t.value}</b><span>{t.label}</span></>;
              return t.to
                ? <a key={t.label} className={`card stat ${t.hot ? "stat--hot" : ""}`} {...link(t.to)}>{inner}</a>
                : <div key={t.label} className="card stat">{inner}</div>;
            })}
          </div>

          <div className="two-col">
            <section className="card pad" aria-labelledby="fresh-h">
              <h2 id="fresh-h" className="h-sm">New enquiries</h2>
              {!fresh && <Spinner label="Loading…" />}
              {fresh && freshError && <p className="muted" role="alert">Could not load the new enquiries. Use the refresh button above to try again.</p>}
              {fresh && !freshError && fresh.items.length === 0 && <p className="muted">No enquiries are in “New” status.</p>}
              {fresh && fresh.items.length > 0 && (
                <>
                  <ul className="mini-table">
                    {fresh.items.map((e) => (
                      <li key={e.id}>
                        <div><a {...link(`admin/enquiries/${e.id}?status=new`)}>{e.full_name}</a><br /><small>{e.programme} · {e.reference}</small></div>
                        <span className="wait">{waitingLabel(e.created_at)}</span>
                      </li>
                    ))}
                  </ul>
                  {fresh.total > fresh.items.length && <p className="small"><a className="text-link" {...link("admin/enquiries?status=new")}>View all {fresh.total} new</a></p>}
                </>
              )}
            </section>
            <section className="card pad" aria-labelledby="st-h">
              <h2 id="st-h" className="h-sm">By status</h2>
              <ul className="status-rows">
                {STATUSES.map((s) => (
                  <li key={s}><a {...link(`admin/enquiries?status=${s}`)}><StatusBadge status={s} /><b>{stats.by_status[s]}</b></a></li>
                ))}
              </ul>
              <p className="small muted">Student accounts registered: <b>{stats.student_accounts}</b></p>
            </section>
          </div>

          <div className="two-col">
            <section className="card pad" aria-labelledby="pg-h">
              <h2 id="pg-h" className="h-sm">Top programmes</h2>
              {stats.top_programmes.length === 0 ? <p className="muted">No enquiries yet.</p> : (
                <ul className="bar-rows">
                  {stats.top_programmes.map((p) => (
                    <li key={p.programme}><span>{p.programme}</span><div className="bar"><i style={{ width: `${(p.count / stats.top_programmes[0].count) * 100}%` }} /></div><b>{p.count}</b></li>
                  ))}
                </ul>
              )}
            </section>
            <section className="card pad" aria-labelledby="dy-h">
              <h2 id="dy-h" className="h-sm">Enquiries per day (last 14 days)</h2>
              <div className="spark" role="img" aria-label={`Daily enquiries, last 14 days: ${stats.daily.map((d) => d.count).join(", ")}`}>
                {stats.daily.map((d) => (
                  <div key={d.date} className="spark-col" title={`${d.date}: ${d.count}`}>
                    <i style={{ height: `${(d.count / max) * 100}%` }} /><small>{d.date.slice(8)}</small>
                  </div>
                ))}
              </div>
            </section>
          </div>
        </>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ List */
/** Filters live in the URL (#admin/enquiries?status=&q=&page=) so Back, refresh and "return from detail" keep them. */
const listQuery = ({ status, term, page }) => {
  const p = new URLSearchParams();
  if (status) p.set("status", status);
  if (term) p.set("q", term);
  if (page > 1) p.set("page", String(page));
  const s = p.toString();
  return s ? `?${s}` : "";
};

function EnquiryList({ route, navigate }) {
  const call = useAdminApi();
  const first = useRef(route.params);
  const [status, setStatus] = useState(first.current.status || "");
  const [q, setQ] = useState(first.current.q || "");
  const [term, setTerm] = useState((first.current.q || "").trim());
  const [page, setPage] = useState(Math.max(1, Number(first.current.page) || 1));
  const [data, setData] = useState(null);
  const [counts, setCounts] = useState(null);
  const [error, setError] = useState("");
  const termRef = useRef(term);

  // Debounced search; only reset to page 1 when the search text really changed (keeps a restored page).
  useEffect(() => {
    const t = setTimeout(() => {
      const next = q.trim();
      if (next !== termRef.current) { termRef.current = next; setTerm(next); setPage(1); }
    }, 300);
    return () => clearTimeout(t);
  }, [q]);

  // Mirror the filters into the address bar without adding history entries or re-rendering the router.
  useEffect(() => { window.history.replaceState(null, "", `#admin/enquiries${listQuery({ status, term, page })}`); }, [status, term, page]);

  useEffect(() => { call("/api/v1/admin/stats").then((s) => setCounts({ ...s.by_status, all: s.total })).catch(() => setCounts(null)); }, [call]);

  const load = useCallback(() => {
    setError(""); setData(null);
    call(`/api/v1/admin/enquiries${qs({ status, q: term, page, page_size: 15 })}`).then(setData).catch((e) => setError(e.message));
  }, [call, status, term, page]);
  useEffect(load, [load]);

  const filtered = Boolean(status || term);
  const clear = () => { setStatus(""); setQ(""); termRef.current = ""; setTerm(""); setPage(1); };
  const pick = (s) => { setStatus(s); setPage(1); };
  const ctx = listQuery({ status, term, page });

  return (
    <>
      <PageHead eyebrow="Administration" title="Student enquiries">Find an enquiry, open it, and set its status. New enquiries are marked.</PageHead>
      <div className="tabs" role="group" aria-label="Filter by status">
        {[["", "All", counts?.all], ...STATUSES.map((s) => [s, STATUS_LABELS[s], counts?.[s]])].map(([value, label, n]) => (
          <button key={value || "all"} type="button" className="tab" aria-pressed={status === value} onClick={() => pick(value)}>{label}{n !== undefined && <i>{n}</i>}</button>
        ))}
      </div>
      <div className="toolbar">
        <div className="search"><Search size={17} /><input type="search" placeholder="Search name, email, phone or reference" aria-label="Search enquiries" value={q} onChange={(e) => setQ(e.target.value)} maxLength={100} /></div>
        {filtered && <button type="button" className="btn btn--quiet btn--sm" onClick={clear}><X size={16} /> Clear filters</button>}
      </div>
      {error && <><Alert kind="error" title="Could not load enquiries">{error}</Alert><button type="button" className="btn btn--secondary btn--sm" onClick={load}><RefreshCw size={16} /> Try again</button></>}
      {!data && !error && <Spinner label="Loading enquiries…" />}
      {data && data.items.length === 0 && (
        <div className="card pad"><EmptyState icon={Inbox} title={filtered ? "No enquiries match" : "No enquiries yet"}
          action={filtered ? <button type="button" className="btn btn--secondary btn--sm" onClick={clear}>Clear filters</button> : undefined}>
          {filtered ? "Try a different search or status." : "New student enquiries will appear here."}</EmptyState></div>
      )}
      {data && data.items.length > 0 && (
        <>
          <div className="list-meta"><span>{data.total} enquir{data.total === 1 ? "y" : "ies"}{filtered ? " match" : ""} · page {data.page} of {data.pages}</span></div>
          <div className="card table-wrap">
            <table className="table">
              <caption className="sr-only">Student enquiries, newest first</caption>
              <thead><tr><th scope="col">Student</th><th scope="col">Programme</th><th scope="col">Status</th><th scope="col">Received</th><th scope="col">Reference</th></tr></thead>
              <tbody>
                {data.items.map((e) => {
                  const to = `admin/enquiries/${e.id}${ctx}`;
                  const open = e.status === "new" || e.status === "in_progress";
                  return (
                    <tr key={e.id} className={e.status === "new" ? "is-new" : ""}>
                      <td data-label="Student"><a className="who" href={`#${to}`} onClick={(ev) => { ev.preventDefault(); navigate(to); }}>{e.full_name}</a><small className="break">{e.email}</small><small className="msg-preview">{e.message_preview}</small></td>
                      <td data-label="Programme">{e.programme}</td>
                      <td data-label="Status"><StatusBadge status={e.status} />{open && <span className="wait">Waiting {waitingLabel(e.created_at)}</span>}</td>
                      <td data-label="Received">{formatDate(e.created_at)}</td>
                      <td data-label="Reference"><span className="mono">{e.reference}</span></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="pager">
            <span className="muted small">Page {data.page} of {data.pages}</span>
            <div>
              <button className="icon-btn" disabled={page <= 1} onClick={() => setPage((p) => p - 1)} aria-label="Previous page"><ChevronLeft size={18} /></button>
              <button className="icon-btn" disabled={page >= data.pages} onClick={() => setPage((p) => p + 1)} aria-label="Next page"><ChevronRight size={18} /></button>
            </div>
          </div>
        </>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ Detail */
const QUICK = [
  { status: "in_progress", label: "Start working on it" },
  { status: "responded", label: "Mark as responded" },
  { status: "closed", label: "Close enquiry" },
];

function EnquiryDetail({ id, route, navigate, notify }) {
  const call = useAdminApi();
  const [e, setE] = useState(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");

  // The list's filters travel in this page's own query string, so "back" returns to the same view.
  const ctx = new URLSearchParams(route.params).toString();
  const listTarget = `admin/enquiries${ctx ? `?${ctx}` : ""}`;

  useEffect(() => {
    setE(null); setError("");
    call(`/api/v1/admin/enquiries/${encodeURIComponent(id)}`)
      .then((d) => { setE(d.enquiry); setStatus(d.enquiry.status); setNotes(d.enquiry.admin_notes || ""); })
      .catch((err) => setError(err.status === 404 ? "This enquiry does not exist." : err.message));
  }, [call, id]);

  async function save(nextStatus = status) {
    setSaving(true); setSaveError("");
    try {
      const d = await call(`/api/v1/admin/enquiries/${encodeURIComponent(id)}`, { method: "PATCH", body: { status: nextStatus, admin_notes: notes } });
      setE(d.enquiry); setStatus(d.enquiry.status); notify("Enquiry updated.");
    } catch (err) { setSaveError(err.fields?.admin_notes || err.fields?.status || err.message); }
    finally { setSaving(false); }
  }

  const back = <a className="text-link back" href={`#${listTarget}`} onClick={(ev) => { ev.preventDefault(); navigate(listTarget); }}><ArrowLeft size={16} /> {ctx ? "Back to filtered list" : "All enquiries"}</a>;
  if (error) return <>{back}<Alert kind="error">{error}</Alert></>;
  if (!e) return <>{back}<Spinner label="Loading enquiry…" /></>;
  const dirty = status !== e.status || notes !== (e.admin_notes || "");
  const open = e.status === "new" || e.status === "in_progress";

  return (
    <>
      {back}
      <PageHead eyebrow={e.reference} title={e.full_name} actions={<StatusBadge status={e.status} />}>
        Received {formatDate(e.created_at)}{open && <> · waiting {waitingLabel(e.created_at)}</>}
      </PageHead>
      <div className="two-col two-col--detail">
        <section className="card pad" aria-labelledby="d-h">
          <h2 id="d-h" className="h-sm">Student details</h2>
          <dl className="kv kv--stack">
            <div><dt>Email</dt><dd className="break"><a className="text-link" href={`mailto:${e.email}`}>{e.email}</a></dd></div>
            <div><dt>Phone</dt><dd><a className="text-link" href={`tel:${e.phone}`}>{e.phone}</a></dd></div>
            <div><dt>Programme</dt><dd>{e.programme}</dd></div>
            <div><dt>Has student account</dt><dd>{e.has_account ? "Yes" : "No (sent without signing in)"}</dd></div>
            <div><dt>Consent given</dt><dd>{formatDate(e.consent_at)} <small className="muted">(wording {e.consent_version})</small></dd></div>
          </dl>
          <h3 className="h-xs">Question</h3>
          <p className="msg-box">{e.message}</p>
        </section>
        <form className="card pad sticky-card" onSubmit={(ev) => { ev.preventDefault(); save(); }} aria-labelledby="u-h">
          <h2 id="u-h" className="h-sm">Update</h2>
          {saveError && <Alert kind="error">{saveError}</Alert>}
          <div className="quick" role="group" aria-label="Quick status actions">
            {QUICK.filter((a) => a.status !== e.status).map((a) => (
              <button key={a.status} type="button" className="btn btn--secondary btn--sm" disabled={saving} onClick={() => save(a.status)}>{a.label}</button>
            ))}
          </div>
          <Field as="select" label="Status" value={status} onChange={(ev) => setStatus(ev.target.value)}>
            {STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABELS[s]}</option>)}
          </Field>
          <Field as="textarea" rows={6} label="Internal notes" value={notes} onChange={(ev) => setNotes(ev.target.value)} maxLength={4000} hint="Visible to administrators only. Never shown to the student." />
          <button className="btn btn--primary btn--sm" type="submit" disabled={saving || !dirty}>{saving ? <><Loader2 size={16} className="spin" /> Saving…</> : "Save changes"}</button>
          {dirty && !saving && <p className="small muted">You have unsaved changes.</p>}
          <p className="muted small">Last updated {formatDate(e.updated_at)}</p>
        </form>
      </div>
    </>
  );
}

/* ------------------------------------------------------------------ Programmes */
function Programmes({ notify }) {
  const call = useAdminApi();
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");
  const [name, setName] = useState("");
  const [nameError, setNameError] = useState("");
  const [busy, setBusy] = useState(false);
  const [toggling, setToggling] = useState(null);

  const load = useCallback(() => { setError(""); call("/api/v1/admin/programmes").then((d) => setItems(d.items)).catch((e) => setError(e.message)); }, [call]);
  useEffect(load, [load]);

  async function add(ev) {
    ev.preventDefault(); setBusy(true); setNameError("");
    try { await call("/api/v1/admin/programmes", { method: "POST", body: { name } }); setName(""); notify("Programme added."); load(); }
    catch (err) { setNameError(err.fields?.name || err.message); }
    finally { setBusy(false); }
  }
  async function toggle(p) {
    setToggling(p.id);
    try { await call(`/api/v1/admin/programmes/${p.id}`, { method: "PATCH", body: { is_active: !p.is_active } }); notify(p.is_active ? "Programme hidden from the form." : "Programme shown on the form."); load(); }
    catch (err) { notify(err.message, "error"); }
    finally { setToggling(null); }
  }

  const shown = items ? items.filter((p) => p.is_active).length : 0;

  return (
    <>
      <PageHead eyebrow="Administration" title="Programmes">The list students choose from on the admissions enquiry form.</PageHead>
      <p className="prog-help">Add only programmes that SVCE has confirmed. Hiding a programme removes it from the enquiry form; it can be shown again at any time. If no programme is shown, students type the programme themselves.</p>
      <form className="card pad inline-form" onSubmit={add}>
        <Field label="New programme name" value={name} onChange={(e) => { setName(e.target.value); setNameError(""); }} error={nameError} maxLength={120} hint="Use the official programme name." />
        <button className="btn btn--primary btn--sm" type="submit" disabled={busy || !name.trim()}>{busy ? <Loader2 size={16} className="spin" /> : <Plus size={16} />} Add programme</button>
      </form>
      {error && <><Alert kind="error" title="Could not load programmes">{error}</Alert><button type="button" className="btn btn--secondary btn--sm" onClick={load}><RefreshCw size={16} /> Try again</button></>}
      {!items && !error && <Spinner label="Loading programmes…" />}
      {items && items.length === 0 && <div className="card pad"><EmptyState icon={BookOpen} title="No programmes added yet">The enquiry form currently asks students to type the programme. Add confirmed programmes above to turn that into a list.</EmptyState></div>}
      {items && items.length > 0 && (
        <>
          <p className="list-meta"><span>{items.length} programme{items.length === 1 ? "" : "s"} · {shown} shown on the form · {items.length - shown} hidden</span></p>
          <ul className="card prog-list">
            {items.map((p) => (
              <li key={p.id}>
                <span className="prog-name"><span className={p.is_active ? "" : "muted"}>{p.name}</span>
                  <span className={`badge ${p.is_active ? "badge--responded" : "badge--closed"}`}>{p.is_active ? "Shown on form" : "Hidden"}</span></span>
                <button type="button" className="btn btn--quiet btn--sm" disabled={toggling === p.id} onClick={() => toggle(p)}>{p.is_active ? "Hide from form" : "Show on form"}</button>
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}
