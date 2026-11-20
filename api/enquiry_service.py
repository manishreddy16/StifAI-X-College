"""Student enquiries and programmes. No web-framework imports: fully unit-testable."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta

from api import db
from api.auth_service import AuthUser, clean_email, clean_name, clean_text
from api.errors import NotFound, RateLimited, ValidationFailed

CONSENT_VERSION = "2026-11-v1"
# DRAFT wording: must be reviewed/approved by the college before launch (see HANDOVER.md).
CONSENT_TEXT = (
    "I agree that the details I enter may be stored and used by the college admissions team to respond "
    "to my enquiry by phone, email or WhatsApp-style messaging, and that I can ask for them to be corrected or deleted."
)
MESSAGE_MIN, MESSAGE_MAX = 10, 2000
DUPLICATE_WINDOW = timedelta(days=7)
MAX_PER_EMAIL_PER_DAY = 5
STATUSES = ("new", "in_progress", "responded", "closed")
STATUS_LABELS = {"new": "New", "in_progress": "In progress", "responded": "Responded", "closed": "Closed"}
GENERAL_LABEL = "General / not sure yet"
MAX_PAGE_SIZE = 100


def clean_phone(value: object) -> str | None:
    """Return a normalised phone (digits with optional leading +) or None if implausible."""
    raw = clean_text(value)
    if not re.fullmatch(r"[+()\-.\s\d]{7,25}", raw):
        return None
    plus = raw.startswith("+")
    digits = re.sub(r"\D", "", raw)
    if plus and digits.startswith("91") and len(digits) == 12:
        national = digits[2:]
        return f"+91{national}" if re.fullmatch(r"[6-9]\d{9}", national) else None
    if not plus:
        if digits.startswith("0") and len(digits) == 11:
            digits = digits[1:]
        if len(digits) == 12 and digits.startswith("91"):
            digits = digits[2:]
        return digits if re.fullmatch(r"[6-9]\d{9}", digits) else None
    return f"+{digits}" if 8 <= len(digits) <= 15 else None


def _norm_key(text: str) -> str:
    return " ".join(text.lower().split())


# ---------------------------------------------------------------- programmes

def list_programmes(conn: db.Connection, *, active_only: bool = True) -> list[dict]:
    sql = "SELECT id, name, is_active FROM programmes"
    if active_only:
        sql += " WHERE is_active = TRUE"
    return [{"id": r["id"], "name": r["name"], "is_active": bool(r["is_active"])}
            for r in conn.execute(sql + " ORDER BY lower(name), name")]


def add_programme(conn: db.Connection, name: object, now: datetime | None = None) -> dict:
    clean = " ".join(clean_text(name).split())
    if not (2 <= len(clean) <= 120):
        raise ValidationFailed({"name": "Enter a programme name (2-120 characters)."})
    try:
        programme_id = conn.insert_id("INSERT INTO programmes (name, name_key, created_at) VALUES (?, ?, ?)",
                                      (clean, _norm_key(clean), db.db_timestamp(now or db.utcnow())))
    except db.IntegrityError as exc:
        raise ValidationFailed({"name": "That programme already exists."}) from exc
    return {"id": programme_id, "name": clean, "is_active": True}


def set_programme_active(conn: db.Connection, programme_id: int, active: bool) -> dict:
    cur = conn.execute("UPDATE programmes SET is_active = ? WHERE id = ?", (active, programme_id))
    if cur.rowcount == 0:
        raise NotFound("Programme not found.")
    r = conn.execute("SELECT id, name, is_active FROM programmes WHERE id = ?", (programme_id,)).fetchone()
    return {"id": r["id"], "name": r["name"], "is_active": bool(r["is_active"])}


# ---------------------------------------------------------------- enquiries

def validate_enquiry(conn: db.Connection, data: dict) -> dict:
    """Validate a raw submission. Returns cleaned values or raises ValidationFailed with per-field messages."""
    problems: dict[str, str] = {}
    name = clean_name(data.get("full_name"))
    if name is None:
        problems["full_name"] = "Enter your full name (2-100 letters)."
    email = clean_email(data.get("email"))
    if email is None:
        problems["email"] = "Enter a valid email address."
    phone = clean_phone(data.get("phone"))
    if phone is None:
        problems["phone"] = "Enter a valid phone number (10-digit Indian mobile, or +country code)."
    message = clean_text(data.get("message"))
    if len(message) < MESSAGE_MIN:
        problems["message"] = f"Please describe your question (at least {MESSAGE_MIN} characters)."
    elif len(message) > MESSAGE_MAX:
        problems["message"] = f"Please keep your message under {MESSAGE_MAX} characters."

    programme_id = data.get("programme_id")
    label = None
    if programme_id in (None, "", 0):
        programme_id = None
        other = " ".join(clean_text(data.get("programme_other")).split())
        if len(other) > 120:
            problems["programme_other"] = "Keep this under 120 characters."
        label = other or GENERAL_LABEL
    else:
        try:
            pid = int(programme_id)
        except (TypeError, ValueError):
            pid = -1
        row = conn.execute("SELECT id, name FROM programmes WHERE id = ? AND is_active = TRUE", (pid,)).fetchone()
        if row is None:
            problems["programme_id"] = "Choose a programme from the list."
        else:
            programme_id, label = row["id"], row["name"]

    if data.get("consent") is not True:
        problems["consent"] = "You must give consent so we can store your details and contact you."
    if problems:
        raise ValidationFailed(problems)
    return {"full_name": name, "email": email, "phone": phone, "message": message,
            "programme_id": programme_id, "programme_label": label}


def _dedupe_hash(v: dict) -> str:
    key = "|".join([v["email"], v["phone"], str(v["programme_id"] or v["programme_label"]).lower(), _norm_key(v["message"])])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def submit_enquiry(conn: db.Connection, data: dict, *, user: AuthUser | None = None, now: datetime | None = None) -> dict:
    """Validate and persist. Returns {"enquiry": {...}, "duplicate": bool}. Nothing is reported saved unless committed."""
    now = now or db.utcnow()
    v = validate_enquiry(conn, data)
    digest = _dedupe_hash(v)
    with db.transaction(conn, immediate=True):  # serialises double-clicks / concurrent identical submits
        # SQLite's immediate transaction serializes writers; PostgreSQL uses a
        # transaction-scoped advisory lock keyed by email for the same guarantee.
        conn.lock_key("enquiry-email:" + v["email"])
        existing = conn.execute(
            "SELECT * FROM enquiries WHERE dedupe_hash = ? AND created_at > ? ORDER BY id LIMIT 1",
            (digest, db.db_timestamp(now - DUPLICATE_WINDOW)),
        ).fetchone()
        if existing is not None:
            return {"enquiry": _public_receipt(existing), "duplicate": True}
        recent = conn.execute("SELECT COUNT(*) FROM enquiries WHERE email = ? AND created_at > ?",
                              (v["email"], db.db_timestamp(now - timedelta(days=1)))).fetchone()[0]
        if recent >= MAX_PER_EMAIL_PER_DAY:
            raise RateLimited("You have sent several enquiries today. Please wait for our reply before sending more.",
                              code="too_many_enquiries")
        stamp = db.db_timestamp(now)
        enquiry_id = conn.insert_id(
            """INSERT INTO enquiries (user_id, full_name, email, phone, programme_id, programme_label, message,
                   consent, consent_version, consent_at, dedupe_hash, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user.id if user else None, v["full_name"], v["email"], v["phone"], v["programme_id"],
             v["programme_label"], v["message"], True, CONSENT_VERSION, stamp, digest, stamp, stamp),
        )
        reference = f"ENQ-{now.year}-{enquiry_id:06d}"
        conn.execute("UPDATE enquiries SET reference = ? WHERE id = ?", (reference, enquiry_id))
        row = conn.execute("SELECT * FROM enquiries WHERE id = ?", (enquiry_id,)).fetchone()
    return {"enquiry": _public_receipt(row), "duplicate": False}


