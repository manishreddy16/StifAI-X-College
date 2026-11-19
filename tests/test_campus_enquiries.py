import unittest
from datetime import timedelta

from api import auth_service, enquiry_service as es
from api.errors import NotFound, RateLimited, ValidationFailed
from tests._campus_support import GOOD_PASSWORD, T0, DbTestCase, valid_enquiry


class PhoneTests(unittest.TestCase):
    def test_accepted_forms(self):
        self.assertEqual(es.clean_phone("98765 43210"), "9876543210")
        self.assertEqual(es.clean_phone("+91 98765-43210"), "+919876543210")
        self.assertEqual(es.clean_phone("09876543210"), "9876543210")
        self.assertEqual(es.clean_phone("+44 7911 123456"), "+447911123456")

    def test_rejected_forms(self):
        for bad in ("", "12345", "1234567890", "abcdefghij", "98765432101234567", "+91 12345 67890", "<b>9876543210</b>", None):
            self.assertIsNone(es.clean_phone(bad), bad)


class SubmitTests(DbTestCase):
    def test_successful_submission_is_persisted_with_reference_and_consent(self):
        res = es.submit_enquiry(self.conn, valid_enquiry(), now=T0)
        self.assertFalse(res["duplicate"])
        ref = res["enquiry"]["reference"]
        self.assertRegex(ref, r"^ENQ-2026-\d{6}$")
        row = self.conn.execute("SELECT * FROM enquiries").fetchone()
        self.assertEqual((row["email"], row["phone"], row["status"], row["consent"]), ("anita.reddy@example.com", "9876543210", "new", 1))
        self.assertEqual(row["consent_version"], es.CONSENT_VERSION)
        self.assertEqual(row["programme_label"], es.GENERAL_LABEL)
        # a fresh connection (i.e. real persistence, not in-memory state) sees it
        from api import db
        other = db.connect(self.db_file)
        self.assertEqual(other.execute("SELECT reference FROM enquiries").fetchone()[0], ref)
        other.close()

    def test_receipt_does_not_leak_contact_or_notes(self):
        res = es.submit_enquiry(self.conn, valid_enquiry(), now=T0)
        self.assertEqual(set(res["enquiry"]), {"reference", "programme", "status", "created_at"})

    def test_validation_reports_every_bad_field_and_stores_nothing(self):
        with self.assertRaises(ValidationFailed) as cm:
            es.submit_enquiry(self.conn, {"full_name": "", "email": "x", "phone": "1", "message": "hi", "consent": True})
        self.assertEqual(set(cm.exception.fields), {"full_name", "email", "phone", "message"})
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM enquiries").fetchone()[0], 0)

    def test_consent_is_mandatory_and_must_be_literally_true(self):
        for value in (False, None, "true", 1, "on"):
            with self.assertRaises(ValidationFailed) as cm:
                es.submit_enquiry(self.conn, valid_enquiry(consent=value))
            self.assertIn("consent", cm.exception.fields)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM enquiries").fetchone()[0], 0)

    def test_database_itself_refuses_enquiry_without_consent(self):
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO enquiries (full_name,email,phone,programme_label,message,consent,consent_version,"
                              "consent_at,dedupe_hash,created_at,updated_at) VALUES ('A B','a@b.co','9876543210','x','m',0,'v','t','h','t','t')")

    def test_message_length_limits(self):
        with self.assertRaises(ValidationFailed):
            es.submit_enquiry(self.conn, valid_enquiry(message="x" * (es.MESSAGE_MAX + 1)))
        es.submit_enquiry(self.conn, valid_enquiry(message="y" * es.MESSAGE_MAX), now=T0)

    def test_programme_must_exist_and_be_active(self):
        pid = self.add_programme("Programme A")
        res = es.submit_enquiry(self.conn, valid_enquiry(programme_id=pid), now=T0)
        self.assertEqual(res["enquiry"]["programme"], "Programme A")
        for bad in (9999, "abc", -1):
            with self.assertRaises(ValidationFailed) as cm:
                es.submit_enquiry(self.conn, valid_enquiry(programme_id=bad), now=T0)
            self.assertIn("programme_id", cm.exception.fields)
        es.set_programme_active(self.conn, pid, False)
        with self.assertRaises(ValidationFailed):
            es.submit_enquiry(self.conn, valid_enquiry(programme_id=pid, message="A different question about fees please"), now=T0)

    def test_free_text_programme_is_used_when_none_selected(self):
        res = es.submit_enquiry(self.conn, valid_enquiry(programme_other="Something not listed"), now=T0)
        self.assertEqual(res["enquiry"]["programme"], "Something not listed")

    def test_stored_text_is_kept_literal_not_executed_or_mangled(self):
        msg = "Is it <b>true</b> that fees are 'low'; DROP TABLE enquiries;-- ? Please reply."
        es.submit_enquiry(self.conn, valid_enquiry(message=msg), now=T0)
        self.assertEqual(self.conn.execute("SELECT message FROM enquiries").fetchone()[0], msg)  # escaped at render time by React
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM enquiries").fetchone()[0], 1)

    def test_control_characters_stripped(self):
        es.submit_enquiry(self.conn, valid_enquiry(message="Hello\x00 there\x07, what are the dates?"), now=T0)
        self.assertEqual(self.conn.execute("SELECT message FROM enquiries").fetchone()[0], "Hello there, what are the dates?")


