import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowRight, ArrowUp, CircleAlert, FileText, LoaderCircle, Mic, MicOff, Paperclip, Plus, RotateCcw, ShieldCheck, Sparkles, X,
} from "lucide-react";
import { API, MAX_DOCUMENT_CHARS, MAX_MESSAGE_CHARS, QUESTIONS, prefersReducedMotion } from "../lib/config.js";
import { getFollowUpQuestions } from "../lib/followups.js";
import useVoiceInput from "../hooks/useVoiceInput.js";
import Message from "../components/chat/Message.jsx";
import VoiceDialog from "../components/chat/VoiceDialog.jsx";

const ACCEPT = ".txt,.md,.csv,.json,.pdf,.docx,.png,.jpg,.jpeg,.webp,text/plain,text/markdown,text/csv,application/json,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,image/png,image/jpeg,image/webp";

async function parseResponse(response, operation) {
  let body = {};
  try { body = await response.json(); } catch { /* Non-JSON error response. */ }
  if (response.ok) return body;
  const detail = body?.detail;
  const message = typeof detail === "string"
    ? detail
    : Array.isArray(detail)
      ? detail.map((item) => item.msg || "Invalid request").join(" ")
      : `${operation} failed (${response.status}).`;
  const kind = [400, 413, 415, 422].includes(response.status)
    ? "validation"
    : response.status >= 500 ? "server" : "request";
  throw Object.assign(new Error(message), { kind, status: response.status });
}

function networkError(operation) {
  return Object.assign(
    new Error(`Couldn't reach the Campus AI backend while ${operation}. Check that the backend is running and try again.`),
    { kind: "network" },
  );
}

