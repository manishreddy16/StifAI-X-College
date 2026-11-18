from __future__ import annotations

import unittest

from evaluation.grounding import check_grounding, is_referral

EV = [{"title": "Placements 2023-24", "url": "https://example.test/placements",
       "text": "Highest package was 12 LPA in 2023-24. Total recruiters: 45. Contact placements@example.test or call +91 98765 43210. "
               "Tuition fee is Rs. 85,000 per year. Admission through EAPCET counselling for 60 seats."}]


def codes(result):
    return {f.code for f in result.findings}


class GroundingTests(unittest.TestCase):
    def test_supported_answer_has_no_findings(self):
        r = check_grounding("The highest package was 12 LPA in 2023-24, with 45 recruiters.", EV,
                            question="What was the highest package?")
        self.assertEqual(r.verdict, "no_issues_found")
        self.assertIn("not mean the answer is correct", r.disclaimer)

    def test_unsupported_placement_number(self):
        r = check_grounding("The highest package was 40 LPA.", EV, question="highest package?")
        self.assertEqual(r.verdict, "fail")
        self.assertIn("unsupported_placement_claim", codes(r))

    def test_unsupported_fee_claim(self):
        r = check_grounding("The tuition fee is Rs. 1,20,000 per year.", EV, question="What is the fee?")
        self.assertIn("unsupported_fee_claim", codes(r))
        ok = check_grounding("The tuition fee is Rs. 85,000 per year.", EV, question="What is the fee?")
        self.assertEqual(ok.verdict, "no_issues_found")

    def test_unsupported_admission_claim(self):
        r = check_grounding("There are 120 seats through EAPCET counselling.", EV, question="admission seats")
        self.assertIn("unsupported_admission_claim", codes(r))

    def test_unsupported_year_range(self):
        r = check_grounding("The highest package was 12 LPA in 2025-26.", EV, question="highest package")
        self.assertEqual(r.verdict, "fail")

    def test_generic_unsupported_number_is_medium(self):
        r = check_grounding("The campus library has 9000 volumes of archived journals.", EV, question="library")
        self.assertIn("unsupported_number", codes(r))
        self.assertEqual({f.severity for f in r.findings if f.code == "unsupported_number"}, {"medium"})

    def test_number_formatting_is_normalised(self):
        r = check_grounding("Tuition is Rs 85000 per year.", EV, question="fee")
        self.assertNotIn("unsupported_fee_claim", codes(r))

    def test_contact_details(self):
        bad = check_grounding("Email admissions@fake.test or call +91 90000 11111, see https://fake.test/x.", EV, question="contact")
        self.assertTrue({"unsupported_email", "unsupported_phone", "unsupported_url"} <= codes(bad))
        good = check_grounding("Email placements@example.test or call +91 98765 43210.", EV, question="contact")
        self.assertEqual(good.verdict, "no_issues_found")

    def test_fact_absent_from_evidence(self):
        r = check_grounding("The college runs a satellite observatory with astronomy fellowships abroad.", EV,
                            question="about the college")
        self.assertIn("low_lexical_support", codes(r))
        self.assertEqual(r.verdict, "warnings")

    def test_insufficient_evidence_without_referral_fails(self):
        r = check_grounding("The hostel fee is quite affordable for all students.", [], question="hostel fee")
        self.assertIn("answer_without_evidence", codes(r))
        self.assertEqual(r.verdict, "fail")

    def test_insufficient_evidence_with_referral_passes(self):
        r = check_grounding("I couldn't find this in the indexed sources. Please check the official college website.",
                            [], question="hostel fee", expect_referral=True)
        self.assertEqual(r.verdict, "no_issues_found")
        self.assertTrue(r.is_referral)

    def test_expected_referral_missing(self):
        r = check_grounding("Everything is published on the website at all times.", EV,
                            question="where do I verify?", expect_referral=True)
        self.assertIn("missing_official_verification_referral", codes(r))

    def test_time_sensitive_without_pointer_is_low_severity(self):
        r = check_grounding("The highest package was 12 LPA in 2023-24.", EV, question="What is the current highest package?")
        self.assertIn("time_sensitive_without_verification_pointer", codes(r))
        self.assertEqual(r.verdict, "warnings")
        ok = check_grounding("The highest package was 12 LPA in 2023-24. Please verify on the official website.", EV,
                             question="What is the current highest package?")
        self.assertEqual(ok.verdict, "no_issues_found")

    def test_empty_answer(self):
        self.assertEqual(check_grounding("  ", EV).verdict, "fail")

    def test_source_references_and_list_markers_not_flagged(self):
        r = check_grounding("1. Highest package was 12 LPA [Source 1].\n2. Total recruiters: 45.", EV, question="placements")
        self.assertEqual(r.verdict, "no_issues_found")

    def test_referral_detection(self):
        self.assertTrue(is_referral("Please contact the SVCE Admissions Office."))
        self.assertFalse(is_referral("Fees are paid yearly."))

    def test_evidence_without_text_counts_as_none(self):
        r = check_grounding("Fees are 5000.", [{"title": "x", "text": "  ", "url": "u"}], question="fee")
        self.assertEqual(r.evidence_count, 0)
        self.assertEqual(r.verdict, "fail")


if __name__ == "__main__":
    unittest.main()
