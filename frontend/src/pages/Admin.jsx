import React, { useCallback, useEffect, useState } from "react";
import { ArrowLeft, BookOpen, ChevronLeft, ChevronRight, ClipboardList, Inbox, LayoutDashboard, Loader2, LogOut, Plus, RefreshCw, Search } from "lucide-react";
import { api, qs } from "../lib/api.js";
import { useAuth } from "../lib/auth.jsx";
import { formatDate, STATUSES, STATUS_LABELS } from "../lib/format.js";
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
  const { user, logout } = useAuth();
  const [section, id] = route.parts;
  const current = section === "enquiries" ? "admin/enquiries" : section === "programmes" ? "admin/programmes" : "admin";
  const go = (t) => (e) => { e.preventDefault(); navigate(t); };

  let body;
  if (!section) body = <Overview navigate={navigate} />;
  else if (section === "enquiries" && id) body = <EnquiryDetail id={id} navigate={navigate} notify={notify} />;
  else if (section === "enquiries") body = <EnquiryList navigate={navigate} />;
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
        <button type="button" className="admin-out" onClick={async () => { navigate("home"); await logout(); notify("You have been signed out."); }}><LogOut size={17} /> Sign out</button>
      </aside>
      <div className="admin-body">{body}</div>
    </main>
  );
}

