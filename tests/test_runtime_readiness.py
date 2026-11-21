from __future__ import annotations

import os
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest import mock

from fastapi import Response
from fastapi.testclient import TestClient

from api import db
from api.main import (PAGES_FRONTEND_ORIGIN, app, configured_allowed_hosts,
                      configured_cors_origins, enforce_production_database, readiness)


class RuntimeReadinessTests(unittest.TestCase):
    def test_production_mode_refuses_sqlite(self):
        with mock.patch.dict(os.environ, {"STIF_ENV": "production", "STIF_DATABASE_URL": ""}):
            with self.assertRaisesRegex(RuntimeError, "requires PostgreSQL"):
                enforce_production_database()

    def test_production_mode_accepts_explicit_postgres_selection(self):
        with mock.patch.dict(os.environ, {"STIF_ENV": "production", "STIF_DATABASE_URL": "postgresql://private"}), \
             mock.patch("api.main.db.database_backend", return_value="postgres"):
            enforce_production_database()

    def test_cors_accepts_only_explicit_https_or_loopback_origins(self):
        with mock.patch.dict(os.environ, {"STIF_CORS_ORIGINS": "https://app.example.edu, http://localhost:5173"}):
            self.assertEqual(configured_cors_origins(), [
                "https://app.example.edu", "http://localhost:5173", PAGES_FRONTEND_ORIGIN,
            ])
        for origin in ("*", "http://example.edu", "https://app.example.edu/path", "https://user:pass@app.example.edu"):
            with self.subTest(origin=origin), mock.patch.dict(os.environ, {"STIF_CORS_ORIGINS": origin}):
                with self.assertRaisesRegex(RuntimeError, "explicit HTTPS origins"):
                    configured_cors_origins()

    def test_pages_origin_is_allowed_for_post_preflight(self):
        client = TestClient(app)
        origin_header = {"Origin": PAGES_FRONTEND_ORIGIN}
        health = client.get("/health", headers=origin_header)
        self.assertEqual(health.headers["access-control-allow-origin"], PAGES_FRONTEND_ORIGIN)

        response = client.options("/api/v1/chat", headers={
            **origin_header,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], PAGES_FRONTEND_ORIGIN)
        self.assertEqual(response.headers["access-control-allow-credentials"], "true")
        self.assertIn("POST", response.headers["access-control-allow-methods"])
        self.assertIn("content-type", response.headers["access-control-allow-headers"].lower())

    def test_host_allowlist_rejects_wildcards_and_malformed_hosts(self):
        with mock.patch.dict(os.environ, {"STIF_ALLOWED_HOSTS": "api.example.edu,localhost"}):
            self.assertEqual(configured_allowed_hosts(), ["api.example.edu", "localhost"])
        for hosts in ("*", "api.example.edu/path", "api..example.edu"):
            with self.subTest(hosts=hosts), mock.patch.dict(os.environ, {"STIF_ALLOWED_HOSTS": hosts}):
                with self.assertRaisesRegex(RuntimeError, "explicit hostnames"):
                    configured_allowed_hosts()

    def test_readiness_reports_ready_without_database_details(self):
        result = SimpleNamespace(fetchone=lambda: (1,))

        @contextmanager
        def session():
            yield SimpleNamespace(execute=mock.Mock(return_value=result))

        response = Response()
        with mock.patch("api.main.db.session", side_effect=session):
            self.assertEqual(readiness(response), {"status": "ready"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_readiness_checks_opted_in_remote_storage_without_details(self):
        result = SimpleNamespace(fetchone=lambda: (1,))

        @contextmanager
        def session():
            yield SimpleNamespace(execute=mock.Mock(return_value=result))

        response = Response()
        with mock.patch("api.main.db.session", side_effect=session), \
             mock.patch("api.main.storage_backend", return_value="r2"), \
             mock.patch("api.main.get_storage") as get_storage:
            get_storage.return_value.check_ready.return_value = False
            self.assertEqual(readiness(response), {"status": "not_ready"})
        self.assertEqual(response.status_code, 503)

    def test_readiness_returns_generic_unavailable_status(self):
        @contextmanager
        def unavailable():
            raise db.DatabaseUnavailable("private connection detail")
            yield  # pragma: no cover - makes this function a context manager

        response = Response()
        with mock.patch("api.main.db.session", side_effect=unavailable):
            self.assertEqual(readiness(response), {"status": "not_ready"})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private connection detail", response.body.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
