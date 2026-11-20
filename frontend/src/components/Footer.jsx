import React from "react";
import { ExternalLink } from "lucide-react";
import Brand from "./Brand.jsx";
import { OFFICIAL_SITE } from "../lib/config.js";
import { useAuth } from "../lib/auth.jsx";

export default function Footer({ navigate }) {
  const { user } = useAuth();
  const go = (target) => (event) => { event.preventDefault(); navigate(target); };
  return (
    <footer className="footer">
      <div className="container">
        <div className="footer-inner">
          <div className="footer-about">
            <Brand onClick={go("home")} />
            <p>Admissions enquiries and a campus information assistant for Sri Venkateswara College of Engineering, Tirupati.</p>
          </div>
          <nav aria-label="Footer">
            <h3>Explore</h3>
            <ul>
              <li><a className="footer-link" href="#home" onClick={go("home")}>Home</a></li>
              <li><a className="footer-link" href="#enquiry" onClick={go("enquiry")}>Admissions enquiry</a></li>
              <li><a className="footer-link" href="#explore" onClick={go("explore")}>College information</a></li>
              <li><a className="footer-link" href="#assistant" onClick={go("assistant")}>AI assistant</a></li>
              <li><a className="footer-link" href="#about" onClick={go("about")}>How it works</a></li>
              {user
                ? <li><a className="footer-link" href="#dashboard" onClick={go("dashboard")}>My dashboard</a></li>
                : <>
                    <li><a className="footer-link" href="#login" onClick={go("login")}>Student login</a></li>
                    <li><a className="footer-link" href="#admin/login" onClick={go("admin/login")}>Staff sign-in</a></li>
                  </>}
            </ul>
          </nav>
          <div>
            <h3>Official</h3>
            <ul>
              <li><a className="footer-link" href={OFFICIAL_SITE} target="_blank" rel="noreferrer">SVCE website <ExternalLink size={14} aria-hidden="true" /><span className="sr-only"> (opens in a new tab)</span></a></li>
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
