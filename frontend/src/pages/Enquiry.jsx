import React, { useEffect, useState } from "react";
import { ArrowRight, CircleCheck, Clock, Loader2, MessageCircle, ShieldCheck } from "lucide-react";
import { api } from "../lib/api.js";
import { useAuth } from "../lib/auth.jsx";
import { EMAIL_RE, formatDate } from "../lib/format.js";
import { Alert, Field, PageHead, Spinner } from "../components/ui/index.jsx";

/**
 * Data journey of this form:
 *  1. React state holds what the student typed.
 *  2. On submit we check basic mistakes in the browser (fast feedback) ...
 *  3. ... then POST JSON to /api/v1/enquiries. The BACKEND validates again (never trust the browser)
 *     and, only if valid, INSERTs a row into the SQLite `enquiries` table.
 *  4. The server replies with a reference number, which we show as the confirmation.
 */
export default function Enquiry({ navigate }) {
  const { user } = useAuth();
  const [config, setConfig] = useState(null);
  const [loadError, setLoadError] = useState("");
  const [form, setForm] = useState({ full_name: "", email: "", phone: "", programme: "", programme_other: "", message: "", consent: false });
  const [errors, setErrors] = useState({});
  const [formError, setFormError] = useState("");
  const [busy, setBusy] = useState(false);
  const [receipt, setReceipt] = useState(null);

  useEffect(() => {
    api("/api/v1/enquiries/form-config").then(setConfig).catch((e) => setLoadError(e.message));
  }, []);

  // Pre-fill from the signed-in account (editable).
  useEffect(() => {
    if (user) setForm((f) => ({ ...f, full_name: f.full_name || user.full_name, email: f.email || user.email }));
  }, [user]);

  useEffect(() => { if (formError) document.querySelector(".form-card .alert--error")?.scrollIntoView({ block: "center" }); }, [formError]);

  const set = (key) => (e) => { setForm((f) => ({ ...f, [key]: e.target.type === "checkbox" ? e.target.checked : e.target.value })); setErrors((x) => ({ ...x, [key]: undefined })); };
  const lim = config?.limits || { message_min: 10, message_max: 2000 };
  const programmes = config?.programmes || [];

  function validate() {
    const e = {};
    if (form.full_name.trim().length < 2) e.full_name = "Enter your full name.";
    if (!EMAIL_RE.test(form.email.trim())) e.email = "Enter a valid email address.";
    if (form.phone.replace(/\D/g, "").length < 8) e.phone = "Enter a valid phone number.";
    if (form.message.trim().length < lim.message_min) e.message = `Please describe your question (at least ${lim.message_min} characters).`;
    if (form.message.length > lim.message_max) e.message = `Please keep your message under ${lim.message_max} characters.`;
    if (!form.consent) e.consent = "You must give consent so we can store your details and contact you.";
    return e;
  }

  async function onSubmit(event) {
    event.preventDefault();
    if (busy) return;
    setFormError("");
    const e = validate();
    setErrors(e);
    if (Object.keys(e).length) { document.querySelector(".has-error .control, .has-error input")?.focus(); return; }
    setBusy(true);
    try {
      const isListed = form.programme && form.programme !== "other";
      const result = await api("/api/v1/enquiries", {
        method: "POST",
        body: {
          full_name: form.full_name, email: form.email, phone: form.phone, message: form.message,
          programme_id: isListed ? Number(form.programme) : null,
          programme_other: form.programme === "other" || (!programmes.length) ? form.programme_other : "",
          consent: form.consent,
        },
      });
      setReceipt(result);
      window.scrollTo({ top: 0, behavior: "auto" });
    } catch (err) {
      if (err.fields && Object.keys(err.fields).length) setErrors(err.fields);
      setFormError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const go = (t) => (e) => { e.preventDefault(); navigate(t); };
  // Start a fresh enquiry but keep the contact details the student already typed.
  const another = () => { setReceipt(null); setErrors({}); setFormError(""); setForm((f) => ({ ...f, programme: "", programme_other: "", message: "", consent: false })); };

  if (receipt) {
    const r = receipt.enquiry;
    return (
      <main id="main" tabIndex={-1} className="container narrow section">
        <div className="card success-card">
          <span className="icon-tile icon-tile--teal"><CircleCheck size={24} /></span>
          <h1>{receipt.duplicate ? "We already have this enquiry" : "Enquiry received"}</h1>
          <p className="lede">
            {receipt.duplicate
              ? "You sent this same enquiry recently, so we did not create a second copy. Our team already has it."
              : "Thank you. The SVCE admissions team will review your question and contact you using the details you provided."}
          </p>
          <dl className="kv">
            <div><dt>Reference</dt><dd className="mono">{r.reference}</dd></div>
            <div><dt>Programme</dt><dd>{r.programme}</dd></div>
            <div><dt>Status</dt><dd>New</dd></div>
            <div><dt>Submitted</dt><dd>{formatDate(r.created_at)}</dd></div>
          </dl>
          <p className="muted small">Keep this reference number if you need to follow up.</p>
          <div className="btn-row">
            {user
              ? <a className="btn btn--primary" href="#dashboard" onClick={go("dashboard")}>View my enquiries <ArrowRight size={18} className="btn-arrow" /></a>
              : <a className="btn btn--primary" href="#register" onClick={go("register")}>Create an account to track it <ArrowRight size={18} className="btn-arrow" /></a>}
            <a className="btn btn--secondary" href="#assistant" onClick={go("assistant")}><MessageCircle size={18} /> Ask the assistant</a>
            <button type="button" className="btn btn--quiet" onClick={another}>Send another enquiry</button>
          </div>
          {!user && <p className="muted small">This enquiry was sent without signing in, so it will not appear in a student dashboard.</p>}
        </div>
      </main>
    );
  }

  return (
    <main id="main" tabIndex={-1} className="container enq-page section">
      <PageHead eyebrow="Admissions enquiry" title="Ask the SVCE admissions team">
        Send your question and contact details to the admissions team at Sri Venkateswara College of Engineering, Tirupati.
      </PageHead>

      <div className="enq-layout">
        <div className="enq-main">
          {!user && <Alert kind="info">Have an account? <a className="text-link" href="#login?next=enquiry" onClick={go("login?next=enquiry")}>Sign in</a> to track your enquiry status afterwards. You can also send this form without signing in.</Alert>}
          {loadError && <Alert kind="error">{loadError} You can still fill in the form; the programme list may be unavailable.</Alert>}

          {!config && !loadError ? <Spinner label="Loading form…" /> : (
            <form className="card form-card" onSubmit={onSubmit} noValidate>
              {formError && <Alert kind="error">{formError}</Alert>}
              <h2 className="form-section">Your details</h2>
              <div className="form-grid">
                <Field label="Full name" value={form.full_name} onChange={set("full_name")} error={errors.full_name} autoComplete="name" required maxLength={100} />
                <Field label="Email" type="email" inputMode="email" value={form.email} onChange={set("email")} error={errors.email} autoComplete="email" required maxLength={254} />
                <Field label="Phone number" type="tel" inputMode="tel" value={form.phone} onChange={set("phone")} error={errors.phone} autoComplete="tel" required
                  hint="10-digit Indian mobile number, or include your country code (+…)." maxLength={25} />
                {programmes.length > 0 ? (
                  <Field as="select" label="Programme you are interested in" value={form.programme} onChange={set("programme")} error={errors.programme_id}>
                    <option value="">{config?.general_label || "General / not sure yet"}</option>
                    {programmes.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                    <option value="other">Other (type below)</option>
                  </Field>
                ) : (
                  <Field label="Programme you are interested in" value={form.programme_other} onChange={set("programme_other")} error={errors.programme_other}
                    hint="Optional. Leave blank if you are not sure yet." maxLength={120} />
                )}
                {programmes.length > 0 && form.programme === "other" && (
                  <Field className="span-2" label="Programme name" value={form.programme_other} onChange={set("programme_other")} error={errors.programme_other} maxLength={120} />
                )}
              </div>

              <h2 className="form-section">Your question</h2>
              <div className="form-grid">
                <div className="span-2">
                  <Field as="textarea" rows={6} label="Your question" value={form.message} onChange={set("message")} error={errors.message} required maxLength={lim.message_max + 200}
                    hint="Admission-related questions only, for example eligibility, process or documents." />
                  <p className={`counter ${form.message.length > lim.message_max ? "over" : ""}`} aria-live="off">{form.message.length} / {lim.message_max}</p>
                </div>
              </div>

              <h2 className="form-section">Consent</h2>
              <div className={`consent ${errors.consent ? "has-error" : ""}`}>
                <label className="check">
                  <input type="checkbox" checked={form.consent} onChange={set("consent")} aria-invalid={errors.consent ? "true" : undefined} aria-describedby={errors.consent ? "consent-err" : undefined} />
                  <span><ShieldCheck size={16} className="inline-icon" /> {config?.consent_text || "I agree that the details I enter may be stored and used by the college admissions team to respond to my enquiry."}</span>
                </label>
                {errors.consent && <p id="consent-err" className="field-error" role="alert">{errors.consent}</p>}
              </div>
              <p className="small muted consent-note">The consent wording and privacy notice are pending college approval.</p>

              <button className="btn btn--primary btn--lg" type="submit" disabled={busy}>
                {busy ? <><Loader2 size={18} className="spin" /> Sending…</> : <>Send enquiry <ArrowRight size={18} className="btn-arrow" /></>}
              </button>
            </form>
          )}
        </div>

        <aside className="enq-side" aria-label="About this enquiry">
          <section className="card enq-box">
            <h2>What happens next</h2>
            <ol className="enq-steps">
              <li><b>You send the form.</b> Your details are stored with your consent.</li>
              <li><b>You get a reference number</b> on screen. Keep it if you need to follow up.</li>
              <li><b>The admissions team reviews</b> your question and contacts you using the email or phone you gave.</li>
            </ol>
            <p className="small muted">If you send the same enquiry again within a short time, it is not duplicated and you see the existing reference.</p>
          </section>
          <section className="card enq-box">
            <h2>Need a quick answer?</h2>
            <p>Try the AI assistant for questions about the college. It shows sources when available.</p>
            <a className="btn btn--secondary btn--sm" href="#assistant" onClick={go("assistant")}><MessageCircle size={16} /> Ask the assistant</a>
          </section>
          <section className="card enq-box">
            <h2>Admissions contact</h2>
            <p>Phone and email of the admissions office will be listed here once approved by the college.</p>
            <span className="pending-tag"><Clock size={13} aria-hidden="true" /> Pending college approval</span>
          </section>
        </aside>
      </div>
    </main>
  );
}
