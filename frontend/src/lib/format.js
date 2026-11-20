export const STATUS_LABELS = { new: "New", in_progress: "In progress", responded: "Responded", closed: "Closed" };
export const STATUSES = Object.keys(STATUS_LABELS);

export function formatDate(iso, withTime = true) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-IN", withTime
    ? { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" }
    : { day: "numeric", month: "short", year: "numeric" });
}

export const EMAIL_RE = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+$/;

/** Steps a student sees on the enquiry tracker (same statuses the admin workflow uses). */
export const TRACK_STEPS = ["new", "in_progress", "responded", "closed"];

/** "Today", "1 day", "5 days" since an ISO timestamp (calendar days, local time). */
export function waitingLabel(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const start = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.max(0, Math.round((start(new Date()) - start(d)) / 86400000));
  return days === 0 ? "Today" : `${days} day${days === 1 ? "" : "s"}`;
}
