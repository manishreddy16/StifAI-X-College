import React from "react";
import {
  ArrowRight, Building2, ClipboardList, ExternalLink, FileText, GraduationCap, LogIn,
  MessageCircle, ShieldCheck, UserPlus, Search, BookOpen, Phone, Zap, Clock,
} from "lucide-react";
import Reveal from "../lib/Reveal.jsx";
import { OFFICIAL_SITE, QUESTIONS } from "../lib/config.js";

/** What actually happens when an enquiry is sent (mirrors pages/Enquiry.jsx + the enquiry API). */
const ENQUIRY_STEPS = [
  { title: "Fill in the form", text: "Name, email, phone number, an optional programme, and your question." },
  { title: "Give consent", text: "Tick the consent box so the admissions team may store your details and reply." },
  { title: "Send and get a reference", text: "You receive a reference number straight away. The same enquiry sent twice is not duplicated." },
  { title: "The team reviews it", text: "The SVCE admissions team reads your question and contacts you using the details you gave." },
];

/** Institutional details that have not been supplied/approved yet. Shown honestly instead of guessed. */
const PENDING_ADMISSIONS = [
  { icon: GraduationCap, label: "Programmes and eligibility" },
  { icon: FileText, label: "Application dates and deadlines" },
  { icon: BookOpen, label: "Fee structure" },
  { icon: Phone, label: "Admissions office contact details" },
];

const PENDING_COLLEGE = [
  { icon: Building2, title: "Departments and programmes", text: "A verified list will appear here once the college approves it." },
  { icon: Zap, title: "Placements", text: "Placement information will be published only after college approval." },
  { icon: Phone, title: "Contact and location", text: "Official contact details will be added once approved by the college." },
];

const STEPS = [
  { icon: ClipboardList, title: "Send an admissions enquiry", text: "Use the form for admission-related questions. The admissions team replies to you directly." },
  { icon: Search, title: "Ask the AI assistant", text: "For quick questions, the assistant searches the SVCE information it has indexed and shows source links when available." },
  { icon: LogIn, title: "Sign in to track", text: "Students with an account can see their own enquiries and their status in a personal dashboard." },
];

function Pending({ children = "Pending college approval" }) {
  return <span className="pending-tag"><Clock size={13} aria-hidden="true" /> {children}</span>;
}