def _public_receipt(row) -> dict:
    """What the submitter gets back: no phone/email echo beyond what they just typed, no admin notes."""
    return {"reference": row["reference"], "programme": row["programme_label"], "status": row["status"],
            "created_at": row["created_at"]}


def _admin_dict(row, *, detail: bool) -> dict:
    d = {"id": row["id"], "reference": row["reference"], "full_name": row["full_name"], "email": row["email"],
         "phone": row["phone"], "programme": row["programme_label"], "programme_id": row["programme_id"],
         "status": row["status"], "created_at": row["created_at"], "updated_at": row["updated_at"],
         "has_account": row["user_id"] is not None}
    if detail:
        d.update(message=row["message"], admin_notes=row["admin_notes"], consent_version=row["consent_version"],
                 consent_at=row["consent_at"])
    else:
        d["message_preview"] = row["message"][:140] + ("…" if len(row["message"]) > 140 else "")
    return d


def list_for_user(conn: db.Connection, user: AuthUser) -> list[dict]:
    rows = conn.execute("SELECT * FROM enquiries WHERE user_id = ? ORDER BY id DESC LIMIT 100", (user.id,))
    return [{**_public_receipt(r), "message": r["message"]} for r in rows]


def _escape_like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_enquiries(conn: db.Connection, *, status: str | None = None, programme_id: int | None = None, q: str | None = None,
                   page: int = 1, page_size: int = 20) -> dict:
    where, args = [], []
    if status:
        if status not in STATUSES:
            raise ValidationFailed({"status": "Unknown status."})
        where.append("status = ?"); args.append(status)
    if programme_id:
        where.append("programme_id = ?"); args.append(int(programme_id))
    term = clean_text(q)[:100] if q else ""
    if term:
        like = f"%{_escape_like(term.lower())}%"
        where.append("(LOWER(full_name) LIKE ? ESCAPE '\\' OR LOWER(email) LIKE ? ESCAPE '\\' OR phone LIKE ? ESCAPE '\\' "
                     "OR LOWER(reference) LIKE ? ESCAPE '\\')")
        args += [like, like, like, like]
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    page = max(1, int(page or 1))
    page_size = min(MAX_PAGE_SIZE, max(1, int(page_size or 20)))
    total = conn.execute(f"SELECT COUNT(*) FROM enquiries{clause}", args).fetchone()[0]
    rows = conn.execute(f"SELECT * FROM enquiries{clause} ORDER BY id DESC LIMIT ? OFFSET ?",
                        args + [page_size, (page - 1) * page_size]).fetchall()
    return {"items": [_admin_dict(r, detail=False) for r in rows], "total": total, "page": page,
            "page_size": page_size, "pages": max(1, -(-total // page_size))}


def get_enquiry(conn: db.Connection, enquiry_id: int) -> dict:
    row = conn.execute("SELECT * FROM enquiries WHERE id = ?", (enquiry_id,)).fetchone()
    if row is None:
        raise NotFound("Enquiry not found.")
    return _admin_dict(row, detail=True)


def update_enquiry(conn: db.Connection, enquiry_id: int, *, status: str | None = None, admin_notes: str | None = None,
                   now: datetime | None = None) -> dict:
    sets, args, problems = [], [], {}
    if status is not None:
        if status not in STATUSES:
            problems["status"] = "Choose a valid status."
        sets.append("status = ?"); args.append(status)
    if admin_notes is not None:
        notes = clean_text(admin_notes)
        if len(notes) > 4000:
            problems["admin_notes"] = "Notes are limited to 4000 characters."
        sets.append("admin_notes = ?"); args.append(notes)
    if problems:
        raise ValidationFailed(problems)
    if not sets:
        raise ValidationFailed({"status": "Nothing to update."})
    sets.append("updated_at = ?"); args.append(db.db_timestamp(now or db.utcnow()))
    cur = conn.execute(f"UPDATE enquiries SET {', '.join(sets)} WHERE id = ?", args + [enquiry_id])
    if cur.rowcount == 0:
        raise NotFound("Enquiry not found.")
    return get_enquiry(conn, enquiry_id)


def stats(conn: db.Connection, *, now: datetime | None = None) -> dict:
    now = now or db.utcnow()
    by_status = {s: 0 for s in STATUSES}
    for r in conn.execute("SELECT status, COUNT(*) c FROM enquiries GROUP BY status"):
        by_status[r["status"]] = r["c"]
    total = sum(by_status.values())
    day_start = db.db_timestamp(now.replace(hour=0, minute=0, second=0, microsecond=0))
    today = conn.execute("SELECT COUNT(*) FROM enquiries WHERE created_at >= ?", (day_start,)).fetchone()[0]
    last7 = conn.execute("SELECT COUNT(*) FROM enquiries WHERE created_at >= ?",
                         (db.db_timestamp(now - timedelta(days=7)),)).fetchone()[0]
    programmes = [{"programme": r["programme_label"], "count": r["c"]} for r in conn.execute(
        "SELECT programme_label, COUNT(*) c FROM enquiries GROUP BY programme_label ORDER BY c DESC, programme_label LIMIT 8")]
    daily = []
    for i in range(13, -1, -1):
        day = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
        next_day = day + timedelta(days=1)
        d = day.strftime("%Y-%m-%d")
        n = conn.execute("SELECT COUNT(*) FROM enquiries WHERE created_at >= ? AND created_at < ?",
                         (db.db_timestamp(day), db.db_timestamp(next_day))).fetchone()[0]
        daily.append({"date": d, "count": n})
    students = conn.execute("SELECT COUNT(*) FROM users WHERE role = 'student'").fetchone()[0]
    return {"total": total, "by_status": by_status, "today": today, "last_7_days": last7,
            "open": by_status["new"] + by_status["in_progress"], "top_programmes": programmes,
            "daily": daily, "student_accounts": students}
