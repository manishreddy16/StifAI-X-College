import React from "react";
import {
  ArrowRight, ArrowDownRight, ArrowUpRight, BarChart3, Building2, FileText, GraduationCap,
  Layers, MessageCircle, Mic, Paperclip, ShieldCheck, Sparkles, Zap, Link2, Search,
} from "lucide-react";
import Reveal from "../lib/Reveal.jsx";
import { QUESTIONS } from "../lib/config.js";

const TOPIC_NODES = [
  { icon: GraduationCap, label: "Admissions", cls: "node-a" },
  { icon: Building2, label: "Departments", cls: "node-b" },
  { icon: Zap, label: "Placements", cls: "node-c" },
  { icon: MessageCircle, label: "Contact", cls: "node-d" },
];

function HeroPreview() {
  return (
    <div className="hero-visual" role="img" aria-label="Illustrative preview: a student asks about B.Tech admission information and the assistant replies with a link to the relevant official page.">
      <div className="hero-arcs" aria-hidden="true"><i /><i /><i /></div>
      <div className="preview" aria-hidden="true">
        <div className="preview-head">
          <span className="preview-mark"><Sparkles size={15} /></span>
          <b>Campus AI</b>
          <span className="preview-tag">Illustrative preview</span>
        </div>
        <div className="preview-body">
          <div className="pv-user">How do I find B.Tech admission information?</div>
          <div className="pv-ai">
            <span className="pv-avatar"><Sparkles size={14} /></span>
            <div>
              <p>I’ll search available SVCE information and show the relevant source.</p>
              <div className="pv-lines"><i /><i /><i /></div>
              <div className="pv-source">
                <span><Link2 size={14} /></span>
                <div><b>Official admission page</b><small>svce.edu.in</small></div>
                <ArrowUpRight size={15} />
              </div>
            </div>
          </div>
        </div>
        <div className="preview-composer"><span>Ask anything…</span><i><ArrowRight size={14} /></i></div>
      </div>
      {TOPIC_NODES.map(({ icon: Icon, label, cls }) => (
        <span key={label} className={`node ${cls}`} aria-hidden="true"><Icon size={15} />{label}</span>
      ))}
    </div>
  );
}

const CAPABILITIES = [
  {
    id: "grounded", wide: true, tone: "teal", icon: ShieldCheck, title: "Find relevant SVCE sources",
    text: "The assistant searches available, indexed SVCE information before it answers, and shows source links so you can check the details yourself.",
    extra: (<ul className="mini-list"><li>Answers can use indexed passages</li><li>Source links when available</li><li>Clear when no relevant result is found</li></ul>),
  },
  {
    id: "topics", tone: "champagne", icon: Layers, title: "One place for campus topics",
    text: "Admissions, departments, placements, fees and official contact details — from a single, focused conversation.",
  },
  { id: "files", tone: "sage", icon: Paperclip, title: "Bring your own document", text: "Attach TXT, MD, CSV, JSON, PDF, DOCX or images (up to 10 MB) and ask questions about what’s inside." },
  { id: "voice", tone: "champagne", icon: Mic, title: "Speak your question", text: "Dictate instead of typing in browsers that support speech recognition, then review the text before sending." },
  { id: "charts", tone: "teal", icon: BarChart3, title: "See numbers at a glance", text: "When an answer contains a table of figures, turn it into a simple chart with one click." },
];

const STEPS = [
  { n: "01", icon: MessageCircle, title: "Ask in plain language", text: "Type, dictate, or pick a suggested question. Attach a document if you want it considered." },
  { n: "02", icon: Search, title: "We search SVCE information", text: "The assistant retrieves the most relevant passages from the indexed SVCE content." },
  { n: "03", icon: FileText, title: "Read, then verify", text: "You get a clear answer with source links when available — always confirm key details officially." },
];

