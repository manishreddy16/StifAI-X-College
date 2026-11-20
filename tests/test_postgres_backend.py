"""PostgreSQL adapter tests use fakes; real integration is gated to a disposable DB."""

from __future__ import annotations

import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from unittest import mock
from urllib.parse import urlsplit
from uuid import uuid4

from api import auth_service, db, enquiry_service
from api.errors import RateLimited
from api.migrate_sqlite import MigrationError, create_snapshot, migrate_snapshot
from tests._campus_support import GOOD_PASSWORD, valid_enquiry


class FakeIntegrityError(Exception):
    pass


class FakeCursor:
    def __init__(self, rows=(), columns=()):
        self.rows = list(rows)
        self.description = [SimpleNamespace(name=name) for name in columns] or None
        self.rowcount = len(self.rows)

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        rows, self.rows = self.rows, []
        return rows

    def __iter__(self):
        while self.rows:
            yield self.rows.pop(0)


class FakePostgresState:
    def __init__(self):
        self.calls = []
        self.migration_versions = set()
        self.integrity_error = False


class FakeRawConnection:
    def __init__(self, state):
        self.state = state
        self.closed = False

    def execute(self, sql, parameters=()):
        self.state.calls.append((sql, tuple(parameters)))
        if self.state.integrity_error:
            raise FakeIntegrityError("sensitive driver detail")
        if sql == "SELECT version FROM schema_migrations":
            return FakeCursor([(v,) for v in sorted(self.state.migration_versions)], ("version",))
        if sql.startswith("INSERT INTO schema_migrations"):
            self.state.migration_versions.add(parameters[0])
        if "RETURNING id" in sql:
            return FakeCursor([(73,)], ("id",))
        if sql.startswith("SELECT id, created_at, is_active"):
            return FakeCursor([(7, datetime(2026, 11, 20, 12, tzinfo=timezone.utc), True)],
                              ("id", "created_at", "is_active"))
        return FakeCursor()

    def close(self):
        self.closed = True


class FakePsycopg:
    IntegrityError = FakeIntegrityError

    def __init__(self, state):
        self.state = state
        self.connect = mock.Mock(side_effect=lambda *a, **k: FakeRawConnection(state))


class PostgreSQLAdapterTests(unittest.TestCase):
    def setUp(self):
        self.state = FakePostgresState()
        self.raw = FakeRawConnection(self.state)
        self.conn = db.PostgreSQLConnection(self.raw, FakeIntegrityError)

    def test_qmark_conversion_skips_literals_identifiers_and_comments(self):
        sql = "SELECT '?' AS literal, \"?\" AS quoted, ? AS value -- ?\n, $$?$$ AS body, /* ? */ ?"
        self.assertEqual(
            db._translate_qmark_sql(sql),
            "SELECT '?' AS literal, \"?\" AS quoted, %s AS value -- ?\n, $$?$$ AS body, /* ? */ %s",
        )

    def test_execute_and_generated_id_use_postgres_parameter_and_returning_contract(self):
        self.assertEqual(self.conn.insert_id("INSERT INTO programmes(name) VALUES (?)", ("CS",)), 73)
        sql, params = self.state.calls[-1]
        self.assertEqual(sql, "INSERT INTO programmes(name) VALUES (%s) RETURNING id")
        self.assertEqual(params, ("CS",))

    def test_rows_normalize_timestamp_boolean_and_positional_access(self):
        row = self.conn.execute("SELECT id, created_at, is_active FROM programmes").fetchone()
        self.assertEqual(row["id"], 7)
        self.assertEqual(row[1], "2026-11-20T12:00:00Z")
        self.assertIs(row["is_active"], True)

    def test_integrity_errors_are_normalized_without_driver_details(self):
        self.state.integrity_error = True
        with self.assertRaises(db.DatabaseIntegrityError) as caught:
            self.conn.execute("INSERT INTO users(email) VALUES (?)", ("private@example.test",))
        self.assertEqual(str(caught.exception), "Database constraint violation.")
        self.assertIsNone(caught.exception.__cause__)

    def test_explicit_transactions_commit_and_rollback(self):
        with db.transaction(self.conn, immediate=True):
            self.conn.execute("UPDATE users SET is_active = ? WHERE id = ?", (True, 1))
        self.assertEqual(self.state.calls[0][0], "BEGIN")
        self.assertEqual(self.state.calls[-1][0], "COMMIT")

        self.state.calls.clear()
        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with db.transaction(self.conn, immediate=True):
                raise RuntimeError("rollback")
        self.assertEqual(self.state.calls[-1][0], "ROLLBACK")

    def test_advisory_lock_uses_stable_signed_key(self):
        self.conn.lock_key("enquiry-email:student@example.test")
        sql, params = self.state.calls[-1]
        self.assertEqual(sql, "SELECT pg_advisory_xact_lock(%s)")
        self.assertIsInstance(params[0], int)
        self.assertGreaterEqual(params[0], -(2**63))
        self.assertLess(params[0], 2**63)


