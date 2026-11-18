import React from "react";
import { ArrowUpRight, Link2 } from "lucide-react";

/** Normalise the backend `sources` array ([{title,url}]) into safe, unique http(s) links. */
export function normaliseSources(sources) {
  if (!Array.isArray(sources)) return [];
  const seen = new Set();
  const out = [];
  for (const item of sources) {
    const url = String(item?.url || "").trim();
    let parsed;
    try { parsed = new URL(url); } catch { continue; }
    if (!/^https?:$/.test(parsed.protocol) || seen.has(url)) continue;
    seen.add(url);
    const host = parsed.hostname.replace(/^www\./, "");
    const path = parsed.pathname === "/" ? "" : parsed.pathname;
    out.push({ url, title: String(item?.title || "").trim() || host, host, display: `${host}${path}` });
  }
  return out;
}

export default function SourceCards({ sources }) {
  const list = normaliseSources(sources);
  if (!list.length) return null;
  return (
    <section className="sources" aria-label={`Sources (${list.length})`}>
      <h3 className="sources-title"><Link2 size={14} /> Sources <span>{list.length}</span></h3>
      <ul className="sources-grid">
        {list.map((source, i) => (
          <li key={source.url}>
            <a className="source-card" href={source.url} target="_blank" rel="noreferrer" style={{ "--i": i }}>
              <span className="source-index" aria-hidden="true">{i + 1}</span>
              <span className="source-meta">
                <b>{source.title}</b>
                <small>{source.display}</small>
              </span>
              <ArrowUpRight size={16} aria-hidden="true" />
              <span className="sr-only"> (opens in a new tab)</span>
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}
