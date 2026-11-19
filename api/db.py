"""SQLite persistence for users, sessions, programmes and enquiries.

Standard library only. Configure the file with ``STIF_DB_PATH`` (default
``data/stif_campus.db``). The schema is created/upgraded by ``init_db`` using
numbered, idempotent migrations recorded in ``schema_migrations``; existing data is
never dropped. The knowledge-base index files in ``data/`` are not touched.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Each migration is a list of statements run inside one transaction.
MIGRATIONS: list[tuple[int, list[str]]] = [
    (1, [
        """CREATE TABLE roles (name TEXT PRIMARY KEY)""",
        # Parent access can later be added with a new migration: INSERT INTO roles VALUES ('parent').
        """INSERT INTO roles (name) VALUES ('student'), ('admin')""",
        """CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            full_name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL REFERENCES roles(name),
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            failed_attempts INTEGER NOT NULL DEFAULT 0,
            locked_until TEXT,
            created_at TEXT NOT NULL,
            last_login_at TEXT
        )""",
        """CREATE TABLE sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token_hash TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            revoked_at TEXT
        )""",
        """CREATE INDEX idx_sessions_user ON sessions(user_id)""",
        """CREATE TABLE programmes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            name_key TEXT NOT NULL UNIQUE,
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            created_at TEXT NOT NULL
        )""",
        """CREATE TABLE enquiries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference TEXT UNIQUE,
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            full_name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT NOT NULL,
            programme_id INTEGER REFERENCES programmes(id),
            programme_label TEXT NOT NULL,
            message TEXT NOT NULL,
            consent INTEGER NOT NULL CHECK (consent = 1),
            consent_version TEXT NOT NULL,
            consent_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'new'
                CHECK (status IN ('new', 'in_progress', 'responded', 'closed')),
            admin_notes TEXT NOT NULL DEFAULT '',
            dedupe_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""",
        """CREATE INDEX idx_enquiries_status ON enquiries(status)""",
        """CREATE INDEX idx_enquiries_created ON enquiries(created_at)""",
        """CREATE INDEX idx_enquiries_dedupe ON enquiries(dedupe_hash, created_at)""",
        """CREATE INDEX idx_enquiries_email ON enquiries(email, created_at)""",
        """CREATE INDEX idx_enquiries_user ON enquiries(user_id)""",
    ]),
]


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def db_path() -> str:
    configured = (os.getenv("STIF_DB_PATH") or "").strip()
    return configured or str(ROOT / "data" / "stif_campus.db")


def connect(path: str | None = None) -> sqlite3.Connection:
    """Open a connection in autocommit mode; use ``transaction`` for atomic blocks."""
    # check_same_thread=False: FastAPI may run a request's dependency and handler on different
    # worker threads; each request owns its connection and uses it sequentially.
    conn = sqlite3.connect(path or db_path(), timeout=15, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection, *, immediate: bool = False):
    conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def init_db(path: str | None = None) -> list[int]:
    """Create or upgrade the schema. Safe to call repeatedly. Returns newly applied versions."""
    target = path or db_path()
    if target != ":memory:":
        Path(target).parent.mkdir(parents=True, exist_ok=True)
    conn = connect(target)
    applied: list[int] = []
    try:
        if target != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        done = {r["version"] for r in conn.execute("SELECT version FROM schema_migrations")}
        for version, statements in MIGRATIONS:
            if version in done:
                continue
            with transaction(conn, immediate=True):
                for statement in statements:
                    conn.execute(statement)
                conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (version, iso(utcnow())),
                )
            applied.append(version)
    finally:
        conn.close()
    return applied


_init_lock = threading.Lock()
_initialised: set[str] = set()


def ensure_initialized() -> None:
    """Lazy, once-per-process schema check so the API works regardless of startup hooks."""
    target = db_path()
    if target in _initialised:
        return
    with _init_lock:
        if target not in _initialised:
            init_db(target)
            _initialised.add(target)


@contextmanager
def session():
    ensure_initialized()
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
