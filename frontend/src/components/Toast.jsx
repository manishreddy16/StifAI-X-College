import React from "react";
import { CircleAlert, CircleCheck } from "lucide-react";

export default function ToastRegion({ toasts }) {
  return (
    <div className="toast-region" role="status" aria-live="polite" aria-atomic="false">
      {toasts.map((toast) => (
        <div key={toast.id} className={`toast ${toast.kind === "error" ? "toast--error" : ""}`}>
          {toast.kind === "error" ? <CircleAlert size={18} /> : <CircleCheck size={18} />}
          {toast.message}
        </div>
      ))}
    </div>
  );
}
