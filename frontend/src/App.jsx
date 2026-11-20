import React, { useCallback, useEffect, useRef, useState } from "react";
import Header from "./components/Header.jsx";
import Footer from "./components/Footer.jsx";
import ToastRegion from "./components/Toast.jsx";
import Guard from "./components/Guard.jsx";
import Landing from "./pages/Landing.jsx";
import Assistant from "./pages/Assistant.jsx";
import Auth from "./pages/Auth.jsx";
import Enquiry from "./pages/Enquiry.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Admin from "./pages/Admin.jsx";
import { AuthProvider } from "./lib/auth.jsx";
import { SECTIONS, useRoute } from "./lib/router.js";
import { prefersReducedMotion } from "./lib/config.js";

const KNOWN = new Set(["assistant", "login", "register", "enquiry", "dashboard", "admin"]);
const TITLES = {
  home: "SVCE Tirupati | Admissions enquiry & Campus AI", assistant: "Campus AI assistant | STIF × SVCE", login: "Student sign-in | STIF × SVCE",
  register: "Create account | STIF × SVCE", enquiry: "Admissions enquiry | STIF × SVCE", dashboard: "My dashboard | STIF × SVCE",
  "admin-login": "Staff sign-in | STIF × SVCE", admin: "Administration | STIF × SVCE",
};

export default function App() {
  return <AuthProvider><Shell /></AuthProvider>;
}

function Shell() {
  const route = useRoute();
  const page = KNOWN.has(route.name) ? (route.name === "admin" && route.parts[0] === "login" ? "admin-login" : route.name) : "home";
  const routeKey = `${route.name}/${route.parts.join("/")}`;
  const [initial, setInitial] = useState("");
  const [messages, setMessages] = useState([]); // kept here so the conversation survives navigating elsewhere
  const [toasts, setToasts] = useState([]);
  const pendingScroll = useRef(null);

  const notify = useCallback((message, kind = "success") => {
    const id = `${Date.now()}-${Math.random()}`;
    setToasts((current) => [...current, { id, message, kind }]);
    window.setTimeout(() => setToasts((current) => current.filter((t) => t.id !== id)), 3200);
  }, []);

  useEffect(() => { document.title = TITLES[page] || TITLES.home; }, [page]);

  // After a page switch, either scroll to the requested section or to the top.
  useEffect(() => {
    const behavior = prefersReducedMotion() ? "auto" : "smooth";
    const target = pendingScroll.current;
    pendingScroll.current = null;
    const hashTarget = window.location.hash.slice(1);
    const section = target || (page === "home" && SECTIONS.includes(hashTarget) ? hashTarget : null);
    if (section) document.getElementById(section)?.scrollIntoView({ behavior, block: "start" });
    else window.scrollTo({ top: 0, behavior: "auto" });
  }, [page, routeKey]);

  /** navigate("home" | "assistant" | "explore" | "about" | "dashboard" | "admin/enquiries/5" ...) */
  const navigate = useCallback((target, { replace = false } = {}) => {
    if (SECTIONS.includes(target)) {
      if (page !== "home") {
        pendingScroll.current = target;
        window.location.hash = `#${target}`;
        return;
      }
      window.history.replaceState(null, "", `#${target}`);
      document.getElementById(target)?.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "start" });
      return;
    }
    const hash = `#${target}`;
    if (window.location.hash === hash) { window.scrollTo({ top: 0, behavior: prefersReducedMotion() ? "auto" : "smooth" }); return; }
    if (replace) { window.history.replaceState(null, "", hash); window.dispatchEvent(new HashChangeEvent("hashchange")); }
    else window.location.hash = hash;
  }, [page]);

  const ask = useCallback((question) => { setInitial(question); navigate("assistant"); }, [navigate]);
  const clearInitial = useCallback(() => setInitial(""), []);

  let view;
  switch (page) {
    case "assistant": view = <Assistant key="assistant" messages={messages} setMessages={setMessages} initial={initial} clear={clearInitial} notify={notify} />; break;
    case "login": view = <Auth key="login" mode="login" navigate={navigate} route={route} notify={notify} />; break;
    case "register": view = <Auth key="register" mode="register" navigate={navigate} route={route} notify={notify} />; break;
    case "admin-login": view = <Auth key="admin-login" mode="admin" navigate={navigate} route={route} notify={notify} />; break;
    case "enquiry": view = <Enquiry navigate={navigate} />; break;
    case "dashboard": view = <Guard role="student" loginTarget="login" navigate={navigate}><Dashboard navigate={navigate} notify={notify} /></Guard>; break;
    case "admin": view = <Guard role="admin" loginTarget="admin/login" navigate={navigate}><Admin route={route} navigate={navigate} notify={notify} /></Guard>; break;
    default: view = <Landing navigate={navigate} ask={ask} />;
  }

  return (
    <>
      <a className="skip-link" href="#main" onClick={(e) => { e.preventDefault(); document.getElementById("main")?.focus(); }}>Skip to main content</a>
      <Header page={page} navigate={navigate} notify={notify} />
      {view}
      {page !== "assistant" && page !== "admin" && <Footer navigate={navigate} />}
      <ToastRegion toasts={toasts} />
    </>
  );
}
