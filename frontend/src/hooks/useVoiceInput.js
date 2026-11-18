import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Browser speech-to-text (Web Speech API). Behaviour is unchanged from the original frontend:
 * continuous dictation in en-IN that appends to whatever was typed before recording, auto-restarts
 * after short pauses, and keeps the recognised text when stopped.
 *
 * `toggle(currentText)` starts/stops; recognised text is pushed through `onText`; problems through `onError`.
 */
export default function useVoiceInput({ onText, onError, onStart }) {
  const [state, setState] = useState("idle"); // "idle" | "listening"
  const [transcript, setTranscript] = useState("");
  const recognitionRef = useRef(null);
  const baseRef = useRef("");
  const finalRef = useRef("");
  const stoppedRef = useRef(false);

  useEffect(() => () => {
    stoppedRef.current = true;
    recognitionRef.current?.abort?.();
  }, []);

  const toggle = useCallback((currentText = "") => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      onError?.("Voice input is not supported in this browser. Try a recent version of Chrome or Edge and allow microphone access.");
      return;
    }

    // Clicking again ends the current dictation and keeps all recognised text.
    if (recognitionRef.current && state === "listening") {
      stoppedRef.current = true;
      try { recognitionRef.current.stop(); } catch { /* It may already have stopped. */ }
      setState("idle");
      return;
    }

    const recognition = new SpeechRecognition();
    recognition.lang = "en-IN";
    recognition.interimResults = true;
    recognition.continuous = true;
    recognitionRef.current = recognition;
    baseRef.current = currentText;
    setTranscript(currentText);
    finalRef.current = "";
    stoppedRef.current = false;

    recognition.onstart = () => { setState("listening"); onStart?.(); };
    recognition.onresult = (event) => {
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const piece = event.results[i][0]?.transcript?.trim() || "";
        if (!piece) continue;
        if (event.results[i].isFinal) finalRef.current = `${finalRef.current} ${piece}`.trim();
        else interim = `${interim} ${piece}`.trim();
      }
      // Keep the text typed before recording and append dictated words with normal spaces.
      const combined = [baseRef.current, finalRef.current, interim].filter(Boolean).join(" ").replace(/\s+/g, " ");
      onText?.(combined);
      setTranscript(combined);
    };
    recognition.onerror = (event) => {
      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        onError?.("Microphone access was blocked. Allow microphone access in your browser settings and try again.");
        stoppedRef.current = true;
        setState("idle");
      } else if (event.error !== "no-speech" && event.error !== "aborted") {
        onError?.(`Voice input stopped: ${event.error}. Your recognized text has been kept; you can continue typing.`);
      }
    };
    recognition.onend = () => {
      if (stoppedRef.current) {
        setState("idle");
        recognitionRef.current = null;
        return;
      }
      // Some browsers end a session after a short pause even in continuous mode: restart while in voice mode.
      if (recognitionRef.current === recognition) {
        window.setTimeout(() => {
          if (stoppedRef.current || recognitionRef.current !== recognition) return;
          try { recognition.start(); } catch { /* A browser may still be transitioning states. */ }
        }, 250);
      }
    };
    try {
      recognition.start();
    } catch {
      setState("idle");
      onError?.("Couldn't start voice input. Please click the microphone and try again.");
      recognitionRef.current = null;
    }
  }, [state, onText, onError, onStart]);

  return { state, transcript, toggle };
}
