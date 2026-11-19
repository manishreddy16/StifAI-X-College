import React, { useId } from "react";
import { CircleAlert, CircleCheck, Info, Loader2 } from "lucide-react";
import { STATUS_LABELS } from "../../lib/format.js";

/** Labelled form control. `as` = "input" | "textarea" | "select". Errors are announced to screen readers. */
export function Field({ label, error, hint, as = "input", children, className = "", ...props }) {
  const id = useId();
  const describedBy = [hint ? `${id}-hint` : null, error ? `${id}-err` : null].filter(Boolean).join(" ") || undefined;
  const Control = as;
  return (
    <div className={`field ${error ? "has-error" : ""} ${className}`}>
      <label htmlFor={id}>{label}{props.required && <span className="req" aria-hidden="true"> *</span>}</label>
      <Control id={id} className="control" aria-invalid={error ? "true" : undefined} aria-describedby={describedBy} {...props}>
        {children}
      </Control>
      {hint && !error && <p id={`${id}-hint`} className="field-hint">{hint}</p>}
      {error && <p id={`${id}-err`} className="field-error" role="alert"><CircleAlert size={15} /> {error}</p>}
    </div>
  );
}

export function Alert({ kind = "info", title, children, onClose }) {
  const Icon = kind === "error" ? CircleAlert : kind === "success" ? CircleCheck : Info;
  return (
    <div className={`alert alert--${kind}`} role={kind === "error" ? "alert" : "status"}>
      <Icon size={20} />
      <div>{title && <b>{title}</b>}{children && <p>{children}</p>}</div>
      {onClose && <button type="button" className="alert-x" onClick={onClose} aria-label="Dismiss">×</button>}
    </div>
  );
}

export function Spinner({ label = "Loading…" }) {
  return <div className="loading" role="status"><Loader2 size={22} className="spin" /> <span>{label}</span></div>;
}

export function EmptyState({ icon: Icon, title, children, action }) {
  return (
    <div className="state-empty">
      {Icon && <span className="icon-tile icon-tile--sage"><Icon size={22} /></span>}
      <h3>{title}</h3>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}

export function StatusBadge({ status }) {
  return <span className={`badge badge--${status}`}>{STATUS_LABELS[status] || status}</span>;
}

/** Shared page title block so student + admin pages look like one product. */
export function PageHead({ eyebrow, title, children, actions }) {
  return (
    <div className="page-head">
      <div>
        {eyebrow && <span className="eyebrow">{eyebrow}</span>}
        <h1>{title}</h1>
        {children && <p>{children}</p>}
      </div>
      {actions && <div className="page-head-actions">{actions}</div>}
    </div>
  );
}
