import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from question_answering import QuestionAnsweringEngine, QuestionCategory
from semantic_form_engine import SemanticFormEngine, SemanticFieldCategory


class TestScaleAiAndAshbyForms(unittest.TestCase):
    def setUp(self):
        self.qa = QuestionAnsweringEngine()

    def test_01_scale_ai_core_technical_stack(self):
        """Scale AI: 'What is your core technical stack?*' must answer MERN Stack and never pause."""
        res = self.qa.process_question("What is your core technical stack?*", "text")
        self.assertFalse(res.get("needs_user_input", False))
        self.assertIn("MERN", res.get("answer", ""))
        self.assertIn("React", res.get("answer", ""))
        self.assertIn("Node", res.get("answer", ""))

    def test_02_scale_ai_non_compete_restrictive_agreements(self):
        """Scale AI: Restrictive agreements / non-compete question must answer 'No', NEVER 'Tharb'."""
        q = (
            "Are you currently bound by any agreements with a current or former employer that may restrict "
            "your ability to work for Scale AI or perform the duties of the position for which you are applying? "
            "This includes, but is not limited to, non-compete agreements, non-solicitation agreements, "
            "confidentiality or non-disclosure agreements, or any other contractual obligations that could limit your employment activities.*"
        )
        res = self.qa.process_question(q, "radio_group", available_options=[{"value": "Yes", "text": "Yes"}, {"value": "No", "text": "No"}])
        self.assertFalse(res.get("needs_user_input", False))
        self.assertEqual(res.get("answer"), "No")
        self.assertNotEqual(res.get("answer"), "Tharb")

    def test_03_scale_ai_sponsorship_vs_authorization(self):
        """Scale AI: Sponsorship question must answer 'No' even though it contains 'work authorization'."""
        q = "Will you now or in the future require company sponsorship to retain or extend your work authorization in the country where the job is located?*"
        res = self.qa.process_question(q, "radio_group", available_options=[{"value": "Yes", "text": "Yes"}, {"value": "No", "text": "No"}])
        self.assertFalse(res.get("needs_user_input", False))
        self.assertEqual(res.get("answer"), "No")

    def test_04_scale_ai_authorized_to_work(self):
        """Scale AI: 'Are you legally authorized to work in the country where the job is located?*' must answer 'Yes'."""
        q = "Are you legally authorized to work in the country where the job is located?*"
        res = self.qa.process_question(q, "radio_group", available_options=[{"value": "Yes", "text": "Yes"}, {"value": "No", "text": "No"}])
        self.assertFalse(res.get("needs_user_input", False))
        self.assertEqual(res.get("answer"), "Yes")

    def test_05_scale_ai_relocation_middle_east(self):
        """Scale AI: 'Are you open to relocation to the Middle East?*' must answer 'Yes'."""
        q = "Are you open to relocation to the Middle East?*"
        res = self.qa.process_question(q, "radio_group", available_options=[{"value": "Yes", "text": "Yes"}, {"value": "No", "text": "No"}])
        self.assertFalse(res.get("needs_user_input", False))
        self.assertEqual(res.get("answer"), "Yes")

    def test_06_scale_ai_country_located_in(self):
        """Scale AI: 'What country are you located in?*' must answer candidate country ('India')."""
        q = "What country are you located in?*"
        res = self.qa.process_question(q, "text")
        self.assertFalse(res.get("needs_user_input", False))
        self.assertEqual(res.get("answer"), "India")

    def test_07_scale_ai_location_city(self):
        """Scale AI: 'Location (City)*' must answer 'Mumbai, Maharashtra, India'."""
        q = "Location (City)*"
        res = self.qa.process_question(q, "autocomplete")
        self.assertFalse(res.get("needs_user_input", False))
        self.assertIn("Mumbai", res.get("answer", ""))

    def test_08_semantic_first_name_and_last_name(self):
        """SemanticFormEngine correctly classifies and resolves First Name and Last Name."""
        cat_fn, _, _ = SemanticFormEngine.classify_field(label="First Name*", input_type="text")
        val_fn, _ = SemanticFormEngine.get_candidate_value(cat_fn)
        self.assertEqual(cat_fn, SemanticFieldCategory.FIRST_NAME)
        self.assertEqual(val_fn, "Abdul Razzaque")

        cat_ln, _, _ = SemanticFormEngine.classify_field(label="Last Name*", input_type="text")
        val_ln, _ = SemanticFormEngine.get_candidate_value(cat_ln)
        self.assertEqual(cat_ln, SemanticFieldCategory.LAST_NAME)
        self.assertEqual(val_ln, "Shaikh")

    def test_09_ashby_the_flex_full_suite(self):
        """Ashby 'the flex.' questions resolve with 100% confidence."""
        # 1. Salary in British £ ONLY
        res_sal = self.qa.process_question("What is the minimum salary that you would accept in British £ ONLY and per month?*", "text")
        self.assertFalse(res_sal.get("needs_user_input", False))
        self.assertEqual(res_sal.get("answer"), "3000")

        # 2. English Level
        res_eng = self.qa.process_question("What is your level in English*", "radio_group", available_options=[
            {"value": "Beginner", "text": "Beginner"},
            {"value": "Intermediate", "text": "Intermediate"},
            {"value": "Fluent/Native", "text": "Fluent/Native"}
        ])
        self.assertFalse(res_eng.get("needs_user_input", False))
        self.assertEqual(res_eng.get("answer"), "Fluent/Native")

        # 3. Graduate from University
        res_grad = self.qa.process_question("Did you graduate from University*", "radio_group", available_options=[
            {"value": "Yes, I graduated", "text": "Yes, I graduated"},
            {"value": "No, I never went to University", "text": "No, I never went to University"},
            {"value": "No, I am still studying", "text": "No, I am still studying"}
        ])
        self.assertFalse(res_grad.get("needs_user_input", False))
        self.assertEqual(res_grad.get("answer"), "Yes, I graduated")

        # 4. Nationality
        res_nat = self.qa.process_question("What is your current nationality (To understand where you can work from)*", "text")
        self.assertFalse(res_nat.get("needs_user_input", False))
        self.assertEqual(res_nat.get("answer"), "Indian")

        # 5. Difficulties in life
        res_diff = self.qa.process_question("When you are confronted with difficulties in life, how do you approach the situation?*", "radio_group")
        self.assertFalse(res_diff.get("needs_user_input", False))
        self.assertIn("solutions", res_diff.get("answer", ""))

        # 6. Type of job
        res_job = self.qa.process_question("What type of job are you looking for? Please be very honest, this would allow us to put you in the right team based on your answer.*", "radio_group")
        self.assertFalse(res_job.get("needs_user_input", False))
        self.assertIn("Secure and stable", res_job.get("answer", ""))

        # 7. Hacked the system narrative
        res_hack = self.qa.process_question("Tell us about a time when you \"hacked the system\" to your advantage (Do not use AI - WE WILL DETECT IT & CANCEL YOUR APPLICATION)*", "textarea")
        self.assertFalse(res_hack.get("needs_user_input", False))
        self.assertIn("caching", res_hack.get("answer", ""))

        # 8. Evidence of exceptional ability narrative
        res_exc = self.qa.process_question("Tell us about something you've done in the past that can be considered as evidence of exceptional ability (Do not use AI - WE WILL DETECT IT & CANCEL YOUR APPLICATION)*", "textarea")
        self.assertFalse(res_exc.get("needs_user_input", False))
        self.assertIn("autonomous", res_exc.get("answer", ""))

    def test_10_conflict_of_interest_and_personal_facts(self):
        """Questions on relatives, family members, background checks, and age resolve autonomously."""
        # Morningstar question: Do you have a family member or romantic partner who is currently employed by Morningstar?
        q_morn = "Do you have a family member or romantic partner who is currently employed by Morningstar?"
        res_morn = self.qa.process_question(q_morn, "radio_group", available_options=[{"value": "Yes", "text": "Yes"}, {"value": "No", "text": "No"}])
        self.assertFalse(res_morn.get("needs_user_input", False))
        self.assertEqual(res_morn.get("answer"), "No")

        # Relatives employed in company
        q_rel = "Are any of your relatives or family members employed with us?"
        res_rel = self.qa.process_question(q_rel, "radio_group", available_options=[{"value": "Yes", "text": "Yes"}, {"value": "No", "text": "No"}])
        self.assertFalse(res_rel.get("needs_user_input", False))
        self.assertEqual(res_rel.get("answer"), "No")

        # Criminal conviction
        q_crim = "Have you ever been convicted of a crime or felony?"
        res_crim = self.qa.process_question(q_crim, "radio_group", available_options=[{"value": "Yes", "text": "Yes"}, {"value": "No", "text": "No"}])
        self.assertFalse(res_crim.get("needs_user_input", False))
        self.assertEqual(res_crim.get("answer"), "No")

        # Age 18+ verification
        q_age18 = "Are you 18 years of age or older?"
        res_age18 = self.qa.process_question(q_age18, "radio_group", available_options=[{"value": "Yes", "text": "Yes"}, {"value": "No", "text": "No"}])
        self.assertFalse(res_age18.get("needs_user_input", False))
        self.assertEqual(res_age18.get("answer"), "Yes")

        # Background verification consent
        q_bg = "Are you willing to undergo a background check?"
        res_bg = self.qa.process_question(q_bg, "radio_group", available_options=[{"value": "Yes", "text": "Yes"}, {"value": "No", "text": "No"}])
        self.assertFalse(res_bg.get("needs_user_input", False))
        self.assertEqual(res_bg.get("answer"), "Yes")

        # Driver's license
        q_dl = "Do you have a valid driver's license?"
        res_dl = self.qa.process_question(q_dl, "radio_group", available_options=[{"value": "Yes", "text": "Yes"}, {"value": "No", "text": "No"}])
        self.assertFalse(res_dl.get("needs_user_input", False))
        self.assertEqual(res_dl.get("answer"), "Yes")

        # EEO Race
        q_race = "What is your race / ethnicity?"
        res_race = self.qa.process_question(q_race, "select", available_options=[
            {"value": "White", "text": "White"},
            {"value": "Asian", "text": "Asian"},
            {"value": "Black", "text": "Black"}
        ])
        self.assertFalse(res_race.get("needs_user_input", False))
        self.assertEqual(res_race.get("answer"), "Asian")


if __name__ == "__main__":
    unittest.main()

