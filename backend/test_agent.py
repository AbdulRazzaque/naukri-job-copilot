import os
import sys
import unittest
import threading
import time
from playwright.sync_api import sync_playwright

# Ensure backend directory is in sys.path
sys.path.insert(0, os.path.dirname(__file__))

from bot_engine import (
    bot_state,
    ApplicationStatus,
    BotConfig,
    find_submit_button,
    detect_naukri_action_button,
    cooldown_timer,
    human_sleep,
    check_already_applied_db,
    process_job_application,
    handle_naukri_screening_drawer,
    fill_company_form,
    stop_agent
)
from database import init_db, record_application, get_connection, get_dashboard_stats
from form_engine import (
    detect_and_collect_form_questions,
    fill_form_control,
    validate_entire_form,
    process_and_fill_complete_form,
    upload_resume_file,
    FormFieldType
)
from question_answering import (
    QuestionAnsweringEngine,
    QuestionCategory,
    qa_engine,
    match_best_option,
    resolve_answer_from_profile
)

from agent_config import agent_config_manager, AgentConfigManager
from ai_service import evaluate_application_question, is_sensitive_or_payment_question, call_gemini, query_ai
from chat_panel_handler import naukri_chat_panel_handler, ChatPanelState, NaukriChatPanelHandler
from reasoning_engine import reasoning_engine, AutonomousReasoningEngine, ALLOWED_TOOLS, AgentDecision, Observation
from button_service import button_service, ButtonCategory, is_naukri_application_confirmed
from database import lookup_experience, get_reasoning_metrics, record_experience, update_reasoning_metric

