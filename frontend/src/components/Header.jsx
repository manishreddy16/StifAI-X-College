import React, { useEffect, useRef, useState } from "react";
import { ArrowRight, LogOut, Menu, X } from "lucide-react";
import Brand from "./Brand.jsx";
import { useAuth } from "../lib/auth.jsx";

/**
 * Role-specific navigation (this is the ONLY place the app offers Sign out):
 *  - admin session / admin-login page: staff header only (no public links)
 *  - student session: Home, Dashboard, AI assistant, Sign out + "Admissions enquiry" button
 *  - public visitor:  Home, College info, AI assistant, How it works, Student login + "Admissions enquiry" button
 */
const MENU_QUERY = "(min-width: 961px)"; // keep in sync with the 960px breakpoint in components.css

export default function Header({ page, navigate, notify }) {
  const { user, logout } = useAuth();
  const isAdmin = user?.role === "admin";
  const isStaffArea = isAdmin || page === "admin-login" || page === "admin";
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const toggleRef = useRef(null);
  const panelRef = useRef(null);

  // Navigate home FIRST so a protected page unmounts before the session disappears (otherwise its guard would redirect to login).
  const signOut = async () => { setOpen(false); navigate("home"); await logout(); notify?.("You have been signed out."); };

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // Escape closes the mobile menu, Tab is trapped inside it; page scroll is locked while open.
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event) => {
      if (event.key === "Escape") { setOpen(false); toggleRef.current?.focus(); return; }
      if (event.key !== "Tab") return;
      const items = panelRef.current?.querySelectorAll("a, button");
      if (!items?.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.removeEventListener("keydown", onKey); document.body.style.overflow = previous; };
  }, [open]);

  useEffect(() => { if (open) panelRef.current?.querySelector("a, button")?.focus(); }, [open]);

  // Close the menu when the viewport grows to desktop width or the role/page changes.
  useEffect(() => {
    const mq = window.matchMedia(MENU_QUERY);
    const onChange = () => { if (mq.matches) setOpen(false); };
    mq.addEventListener?.("change", onChange);
    return () => mq.removeEventListener?.("change", onChange);
  }, []);
  useEffect(() => { setOpen(false); }, [page, user?.role]);

  const go = (target) => (event) => {
    event.preventDefault();
    const wasOpen = open;
    setOpen(false);
    navigate(target);
    if (wasOpen) window.requestAnimationFrame(() => toggleRef.current?.focus());
  };

  const wide = page === "assistant" || page === "admin" ? "container--wide" : "";

  // ---------- Staff header: no public navigation ----------
  if (isStaffArea) {
    return (
      <header className={`header ${scrolled ? "is-scrolled" : ""}`}>
        <div className={`container header-inner ${wide}`}>
          <Brand context="Staff console" href={isAdmin ? "#admin" : "#admin/login"} onClick={go(isAdmin ? "admin" : "admin/login")} />
          <div className="nav nav--staff">
            {isAdmin ? (
              <>
                <span className="header-who" title={user.email}>{user.full_name}</span>
                <button type="button" className="btn btn--secondary btn--sm" onClick={signOut}><LogOut size={16} /> Sign out</button>
              </>
            ) : (
              <a className="nav-link" href="#home" onClick={go("home")}>Back to main site</a>
            )}
          </div>
        </div>
      </header>
    );
  }

  // ---------- Student / public header ----------
  const links = user
    ? [
        { to: "home", label: "Home", page: "home" },
        { to: "dashboard", label: "Dashboard", page: "dashboard" },
        { to: "assistant", label: "AI assistant", page: "assistant" },
      ]
    : [
        { to: "home", label: "Home", page: "home" },
        { to: "explore", label: "College info" },
        { to: "assistant", label: "AI assistant", page: "assistant" },
        { to: "about", label: "How it works" },
        { to: "login", label: "Student login", page: "login" },
      ];
  const current = (item) => (item.page && item.page === page ? "page" : undefined);

  return (
    <header className={`header ${scrolled ? "is-scrolled" : ""}`}>
      <div className={`container header-inner ${wide}`}>
        <Brand onClick={go("home")} />
        <nav className="nav" aria-label="Primary">
          {links.map((item) => (
            <a key={item.to} className="nav-link" href={`#${item.to}`} aria-current={current(item)} onClick={go(item.to)}>{item.label}</a>
          ))}
          {user && <button type="button" className="nav-link" onClick={signOut}>Sign out</button>}
          <a className="btn btn--primary btn--sm" href="#enquiry" aria-current={page === "enquiry" ? "page" : undefined} onClick={go("enquiry")}>
            Admissions enquiry <ArrowRight size={16} className="btn-arrow" />
          </a>
        </nav>
        <button
          ref={toggleRef} type="button" className="icon-btn menu-toggle" aria-label={open ? "Close menu" : "Open menu"}
          aria-expanded={open} aria-controls="mobile-menu" onClick={() => setOpen((value) => !value)}
        >
          {open ? <X size={22} /> : <Menu size={22} />}
        </button>
      </div>
      <nav id="mobile-menu" ref={panelRef} className={`mobile-panel ${open ? "is-open" : ""}`} aria-label="Mobile navigation" aria-hidden={!open}>
        {links.map((item) => (
          <a key={item.to} href={`#${item.to}`} aria-current={current(item)} tabIndex={open ? 0 : -1} onClick={go(item.to)}>{item.label} <ArrowRight size={20} /></a>
        ))}
        {user && <button type="button" className="mobile-link" tabIndex={open ? 0 : -1} onClick={signOut}>Sign out <LogOut size={20} /></button>}
        <a className="btn btn--primary" href="#enquiry" tabIndex={open ? 0 : -1} onClick={go("enquiry")}>Start admissions enquiry <ArrowRight size={18} /></a>
        <small>Answers come from available SVCE information. Verify important details with official sources.</small>
      </nav>
    </header>
  );
}
