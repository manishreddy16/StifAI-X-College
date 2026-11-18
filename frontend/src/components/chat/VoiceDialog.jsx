import React, { useEffect, useRef } from "react";
import { AudioLines, MicOff, X } from "lucide-react";

/** Accessible, light-themed live-dictation dialog. Escape or either button stops listening. */
export default function VoiceDialog({ transcript, onStop }) {
  const panelRef = useRef(null);
  const stopRef = useRef(null);
  const onStopRef = useRef(onStop);
  onStopRef.current = onStop;

  useEffect(() => {
    const previous = document.activeElement;
    stopRef.current?.focus();
    const onKey = (event) => {
      if (event.key === "Escape") { event.preventDefault(); onStopRef.current(); return; }
      if (event.key !== "Tab") return;
      const focusable = panelRef.current?.querySelectorAll("button");
      if (!focusable?.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); previous?.focus?.(); };
  }, []);

  return (
    <div className="voice-overlay">
      <div className="voice-panel" ref={panelRef} role="dialog" aria-modal="true" aria-labelledby="voice-title" aria-describedby="voice-help">
        <button type="button" className="icon-btn voice-close" onClick={onStop} aria-label="Stop voice input"><X size={18} /></button>
        <div className="voice-orb-wrap" aria-hidden="true">
          <div className="voice-orb"><AudioLines size={34} /></div>
          <span className="voice-ring ring-one" /><span className="voice-ring ring-two" />
        </div>
        <p className="voice-eyebrow"><span className="voice-live-dot" aria-hidden="true" /> Live voice input</p>
        <h2 id="voice-title">I’m listening</h2>
        <p id="voice-help" className="voice-help">Speak naturally. Pause whenever you need — I’ll keep listening until you stop.</p>
        <div className="voice-wave" aria-hidden="true">
          {Array.from({ length: 33 }, (_, i) => <i key={i} style={{ "--bar": `${10 + ((i * 17 + 9) % 31)}px`, "--delay": `${(i % 11) * -0.09}s` }} />)}
        </div>
        <div className="voice-transcript" aria-live="polite">
          <span>Live transcript</span>
          <p>{transcript.trim() || "Your spoken words will appear here…"}</p>
        </div>
        <button type="button" className="btn btn--primary" ref={stopRef} onClick={onStop}><MicOff size={18} /> Stop listening</button>
        <small>Your text stays in the message box so you can review it before sending.</small>
      </div>
    </div>
  );
}