export default function Assistant({ messages, setMessages, initial, clear, notify }) {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [chatError, setChatError] = useState(null);   // failed chat request (retryable)
  const [notice, setNotice] = useState("");           // file / voice problems
  const [attachment, setAttachment] = useState(null);
  const [uploading, setUploading] = useState("");
  const [backendStatus, setBackendStatus] = useState({ state: "checking" });
  const [menuOpen, setMenuOpen] = useState(false);
  const fileInputRef = useRef(null);
  const inputRef = useRef(null);
  const threadRef = useRef(null);
  const attachRef = useRef(null);
  const plusRef = useRef(null);
  const lastRequestRef = useRef(null);

  useEffect(() => {
    let active = true;
    const refreshStatus = async () => {
      try {
        const response = await fetch(`${API}/health`);
        const health = await parseResponse(response, "Status check");
        if (active) setBackendStatus({
          state: health.index_ready ? "ready" : "index-unavailable",
          chunks: health.chunks_loaded,
        });
      } catch {
        if (active) setBackendStatus({ state: "offline" });
      }
    };
    refreshStatus();
    const timer = window.setInterval(refreshStatus, 30000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  const voice = useVoiceInput({
    onText: setInput,
    onError: setNotice,
    onStart: () => setNotice(""),
  });
  const listening = voice.state === "listening";
  const stopVoice = useCallback(() => voice.toggle(), [voice]);

  // Keep the newest content in view: new assistant answers start at their top, everything else follows the bottom.
  useEffect(() => {
    const thread = threadRef.current;
    if (!thread) return;
    const behavior = prefersReducedMotion() ? "auto" : "smooth";
    if (messages.length === 0 && !loading && !chatError) { thread.scrollTo({ top: 0 }); return; }
    const last = messages[messages.length - 1];
    const target = !loading && !chatError && last?.role === "assistant" ? thread.querySelector("[data-last]") : null;
    thread.scrollTo({ top: target ? Math.max(0, target.offsetTop - 12) : thread.scrollHeight, behavior });
  }, [messages, loading, chatError]);

  // Autosize the composer textarea.
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 168)}px`;
  }, [input]);

  // Close the attach popover on outside click / Escape.
  useEffect(() => {
    if (!menuOpen) return undefined;
    const onDown = (event) => { if (attachRef.current && !attachRef.current.contains(event.target)) setMenuOpen(false); };
    const onKey = (event) => { if (event.key === "Escape") { setMenuOpen(false); plusRef.current?.focus(); } };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("pointerdown", onDown); document.removeEventListener("keydown", onKey); };
  }, [menuOpen]);

  // Apply a suggested question chosen on the landing page.
  useEffect(() => {
    if (initial) {
      setInput(initial);
      clear();
      inputRef.current?.focus();
    }
  }, [initial, clear]);

  async function runRequest(payload, question) {
    lastRequestRef.current = { payload, question };
    setChatError(null);
    setLoading(true);
    try {
      let response;
      try {
        response = await fetch(`${API}/api/v1/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
      } catch { throw networkError("sending your question"); }
      const data = await parseResponse(response, "Chat request");
      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          content: data.answer || "I couldn't produce an answer.",
          sources: Array.isArray(data.sources) ? data.sources : [],
          mode: data.mode,
          followUps: getFollowUpQuestions(question, data.answer || ""),
        },
      ]);
    } catch (err) {
      setChatError({
        kind: err?.kind || "request",
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setLoading(false);
    }
  }

  function send(question = input) {
    const typedQuestion = String(question).trim();
    if ((!typedQuestion && !attachment) || loading) return;
    const q = typedQuestion || `Please summarize the attached file: ${attachment?.name || "uploaded file"}`;
    if (q.length > MAX_MESSAGE_CHARS) {
      setNotice(`Your question is longer than ${MAX_MESSAGE_CHARS.toLocaleString()} characters. Shorten it and try again.`);
      inputRef.current?.focus();
      return;
    }
    const payload = { message: q };
    if (attachment?.text) {
      if (attachment.text.length > MAX_DOCUMENT_CHARS) {
        setNotice("This document is too long to send. No text was discarded; split it into smaller files and try again.");
        return;
      }
      payload.attachment_text = attachment.text;
      payload.attachment_name = attachment.name;
    }
    setInput("");
    setAttachment(null);
    setMenuOpen(false);
    setNotice("");
    setMessages((current) => [...current, { role: "user", content: q }]);
    runRequest(payload, q);
    inputRef.current?.focus();
  }

  function retry() {
    if (!lastRequestRef.current || loading) return;
    runRequest(lastRequestRef.current.payload, lastRequestRef.current.question);
  }

  function newConversation() {
    if (listening) voice.toggle();
    setMessages([]);
    setChatError(null);
    setNotice("");
    setInput("");
    setAttachment(null);
    lastRequestRef.current = null;
    inputRef.current?.focus();
  }

  async function handleFile(file) {
    if (!file) return;
    const allowed = /\.(txt|md|csv|json|pdf|docx|png|jpe?g|webp)$/i.test(file.name);
    if (!allowed) { setNotice("Unsupported file type. Upload TXT, MD, CSV, JSON, PDF, DOCX, PNG, JPG, or WEBP."); return; }
    if (file.size > 10 * 1024 * 1024) { setNotice("Please choose a file smaller than 10 MB."); return; }
    setMenuOpen(false);
    setNotice("");
    setUploading(file.name);
    try {
      const form = new FormData();
      form.append("file", file);
      let response;
      try { response = await fetch(`${API}/api/v1/files/extract`, { method: "POST", body: form }); }
      catch { throw networkError("reading your file"); }
      const data = await parseResponse(response, "File extraction");
      if (data.truncated || String(data.text || "").length > MAX_DOCUMENT_CHARS) {
        throw new Error("The extracted text is too long to send. No text was discarded; split the document into smaller files and try again.");
      }
      if (!String(data.text || "").trim()) throw new Error("No readable text was found. Scanned PDFs may need OCR before they can be read.");
      setAttachment({ name: file.name, size: file.size, text: data.text, fileType: data.file_type || "document" });
      notify?.("File ready to include with your question");
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "I couldn't process this file.");
    } finally {
      setUploading("");
    }
  }

  const canSend = !loading && !uploading && (input.trim() || attachment);
  const empty = messages.length === 0;
  const retryableError = chatError && ["network", "server"].includes(chatError.kind);
  const statusLabel = backendStatus.state === "checking" ? "Checking SVCE index…"
    : backendStatus.state === "ready" ? "SVCE index available · answers are not independently verified"
      : backendStatus.state === "index-unavailable" ? "SVCE index unavailable"
        : "Backend status unavailable";

  return (
    <main id="main" tabIndex={-1} className="assistant">
      <div className="app-shell">
        <aside className="rail" aria-label="Conversation tools">
          <div className="rail-head">
            <span className="rail-mark"><Sparkles size={18} /></span>
            <div><b>Campus assistant</b><small>SVCE Tirupati</small></div>
          </div>
          <button type="button" className="btn btn--primary btn--sm rail-new" onClick={newConversation}>
            <Plus size={17} /> New conversation
          </button>
          <p className="rail-title" id="rail-topics-label">Explore topics</p>
          <ul className="rail-topics" aria-labelledby="rail-topics-label">
            {QUESTIONS.map(({ icon: Icon, label, q }) => (
              <li key={label}>
                <button type="button" className="rail-topic" onClick={() => send(q)} disabled={loading}>
                  <Icon size={18} /><span>{label}</span><ArrowRight size={15} />
                </button>
              </li>
            ))}
          </ul>
          <p className="rail-note"><ShieldCheck size={18} /> Answers may use available indexed content. Verify important details with official sources.</p>
        </aside>

        <section className="chat" aria-label="Conversation">
          <div className="chat-bar">
            <div className="chat-bar-title">
              <h1>Campus AI</h1>
              <span className={`status-pill status-pill--${backendStatus.state}`} role="status" aria-live="polite">
                <i aria-hidden="true" /> {statusLabel}
              </span>
            </div>
            <button type="button" className="icon-btn" onClick={newConversation} aria-label="New conversation" data-tip="New conversation" data-tip-pos="bottom">
              <Plus size={20} />
            </button>
          </div>

          <div className="thread" ref={threadRef} role="log" aria-live="polite" aria-relevant="additions" aria-label="Messages" tabIndex={-1} aria-busy={loading}>
            <div className="thread-inner">
              {empty && !loading && (
                <div className="empty">
                  <span className="empty-mark"><Sparkles size={26} /></span>
                  <h2>How can I help today?</h2>
                  <p>Ask about SVCE admissions, academics, placements and campus information — or pick a question to start.</p>
                  <div className="empty-grid">
                    {QUESTIONS.map(({ icon: Icon, label, q }, i) => (
                      <button type="button" key={label} className="card card--interactive empty-card" style={{ "--i": i }} onClick={() => send(q)} disabled={loading}>
                        <span className={`icon-tile ${i % 3 === 1 ? "icon-tile--sage" : i % 3 === 2 ? "icon-tile--teal" : ""}`}><Icon size={20} /></span>
                        <span className="empty-card-text"><b>{label}</b><small>{q}</small></span>
                        <ArrowRight size={16} className="empty-card-go" />
                      </button>
                    ))}
                  </div>
                  <ul className="empty-tips">
                    <li><Paperclip size={15} /> Attach a document</li>
                    <li><Mic size={15} /> Dictate your question</li>
                    <li><ShieldCheck size={15} /> Links when available</li>
                  </ul>
                </div>
              )}

              {messages.map((message, index) => (
                <Message
                  key={index} message={message} isLast={index === messages.length - 1} busy={loading}
                  onFollowUp={send} notify={notify}
                />
              ))}

              {loading && (
                <div className="msg msg--ai msg--loading" role="status">
                  <span className="avatar avatar--pulse" aria-hidden="true"><Sparkles size={17} /></span>
                  <div className="msg-main">
                    <div className="answer-surface loading-surface">
                      <div className="loading-line"><span className="typing-dots" aria-hidden="true"><i /><i /><i /></span> {attachment ? "Reading your document and checking SVCE information…" : "Finding relevant SVCE information…"}</div>
                      <div className="skeleton" aria-hidden="true"><i /><i /><i /></div>
                    </div>
                  </div>
                </div>
              )}

              {chatError && !loading && (
                <div className="error-card" role="alert">
                  <CircleAlert size={22} />
                  <div className="error-body">
                    <b>{chatError.kind === "validation" ? "Please check your request" : chatError.kind === "server" ? "The backend could not complete this request" : chatError.kind === "request" ? "The request could not be completed" : "Couldn't reach the Campus AI backend"}</b>
                    <p>{chatError.message}</p>
                    <div className="error-actions">
                      {retryableError && <button type="button" className="btn btn--teal btn--sm" onClick={retry}><RotateCcw size={16} /> Try again</button>}
                      <button type="button" className="btn btn--quiet btn--sm" onClick={() => setChatError(null)}>Dismiss</button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>

          <div className="dock">
            <div className="dock-inner">
              {notice && (
                <div className="notice" role="alert">
                  <CircleAlert size={17} /><span>{notice}</span>
                  <button type="button" onClick={() => setNotice("")} aria-label="Dismiss message"><X size={16} /></button>
                </div>
              )}
              {uploading && (
                <div className="attachment-pill is-busy" role="status">
                  <LoaderCircle size={17} className="spin" />
                  <span><b>{uploading}</b><small>Reading file…</small></span>
                </div>
              )}
              {attachment && (
                <div className="attachment-pill">
                  <FileText size={18} />
                  <span><b>{attachment.name}</b><small>{Math.max(1, Math.round(attachment.size / 1024))} KB · extracted text ready to include</small></span>
                  <button type="button" onClick={() => setAttachment(null)} aria-label={`Remove attachment ${attachment.name}`}><X size={16} /></button>
                </div>
              )}
              <form className="composer" onSubmit={(event) => { event.preventDefault(); send(); }}>
                <div className="attach-control" ref={attachRef}>
                  <button type="button" ref={plusRef} className="icon-btn" aria-label="Attach a file" aria-haspopup="true" aria-expanded={menuOpen} data-tip="Attach a file" onClick={() => setMenuOpen((v) => !v)}>
                    <Plus size={20} />
                  </button>
                  {menuOpen && (
                    <div className="upload-menu">
                      <button type="button" onClick={() => fileInputRef.current?.click()}>
                        <span className="icon-tile icon-tile--sage"><Paperclip size={18} /></span>
                        <span><b>Attach a file</b><small>PDF, DOCX, images, TXT, CSV · up to 10 MB</small></span>
                      </button>
                      <p>PDF, DOCX, TXT, MD, CSV, JSON, PNG, JPG, WEBP · up to 10 MB. Extracted text is sent with your question to the configured AI service and is not added to the SVCE index.</p>
                    </div>
                  )}
                  <input ref={fileInputRef} type="file" accept={ACCEPT} hidden onChange={(event) => { handleFile(event.target.files?.[0]); event.target.value = ""; }} />
                </div>
                <label className="sr-only" htmlFor="composer-input">Ask the Campus AI assistant</label>
                <textarea
                  id="composer-input" ref={inputRef} value={input} rows={1} maxLength={MAX_MESSAGE_CHARS}
                  aria-describedby="composer-help"
                  onChange={(event) => setInput(event.target.value)}
                  onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); send(); } }}
                  placeholder="Ask anything about SVCE…"
                />
                <button
                  type="button" className={`icon-btn ${listening ? "is-listening" : ""}`} onClick={() => voice.toggle(input)} disabled={loading || Boolean(uploading)}
                  aria-label={listening ? "Stop voice input" : "Use voice input"} data-tip={listening ? "Stop listening" : "Speak your question"}
                >
                  {listening ? <MicOff size={19} /> : <Mic size={19} />}
                </button>
                <button type="submit" className="send-btn" disabled={!canSend} aria-label={loading ? "Sending message" : "Send message"} data-tip={loading ? "Sending" : "Send"}><ArrowUp size={20} /></button>
              </form>
              <div className="dock-foot" id="composer-help">
                <span><ShieldCheck size={14} /> Answers and linked sources are not independently verified.</span>
                <span className="dock-keys">{input.length}/{MAX_MESSAGE_CHARS} · Enter to send · Shift + Enter for a new line</span>
              </div>
            </div>
          </div>
        </section>
      </div>
      {listening && <VoiceDialog transcript={voice.transcript} onStop={stopVoice} />}
    </main>
  );
}
