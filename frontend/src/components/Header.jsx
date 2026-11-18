import React, { useEffect, useRef, useState } from "react";
import { ArrowRight, Menu, X } from "lucide-react";
import Brand from "./Brand.jsx";

export default function Header({ page, navigate }) {
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const toggleRef = useRef(null);
  const panelRef = useRef(null);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // Escape closes the mobile menu; lock page scroll while it is open.
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event) => {
      if (event.key === "Escape") { setOpen(false); toggleRef.current?.focus(); return; }
      if (event.key !== "Tab") return;
      const links = panelRef.current?.querySelectorAll("a");
      if (!links?.length) return;
      const first = links[0];
      const last = links[links.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.removeEventListener("keydown", onKey); document.body.style.overflow = previous; };
  }, [open]);

  useEffect(() => {
    if (open) panelRef.current?.querySelector("a")?.focus();
  }, [open]);

  // Close the menu if the viewport grows to desktop width.
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 861px)");
    const onChange = () => { if (mq.matches) setOpen(false); };
    mq.addEventListener?.("change", onChange);
    return () => mq.removeEventListener?.("change", onChange);
  }, []);

  const go = (target) => (event) => {
    event.preventDefault();
    const wasOpen = open;
    setOpen(false);
    navigate(target);
    if (wasOpen) window.requestAnimationFrame(() => toggleRef.current?.focus());
  };

  return (
    <header className={`header ${scrolled ? "is-scrolled" : ""}`}>
      <div className={`container header-inner ${page === "assistant" ? "container--wide" : ""}`}>
        <Brand onClick={go("home")} />
        <nav className="nav" aria-label="Primary">
          <a className="nav-link" href="#home" aria-current={page === "home" ? "page" : undefined} onClick={go("home")}>Home</a>
          <a className="nav-link" href="#explore" onClick={go("explore")}>Explore</a>
          <a className="nav-link" href="#about" onClick={go("about")}>About</a>
          <a className="btn btn--primary btn--sm" href="#assistant" aria-current={page === "assistant" ? "page" : undefined} onClick={go("assistant")}>
            Open assistant <ArrowRight size={16} className="btn-arrow" />
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
        <a href="#home" onClick={go("home")}>Home <ArrowRight size={20} /></a>
        <a href="#explore" onClick={go("explore")}>Explore <ArrowRight size={20} /></a>
        <a href="#about" onClick={go("about")}>About <ArrowRight size={20} /></a>
        <a className="btn btn--primary" href="#assistant" onClick={go("assistant")}>Open the AI assistant <ArrowRight size={18} /></a>
        <small>Answers come from available SVCE information. Verify important details with official sources.</small>
      </nav>
    </header>
  );
}
