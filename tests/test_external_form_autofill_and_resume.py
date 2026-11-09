"""
Test Suite: External Modern ATS Form Autofill & Resume Attachment
=================================================================
Validates fixes for:
1. Upload CV/Resume mandatory upload resolution without halting for candidate verification.
2. Full Name, Email, Phone, Bio, and Terms Agreement auto-detection and population.
3. Interview transcripts consent radio button selection ("Yes, I consent").
4. Current country dropdown switching from default "United States" to candidate's verified country.
"""

import sys
import os
import unittest

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from semantic_form_engine import SemanticFormEngine, SemanticFieldCategory
from question_answering import QuestionAnsweringEngine, QuestionCategory, match_best_option
from candidate_manager import getCandidateProfileByJobLocation


class TestExternalModernATSAutofill(unittest.TestCase):

    def setUp(self):
        self.qa = QuestionAnsweringEngine()

    def test_01_full_name_semantic_classification_and_value(self):
        """Full Name input with placeholder 'Full name' inside 'General information' section."""
        cat, conf, expl = SemanticFormEngine.classify_field(
            label="Full name",
            heading="General information",
            placeholder="Full name",
            input_type="text"
        )
        self.assertEqual(cat, SemanticFieldCategory.FULL_NAME)
        val, desc = SemanticFormEngine.get_candidate_value(cat)
        self.assertEqual(val, "Abdul Razzaque Shaikh")

    def test_02_email_and_phone_semantic_classification(self):
        """Email and Phone inputs with placeholders inside 'General information' section."""
        cat_email, _, _ = SemanticFormEngine.classify_field(
            label="",
            heading="General information",
            placeholder="Email",
            input_type="text"
        )
        self.assertEqual(cat_email, SemanticFieldCategory.EMAIL_ADDRESS)
        val_email, _ = SemanticFormEngine.get_candidate_value(cat_email)
        self.assertEqual(val_email, "mhaslaiabdur@gmail.com")

        cat_phone, _, _ = SemanticFormEngine.classify_field(
            label="",
            heading="General information",
            placeholder="Phone",
            input_type="tel"
        )
        self.assertEqual(cat_phone, SemanticFieldCategory.PHONE_NUMBER)

    def test_03_bio_semantic_classification_and_answering(self):
        """Bio / Profile Summary input must be populated with verified candidate bio."""
        cat_bio, _, _ = SemanticFormEngine.classify_field(
            label="Bio *",
            placeholder="Tell us about yourself",
            input_type="textarea"
        )
        self.assertEqual(cat_bio, SemanticFieldCategory.PROFESSIONAL_SUMMARY)
        val_bio, _ = SemanticFormEngine.get_candidate_value(cat_bio)
        self.assertIn("Senior Full Stack Developer", val_bio)
        self.assertIn("React.js", val_bio)

        # QA Engine resolution
        res = self.qa.process_question(
            question_text="Bio *",
            input_type="textarea"
        )
        self.assertFalse(res.get("needs_user_input"))
        self.assertIn("Senior Full Stack Developer", res.get("answer", ""))

    def test_04_resume_cv_upload_classification_and_resolution(self):
        """Upload CV* Required / Upload CV/Resume * must resolve to candidate's tailored resume path."""
        labels = [
            "Upload CV* Required",
            "Upload CV/Resume *",
            "CV / Resume (Please attach an English version of your resume)",
            "Drag & drop or click to attach document"
        ]
        for lbl in labels:
            cat, conf, _ = SemanticFormEngine.classify_field(
                label=lbl,
                input_type="file"
            )
            self.assertEqual(cat, SemanticFieldCategory.RESUME_UPLOAD)
            res_path, desc = SemanticFormEngine.get_candidate_value(cat, location_hint="Qatar")
            self.assertTrue(os.path.exists(res_path), f"Resume path does not exist: {res_path}")
            self.assertIn("Qatar", res_path)

    def test_05_terms_and_data_storage_checkbox(self):
        """'By using this form you agree with the storage and handling of your data by this website. *' must be agreed."""
        q_text = "By using this form you agree with the storage and handling of your data by this website. *"
        cat, _, _ = SemanticFormEngine.classify_field(label=q_text, input_type="checkbox")
        self.assertEqual(cat, SemanticFieldCategory.TERMS_ACCEPTANCE)

        res = self.qa.process_question(
            question_text=q_text,
            input_type="checkbox"
        )
        self.assertEqual(res.get("answer"), "true")
        self.assertFalse(res.get("needs_user_input"))

    def test_06_interview_transcripts_consent_radio(self):
        """Interview transcripts consent must select 'Yes, I consent'."""
        options = [
            {"text": "Yes, I consent", "value": "yes"},
            {"text": "No, I don't consent", "value": "no"}
        ]
        res = self.qa.process_question(
            question_text="Interview transcripts",
            input_type="radio_group",
            available_options=options
        )
        self.assertFalse(res.get("needs_user_input"))
        best_opt = match_best_option("Yes", options)
        self.assertIsNotNone(best_opt)
        self.assertEqual(best_opt["text"], "Yes, I consent")

    def test_07_country_resolution_by_location(self):
        """Candidate's country for Qatar applications must be Qatar, for India applications must be India."""
        qatar_prof = getCandidateProfileByJobLocation("Qatar (Remote)")
        self.assertEqual(qatar_prof["detected_country"], "Qatar")
        self.assertEqual(qatar_prof["country_code"], "+974")

        india_prof = getCandidateProfileByJobLocation("Mumbai, India")
        self.assertEqual(india_prof["detected_country"], "India")
        self.assertEqual(india_prof["country_code"], "+91")


if __name__ == "__main__":
    unittest.main()

