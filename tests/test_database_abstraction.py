"""Focused tests for the SQLite implementation of the database boundary."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from api import db


class DatabaseBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = str(Path(self.temp_dir.name) / "boundary.db")
        self.assertEqual(db.init_db(self.path), [1])
        self.conn = db.connect(self.path)
        self.addCleanup(self.conn.close)

    def test_sqlite_is_the_only_active_connection_and_rows_are_normalized(self):
        self.assertIsInstance(self.conn, db.SQLiteConnection)
        created_id = self.conn.insert_id(
            "INSERT INTO programmes (name, name_key, created_at) VALUES (?, ?, ?)",
            ("Computer Science", "computer science", "2026-11-20T00:00:00Z"),
        )
        result = self.conn.execute("SELECT id, name FROM programmes WHERE id = ?", (created_id,))
        row = result.fetchone()
        self.assertEqual(row["id"], created_id)
        self.assertEqual(row[1], "Computer Science")
        self.assertEqual(row.keys(), ("id", "name"))
        self.assertIsNone(result.fetchone())

    def test_execute_normalizes_parameters_and_result_iteration(self):
        self.conn.execute(
            "INSERT INTO programmes (name, name_key, created_at) VALUES (?, ?, ?)",
            ["Computer Science", "computer science", "2026-11-20T00:00:00Z"],
        )
        rows = list(self.conn.execute("SELECT name FROM programmes ORDER BY id"))
        self.assertEqual([row["name"] for row in rows], ["Computer Science"])

    def test_transaction_rolls_back_on_error(self):
        with self.assertRaisesRegex(RuntimeError, "rollback test"):
            with db.transaction(self.conn, immediate=True):
                self.conn.insert_id(
                    "INSERT INTO programmes (name, name_key, created_at) VALUES (?, ?, ?)",
                    ("Computer Science", "computer science", "2026-11-20T00:00:00Z"),
                )
                raise RuntimeError("rollback test")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM programmes").fetchone()[0], 0)

    def test_schema_initialization_remains_idempotent_and_preserves_constraints(self):
        self.assertEqual(db.init_db(self.path), [])
        tables = {row[0] for row in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = ?", ("table",)
        )}
        self.assertTrue({"roles", "users", "sessions", "programmes", "enquiries", "schema_migrations"} <= tables)
        self.assertEqual(self.conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.assertEqual([row[0] for row in self.conn.execute("SELECT version FROM schema_migrations")], [1])


if __name__ == "__main__":
    unittest.main()
