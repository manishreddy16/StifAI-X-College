"""Accounts, roles and sessions. No web-framework imports: fully unit-testable."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from api import db, security
from api.errors import AccountLocked, AuthError, Conflict, ValidationFailed

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15
DEFAULT_SESSION_HOURS = 12

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?)+$")


@dataclass(frozen=True)
class AuthUser:
    id: int
    email: str
    full_name: str
    role: str

    def public(self) -> dict:
        return {"id": self.id, "email": self.email, "full_name": self.full_name, "role": self.role}


def clean_text(value: object) -> str:
    """Strip control characters and collapse surrounding whitespace."""
    if not isinstance(value, str):
        return ""
    return "".join(ch for ch in value if ch in "\n\t " or ch.isprintable()).strip()


def clean_email(value: object) -> str | None:
    email = clean_text(value).lower()
    if len(email) > 254 or not _EMAIL_RE.match(email) or ".." in email:
        return None
    return email


def clean_name(value: object) -> str | None:
    import unicodedata
    name = " ".join(clean_text(value).split())
    if not (2 <= len(name) <= 100):
        return None
    for ch in name:
        cat = unicodedata.category(ch)
        if not (cat[0] in ("L", "M") or ch in " .'-\u2019"):
            return None
    return name


def _user(row: db.DatabaseRow) -> AuthUser:
    return AuthUser(id=row["id"], email=row["email"], full_name=row["full_name"], role=row["role"])


def create_user(conn: db.Connection, *, email: str, full_name: str, password: str, role: str,
                now: datetime | None = None) -> AuthUser:
    """Validate and create an account with an explicit role (callers decide who may pick roles)."""
    problems: dict[str, str] = {}
    norm_email = clean_email(email)
    name = clean_name(full_name)
    if norm_email is None:
        problems["email"] = "Enter a valid email address."
    if name is None:
        problems["full_name"] = "Enter your full name (2-100 letters)."
    pw_problem = security.password_problem(password, email=norm_email or "")
    if pw_problem:
        problems["password"] = pw_problem
    if not conn.execute("SELECT 1 FROM roles WHERE name = ?", (role,)).fetchone():
        problems["role"] = "Unknown role."
    if problems:
        raise ValidationFailed(problems)
    pw_hash = security.hash_password(password)
    created = db.db_timestamp(now or db.utcnow())
    try:
        user_id = conn.insert_id(
            "INSERT INTO users (email, full_name, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
            (norm_email, name, pw_hash, role, created),
        )
    except db.IntegrityError as exc:
        raise Conflict("An account with this email already exists.", fields={"email": "Already registered."},
                       code="email_taken") from exc
    return AuthUser(id=user_id, email=norm_email, full_name=name, role=role)


def register_student(conn: db.Connection, *, email, full_name, password, now=None) -> AuthUser:
    """Public sign-up. The role is fixed to 'student' here; clients can never choose it."""
    return create_user(conn, email=email, full_name=full_name, password=password, role="student", now=now)


def authenticate(conn: db.Connection, email: str, password: str, now: datetime | None = None) -> AuthUser:
    now = now or db.utcnow()
    generic = AuthError("Incorrect email or password.", code="invalid_credentials")
    norm = clean_email(email)
    if norm is None or not isinstance(password, str) or not password or len(password) > security.MAX_PASSWORD:
        security.dummy_verify("x")
        raise generic
    row = conn.execute("SELECT * FROM users WHERE email = ?", (norm,)).fetchone()
    if row is None:
        security.dummy_verify(password)
        raise generic
    if row["locked_until"] and db.parse_iso(row["locked_until"]) > now:
        minutes = max(1, int((db.parse_iso(row["locked_until"]) - now).total_seconds() // 60) + 1)
        raise AccountLocked(f"Too many failed attempts. Try again in about {minutes} minute(s).")
    if not security.verify_password(password, row["password_hash"]) or not row["is_active"]:
        attempts = row["failed_attempts"] + 1
        if attempts >= MAX_FAILED_ATTEMPTS:
            conn.execute("UPDATE users SET failed_attempts = 0, locked_until = ? WHERE id = ?",
                         (db.db_timestamp(now + timedelta(minutes=LOCKOUT_MINUTES)), row["id"]))
        else:
            conn.execute("UPDATE users SET failed_attempts = ? WHERE id = ?", (attempts, row["id"]))
        raise generic
    conn.execute("UPDATE users SET failed_attempts = 0, locked_until = NULL, last_login_at = ? WHERE id = ?",
                 (db.db_timestamp(now), row["id"]))
    return _user(row)


def create_session(conn: db.Connection, user_id: int, *, now: datetime | None = None, ttl_hours: float | None = None):
    """Returns (raw_token, expires_at_iso). Only a digest of the token is stored."""
    now = now or db.utcnow()
    ttl = ttl_hours if ttl_hours is not None else DEFAULT_SESSION_HOURS
    if not isinstance(ttl, (int, float)) or not 0.25 <= ttl <= 24 * 30:
        raise ValueError("Session lifetime must be between 15 minutes and 30 days.")
    expires = now + timedelta(hours=ttl)
    token = security.new_token()
    with db.transaction(conn, immediate=True):
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (security.token_digest(token), user_id, db.db_timestamp(now), db.db_timestamp(expires)),
        )
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (db.db_timestamp(now - timedelta(days=1)),))
    return token, db.iso(expires)


def user_for_token(conn: db.Connection, token: str | None, now: datetime | None = None) -> AuthUser | None:
    if not token or len(token) > 256:
        return None
    now = now or db.utcnow()
    row = conn.execute(
        """SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id
           WHERE s.token_hash = ? AND s.revoked_at IS NULL AND s.expires_at > ? AND u.is_active = TRUE""",
        (security.token_digest(token), db.db_timestamp(now)),
    ).fetchone()
    return _user(row) if row else None


def revoke_token(conn: db.Connection, token: str | None, now: datetime | None = None) -> None:
    if token:
        conn.execute("UPDATE sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
                     (db.db_timestamp(now or db.utcnow()), security.token_digest(token)))


def set_password(conn: db.Connection, email: str, password: str, now: datetime | None = None) -> None:
    norm = clean_email(email)
    problem = security.password_problem(password, email=norm or "")
    if problem:
        raise ValidationFailed({"password": problem})
    row = conn.execute("SELECT id FROM users WHERE email = ?", (norm,)).fetchone()
    if row is None:
        raise ValidationFailed({"email": "No account with that email."})
    with db.transaction(conn, immediate=True):
        conn.execute("UPDATE users SET password_hash = ?, failed_attempts = 0, locked_until = NULL WHERE id = ?",
                     (security.hash_password(password), row["id"]))
        conn.execute("UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                     (db.db_timestamp(now or db.utcnow()), row["id"]))
