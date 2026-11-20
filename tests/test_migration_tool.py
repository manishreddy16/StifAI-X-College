"""Synthetic SQLite snapshot tests for the guarded SQLite-to-PostgreSQL tool."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from api import auth_service, db, enquiry_service
from api.migrate_sqlite import MigrationError, _open_snapshot, _validate_snapshot, create_snapshot, main
from tests._campus_support import GOOD_PASSWORD, T0, valid_enquiry


class SQLiteSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source_path = self.root / "source.db"
        db.init_db(str(self.source_path))
        conn = db.connect(str(self.source_path))
        try:
            user = auth_service.register_student(
                conn, email="migration-student@example.test", full_name="Migration Student",
                password=GOOD_PASSWORD, now=T0,
            )
            token, _ = auth_service.create_session(conn, user.id, now=T0)
            self.assertTrue(token)
            programme = enquiry_service.add_programme(conn, "Migration Test Programme", now=T0)
            enquiry_service.submit_enquiry(
                conn,
                valid_enquiry(email=user.email, programme_id=programme["id"],
                              message="Migration fixture asks about admission requirements."),
                user=user,
                now=T0,
            )
        finally:
            conn.close()

    def test_snapshot_is_separate_integrity_checked_and_does_not_change_source(self):
        output = self.root / "stif_snapshot_synthetic.db"
        before = hashlib.sha256(self.source_path.read_bytes()).hexdigest()
        result = create_snapshot(self.source_path, output)
        after = hashlib.sha256(self.source_path.read_bytes()).hexdigest()
        self.assertEqual(before, after)
        self.assertEqual(result["counts"], {"users": 1, "programmes": 1, "enquiries": 1, "sessions": 1})
        snapshot = _open_snapshot(output)
        try:
            self.assertEqual(_validate_snapshot(snapshot), result["counts"])
        finally:
            snapshot.close()
        with self.assertRaisesRegex(MigrationError, "already exists"):
            create_snapshot(self.source_path, output)

    def test_refuses_live_database_as_snapshot_or_output(self):
        with mock.patch("api.migrate_sqlite.db.db_path", return_value=str(self.source_path)):
            with self.assertRaisesRegex(MigrationError, "live SQLite"):
                from api.migrate_sqlite import _assert_snapshot_path
                _assert_snapshot_path(self.source_path)
            with self.assertRaisesRegex(MigrationError, "separate"):
                create_snapshot(self.source_path, self.source_path)

    def test_snapshot_requires_prefix_and_supported_schema(self):
        wrong_name = self.root / "copy.db"
        wrong_name.write_bytes(self.source_path.read_bytes())
        with self.assertRaisesRegex(MigrationError, "filename prefix"):
            from api.migrate_sqlite import _assert_snapshot_path
            _assert_snapshot_path(wrong_name)

        invalid = self.root / "invalid.db"
        import sqlite3
        conn = sqlite3.connect(invalid)
        conn.execute("CREATE TABLE not_stif (id INTEGER PRIMARY KEY)")
        conn.close()
        with self.assertRaisesRegex(MigrationError, "schema is incomplete"):
            create_snapshot(invalid, self.root / "stif_snapshot_invalid.db")

    def test_import_cli_refuses_sqlite_backend(self):
        snapshot = self.root / "stif_snapshot_cli.db"
        create_snapshot(self.source_path, snapshot)
        with mock.patch("api.migrate_sqlite.db.database_backend", return_value="sqlite"):
            self.assertEqual(main(["run", "--snapshot", str(snapshot), "--dry-run"]), 2)


if __name__ == "__main__":
    unittest.main()
