import React from "react";

/** STIF × SVCE wordmark. The mark is a CSS-drawn overlap (two linked forms) — not an official logo. */
export default function Brand({ onClick, href = "#home" }) {
  return (
    <a className="brand" href={href} onClick={onClick} aria-label="STIF × SVCE Campus AI — home">
      <svg className="brand-mark" viewBox="0 0 44 44" aria-hidden="true">
        <circle cx="16" cy="22" r="12.5" fill="#efe3cb" stroke="#16233b" strokeWidth="1.6" />
        <circle cx="28" cy="22" r="12.5" fill="#2c8379" fillOpacity="0.22" stroke="#1e6e68" strokeWidth="1.6" />
        <path d="M22 12.8a12.5 12.5 0 0 1 0 18.4 12.5 12.5 0 0 1 0-18.4Z" fill="#1e6e68" fillOpacity="0.35" />
      </svg>
      <span className="brand-text">
        <b>STIF<i>×</i>SVCE</b>
        <small>Campus AI</small>
      </span>
    </a>
  );
}
