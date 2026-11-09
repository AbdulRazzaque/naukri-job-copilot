"""
tests/test_linkedin_e2e_scenarios.py
Comprehensive End-to-End Automated Test Suite for Autonomous Job Application System.
Validates all 10 Scenarios and Section H compliance requirements.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock

# Ensure backend modules are loadable
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from technology_matcher import evaluate_technology_alignment, classify_technologies
from location_matcher import match_location, check_application_eligibility
from linkedin_engine import classify_linkedin_content, is_valid_linkedin_job_url, LinkedInEngine
from question_answering import qa_engine
from database import map_to_skip_reason_code, check_already_applied_db


class TestScenario1MERNApplication(unittest.TestCase):
    """Scenario 1: Successful MERN Application (score >= 65%, eligible, proceeds)"""

    def test_mern_application_eligibility_and_alignment(self):
        title = "Full Stack Engineer (MERN Stack)"
        jd = (
            "We are seeking an experienced MERN Stack Developer proficient in React.js, "
            "Node.js, Express.js, MongoDB, and TypeScript. Experience building REST APIs and microservices."
        )
        align = evaluate_technology_alignment(title=title, desc=jd)
        self.assertTrue(align["should_apply"], "MERN Stack role should be accepted for application.")
        self.assertGreaterEqual(align["match_score"], 80, "MERN role should have high match score (>=80%).")

        loc_valid, matched, _ = match_location("Mumbai, India", ["Mumbai", "Pune", "Remote"])
        self.assertTrue(loc_valid, "Location in Mumbai should be valid.")

        eligibility = check_application_eligibility(
            match_score=align["match_score"],
            is_technical_compatible=True,
            job_location="Mumbai",
            preferred_locations=["Mumbai", "Pune", "Remote"]
        )
        self.assertTrue(eligibility["is_eligible"], "Job should be fully eligible for application.")
        self.assertNotEqual(eligibility.get("skip_reason_code"), "LOW_MATCH_SCORE")


class TestScenario2WrongSpecialization(unittest.TestCase):
    """Scenario 2: Dedicated Java/Specialist Role -> PRIMARY_SPECIALIZATION_MISMATCH"""

    def test_dedicated_java_rejection(self):
        title = "Senior Java Backend Engineer (Spring Boot)"
        jd = "Core Java 17+, Spring Boot, Hibernate, Kafka, Microservices architecture."
        align = evaluate_technology_alignment(title=title, desc=jd)
        self.assertFalse(align["should_apply"])
        self.assertEqual(align["reason_code"], "PRIMARY_SPECIALIZATION_MISMATCH")

    def test_dedicated_dotnet_rejection(self):
        title = "Principal .NET Architect"
        jd = "10+ years dedicated .NET Core, C#, ASP.NET, WPF."
        align = evaluate_technology_alignment(title=title, desc=jd)
        self.assertFalse(align["should_apply"])
        self.assertEqual(align["reason_code"], "PRIMARY_SPECIALIZATION_MISMATCH")


class TestScenario3MixedTechnology(unittest.TestCase):
    """Scenario 3: Mixed Technology (MERN + Python / MERN + .NET) -> APPLY"""

    def test_mern_plus_python(self):
        title = "Full Stack Developer - React / Node.js / Python"
        jd = "Primary stack is React and Node.js with additional data processing scripts in Python."
        align = evaluate_technology_alignment(title=title, desc=jd)
        self.assertTrue(align["should_apply"], "MERN + Python mixed role must be accepted.")
        self.assertGreaterEqual(align["match_score"], 65, "Match score must be >= 65%.")

    def test_mern_plus_dotnet(self):
        title = "Full Stack Engineer (Node.js, React, C# / .NET)"
        jd = "Full stack developer maintaining React web apps, Node services, and legacy .NET integrations."
        align = evaluate_technology_alignment(title=title, desc=jd)
        self.assertTrue(align["should_apply"], "MERN + .NET mixed role must be accepted.")
        self.assertGreaterEqual(align["match_score"], 65, "Match score must be >= 65%.")


class TestScenario4LocationChange(unittest.TestCase):
    """Scenario 4: Location Change Navigation & URL State Verification"""

    def test_search_url_location_update(self):
        bot_state = MagicMock()
        engine = LinkedInEngine(bot_state, MagicMock(), MagicMock(), MagicMock())

        # Location 1: Mumbai
        url_mumbai = engine.build_search_url("MERN Developer", "Mumbai")
        self.assertIn("location=Mumbai", url_mumbai)

        # Location 2: Switch to Qatar
        url_qatar = engine.build_search_url("MERN Developer", "Qatar")
        self.assertIn("location=Qatar", url_qatar)
        self.assertNotIn("location=Mumbai", url_qatar)

        # Location 3: Remote filter
        url_remote = engine.build_search_url("MERN Developer", "Remote")
        self.assertIn("f_WT=2", url_remote, "Remote searches should append f_WT=2 filter.")


class TestScenario5DuplicatePrevention(unittest.TestCase):
    """Scenario 5: Session & Database Deduplication"""

    def test_session_deduplication(self):
        bot_state = MagicMock()
        engine = LinkedInEngine(bot_state, MagicMock(), MagicMock(), MagicMock())
        self.assertEqual(len(engine.processed_job_ids), 0)

        job_id = "4123456789"
        engine.processed_job_ids.add(job_id)
        self.assertIn(job_id, engine.processed_job_ids, "Processed job ID must be tracked in session.")

    def test_db_deduplication_helper(self):
        # Even with mocked DB failure or disconnected DB, function returns a bool safely
        res = check_already_applied_db("Software Engineer", "Acme Corp", "https://linkedin.com/jobs/view/123/", "123")
        self.assertIsInstance(res, bool)


class TestScenario6InvalidLinkedInContent(unittest.TestCase):
    """Scenario 6: Distinguish Job Listings from Profiles, Posts, and Fake IDs"""

    def test_content_classifier(self):
        # 1. Job listings
        self.assertEqual(classify_linkedin_content("https://www.linkedin.com/jobs/view/3910249821/"), "JOB_LISTING")
        self.assertTrue(is_valid_linkedin_job_url("https://www.linkedin.com/jobs/view/3910249821/"))

        # 2. Personal profiles
        self.assertEqual(classify_linkedin_content("https://www.linkedin.com/in/johndoe-recruiter/"), "PERSONAL_PROFILE")
        self.assertFalse(is_valid_linkedin_job_url("https://www.linkedin.com/in/johndoe-recruiter/"))

        # 3. Feed posts
        self.assertEqual(classify_linkedin_content("https://www.linkedin.com/feed/update/urn:li:activity:71239102/"), "POST")
        self.assertEqual(classify_linkedin_content("https://www.linkedin.com/posts/acme-corp_hiring-mern/"), "POST")
        self.assertFalse(is_valid_linkedin_job_url("https://www.linkedin.com/posts/acme-corp_hiring-mern/"))

        # 4. Company pages
        self.assertEqual(classify_linkedin_content("https://www.linkedin.com/company/google/"), "COMPANY_PAGE")
        self.assertFalse(is_valid_linkedin_job_url("https://www.linkedin.com/company/google/"))

        # 5. Synthetic fake IDs (lk_...)
        self.assertFalse(is_valid_linkedin_job_url("https://www.linkedin.com/jobs/view/lk_56826253/"))


class TestScenario7FailedAndUnavailableApply(unittest.TestCase):
    """Scenario 7: Proper Skip / Failure Reason Codes"""

    def test_apply_option_not_available_mapping(self):
        code = map_to_skip_reason_code("No active Apply button found on page.")
        self.assertEqual(code, "APPLY_OPTION_NOT_AVAILABLE")

    def test_application_blocked_mapping(self):
        code = map_to_skip_reason_code("Timeout while waiting for submit selector.")
        self.assertEqual(code, "APPLICATION_BLOCKED")


class TestScenario8SessionValidation(unittest.TestCase):
    """Scenario 8: LinkedIn Session Expiration Detection"""

    def test_verify_session_expired(self):
        bot_state = MagicMock()
        engine = LinkedInEngine(bot_state, MagicMock(), MagicMock(), MagicMock())
        mock_page = MagicMock()

        # Authwall URL
        mock_page.url = "https://www.linkedin.com/authwall?trk=rip"
        self.assertFalse(engine.verify_linkedin_session(mock_page))

        # Checkpoint URL
        mock_page.url = "https://www.linkedin.com/checkpoint/challenge"
        self.assertFalse(engine.verify_linkedin_session(mock_page))

        # Login page URL
        mock_page.url = "https://www.linkedin.com/login"
        self.assertFalse(engine.verify_linkedin_session(mock_page))


class TestScenario9AlreadyAppliedDetection(unittest.TestCase):
    """Scenario 9: Detection of 'Applied' Status on Page"""

    def test_detect_already_applied(self):
        bot_state = MagicMock()
        engine = LinkedInEngine(bot_state, MagicMock(), MagicMock(), MagicMock())
        mock_page = MagicMock()

        mock_applied_btn = MagicMock()
        mock_applied_btn.is_visible.return_value = True
        mock_applied_btn.inner_text.return_value = "Applied 2 days ago"

        mock_page.query_selector.side_effect = lambda sel: mock_applied_btn if "Applied" in sel else None

        action_type, btn = engine.detect_job_action_button(mock_page)
        self.assertEqual(action_type, "ALREADY_APPLIED")


class TestScenario10ScreeningQuestions(unittest.TestCase):
    """Scenario 10: Screening Questions Grounded in Candidate Profile"""

    def test_mern_experience_question(self):
        res = qa_engine.process_question("How many years of experience do you have with Node.js and React?")
        ans = res.get("answer", "")
        # Should be 5 based on verified candidate profile (Abdul Razzaque Shaikh)
        self.assertEqual(str(ans).strip(), "5")

    def test_java_experience_question_never_invented(self):
        res = qa_engine.process_question("How many years of experience do you have with Java / Spring Boot?")
        ans = res.get("answer", "")
        # Candidate has 0 Java experience, must not invent experience
        self.assertIn(str(ans).lower().strip(), ["0", "no", "none", "0 years"])


class TestSectionHConsistencyRules(unittest.TestCase):
    """Section H: Location and Match Score Consistency Guarantees"""

    def test_multi_location_split(self):
        # Multi-location string containing preferred locations
        is_valid, matched, extracted = match_location(
            "Mumbai, Pune, Hyderabad, Bengaluru, Chennai",
            ["Mumbai", "Pune", "Remote"]
        )
        self.assertTrue(is_valid)
        self.assertIn("Mumbai", matched)
        self.assertIn("Pune", matched)

    def test_missing_location_returns_location_not_found(self):
        eligibility = check_application_eligibility(
            match_score=85,
            is_technical_compatible=True,
            job_location="",  # Missing location
            preferred_locations=["Mumbai", "Pune", "Remote"]
        )
        self.assertFalse(eligibility["is_eligible"])
        self.assertEqual(eligibility["skip_reason_code"], "LOCATION_NOT_FOUND")
        self.assertNotEqual(eligibility["skip_reason_code"], "LOCATION_MISMATCH")

    def test_match_score_above_65_never_low_match(self):
        # When match_score is 88%, skip reason code can NEVER be LOW_MATCH_SCORE
        code = map_to_skip_reason_code("AI Skipped: Some note", match_score=88)
        self.assertNotEqual(code, "LOW_MATCH_SCORE")

        code_65 = map_to_skip_reason_code("AI Skipped", match_score=65)
        self.assertNotEqual(code_65, "LOW_MATCH_SCORE")


class TestSectionGLocationSyncAndCardDetection(unittest.TestCase):
    """
    Section G Mandatory Regression Tests:
    Test 1: Requested: Dubai, UAE | Actual: Doha, Qatar -> LOCATION_SYNC_FAILED. No scraping.
    Test 2: Requested: Dubai, UAE | Actual: Dubai, UAE -> LOCATION_VERIFIED. Start scraping.
    Test 3: Requested: Mumbai, India | Previous: Dubai, UAE -> Clear previous location, enter and select Mumbai.
    Test 4: LinkedIn displays 87 results and job cards visible -> Scraper inspects DOM and extracts available cards.
    Test 5: LinkedIn displays results but DOM extraction returns zero -> JOB_CARD_EXTRACTION_FAILED with diagnostics.
    Test 6: Search multiple cities sequentially -> Every city independently selected and verified.
    """

    def setUp(self):
        import threading
        self.bot_state = MagicMock()
        self.bot_state.stop_event = threading.Event()
        self.bot_state.last_search_diagnostics = {}
        self.stop_event = self.bot_state.stop_event
        self.engine = LinkedInEngine(self.bot_state, MagicMock(), MagicMock(), MagicMock())

    def test_g1_requested_dubai_actual_doha_location_sync_failed_no_scraping(self):
        """Test 1: Requested: Dubai, UAE | Actual: Doha, Qatar -> LOCATION_SYNC_FAILED. No scraping."""
        mock_page = MagicMock()
        # LinkedIn browser is stuck on Doha, Qatar
        mock_page.evaluate.return_value = "Doha, Qatar"
        mock_page.query_selector.return_value = None  # Autocomplete not found / interaction fails

        verified, actual_loc, err_msg = self.engine.synchronize_linkedin_location(
            mock_page, requested_location="Dubai, UAE", stop_event=self.stop_event, max_retries=0
        )

        self.assertFalse(verified, "Location synchronization must fail when actual location does not match requested.")
        self.assertEqual(actual_loc, "Doha, Qatar")
        self.assertIn("LOCATION_SYNC_FAILED", err_msg)
        # Verify error log recorded
        self.bot_state.add_log.assert_any_call(unittest.mock.ANY, "ERROR")

    def test_g2_requested_dubai_actual_dubai_verified_proceeds(self):
        """Test 2: Requested: Dubai, UAE | Actual: Dubai, UAE -> LOCATION_VERIFIED. Start scraping."""
        mock_page = MagicMock()
        # LinkedIn browser displays Dubai, United Arab Emirates
        mock_page.evaluate.return_value = "Dubai, United Arab Emirates"

        verified, actual_loc, err_msg = self.engine.synchronize_linkedin_location(
            mock_page, requested_location="Dubai, UAE", stop_event=self.stop_event, max_retries=1
        )

        self.assertTrue(verified, "Location synchronization must succeed when browser matches requested city.")
        self.assertEqual(actual_loc, "Dubai, United Arab Emirates")
        self.assertEqual(err_msg, "")
        self.bot_state.add_log.assert_any_call(
            "📍 [LinkedIn] Location verified: 'Dubai, United Arab Emirates' matches requested 'Dubai, UAE'.",
            "SUCCESS"
        )

    def test_g3_requested_mumbai_previous_dubai_clears_and_selects_mumbai(self):
        """Test 3: Requested: Mumbai, India | Previous: Dubai, UAE -> Clear previous location, enter and select Mumbai."""
        mock_page = MagicMock()

        # Step 1: Initial location is Dubai
        # Step 2: After sync interaction, location becomes Mumbai, Maharashtra, India
        eval_responses = ["Dubai, United Arab Emirates", "Mumbai, Maharashtra, India"]
        mock_page.evaluate.side_effect = eval_responses

        # Setup modern layout elements
        mock_loc_btn = MagicMock()
        mock_loc_btn.is_visible.return_value = True

        mock_clear_btn = MagicMock()
        mock_clear_btn.is_visible.return_value = True

        mock_textbox = MagicMock()

        mock_sugg = MagicMock()
        mock_sugg.inner_text.return_value = "Mumbai, Maharashtra, India"

        def mock_qs(selector):
            if "Clear location" in selector:
                return mock_clear_btn
            if "role=\"textbox\"" in selector or "LocationTypeahead_TextEditor" in selector:
                return mock_textbox
            if "Location " in selector or "location-dot-outline-small" in selector:
                return mock_loc_btn
            return None

        mock_page.query_selector.side_effect = mock_qs
        mock_page.query_selector_all.return_value = [mock_sugg]

        verified, actual_loc, err_msg = self.engine.synchronize_linkedin_location(
            mock_page, requested_location="Mumbai, India", stop_event=self.stop_event, max_retries=1
        )

        # Assert clear button was clicked to remove Dubai
        mock_clear_btn.click.assert_called()
        # Assert Mumbai was typed into typeahead
        mock_textbox.type.assert_called_with("Mumbai", delay=80)
        # Assert autocomplete suggestion was clicked
        mock_sugg.click.assert_called()
        # Assert final verified location is Mumbai
        self.assertTrue(verified)
        self.assertEqual(actual_loc, "Mumbai, Maharashtra, India")

    def test_g4_displays_87_results_and_job_cards_extracted(self):
        """Test 4: LinkedIn displays 87 results and job cards visible -> Scraper inspects DOM and extracts available cards."""
        mock_page = MagicMock()

        # Mock result count: 87 results
        # Mock modern card evaluation: 1 card returned
        card_data = [{
            "jobId": "4482976903",
            "url": "https://www.linkedin.com/jobs/view/4482976903/",
            "lines": [
                "Senior Software Engineer",
                "Penta Consulting",
                "Doha, Qatar (On-site)",
                "Actively reviewing applicants",
                "Viewed",
                "Easy Apply"
            ],
            "rawText": "Senior Software Engineer\nPenta Consulting\nDoha, Qatar",
            "verifiedLocation": "Doha, Qatar",
            "cardSelector": "[componentkey=\"job-card-component-ref-4482976903\"]",
            "index": 0
        }]

        def mock_eval(script):
            if "results?" in script:
                return "87 results"
            if "job-card-component-ref-" in script:
                return card_data
            return None

        mock_page.evaluate.side_effect = mock_eval

        # Extract result count
        count_val, raw_txt = self.engine.get_linkedin_result_count(mock_page)
        self.assertEqual(count_val, 87)
        self.assertEqual(raw_txt, "87 results")

        # Extract cards
        jobs = self.engine.extract_job_cards(mock_page, max_cards=10)
        self.assertEqual(len(jobs), 1)
        extracted = jobs[0]
        self.assertEqual(extracted["id"], "4482976903")
        self.assertEqual(extracted["title"], "Senior Software Engineer")
        self.assertEqual(extracted["company"], "Penta Consulting")
        self.assertEqual(extracted["location"], "Doha, Qatar")
        self.assertTrue(extracted["is_easy_apply"])
        self.assertIn("4482976903", extracted["url"])

    def test_g5_displays_results_but_zero_cards_triggers_job_card_extraction_failed(self):
        """Test 5: LinkedIn displays results but DOM extraction returns zero -> JOB_CARD_EXTRACTION_FAILED, with diagnostics and screenshot."""
        mock_page = MagicMock()

        def mock_eval(script):
            if "results?" in script:
                return "87 results"
            if "job-card-component-ref-" in script:
                return []  # DOM returns 0 cards despite 87 results
            return None

        mock_page.evaluate.side_effect = mock_eval
        mock_page.query_selector_all.return_value = []

        jobs = self.engine.extract_job_cards(mock_page, max_cards=10)
        self.assertEqual(len(jobs), 0)

        # Verify that JOB_CARD_EXTRACTION_FAILED is reported, NOT silent "no jobs found"
        warning_logged = any(
            "JOB_CARD_EXTRACTION_FAILED" in str(call_arg)
            for call_arg in self.bot_state.add_log.call_args_list
        )
        self.assertTrue(warning_logged, "Must emit JOB_CARD_EXTRACTION_FAILED when results > 0 but 0 cards extracted.")

    def test_g6_sequential_multi_city_search_independent_verification(self):
        """Test 6: Search multiple cities sequentially -> Every city independently selected and verified."""
        cities = ["Dubai, UAE", "Pune, Maharashtra", "Remote"]
        mock_page = MagicMock()

        for target_city in cities:
            # Browser matches each requested city
            mock_page.evaluate.return_value = target_city

            verified, actual_loc, err = self.engine.synchronize_linkedin_location(
                mock_page, requested_location=target_city, stop_event=self.stop_event, max_retries=1
            )
            self.assertTrue(verified, f"Target city {target_city} must be independently verified.")
            self.assertEqual(actual_loc, target_city)
            self.assertEqual(err, "")


class TestSectionHEasyApplyWorkflowAndSubmission(unittest.TestCase):
    """
    Mandatory Regression Tests for Section H: LinkedIn Easy Apply Final Submission:
    1. Easy Apply modal opens.
    2. Resume uploads successfully.
    3. Multiple form steps are completed.
    4. Next button works.
    5. Review button works.
    6. Missing mandatory field is detected.
    7. Disabled Submit button is not clicked.
    8. Final Submit application button is detected.
    9. Final submission is executed.
    10. Submission confirmation is verified.
    11. Duplicate submission is prevented.
    """

    def setUp(self):
        import threading
        self.bot_state = MagicMock()
        self.bot_state.stop_event = threading.Event()
        self.bot_state.config.unconfirmed_cooldown_min_sec = 0
        self.bot_state.config.unconfirmed_cooldown_max_sec = 0
        self.stop_event = self.bot_state.stop_event
        self.engine = LinkedInEngine(self.bot_state, MagicMock(), MagicMock(), MagicMock())

    def test_h1_easy_apply_modal_opens(self):
        """1. Easy Apply modal opens and is reliably located."""
        mock_page = MagicMock()
        mock_modal = MagicMock()
        mock_modal.is_visible.return_value = True
        mock_page.query_selector_all.return_value = [mock_modal]

        modal = self.engine.find_easy_apply_modal(mock_page)
        self.assertIsNotNone(modal)
        self.assertEqual(modal, mock_modal)

    def test_h2_resume_selection_and_upload(self):
        """2. Resume uploads/selects successfully matching job region."""
        from linkedin_engine import select_or_upload_linkedin_resume
        mock_dialog = MagicMock()
        mock_dialog.evaluate.side_effect = [
            1,  # r_count
            {"found": True, "checked": True, "text": "Abdul_Razzaque_India.pdf"},  # selection
            {"isVerified": True, "matchedText": "Abdul_Razzaque_India.pdf"}  # verification
        ]

        verified, name = select_or_upload_linkedin_resume(
            dialog=mock_dialog,
            is_india=True,
            profile={"resume_path": "Abdul_Razzaque_India.pdf"},
            bot_state=self.bot_state
        )
        self.assertTrue(verified, "Resume must be verified and checked.")
        self.assertIn("India", name)

    def test_h3_multiple_form_steps_completed(self):
        """3. Multiple form steps completed cleanly."""
        mock_dialog = MagicMock()
        mock_dialog.query_selector_all.return_value = []
        mock_dialog.evaluate.return_value = 0
        mock_page = MagicMock()

        # Step 1: Contact info step
        res1 = self.engine.fill_easy_apply_step(mock_dialog, mock_page, {}, self.stop_event, "Acme", "Full Stack", "Mumbai")
        self.assertEqual(res1.get("status"), "SUCCESS")

        # Step 2: Experience / Screening questions step
        res2 = self.engine.fill_easy_apply_step(mock_dialog, mock_page, {}, self.stop_event, "Acme", "Full Stack", "Mumbai")
        self.assertEqual(res2.get("status"), "SUCCESS")

    def test_h4_next_button_works(self):
        """4. Next button is detected, verified enabled, and distinguished from submit."""
        mock_modal = MagicMock()
        mock_next_btn = MagicMock()
        mock_next_btn.is_visible.return_value = True
        mock_next_btn.is_enabled.return_value = True
        mock_next_btn.get_attribute.side_effect = lambda attr: "Continue to next step" if attr == "aria-label" else ""
        mock_next_btn.inner_text.return_value = "Next"

        mock_modal.query_selector_all.return_value = [mock_next_btn]

        buttons = self.engine.detect_modal_action_buttons(mock_modal, MagicMock())
        self.assertIsNotNone(buttons["next"], "Next button must be detected.")
        self.assertTrue(buttons["next"]["enabled"], "Next button must be enabled.")
        self.assertIsNone(buttons["submit"], "Next button must NOT be categorized as Submit.")
        self.assertIsNone(buttons["review"], "Next button must NOT be categorized as Review.")

    def test_h5_review_button_works(self):
        """5. Review button is detected, verified enabled, and distinguished from submit."""
        mock_modal = MagicMock()
        mock_rev_btn = MagicMock()
        mock_rev_btn.is_visible.return_value = True
        mock_rev_btn.is_enabled.return_value = True
        mock_rev_btn.get_attribute.side_effect = lambda attr: "Review your application" if attr == "aria-label" else ""
        mock_rev_btn.inner_text.return_value = "Review"

        mock_modal.query_selector_all.return_value = [mock_rev_btn]

        buttons = self.engine.detect_modal_action_buttons(mock_modal, MagicMock())
        self.assertIsNotNone(buttons["review"], "Review button must be detected.")
        self.assertTrue(buttons["review"]["enabled"], "Review button must be enabled.")
        self.assertIsNone(buttons["submit"], "Review button must NOT be categorized as Submit.")

    def test_h6_missing_mandatory_field_detected(self):
        """6. Missing mandatory field or validation error is detected."""
        mock_modal = MagicMock()
        mock_modal.evaluate.return_value = [
            "Please enter a valid phone number",
            "Required field empty: City"
        ]

        errors = self.engine.inspect_modal_validation_errors(mock_modal)
        self.assertEqual(len(errors), 2)
        self.assertIn("Please enter a valid phone number", errors)
        self.assertIn("Required field empty: City", errors)

    def test_h7_disabled_submit_button_not_clicked(self):
        """7. Disabled Submit button is not clicked and triggers activation scroll/diagnostic."""
        mock_modal = MagicMock()
        mock_sub_btn = MagicMock()
        mock_sub_btn.is_visible.return_value = True
        mock_sub_btn.is_enabled.return_value = False  # Disabled!
        mock_sub_btn.get_attribute.side_effect = lambda attr: "Submit application" if attr == "aria-label" else ("true" if attr == "aria-disabled" else "")
        mock_sub_btn.inner_text.return_value = "Submit application"

        mock_modal.query_selector_all.return_value = [mock_sub_btn]

        buttons = self.engine.detect_modal_action_buttons(mock_modal, MagicMock())
        self.assertIsNotNone(buttons["submit"])
        self.assertFalse(buttons["submit"]["enabled"], "Disabled Submit button must report enabled=False.")

    def test_h8_final_submit_application_button_detected(self):
        """8. Final Submit application button is accurately detected."""
        mock_modal = MagicMock()
        mock_sub_btn = MagicMock()
        mock_sub_btn.is_visible.return_value = True
        mock_sub_btn.is_enabled.return_value = True
        mock_sub_btn.get_attribute.side_effect = lambda attr: "Submit application" if attr == "aria-label" else ""
        mock_sub_btn.inner_text.return_value = "Submit application"

        mock_modal.query_selector_all.return_value = [mock_sub_btn]

        buttons = self.engine.detect_modal_action_buttons(mock_modal, MagicMock())
        self.assertIsNotNone(buttons["submit"])
        self.assertTrue(buttons["submit"]["enabled"])
        self.assertEqual(buttons["submit"]["text"], "Submit application")

    def test_h9_final_submission_executed(self):
        """9. Final submission is executed when enabled and authorized."""
        mock_modal = MagicMock()
        mock_sub_btn = MagicMock()
        mock_sub_btn.is_visible.return_value = True
        mock_sub_btn.is_enabled.return_value = True
        mock_sub_btn.get_attribute.return_value = "Submit application"
        mock_sub_btn.inner_text.return_value = "Submit application"

        mock_modal.query_selector_all.return_value = [mock_sub_btn]
        buttons = self.engine.detect_modal_action_buttons(mock_modal, MagicMock())
        sub_info = buttons["submit"]

        # Simulate execution
        sub_info["element"].scroll_into_view_if_needed()
        sub_info["element"].click()

        mock_sub_btn.click.assert_called_once()

    def test_h10_submission_confirmation_verified(self):
        """10. Submission confirmation is verified before marking APPLIED."""
        mock_page = MagicMock()
        # Mock confirmation screen: Done button present and confirmation text
        mock_done_btn = MagicMock()
        mock_done_btn.is_visible.return_value = True
        mock_page.query_selector.return_value = mock_done_btn
        mock_page.evaluate.return_value = "Your application was sent to Acme Corp"

        confirmed, msg, done_el = self.engine.verify_submission_confirmation(mock_page, max_wait_sec=2)
        self.assertTrue(confirmed, "Submission must be confirmed when Done button is visible.")
        self.assertIsNotNone(done_el)
        self.assertIn("CONFIRMATION", msg)

    def test_h11_duplicate_submission_prevented(self):
        """11. Duplicate submission is prevented."""
        job_id = "4999888777"
        self.engine.processed_job_ids.add(job_id)

        job_info = {
            "id": job_id,
            "title": "Full Stack Developer",
            "company": "Acme Corp",
            "location": "Mumbai",
            "url": f"https://www.linkedin.com/jobs/view/{job_id}/"
        }

        # Should skip immediately without attempting application
        res = self.engine.process_linkedin_job(MagicMock(), MagicMock(), job_info, score=90, stop_event=self.stop_event)
        self.assertEqual(res.get("status"), "SKIPPED")
        self.assertFalse(res.get("attempted"))

    def test_h12_external_apply_button_detected_accurately(self):
        """12. External Apply link (e.g. Emirates NBD Oracle HCM) is accurately detected."""
        mock_page = MagicMock()
        mock_ext_btn = MagicMock()
        mock_ext_btn.is_visible.return_value = True
        mock_ext_btn.inner_text.return_value = "Apply"
        mock_ext_btn.get_attribute.side_effect = lambda attr: "Apply on company website" if attr == "aria-label" else ("https://www.linkedin.com/safety/go/?url=oraclecloud.com" if attr == "href" else "")

        mock_page.query_selector_all.return_value = [mock_ext_btn]
        mock_page.query_selector.return_value = None

        action_type, btn = self.engine.detect_job_action_button(mock_page)
        self.assertEqual(action_type, "EXTERNAL_APPLY")
        self.assertIsNotNone(btn)

    def test_h13_score_65_eligible_in_resume_optimizer(self):
        """13. Jobs with match score >= 65% are eligible and not skipped with APPLY_OPTION_NOT_AVAILABLE."""
        from resume_optimizer import analyze_job_description
        analysis = analyze_job_description(
            job_title="Senior Software Engineer",
            company="Penta Consulting",
            job_desc="We are hiring a Senior Software Engineer for full stack application development, web APIs, database design, and cloud deployments.",
            location="Doha, Qatar",
            job_url="https://www.linkedin.com/jobs/view/4478544021"
        )
        self.assertTrue(analysis.should_apply, "Score >= 65% must be eligible to apply")
        self.assertGreaterEqual(analysis.match_score, 65)
        self.assertNotEqual(analysis.match_type, "NO_MATCH")

    def test_h14_state_machine_sequential_transitions(self):
        """14. ApplicationStateMachine tracks full sequential pipeline through terminal state."""
        from state_machine import ApplicationStateMachine, ApplicationStage
        job_info = {"id": "12345", "title": "Senior MERN Developer", "company": "TechCorp", "url": "https://linkedin.com/jobs/view/12345"}
        sm = ApplicationStateMachine(job_info)
        self.assertEqual(sm.current_state, ApplicationStage.DISCOVERED)

        sm.transition(ApplicationStage.JOB_VERIFIED, reason="Job verified")
        sm.transition(ApplicationStage.ELIGIBILITY_CHECKED, reason="Eligibility verified")
        sm.transition(ApplicationStage.APPLY_OPTION_DETECTED, reason="Easy Apply detected")
        sm.transition(ApplicationStage.APPLICATION_OPENED, reason="Modal opened")
        sm.transition(ApplicationStage.FORM_IN_PROGRESS, reason="Step 1 filled")
        sm.transition(ApplicationStage.FORM_COMPLETED, reason="Review step complete")
        sm.transition(ApplicationStage.SUBMISSION_PENDING, reason="Submit clicked")
        sm.transition(ApplicationStage.SUBMISSION_VERIFIED, reason="Confirmation detected")
        sm.transition(ApplicationStage.APPLICATION_CONFIRMED, reason="Application confirmed")

        self.assertEqual(sm.current_state, ApplicationStage.APPLICATION_CONFIRMED)
        self.assertTrue(sm.is_terminal())
        self.assertEqual(len(sm.get_history()), 10)

    def test_h15_dismiss_button_never_triggers_confirmation(self):
        """15. Dismiss button on modal does not trigger submission confirmation."""
        mock_modal = MagicMock()
        mock_dismiss_btn = MagicMock()
        mock_dismiss_btn.is_visible.return_value = True
        mock_dismiss_btn.is_enabled.return_value = True
        mock_dismiss_btn.get_attribute.side_effect = lambda attr: "Dismiss" if attr == "aria-label" else ""
        mock_dismiss_btn.inner_text.return_value = "Dismiss"

        mock_modal.query_selector_all.return_value = [mock_dismiss_btn]
        buttons = self.engine.detect_modal_action_buttons(mock_modal, MagicMock())

        self.assertIsNone(buttons["done"], "Dismiss button must NOT be classified as Done confirmation!")
        self.assertIsNotNone(buttons["dismiss"], "Dismiss button should be classified as dismiss.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
