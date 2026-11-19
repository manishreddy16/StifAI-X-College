"""Helpers for the Campus AI (accounts + enquiries) tests. Standard library only."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from api import db

GOOD_PASSWORD = "Correct-Horse-42"
T0 = datetime(2026, 11, 19, 10, 0, 0, tzinfo=timezone.utc)


class DbTestCase(unittest.TestCase):
    """Each test gets a fresh SQLite file with the real migrations applied."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_file = str(Path(self._tmp.name) / "test.db")
        db.init_db(self.db_file)
        self.conn = db.connect(self.db_file)
        self.addCleanup(self.conn.close)

    def add_programme(self, name="Test Programme"):
        from api import enquiry_service
        return enquiry_service.add_programme(self.conn, name, now=T0)["id"]


def valid_enquiry(**over):
    data = {
        "full_name": "Anita Reddy", "email": "Anita.Reddy@example.com", "phone": "98765 43210",
        "programme_id": None, "programme_other": "", "consent": True,
        "message": "What documents are needed for admission counselling?",
    }
    data.update(over)
    return data
