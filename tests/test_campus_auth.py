import unittest
from datetime import timedelta

from api import auth_service, db, security
from api.errors import AccountLocked, AuthError, Conflict, ValidationFailed
from api.ratelimit import SlidingWindowLimiter
from tests._campus_support import GOOD_PASSWORD, T0, DbTestCase


class PasswordTests(unittest.TestCase):
    def test_hash_is_salted_and_verifies(self):
        a, b = security.hash_password(GOOD_PASSWORD), security.hash_password(GOOD_PASSWORD)
        self.assertNotEqual(a, b)
        self.assertNotIn(GOOD_PASSWORD, a)
        self.assertTrue(security.verify_password(GOOD_PASSWORD, a))
        self.assertFalse(security.verify_password("wrong-password-1", a))

    def test_malformed_hash_never_verifies(self):
        for bad in ("", "plain", "scrypt$x$y", "md5$1$2$3$4$5", "scrypt$1$1$1$!!$!!",
                    "scrypt$2147483648$8$1$AAAAAAAAAAAAAAAAAAAAAA==$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="):
            self.assertFalse(security.verify_password(GOOD_PASSWORD, bad))

    def test_password_policy(self):
        self.assertIsNone(security.password_problem(GOOD_PASSWORD, email="a@b.co"))
        self.assertIsNotNone(security.password_problem("short1"))
        self.assertIsNotNone(security.password_problem("password123"))
        self.assertIsNotNone(security.password_problem("aaaaaaaaaaaa"))
        self.assertIsNotNone(security.password_problem("x" * 129))
        self.assertIsNotNone(security.password_problem("anita.reddy-2026", email="anita.reddy@example.com"))

    def test_token_digest_differs_from_token(self):
        t = security.new_token()
        self.assertNotEqual(t, security.token_digest(t))
        self.assertGreaterEqual(len(t), 40)


class AccountTests(DbTestCase):
    def reg(self, email="stu@example.com", name="Ravi Kumar", pw=GOOD_PASSWORD):
        return auth_service.register_student(self.conn, email=email, full_name=name, password=pw, now=T0)

    def test_register_creates_student_and_never_stores_plain_password(self):
        u = self.reg()
        self.assertEqual((u.role, u.email), ("student", "stu@example.com"))
        stored = self.conn.execute("SELECT password_hash FROM users").fetchone()[0]
        self.assertTrue(stored.startswith("scrypt$"))
        self.assertNotIn(GOOD_PASSWORD, stored)

    def test_email_is_normalised_and_unique_case_insensitively(self):
        self.reg(email="  Stu@Example.COM ")
        with self.assertRaises(Conflict):
            self.reg(email="stu@example.com")

    def test_validation_errors_are_per_field(self):
        with self.assertRaises(ValidationFailed) as cm:
            auth_service.register_student(self.conn, email="nope", full_name="R", password="short")
        self.assertEqual(set(cm.exception.fields), {"email", "full_name", "password"})
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)

    def test_indic_names_accepted_and_symbols_rejected(self):
        self.assertEqual(auth_service.clean_name("శ్రీనివాస్ రెడ్డి"), "శ్రీనివాస్ రెడ్డి")
        self.assertEqual(auth_service.clean_name("Anne-Marie O'Neil"), "Anne-Marie O'Neil")
        self.assertIsNone(auth_service.clean_name("<script>alert(1)</script>"))
        self.assertIsNone(auth_service.clean_name("A"))

    def test_role_cannot_be_chosen_via_public_registration(self):
        # register_student has no role parameter at all; verify admin can only come from create_user.
        u = self.reg()
        self.assertEqual(u.role, "student")
        admin = auth_service.create_user(self.conn, email="admin@example.com", full_name="Site Admin",
                                         password=GOOD_PASSWORD, role="admin", now=T0)
        self.assertEqual(admin.role, "admin")
        with self.assertRaises(ValidationFailed):
            auth_service.create_user(self.conn, email="x@example.com", full_name="Some One",
                                     password=GOOD_PASSWORD, role="superuser", now=T0)

    def test_database_rejects_unknown_role_even_with_raw_sql(self):
        with self.assertRaises(db.DatabaseIntegrityError):
            self.conn.execute("INSERT INTO users (email, full_name, password_hash, role, created_at) "
                              "VALUES ('a@b.co', 'A B', 'x', 'root', 'now')")


