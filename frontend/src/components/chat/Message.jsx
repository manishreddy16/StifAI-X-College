import React, { useState } from "react";
import { ArrowRight, Check, Copy, Sparkles } from "lucide-react";
import { MarkdownAnswer } from "./Markdown.jsx";
import DataChart from "./DataChart.jsx";
import SourceCards from "./SourceCards.jsx";

export default function Message({ message, isLast, busy, onFollowUp, notify }) {
  const [copied, setCopied] = useState(false);

  if (message.role === "user") {
    return (
      <div className="msg msg--user" data-last={isLast || undefined}>
        <div className="bubble-user"><span className="sr-only">You: </span>{message.content}</div>
      </div>
    );
  }

  async function copy() {
    try {
      let copied = false;
      if (navigator.clipboard?.writeText && window.isSecureContext) {
        try {
          await navigator.clipboard.writeText(message.content);
          copied = true;
        } catch { /* Fall back for browsers that reject clipboard permissions. */ }
      }
      if (!copied) {
        const field = document.createElement("textarea");
        field.value = message.content;
        field.setAttribute("readonly", "");
        field.style.position = "fixed";
        field.style.opacity = "0";
        document.body.appendChild(field);
        try {
          field.select();
          copied = document.execCommand("copy");
        } finally {
          field.remove();
        }
        if (!copied) throw new Error("Clipboard copy was not available");
      }
      setCopied(true);
      notify?.("Answer copied to clipboard");
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      notify?.("Couldn't copy — select the text and copy it manually.", "error");
    }
  }

  return (
    <div className="msg msg--ai" data-last={isLast || undefined}>
      <span className="avatar" aria-hidden="true"><Sparkles size={17} /></span>
      <div className="msg-main">
        <h2 className="msg-label">Campus AI <span className="sr-only">answer</span></h2>
        <div className="answer-surface">
          <MarkdownAnswer text={message.content} />
          <DataChart text={message.content} />
        </div>
        <p className="answer-note" role="note">
          {message.mode === "llm_with_user_document"
            ? "This response used your uploaded document, which has not been independently verified."
            : message.sources?.length
              ? "Links below are supporting references; their contents and the answer have not been independently verified."
              : "No supporting source links were returned for this answer."}
        </p>
        <SourceCards sources={message.sources} />
        <div className="msg-actions">
          <button type="button" className="action-btn" onClick={copy}>
            {copied ? <Check size={15} /> : <Copy size={15} />} {copied ? "Copied" : "Copy"}
          </button>
        </div>
        {message.followUps?.length > 0 && (
          <div className="followups" role="group" aria-label="Suggested follow-up questions">
            <div className="followups-title">Keep exploring</div>
            <div className="followups-list">
              {message.followUps.map((followUp) => (
                <button type="button" key={followUp} onClick={() => onFollowUp(followUp)} disabled={busy}>
                  <span>{followUp}</span><ArrowRight size={14} />
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