class BackendSelectionTests(unittest.TestCase):
    def test_sqlite_remains_default_and_explicit_test_paths_stay_sqlite(self):
        with mock.patch.dict(os.environ, {"STIF_DATABASE_URL": ""}, clear=False):
            self.assertEqual(db.database_backend(), "sqlite")
            conn = db.connect(":memory:")
        try:
            self.assertIsInstance(conn, db.SQLiteConnection)
        finally:
            conn.close()

    def test_explicit_postgres_selection_never_falls_back_when_driver_missing(self):
        env = {"STIF_DATABASE_URL": "postgresql://user:password@localhost/stif_test", "STIF_DB_PATH": "unused.db"}
        with mock.patch.dict(os.environ, env), \
             mock.patch("api.db._load_psycopg", side_effect=db.DatabaseUnavailable("driver missing")), \
             mock.patch("api.db.sqlite3.connect") as sqlite_connect:
            with self.assertRaises(db.DatabaseUnavailable):
                db.connect()
        sqlite_connect.assert_not_called()

    def test_invalid_postgres_url_fails_without_attempting_sqlite(self):
        with mock.patch.dict(os.environ, {"STIF_DATABASE_URL": "not-a-postgres-url"}), \
             mock.patch("api.db.sqlite3.connect") as sqlite_connect:
            with self.assertRaises(db.DatabaseConfigurationError):
                db.connect()
        sqlite_connect.assert_not_called()

    def test_connection_error_is_sanitized(self):
        fake = FakePsycopg(FakePostgresState())
        fake.connect.side_effect = RuntimeError("failed URL password=do-not-show")
        with mock.patch.dict(os.environ, {"STIF_DATABASE_URL": "postgresql://user:secret@localhost/stif_test"}), \
             mock.patch("api.db._load_psycopg", return_value=(fake, object())):
            with self.assertRaises(db.DatabaseUnavailable) as caught:
                db.connect()
        self.assertNotIn("secret", str(caught.exception))
        self.assertNotIn("do-not-show", str(caught.exception))

    def test_postgres_migrations_use_a_transaction_lock_and_are_versioned(self):
        state = FakePostgresState()
        fake = FakePsycopg(state)
        env = {"STIF_DATABASE_URL": "postgresql://user:secret@localhost/stif_test"}
        with mock.patch.dict(os.environ, env), mock.patch("api.db._load_psycopg", return_value=(fake, object())):
            self.assertEqual(db.init_db(), [1])
            self.assertEqual(db.init_db(), [])
        first_sql = [sql for sql, _ in state.calls]
        self.assertEqual(first_sql[0], "BEGIN")
        self.assertEqual(first_sql[1], "SELECT pg_advisory_xact_lock(%s)")
        self.assertIn("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL)", first_sql)
        self.assertEqual(state.migration_versions, {1})


def _integration_db_is_explicitly_disposable() -> bool:
    url = os.getenv("STIF_TEST_POSTGRES_URL", "").strip()
    ack = os.getenv("STIF_TEST_POSTGRES_DISPOSABLE") == "I_UNDERSTAND_THIS_DATABASE_IS_DISPOSABLE"
    parsed = urlsplit(url)
    database = parsed.path.strip("/")
    host = (parsed.hostname or "").lower()
    return bool(url and ack and parsed.scheme in {"postgres", "postgresql"}
                and database.startswith("stif_test_") and not host.endswith(".neon.tech"))


