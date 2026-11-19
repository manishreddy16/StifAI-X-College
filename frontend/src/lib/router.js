import { useEffect, useState } from "react";

/**
 * Tiny hash router that extends the app's existing "#home / #assistant" scheme.
 * "#admin/enquiries/12?x=1" -> { name: "admin", parts: ["enquiries","12"], params: {x:"1"} }
 */
export const SECTIONS = ["explore", "about"];

export function parseHash(hash = window.location.hash) {
  const raw = hash.replace(/^#\/?/, "");
  const [path, query = ""] = raw.split("?");
  const segments = path.split("/").filter(Boolean);
  const name = segments[0] || "home";
  return { name, parts: segments.slice(1), params: Object.fromEntries(new URLSearchParams(query)) };
}

export function useRoute() {
  const [route, setRoute] = useState(parseHash);
  useEffect(() => {
    const onHash = () => setRoute(parseHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  return route;
}

export const hrefFor = (target) => `#${target}`;