export default function Landing({ navigate, ask }) {
  return (
    <main id="main" tabIndex={-1}>
      {/* ------------------------------ Hero ------------------------------ */}
      <section className="hero" id="home" aria-labelledby="hero-title">
        <div className="hero-bg" aria-hidden="true"><i className="glow glow-1" /><i className="glow glow-2" /><i className="dots" /></div>
        <div className="container hero-grid">
          <div className="hero-copy">
            <span className="eyebrow hero-in" style={{ "--d": "0ms" }}>Your campus. Connected.</span>
            <h1 id="hero-title" className="hero-in" style={{ "--d": "90ms" }}>
              College information, <em>made intelligent.</em>
            </h1>
            <p className="hero-lede hero-in" style={{ "--d": "190ms" }}>
              A smarter way to explore Sri Venkateswara College of Engineering, Tirupati. Ask questions, discover official information, and get answers grounded in available college sources.
            </p>
            <div className="hero-actions hero-in" style={{ "--d": "290ms" }}>
              <button type="button" className="btn btn--primary" onClick={() => navigate("assistant")}>
                Ask the AI assistant <ArrowRight size={18} className="btn-arrow" />
              </button>
              <a className="btn btn--secondary" href="#explore" onClick={(e) => { e.preventDefault(); navigate("explore"); }}>
                Explore capabilities <ArrowDownRight size={18} />
              </a>
            </div>
            <ul className="hero-proof hero-in" style={{ "--d": "390ms" }}>
              <li><ShieldCheck size={16} /> Source links when available</li>
              <li><Zap size={16} /> Built for SVCE Tirupati</li>
              <li><Paperclip size={16} /> Files &amp; voice supported</li>
            </ul>
          </div>
          <div className="hero-in hero-visual-wrap" style={{ "--d": "260ms" }}><HeroPreview /></div>
        </div>
      </section>

      {/* ------------------------- Suggested questions ------------------------- */}
      <section className="section explore" id="explore" aria-labelledby="explore-title">
        <div className="container">
          <Reveal className="section-head section-head--split">
            <div>
              <span className="eyebrow">Start with a question</span>
              <h2 id="explore-title">What do you need to know today?</h2>
            </div>
            <p>Choose a topic or ask your own question. The assistant searches available SVCE information and shows sources when available.</p>
          </Reveal>
          <div className="q-grid">
            {QUESTIONS.map(({ icon: Icon, label, q }, i) => (
              <Reveal key={label} delay={i * 70} className={`q-slot q-slot-${i + 1}`}>
                <button type="button" className="card card--interactive q-card" onClick={() => ask(q)}>
                  <span className="q-top">
                    <span className={`icon-tile ${i % 3 === 1 ? "icon-tile--sage" : i % 3 === 2 ? "icon-tile--teal" : ""}`}><Icon size={22} /></span>
                    <span className="q-num" aria-hidden="true">0{i + 1}</span>
                  </span>
                  <b>{label}</b>
                  <span className="q-text">{q}</span>
                  <span className="q-go">Ask this <ArrowRight size={16} /></span>
                </button>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ------------------------------ Capabilities ------------------------------ */}
      <section className="section about" id="about" aria-labelledby="about-title">
        <div className="container">
          <Reveal className="section-head">
            <span className="eyebrow">What it can do</span>
            <h2 id="about-title">Less searching. <em>More understanding.</em></h2>
            <p>Explore admissions, departments, placement reports, academic information and official contact details from one focused interface.</p>
          </Reveal>
          <div className="bento">
            {CAPABILITIES.map(({ id, wide, tone, icon: Icon, title, text, extra }, i) => (
              <Reveal key={id} delay={i * 70} className={`bento-slot ${wide ? "bento-wide" : ""}`}>
                <article className={`card bento-card bento-${tone}`}>
                  <span className={`icon-tile ${tone === "sage" ? "icon-tile--sage" : tone === "teal" ? "icon-tile--teal" : ""}`}><Icon size={22} /></span>
                  <h3>{title}</h3>
                  <p>{text}</p>
                  {extra}
                </article>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ------------------------------ How it works ------------------------------ */}
      <section className="section how" aria-labelledby="how-title">
        <div className="container">
          <Reveal className="section-head">
            <span className="eyebrow">How it works</span>
            <h2 id="how-title">From question to clarity in three steps</h2>
          </Reveal>
          <ol className="steps">
            {STEPS.map(({ n, icon: Icon, title, text }, i) => (
              <Reveal as="li" key={n} delay={i * 90} className="step">
                <span className="step-num" aria-hidden="true">{n}</span>
                <span className="icon-tile icon-tile--sage"><Icon size={22} /></span>
                <h3>{title}</h3>
                <p>{text}</p>
              </Reveal>
            ))}
          </ol>
          <Reveal className="note" delay={120}>
            <ShieldCheck size={20} />
            <p><b>Good to know.</b> Answers are based on the information the assistant can find in its index. AI can be incomplete or out of date — verify admissions, fees and other important details with official SVCE sources.</p>
          </Reveal>
        </div>
      </section>

      {/* ------------------------------ Closing CTA ------------------------------ */}
      <section className="cta-wrap" aria-labelledby="cta-title">
        <div className="container">
          <Reveal className="cta">
            <div>
              <span className="eyebrow">Ready when you are</span>
              <h2 id="cta-title">Your next question starts here.</h2>
            </div>
            <button type="button" className="btn btn--primary" onClick={() => navigate("assistant")}>
              Open Campus AI <ArrowRight size={18} className="btn-arrow" />
            </button>
          </Reveal>
        </div>
      </section>
    </main>
  );
}
