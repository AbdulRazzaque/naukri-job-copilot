"""
Automated Test Suite for Semantic Form Understanding, Candidate Data Mapping,
Country Code Precision (+974 Qatar vs +971 UAE), Date of Birth, and CAPTCHA Safety.
"""

import unittest
import sys
import os

# Add backend directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from semantic_form_engine import SemanticFormEngine, SemanticFieldCategory
from candidate_manager import getCandidateProfileByJobLocation
from question_answering import QuestionAnsweringEngine, QuestionCategory
from database import check_already_applied_db as is_job_already_processed, get_dashboard_stats


class TestSemanticFormAutofill(unittest.TestCase):

    def setUp(self):
        self.qa = QuestionAnsweringEngine()

    def test_01_salary_semantic_classification(self):
        """Test current monthly salary vs expected monthly salary vs annual CTC."""
        cat, conf, _ = SemanticFormEngine.classify_field(
            label="Current Monthly Renumeration/Salary *",
            heading="Compensation Details",
            help_text="Provide your current Cost-To-Company (CTC), in your local currency."
        )
        self.assertEqual(cat, SemanticFieldCategory.CURRENT_MONTHLY_SALARY)
        self.assertGreaterEqual(conf, 0.90)

        cat2, conf2, _ = SemanticFormEngine.classify_field(
            label="Expected Monthly Renumeration/Salary *",
            heading="Compensation Details",
            help_text="Provide your expected Cost-To-Company (CTC), in you local currency."
        )
        self.assertEqual(cat2, SemanticFieldCategory.EXPECTED_MONTHLY_SALARY)
        self.assertGreaterEqual(conf2, 0.90)

        cat3, conf3, _ = SemanticFormEngine.classify_field(
            label="Current Annual CTC",
            heading="Salary",
            help_text="Annual CTC in INR"
        )
        self.assertEqual(cat3, SemanticFieldCategory.CURRENT_ANNUAL_CTC)
        self.assertGreaterEqual(conf3, 0.90)

    def test_02_salary_value_mapping_no_essay_pollution(self):
        """Test that salary values are clean numeric/local currency, never essay paragraphs."""
        # Gulf location (Dubai, UAE) -> 8000 QAR
        val_gulf, _ = SemanticFormEngine.get_candidate_value(
            category=SemanticFieldCategory.CURRENT_MONTHLY_SALARY,
            location_hint="Dubai, United Arab Emirates"
        )
        self.assertIn("8000", val_gulf)
        self.assertNotIn("Senior Full Stack Developer", val_gulf)
        self.assertNotIn("React", val_gulf)
        self.assertLess(len(val_gulf), 20)

        # India location (Mumbai) -> 83,000 INR
        val_india, _ = SemanticFormEngine.get_candidate_value(
            category=SemanticFieldCategory.CURRENT_MONTHLY_SALARY,
            location_hint="Mumbai, India"
        )
        self.assertIn("83", val_india)
        self.assertNotIn("Senior Full Stack Developer", val_india)

    def test_03_phone_country_code_strict_qatar_vs_uae(self):
        """
        CRITICAL: For Dubai/UAE/Qatar/Gulf jobs, phone country code MUST strictly be +974 (Qatar).
        Candidate does NOT have a UAE (+971) phone number. NEVER return +971!
        """
        # 1. Dubai, UAE job
        cand_dubai = getCandidateProfileByJobLocation("Dubai, United Arab Emirates")
        self.assertEqual(cand_dubai["country_code"], "+974")
        self.assertNotEqual(cand_dubai["country_code"], "+971")

        val_dubai, _ = SemanticFormEngine.get_candidate_value(
            category=SemanticFieldCategory.PHONE_COUNTRY_CODE,
            location_hint="Dubai, UAE"
        )
        self.assertEqual(val_dubai, "+974")
        self.assertNotEqual(val_dubai, "+971")

        # 2. Doha, Qatar job
        val_qatar, _ = SemanticFormEngine.get_candidate_value(
            category=SemanticFieldCategory.PHONE_COUNTRY_CODE,
            location_hint="Doha, Qatar"
        )
        self.assertEqual(val_qatar, "+974")

        # 3. Mumbai, India job
        val_mumbai, _ = SemanticFormEngine.get_candidate_value(
            category=SemanticFieldCategory.PHONE_COUNTRY_CODE,
            location_hint="Mumbai, India"
        )
        self.assertEqual(val_mumbai, "+91")

    def test_04_phone_country_code_sanitizer_removes_971(self):
        """Sanitizer must detect and correct +971 to +974 for international candidate profile."""
        is_valid, corrected, reason = SemanticFormEngine.sanitize_and_validate_field(
            category=SemanticFieldCategory.PHONE_COUNTRY_CODE,
            current_value="+971",
            location_hint="Dubai, UAE"
        )
        self.assertFalse(is_valid)
        self.assertEqual(corrected, "+974")
        self.assertIn("+971 detected", reason)

    def test_05_date_of_birth_detection_and_value(self):
        """Test Date of Birth detection and value mapping (19-11-1999)."""
        cat, conf, _ = SemanticFormEngine.classify_field(
            label="Date of Birth",
            heading="Personal Details",
            name="dateOfBirth",
            field_id="dateOfBirth"
        )
        self.assertEqual(cat, SemanticFieldCategory.DATE_OF_BIRTH)

        val_dob, _ = SemanticFormEngine.get_candidate_value(
            category=SemanticFieldCategory.DATE_OF_BIRTH,
            input_type="text"
        )
        self.assertEqual(val_dob, "19-11-1999")

        val_dob_iso, _ = SemanticFormEngine.get_candidate_value(
            category=SemanticFieldCategory.DATE_OF_BIRTH,
            input_type="date"
        )
        self.assertEqual(val_dob_iso, "1999-11-19")

    def test_06_captcha_safety_and_detection(self):
        """
        CRITICAL SAFETY RULE: CAPTCHA fields must be detected, kept empty,
        and never populated with roles or summaries.
        """
        cat, conf, _ = SemanticFormEngine.classify_field(
            label="Captcha",
            heading="",
            name="captcha",
            field_id="captcha"
        )
        self.assertEqual(cat, SemanticFieldCategory.CAPTCHA)

        val_cap, _ = SemanticFormEngine.get_candidate_value(category=SemanticFieldCategory.CAPTCHA)
        self.assertEqual(val_cap, "")

        # Test QA Engine does not output 'Senior Full Stack Developer' for captcha
        qa_res = self.qa.process_question(
            question_text="Captcha",
            field_name="captcha",
            field_id="captcha"
        )
        self.assertEqual(qa_res["answer"], "")
        self.assertTrue(qa_res["needs_user_input"])
        self.assertTrue(qa_res["is_blocked"])

    def test_07_salary_pollution_sanitizer(self):
        """Sanitizer must strip 400+ char essays from salary fields."""
        essay = "I bring 5+ years of production experience as a Senior Full Stack Developer specializing in React.js, Next.js, Node.js..."
        is_valid, corrected, reason = SemanticFormEngine.sanitize_and_validate_field(
            category=SemanticFieldCategory.CURRENT_MONTHLY_SALARY,
            current_value=essay,
            location_hint="Dubai, UAE"
        )
        self.assertFalse(is_valid)
        self.assertIn("8000", corrected)
        self.assertIn("POLLUTION DETECTED", reason)

    def test_08_duplicate_detection_sokin_job(self):
        """Duplicate detection must recognize Sokin job by ID, URL, and title+company."""
        # Check by LinkedIn job ID
        is_dup_id = is_job_already_processed(job_id="4463577090")
        self.assertTrue(is_dup_id)

        # Check by Job URL
        is_dup_url = is_job_already_processed(job_url="https://www.linkedin.com/jobs/view/4463577090/")
        self.assertTrue(is_dup_url)

        # Check by Title and Company (case-insensitive)
        is_dup_meta = is_job_already_processed(title="Senior Fullstack Engineer - Dubai", company="Sokin")
        self.assertTrue(is_dup_meta)

    def test_09_dashboard_stats_applied_counts(self):
        """Dashboard stats must report LinkedIn, Naukri, and total applied numbers."""
        stats = get_dashboard_stats()
        self.assertGreater(stats["total_applied"], 200)
        self.assertGreater(stats["naukri_applied"], 100)
        self.assertGreater(stats["linkedin_applied"], 50)
        self.assertGreaterEqual(stats["today_applied"], 10)
        self.assertGreaterEqual(stats["today_linkedin"], 10)

    def test_10_generic_label_contextual_fallback(self):
        """Generic labels like 'Your answer' must fall back to heading text."""
        cat, conf, _ = SemanticFormEngine.classify_field(
            label="Your answer",
            heading="Current Monthly Renumeration/Salary *",
            help_text="Provide your current Cost-To-Company (CTC), in your local currency."
        )
        self.assertEqual(cat, SemanticFieldCategory.CURRENT_MONTHLY_SALARY)

    def test_11_duplicate_detection_for_skipped_jobs(self):
        """CRITICAL: If a job was SKIPPED previously, it must be recognized as already processed and blocked from re-application."""
        # Virtusa was skipped for LOCATION_MISMATCH
        is_dup_virtusa = is_job_already_processed(title="Fullstack Developer", company="Virtusa")
        self.assertTrue(is_dup_virtusa, "Virtusa skipped job must be detected and blocked from re-application")

    def test_12_duplicate_detection_by_external_url(self):
        """CRITICAL: External career portal URLs must be checked to prevent redirecting to already processed websites."""
        # CannonDesign was processed on external URL
        is_dup_ext = is_job_already_processed(external_url="https://www.cannondesign.com/careers/sr-software-engineer?gh_jid=8643133002")
        self.assertTrue(is_dup_ext, "External career portal URL must be detected and blocked from re-application")


if __name__ == "__main__":
    unittest.main()
