"""Safely snapshot a local SQLite file and import a snapshot into empty PostgreSQL.

This is intentionally separate from application startup: no records are copied unless an
operator supplies an explicit verified snapshot and the ``--apply`` flag.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from api import db

ROOT = Path(__file__).resolve().parents[1]
DATA_TABLES = ("users", "programmes", "enquiries")
TIMESTAMP_COLUMNS = {
    "users": ("locked_until", "created_at", "last_login_at"),
    "programmes": ("created_at",),
    "enquiries": ("consent_at", "created_at", "updated_at"),
}
IMPORT_COLUMNS = {
    "users": ("id", "email", "full_name", "password_hash", "role", "is_active", "failed_attempts",
              "locked_until", "created_at", "last_login_at"),
    "programmes": ("id", "name", "name_key", "is_active", "created_at"),
    "enquiries": ("id", "reference", "user_id", "full_name", "email", "phone", "programme_id",
                  "programme_label", "message", "consent", "consent_version", "consent_at", "status",
                  "admin_notes", "dedupe_hash", "created_at", "updated_at"),
}


class MigrationError(RuntimeError):
    """Safe, operator-facing migration validation error."""


def _resolve(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _live_sqlite_paths() -> set[Path]:
    return {_resolve(db.db_path()), _resolve(ROOT / "data" / "stif_campus.db")}


def _assert_snapshot_path(path: str | Path) -> Path:
    snapshot = _resolve(path)
    if snapshot in _live_sqlite_paths():
        raise MigrationError("Refusing to use the configured/live SQLite database; create a separate snapshot first.")
    if not snapshot.is_file():
        raise MigrationError("Snapshot file does not exist.")
    if not snapshot.name.lower().startswith("stif_snapshot_"):
        raise MigrationError("Snapshot file must use the stif_snapshot_ filename prefix.")
    return snapshot


def _open_snapshot(path: Path) -> sqlite3.Connection:
    # Read-only mode prevents accidental journal recovery or writes to the source snapshot.
    uri = "file:" + quote(path.as_posix(), safe="/:\\") + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        raise MigrationError("Could not open the SQLite snapshot.") from None
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _validate_snapshot(conn: sqlite3.Connection) -> dict[str, int]:
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise MigrationError("SQLite snapshot integrity check failed.")
        fk_problem = conn.execute("PRAGMA foreign_key_check").fetchone()
        if fk_problem is not None:
            raise MigrationError("SQLite snapshot contains a foreign-key violation.")
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        required = {"schema_migrations", "roles", "users", "sessions", "programmes", "enquiries"}
        if not required.issubset(tables):
            raise MigrationError("SQLite snapshot schema is incomplete.")
        versions = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
        if 1 not in versions:
            raise MigrationError("SQLite snapshot schema version is unsupported.")
        role_names = {row[0] for row in conn.execute("SELECT name FROM roles")}
        if not {"student", "admin"}.issubset(role_names):
            raise MigrationError("SQLite snapshot is missing required account roles.")
        return {table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in (*DATA_TABLES, "sessions")}
    except sqlite3.Error:
        raise MigrationError("Could not validate the SQLite snapshot schema or records.") from None


def _timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            raise MigrationError("Snapshot contains an invalid timestamp.") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return db.db_timestamp(parsed)


def _converted(table: str, row: sqlite3.Row) -> tuple[Any, ...]:
    values: list[Any] = []
    for column in IMPORT_COLUMNS[table]:
        value = row[column]
        if column in TIMESTAMP_COLUMNS[table]:
            value = _timestamp(value)
        elif column in {"is_active", "consent"}:
            value = bool(value)
        values.append(value)
    return tuple(values)


def create_snapshot(source: str | Path, output: str | Path) -> dict[str, Any]:
    """Create and verify an atomic, separate SQLite snapshot without changing source."""
    source_path = _resolve(source)
    target = _resolve(output)
    if source_path == target or target in _live_sqlite_paths():
        raise MigrationError("Snapshot output must be separate from the live SQLite database.")
    if target.exists():
        raise MigrationError("Snapshot output already exists; refusing to overwrite it.")
    if not source_path.is_file():
        raise MigrationError("SQLite source file does not exist.")
    if not target.name.lower().startswith("stif_snapshot_"):
        raise MigrationError("Snapshot output must use the stif_snapshot_ filename prefix.")

    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.with_name(f".{target.name}.tmp-{uuid.uuid4().hex}")
    src = sqlite3.connect("file:" + quote(source_path.as_posix(), safe="/:\\") + "?mode=ro", uri=True)
    dst: sqlite3.Connection | None = None
    try:
        dst = sqlite3.connect(str(temp_path))
        src.backup(dst)
        dst.close()
        dst = None
        snapshot = _open_snapshot(temp_path)
        try:
            counts = _validate_snapshot(snapshot)
        finally:
            snapshot.close()
        # Hard-link creation is atomic and refuses to replace a path created concurrently.
        os.link(temp_path, target)
        temp_path.unlink()
        return {"snapshot": str(target), "counts": counts}
    except MigrationError:
        raise
    except (sqlite3.Error, OSError):
        raise MigrationError("Could not create or verify a separate SQLite snapshot.") from None
    finally:
        src.close()
        if dst is not None:
            dst.close()
        if temp_path.exists():
            temp_path.unlink()


def _snapshot_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _destination_counts(conn: db.Connection) -> dict[str, int]:
    try:
        versions = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    except Exception:
        raise MigrationError("PostgreSQL schema is not initialized; run the backend schema initializer first.") from None
    if 1 not in versions:
        raise MigrationError("PostgreSQL schema version is unsupported.")
    try:
        return {table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in DATA_TABLES}
    except Exception:
        raise MigrationError("PostgreSQL destination schema is incomplete.") from None


def _verify_destination_foreign_keys(conn: db.Connection) -> None:
    checks = (
        "SELECT COUNT(*) FROM users u LEFT JOIN roles r ON r.name = u.role WHERE r.name IS NULL",
        "SELECT COUNT(*) FROM enquiries e LEFT JOIN users u ON u.id = e.user_id WHERE e.user_id IS NOT NULL AND u.id IS NULL",
        "SELECT COUNT(*) FROM enquiries e LEFT JOIN programmes p ON p.id = e.programme_id WHERE e.programme_id IS NOT NULL AND p.id IS NULL",
    )
    if any(conn.execute(sql).fetchone()[0] for sql in checks):
        raise MigrationError("PostgreSQL foreign-key validation failed; the transaction was rolled back.")


def migrate_snapshot(snapshot_path: str | Path, conn: db.Connection, *, apply: bool = False) -> dict[str, Any]:
    """Validate, dry-run, or transactionally import a verified snapshot into an empty PG target."""
    if db.database_backend() != "postgres":
        raise MigrationError("Set STIF_DATABASE_URL to PostgreSQL before migration validation.")
    snapshot_path = _assert_snapshot_path(snapshot_path)
    source = _open_snapshot(snapshot_path)
    try:
        source_counts = _validate_snapshot(source)
        digest = _snapshot_digest(snapshot_path)
        dest_before = _destination_counts(conn)
        if any(dest_before.values()):
            raise MigrationError("PostgreSQL destination is not empty; refusing to merge or duplicate records.")
        report: dict[str, Any] = {
            "status": "applied" if apply else "dry_run",
            "snapshot_sha256": digest,
            "source_counts": source_counts,
            "sessions_imported": 0,
            "destination_counts": dict(dest_before),
        }
        if not apply:
            return report

        with db.transaction(conn, immediate=True):
            conn.lock_key("sqlite-snapshot-import:" + digest)
            # Recheck after acquiring the transaction lock so concurrent import attempts cannot race.
            if any(_destination_counts(conn).values()):
                raise MigrationError("PostgreSQL destination became non-empty; refusing to merge records.")
            for role in source.execute("SELECT name FROM roles ORDER BY name"):
                conn.execute("INSERT INTO roles (name) VALUES (?) ON CONFLICT (name) DO NOTHING", (role[0],))
            for table in DATA_TABLES:
                columns = IMPORT_COLUMNS[table]
                column_sql = ", ".join(columns)
                placeholders = ", ".join("?" for _ in columns)
                query = f"INSERT INTO {table} ({column_sql}) VALUES ({placeholders})"
                for row in source.execute(f"SELECT {column_sql} FROM {table} ORDER BY id"):
                    conn.execute(query, _converted(table, row))

            for table in DATA_TABLES:
                conn.execute(
                    "SELECT setval(pg_get_serial_sequence(?, 'id'), COALESCE(MAX(id), 1), MAX(id) IS NOT NULL) "
                    f"FROM {table}",
                    (table,),
                )
            _verify_destination_foreign_keys(conn)
            destination_counts = _destination_counts(conn)
            if destination_counts != {table: source_counts[table] for table in DATA_TABLES}:
                raise MigrationError("PostgreSQL record-count validation failed; the transaction was rolled back.")
            report["destination_counts"] = destination_counts
        return report
    finally:
        source.close()


def _write_report(path: str | Path, report: dict[str, Any]) -> None:
    target = _resolve(path)
    if target.exists():
        raise MigrationError("Report output already exists; refusing to overwrite it.")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("x", encoding="utf-8") as output:
            json.dump(report, output, indent=2, sort_keys=True)
            output.write("\n")
    except OSError:
        raise MigrationError("Could not write migration report.") from None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Snapshot SQLite and explicitly import a snapshot into PostgreSQL.")
    commands = parser.add_subparsers(dest="command", required=True)
    snapshot = commands.add_parser("snapshot", help="Create a separate, integrity-checked SQLite snapshot.")
    snapshot.add_argument("--source", default=db.db_path(), help="SQLite source file (default: STIF_DB_PATH).")
    snapshot.add_argument("--output", required=True, help="New stif_snapshot_*.db path; existing files are never replaced.")
    run = commands.add_parser("run", help="Dry-run or explicitly import a verified SQLite snapshot.")
    run.add_argument("--snapshot", required=True, help="Separate stif_snapshot_*.db file.")
    mode = run.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Validate and report only; do not write to PostgreSQL.")
    mode.add_argument("--apply", action="store_true", help="Initialize PostgreSQL schema and import in one transaction.")
    run.add_argument("--report", help="Optional new JSON report path; existing files are not overwritten.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "snapshot":
            report = create_snapshot(args.source, args.output)
        else:
            if db.database_backend() != "postgres":
                raise MigrationError("Set STIF_DATABASE_URL to a PostgreSQL URL before migration validation.")
            if args.report and _resolve(args.report).exists():
                raise MigrationError("Report output already exists; refusing to overwrite it.")
            if args.apply:
                snapshot = _assert_snapshot_path(args.snapshot)
                source = _open_snapshot(snapshot)
                try:
                    _validate_snapshot(source)
                finally:
                    source.close()
                db.init_db()
            conn = db.connect()
            try:
                report = migrate_snapshot(args.snapshot, conn, apply=args.apply)
            finally:
                conn.close()
            if args.report:
                _write_report(args.report, report)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except (MigrationError, db.DatabaseConfigurationError, db.DatabaseUnavailable) as exc:
        print(f"Migration stopped: {exc}", file=sys.stderr)
        return 2
    except Exception:
        # Driver/file exceptions may carry host, SQL or path details; keep CLI output generic.
        print("Migration stopped because of an unexpected database or file error.", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
