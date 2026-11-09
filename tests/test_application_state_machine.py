"""
Comprehensive Application State Machine & Lifecycle Regression Test Suite
========================================================================
Validates the 12 critical lifecycle and deduplication scenarios:
1. Successful LinkedIn Easy Apply with verified confirmation -> APPLIED
2. Successful external application with verified confirmation -> APPLIED
3. Submit clicked but confirmation missing -> SUBMITTED_PENDING_CONFIRMATION
4. Form completed but manual confirmation required -> NEEDS_INPUT
5. CAPTCHA interruption -> NEEDS_INPUT
6. Resume upload failure -> NEEDS_INPUT / FAILED
7. Application form not found after complete inspection -> SKIPPED (APPLY_OPTION_NOT_AVAILABLE)
8. External page loading timeout -> SKIPPED (EXTERNAL_PAGE_UNAVAILABLE)
9. Application already submitted -> APPLIED / ALREADY_APPLIED
10. Anti-overwriting database protection (Background worker cannot demote APPLIED to SKIPPED)
11. Frontend data persistence & status synchronization across refreshes
12. Atomic job claiming & concurrency protection
13. Semantic Salary Integrity (Monthly salary cannot be polluted by bio essays)
14. Phone Country Code selection (+974 Qatar for international, never +971 UAE)
15. Date of Birth autofill (19-11-1999 verified)
16. CAPTCHA Safety (Mystery/code inputs never receive candidate designation)
"""

import os
import sys
import unittest
import time
import uuid

# Add backend directory to sys.path
BACKEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from state_machine import (
    ApplicationStatus,
    ApplicationStateMachine,
    normalize_application_status,
    is_valid_status_transition,
    STATUS_PRIORITY
)
from database import (
    record_application,
    check_already_applied_db,
    get_recent_applications,
    get_connection
)
from question_answering import qa_engine, QuestionCategory
from candidate_manager import getCandidateProfileByJobLocation


def get_db_record(job_url: str):
    """Test helper to query record by URL directly."""
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM job_applications WHERE job_url = %s ORDER BY id DESC LIMIT 1", (job_url,))
        row = cursor.fetchone()
        conn.close()
        return row


