import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from question_answering import (
    qa_engine, 
    classify_question_category, 
    QuestionCategory,
    match_best_option
)
from semantic_form_engine import SemanticFormEngine, SemanticFieldCategory

class TestLogiNextAndResidenceForm(unittest.TestCase):
    def test_01_composite_location_residence_and_language(self):
        """Verify 'Location of Residence and Language:' from DNEG / Jobvite resolves accurately."""
        res = qa_engine.process_question("Location of Residence and Language:")
        self.assertIn("Kurla, Mumbai", res["answer"])
        self.assertIn("English", res["answer"])
        self.assertIn("Hindi", res["answer"])
        self.assertFalse(res["needs_user_input"])

    def test_02_location_of_residence_standalone(self):
        """Verify 'Location of Residence' resolves to Kurla, Mumbai, Maharashtra, India."""
        res = qa_engine.process_question("Location of Residence")
        self.assertEqual(res["answer"], "Kurla, Mumbai, Maharashtra, India")
        self.assertFalse(res["needs_user_input"])

    def test_03_loginext_permanent_address(self):
        """Verify LogiNext permanent address question resolves to candidate ID address."""
        res = qa_engine.process_question("Permanent Address (as per a government issued ID) *")
        self.assertEqual(res["answer"], "Kurla, Mumbai, Maharashtra, India")
        self.assertFalse(res["needs_user_input"])

    def test_04_language_standalone(self):
        """Verify 'Language:' resolves to candidate verified languages (not 'Keine')."""
        res = qa_engine.process_question("Language:")
        self.assertIn("English", res["answer"])
        self.assertNotIn("Keine", res["answer"])
        self.assertFalse(res["needs_user_input"])

    def test_05_ashby_english_level_question(self):
        """Verify Ashby 'What is your level in English*' returns Fluent/Native."""
        res = qa_engine.process_question("What is your level in English*")
        self.assertEqual(res["answer"], "Fluent/Native")
        self.assertFalse(res["needs_user_input"])

    def test_06_ashby_english_level_option_match(self):
        """Verify option matcher matches Fluent/Native in Ashby radio options."""
        options = [
            {"value": "Beginner", "text": "Beginner"},
            {"value": "Intermediate", "text": "Intermediate"},
            {"value": "Fluent/Native", "text": "Fluent/Native"}
        ]
        matched = match_best_option(
            answer="Fluent/Native",
            options=options,
            category=QuestionCategory.LANGUAGE_SKILLS,
            question_context="What is your level in English*"
        )
        self.assertIsNotNone(matched)
        self.assertEqual(matched["value"], "Fluent/Native")

    def test_07_loginext_current_annual_ctc(self):
        """Verify LogiNext 'Current Annual CTC (in INR) * *' returns 1200000."""
        res = qa_engine.process_question("Current Annual CTC (in INR) * *")
        self.assertEqual(res["answer"], "1200000")
        self.assertFalse(res["needs_user_input"])

    def test_08_loginext_expected_annual_ctc(self):
        """Verify LogiNext 'Expected Annual CTC (in INR) * *' returns 1500000."""
        res = qa_engine.process_question("Expected Annual CTC (in INR) * *")
        self.assertEqual(res["answer"], "1500000")
        self.assertFalse(res["needs_user_input"])

    def test_09_loginext_notice_period(self):
        """Verify LogiNext 'Notice Period (In days) *' returns 0 (Immediate joiner)."""
        res = qa_engine.process_question("Notice Period (In days) *")
        self.assertEqual(res["answer"], "0")
        self.assertFalse(res["needs_user_input"])

    def test_10_semantic_classification_permanent_address_and_residence(self):
        """Verify semantic form engine classifies permanent address and residence correctly."""
        cat1, _, _ = SemanticFormEngine.classify_field("Permanent Address (as per a government issued ID)")
        self.assertEqual(cat1, SemanticFieldCategory.RESIDENTIAL_LOCATION)

        cat2, _, _ = SemanticFormEngine.classify_field("Location of Residence")
        self.assertEqual(cat2, SemanticFieldCategory.RESIDENTIAL_LOCATION)

        cat3, _, _ = SemanticFormEngine.classify_field("Location of Residence and Language:")
        self.assertEqual(cat3, SemanticFieldCategory.RESIDENTIAL_LOCATION)

if __name__ == "__main__":
    unittest.main()
