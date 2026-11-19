import React, { useState } from "react";
import { ArrowRight, Eye, EyeOff, Loader2, LockKeyhole, ShieldCheck } from "lucide-react";
import { useAuth } from "../lib/auth.jsx";
import { EMAIL_RE } from "../lib/format.js";
import { Alert, Field } from "../components/ui/index.jsx";

/** Only allow redirecting to our own known pages after sign-in (prevents "open redirect" tricks). */
const safeNext = (next) => (/^(dashboard|enquiry|assistant|admin(\/[a-z0-9-]+)*)$/.test(next || "") ? next : null);

function PasswordField({ label, value, onChange, error, autoComplete, hint }) {
  const [show, setShow] = useState(false);
  return (
    <div className="pw-wrap">
      <Field label={label} type={show ? "text" : "password"} value={value} onChange={onChange} error={error} hint={hint}
        autoComplete={autoComplete} required maxLength={128} />
      <button type="button" className="pw-toggle icon-btn icon-btn--ghost" onClick={() => setShow((s) => !s)} aria-label={show ? "Hide password" : "Show password"}>
        {show ? <EyeOff size={18} /> : <Eye size={18} />}
      </button>
    </div>
  );
}

/** One page for three modes: "login" (students), "register" (students), "admin" (staff sign-in). */
export default function Auth({ mode, navigate, route, notify }) {
  const { login, register, logout } = useAuth();
  const isRegister = mode === "register";
  const isAdmin = mode === "admin";
  const [form, setForm] = useState({ full_name: "", email: "", password: "", confirm: "" });
  const [errors, setErrors] = useState({});
  const [formError, setFormError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (key) => (e) => { setForm((f) => ({ ...f, [key]: e.target.value })); setErrors((x) => ({ ...x, [key]: undefined })); };

  function validate() {
    const e = {};
    const name = form.full_name.trim().replace(/\s+/g, " ");
    if (isRegister && (name.length < 2 || name.length > 100)) e.full_name = "Enter your full name (2-100 letters).";
    if (!EMAIL_RE.test(form.email.trim())) e.email = "Enter a valid email address.";
    if (!form.password) e.password = "Enter your password.";
    if (isRegister) {
      if (form.password && form.password.length < 10) e.password = "Use at least 10 characters.";
      if (form.confirm !== form.password) e.confirm = "The two passwords do not match.";
    }
    return e;
  }

  async function onSubmit(event) {
    event.preventDefault();
    if (busy) return;
    setFormError("");
    const e = validate();
    setErrors(e);
    if (Object.keys(e).length) return;
    setBusy(true);
    try {
      let user;
      if (isRegister) user = await register({ full_name: form.full_name, email: form.email, password: form.password });
      else user = await login(form.email, form.password);

      if (isAdmin && user.role !== "admin") {
        await logout();
        setFormError("This account does not have administrator access. Students can sign in from the student sign-in page.");
        return;
      }
      notify(isRegister ? "Account created — welcome!" : `Welcome back, ${user.full_name.split(" ")[0]}.`);
      const next = safeNext(route.params.next);
      navigate(user.role === "admin" ? (next?.startsWith("admin") ? next : "admin") : (next && !next.startsWith("admin") ? next : "dashboard"));
    } catch (err) {
      if (err.fields && Object.keys(err.fields).length) setErrors(err.fields);
      setFormError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const title = isAdmin ? "Staff sign-in" : isRegister ? "Create your student account" : "Student sign-in";
  const intro = isAdmin
    ? "For SVCE administrators managing student enquiries."
    : isRegister
      ? "Track your enquiries and get quick access to the campus assistant."
      : "Sign in to see your enquiries and use the campus assistant.";

  return (
    <main id="main" tabIndex={-1} className="auth">
      <div className="auth-card card">
        <span className="icon-tile icon-tile--teal">{isAdmin ? <ShieldCheck size={22} /> : <LockKeyhole size={22} />}</span>
        <h1>{title}</h1>
        <p className="auth-intro">{intro}</p>

        <form onSubmit={onSubmit} noValidate>
          {formError && <Alert kind="error">{formError}</Alert>}
          {isRegister && <Field label="Full name" value={form.full_name} onChange={set("full_name")} error={errors.full_name} autoComplete="name" required maxLength={100} />}
          <Field label="Email" type="email" inputMode="email" value={form.email} onChange={set("email")} error={errors.email} autoComplete="email" required maxLength={254} />
          <PasswordField label="Password" value={form.password} onChange={set("password")} error={errors.password}
            autoComplete={isRegister ? "new-password" : "current-password"} hint={isRegister ? "At least 10 characters. Avoid common passwords." : undefined} />
          {isRegister && <PasswordField label="Confirm password" value={form.confirm} onChange={set("confirm")} error={errors.confirm} autoComplete="new-password" />}
          <button className="btn btn--primary auth-submit" type="submit" disabled={busy}>
            {busy ? <><Loader2 size={18} className="spin" /> Please wait…</> : <>{isRegister ? "Create account" : "Sign in"} <ArrowRight size={18} className="btn-arrow" /></>}
          </button>
        </form>

        <p className="auth-switch">
          {isAdmin ? <>Student? <a href="#login" onClick={(e) => { e.preventDefault(); navigate("login"); }}>Student sign-in</a></>
            : isRegister ? <>Already have an account? <a href="#login" onClick={(e) => { e.preventDefault(); navigate("login"); }}>Sign in</a></>
              : <>New here? <a href="#register" onClick={(e) => { e.preventDefault(); navigate("register"); }}>Create a student account</a></>}
        </p>
        {!isAdmin && !isRegister && <p className="auth-switch auth-switch--quiet"><a href="#admin/login" onClick={(e) => { e.preventDefault(); navigate("admin/login"); }}>Staff sign-in</a></p>}
      </div>
    </main>
  );
}
