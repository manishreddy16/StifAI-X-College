import React from "react";
import { ExternalLink } from "lucide-react";
import Brand from "./Brand.jsx";
import { OFFICIAL_SITE } from "../lib/config.js";

export default function Footer({ navigate }) {
  const go = (target) => (event) => { event.preventDefault(); navigate(target); };
  return (
    <footer className="footer">
      <div className="container">
        <div className="footer-inner">
          <div className="footer-about">
            <Brand onClick={go("home")} />
            <p>A campus information assistant for Sri Venkateswara College of Engineering, Tirupati — built to make official information easier to find.</p>
          </div>
          <nav aria-label="Footer">
            <h3>Explore</h3>
            <ul>
              <li><a className="footer-link" href="#home" onClick={go("home")}>Home</a></li>
              <li><a className="footer-link" href="#explore" onClick={go("explore")}>Suggested questions</a></li>
              <li><a className="footer-link" href="#about" onClick={go("about")}>What it can do</a></li>
              <li><a className="footer-link" href="#assistant" onClick={go("assistant")}>AI assistant</a></li>
            </ul>
          </nav>
          <div>
            <h3>Official</h3>
            <ul>
              <li><a className="footer-link" href={OFFICIAL_SITE} target="_blank" rel="noreferrer">SVCE website <ExternalLink size={14} /></a></li>
            </ul>
          </div>
        </div>
        <div className="footer-base">
          <span>STIF × SVCE Tirupati · Campus AI</span>
          <span>AI answers can be incomplete. Please verify important details with official SVCE sources.</span>
        </div>
      </div>
    </footer>
  );
}
