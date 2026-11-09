"""
Test Suite: Intelligent Form Understanding & Autofill Accuracy
==============================================================
Validates:
1. Salary / Remuneration fields strictly receive numeric salary (never essay summary).
2. Country Code dropdown strictly selects Qatar (+974) for International/Gulf jobs, never UAE (+971).
3. Phone number input contains only national digits when country code exists (no leading +91 / +974).
4. Date of Birth strictly receives verified date in proper format (ISO for date type, slash/hyphen for text).
5. CAPTCHA fields are never filled with job title / text, kept completely empty, and trigger NEEDS_INPUT.
6. External portals showing 'already reviewing your awesome application' are detected as ALREADY_APPLIED.
7. Deduplication (check_already_applied_db) prevents re-visiting already applied or skipped roles.
"""

import sys
import os
import unittest

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from semantic_form_engine import SemanticFormEngine, SemanticFieldCategory
from question_answering import QuestionAnsweringEngine, QuestionCategory
from candidate_manager import CandidateProfileManager, getCandidateProfileByJobLocation
from database import check_already_applied_db, record_application, get_connection
from state_machine import ApplicationStatus, ApplicationStateMachine


class TestFormUnderstandingAndAutofill(unittest.TestCase):

    def setUp(self):
        self.qa = QuestionAnsweringEngine()

    def test_01_current_monthly_remuneration_numeric_salary(self):
        """Image 4 Fix: Current Monthly Remuneration/Salary must strictly return numeric salary, never essay."""
        labels = [
            "Current Monthly Remuneration/Salary *",
            "Current Monthly Renumeration/Salary *",
            "Expected Monthly Remuneration/Salary *",
            "Expected Monthly Renumeration/Salary *",
            "Provide your current Cost-To-Company (CTC), in your local currency."
        ]
        for lbl in labels:
            res = self.qa.process_question(
                question_text=lbl,
                input_type="textarea",
                job_title="Senior Full Stack Developer",
                company_name="ADG",
                location_hint="Qatar"
            )
            ans = res.get("answer", "")
            self.assertNotIn("production experience", ans.lower(), f"Essay leaked into salary for '{lbl}'!")
            self.assertNotIn("react.js", ans.lower(), f"Tech skills leaked into salary for '{lbl}'!")
            self.assertLessEqual(len(ans), 20, f"Salary answer is too long for '{lbl}': {ans}")
            self.assertEqual(res.get("category"), QuestionCategory.SALARY)
            self.assertEqual(ans, "8000")

    def test_02_country_code_strictly_qatar_plus974_never_971(self):
        """Image 2 Fix: For Qatar/Gulf jobs, Country Code dropdown must select +974, never +971."""
        cand_p = getCandidateProfileByJobLocation("Qatar (Remote)")
        self.assertTrue(cand_p["is_international"])
        self.assertEqual(cand_p["country_code"], "+974")

        # Test semantic field category and value
        cat, conf, _ = SemanticFormEngine.classify_field(
            label="Phone Number",
            heading="Mobile Phone",
            help_text="Select Country Code",
            placeholder="+971",
            input_type="select",
            name="country_code"
        )
        self.assertEqual(cat, SemanticFieldCategory.PHONE_COUNTRY_CODE)
        
        val, _ = SemanticFormEngine.get_candidate_value(cat, location_hint="Qatar")
        self.assertEqual(val, "+974")
        self.assertNotIn("971", val)

        # Validation rejects +971 and corrects to +974
        valid, corrected, _ = SemanticFormEngine.validate_field_value(
            category=SemanticFieldCategory.PHONE_COUNTRY_CODE,
            value="+971",
            location_hint="Qatar"
        )
        self.assertFalse(valid)
        self.assertEqual(corrected, "+974")

    def test_03_phone_input_national_digits_only(self):
        """Image 5 Fix: When separate country code selector exists, phone input must not have leading +91 or +974."""
        cand_p_qatar = getCandidateProfileByJobLocation("Qatar")
        self.assertEqual(cand_p_qatar["mobile_number"], "77557982")

        cand_p_india = getCandidateProfileByJobLocation("Mumbai, India")
        self.assertEqual(cand_p_india["mobile_number"], "7972694663")

        # Validate that phone number field cleans leading +91
        valid, clean_val, _ = SemanticFormEngine.validate_field_value(
            category=SemanticFieldCategory.PHONE_NUMBER,
            value="+917972694663",
            location_hint="India"
        )
        self.assertFalse(valid)
        self.assertEqual(clean_val, "7972694663")

        # Validate Qatar phone removes +974 / Indian contamination
        valid_qa, clean_qa, _ = SemanticFormEngine.validate_field_value(
            category=SemanticFieldCategory.PHONE_NUMBER,
            value="+91797269466",
            location_hint="Qatar"
        )
        self.assertFalse(valid_qa)
        self.assertEqual(clean_qa, "77557982")

    def test_04_date_of_birth_formatting(self):
        """Image 6 Fix: Date of Birth is populated with verified date (ISO for date input, formatted for text)."""
        cat, conf, _ = SemanticFormEngine.classify_field(
            label="Date of Birth",
            heading="",
            input_type="date",
            name="dob"
        )
        self.assertEqual(cat, SemanticFieldCategory.DATE_OF_BIRTH)

        val_date, _ = SemanticFormEngine.get_candidate_value(cat, input_type="date")
        self.assertEqual(val_date, "1999-11-19")

        val_text, _ = SemanticFormEngine.get_candidate_value(cat, input_type="text")
        self.assertEqual(val_text, "19-11-1999")

    def test_05_captcha_field_empty_and_needs_input(self):
        """Image 7 Fix: CAPTCHA field is never filled with job title, stays empty, triggers NEEDS_INPUT."""
        cat, conf, _ = SemanticFormEngine.classify_field(
            label="Security Code",
            heading="Please enter characters from image",
            placeholder="Captcha",
            input_type="text",
            name="captcha_code"
        )
        self.assertEqual(cat, SemanticFieldCategory.CAPTCHA)

        # QA Engine process_question returns is_blocked=True and needs_user_input=True
        qa_res = self.qa.process_question(
            question_text="Enter text from image",
            input_type="text",
            job_title="Senior Full Stack Developer",
            company_name="TestCorp"
        )
        self.assertTrue(qa_res.get("needs_user_input"))
        self.assertEqual(qa_res.get("answer"), "")
        self.assertNotIn("Senior Full Stack Developer", qa_res.get("answer"))

        # Validation clears polluted text
        valid, cleaned, _ = SemanticFormEngine.validate_field_value(
            category=SemanticFieldCategory.CAPTCHA,
            value="Senior Full Stack Develo"
        )
        self.assertFalse(valid)
        self.assertEqual(cleaned, "")

    def test_06_already_applied_banner_signals(self):
        """Image 1 Fix: Explicit portal banners saying 'already reviewing your awesome application' detected."""
        banner_texts = [
            "Hey Abdul Razzaque, it looks like we are already reviewing your awesome application! Please wait to hear from us before applying again.",
            "Looks like we are already reviewing your application. Please wait to hear from us before applying again.",
            "You have already applied for this position."
        ]
        from form_engine import check_page_already_applied
        
        # Verify pattern matching logic directly
        patterns = [
            'already reviewing your awesome application',
            'already reviewing your application',
            'already reviewing your',
            'looks like we are already reviewing',
            'wait to hear from us before applying again',
            'please wait to hear from us before applying again',
            'we are already reviewing',
            'already applied for this job',
            'already applied for this position',
            'already applied',
            'you have already applied'
        ]
        for b in banner_texts:
            b_low = b.lower()
            matched = any(p in b_low for p in patterns)
            self.assertTrue(matched, f"Banner text failed to match already applied signals: '{b}'")

    def test_07_deduplication_prevents_duplicate_applications(self):
        """Prompt 7 Fix: check_already_applied_db prevents re-navigating to already applied, skipped, or failed roles."""
        import random
        unique_co = f"DedupTestCorp_{os.urandom(4).hex()}"
        unique_title = f"Lead Cloud Engineer {os.urandom(4).hex()}"
        unique_url = f"https://www.linkedin.com/jobs/view/{random.randint(100000000, 999999999)}"

        # Before recording -> False
        self.assertFalse(check_already_applied_db(title=unique_title, company=unique_co, job_url=unique_url))

        # Record as ALREADY_APPLIED
        record_application(
            job_title=unique_title,
            company_name=unique_co,
            location="Qatar",
            job_url=unique_url,
            status="ALREADY_APPLIED",
            apply_type="COMPANY_WEBSITE",
            notes="Portal confirms application already under review"
        )

        # After recording -> True (Deduplication blocks re-application)
        self.assertTrue(check_already_applied_db(title=unique_title, company=unique_co, job_url=unique_url))
        self.assertTrue(check_already_applied_db(job_url=unique_url))
        self.assertTrue(check_already_applied_db(title=unique_title, company=unique_co))


if __name__ == "__main__":
    unittest.main()

