import React, { useCallback, useEffect, useRef, useState } from "react";
import Header from "./components/Header.jsx";
import Footer from "./components/Footer.jsx";
import ToastRegion from "./components/Toast.jsx";
import Landing from "./pages/Landing.jsx";
import Assistant from "./pages/Assistant.jsx";
import { prefersReducedMotion } from "./lib/config.js";

const SECTIONS = ["explore", "about"];
const pageFromHash = () => (window.location.hash === "#assistant" ? "assistant" : "home");

export default function App() {
  const [page, setPage] = useState(pageFromHash);
  const [initial, setInitial] = useState("");
  const [messages, setMessages] = useState([]); // kept here so the conversation survives navigating to the landing page
  const [toasts, setToasts] = useState([]);
  const pendingScroll = useRef(null);

  const notify = useCallback((message, kind = "success") => {
    const id = `${Date.now()}-${Math.random()}`;
    setToasts((current) => [...current, { id, message, kind }]);
    window.setTimeout(() => setToasts((current) => current.filter((t) => t.id !== id)), 3200);
  }, []);

  useEffect(() => {
    const onHash = () => setPage(pageFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  // Document title follows the page (helps tabs, history and screen readers).
  useEffect(() => {
    document.title = page === "assistant" ? "Campus AI assistant | STIF × SVCE" : "STIF × SVCE | Campus AI";
  }, [page]);

  // After a page switch, either scroll to the requested section or to the top.
  useEffect(() => {
    const behavior = prefersReducedMotion() ? "auto" : "smooth";
    const target = pendingScroll.current;
    pendingScroll.current = null;
    const hashTarget = window.location.hash.slice(1);
    const section = target || (SECTIONS.includes(hashTarget) ? hashTarget : null);
    if (section) document.getElementById(section)?.scrollIntoView({ behavior, block: "start" });
    else window.scrollTo({ top: 0, behavior: "auto" });
  }, [page]);

  /** navigate("home" | "assistant" | "explore" | "about") */
  const navigate = useCallback((target) => {
    if (SECTIONS.includes(target)) {
      if (pageFromHash() === "assistant" || page === "assistant") {
        pendingScroll.current = target;
        window.location.hash = `#${target}`;
        setPage("home");
        return;
      }
      window.history.replaceState(null, "", `#${target}`);
      document.getElementById(target)?.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "start" });
      return;
    }
    const next = target === "assistant" ? "assistant" : "home";
    const hash = next === "assistant" ? "#assistant" : "#home";
    if (window.location.hash !== hash) window.location.hash = hash;
    if (next === page) window.scrollTo({ top: 0, behavior: prefersReducedMotion() ? "auto" : "smooth" });
    setPage(next);
  }, [page]);

  const ask = useCallback((question) => { setInitial(question); navigate("assistant"); }, [navigate]);
  const clearInitial = useCallback(() => setInitial(""), []);

  return (
    <>
      <a className="skip-link" href="#main" onClick={(e) => { e.preventDefault(); document.getElementById("main")?.focus(); }}>Skip to main content</a>
      <Header page={page} navigate={navigate} />
      {page === "home"
        ? <Landing navigate={navigate} ask={ask} />
        : <Assistant key="assistant" messages={messages} setMessages={setMessages} initial={initial} clear={clearInitial} notify={notify} />}
      {page === "home" && <Footer navigate={navigate} />}
      <ToastRegion toasts={toasts} />
    </>
  );
}