class LoginTests(DbTestCase):
    def setUp(self):
        super().setUp()
        auth_service.register_student(self.conn, email="stu@example.com", full_name="Ravi Kumar",
                                      password=GOOD_PASSWORD, now=T0)

    def test_login_success_and_wrong_password_share_generic_message(self):
        u = auth_service.authenticate(self.conn, "STU@example.com", GOOD_PASSWORD, now=T0)
        self.assertEqual(u.email, "stu@example.com")
        with self.assertRaises(AuthError) as wrong:
            auth_service.authenticate(self.conn, "stu@example.com", "Wrong-Password-1", now=T0)
        with self.assertRaises(AuthError) as unknown:
            auth_service.authenticate(self.conn, "ghost@example.com", "Wrong-Password-1", now=T0)
        self.assertEqual(wrong.exception.message, unknown.exception.message)

    def test_lockout_after_repeated_failures_then_recovers(self):
        for _ in range(auth_service.MAX_FAILED_ATTEMPTS):
            with self.assertRaises(AuthError):
                auth_service.authenticate(self.conn, "stu@example.com", "Wrong-Password-1", now=T0)
        with self.assertRaises(AccountLocked):  # even the correct password is refused while locked
            auth_service.authenticate(self.conn, "stu@example.com", GOOD_PASSWORD, now=T0 + timedelta(minutes=1))
        later = T0 + timedelta(minutes=auth_service.LOCKOUT_MINUTES + 1)
        self.assertEqual(auth_service.authenticate(self.conn, "stu@example.com", GOOD_PASSWORD, now=later).role, "student")

    def test_successful_login_resets_failure_counter(self):
        for _ in range(3):
            with self.assertRaises(AuthError):
                auth_service.authenticate(self.conn, "stu@example.com", "Wrong-Password-1", now=T0)
        auth_service.authenticate(self.conn, "stu@example.com", GOOD_PASSWORD, now=T0)
        self.assertEqual(self.conn.execute("SELECT failed_attempts FROM users").fetchone()[0], 0)

    def test_deactivated_account_cannot_log_in_or_use_session(self):
        u = auth_service.authenticate(self.conn, "stu@example.com", GOOD_PASSWORD, now=T0)
        token, _ = auth_service.create_session(self.conn, u.id, now=T0)
        self.conn.execute("UPDATE users SET is_active = 0")
        with self.assertRaises(AuthError):
            auth_service.authenticate(self.conn, "stu@example.com", GOOD_PASSWORD, now=T0)
        self.assertIsNone(auth_service.user_for_token(self.conn, token, now=T0))

    def test_malformed_login_input_is_rejected_generically(self):
        for email, pw in (("", ""), ("not-an-email", "x"), ("stu@example.com", ""), (None, None), ("stu@example.com", "x" * 500)):
            with self.assertRaises(AuthError):
                auth_service.authenticate(self.conn, email, pw, now=T0)


class SessionTests(DbTestCase):
    def setUp(self):
        super().setUp()
        self.user = auth_service.register_student(self.conn, email="stu@example.com", full_name="Ravi Kumar",
                                                  password=GOOD_PASSWORD, now=T0)

    def test_session_round_trip_and_only_digest_stored(self):
        token, _ = auth_service.create_session(self.conn, self.user.id, now=T0)
        self.assertEqual(auth_service.user_for_token(self.conn, token, now=T0).id, self.user.id)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM sessions WHERE token_hash = ?", (token,)).fetchone()[0], 0)

    def test_logout_revokes(self):
        token, _ = auth_service.create_session(self.conn, self.user.id, now=T0)
        auth_service.revoke_token(self.conn, token, now=T0)
        self.assertIsNone(auth_service.user_for_token(self.conn, token, now=T0))

    def test_expiry(self):
        token, exp = auth_service.create_session(self.conn, self.user.id, now=T0, ttl_hours=1)
        self.assertIsNotNone(auth_service.user_for_token(self.conn, token, now=T0 + timedelta(minutes=59)))
        self.assertIsNone(auth_service.user_for_token(self.conn, token, now=T0 + timedelta(minutes=61)))

    def test_session_lifetime_is_bounded(self):
        for ttl in (0, 24 * 31, float("inf")):
            with self.assertRaises(ValueError):
                auth_service.create_session(self.conn, self.user.id, now=T0, ttl_hours=ttl)

    def test_garbage_tokens(self):
        for t in (None, "", "abc", "x" * 1000):
            self.assertIsNone(auth_service.user_for_token(self.conn, t, now=T0))

    def test_password_reset_revokes_all_sessions(self):
        token, _ = auth_service.create_session(self.conn, self.user.id, now=T0)
        auth_service.set_password(self.conn, "stu@example.com", "Another-Strong-77", now=T0)
        self.assertIsNone(auth_service.user_for_token(self.conn, token, now=T0))
        auth_service.authenticate(self.conn, "stu@example.com", "Another-Strong-77", now=T0)


class MigrationAndLimiterTests(DbTestCase):
    def test_init_is_idempotent_and_keeps_data(self):
        auth_service.register_student(self.conn, email="stu@example.com", full_name="Ravi Kumar",
                                      password=GOOD_PASSWORD, now=T0)
        self.assertEqual(db.init_db(self.db_file), [])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0], 1)
        self.assertEqual([r[0] for r in self.conn.execute("SELECT version FROM schema_migrations")], [1])

    def test_rate_limiter_blocks_then_releases(self):
        now = [0.0]
        lim = SlidingWindowLimiter(3, 60, clock=lambda: now[0])
        self.assertEqual([lim.allow("ip") for _ in range(4)], [True, True, True, False])
        self.assertTrue(lim.allow("other"))
        now[0] = 61
        self.assertTrue(lim.allow("ip"))

    def test_rate_limiter_bounds_unique_keys(self):
        now = [0.0]
        lim = SlidingWindowLimiter(1, 60, clock=lambda: now[0], max_keys=2)
        lim.allow("a")
        lim.allow("b")
        self.assertFalse(lim.allow("c"))
        self.assertLessEqual(len(lim._hits), 2)
        self.assertFalse(lim.allow("a"))


if __name__ == "__main__":
    unittest.main()
