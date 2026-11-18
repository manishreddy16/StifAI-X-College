import React, { useEffect, useRef, useState } from "react";
import { prefersReducedMotion } from "./config.js";

/** Fades/raises its children in once as they scroll into view. Falls back to visible. */
export default function Reveal({ as: Tag = "div", delay = 0, className = "", children, ...rest }) {
  const ref = useRef(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node || prefersReducedMotion() || typeof IntersectionObserver === "undefined") {
      setVisible(true);
      return undefined;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.08 }
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return (
    <Tag ref={ref} className={`reveal ${visible ? "is-visible" : ""} ${className}`.trim()} style={{ "--reveal-delay": `${delay}ms` }} {...rest}>
      {children}
    </Tag>
  );
}