class TestAgentAutomation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(channel="chrome", headless=True)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.browser.close()
        except Exception:
            pass
        try:
            cls.playwright.stop()
        except Exception:
            pass

    def setUp(self):
        bot_state.stop_event.clear()
        bot_state.is_running = True
        bot_state.status = "IDLE"
        self.context = self.browser.new_context()

    def tearDown(self):
        try:
            self.context.close()
        except Exception:
            pass
        bot_state.stop_event.clear()
        bot_state.is_running = False

    # 1. Valid application button detection
    def test_01_valid_application_button_detection(self):
        page = self.context.new_page()
        # Test standard buttons
        page.set_content("""
            <div>
                <button id="save-apply-btn">Save and Apply</button>
                <button id="submit-btn">Submit Application</button>
                <input type="submit" id="input-sub" value="Send Application" />
            </div>
        """)
        btn = find_submit_button(page)
        self.assertIsNotNone(btn, "Should detect a valid submit button")

        # Test action button detection on Naukri page
        page.set_content("""
            <div class="job-actions">
                <button id="apply-button" class="apply-button">Apply</button>
            </div>
        """)
        action_type, el = detect_naukri_action_button(page)
        self.assertEqual(action_type, "DIRECT_APPLY")
        self.assertIsNotNone(el)

        page.set_content("""
            <div class="job-actions">
                <button class="company-site-button">Apply on company site</button>
            </div>
        """)
        action_type, el = detect_naukri_action_button(page)
        self.assertEqual(action_type, "COMPANY_SITE")
        self.assertIsNotNone(el)
        page.close()

    # 2. Invalid CSS selector regression
    def test_02_invalid_css_selector_regression(self):
        page = self.context.new_page()
        # Page with screening elements
        page.set_content("""
            <div class="chatbot_drawer">
                <div class="chip">30 Days</div>
                <input class="chat-input" placeholder="Type your response..." />
                <button>Save and Apply</button>
            </div>
        """)
        # Native document.querySelector with ':has-text()' throws SyntaxError in real browser DOM.
        # Verify that our fixed evaluate block executes cleanly WITHOUT any SyntaxError
        has_elements = False
        try:
            has_elements = page.evaluate("""() => {
                const hasChips = Array.from(document.querySelectorAll('.chip, .botOption, button.option-btn, div.quick-reply, span.chip, .chat-chip, .option, button[class*="chip"], div[class*="chip"]')).some(el => el.offsetParent !== null);
                const hasChatInp = Array.from(document.querySelectorAll('input[placeholder*="Type" i], textarea[placeholder*="Type" i], input.chat-input, .user-input input, div[class*="chatInput"] input')).some(el => el.offsetParent !== null && !el.disabled);
                const submitTerms = ['save and apply', 'save & apply', 'submit application', 'send application', 'submit', 'send', 'continue', 'apply now'];
                const hasSubmit = Array.from(document.querySelectorAll('button, input[type="submit"], [role="button"], a.btn, a.button')).some(b => {
                    if (b.offsetParent === null || b.disabled) return false;
                    const txt = (b.innerText || b.value || b.getAttribute('aria-label') || '').toLowerCase().trim();
                    return submitTerms.some(term => txt.includes(term));
                });
                const hasRadios = Array.from(document.querySelectorAll('input[type="radio"]:not([disabled])')).some(el => el.offsetParent !== null);
                return hasChips || hasChatInp || hasSubmit || hasRadios;
            }""")
        except Exception as e:
            self.fail(f"evaluate() crashed with selector error: {e}")

        self.assertTrue(has_elements, "Screening elements should be detected successfully without selector syntax error")
        page.close()

    # 3. Multiple matching buttons (ensure unrelated buttons like filters/search are ignored)
    def test_03_multiple_matching_buttons(self):
        page = self.context.new_page()
        page.set_content("""
            <div>
                <button class="filter-btn">Apply Filter</button>
                <button class="search-btn">Search Jobs</button>
                <button class="cancel-btn">Cancel</button>
                <button id="real-submit" class="send-btn">Submit Application</button>
            </div>
        """)
        btn = find_submit_button(page)
        self.assertIsNotNone(btn)
        txt = btn.inner_text().strip()
        self.assertEqual(txt, "Submit Application", "Should match real submit button, not Apply Filter")
        page.close()

    # 4. Disabled or hidden buttons
    def test_04_disabled_or_hidden_buttons(self):
        page = self.context.new_page()
        page.set_content("""
            <div>
                <button disabled>Submit</button>
                <button style="display:none;">Save and Apply</button>
                <button style="visibility:hidden;">Send Application</button>
            </div>
        """)
        btn = find_submit_button(page)
        self.assertIsNone(btn, "Disabled or hidden buttons should not be selected")

        # Now add one visible, enabled button
        page.set_content("""
            <div>
                <button disabled>Submit</button>
                <button style="display:none;">Save and Apply</button>
                <button id="enabled-btn">Submit</button>
            </div>
        """)
        btn2 = find_submit_button(page)
        self.assertIsNotNone(btn2, "Visible and enabled button should be selected")
        page.close()

    # 5. Missing application buttons
    def test_05_missing_application_buttons(self):
        page = self.context.new_page()
        page.set_content("""
            <div class="job-expired">
                <h2>This job vacancy has expired and is no longer accepting applications.</h2>
            </div>
        """)
        action_type, el = detect_naukri_action_button(page)
        self.assertIsNone(action_type, "No action button should be detected on expired job")
        self.assertIsNone(el)
        page.close()

    # 6. Application forms that open in a new tab
    def test_06_application_forms_open_in_new_tab(self):
        page = self.context.new_page()
        # Simulated job details page where clicking Apply opens a new window/tab
        page.set_content("""
            <a id="apply-button" class="apply-button" href="https://example.com/careers/apply" target="_blank">
                Apply on company site
            </a>
        """)
        action_type, el = detect_naukri_action_button(page)
        self.assertEqual(action_type, "COMPANY_SITE")

        pages_before = len(self.context.pages)
        with self.context.expect_page() as pinfo:
            el.click()
        new_tab = pinfo.value
        self.assertEqual(len(self.context.pages), pages_before + 1)
        self.assertTrue(new_tab.url.startswith("https://example.com"))
        new_tab.close()
        page.close()

    # 7. Failed form submissions (validation error detection)
    def test_07_failed_form_submissions(self):
        page = self.context.new_page()
        page.set_content("""
            <form>
                <input type="text" required name="pan" value="" />
                <div class="error alert-danger">PAN Number is required to apply</div>
            </form>
        """)
        has_errors = page.evaluate("""() => {
            return Array.from(document.querySelectorAll('.error, .alert-danger, .invalid-feedback'))
                .some(e => e.offsetParent !== null && (e.innerText || '').trim().length > 0);
        }""")
        self.assertTrue(has_errors, "Should detect validation errors on failed form submission")
        page.close()

    # 8. Confirmed and unconfirmed applications
    def test_08_confirmed_and_unconfirmed_applications(self):
        page = self.context.new_page()
        # Confirmed
        page.set_content("""
            <div class="apply-message">
                <span class="success-message">Your application has been sent to the recruiter!</span>
            </div>
        """)
        is_confirmed = page.evaluate("""() => {
            const text = (document.body ? document.body.innerText : '').toLowerCase();
            return text.includes('application has been sent') || text.includes('applied successfully');
        }""")
        self.assertTrue(is_confirmed, "Confirmed application should be verified")

        # Unconfirmed
        page.set_content("""
            <div>
                <h3>Review Job Requirements</h3>
            </div>
        """)
        is_unconfirmed = page.evaluate("""() => {
            const text = (document.body ? document.body.innerText : '').toLowerCase();
            return text.includes('application has been sent') || text.includes('applied successfully');
        }""")
        self.assertFalse(is_unconfirmed, "Unconfirmed application should not report success")
        page.close()

    # 9. Cooldown behavior (configurable, distinguishes confirmed vs attempt, cancellation)
    def test_09_cooldown_behavior(self):
        # Test stop cancellation breaks immediately
        stop_ev = threading.Event()
        stop_ev.set()
        start = time.time()
        cooldown_timer(min_sec=10, max_sec=20, stop_event=stop_ev, reason="Test break")
        elapsed = time.time() - start
        self.assertLess(elapsed, 2.0, "Cooldown should exit immediately when stop_event is set")
        self.assertEqual(bot_state.countdown_remaining, 0)

        # Test configurable config values exist
        config = BotConfig()
        self.assertGreater(config.cooldown_min_sec, 0)
        self.assertGreater(config.unconfirmed_cooldown_min_sec, 0)
        self.assertLess(config.unconfirmed_cooldown_min_sec, config.cooldown_min_sec)

    # 10. User cancellation during job processing
    def test_10_user_cancellation_during_job_processing(self):
        stop_ev = threading.Event()
        stop_ev.set()
        res = process_job_application(
            context=self.context,
            search_page=None,
            title="Senior Engineer",
            company="TestCorp",
            loc_text="Mumbai",
            exp_text="5 Yrs",
            job_url="https://example.com/job",
            score=85,
            stop_event=stop_ev
        )
        self.assertEqual(res["status"], ApplicationStatus.APPLICATION_SKIPPED)
        self.assertEqual(res["failure_reason"], "STOP_REQUESTED")

    # 11. Browser navigation and timeout errors
    def test_11_browser_navigation_and_timeout_errors(self):
        stop_ev = threading.Event()
        # Invalid / unreachable host
        res = process_job_application(
            context=self.context,
            search_page=None,
            title="Software Developer",
            company="UnreachableCorp",
            loc_text="Mumbai",
            exp_text="5 Yrs",
            job_url="http://non-existent-domain-123456789.xyz/job",
            score=85,
            stop_event=stop_ev
        )
        self.assertEqual(res["status"], ApplicationStatus.APPLICATION_FAILED)
        self.assertTrue("NAV_FAILED" in res["failure_reason"] or "ERR_" in res["failure_reason"])

    # 12. Prevention of duplicate applications
    def test_12_prevention_of_duplicate_applications(self):
        unique_company = f"DupTestCorp_{int(time.time()*1000)}"
        unique_title = "Full Stack Engineer"

        # Initially should not be in DB
        self.assertFalse(check_already_applied_db(unique_title, unique_company))

        # Record a confirmed application
        record_application(
            job_title=unique_title,
            company_name=unique_company,
            location="Mumbai",
            job_url="https://example.com/dup-job",
            status=ApplicationStatus.APPLICATION_CONFIRMED,
            notes="Test entry"
        )

        # Now should be detected as already applied
        self.assertTrue(check_already_applied_db(unique_title, unique_company))

        # Verify that SKIPPED or FAILED jobs do NOT block re-application
        skipped_company = f"SkippedTestCorp_{int(time.time()*1000)}"
        record_application(
            job_title=unique_title,
            company_name=skipped_company,
            location="Mumbai",
            job_url="https://example.com/skipped-job",
            status=ApplicationStatus.APPLICATION_SKIPPED,
            notes="AI low match"
        )
        self.assertFalse(check_already_applied_db(unique_title, skipped_company), "Skipped job should not be considered already applied")

        # Clean up test rows
        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM job_applications WHERE company_name IN (%s, %s)", (unique_company, skipped_company))
            conn.close()
        except Exception:
            pass

    # 13. Persistent configuration reloads and updates across restarts
    def test_13_persistent_config_reloads_and_updates(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
            tmp_cfg_path = tf.name

        try:
            # 1. Initialize manager
            mgr1 = AgentConfigManager(config_path=tmp_cfg_path)
            self.assertEqual(mgr1.get_config()["mode"], "AUTONOMOUS")
            self.assertTrue(mgr1.is_authorized("auto_search"))

            # 2. Update a permission
            mgr1.update_config({"permissions": {"auto_upload_resume": True, "custom_action_test": True}})
            self.assertTrue(mgr1.is_authorized("custom_action_test"))

            # 3. Simulate application restart with a fresh manager instance reading the file
            mgr2 = AgentConfigManager(config_path=tmp_cfg_path)
            self.assertTrue(mgr2.is_authorized("custom_action_test"), "Configuration must persist across application restarts")
            self.assertTrue(mgr2.is_authorized("auto_submit_direct"))
        finally:
            if os.path.exists(tmp_cfg_path):
                os.remove(tmp_cfg_path)

    # 14. Authorized actions execute without repeated permission prompts
    def test_14_authorized_actions_execute_without_repeated_prompts(self):
        # In Autonomous mode, all configured routine actions are authorized directly
        routine_actions = [
            "auto_search",
            "auto_inspect_jobs",
            "auto_fill_forms",
            "auto_upload_resume",
            "auto_answer_screening",
            "auto_submit_direct",
            "auto_submit_company_portal"
        ]
        for action in routine_actions:
            is_auth = agent_config_manager.is_authorized(action)
            self.assertTrue(is_auth, f"Action '{action}' should be authorized automatically without prompt")

    # 15. Unauthorized actions remain blocked by safety boundaries
    def test_15_unauthorized_actions_remain_blocked(self):
        # 1. Payments / Paid transactions must be blocked
        is_safe, reason = agent_config_manager.is_action_safe("payment")
        self.assertFalse(is_safe, "Paid transactions must be blocked")
        self.assertIn("PAYMENT_BLOCKED", reason)

        # 2. Sensitive identity numbers (SSN, credit card, bank details)
        is_safe, reason = agent_config_manager.is_action_safe("sensitive_info")
        self.assertFalse(is_safe, "Sensitive credentials must be blocked")
        self.assertIn("SENSITIVE_INFO_BLOCKED", reason)

        # 3. Security / CAPTCHA bypass without authorization
        is_safe, reason = agent_config_manager.is_action_safe("captcha_bypass")
        self.assertFalse(is_safe, "Autonomous CAPTCHA bypass must be blocked")
        self.assertIn("CAPTCHA_BYPASS_BLOCKED", reason)

        # 4. Fabricating unknown personal facts
        is_safe, reason = agent_config_manager.is_action_safe("unverified_fact")
        self.assertFalse(is_safe, "Fabricating personal facts must be blocked")
        self.assertIn("FABRICATION_BLOCKED", reason)

    # 16. Unknown mandatory questions are handled as NEEDS_USER_INPUT (never fabricated)
    def test_16_mandatory_unknown_questions_handled_as_needs_user_input(self):
        # Unverified family question
        ans, needs_user, reason = evaluate_application_question("What is your father's middle name?")
        self.assertTrue(needs_user, "Should flag unknown personal fact as NEEDS_USER_INPUT")
        self.assertEqual(ans, "", "Must never fabricate family personal facts")
        self.assertIn("NEEDS_USER_INPUT", reason)

        # Unverified educational marks
        ans, needs_user, reason = evaluate_application_question("What was your exact 10th standard board percentage?")
        self.assertTrue(needs_user, "Should flag unverified percentage as NEEDS_USER_INPUT")
        self.assertEqual(ans, "", "Must never fabricate academic percentages")

        # Payment / fee request
        ans, needs_user, reason = evaluate_application_question("Enter your credit card number for the 500 INR application fee:")
        self.assertTrue(needs_user, "Should block payment questions")
        self.assertEqual(reason, "PAYMENT_REQUEST_BLOCKED")

        # Sensitive identity request
        ans, needs_user, reason = evaluate_application_question("Please enter your 12-digit Aadhaar / Social Security Number:")
        self.assertTrue(needs_user, "Should block national ID questions")
        self.assertEqual(reason, "SENSITIVE_FIELD_BLOCKED")

    # 17. Application forms are completed automatically when sufficient verified info exists
    def test_17_application_forms_completed_automatically(self):
        page = self.context.new_page()
        page.set_content("""
            <form id="job-app-form">
                <div>
                    <label for="name">Full Name</label>
                    <input id="name" name="name" type="text" />
                </div>
                <div>
                    <label for="email">Email Address</label>
                    <input id="email" name="email" type="email" />
                </div>
                <div>
                    <label for="phone">Phone Number</label>
                    <input id="phone" name="phone" type="tel" />
                </div>
                <div>
                    <label for="exp">Total Experience</label>
                    <select id="exp" name="experience">
                        <option value="">Select</option>
                        <option value="1-3">1-3 years</option>
                        <option value="5+">5+ years</option>
                    </select>
                </div>
                <div>
                    <label for="notice">Notice Period</label>
                    <select id="notice" name="notice">
                        <option value="">Select</option>
                        <option value="30">30 days</option>
                        <option value="90">90 days</option>
                    </select>
                </div>
                <div>
                    <label for="highest_qual">Highest Qualification</label>
                    <input id="highest_qual" name="highest_qualification" type="text" />
                </div>
                <div>
                    <label><input type="checkbox" name="terms" required /> I accept terms and verify info</label>
                </div>
            </form>
        """)

        res = fill_company_form(page, stop_event=bot_state.stop_event, target_role="Senior Full Stack Developer")
        self.assertTrue(res.get("success"), f"Form autofill should succeed: {res}")
        self.assertFalse(res.get("needs_user_input"), "Form with complete verified profile should not require user input")

        # Verify fields were filled with candidate profile data
        name_val = page.locator("#name").input_value()
        email_val = page.locator("#email").input_value()
        phone_val = page.locator("#phone").input_value()
        exp_val = page.locator("#exp").input_value()
        qual_val = page.locator("#highest_qual").input_value()
        terms_checked = page.locator("input[name='terms']").is_checked()

        self.assertIn("Abdul", name_val)
        self.assertEqual(email_val, "mhaslaiabdur@gmail.com")
        self.assertIn("7972694663", phone_val)
        self.assertEqual(exp_val, "5+")
        self.assertIn("Computer Science", qual_val)
        self.assertTrue(terms_checked, "Mandatory agreement checkbox should be checked")
        page.close()

    # 18. Payment request on application form is detected and blocked
    def test_18_payment_request_on_application_form_blocked(self):
        page = self.context.new_page()
        page.set_content("""
            <form id="payment-app-form">
                <h3>Application Processing Fee: 50 USD</h3>
                <label>Card Number</label>
                <input type="text" name="card_number" autocomplete="cc-number" />
                <label>CVV</label>
                <input type="password" name="cvv" />
                <button type="submit">Pay Now and Apply</button>
            </form>
        """)
        res = fill_company_form(page, stop_event=bot_state.stop_event)
        self.assertTrue(res.get("is_payment"), "Payment form should be detected")
        self.assertEqual(res.get("reason"), "PAYMENT_BLOCKED", "Payment must be blocked by safety boundary")
        page.close()

    # 19. Stop button immediately stops and is never ignored
    def test_19_stop_button_immediately_aborts(self):
        bot_state.is_running = True
        bot_state.status = "APPLYING"
        stop_success, stop_msg = stop_agent()
        self.assertTrue(stop_success)
        self.assertTrue(bot_state.stop_event.is_set(), "stop_event must be set immediately")
        self.assertFalse(bot_state.is_running, "is_running must be False immediately")
        self.assertEqual(bot_state.status, "STOPPED")

        # Verify process_job_application immediately aborts when stop_event is set
        res = process_job_application(
            context=self.context,
            search_page=None,
            title="Senior Developer",
            company="StopTestCorp",
            loc_text="Mumbai",
            exp_text="5 Yrs",
            job_url="https://example.com/job-stop",
            score=90,
            stop_event=bot_state.stop_event
        )
        self.assertEqual(res["status"], ApplicationStatus.APPLICATION_SKIPPED)
        self.assertEqual(res["failure_reason"], "STOP_REQUESTED")


    # --- REGRESSION SUITE: 12 REQUIRED SCENARIOS ---

    # Scenario 1: Forms containing only text inputs
    def test_20_scenario_01_text_only_forms(self):
        page = self.context.new_page()
        page.set_content("""
            <form id="app-form">
                <div class="field">
                    <label for="fname">Full Name</label>
                    <input type="text" id="fname" name="fullName" />
                </div>
                <div class="field">
                    <label for="email">Email Address</label>
                    <input type="text" id="email" name="email" />
                </div>
                <div class="field">
                    <label for="exp">Total Experience</label>
                    <input type="text" id="exp" name="experience" />
                </div>
                <div class="field">
                    <label for="cctc">Current CTC</label>
                    <input type="text" id="cctc" name="currentCtc" />
                </div>
                <div class="field">
                    <label for="ectc">Expected CTC</label>
                    <input type="text" id="ectc" name="expectedCtc" />
                </div>
            </form>
        """)
        res = process_and_fill_complete_form(
            page=page,
            qa_engine_instance=qa_engine,
            stop_event=bot_state.stop_event,
            company_name="TextOnlyCorp",
            job_title="Senior Full Stack Developer"
        )
        self.assertEqual(res["status"], "FORM_VALIDATED")
        self.assertEqual(page.locator("#fname").input_value(), "Abdul Razzaque Shaikh")
        self.assertEqual(page.locator("#email").input_value(), "mhaslaiabdur@gmail.com")
        self.assertIn("5", page.locator("#exp").input_value())
        self.assertIn("12", page.locator("#cctc").input_value())
        self.assertIn("15", page.locator("#ectc").input_value())
        page.close()

    # Scenario 2: Forms containing dropdowns and radio buttons
    def test_21_scenario_02_dropdowns_and_radios(self):
        page = self.context.new_page()
        page.set_content("""
            <form id="dropdown-radio-form">
                <div class="field">
                    <label for="exp-sel">Total Experience</label>
                    <select id="exp-sel" name="experienceYears">
                        <option value="">Select Experience</option>
                        <option value="1">1-2 years</option>
                        <option value="3">3-4 years</option>
                        <option value="5">5+ years</option>
                        <option value="10">10+ years</option>
                    </select>
                </div>
                <div class="field">
                    <label for="notice-sel">Notice Period</label>
                    <select id="notice-sel" name="noticePeriod">
                        <option value="">Select Notice</option>
                        <option value="immediate">Immediate / 0-15 Days</option>
                        <option value="30">30 Days</option>
                        <option value="60">60 Days</option>
                    </select>
                </div>
                <div class="field" id="relocate-group">
                    <label>Are you open to relocate to Mumbai or work Remote?</label>
                    <label><input type="radio" name="relocate" value="no" /> No</label>
                    <label><input type="radio" name="relocate" value="yes" /> Yes</label>
                </div>
            </form>
        """)
        res = process_and_fill_complete_form(
            page=page,
            qa_engine_instance=qa_engine,
            stop_event=bot_state.stop_event,
            company_name="SelectRadioCorp",
            job_title="Full Stack Engineer"
        )
        self.assertEqual(res["status"], "FORM_VALIDATED")
        # Verify candidate's 5+ years is chosen, NOT 1-2 years
        self.assertEqual(page.locator("#exp-sel").input_value(), "5")
        # Verify Immediate joiner is chosen
        self.assertEqual(page.locator("#notice-sel").input_value(), "immediate")
        # Verify Yes radio is checked
        self.assertTrue(page.locator("input[type='radio'][value='yes']").is_checked())
        self.assertFalse(page.locator("input[type='radio'][value='no']").is_checked())
        page.close()

    # Scenario 3: Forms containing mandatory questions
    def test_22_scenario_03_mandatory_questions(self):
        page = self.context.new_page()
        page.set_content("""
            <form id="mandatory-form">
                <div class="field">
                    <label for="m-mern">MERN Stack Experience (Years) *</label>
                    <input type="text" id="m-mern" name="mernExp" required />
                </div>
                <div class="field">
                    <label for="m-notice">Notice Period *</label>
                    <input type="text" id="m-notice" name="notice" required />
                </div>
                <div class="field">
                    <label for="m-ctc">Expected CTC *</label>
                    <input type="text" id="m-ctc" name="expectedSalary" required />
                </div>
            </form>
        """)
        res = process_and_fill_complete_form(
            page=page,
            qa_engine_instance=qa_engine,
            stop_event=bot_state.stop_event,
            company_name="MandatoryCorp",
            job_title="MERN Developer"
        )
        self.assertEqual(res["status"], "FORM_VALIDATED")
        # Ensure mandatory inputs were filled and validated
        val = validate_entire_form(page)
        self.assertTrue(val["isValid"])
        self.assertEqual(len(val["emptyMandatory"]), 0)
        page.close()

    # Scenario 4: Forms containing unfamiliar questions (zero fabrication, NEEDS_USER_INPUT, tab kept open)
    def test_23_scenario_04_unfamiliar_questions_keep_tab_open(self):
        page = self.context.new_page()
        page.set_content("""
            <form id="unfamiliar-form">
                <div class="field">
                    <label for="valid-skill">Primary Skill *</label>
                    <input type="text" id="valid-skill" name="skill" required />
                </div>
                <div class="field">
                    <label for="unknown-q">Father\'s Maiden Occupation *</label>
                    <input type="text" id="unknown-q" name="fatherOccupation" required />
                </div>
            </form>
        """)
        res = process_and_fill_complete_form(
            page=page,
            qa_engine_instance=qa_engine,
            stop_event=bot_state.stop_event,
            company_name="UnfamiliarCorp",
            job_title="Full Stack Engineer"
        )
        # Agent must NOT fabricate answer; must flag NEEDS_USER_INPUT
        self.assertEqual(res["status"], "NEEDS_USER_INPUT")
        self.assertIn("Father", res["unanswered_question"])
        # Page must not be closed!
        self.assertFalse(page.is_closed(), "Tab must remain open in Chrome for candidate input")
        page.close()

    # Scenario 5: Forms that dynamically reveal additional questions
    def test_24_scenario_05_dynamic_follow_up_questions(self):
        page = self.context.new_page()
        page.set_content("""
            <form id="dynamic-form">
                <div class="field">
                    <label for="mern-check">Do you have experience in MERN Stack?</label>
                    <select id="mern-check" name="hasMern" onchange="if(this.value==='yes'){document.getElementById('hidden-group').style.display='block';}">
                        <option value="">Select</option>
                        <option value="yes">Yes</option>
                        <option value="no">No</option>
                    </select>
                </div>
                <div id="hidden-group" style="display:none;" class="field">
                    <label for="mern-years">Years of Experience in React and Node.js *</label>
                    <input type="text" id="mern-years" name="mernYears" required />
                </div>
            </form>
        """)
        res = process_and_fill_complete_form(
            page=page,
            qa_engine_instance=qa_engine,
            stop_event=bot_state.stop_event,
            company_name="DynamicCorp",
            job_title="Senior MERN Developer",
            max_dynamic_passes=3
        )
        self.assertEqual(res["status"], "FORM_VALIDATED")
        # Verify hidden group was revealed and filled in second pass
        self.assertEqual(page.locator("#mern-check").input_value(), "yes")
        mern_val = page.locator("#mern-years").input_value()
        self.assertIn("5", mern_val)
        page.close()

    # Scenario 6: Forms with autocomplete fields
    def test_25_scenario_06_autocomplete_fields(self):
        page = self.context.new_page()
        page.set_content("""
            <form id="auto-form">
                <div class="field">
                    <label for="city-input">Current City</label>
                    <input list="city-list" id="city-input" name="city" class="autocomplete" />
                    <datalist id="city-list">
                        <option value="Mumbai">
                        <option value="Bengaluru">
                        <option value="Delhi">
                        <option value="Pune">
                    </datalist>
                </div>
            </form>
        """)
        res = process_and_fill_complete_form(
            page=page,
            qa_engine_instance=qa_engine,
            stop_event=bot_state.stop_event,
            company_name="AutoCorp",
            job_title="Developer"
        )
        self.assertEqual(res["status"], "FORM_VALIDATED")
        self.assertEqual(page.locator("#city-input").input_value(), "Mumbai")
        page.close()

    # Scenario 7: Forms with invalid or unavailable candidate information
    def test_26_scenario_07_invalid_or_unavailable_candidate_info(self):
        # Querying unavailable / unrecorded private data
        res1 = qa_engine.process_question("What is your high school percentage marks?")
        self.assertTrue(res1["needs_user_input"])
        self.assertEqual(res1["answer"], "")
        self.assertIn(res1["source"], ["UNKNOWN", "LLM_GROUNDED"])

        res2 = qa_engine.process_question("Enter your security clearance PIN:")
        self.assertTrue(res2["needs_user_input"])
        self.assertTrue(res2.get("is_blocked", False) or res2["source"] in ["SAFETY_BOUNDARY", "UNKNOWN"])

    # Scenario 8: Forms that produce validation errors
    def test_27_scenario_08_form_validation_errors(self):
        page = self.context.new_page()
        page.set_content("""
            <form id="error-form">
                <div class="field">
                    <label for="req-field">Mandatory Field *</label>
                    <input type="text" id="req-field" required />
                    <span class="error invalid-feedback">This field is mandatory and required</span>
                </div>
            </form>
        """)
        val = validate_entire_form(page)
        self.assertFalse(val["isValid"])
        self.assertTrue(len(val["emptyMandatory"]) > 0 or len(val["errorMessages"]) > 0)
        page.close()

    # Scenario 9: Forms that open in a new tab
    def test_28_scenario_09_forms_opening_in_new_tab(self):
        # Mock opening application in a fresh page tab
        detail_tab = self.context.new_page()
        detail_tab.set_content("""
            <div>
                <a id="apply-portal-link" href="https://example.com/careers" target="_blank">Apply on Employer Site</a>
            </div>
        """)
        link = detail_tab.locator("#apply-portal-link")
        self.assertEqual(link.get_attribute("target"), "_blank")
        # Test context new page tracking
        new_tab = self.context.new_page()
        new_tab.set_content("<h1>Company Career Application</h1>")
        self.assertTrue(new_tab.is_visible("h1"))
        new_tab.close()
        detail_tab.close()

    # Scenario 10: LLM failures and deterministic fallbacks
    def test_29_scenario_10_llm_failures_and_deterministic_fallbacks(self):
        # Even if LLM query fails or returns None, deterministic profile resolution works seamlessly
        import ai_service
        original_query = ai_service.query_ai
        ai_service.query_ai = lambda prompt, sys="": ""  # Mock LLM failure

        try:
            # Notice Period
            res = qa_engine.process_question("What is your notice period?")
            self.assertEqual(res["source"], "CANDIDATE_PROFILE")
            self.assertIn("Immediate", res["answer"])

            # Experience
            res = qa_engine.process_question("Total years of experience in MERN?")
            self.assertEqual(res["source"], "CANDIDATE_PROFILE")
            self.assertIn("5", res["answer"])

            # CTC
            res = qa_engine.process_question("Current CTC?")
            self.assertEqual(res["source"], "CANDIDATE_PROFILE")
            self.assertIn("12", res["answer"])

            # Suitability
            res = qa_engine.process_question("Why are you suitable for this role?")
            self.assertEqual(res["source"], "CANDIDATE_PROFILE")
            self.assertTrue(len(res["answer"]) > 20)
        finally:
            ai_service.query_ai = original_query

    # Scenario 11: User cancellation during question answering
    def test_30_scenario_11_user_cancellation_during_answering(self):
        stop_ev = threading.Event()
        stop_ev.set()  # User clicks Stop

        page = self.context.new_page()
        page.set_content("""
            <form>
                <input type="text" name="dummy" />
            </form>
        """)
        res = process_and_fill_complete_form(
            page=page,
            qa_engine_instance=qa_engine,
            stop_event=stop_ev,
            company_name="CancelCorp",
            job_title="Developer"
        )
        self.assertEqual(res["status"], "STOPPED")
        self.assertEqual(res["reason"], "STOP_REQUESTED")
        page.close()

    # Scenario 12: Prevention of duplicate submissions
    def test_31_scenario_12_prevention_of_duplicate_submissions(self):
        # 1. Database level check
        record_application(
            job_title="Senior Developer",
            company_name="DuplicatePreventionCorp",
            location="Mumbai",
            job_url="https://example.com/job-dup-1",
            status=ApplicationStatus.APPLICATION_CONFIRMED,
            apply_type="DIRECT_NAUKRI",
            match_score=95
        )
        already_applied = check_already_applied_db("Senior Developer", "DuplicatePreventionCorp")
        self.assertTrue(already_applied, "check_already_applied_db must return True for recorded job")

        # 2. UI button level check
        page = self.context.new_page()
        page.set_content("""
            <div class="actions">
                <button class="applied-badge">Applied 2 days ago</button>
            </div>
        """)
        action_type, el = detect_naukri_action_button(page)
        self.assertEqual(action_type, "ALREADY_APPLIED", "Should identify ALREADY_APPLIED action type")
        page.close()

    # Scenario 13: Naukri Right-Side Chat Panel Detection & Compound Notice Question
    def test_32_naukri_chat_panel_detection_and_compound_notice_question(self):
        page = self.context.new_page()
        # Mock reproducing exact Naukri right-side chat screening drawer
        page.set_content("""
            <div id="drawer-container" class="chatbot_drawer right-panel" style="position: fixed; right: 0; width: 400px; height: 100%; background: #fff;">
                <div class="drawer-header">
                    <span class="title">Screening Questions</span>
                    <button class="close-btn" aria-label="Close">✕</button>
                </div>
                <div class="chatContent">
                    <div class="botMsg msgText">What is your official notice period? IF serving what is the LWD?</div>
                </div>
                <div class="drawer-footer" style="position: absolute; bottom: 0; width: 100%;">
                    <input class="chat-input" id="chat-input" placeholder="Type message here..." />
                    <button class="save-btn" id="save-btn" type="button">Save</button>
                </div>
            </div>
            <script>
                document.getElementById('save-btn').addEventListener('click', function() {
                    var val = document.getElementById('chat-input').value;
                    if (val && val.trim().length > 0) {
                        // Close panel on save
                        document.getElementById('drawer-container').style.display = 'none';
                    }
                });
            </script>
        """)

        # 1. Detect visible chat panel
        panel = naukri_chat_panel_handler.detect_chat_panel(page)
        self.assertIsNotNone(panel, "Must detect the right-side chat-style application panel")

        # 2. Extract actual question displayed in chat bubble
        q_text = naukri_chat_panel_handler.extract_latest_question(page, panel)
        self.assertEqual(q_text, "What is your official notice period? IF serving what is the LWD?")
        self.assertNotEqual(q_text, "Type message here...", "Must NOT extract placeholder as question text")

        # 3. Resolve answer accurately (candidate is Immediate Joiner, not serving notice; never invent a date)
        qa_res = qa_engine.process_question(q_text, input_type="text")
        self.assertIn("Immediate", qa_res["answer"], "Notice period answer must be Immediate Joiner")
        self.assertNotIn("2026", qa_res["answer"], "Must NEVER return today's date for compound notice question")
        self.assertFalse(qa_res["needs_user_input"])

        # 4. Locate input associated with question
        chat_inp = naukri_chat_panel_handler.locate_chat_input(page, panel)
        self.assertIsNotNone(chat_inp, "Must locate input with placeholder 'Type message here...'")

        # 5. Fill and verify answer retention
        inserted = naukri_chat_panel_handler.fill_and_verify_answer(page, chat_inp, qa_res["answer"])
        self.assertTrue(inserted, "Entered answer must be retained and verified in input")

        # 6. Locate Save button
        save_btn = naukri_chat_panel_handler.locate_save_button(page, panel)
        self.assertIsNotNone(save_btn, "Must locate Save button within the panel")
        self.assertTrue(save_btn.is_visible())
        self.assertTrue(save_btn.is_enabled())

        # 7. Execute complete sequential processing loop
        res = naukri_chat_panel_handler.process_sequential_chat_questions(
            page=page,
            qa_engine_instance=qa_engine,
            stop_event=threading.Event(),
            company="Hiringeye Solutions",
            title="Senior Software Engineer"
        )
        self.assertEqual(res["status"], ChatPanelState.FORM_COMPLETED)
        self.assertTrue(res["success"])
        page.close()

    # Scenario 14: Sequential Questions Handling in Chat Panel
    def test_33_sequential_screening_questions_in_chat_panel(self):
        page = self.context.new_page()
        # Mock sequential screening panel where question 2 appears after saving question 1
        page.set_content("""
            <div id="drawer-container" class="chatbot_drawer" style="position: fixed; right: 0; width: 400px; height: 100%;">
                <div class="chatContent" id="chat-content">
                    <div class="botMsg msgText">What is your official notice period? IF serving what is the LWD?</div>
                </div>
                <div class="footer">
                    <input class="chat-input" id="chat-input" placeholder="Type message here..." />
                    <button class="save-btn" id="save-btn">Save</button>
                </div>
            </div>
            <script>
                var round = 1;
                document.getElementById('save-btn').addEventListener('click', function() {
                    var inp = document.getElementById('chat-input');
                    if (round === 1) {
                        round = 2;
                        inp.value = '';
                        var newMsg = document.createElement('div');
                        newMsg.className = 'botMsg msgText';
                        newMsg.innerText = 'What is your expected CTC in LPA?';
                        document.getElementById('chat-content').appendChild(newMsg);
                    } else if (round === 2) {
                        // After round 2, panel closes and application confirmed
                        document.getElementById('drawer-container').style.display = 'none';
                        var badge = document.createElement('div');
                        badge.className = 'applied-badge';
                        badge.innerText = 'Applied successfully';
                        document.body.appendChild(badge);
                    }
                });
            </script>
        """)

        res = naukri_chat_panel_handler.process_sequential_chat_questions(
            page=page,
            qa_engine_instance=qa_engine,
            stop_event=threading.Event(),
            company="MultiRoundCorp",
            title="Senior Full Stack Developer"
        )
        self.assertIn(res["status"], [ChatPanelState.FORM_COMPLETED, ChatPanelState.APPLICATION_CONFIRMED])
        self.assertTrue(res["success"])
        self.assertEqual(len(res.get("processed", [])), 2, "Must process both sequential questions")
        page.close()

    # Scenario 15: Safe Stop on Unavailable Personal Information
    def test_34_safe_stop_on_unavailable_personal_info_in_chat_panel(self):
        page = self.context.new_page()
        # Mock panel asking for unverified personal family data
        page.set_content("""
            <div id="drawer-container" class="chatbot_drawer" style="position: fixed; right: 0; width: 400px; height: 100%;">
                <div class="chatContent">
                    <div class="botMsg msgText">Please enter your Father's Middle Name *</div>
                </div>
                <div class="footer">
                    <input class="chat-input" id="chat-input" placeholder="Type message here..." />
                    <button class="save-btn" id="save-btn">Save</button>
                </div>
            </div>
        """)

        res = naukri_chat_panel_handler.process_sequential_chat_questions(
            page=page,
            qa_engine_instance=qa_engine,
            stop_event=threading.Event(),
            company="SecurityCorp",
            title="Developer"
        )
        self.assertEqual(res["status"], ChatPanelState.NEEDS_USER_INPUT)
        self.assertFalse(res.get("success", False))
        # Verify tab and panel were preserved open
        self.assertFalse(page.is_closed(), "Tab must remain OPEN for user input")
        self.assertTrue(page.locator("#drawer-container").is_visible(), "Drawer must remain OPEN in Chrome")
        page.close()

    # Scenario 16: Prevent False Confirmation When Panel Remains Open
    def test_35_prevent_false_confirmation_when_panel_remains_open(self):
        page = self.context.new_page()
        # Mock panel where Save is clicked but server hangs or question remains unanswered
        page.set_content("""
            <div id="drawer-container" class="chatbot_drawer" style="position: fixed; right: 0; width: 400px; height: 100%;">
                <div class="chatContent">
                    <div class="botMsg msgText">What is your official notice period? IF serving what is the LWD?</div>
                </div>
                <div class="footer">
                    <input class="chat-input" id="chat-input" placeholder="Type message here..." />
                    <button class="save-btn" id="save-btn">Save</button>
                </div>
            </div>
            <script>
                // Click does not close the panel (simulating server hang or timeout)
                document.getElementById('save-btn').addEventListener('click', function() {
                    console.log('Save clicked but panel stays open');
                });
            </script>
        """)

        res = naukri_chat_panel_handler.process_sequential_chat_questions(
            page=page,
            qa_engine_instance=qa_engine,
            stop_event=threading.Event(),
            company="HangingCorp",
            title="Developer",
            max_rounds=2
        )
        # An open panel must NOT be reported as confirmed!
        self.assertNotEqual(res.get("status"), ApplicationStatus.APPLICATION_CONFIRMED)
        self.assertTrue(page.locator("#drawer-container").is_visible(), "Panel should remain open")
        page.close()

    # Scenario 17: Autonomous Reasoning Engine (Observe -> Reason -> Act -> Verify)
    def test_36_autonomous_reasoning_observe_reason_act_verify_loop(self):
        page = self.context.new_page()
        page.set_content("""
            <div id="drawer-container" class="chatbot_drawer" style="position: fixed; right: 0; width: 400px; height: 100%;">
                <div class="chatContent">
                    <div class="botMsg msgText">What is your official notice period? IF serving what is the LWD?</div>
                </div>
                <div class="footer">
                    <input class="chat-input" id="chat-input" placeholder="Type message here..." />
                    <button class="save-btn" id="save-btn">Save</button>
                </div>
            </div>
            <script>
                document.getElementById('save-btn').addEventListener('click', function() {
                    document.getElementById('drawer-container').style.display = 'none';
                });
            </script>
        """)

        # 1. OBSERVE
        obs = reasoning_engine.observe(page, {"job_title": "Senior Software Engineer", "company_name": "ReasoningCorp"})
        self.assertEqual(obs.panel_type, "CHAT_DRAWER")
        self.assertIn("What is your official notice period?", obs.visible_questions[0])
        self.assertTrue(obs.has_save_or_submit_button)

        # 2. REASON
        decision = reasoning_engine.reason(obs)
        self.assertIn(decision.action, ALLOWED_TOOLS, "Decision action must be in allowed tools allowlist")
        self.assertEqual(decision.action, "PROCESS_CHAT_QUESTION")
        self.assertFalse(decision.requires_user_input)
        self.assertEqual(decision.source, "CANDIDATE_PROFILE")

        # 3. ACT
        act_res = reasoning_engine.act(page, decision)
        self.assertTrue(act_res.get("success", False))

        # 4. VERIFY
        verified, msg = reasoning_engine.verify(page, decision, act_res)
        self.assertTrue(verified, f"Verification must confirm successful completion: {msg}")

        # 5. Reasoning Quality Metrics
        metrics = get_reasoning_metrics()
        self.assertIn("question_detection_count", metrics)
        self.assertIn("answer_insertion_success_count", metrics)
        page.close()

    # Scenario 18: Self-Correction and Experience Memory Persistence
    def test_37_self_correction_and_experience_memory(self):
        # 1. Experience recording and lookup
        record_experience(
            domain="naukri.com",
            page_type="chat_panel",
            problem_pattern="NOTICE_PERIOD_COMPOUND",
            action_taken="IMMEDIATE_NOT_SERVING",
            recovery_strategy="NONE",
            result_status="SUCCESS",
            confidence=1.0
        )
        experiences = lookup_experience("naukri.com", "NOTICE_PERIOD_COMPOUND")
        self.assertTrue(len(experiences) > 0, "Must retrieve past recorded experience")
        self.assertEqual(experiences[0]["result_status"], "SUCCESS")

        # 2. Self-correction simulation
        page = self.context.new_page()
        page.set_content("""
            <div class="chatbot_drawer">
                <input class="chat-input" placeholder="Type message here..." />
                <button class="save-btn" id="save-btn" disabled>Save</button>
            </div>
            <script>
                // Blur enables the save button
                window.addEventListener('blur', function() {
                    document.getElementById('save-btn').disabled = false;
                });
            </script>
        """)
        # Trigger self-correction for disabled save button
        corrected = reasoning_engine.self_correct(page, "SAVE_BUTTON_NOT_ENABLED", attempt=1, max_attempts=2)
        # Experience memory should be logged
        metrics = get_reasoning_metrics()
        self.assertIn("total_recovery_attempts", metrics)
        page.close()

    # Scenario 1: Standard Single-Page Application Form
    def test_38_scenario_01_standard_single_page_form(self):
        page = self.context.new_page()
        page.set_content("""
            <form id="apply-form">
                <div class="form-group">
                    <label for="name">Full Name *</label>
                    <input id="name" name="name" required />
                </div>
                <div class="form-group">
                    <label for="email">Email Address *</label>
                    <input id="email" name="email" type="email" required />
                </div>
                <div class="form-group">
                    <label for="phone">Phone Number *</label>
                    <input id="phone" name="phone" type="tel" required />
                </div>
                <div class="form-group">
                    <label for="exp">Total Experience (Years) *</label>
                    <input id="exp" name="exp" required />
                </div>
                <div class="form-group">
                    <label for="notice">Notice Period *</label>
                    <input id="notice" name="notice" required />
                </div>
                <button type="submit" id="submit-btn">Submit Application</button>
            </form>
        """)
        res = process_and_fill_complete_form(
            page=page,
            qa_engine_instance=qa_engine,
            stop_event=threading.Event(),
            company_name="SinglePageCorp",
            job_title="Full Stack Engineer"
        )
        self.assertTrue(res.get("success"), f"Single-page form should fill successfully: {res}")
        self.assertEqual(res.get("status"), "FORM_VALIDATED")
        self.assertEqual(page.locator("#name").input_value(), "Abdul Razzaque Shaikh")
        self.assertEqual(page.locator("#email").input_value(), "mhaslaiabdur@gmail.com")
        page.close()

    # Scenario 2: Multi-Step Career Portal
    def test_39_scenario_02_multistep_career_portal(self):
        page = self.context.new_page()
        page.set_content("""
            <div id="portal-step-1">
                <h2>Step 1: Contact Details</h2>
                <input id="full-name" placeholder="Full Name" value="Abdul Razzaque Shaikh" />
                <button id="btn-next-1" class="btn next-step">Continue to Experience</button>
            </div>
        """)
        # Detect continue button on step 1
        btn1 = button_service.find_action_button(page, [ButtonCategory.CONTINUE, ButtonCategory.REVIEW])
        self.assertIsNotNone(btn1, "Must detect continue button on Step 1")
        self.assertIn("continue", btn1.inner_text().lower())

        # Advance to step 2
        page.set_content("""
            <div id="portal-step-2">
                <h2>Step 2: Experience & Skills</h2>
                <input id="tech-skills" placeholder="Skills" value="React.js, Node.js, Next.js" />
                <button id="btn-next-2" class="btn next-step">Next Step</button>
            </div>
        """)
        btn2 = button_service.find_action_button(page, [ButtonCategory.CONTINUE])
        self.assertIsNotNone(btn2, "Must detect Next Step on Step 2")

        # Advance to step 3 (final submission)
        page.set_content("""
            <div id="portal-step-3">
                <h2>Step 3: Review & Submit</h2>
                <button id="btn-submit" class="btn submit-app">Submit Application</button>
            </div>
        """)
        btn3 = button_service.find_action_button(page, [ButtonCategory.SUBMIT])
        self.assertIsNotNone(btn3, "Must detect Submit Application on final step")
        self.assertIn("submit", btn3.inner_text().lower())
        page.close()

    # Scenario 3: Forms with Custom Dropdowns
    def test_40_scenario_03_custom_dropdown_selection(self):
        page = self.context.new_page()
        page.set_content("""
            <div class="custom-select-container">
                <label id="lbl-notice">Notice Period</label>
                <div id="notice-dropdown" role="combobox" aria-labelledby="lbl-notice" class="custom-select">
                    <span class="selected-text">Select notice</span>
                </div>
                <div class="options-list" style="display: block;">
                    <div role="option" class="option" id="opt-1">30 Days</div>
                    <div role="option" class="option" id="opt-2">Immediate Joiner</div>
                    <div role="option" class="option" id="opt-3">60 Days</div>
                </div>
            </div>
        """)
        field_meta = {
            "fieldType": FormFieldType.CUSTOM_SELECT,
            "id": "notice-dropdown",
            "questionText": "Notice Period",
            "isRequired": True,
            "selector": "#notice-dropdown"
        }
        res = fill_form_control(
            page=page,
            field=field_meta,
            answer="Immediate Joiner",
            selected_option={"text": "Immediate Joiner", "value": "immediate"},
            stop_event=threading.Event()
        )
        self.assertTrue(res.get("success"), f"Custom dropdown selection must succeed: {res}")
        page.close()

    # Scenario 4: Forms with Dynamic Questions
    def test_41_scenario_04_dynamic_revealed_questions(self):
        page = self.context.new_page()
        page.set_content("""
            <form id="dynamic-form">
                <div class="form-group">
                    <label for="relocate">Are you open to relocate? *</label>
                    <select id="relocate" name="relocate" required>
                        <option value="">Select option</option>
                        <option value="yes">Yes</option>
                        <option value="no">No</option>
                    </select>
                </div>
                <div id="followup-container" style="display: none;">
                    <label for="city-pref">Preferred Relocation City *</label>
                    <input id="city-pref" name="city-pref" required />
                </div>
            </form>
            <script>
                document.getElementById('relocate').addEventListener('change', function() {
                    if (this.value === 'yes') {
                        document.getElementById('followup-container').style.display = 'block';
                    }
                });
            </script>
        """)
        res = process_and_fill_complete_form(
            page=page,
            qa_engine_instance=qa_engine,
            stop_event=threading.Event(),
            company_name="DynamicCorp",
            job_title="Software Developer",
            max_dynamic_passes=3
        )
        self.assertTrue(res.get("success"), "Dynamic form filling must succeed across passes")
        # Follow-up field became visible and was filled with candidate location
        self.assertIn("Mumbai", page.locator("#city-pref").input_value())
        page.close()

    # Scenario 5: Forms Requiring Resume Uploads
    def test_42_scenario_05_resume_and_document_upload(self):
        page = self.context.new_page()
        page.set_content("""
            <form id="upload-form">
                <label for="resume-file">Upload Resume / CV (PDF) *</label>
                <input type="file" id="resume-file" name="resume" accept=".pdf,.doc,.docx" required />
                <button type="submit">Submit</button>
            </form>
        """)
        # 1. Test dedicated upload function
        upload_res = upload_resume_file(page)
        self.assertTrue(upload_res.get("success"), f"Resume upload must succeed: {upload_res}")
        self.assertIn(".pdf", upload_res.get("filename", "").lower())

        # 2. Test field detection for file input
        fields = detect_and_collect_form_questions(page)
        file_fields = [f for f in fields if f.get("fieldType") == "file"]
        self.assertTrue(len(file_fields) > 0, "detect_and_collect_form_questions must detect file input")
        self.assertTrue(file_fields[0]["isRequired"])
        page.close()

    # Scenario 6: Apply Buttons that Open New Tabs
    def test_43_scenario_06_apply_button_opens_new_tab(self):
        page = self.context.new_page()
        page.set_content("""
            <div class="actions">
                <a id="ext-apply" href="https://example.com/careers/job123" target="_blank">Apply on company site</a>
            </div>
        """)
        # Verify button detection classifies it as APPLY
        detected = button_service.detect_buttons_in_container(page)
        apply_btns = [b for b in detected if b.category == ButtonCategory.APPLY]
        self.assertTrue(len(apply_btns) > 0, "Must detect external apply link")

        # Test INSPECT_NEW_TAB tool in reasoning engine
        decision = AgentDecision(
            observation_summary="Apply opens external page",
            objective="Inspect new tab",
            action="INSPECT_NEW_TAB",
            action_params={},
            reason="External link opens new browser tab",
            source="DETERMINISTIC_TOOL",
            verification_plan="Verify new tab URL",
            requires_user_input=False
        )
        act_res = reasoning_engine.act(page, decision)
        self.assertTrue(act_res.get("success"))
        page.close()

    # Scenario 7: Disabled Buttons and Validation Errors
    def test_44_scenario_07_disabled_buttons_and_validation_errors(self):
        page = self.context.new_page()
        page.set_content("""
            <form id="test-val-form">
                <input id="req-field" required />
                <div class="error alert-danger" style="display: block;">This field is required.</div>
                <button id="submit-btn" disabled>Submit Application</button>
            </form>
        """)
        obs = reasoning_engine.observe(page, {"job_title": "Developer", "company_name": "ValCorp"})
        self.assertTrue(obs.has_validation_errors, "Must detect visible validation error")
        self.assertEqual(obs.error_message, "This field is required.")

        decision = reasoning_engine.reason(obs)
        self.assertTrue(decision.requires_user_input, "Validation error must trigger candidate input request")
        self.assertEqual(decision.action, "REQUEST_USER_INPUT")
        page.close()

    # Scenario 8: Unrecognized Questions Halt Safely
    def test_45_scenario_08_unrecognized_questions_halt_safely(self):
        page = self.context.new_page()
        page.set_content("""
            <form id="unrecognized-form">
                <label for="fav-element">What is your favorite periodic table element? *</label>
                <input id="fav-element" name="fav_element" required />
                <button type="submit">Submit</button>
            </form>
        """)
        res = process_and_fill_complete_form(
            page=page,
            qa_engine_instance=qa_engine,
            stop_event=threading.Event(),
            company_name="MysteryCorp",
            job_title="Developer"
        )
        self.assertEqual(res.get("status"), "NEEDS_USER_INPUT")
        self.assertFalse(res.get("success"))
        self.assertIn("favorite periodic table element", res.get("unanswered_question", "").lower())
        page.close()

    # Scenario 9: Gemini API Failure & Timeout Fallback
    def test_46_scenario_09_gemini_api_failure_and_timeout_fallback(self):
        # Temporarily point GEMINI_API_KEY to invalid/dummy key to test graceful fallback
        old_key = os.environ.get("GEMINI_API_KEY")
        try:
            os.environ["GEMINI_API_KEY"] = "INVALID_KEY_TO_TRIGGER_API_ERROR"
            # query_ai should gracefully catch API exception and fall back to Ollama or empty without crashing
            ans = query_ai("What is your total experience?", "Test assistant")
            self.assertIsInstance(ans, str, "query_ai must return string even when Gemini API fails")

            # reasoning_engine.reason must gracefully fall back to deterministic profile decision
            page = self.context.new_page()
            page.set_content("""
                <form id="fallback-form">
                    <input name="email" placeholder="Email" />
                    <button type="submit">Submit Application</button>
                </form>
            """)
            obs = reasoning_engine.observe(page, {"job_title": "Software Engineer", "company_name": "FallbackCorp"})
            dec = reasoning_engine.reason(obs)
            self.assertIn(dec.action, ALLOWED_TOOLS, "Must fall back to allowed tool on Gemini error")
            page.close()
        finally:
            if old_key is not None:
                os.environ["GEMINI_API_KEY"] = old_key
            elif "GEMINI_API_KEY" in os.environ:
                del os.environ["GEMINI_API_KEY"]

    # Scenario 10: Missing Profile Data Prevents Fabrication
    def test_47_scenario_10_missing_profile_data_no_fabrication(self):
        # Test QA resolution for unknown personal facts
        res = qa_engine.process_question(
            question_text="What was your University Graduation CGPA / Percentage? *",
            input_type="text",
            job_title="Full Stack Developer",
            company_name="AuditCorp"
        )
        # Profile contains degree and university, but not an exact fabricated CGPA
        # When exact facts are absent, it must flag needs_user_input instead of inventing a number
        self.assertTrue(res.get("needs_user_input") or "B.Sc" in res.get("answer", ""))

        # Test Notice Period zero fabrication: Candidate is Immediate Joiner
        np_res = qa_engine.process_question(
            question_text="What is your official notice period? IF serving what is the LWD?",
            input_type="text"
        )
        self.assertIn("Immediate", np_res.get("answer", ""))
        self.assertNotIn("30 days", np_res.get("answer", "").lower())
        self.assertNotIn("60 days", np_res.get("answer", "").lower())

    # Scenario 11: User Stop During Form Completion
    def test_48_scenario_11_user_stop_during_form_completion(self):
        page = self.context.new_page()
        page.set_content("""
            <form id="stop-form">
                <input id="q1" placeholder="Question 1" />
                <input id="q2" placeholder="Question 2" />
            </form>
        """)
        stop_evt = threading.Event()
        stop_evt.set()  # Stop requested by user

        res = process_and_fill_complete_form(
            page=page,
            qa_engine_instance=qa_engine,
            stop_event=stop_evt,
            company_name="StopCorp",
            job_title="Developer"
        )
        self.assertEqual(res.get("status"), "STOPPED")
        self.assertFalse(res.get("success"))
        self.assertEqual(res.get("reason"), "STOP_REQUESTED")
        page.close()

    # Scenario 12: Prevention of Duplicate Submissions
    def test_49_scenario_12_prevention_of_duplicate_submissions(self):
        job_url = "https://www.naukri.com/job-listings-duplicate-test-12345"
        # Record successful application
        record_application(
            job_title="MERN Stack Developer",
            company_name="DuplicateTestCorp",
            location="Mumbai",
            job_url=job_url,
            status="APPLICATION_CONFIRMED"
        )
        # Check duplicate lookup
        already_applied = check_already_applied_db("MERN Stack Developer", "DuplicateTestCorp")
        self.assertTrue(already_applied, "check_already_applied_db must prevent duplicate application")

    # Scenario 13: Correct Differentiation Between Submitted and Confirmed States
    def test_50_scenario_13_differentiate_submitted_and_confirmed(self):
        page = self.context.new_page()
        # Case A: Merely clicked button, form still open without confirmation message
        page.set_content("""
            <div id="hanging-modal">
                <p>Please wait, processing...</p>
                <input id="in-progress-input" value="Still here" />
            </div>
        """)
        dec = AgentDecision(
            observation_summary="Submit was clicked",
            objective="Verify submission",
            action="CLICK_SUBMIT",
            action_params={},
            reason="Form submit clicked",
            source="DETERMINISTIC_TOOL",
            verification_plan="Check for confirmation text",
            requires_user_input=False
        )
        # Verification check should return False when no confirmation message exists
        verified, status = reasoning_engine.verify(page, dec, {"success": True, "outcome": "CLICK_EXECUTED"})
        self.assertNotEqual(status, "APPLICATION_CONFIRMED")

        # Case B: Verified confirmation badge present
        page.set_content("""
            <div class="apply-message success-message">
                <h3>Application has been sent successfully!</h3>
            </div>
        """)
        verified_b, status_b = reasoning_engine.verify(page, dec, {"success": True, "confirmed": True})
        self.assertTrue(verified_b)
        self.assertEqual(status_b, "APPLICATION_CONFIRMED")
        page.close()

    # Scenario 14: Enhanced Dashboard Statistics Summary
    def test_51_dashboard_stats_and_failure_causes(self):
        # Insert test records for failure cause aggregation
        record_application(
            job_title="Test Job 1",
            company_name="FailCorp 1",
            location="Mumbai",
            job_url="https://test.com/fail1",
            status="APPLICATION_FAILED",
            failure_reason="CONFIRMATION_TIMEOUT"
        )
        record_application(
            job_title="Test Job 2",
            company_name="FailCorp 2",
            location="Mumbai",
            job_url="https://test.com/fail2",
            status="APPLICATION_FAILED",
            failure_reason="CONFIRMATION_TIMEOUT"
        )
        record_application(
            job_title="Test Job 3",
            company_name="BlockCorp 1",
            location="Mumbai",
            job_url="https://test.com/block1",
            status="APPLICATION_BLOCKED",
            failure_reason="PAYMENT_REQUEST_BLOCKED"
        )

        stats = get_dashboard_stats()
        self.assertIn("completed_applications", stats)
        self.assertIn("confirmed_submissions", stats)
        self.assertIn("pending_user_input", stats)
        self.assertIn("blocked_applications", stats)
        self.assertIn("failed_applications", stats)
        self.assertIn("common_failure_causes", stats)
        self.assertIsInstance(stats["common_failure_causes"], list)

    # Scenario 15: Structured Tool Allowlist Execution & Disallowed Action Rejection
    def test_52_structured_tool_allowlist_execution(self):
        page = self.context.new_page()
        page.set_content("""
            <form>
                <input id="input-test" name="test_field" />
                <input type="checkbox" id="chk-test" />
                <button type="submit" id="btn-save">Save</button>
            </form>
        """)

        # 1. Test FILL_INPUT
        dec_fill = AgentDecision(
            observation_summary="Fill input",
            objective="Fill field",
            action="FILL_INPUT",
            action_params={"selector": "#input-test", "value": "Test Value"},
            reason="Fill test",
            source="DETERMINISTIC_TOOL",
            verification_plan="Check value",
            requires_user_input=False
        )
        res_fill = reasoning_engine.act(page, dec_fill)
        self.assertTrue(res_fill.get("success"))
        self.assertEqual(page.locator("#input-test").input_value(), "Test Value")

        # 2. Test SET_CHECKBOX
        dec_chk = AgentDecision(
            observation_summary="Check box",
            objective="Check checkbox",
            action="SET_CHECKBOX",
            action_params={"selector": "#chk-test", "checked": True},
            reason="Check test",
            source="DETERMINISTIC_TOOL",
            verification_plan="Check state",
            requires_user_input=False
        )
        res_chk = reasoning_engine.act(page, dec_chk)
        self.assertTrue(res_chk.get("success"))
        self.assertTrue(page.locator("#chk-test").is_checked())

        # 3. Test Disallowed Action is safely blocked
        dec_bad = AgentDecision(
            observation_summary="Malicious code",
            objective="Run arbitrary bash",
            action="EXECUTE_ARBITRARY_SHELL",
            action_params={},
            reason="Unsafe",
            source="ATTACK",
            verification_plan="None",
            requires_user_input=False
        )
        res_bad = reasoning_engine.act(page, dec_bad)
        self.assertFalse(res_bad.get("success"))
        self.assertIn("ACTION_DISALLOWED", res_bad.get("error", ""))
        page.close()

    def test_53_naukri_chatbot_container_and_filter_user_bubbles(self):
        """Verify _chatBotContainer detection without save button and user bubble filtering."""
        page = self.context.new_page()
        page.set_content("""
            <div id="_ni615b3msChatbotContainer" class="_chatBotContainer">
                <div class="chatbot_Overlay show"></div>
                <div class="chatContent">
                    <div class="botMsg">What is your highest educational qualification?</div>
                    <div class="userMsg">Abdul_Razzaque_India.pdf</div>
                    <div class="botMsg">File upload was unsuccessful. Please try again.</div>
                    <div class="botMsg">Hi Abdul Razzaque, thank you for showing interest. Kindly answer all the recruiter's questions to successfully apply for the job.</div>
                    <div class="botMsg">What is your highest educational qualification?</div>
                    <div class="userMsg">BSC computer sciences</div>
                    <div class="botMsg">Have you completed or are you currently pursuing any professional qualification (e.g., CA, CS, CMA, CFA)?</div>
                </div>
                <input class="chat-input" placeholder="Type message here..." />
                <script>
                    document.querySelector('.chat-input').addEventListener('keydown', (e) => {
                        if (e.key === 'Enter') {
                            document.getElementById('_ni615b3msChatbotContainer').style.display = 'none';
                        }
                    });
                </script>
            </div>
        """)
        # 1. Panel Detection
        panel = naukri_chat_panel_handler.detect_chat_panel(page)
        self.assertIsNotNone(panel)

        # 2. Latest Question Extraction: should ignore userMsg, file attachment, and greeting/error notice
        q = naukri_chat_panel_handler.extract_latest_question(page, panel)
        self.assertEqual(q, "Have you completed or are you currently pursuing any professional qualification (e.g., CA, CS, CMA, CFA)?")

        # 3. No Save button present, but input should be filled and submitted via Enter
        res = naukri_chat_panel_handler.process_sequential_chat_questions(
            page=page,
            qa_engine_instance=qa_engine,
            stop_event=bot_state.stop_event,
            company="Morningstar",
            title="Node.js Developer",
            max_rounds=1
        )
        self.assertEqual(res.get("status"), "FORM_COMPLETED")
        self.assertEqual(page.locator("input.chat-input").input_value(), "No")
        page.close()

    def test_54_find_submit_button_ignores_bookmark_button(self):
        """Ensure find_submit_button never selects background Save Job bookmark button."""
        page = self.context.new_page()
        page.set_content("""
            <div>
                <button type="button" aria-pressed="false" class="styles_save-job-button__WLm_s">Save</button>
                <button type="button" class="btn-bookmark">Bookmark</button>
            </div>
        """)
        btn = find_submit_button(page)
        self.assertIsNone(btn)
        page.close()

    def test_55_qa_qualification_answers(self):
        """Verify QA engine correctly answers highest qualification and professional qualification questions."""
        q1 = qa_engine.process_question("What is your highest educational qualification?", "text")
        self.assertEqual(q1.get("answer"), "BSC Computer Science")

        q2 = qa_engine.process_question("Have you completed or are you currently pursuing any professional qualification (e.g., CA, CS, CMA, CFA)?", "text")
        self.assertEqual(q2.get("answer"), "No")

    # Scenario 15: Naukri Direct Apply Confirmation Detection (ACP & saveApply)
    def test_56_is_naukri_application_confirmed_saveapply_url(self):
        """Ensure saveApply URL with 200 response confirms application immediately."""
        page = self.context.new_page()
        page.goto("https://www.naukri.com/myapply/saveApply?strJobsarr=[261026002320]&multiApplyResp=%7B%22261026002320%22%3A200%7D")
        is_conf, reason = is_naukri_application_confirmed(page)
        self.assertTrue(is_conf)
        self.assertEqual(reason, "URL_MULTI_APPLY_200")
        page.close()

    def test_57_is_naukri_application_confirmed_acp_elements(self):
        """Ensure Apply Confirmation Page container (.acp-container) and heading are detected."""
        page = self.context.new_page()
        page.set_content("""
            <div id="root">
                <div class="acp-container">
                    <div class="acp-header-container">
                        <h3>Applied to "Digital : Microservices(Java Full Stack, Angular)"</h3>
                    </div>
                </div>
            </div>
        """)
        is_conf, reason = is_naukri_application_confirmed(page)
        self.assertTrue(is_conf)
        self.assertEqual(reason, "DOM_ACP_CONTAINER_FOUND")
        page.close()

    def test_58_is_naukri_application_confirmed_already_applied_badge(self):
        """Ensure '#already-applied' span and 'Applied' button container confirm application."""
        page = self.context.new_page()
        page.set_content("""
            <div class="styles_jhc__apply-button-container__5Bqnb">
                <span id="already-applied" class="styles_already-applied__4KDhw already-applied">Applied</span>
            </div>
        """)
        is_conf, reason = is_naukri_application_confirmed(page)
        self.assertTrue(is_conf)
        self.assertEqual(reason, "DOM_ALREADY_APPLIED_BADGE")
        page.close()

    def test_59_is_naukri_application_confirmed_toast_notification(self):
        """Ensure toast notifications with 'applied successfully' are detected."""
        page = self.context.new_page()
        page.set_content("""
            <div>
                <div class="toaster visible">
                    <span class="toast-message">You have successfully applied to Tata Consultancy Services</span>
                </div>
            </div>
        """)
        is_conf, reason = is_naukri_application_confirmed(page)
        self.assertTrue(is_conf)
        self.assertEqual(reason, "TOAST_CONFIRMATION_FOUND")
        page.close()

    def test_60_is_naukri_application_confirmed_prevents_false_positive(self):
        """Ensure an unapplied job details page with normal Apply button returns False."""
        page = self.context.new_page()
        page.set_content("""
            <div>
                <div class="apply-button-container">
                    <button id="apply-button" class="apply-button">Apply</button>
                </div>
                <input class="suggestor-input" placeholder="Search jobs here" />
            </div>
        """)
        is_conf, reason = is_naukri_application_confirmed(page)
        self.assertFalse(is_conf)
        self.assertEqual(reason, "NOT_CONFIRMED")
    def test_61_reasoning_engine_verify_application_submission_action(self):
        """Ensure reasoning engine VERIFY_APPLICATION_SUBMISSION safely runs and returns boolean confirmed & reason."""
        page = self.context.new_page()
        page.set_content("""
            <div class="apply-button-container">
                <span id="already-applied" class="already-applied">Applied</span>
            </div>
        """)
        dec = AgentDecision(
            observation_summary="Verify applied status",
            objective="Confirm application submission",
            action="VERIFY_APPLICATION_SUBMISSION",
            action_params={},
            reason="Test verification",
            source="TEST",
            verification_plan="Check confirmation",
            requires_user_input=False
        )
        res = reasoning_engine.act(page, dec, "TestCompany")
        self.assertTrue(res.get("success"))
        self.assertTrue(res.get("confirmed"))
        self.assertEqual(res.get("reason"), "DOM_ALREADY_APPLIED_BADGE")
        page.close()

    def test_62_chat_panel_chip_options_without_input_field(self):
        """Ensure chat panel with quick-reply chips and NO text input field is answered by clicking the chip."""
        page = self.context.new_page()
        page.set_content("""
            <div id="_chatBotContainer" class="_chatBotContainer" style="position: fixed; right: 0; width: 400px; height: 100%;">
                <div class="chatContent" id="chat-content">
                    <div class="botMsg msgText">Are you currently residing in Mumbai or willing to relocate to Mumbai?</div>
                    <div class="quick-reply" id="chips-area">
                        <button class="chip" id="opt-1" onclick="document.getElementById('_chatBotContainer').style.display='none';">Currently residing in Mumbai</button>
                        <button class="chip" id="opt-2" onclick="document.getElementById('_chatBotContainer').style.display='none';">Willing to relocate to Mumbai</button>
                        <button class="chip" id="opt-3">No</button>
                    </div>
                </div>
            </div>
        """)
        res = naukri_chat_panel_handler.process_sequential_chat_questions(
            page=page,
            qa_engine_instance=qa_engine,
            stop_event=threading.Event(),
            company="Zenvior Technologies",
            title="Fullstack Developer",
            max_rounds=1
        )
        self.assertEqual(res.get("status"), ChatPanelState.FORM_COMPLETED)
        self.assertTrue(res.get("success"))
        self.assertNotIn("CHAT_INPUT_NOT_FOUND", res.get("reason", ""))
        page.close()

    def test_63_chat_panel_technical_skills_choice_without_input_field(self):
        """Ensure backend technology choice questions (e.g. Golang or Node.js) pick Node.js from profile."""
        page = self.context.new_page()
        page.set_content("""
            <div id="_chatBotContainer" class="_chatBotContainer" style="position: fixed; right: 0; width: 400px; height: 100%;">
                <div class="chatContent" id="chat-content">
                    <div class="botMsg msgText">Which backend technology do you have the strongest hands-on experience in: Golang or Node.js?</div>
                    <div class="quick-reply" id="chips-area">
                        <button class="chip" id="opt-go">Golang</button>
                        <button class="chip" id="opt-node" onclick="document.getElementById('_chatBotContainer').style.display='none';">Node.js</button>
                    </div>
                </div>
            </div>
        """)
        res = naukri_chat_panel_handler.process_sequential_chat_questions(
            page=page,
            qa_engine_instance=qa_engine,
            stop_event=threading.Event(),
            company="Zenvior Technologies",
            title="Fullstack Developer",
            max_rounds=1
        )
        self.assertEqual(res.get("status"), ChatPanelState.FORM_COMPLETED)
        self.assertTrue(res.get("success"))
    def test_64_chat_panel_contenteditable_div_input_and_sendMsg(self):
        """Ensure chat panel with contenteditable div input and .sendMsg Save button verifies answer and completes."""
        page = self.context.new_page()
        page.set_content("""
            <div id="_chatBotContainer" class="_chatBotContainer" style="position: fixed; right: 0; width: 400px; height: 100%;">
                <div class="chatContent" id="chat-content">
                    <div class="botMsg msgText">What is your highest educational qualification?</div>
                    <div id="userInput__abc" class="textArea" contenteditable="true" data-placeholder="Type message here..."></div>
                    <div class="sendMsgbtn_container">
                        <div id="sendMsg__abc" class="send">
                            <div class="sendMsg" tabindex="0" onclick="document.getElementById('_chatBotContainer').style.display='none';">Save</div>
                        </div>
                    </div>
                </div>
            </div>
        """)
        res = naukri_chat_panel_handler.process_sequential_chat_questions(
            page=page,
            qa_engine_instance=qa_engine,
            stop_event=threading.Event(),
            company="Morningstar India",
            title="Software Engineer",
            max_rounds=1
        )
        self.assertEqual(res.get("status"), ChatPanelState.FORM_COMPLETED)
        self.assertTrue(res.get("success"))
        self.assertNotIn("ANSWER_INSERTION_UNVERIFIED", res.get("reason", ""))
        self.assertNotIn("CHAT_INPUT_NOT_FOUND", res.get("reason", ""))
        page.close()

    def test_65_chat_panel_ssrc_radio_buttons_and_sendMsg(self):
        """Ensure TCS style ssrc__radio-btn-container options click the label, enable .sendMsg Save button, and advance cleanly."""
        page = self.context.new_page()
        page.set_content("""
            <div id="_chatBotContainer" class="_chatBotContainer" style="position: fixed; right: 0; width: 400px; height: 100%;">
                <div class="chatContent" id="chat-content">
                    <div class="botMsg msgText">Comfortable for Mumbai location ?</div>
                    <div class="ssrc__radio-btn-container">
                        <input type="radio" id="opt-yes" class="ssrc__radio" value="Yes">
                        <label for="opt-yes" class="ssrc__label" onclick="document.getElementById('sendMsg__container').classList.remove('disabled');">Yes</label>
                    </div>
                    <div class="ssrc__radio-btn-container">
                        <input type="radio" id="opt-no" class="ssrc__radio" value="No">
                        <label for="opt-no" class="ssrc__label">No</label>
                    </div>
                    <div class="sendMsgbtn_container">
                        <div id="sendMsg__container" class="send disabled">
                            <div class="sendMsg" tabindex="0" onclick="if (!this.parentElement.classList.contains('disabled')) document.getElementById('_chatBotContainer').style.display='none';">Save</div>
                        </div>
                    </div>
                </div>
            </div>
        """)
        res = naukri_chat_panel_handler.process_sequential_chat_questions(
            page=page,
            qa_engine_instance=qa_engine,
            stop_event=threading.Event(),
            company="Tata Consultancy Services",
            title="Core Java Developer",
            max_rounds=1
        )
        self.assertEqual(res.get("status"), ChatPanelState.FORM_COMPLETED)
        self.assertTrue(res.get("success"))
        self.assertIn("Comfortable for Mumbai location ?", res.get("processed", []))
        page.close()

if __name__ == "__main__":
    unittest.main()



