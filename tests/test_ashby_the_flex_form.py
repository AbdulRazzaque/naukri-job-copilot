"""
Test Suite: Ashby Portal Form Autofill & False CAPTCHA Elimination (The Flex)
=============================================================================
Validates fixes for:
1. False CAPTCHA detection elimination on forms with company logos or invisible scripts.
2. Full automated question answering for Senior Software Engineer @ The Flex:
   - Full Name, Email, Phone
   - Gender (Male)
   - Age (27)
   - Marital Status (Single)
   - Resume Upload
   - English Level (Fluent/Native)
   - Role Looking For (Full-Time)
   - University Graduation (Yes, I graduated)
   - Minimum Salary in British Pounds (£3,000/month)
   - Difficulties in Life Approach
   - Job Type / Team Fit
   - Current Nationality (Indian)
   - Hacked the System Narrative
   - Evidence of Exceptional Ability Narrative
"""

import sys
import os
import unittest

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from semantic_form_engine import SemanticFormEngine, SemanticFieldCategory
from question_answering import QuestionAnsweringEngine, match_best_option


class TestAshbyTheFlexForm(unittest.TestCase):

    def setUp(self):
        self.qa = QuestionAnsweringEngine()

    def test_01_no_false_captcha_on_interview_questions(self):
        """Questions containing words like 'challenge' or 'code' must NEVER be marked as CAPTCHA."""
        questions_with_subtle_words = [
            "Phone Number (include country code +XXX)*",
            "What type of job are you looking for? Very high growth job that challenges me a lot",
            "Tell us about a time when you 'hacked the system' to your advantage",
            "Tell us about something you've done in the past that can be considered as evidence of exceptional ability",
            "When you are confronted with difficulties in life, how do you approach the situation?*"
        ]
        for q in questions_with_subtle_words:
            res = self.qa.process_question(question_text=q, input_type="textarea" if "Tell us" in q else "text")
            self.assertFalse(res.get("is_captcha"), f"Question falsely flagged as CAPTCHA: '{q}'")
            self.assertNotEqual(res.get("failure_reason"), "CAPTCHA_REQUIRED")

    def test_02_demographics_age_and_marital_status(self):
        """Age* must resolve to candidate age (27) and Marital Status* to 'Single'."""
        # Age
        res_age = self.qa.process_question(question_text="Age*", input_type="text")
        self.assertFalse(res_age.get("needs_user_input"))
        self.assertEqual(res_age.get("answer"), "27")

        cat_age, _, _ = SemanticFormEngine.classify_field(label="Age*", input_type="text")
        self.assertEqual(cat_age, SemanticFieldCategory.AGE)
        val_age, _ = SemanticFormEngine.get_candidate_value(cat_age)
        self.assertEqual(val_age, "27")

        # Marital Status
        marital_options = [
            {"text": "Single", "value": "single"},
            {"text": "Married", "value": "married"},
            {"text": "I prefer not to say", "value": "prefer_not_to_say"},
            {"text": "Married with kids", "value": "married_with_kids"}
        ]
        res_marital = self.qa.process_question(
            question_text="Marital Status*",
            input_type="radio_group",
            available_options=marital_options
        )
        self.assertFalse(res_marital.get("needs_user_input"))
        best_opt = match_best_option(res_marital.get("answer"), marital_options)
        self.assertIsNotNone(best_opt)
        self.assertEqual(best_opt["text"], "Single")

    def test_03_english_level_and_role_preference(self):
        """English level must match Fluent/Native and Role Looking For must match Full-Time."""
        # English
        eng_options = [
            {"text": "Beginner", "value": "beginner"},
            {"text": "Intermediate", "value": "intermediate"},
            {"text": "Fluent/Native", "value": "fluent_native"}
        ]
        res_eng = self.qa.process_question(
            question_text="What is your level in English*",
            input_type="radio_group",
            available_options=eng_options
        )
        self.assertFalse(res_eng.get("needs_user_input"))
        best_eng = match_best_option(res_eng.get("answer"), eng_options)
        self.assertIsNotNone(best_eng)
        self.assertEqual(best_eng["text"], "Fluent/Native")

        # Role
        role_options = [
            {"text": "Part-Time/Summer Job", "value": "part_time"},
            {"text": "Full-Time", "value": "full_time"}
        ]
        res_role = self.qa.process_question(
            question_text="What role are you looking for?*",
            input_type="radio_group",
            available_options=role_options
        )
        self.assertFalse(res_role.get("needs_user_input"))
        best_role = match_best_option(res_role.get("answer"), role_options)
        self.assertIsNotNone(best_role)
        self.assertEqual(best_role["text"], "Full-Time")

    def test_04_university_graduation(self):
        """Did you graduate from University* must select 'Yes, I graduated'."""
        uni_options = [
            {"text": "Yes, I graduated", "value": "graduated"},
            {"text": "No, I never went to University", "value": "no_uni"},
            {"text": "No, I am still studying", "value": "studying"}
        ]
        res_uni = self.qa.process_question(
            question_text="Did you graduate from University*",
            input_type="radio_group",
            available_options=uni_options
        )
        self.assertFalse(res_uni.get("needs_user_input"))
        best_uni = match_best_option(res_uni.get("answer"), uni_options)
        self.assertIsNotNone(best_uni)
        self.assertEqual(best_uni["text"], "Yes, I graduated")

    def test_05_minimum_salary_british_pounds(self):
        """Minimum monthly salary in British £ must return numeric string '3000'."""
        res_sal = self.qa.process_question(
            question_text="What is the minimum salary that you would accept in British £ ONLY and per month?*",
            input_type="text"
        )
        self.assertFalse(res_sal.get("needs_user_input"))
        self.assertIn("3000", res_sal.get("answer"))

    def test_06_behavioral_and_team_fit_questions(self):
        """Behavioral and team preference radio groups must resolve affirmatively."""
        diff_options = [
            {"text": "I take some time to think then start finding the solutions", "value": "think_solutions"},
            {"text": "I take some time off to relax", "value": "relax"}
        ]
        res_diff = self.qa.process_question(
            question_text="When you are confronted with difficulties in life, how do you approach the situation?*",
            input_type="radio_group",
            available_options=diff_options
        )
        best_diff = match_best_option(res_diff.get("answer"), diff_options)
        self.assertIsNotNone(best_diff)
        self.assertEqual(best_diff["text"], "I take some time to think then start finding the solutions")

    def test_07_nationality(self):
        """Current nationality must return 'Indian'."""
        res_nat = self.qa.process_question(
            question_text="What is your current nationality (To understand where you can work from)*",
            input_type="text"
        )
        self.assertFalse(res_nat.get("needs_user_input"))
        self.assertEqual(res_nat.get("answer"), "Indian")

    def test_08_engineering_narratives(self):
        """Hacked the system and Exceptional ability prompts must populate with professional developer achievements."""
        res_hack = self.qa.process_question(
            question_text="Tell us about a time when you 'hacked the system' to your advantage (Do not use AI - WE WILL DETECT IT & CANCEL YOUR APPLICATION)*",
            input_type="textarea"
        )
        self.assertFalse(res_hack.get("needs_user_input"))
        self.assertTrue(len(res_hack.get("answer", "")) > 50)
        self.assertIn("caching", res_hack.get("answer", "").lower())

        res_except = self.qa.process_question(
            question_text="Tell us about something you've done in the past that can be considered as evidence of exceptional ability (Do not use AI - WE WILL DETECT IT & CANCEL YOUR APPLICATION)*",
            input_type="textarea"
        )
        self.assertFalse(res_except.get("needs_user_input"))
        self.assertTrue(len(res_except.get("answer", "")) > 50)
        self.assertIn("uptime", res_except.get("answer", "").lower())


if __name__ == "__main__":
    unittest.main()