export default function Landing({ navigate, ask }) {
  const go = (target) => (e) => { e.preventDefault(); navigate(target); };

  return (
    <main id="main" tabIndex={-1}>
      {/* ------------------------------ Hero ------------------------------ */}
      <section className="hero" id="home" aria-labelledby="hero-title">
        <div className="container hero-grid">
          <div className="hero-copy">
            <span className="eyebrow">Sri Venkateswara College of Engineering, Tirupati</span>
            <h1 id="hero-title">Admissions enquiries and campus information for SVCE Tirupati</h1>
            <p className="hero-lede">
              Send your admissions question to the SVCE team, or ask the campus AI assistant for information from available college sources.
            </p>
            <div className="hero-actions">
              <a className="btn btn--primary btn--lg" href="#enquiry" onClick={go("enquiry")}>
                Start admissions enquiry <ArrowRight size={18} className="btn-arrow" />
              </a>
              <a className="btn btn--secondary btn--lg" href="#assistant" onClick={go("assistant")}>
                <MessageCircle size={18} /> Ask the AI assistant
              </a>
            </div>
            <p className="hero-login">
              Already a student? <a className="text-link" href="#login" onClick={go("login")}>Student login</a>
            </p>
          </div>

          <aside className="hero-panel" aria-labelledby="journey-title">
            <h2 id="journey-title">How an admissions enquiry works</h2>
            <ol className="journey">
              {ENQUIRY_STEPS.map(({ title, text }, i) => (
                <li key={title}>
                  <span className="journey-n" aria-hidden="true">{i + 1}</span>
                  <div><b>{title}</b><p>{text}</p></div>
                </li>
              ))}
            </ol>
            <a className="text-link hero-panel-link" href="#enquiry" onClick={go("enquiry")}>Go to the enquiry form <ArrowRight size={16} /></a>
          </aside>
        </div>
      </section>

      {/* --------------------------- Admissions --------------------------- */}
      <section className="section band" id="admissions" aria-labelledby="adm-title">
        <div className="container">
          <Reveal className="section-head">
            <span className="eyebrow">Admissions</span>
            <h2 id="adm-title">What you can do now, and what is still to come</h2>
            <p>The enquiry form is live. Official admission details are being added only after the college approves them.</p>
          </Reveal>
          <div className="adm-grid">
            <Reveal className="card adm-card">
              <span className="icon-tile icon-tile--teal"><ClipboardList size={22} /></span>
              <h3>Ask the admissions team</h3>
              <p>Questions about eligibility, the process or documents can be sent through the enquiry form. No account is needed.</p>
              <a className="btn btn--primary" href="#enquiry" onClick={go("enquiry")}>Open the enquiry form <ArrowRight size={18} className="btn-arrow" /></a>
            </Reveal>
            <Reveal className="card adm-card" delay={80}>
              <h3>Admission details</h3>
              <p>These will be published here once supplied and approved by SVCE.</p>
              <ul className="pending-list">
                {PENDING_ADMISSIONS.map(({ icon: Icon, label }) => (
                  <li key={label}><Icon size={18} aria-hidden="true" /><span>{label}</span><Pending /></li>
                ))}
              </ul>
              <p className="small muted">Until then, ask through the enquiry form or check the{" "}
                <a className="text-link" href={OFFICIAL_SITE} target="_blank" rel="noreferrer">official SVCE website<span className="sr-only"> (opens in a new tab)</span></a>.</p>
            </Reveal>
          </div>
        </div>
      </section>

      {/* ------------------------- College information ------------------------- */}
      <section className="section" id="explore" aria-labelledby="college-title">
        <div className="container">
          <Reveal className="section-head">
            <span className="eyebrow">College information</span>
            <h2 id="college-title">Sri Venkateswara College of Engineering, Tirupati</h2>
            <p>Verified college information will be listed here. For anything not listed yet, the official website is the reference.</p>
          </Reveal>
          <div className="info-grid">
            {PENDING_COLLEGE.map(({ icon: Icon, title, text }, i) => (
              <Reveal key={title} delay={i * 70} className="card info-card">
                <span className="icon-tile icon-tile--sage"><Icon size={22} /></span>
                <h3>{title}</h3>
                <p>{text}</p>
                <Pending />
              </Reveal>
            ))}
            <Reveal delay={210} className="card info-card info-card--link">
              <span className="icon-tile"><ExternalLink size={22} /></span>
              <h3>Official SVCE website</h3>
              <p>The college’s own website is the authoritative source for current information.</p>
              <a className="text-link" href={OFFICIAL_SITE} target="_blank" rel="noreferrer">Visit svce.edu.in <ExternalLink size={14} className="inline-icon" aria-hidden="true" /><span className="sr-only"> (opens in a new tab)</span></a>
            </Reveal>
          </div>
        </div>
      </section>

      {/* ---------------------------- Student support ---------------------------- */}
      <section className="section band" id="support" aria-labelledby="support-title">
        <div className="container">
          <Reveal className="section-head">
            <span className="eyebrow">Student support</span>
            <h2 id="support-title">Get answers, or sign in to your account</h2>
          </Reveal>
          <div className="support-grid">
            <Reveal className="card support-card">
              <span className="icon-tile icon-tile--teal"><MessageCircle size={22} /></span>
              <h3>AI assistant</h3>
              <p>Ask in plain language. The assistant searches the SVCE information available to it and shows sources when it can. Pick a starting question:</p>
              <div className="ask-chips">
                {QUESTIONS.map(({ icon: Icon, label, q }) => (
                  <button key={label} type="button" className="chip" onClick={() => ask(q)}><Icon size={15} aria-hidden="true" /> {label}</button>
                ))}
              </div>
              <a className="btn btn--secondary" href="#assistant" onClick={go("assistant")}>Open the assistant <ArrowRight size={18} className="btn-arrow" /></a>
            </Reveal>
            <Reveal className="card support-card" delay={80}>
              <span className="icon-tile icon-tile--sage"><LogIn size={22} /></span>
              <h3>Student login</h3>
              <p>Sign in to see the enquiries you have sent and their current status. New here? You can create an account.</p>
              <div className="btn-row btn-row--tight">
                <a className="btn btn--secondary" href="#login" onClick={go("login")}><LogIn size={18} /> Student login</a>
                <a className="btn btn--quiet" href="#register" onClick={go("register")}><UserPlus size={18} /> Create account</a>
              </div>
            </Reveal>
          </div>
        </div>
      </section>

      {/* ---------------------------- How it works ---------------------------- */}
      <section className="section" id="about" aria-labelledby="how-title">
        <div className="container">
          <Reveal className="section-head">
            <span className="eyebrow">How the platform works</span>
            <h2 id="how-title">Three ways to get help</h2>
          </Reveal>
          <ol className="steps">
            {STEPS.map(({ icon: Icon, title, text }, i) => (
              <Reveal as="li" key={title} delay={i * 80} className="step">
                <span className="icon-tile icon-tile--sage"><Icon size={22} /></span>
                <h3>{title}</h3>
                <p>{text}</p>
              </Reveal>
            ))}
          </ol>
          <Reveal className="note" delay={100}>
            <ShieldCheck size={20} />
            <p><b>Good to know.</b> The assistant answers only from information it has indexed, and AI can be incomplete or out of date. Confirm admissions, fees and other important details with official SVCE sources.</p>
          </Reveal>
        </div>
      </section>
    </main>
  );
}
