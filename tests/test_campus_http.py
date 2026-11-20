"""HTTP-level tests for accounts, enquiries and admin APIs (FastAPI TestClient).

Skipped automatically when fastapi/httpx are not installed (same convention as test_backend_llm_flow.py).
"""

import os
import tempfile
import unittest
from pathlib import Path

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    HAVE_STACK = True
except Exception:  # pragma: no cover
    HAVE_STACK = False

from tests._campus_support import GOOD_PASSWORD, valid_enquiry

H = {"X-Requested-With": "stif-campus"}


@unittest.skipUnless(HAVE_STACK, "fastapi/httpx not installed in this environment")
class CampusHttpTests(unittest.TestCase):
    def setUp(self):
        from api import auth_service, db, routes_auth, routes_enquiries
        from api.campus import install_campus_routes
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._old = os.environ.get("STIF_DB_PATH")
        self._old_database_url = os.environ.get("STIF_DATABASE_URL")
        os.environ["STIF_DB_PATH"] = str(Path(self._tmp.name) / "http.db")
        os.environ["STIF_DATABASE_URL"] = ""
        self.addCleanup(lambda: os.environ.pop("STIF_DB_PATH") if self._old is None else os.environ.__setitem__("STIF_DB_PATH", self._old))
        self.addCleanup(lambda: os.environ.pop("STIF_DATABASE_URL") if self._old_database_url is None else os.environ.__setitem__("STIF_DATABASE_URL", self._old_database_url))
        db.init_db()
        db._initialised.clear()
        for lim in (routes_auth.login_limiter, routes_auth.register_limiter, routes_enquiries.submit_limiter):
            lim.reset()
        conn = db.connect()
        auth_service.create_user(conn, email="admin@example.com", full_name="Site Admin", password=GOOD_PASSWORD, role="admin")
        conn.close()
        app = FastAPI()
        install_campus_routes(app)
        self.app = app
        self.client = TestClient(app)

    def login(self, client, email, password=GOOD_PASSWORD):
        return client.post("/api/v1/auth/login", json={"email": email, "password": password}, headers=H)

    def new_client(self):
        return TestClient(self.app)

    # ---- enquiry submission
    def test_form_config_has_no_invented_programmes(self):
        body = self.client.get("/api/v1/enquiries/form-config").json()
        self.assertEqual(body["programmes"], [])
        self.assertTrue(body["consent_text"])

    def test_submit_requires_csrf_header(self):
        r = self.client.post("/api/v1/enquiries", json=valid_enquiry())
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (403, "csrf"))

    def test_invalid_auth_payload_does_not_echo_submitted_password(self):
        secret = "sensitive-password-value"
        r = self.client.post("/api/v1/auth/login", headers=H, json={"email": "a" * 500, "password": secret})
        self.assertEqual(r.status_code, 422)
        self.assertNotIn(secret, r.text)
        self.assertEqual(r.headers["cache-control"], "no-store")

    def test_submit_success_duplicate_and_validation(self):
        r = self.client.post("/api/v1/enquiries", json=valid_enquiry(), headers=H)
        self.assertEqual(r.status_code, 201)
        ref = r.json()["enquiry"]["reference"]
        dup = self.client.post("/api/v1/enquiries", json=valid_enquiry(), headers=H)
        self.assertEqual((dup.status_code, dup.json()["duplicate"], dup.json()["enquiry"]["reference"]), (200, True, ref))
        bad = self.client.post("/api/v1/enquiries", json=valid_enquiry(email="nope", consent=False), headers=H)
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(set(bad.json()["error"]["fields"]), {"email", "consent"})

    def test_submit_rate_limit(self):
        from api import routes_enquiries
        routes_enquiries.submit_limiter.limit = 2
        self.addCleanup(lambda: setattr(routes_enquiries.submit_limiter, "limit", 10))
        codes = [self.client.post("/api/v1/enquiries", json=valid_enquiry(message=f"Distinct question {i} about admissions"), headers=H).status_code for i in range(3)]
        self.assertEqual(codes, [201, 201, 429])

    # ---- auth
    def test_register_ignores_role_and_sets_secure_cookie(self):
        r = self.client.post("/api/v1/auth/register", headers=H,
                             json={"email": "stu@example.com", "full_name": "Ravi Kumar", "password": GOOD_PASSWORD, "role": "admin"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["user"]["role"], "student")
        cookie = r.headers["set-cookie"].lower()
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=lax", cookie)
        self.assertNotIn("password", r.text.lower())
        self.assertEqual(self.client.get("/api/v1/auth/me").json()["user"]["email"], "stu@example.com")

    def test_login_logout_cycle(self):
        self.assertIsNone(self.client.get("/api/v1/auth/me").json()["user"])
        self.assertEqual(self.login(self.client, "admin@example.com").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/auth/me").json()["user"]["role"], "admin")
        self.assertEqual(self.client.post("/api/v1/auth/logout", headers=H).status_code, 200)
        self.assertIsNone(self.client.get("/api/v1/auth/me").json()["user"])

    def test_wrong_password_and_unknown_user_look_identical(self):
        a = self.login(self.client, "admin@example.com", "Wrong-Password-9")
        b = self.login(self.client, "ghost@example.com", "Wrong-Password-9")
        self.assertEqual((a.status_code, b.status_code), (401, 401))
        self.assertEqual(a.json(), b.json())

    def test_login_rate_limit(self):
        from api import routes_auth
        routes_auth.login_limiter.limit = 3
        self.addCleanup(lambda: setattr(routes_auth.login_limiter, "limit", 10))
        codes = [self.login(self.client, "ghost@example.com", "Wrong-Password-9").status_code for _ in range(4)]
        self.assertEqual(codes, [401, 401, 401, 429])

    def test_logged_out_token_is_dead_even_if_replayed(self):
        self.login(self.client, "admin@example.com")
        stolen = self.client.cookies.get("stif_session")
        self.client.post("/api/v1/auth/logout", headers=H)
        other = self.new_client()
        other.cookies.set("stif_session", stolen)
        self.assertIsNone(other.get("/api/v1/auth/me").json()["user"])
        self.assertEqual(other.get("/api/v1/admin/stats").status_code, 401)

    # ---- authorization
    def test_admin_api_requires_authentication_and_admin_role(self):
        paths = ["/api/v1/admin/stats", "/api/v1/admin/enquiries", "/api/v1/admin/enquiries/1", "/api/v1/admin/programmes"]
        for p in paths:
            self.assertEqual(self.client.get(p).status_code, 401, p)
        stu = self.new_client()
        stu.post("/api/v1/auth/register", headers=H, json={"email": "stu@example.com", "full_name": "Ravi Kumar", "password": GOOD_PASSWORD})
        for p in paths:
            self.assertEqual(stu.get(p).status_code, 403, p)
        self.assertEqual(stu.patch("/api/v1/admin/enquiries/1", json={"status": "closed"}, headers=H).status_code, 403)
        self.assertEqual(stu.post("/api/v1/admin/programmes", json={"name": "Nope"}, headers=H).status_code, 403)

    def test_student_sees_only_own_enquiries(self):
        a, b = self.new_client(), self.new_client()
        for c, mail in ((a, "a@example.com"), (b, "b@example.com")):
            c.post("/api/v1/auth/register", headers=H, json={"email": mail, "full_name": "Some Student", "password": GOOD_PASSWORD})
        a.post("/api/v1/enquiries", json=valid_enquiry(email="a@example.com"), headers=H)
        b.post("/api/v1/enquiries", json=valid_enquiry(email="b@example.com", message="B asks about hostel facilities here"), headers=H)
        mine = a.get("/api/v1/enquiries/mine").json()["items"]
        self.assertEqual(len(mine), 1)
        self.assertEqual(self.client.get("/api/v1/enquiries/mine").status_code, 401)

    def test_admin_end_to_end(self):
        admin = self.new_client()
        self.login(admin, "admin@example.com")
        pid = admin.post("/api/v1/admin/programmes", json={"name": "Programme X"}, headers=H).json()["programme"]["id"]
        self.assertEqual(self.client.get("/api/v1/enquiries/form-config").json()["programmes"][0]["name"], "Programme X")
        self.client.post("/api/v1/enquiries", json=valid_enquiry(programme_id=pid), headers=H)
        lst = admin.get("/api/v1/admin/enquiries", params={"status": "new", "q": "anita"}).json()
        self.assertEqual(lst["total"], 1)
        eid = lst["items"][0]["id"]
        detail = admin.get(f"/api/v1/admin/enquiries/{eid}").json()["enquiry"]
        self.assertIn("documents", detail["message"])
        upd = admin.patch(f"/api/v1/admin/enquiries/{eid}", json={"status": "responded", "admin_notes": "Called"}, headers=H)
        self.assertEqual(upd.json()["enquiry"]["status"], "responded")
        self.assertEqual(admin.patch(f"/api/v1/admin/enquiries/{eid}", json={"status": "bogus"}, headers=H).status_code, 422)
        self.assertEqual(admin.get("/api/v1/admin/enquiries/99999").status_code, 404)
        stats = admin.get("/api/v1/admin/stats").json()
        self.assertEqual((stats["total"], stats["by_status"]["responded"]), (1, 1))
        self.assertEqual(admin.get("/api/v1/admin/stats").headers["cache-control"], "no-store")

    # ---- existing operational endpoints are now admin-only
    def test_existing_ops_endpoints_require_admin(self):
        try:
            from api.main import app as main_app
        except Exception as exc:  # retrieval stack may be missing
            self.skipTest(f"api.main not importable here: {exc}")
        client = TestClient(main_app)
        for method, path in (("post", "/api/v1/ingest/run"), ("post", "/api/v1/index/reload"), ("get", "/api/v1/ingest/status")):
            self.assertEqual(getattr(client, method)(path, headers=H).status_code, 401, path)
        self.assertEqual(client.get("/health").status_code, 200)  # public chatbot/health surface unchanged


if __name__ == "__main__":
    unittest.main()
