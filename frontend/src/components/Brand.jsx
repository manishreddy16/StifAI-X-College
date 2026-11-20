import React from "react";

/**
 * STIF × SVCE wordmark, used identically in the header, footer and chat rail.
 * The mark is a simple CSS/SVG overlap of two forms — it is NOT an official STIF or SVCE logo.
 * `context` adds an optional second line (e.g. "Staff console"); default is "Campus AI".
 */
export default function Brand({ onClick, href = "#home", context = "Campus AI" }) {
  return (
    <a className="brand" href={href} onClick={onClick} aria-label={`STIF × SVCE ${context} — home`}>
      <svg className="brand-mark" viewBox="0 0 44 44" aria-hidden="true">
        <circle cx="16" cy="22" r="12.5" fill="#e2e8f0" stroke="#12213d" strokeWidth="1.6" />
        <circle cx="28" cy="22" r="12.5" fill="#1f8a80" fillOpacity="0.22" stroke="#0f766e" strokeWidth="1.6" />
        <path d="M22 12.8a12.5 12.5 0 0 1 0 18.4 12.5 12.5 0 0 1 0-18.4Z" fill="#0f766e" fillOpacity="0.35" />
      </svg>
      <span className="brand-text">
        <b>STIF<i>×</i>SVCE</b>
        <small>{context}</small>
      </span>
    </a>
  );
}
