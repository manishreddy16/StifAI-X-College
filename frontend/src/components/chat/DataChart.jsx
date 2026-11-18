import React, { useState } from "react";
import { BarChart3, ChevronDown } from "lucide-react";

// Numeric-table visualisation — data extraction logic unchanged from the original frontend.
export default function DataChart({ text }) {
  const [open, setOpen] = useState(false);
  const rows = String(text || "").split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.includes("|") && line.split("|").length >= 3)
    .map((line) => line.replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim()))
    .filter((row) => !row.every((cell) => /^:?-{2,}:?$/.test(cell)));
  if (rows.length < 3) return null;
  const body = rows.slice(1).filter((row) => row.length >= 2);
  const data = body.map((row) => {
    const raw = (row[1] || "").replace(/,/g, "");
    const match = raw.match(/-?\d+(?:\.\d+)?/);
    return match ? { label: row[0].replace(/\*\*/g, ""), value: Number(match[0]), display: row[1] } : null;
  }).filter(Boolean).filter((item) => Number.isFinite(item.value) && item.value >= 0).slice(0, 8);
  if (data.length < 2 || data.every((item) => item.value === 0)) return null;
  const max = Math.max(...data.map((item) => item.value), 1);
  return (
    <div className="chart-panel">
      <button className="chart-toggle" type="button" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <BarChart3 size={16} /> {open ? "Hide chart" : "Visualize table"}
        <ChevronDown size={16} className={open ? "chev is-open" : "chev"} />
      </button>
      {open && (
        <div className="mini-chart">
          <div className="chart-title">Values from this answer</div>
          <div role="img" aria-label="Bar chart generated from the numeric values in the answer table">
            {data.map((item) => (
              <div className="chart-row" key={item.label}>
                <div className="chart-label" title={item.label}>{item.label}</div>
                <div className="chart-track"><div className="chart-bar" style={{ width: `${Math.max(2, item.value / max * 100)}%` }} /></div>
                <div className="chart-value">{item.display}</div>
              </div>
            ))}
          </div>
          <small>Visualisation uses numeric values from the displayed answer; verify the source figures before relying on them.</small>
        </div>
      )}
    </div>
  );
}