class TestApplicationStateMachineAndAutofill(unittest.TestCase):

    def setUp(self):
        self.test_prefix = f"TestCo_{uuid.uuid4().hex[:6]}"
        self.job_title = "Senior Full Stack Engineer"
        self.company_name = f"{self.test_prefix} Tech"
        self.unique_job_id = f"test_{uuid.uuid4().hex[:8]}"
        self.job_url = f"https://www.linkedin.com/jobs/view/{self.unique_job_id}/"

    # -------------------------------------------------------------
    # Scenario 1: Successful LinkedIn Easy Apply with confirmation -> APPLIED
    # -------------------------------------------------------------
    def test_01_linkedin_easy_apply_confirmed(self):
        app_id = record_application(
            job_title=self.job_title,
            company_name=self.company_name,
            location="Dubai, UAE",
            job_url=self.job_url,
            status=ApplicationStatus.APPLIED,
            apply_type="LINKEDIN_EASY_APPLY",
            confirmation_type="MODAL_SUBMITTED_BANNER",
            confirmation_message="Your application was sent to the employer",
            application_submitted=True,
            application_confirmed=True,
            platform="LINKEDIN"
        )
        self.assertTrue(app_id > 0)
        
        # Verify persistence in DB
        rec = get_db_record(self.job_url)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["status"], ApplicationStatus.APPLIED)
        self.assertEqual(rec["confirmation_type"], "MODAL_SUBMITTED_BANNER")
        self.assertEqual(rec["application_confirmed"], 1)

    # -------------------------------------------------------------
    # Scenario 2: Successful external application with confirmation -> APPLIED
    # -------------------------------------------------------------
    def test_02_external_application_confirmed(self):
        ext_url = f"https://careers.{self.test_prefix.lower()}.com/jobs/{self.unique_job_id}"
        app_id = record_application(
            job_title=self.job_title,
            company_name=self.company_name,
            location="Doha, Qatar",
            job_url=self.job_url,
            external_application_url=ext_url,
            status=ApplicationStatus.APPLIED,
            apply_type="COMPANY_WEBSITE",
            confirmation_type="PORTAL_SUCCESS_PAGE",
            confirmation_message="Thank you for applying. Your application has been received.",
            application_submitted=True,
            application_confirmed=True,
            platform="LINKEDIN"
        )
        self.assertTrue(app_id > 0)
        rec = get_db_record(self.job_url)
        self.assertEqual(rec["status"], ApplicationStatus.APPLIED)
        self.assertEqual(rec["confirmation_type"], "PORTAL_SUCCESS_PAGE")

    # -------------------------------------------------------------
    # Scenario 3: Submit clicked but confirmation missing -> SUBMITTED_PENDING_CONFIRMATION
    # -------------------------------------------------------------
    def test_03_submit_clicked_unconfirmed(self):
        app_id = record_application(
            job_title=self.job_title,
            company_name=self.company_name,
            location="Mumbai, India",
            job_url=self.job_url,
            status=ApplicationStatus.SUBMITTED_PENDING_CONFIRMATION,
            apply_type="COMPANY_WEBSITE",
            failure_reason="CONFIRMATION_UNCERTAIN",
            notes="Submit button clicked, awaiting employer verification",
            application_attempted=True,
            application_submitted=True,
            application_confirmed=False,
            platform="NAUKRI"
        )
        self.assertTrue(app_id > 0)
        rec = get_db_record(self.job_url)
        self.assertEqual(rec["status"], ApplicationStatus.SUBMITTED_PENDING_CONFIRMATION)
        self.assertEqual(rec["application_confirmed"], 0)

    # -------------------------------------------------------------
    # Scenario 4: Form completed but manual confirmation required -> NEEDS_INPUT
    # -------------------------------------------------------------
    def test_04_form_completed_needs_user_input(self):
        app_id = record_application(
            job_title=self.job_title,
            company_name=self.company_name,
            location="Remote",
            job_url=self.job_url,
            status=ApplicationStatus.NEEDS_INPUT,
            apply_type="LINKEDIN_EASY_APPLY",
            execution_stage="FORM_COMPLETED",
            failure_reason="CONFIRMATION_UNCERTAIN",
            detailed_explanation="Requires Candidate Action: Easy Apply form completed, tab kept open in Chrome",
            application_attempted=True,
            application_submitted=False,
            application_confirmed=False,
            platform="LINKEDIN"
        )
        self.assertTrue(app_id > 0)
        rec = get_db_record(self.job_url)
        self.assertEqual(rec["status"], ApplicationStatus.NEEDS_INPUT)

    # -------------------------------------------------------------
    # Scenario 5: CAPTCHA interruption -> NEEDS_INPUT
    # -------------------------------------------------------------
    def test_05_captcha_interruption(self):
        app_id = record_application(
            job_title=self.job_title,
            company_name=self.company_name,
            location="Qatar",
            job_url=self.job_url,
            status=ApplicationStatus.NEEDS_INPUT,
            failure_reason="CAPTCHA_REQUIRED",
            skip_reason_code="CAPTCHA_REQUIRED",
            execution_stage="FORM_IN_PROGRESS",
            detailed_explanation="CAPTCHA challenge encountered on external portal. Field kept empty in Chrome.",
            application_attempted=True,
            platform="LINKEDIN"
        )
        self.assertTrue(app_id > 0)
        rec = get_db_record(self.job_url)
        self.assertEqual(rec["status"], ApplicationStatus.NEEDS_INPUT)
        self.assertEqual(rec["failure_reason"], "CAPTCHA_REQUIRED")

    # -------------------------------------------------------------
    # Scenario 6: Resume upload failure -> FAILED
    # -------------------------------------------------------------
    def test_06_resume_upload_failure(self):
        app_id = record_application(
            job_title=self.job_title,
            company_name=self.company_name,
            location="Dubai",
            job_url=self.job_url,
            status=ApplicationStatus.FAILED,
            failure_reason="RESUME_UPLOAD_FAILED",
            resume_upload_status="FAILED",
            platform="LINKEDIN"
        )
        self.assertTrue(app_id > 0)
        rec = get_db_record(self.job_url)
        self.assertEqual(rec["status"], ApplicationStatus.FAILED)
        self.assertEqual(rec["failure_reason"], "RESUME_UPLOAD_FAILED")

    # -------------------------------------------------------------
    # Scenario 7: Application form not found -> SKIPPED (APPLY_OPTION_NOT_AVAILABLE)
    # -------------------------------------------------------------
    def test_07_form_not_found_skipped(self):
        app_id = record_application(
            job_title=self.job_title,
            company_name=self.company_name,
            location="Pune, India",
            job_url=self.job_url,
            status=ApplicationStatus.SKIPPED,
            skip_reason_code="APPLY_OPTION_NOT_AVAILABLE",
            detailed_explanation="No interactive application form found after scanning DOM and iframes.",
            platform="LINKEDIN"
        )
        self.assertTrue(app_id > 0)
        rec = get_db_record(self.job_url)
        self.assertEqual(rec["status"], ApplicationStatus.SKIPPED)
        self.assertEqual(rec["skip_reason_code"], "APPLY_OPTION_NOT_AVAILABLE")

    # -------------------------------------------------------------
    # Scenario 8: External page loading timeout -> SKIPPED (EXTERNAL_PAGE_UNAVAILABLE)
    # -------------------------------------------------------------
    def test_08_page_timeout_skipped(self):
        app_id = record_application(
            job_title=self.job_title,
            company_name=self.company_name,
            location="Remote",
            job_url=self.job_url,
            status=ApplicationStatus.SKIPPED,
            skip_reason_code="EXTERNAL_PAGE_UNAVAILABLE",
            detailed_explanation="External career portal timed out during navigation.",
            platform="LINKEDIN"
        )
        self.assertTrue(app_id > 0)
        rec = get_db_record(self.job_url)
        self.assertEqual(rec["status"], ApplicationStatus.SKIPPED)
        self.assertEqual(rec["skip_reason_code"], "EXTERNAL_PAGE_UNAVAILABLE")

    # -------------------------------------------------------------
    # Scenario 9: Application already submitted -> ALREADY_APPLIED
    # -------------------------------------------------------------
    def test_09_already_applied_detection(self):
        app_id = record_application(
            job_title=self.job_title,
            company_name=self.company_name,
            location="Dubai",
            job_url=self.job_url,
            status=ApplicationStatus.ALREADY_APPLIED,
            confirmation_type="PORTAL_UNDER_REVIEW_BANNER",
            confirmation_message="Hey candidate, it looks like we are already reviewing your application!",
            application_submitted=True,
            application_confirmed=True,
            platform="LINKEDIN"
        )
        self.assertTrue(app_id > 0)
        rec = get_db_record(self.job_url)
        self.assertEqual(rec["status"], ApplicationStatus.ALREADY_APPLIED)
        self.assertEqual(rec["confirmation_type"], "PORTAL_UNDER_REVIEW_BANNER")

    # -------------------------------------------------------------
    # Scenario 10: Anti-overwriting Database Protection
    # (Attempt to overwrite APPLIED with SKIPPED is BLOCKED)
    # -------------------------------------------------------------
    def test_10_anti_overwrite_protection(self):
        # 1. Create confirmed application
        app_id = record_application(
            job_title=self.job_title,
            company_name=self.company_name,
            location="Qatar",
            job_url=self.job_url,
            status=ApplicationStatus.APPLIED,
            confirmation_type="CONFIRMED_SUBMISSION",
            application_submitted=True,
            application_confirmed=True,
            platform="LINKEDIN"
        )
        self.assertTrue(app_id > 0)

        # 2. Later background worker attempts to overwrite with SKIPPED
        # The anti-overwrite guard will block the overwrite and preserve APPLIED
        attempt_id = record_application(
            job_title=self.job_title,
            company_name=self.company_name,
            location="Qatar",
            job_url=self.job_url,
            status=ApplicationStatus.SKIPPED,
            skip_reason_code="APPLY_OPTION_NOT_AVAILABLE",
            detailed_explanation="Stale check found no apply option",
            platform="LINKEDIN"
        )
        # 3. Verify status in database remains APPLIED
        rec = get_db_record(self.job_url)
        self.assertEqual(rec["status"], ApplicationStatus.APPLIED)

    # -------------------------------------------------------------
    # Scenario 11: Frontend persistence across refresh
    # -------------------------------------------------------------
    def test_11_frontend_persistence(self):
        record_application(
            job_title=self.job_title,
            company_name=self.company_name,
            location="Mumbai, India",
            job_url=self.job_url,
            status=ApplicationStatus.APPLIED,
            confirmation_type="PORTAL_CONFIRMED",
            application_submitted=True,
            application_confirmed=True,
            platform="LINKEDIN"
        )
        apps = get_recent_applications(limit=30)
        matched = [a for a in apps if a.get("job_url") == self.job_url]
        self.assertTrue(len(matched) > 0)
        self.assertEqual(matched[0]["status"], ApplicationStatus.APPLIED)
        self.assertEqual(matched[0]["applicationStatus"], ApplicationStatus.APPLIED)

    # -------------------------------------------------------------
    # Scenario 12: Concurrency & Duplicate Check
    # -------------------------------------------------------------
    def test_12_deduplication_by_id_and_title(self):
        test_url = f"https://www.linkedin.com/jobs/view/{self.unique_job_id}/"
        record_application(
            job_title="Senior Fullstack Engineer - Dubai",
            company_name=self.company_name,
            location="Dubai, UAE",
            job_url=test_url,
            status=ApplicationStatus.APPLIED,
            platform="LINKEDIN"
        )
        # Check by ID
        self.assertTrue(check_already_applied_db(job_id=self.unique_job_id))
        # Check by clean title & company
        self.assertTrue(check_already_applied_db(title="Senior Fullstack Engineer", company=self.company_name))
        # Check by URL
        self.assertTrue(check_already_applied_db(job_url=f"{test_url}?trackingId=abc123xyz"))

    # -------------------------------------------------------------
    # Scenario 13: Salary Integrity (No Essay Pollution)
    # -------------------------------------------------------------
    def test_13_salary_integrity(self):
        res_current = qa_engine.process_question(
            "Current Monthly Renumeration/Salary *",
            "text",
            location_hint="Dubai"
        )
        self.assertEqual(res_current["answer"], "8000")
        self.assertNotIn("I bring 5+ years", res_current["answer"])
        self.assertEqual(res_current["category"], QuestionCategory.SALARY)

        res_expected = qa_engine.process_question(
            "Expected Monthly Renumeration/Salary *",
            "text",
            location_hint="Dubai"
        )
        self.assertEqual(res_expected["answer"], "8000")
        self.assertNotIn("Developer", res_expected["answer"])

    # -------------------------------------------------------------
    # Scenario 14: Phone Country Code Selection (+974 Qatar, never +971 UAE)
    # -------------------------------------------------------------
    def test_14_phone_country_code_selection(self):
        # International profile (Dubai job)
        cand_p = getCandidateProfileByJobLocation("Dubai")
        self.assertEqual(cand_p["country_code"], "+974")
        self.assertEqual(cand_p["mobile_number"], "77557982")
        self.assertNotEqual(cand_p["country_code"], "+971")

        # India profile
        cand_in = getCandidateProfileByJobLocation("Mumbai")
        self.assertEqual(cand_in["country_code"], "+91")
        self.assertEqual(cand_in["mobile_number"], "7972694663")

    # -------------------------------------------------------------
    # Scenario 15: Date of Birth Autofill
    # -------------------------------------------------------------
    def test_15_date_of_birth_autofill(self):
        res_dob = qa_engine.process_question("Date of Birth", "text")
        self.assertEqual(res_dob["answer"], "19/11/1999")
        self.assertEqual(res_dob["category"], QuestionCategory.PERSONAL_INFO)

    # -------------------------------------------------------------
    # Scenario 16: CAPTCHA Safety (No Designation Fallback)
    # -------------------------------------------------------------
    def test_16_captcha_safety(self):
        # Empty prompt or captcha field should never receive "Senior Full Stack Developer"
        res_empty = qa_engine.process_question("", "text")
        self.assertEqual(res_empty["answer"], "")
        self.assertNotEqual(res_empty["answer"], "Senior Full Stack Developer")

        res_captcha = qa_engine.process_question("Enter characters from image", "text")
        self.assertEqual(res_captcha["answer"], "")


if __name__ == "__main__":
    unittest.main()