@unittest.skipUnless(_integration_db_is_explicitly_disposable(),
                     "requires an explicitly disposable local/CI PostgreSQL database named stif_test_*")
class PostgreSQLIntegrationTests(unittest.TestCase):
    """Only run against an explicitly named disposable PostgreSQL database."""

    @classmethod
    def setUpClass(cls):
        cls._old_database_url = os.environ.get("STIF_DATABASE_URL")
        os.environ["STIF_DATABASE_URL"] = os.environ["STIF_TEST_POSTGRES_URL"]
        cls.initial_migrations = db.init_db()
        cls.repeat_migrations = db.init_db()

    @classmethod
    def tearDownClass(cls):
        if cls._old_database_url is None:
            os.environ.pop("STIF_DATABASE_URL", None)
        else:
            os.environ["STIF_DATABASE_URL"] = cls._old_database_url

    def test_00_synthetic_snapshot_import_preserves_records_and_skips_sessions(self):
        marker = uuid4().hex
        with tempfile.TemporaryDirectory() as temp:
            source_path = Path(temp) / "source.db"
            snapshot_path = Path(temp) / "stif_snapshot_synthetic.db"
            db.init_db(str(source_path))
            source_conn = db.connect(str(source_path))
            try:
                user = auth_service.register_student(
                    source_conn, email=f"migration-{marker}@example.test", full_name="Migration Student",
                    password=GOOD_PASSWORD,
                )
                session_token, _ = auth_service.create_session(source_conn, user.id)
                programme = enquiry_service.add_programme(source_conn, f"Migration Programme {marker[:8]}")
                enquiry = enquiry_service.submit_enquiry(
                    source_conn,
                    valid_enquiry(email=user.email, programme_id=programme["id"],
                                  message=f"Migration fixture question {marker}"),
                    user=user,
                )
                source_hash = source_conn.execute("SELECT password_hash FROM users WHERE id = ?", (user.id,)).fetchone()[0]
                source_enquiry_id = source_conn.execute(
                    "SELECT id FROM enquiries WHERE reference = ?", (enquiry["enquiry"]["reference"],)
                ).fetchone()[0]
                self.assertTrue(session_token)
            finally:
                source_conn.close()
            create_snapshot(source_path, snapshot_path)

            conn = db.connect()
            try:
                report = migrate_snapshot(snapshot_path, conn, apply=True)
                self.assertEqual(report["status"], "applied")
                self.assertEqual(report["source_counts"], {"users": 1, "programmes": 1, "enquiries": 1, "sessions": 1})
                self.assertEqual(report["sessions_imported"], 0)
                imported = conn.execute("SELECT * FROM users WHERE id = ?", (user.id,)).fetchone()
                self.assertEqual(imported["email"], user.email)
                self.assertEqual(imported["password_hash"], source_hash)
                self.assertEqual(imported["role"], "student")
                self.assertEqual(imported["is_active"], True)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0)
                imported_enquiry = conn.execute("SELECT id, reference, user_id, programme_id FROM enquiries").fetchone()
                self.assertEqual(imported_enquiry["id"], source_enquiry_id)
                self.assertEqual(imported_enquiry["user_id"], user.id)
                self.assertEqual(imported_enquiry["programme_id"], programme["id"])
                next_user = auth_service.register_student(
                    conn, email=f"sequence-{marker}@example.test", full_name="Sequence Test", password=GOOD_PASSWORD,
                )
                self.assertGreater(next_user.id, user.id)
                with self.assertRaisesRegex(MigrationError, "not empty"):
                    migrate_snapshot(snapshot_path, conn, apply=True)
            finally:
                conn.close()

    def test_account_session_programme_and_enquiry_contracts(self):
        self.assertEqual(self.initial_migrations, [1])
        self.assertEqual(self.repeat_migrations, [])
        marker = uuid4().hex
        conn = db.connect()
        try:
            user = auth_service.register_student(
                conn, email=f"{marker}@example.test", full_name="Test Student", password=GOOD_PASSWORD,
            )
            self.assertEqual(auth_service.authenticate(conn, user.email, GOOD_PASSWORD).id, user.id)
            token, expires = auth_service.create_session(conn, user.id)
            self.assertIsNotNone(auth_service.user_for_token(conn, token))
            auth_service.revoke_token(conn, token)
            self.assertIsNone(auth_service.user_for_token(conn, token))

            programme = enquiry_service.add_programme(conn, f"Test Programme {marker}")
            payload = valid_enquiry(email=f"{marker}@example.test", programme_id=programme["id"],
                                    message=f"Question for test {marker}")
            first = enquiry_service.submit_enquiry(conn, payload, user=user)
            second = enquiry_service.submit_enquiry(conn, payload, user=user)
            self.assertFalse(first["duplicate"])
            self.assertTrue(second["duplicate"])
            self.assertEqual(first["enquiry"]["reference"], second["enquiry"]["reference"])
            self.assertTrue(expires)
        finally:
            conn.close()

    def test_real_connection_close_integrity_normalization_and_rollback(self):
        marker = uuid4().hex
        conn = db.connect()
        raw = conn._raw
        try:
            user = auth_service.register_student(
                conn, email=f"rollback-{marker}@example.test", full_name="Rollback Test", password=GOOD_PASSWORD,
            )
            conflict = auth_service.register_student(
                conn, email=f"conflict-{marker}@example.test", full_name="Conflict Test", password=GOOD_PASSWORD,
            )
            with self.assertRaises(db.DatabaseIntegrityError):
                conn.execute("UPDATE users SET email = ? WHERE id = ?", (conflict.email, user.id))

            rollback_email = f"rolled-back-{marker}@example.test"
            with self.assertRaisesRegex(RuntimeError, "rollback marker"):
                with db.transaction(conn):
                    auth_service.register_student(
                        conn, email=rollback_email, full_name="Rollback Test", password=GOOD_PASSWORD,
                    )
                    raise RuntimeError("rollback marker")
            self.assertIsNone(conn.execute("SELECT id FROM users WHERE email = ?", (rollback_email,)).fetchone())
            timestamp = conn.execute("SELECT created_at FROM users WHERE id = ?", (user.id,)).fetchone()[0]
            self.assertEqual(timestamp[-1], "Z")
        finally:
            conn.close()
        self.assertTrue(raw.closed)

    def test_concurrent_schema_initialization_is_serialized_and_idempotent(self):
        barrier = Barrier(4)

        def initialize(_):
            barrier.wait(timeout=5)
            return db.init_db()

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(initialize, range(4)))
        self.assertEqual(results, [[], [], [], []])

    def test_http_auth_permissions_ownership_search_management_and_logout(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from api.campus import install_campus_routes

        marker = uuid4().hex
        app = FastAPI()
        install_campus_routes(app)
        student = TestClient(app)
        second_student = TestClient(app)
        admin = TestClient(app)
        headers = {"X-Requested-With": "stif-campus"}
        student_email = f"student-{marker}@example.test"
        second_email = f"student-two-{marker}@example.test"
        admin_email = f"admin-{marker}@example.test"

        registered = student.post("/api/v1/auth/register", headers=headers, json={
            "email": student_email, "full_name": "Test Student", "password": GOOD_PASSWORD, "role": "admin",
        })
        self.assertEqual(registered.status_code, 201)
        self.assertEqual(registered.json()["user"]["role"], "student")
        self.assertNotIn("password_hash", registered.text)
        self.assertEqual(student.get("/api/v1/auth/me").json()["user"]["email"], student_email)

        conn = db.connect()
        try:
            auth_service.create_user(conn, email=admin_email, full_name="Test Admin", password=GOOD_PASSWORD,
                                     role="admin")
            expiring_user = auth_service.register_student(
                conn, email=f"expiry-{marker}@example.test", full_name="Expiry Test", password=GOOD_PASSWORD,
            )
            expiring_token, _ = auth_service.create_session(conn, expiring_user.id, ttl_hours=0.25)
            self.assertIsNone(auth_service.user_for_token(
                conn, expiring_token, now=db.utcnow() + timedelta(minutes=16),
            ))
        finally:
            conn.close()

        self.assertEqual(student.get("/api/v1/admin/stats").status_code, 403)
        self.assertEqual(admin.get("/api/v1/admin/stats").status_code, 401)
        login = admin.post("/api/v1/auth/login", headers=headers,
                           json={"email": admin_email, "password": GOOD_PASSWORD})
        self.assertEqual(login.status_code, 200)
        self.assertEqual(login.json()["user"]["role"], "admin")

        programme_response = admin.post("/api/v1/admin/programmes", headers=headers,
                                        json={"name": f"Phase A {marker[:8]}"})
        self.assertEqual(programme_response.status_code, 201)
        programme_id = programme_response.json()["programme"]["id"]
        for client, email, message in (
            (student, student_email, f"Question about admissions {marker}"),
            (second_student, second_email, f"Question about hostel facilities {marker}"),
        ):
            if client is second_student:
                result = client.post("/api/v1/auth/register", headers=headers, json={
                    "email": email, "full_name": "Second Student", "password": GOOD_PASSWORD,
                })
                self.assertEqual(result.status_code, 201)
            payload = valid_enquiry(email=email, programme_id=programme_id, message=message)
            self.assertEqual(client.post("/api/v1/enquiries", headers=headers, json=payload).status_code, 201)

        owned = student.get("/api/v1/enquiries/mine")
        self.assertEqual(owned.status_code, 200)
        self.assertEqual(len(owned.json()["items"]), 1)
        self.assertIn("admissions", owned.json()["items"][0]["message"])
        filtered = admin.get("/api/v1/admin/enquiries", params={"status": "new", "q": marker})
        self.assertEqual(filtered.status_code, 200)
        self.assertEqual(filtered.json()["total"], 2)
        enquiry_id = filtered.json()["items"][0]["id"]
        self.assertEqual(admin.patch(f"/api/v1/admin/enquiries/{enquiry_id}", headers=headers,
                                     json={"status": "responded"}).json()["enquiry"]["status"], "responded")
        self.assertGreaterEqual(admin.get("/api/v1/admin/stats").json()["by_status"]["responded"], 1)
        deactivated = admin.patch(f"/api/v1/admin/programmes/{programme_id}", headers=headers,
                                  json={"is_active": False})
        self.assertFalse(deactivated.json()["programme"]["is_active"])

        replay = TestClient(app)
        replay.cookies.set("stif_session", student.cookies.get("stif_session"))
        self.assertEqual(student.post("/api/v1/auth/logout", headers=headers).json(), {"ok": True})
        self.assertIsNone(replay.get("/api/v1/auth/me").json()["user"])

    def test_concurrent_duplicate_submissions_and_daily_cap(self):
        marker = uuid4().hex
        duplicate_payload = valid_enquiry(email=f"{marker}@example.test", message=f"Same question {marker}")

        def submit(payload):
            conn = db.connect()
            try:
                return enquiry_service.submit_enquiry(conn, payload)
            finally:
                conn.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            duplicate_results = list(pool.map(submit, [duplicate_payload, duplicate_payload]))
        self.assertEqual(sum(not result["duplicate"] for result in duplicate_results), 1)

        cap_email = f"cap-{marker}@example.test"
        payloads = [valid_enquiry(email=cap_email, message=f"Question number {i} {marker}")
                    for i in range(enquiry_service.MAX_PER_EMAIL_PER_DAY + 2)]
        def submit_capped(payload):
            try:
                return submit(payload)
            except RateLimited:
                return None
        with ThreadPoolExecutor(max_workers=len(payloads)) as pool:
            cap_results = list(pool.map(submit_capped, payloads))
        self.assertEqual(sum(result is not None for result in cap_results), enquiry_service.MAX_PER_EMAIL_PER_DAY)


if __name__ == "__main__":
    unittest.main()
