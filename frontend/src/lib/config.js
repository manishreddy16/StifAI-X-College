import { BookOpen, Building2, GraduationCap, MessageCircle, Zap } from "lucide-react";

// Same-origin by default: Vite proxies API calls in development and FastAPI serves
// the built frontend in production. Set VITE_API_BASE_URL only for split hosting.
export const API = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/+$/, "");
export const MAX_MESSAGE_CHARS = 3000;
export const MAX_DOCUMENT_CHARS = 30000;

// Suggested questions — identical prompts to the original frontend.
export const QUESTIONS = [
  { icon: GraduationCap, label: "Admissions", q: "What is the admission process for B.Tech at SVCE Tirupati?" },
  { icon: Building2, label: "Departments", q: "What engineering departments are available at SVCE Tirupati?" },
  { icon: Zap, label: "Placements", q: "What are the latest placement statistics and highest package at SVCE Tirupati?" },
  { icon: MessageCircle, label: "Contact", q: "What is the phone number and email address of SVCE Tirupati?" },
  { icon: BookOpen, label: "Fees", q: "What is the B.Tech fee structure at SVCE Tirupati?" },
];

export const OFFICIAL_SITE = "https://svce.edu.in/";

export const prefersReducedMotion = () =>
  typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
