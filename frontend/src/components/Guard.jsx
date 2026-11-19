import React, { useEffect } from "react";
import { ShieldAlert } from "lucide-react";
import { useAuth } from "../lib/auth.jsx";
import { EmptyState, Spinner } from "./ui/index.jsx";

/**
 * Frontend route protection. This only improves the experience (redirects, friendly messages).
 * The REAL protection is the backend: every protected API re-checks the cookie and role.
 */
export default function Guard({ role, navigate, loginTarget, children }) {
  const { user, status } = useAuth();
  const wrongRole = user && ((role === "admin" && user.role !== "admin") || (role === "student" && user.role === "admin"));

  useEffect(() => {
    if (status !== "ready") return;
    if (!user) {
      const next = window.location.hash.replace(/^#/, "");
      navigate(`${loginTarget}?next=${encodeURIComponent(next)}`, { replace: true });
    } else if (role === "student" && user.role === "admin") {
      navigate("admin", { replace: true });
    }
  }, [status, user, role, navigate, loginTarget]);

  if (status === "loading" || !user || (role === "student" && wrongRole)) return <main id="main" tabIndex={-1}><Spinner label="Checking your session…" /></main>;
  if (wrongRole) {
    return (
      <main id="main" tabIndex={-1} className="container narrow section">
        <EmptyState icon={ShieldAlert} title="You do not have access to this area"
          action={<a className="btn btn--primary btn--sm" href="#dashboard" onClick={(e) => { e.preventDefault(); navigate("dashboard"); }}>Go to my dashboard</a>}>
          This section is for college administrators. Your account is a student account.
        </EmptyState>
      </main>
    );
  }
  return children;
}