class DuplicateTests(DbTestCase):
    def test_identical_resubmission_returns_original_reference_without_new_row(self):
        first = es.submit_enquiry(self.conn, valid_enquiry(), now=T0)
        again = es.submit_enquiry(self.conn, valid_enquiry(full_name="Anita R", email="ANITA.REDDY@example.com",
                                                           message="  what documents are NEEDED for   admission counselling? "),
                                  now=T0 + timedelta(minutes=2))
        self.assertTrue(again["duplicate"])
        self.assertEqual(again["enquiry"]["reference"], first["enquiry"]["reference"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM enquiries").fetchone()[0], 1)

    def test_same_enquiry_after_window_is_accepted_again(self):
        es.submit_enquiry(self.conn, valid_enquiry(), now=T0)
        later = es.submit_enquiry(self.conn, valid_enquiry(), now=T0 + es.DUPLICATE_WINDOW + timedelta(hours=1))
        self.assertFalse(later["duplicate"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM enquiries").fetchone()[0], 2)

    def test_different_question_from_same_person_is_not_a_duplicate(self):
        es.submit_enquiry(self.conn, valid_enquiry(), now=T0)
        res = es.submit_enquiry(self.conn, valid_enquiry(message="Is hostel accommodation available for first years?"), now=T0)
        self.assertFalse(res["duplicate"])

    def test_daily_cap_per_email(self):
        for i in range(es.MAX_PER_EMAIL_PER_DAY):
            es.submit_enquiry(self.conn, valid_enquiry(message=f"Distinct question number {i} about admissions"), now=T0)
        with self.assertRaises(RateLimited):
            es.submit_enquiry(self.conn, valid_enquiry(message="One more distinct question about admissions"), now=T0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM enquiries").fetchone()[0], es.MAX_PER_EMAIL_PER_DAY)


class AccessScopingTests(DbTestCase):
    def test_student_sees_only_own_linked_enquiries(self):
        a = auth_service.register_student(self.conn, email="a@example.com", full_name="Student A", password=GOOD_PASSWORD, now=T0)
        b = auth_service.register_student(self.conn, email="b@example.com", full_name="Student B", password=GOOD_PASSWORD, now=T0)
        es.submit_enquiry(self.conn, valid_enquiry(email="a@example.com"), user=a, now=T0)
        es.submit_enquiry(self.conn, valid_enquiry(email="b@example.com", message="Question from student B about fees"), user=b, now=T0)
        es.submit_enquiry(self.conn, valid_enquiry(email="a@example.com", message="Anonymous question using A's email address"), now=T0)
        mine = es.list_for_user(self.conn, a)
        self.assertEqual(len(mine), 1)  # the anonymous one is NOT linked just because the email matches
        self.assertEqual(len(es.list_for_user(self.conn, b)), 1)


class AdminQueryTests(DbTestCase):
    def setUp(self):
        super().setUp()
        self.p1 = self.add_programme("Programme One")
        self.p2 = self.add_programme("Programme Two")
        for i, (pid, name) in enumerate([(self.p1, "Alpha Student"), (self.p1, "Beta Student"), (self.p2, "Gamma Student")]):
            es.submit_enquiry(self.conn, valid_enquiry(full_name=name, email=f"s{i}@example.com", programme_id=pid,
                              message=f"Question {i} about 100% placement_records?"), now=T0 + timedelta(hours=i))

    def test_list_filter_search_and_pagination(self):
        self.assertEqual(es.list_enquiries(self.conn)["total"], 3)
        self.assertEqual(es.list_enquiries(self.conn, programme_id=self.p1)["total"], 2)
        self.assertEqual(es.list_enquiries(self.conn, q="gamma")["total"], 1)
        self.assertEqual(es.list_enquiries(self.conn, q="s1@example")["total"], 1)
        page = es.list_enquiries(self.conn, page=2, page_size=2)
        self.assertEqual((len(page["items"]), page["pages"]), (1, 2))
        self.assertEqual(es.list_enquiries(self.conn, page_size=10_000)["page_size"], es.MAX_PAGE_SIZE)

    def test_like_wildcards_in_search_are_literal(self):
        self.assertEqual(es.list_enquiries(self.conn, q="%")["total"], 0)
        self.assertEqual(es.list_enquiries(self.conn, q="_")["total"], 0)
        self.assertEqual(es.list_enquiries(self.conn, q="' OR 1=1 --")["total"], 0)

    def test_invalid_status_filter_rejected(self):
        with self.assertRaises(ValidationFailed):
            es.list_enquiries(self.conn, status="bogus")

    def test_detail_update_and_notfound(self):
        eid = es.list_enquiries(self.conn)["items"][0]["id"]
        d = es.update_enquiry(self.conn, eid, status="responded", admin_notes="Called back", now=T0 + timedelta(days=1))
        self.assertEqual((d["status"], d["admin_notes"]), ("responded", "Called back"))
        self.assertIn("message", d)
        self.assertEqual(es.list_enquiries(self.conn, status="responded")["total"], 1)
        with self.assertRaises(NotFound):
            es.get_enquiry(self.conn, 99999)
        with self.assertRaises(NotFound):
            es.update_enquiry(self.conn, 99999, status="closed")
        with self.assertRaises(ValidationFailed):
            es.update_enquiry(self.conn, eid, status="deleted")
        with self.assertRaises(ValidationFailed):
            es.update_enquiry(self.conn, eid)

    def test_stats_are_computed_from_real_rows(self):
        eid = es.list_enquiries(self.conn)["items"][0]["id"]
        es.update_enquiry(self.conn, eid, status="closed", now=T0)
        s = es.stats(self.conn, now=T0 + timedelta(hours=5))
        self.assertEqual(s["total"], 3)
        self.assertEqual(s["by_status"], {"new": 2, "in_progress": 0, "responded": 0, "closed": 1})
        self.assertEqual(s["open"], 2)
        self.assertEqual(s["today"], 3)
        self.assertEqual(sum(d["count"] for d in s["daily"]), 3)
        self.assertEqual(s["top_programmes"][0], {"programme": "Programme One", "count": 2})

    def test_stats_on_empty_database(self):
        from api import db
        self.conn.execute("DELETE FROM enquiries")
        s = es.stats(self.conn, now=T0)
        self.assertEqual((s["total"], s["today"], s["open"]), (0, 0, 0))
        self.assertEqual(s["top_programmes"], [])


class ProgrammeTests(DbTestCase):
    def test_no_programmes_are_invented(self):
        self.assertEqual(es.list_programmes(self.conn), [])

    def test_add_duplicate_and_toggle(self):
        es.add_programme(self.conn, "Some Programme", now=T0)
        with self.assertRaises(ValidationFailed):
            es.add_programme(self.conn, "  some   programme ", now=T0)
        with self.assertRaises(ValidationFailed):
            es.add_programme(self.conn, "x")
        pid = es.list_programmes(self.conn)[0]["id"]
        es.set_programme_active(self.conn, pid, False)
        self.assertEqual(es.list_programmes(self.conn), [])
        self.assertEqual(len(es.list_programmes(self.conn, active_only=False)), 1)
        with self.assertRaises(NotFound):
            es.set_programme_active(self.conn, 999, True)


if __name__ == "__main__":
    unittest.main()