/* ------------------------------------------------------------------ Overview */
function Overview({ navigate }) {
  const call = useAdminApi();
  const [stats, setStats] = useState(null);
  const [error, setError] = useState("");
  const load = useCallback(() => { setError(""); setStats(null); call("/api/v1/admin/stats").then(setStats).catch((e) => setError(e.message)); }, [call]);
  useEffect(load, [load]);

  const max = stats ? Math.max(1, ...stats.daily.map((d) => d.count)) : 1;
  const tiles = stats && [
    { label: "Total enquiries", value: stats.total },
    { label: "Open (new + in progress)", value: stats.open },
    { label: "Received today (UTC)", value: stats.today },
    { label: "Last 7 days", value: stats.last_7_days },
    { label: "Student accounts", value: stats.student_accounts },
  ];

  return (
    <>
      <PageHead eyebrow="Administration" title="Enquiry overview"
        actions={<button type="button" className="icon-btn" onClick={load} aria-label="Refresh" data-tip="Refresh" data-tip-pos="bottom"><RefreshCw size={17} /></button>}>
        A live summary of student enquiries stored in the database.
      </PageHead>
      {error && <Alert kind="error" title="Could not load statistics">{error}</Alert>}
      {!stats && !error && <Spinner label="Loading statistics…" />}
      {stats && (
        <>
          <div className="stat-grid">
            {tiles.map((t) => <div key={t.label} className="card stat"><b>{t.value}</b><span>{t.label}</span></div>)}
          </div>
          <div className="two-col">
            <section className="card pad" aria-labelledby="st-h">
              <h2 id="st-h" className="h-sm">By status</h2>
              <ul className="status-rows">
                {STATUSES.map((s) => (
                  <li key={s}>
                    <a href={`#admin/enquiries?status=${s}`} onClick={(e) => { e.preventDefault(); navigate(`admin/enquiries?status=${s}`); }}>
                      <StatusBadge status={s} /><b>{stats.by_status[s]}</b>
                    </a>
                  </li>
                ))}
              </ul>
            </section>
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
          </div>
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
        </>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ List */
function EnquiryList({ navigate }) {
  const call = useAdminApi();
  const route = new URLSearchParams(window.location.hash.split("?")[1] || "");
  const [status, setStatus] = useState(route.get("status") || "");
  const [q, setQ] = useState("");
  const [term, setTerm] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => { const t = setTimeout(() => { setTerm(q.trim()); setPage(1); }, 300); return () => clearTimeout(t); }, [q]);
  const load = useCallback(() => {
    setError(""); setData(null);
    call(`/api/v1/admin/enquiries${qs({ status, q: term, page, page_size: 15 })}`).then(setData).catch((e) => setError(e.message));
  }, [call, status, term, page]);
  useEffect(load, [load]);

  return (
    <>
      <PageHead eyebrow="Administration" title="Student enquiries">Search, filter and open an enquiry to read it and update its status.</PageHead>
      <div className="toolbar">
        <div className="search"><Search size={17} /><input type="search" placeholder="Search name, email, phone or reference" aria-label="Search enquiries" value={q} onChange={(e) => setQ(e.target.value)} maxLength={100} /></div>
        <select className="control" aria-label="Filter by status" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
          <option value="">All statuses</option>
          {STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABELS[s]}</option>)}
        </select>
      </div>
      {error && <Alert kind="error" title="Could not load enquiries">{error}</Alert>}
      {!data && !error && <Spinner label="Loading enquiries…" />}
      {data && data.items.length === 0 && <div className="card pad"><EmptyState icon={Inbox} title="No enquiries found">{status || term ? "Try clearing the search or filter." : "New student enquiries will appear here."}</EmptyState></div>}
      {data && data.items.length > 0 && (
        <>
          <div className="card table-wrap">
            <table className="table">
              <thead><tr><th>Reference</th><th>Student</th><th>Programme</th><th>Status</th><th>Received</th></tr></thead>
              <tbody>
                {data.items.map((e) => (
                  <tr key={e.id}>
                    <td data-label="Reference"><a className="text-link mono" href={`#admin/enquiries/${e.id}`} onClick={(ev) => { ev.preventDefault(); navigate(`admin/enquiries/${e.id}`); }}>{e.reference}</a></td>
                    <td data-label="Student"><b>{e.full_name}</b><small className="break">{e.email}</small><small className="msg-preview">{e.message_preview}</small></td>
                    <td data-label="Programme">{e.programme}</td>
                    <td data-label="Status"><StatusBadge status={e.status} /></td>
                    <td data-label="Received">{formatDate(e.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="pager">
            <span className="muted small">{data.total} enquir{data.total === 1 ? "y" : "ies"} · page {data.page} of {data.pages}</span>
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
function EnquiryDetail({ id, navigate, notify }) {
  const call = useAdminApi();
  const [e, setE] = useState(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");

  useEffect(() => {
    setE(null); setError("");
    call(`/api/v1/admin/enquiries/${encodeURIComponent(id)}`)
      .then((d) => { setE(d.enquiry); setStatus(d.enquiry.status); setNotes(d.enquiry.admin_notes || ""); })
      .catch((err) => setError(err.status === 404 ? "This enquiry does not exist." : err.message));
  }, [call, id]);

  async function save(ev) {
    ev.preventDefault();
    setSaving(true); setSaveError("");
    try {
      const d = await call(`/api/v1/admin/enquiries/${encodeURIComponent(id)}`, { method: "PATCH", body: { status, admin_notes: notes } });
      setE(d.enquiry); notify("Enquiry updated.");
    } catch (err) { setSaveError(err.fields?.admin_notes || err.fields?.status || err.message); }
    finally { setSaving(false); }
  }

  const back = <a className="text-link back" href="#admin/enquiries" onClick={(ev) => { ev.preventDefault(); navigate("admin/enquiries"); }}><ArrowLeft size={16} /> All enquiries</a>;
  if (error) return <>{back}<Alert kind="error">{error}</Alert></>;
  if (!e) return <>{back}<Spinner label="Loading enquiry…" /></>;
  const dirty = status !== e.status || notes !== (e.admin_notes || "");

  return (
    <>
      {back}
      <PageHead eyebrow={e.reference} title={e.full_name} actions={<StatusBadge status={e.status} />}>Received {formatDate(e.created_at)}</PageHead>
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
        <form className="card pad" onSubmit={save} aria-labelledby="u-h">
          <h2 id="u-h" className="h-sm">Update</h2>
          {saveError && <Alert kind="error">{saveError}</Alert>}
          <Field as="select" label="Status" value={status} onChange={(ev) => setStatus(ev.target.value)}>
            {STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABELS[s]}</option>)}
          </Field>
          <Field as="textarea" rows={6} label="Internal notes" value={notes} onChange={(ev) => setNotes(ev.target.value)} maxLength={4000} hint="Visible to administrators only. Never shown to the student." />
          <button className="btn btn--primary btn--sm" type="submit" disabled={saving || !dirty}>{saving ? <><Loader2 size={16} className="spin" /> Saving…</> : "Save changes"}</button>
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

  const load = useCallback(() => { call("/api/v1/admin/programmes").then((d) => setItems(d.items)).catch((e) => setError(e.message)); }, [call]);
  useEffect(load, [load]);

  async function add(ev) {
    ev.preventDefault(); setBusy(true); setNameError("");
    try { await call("/api/v1/admin/programmes", { method: "POST", body: { name } }); setName(""); notify("Programme added."); load(); }
    catch (err) { setNameError(err.fields?.name || err.message); }
    finally { setBusy(false); }
  }
  async function toggle(p) {
    try { await call(`/api/v1/admin/programmes/${p.id}`, { method: "PATCH", body: { is_active: !p.is_active } }); load(); }
    catch (err) { notify(err.message, "error"); }
  }

  return (
    <>
      <PageHead eyebrow="Administration" title="Programmes">The programmes students can pick on the enquiry form. Enter only courses SVCE actually offers.</PageHead>
      <form className="card pad inline-form" onSubmit={add}>
        <Field label="New programme name" value={name} onChange={(e) => { setName(e.target.value); setNameError(""); }} error={nameError} maxLength={120} />
        <button className="btn btn--primary btn--sm" type="submit" disabled={busy || !name.trim()}><Plus size={16} /> Add</button>
      </form>
      {error && <Alert kind="error">{error}</Alert>}
      {!items && !error && <Spinner />}
      {items && items.length === 0 && <div className="card pad"><EmptyState icon={BookOpen} title="No programmes yet">Until you add some, students can type the programme they are interested in.</EmptyState></div>}
      {items && items.length > 0 && (
        <ul className="card prog-list">
          {items.map((p) => (
            <li key={p.id}><span className={p.is_active ? "" : "muted"}>{p.name}</span>
              <button type="button" className="btn btn--quiet btn--sm" onClick={() => toggle(p)}>{p.is_active ? "Hide from form" : "Show on form"}</button></li>
          ))}
        </ul>
      )}
    </>
  );
}
