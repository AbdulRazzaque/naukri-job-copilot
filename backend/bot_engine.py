import sys
import os
import re
import json
import asyncio
import random
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from playwright.sync_api import sync_playwright, Browser, Page

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from database import (
    get_today_applied_count, 
    record_application, 
    log_event, 
    get_connection,
    format_final_application_report,
    check_already_applied_db
)
from ai_service import (
    evaluate_job_relevance, 
    answer_application_question, 
    evaluate_application_question,
    is_sensitive_or_payment_question,
    get_candidate_profile
)
from agent_config import agent_config_manager
from form_engine import (
    detect_and_collect_form_questions,
    fill_form_control,
    validate_entire_form,
    process_and_fill_complete_form,
    FormFieldType
)
from question_answering import (
    QuestionAnsweringEngine,
    QuestionCategory,
    qa_engine,
    match_best_option
)
from candidate_manager import getCandidateProfileByJobLocation, CandidateProfileManager, mask_phone_number
from chat_panel_handler import naukri_chat_panel_handler, ChatPanelState
from reasoning_engine import reasoning_engine, AutonomousReasoningEngine
from button_service import button_service, is_naukri_application_confirmed
from linkedin_engine import LinkedInEngine
from naukrigulf_engine import NaukriGulfEngine

class ApplicationStatus:
    JOB_FOUND = "JOB_FOUND"
    JOB_DETAILS_OPENED = "JOB_DETAILS_OPENED"
    APPLY_CLICKED = "APPLY_CLICKED"
    APPLICATION_FORM_OPENED = "APPLICATION_FORM_OPENED"
    FORM_OPENED = "APPLICATION_FORM_OPENED"
    QUESTION_DETECTED = "QUESTION_DETECTED"
    QUESTIONS_DETECTED = "QUESTIONS_DETECTED"
    ANSWER_GENERATED = "ANSWER_GENERATED"
    ANSWERS_GENERATED = "ANSWERS_GENERATED"
    ANSWER_INSERTED = "ANSWER_INSERTED"
    ANSWER_SAVED = "ANSWER_SAVED"
    NEXT_QUESTION_PENDING = "NEXT_QUESTION_PENDING"
    FORM_FILLING = "FORM_FILLING"
    FORM_FILLED = "FORM_FILLED"
    FORM_VALIDATING = "FORM_VALIDATING"
    FORM_VALIDATED = "FORM_VALIDATED"
    READY_TO_SUBMIT = "READY_TO_SUBMIT"
    NEEDS_USER_INPUT = "NEEDS_USER_INPUT"
    FORM_SUBMITTED = "FORM_SUBMITTED"
    FORM_COMPLETED = "FORM_COMPLETED"
    APPLICATION_CONFIRMED = "APPLICATION_CONFIRMED"
    APPLICATION_FAILED = "APPLICATION_FAILED"
    APPLICATION_BLOCKED = "APPLICATION_BLOCKED"
    APPLICATION_SKIPPED = "APPLICATION_SKIPPED"
    APPLICATION_PENDING_CONFIRMATION = "APPLICATION_PENDING_CONFIRMATION"
    CONFIRMATION_TIMEOUT = "CONFIRMATION_TIMEOUT"

class BotConfig:
    def __init__(self):
        cfg = agent_config_manager.get_config()
        cooldown = cfg.get("cooldown", {})
        safety = cfg.get("safety_boundaries", {})
        retry = cfg.get("retry_policy", {})

        self.cooldown_min_sec = int(cooldown.get("confirmed_min_sec", 120))
        self.cooldown_max_sec = int(cooldown.get("confirmed_max_sec", 180))
        self.unconfirmed_cooldown_min_sec = int(cooldown.get("unconfirmed_min_sec", 45))
        self.unconfirmed_cooldown_max_sec = int(cooldown.get("unconfirmed_max_sec", 75))
        self.daily_limit = int(safety.get("max_daily_applications", 135))
        self.naukri_quota = int(safety.get("max_daily_naukri", 45))
        self.linkedin_quota = int(safety.get("max_daily_linkedin", 45))
        self.naukrigulf_quota = int(safety.get("max_daily_naukrigulf", 45))
        self.max_retries = int(retry.get("max_retries", 2))

    def reload(self):
        cfg = agent_config_manager.get_config()
        cooldown = cfg.get("cooldown", {})
        safety = cfg.get("safety_boundaries", {})
        retry = cfg.get("retry_policy", {})

        self.cooldown_min_sec = int(cooldown.get("confirmed_min_sec", 120))
        self.cooldown_max_sec = int(cooldown.get("confirmed_max_sec", 180))
        self.unconfirmed_cooldown_min_sec = int(cooldown.get("unconfirmed_min_sec", 45))
        self.unconfirmed_cooldown_max_sec = int(cooldown.get("unconfirmed_max_sec", 75))
        self.daily_limit = int(safety.get("max_daily_applications", 135))
        self.naukri_quota = int(safety.get("max_daily_naukri", 45))
        self.linkedin_quota = int(safety.get("max_daily_linkedin", 45))
        self.naukrigulf_quota = int(safety.get("max_daily_naukrigulf", 45))
        self.max_retries = int(retry.get("max_retries", 2))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cooldown_min_sec": self.cooldown_min_sec,
            "cooldown_max_sec": self.cooldown_max_sec,
            "unconfirmed_cooldown_min_sec": self.unconfirmed_cooldown_min_sec,
            "unconfirmed_cooldown_max_sec": self.unconfirmed_cooldown_max_sec,
            "daily_limit": self.daily_limit,
            "naukri_quota": self.naukri_quota,
            "linkedin_quota": self.linkedin_quota,
            "naukrigulf_quota": self.naukrigulf_quota,
            "max_retries": self.max_retries
        }

class BotState:
    def __init__(self):
        self.is_running = False
        self.status = "IDLE"  # IDLE, CONNECTING, SEARCHING, EVALUATING, APPLYING, COOLDOWN, LIMIT_REACHED, STOPPED, ERROR
        self.current_job: Dict[str, Any] = {}
        self.countdown_remaining = 0
        self.today_applied = 0
        self.daily_limit = 135
        self.platform_quotas = {
            "NAUKRI": 45,
            "LINKEDIN": 45,
            "NAUKRIGULF": 45
        }
        self.platform_applied = {
            "NAUKRI": 0,
            "LINKEDIN": 0,
            "NAUKRIGULF": 0
        }
        self.last_error = ""
        self.last_search_diagnostics = {
            "requestedLocation": "",
            "actualBrowserLocation": "",
            "locationVerified": False,
            "searchKeyword": "",
            "searchUrl": "",
            "linkedinResultCount": 0,
            "extractedJobCount": 0,
            "locationSyncStatus": "IDLE",
            "extractionStatus": "IDLE"
        }
        self.stop_event = threading.Event()
        self.logs: List[Dict[str, str]] = []
        self.config = BotConfig()

    def add_log(self, message: str, level: str = "INFO"):
        entry = {"timestamp": time.strftime("%H:%M:%S"), "message": message, "level": level}
        self.logs.insert(0, entry)
        if len(self.logs) > 100:
            self.logs.pop()
        try:
            log_event(message, level)
        except Exception:
            pass
        try:
            print(f"[{entry['timestamp']}] [{level}] {message}")
        except Exception:
            try:
                safe_msg = message.encode("ascii", "replace").decode("ascii")
                print(f"[{entry['timestamp']}] [{level}] {safe_msg}")
            except Exception:
                pass

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_running": self.is_running,
            "status": self.status,
            "current_job": self.current_job,
            "countdown_remaining": self.countdown_remaining,
            "today_applied": self.today_applied,
            "daily_limit": self.daily_limit,
            "platform_quotas": self.platform_quotas,
            "platform_applied": self.platform_applied,
            "last_error": self.last_error,
            "recent_logs": self.logs[:60],
            "config": self.config.to_dict(),
            "last_search_diagnostics": self.last_search_diagnostics
        }

bot_state = BotState()

def human_sleep(min_sec: float, max_sec: float, stop_event: threading.Event):
    """Sleeps with random jitter while respecting user stop request."""
    duration = random.uniform(min_sec, max_sec)
    start = time.time()
    while time.time() - start < duration:
        if stop_event and stop_event.is_set():
            break
        time.sleep(0.5)

def cooldown_timer(min_sec: int = None, max_sec: int = None, stop_event: threading.Event = None, reason: str = ""):
    """
    Mandatory safety cooldown: Configurable duration between applications.
    Updates bot_state.countdown_remaining every second so Next.js UI shows real-time countdown.
    Aborts immediately when stop_event is set.
    """
    if min_sec is None:
        min_sec = bot_state.config.cooldown_min_sec
    if max_sec is None:
        max_sec = bot_state.config.cooldown_max_sec
    if min_sec <= 0:
        return

    break_seconds = random.randint(min_sec, max(min_sec, max_sec))
    bot_state.status = "COOLDOWN"
    reason_label = f" ({reason})" if reason else ""
    bot_state.add_log(f"🛡️ Anti-Ban Cooldown: Taking a safe {break_seconds}s pause{reason_label}.", "INFO")
    
    for remaining in range(break_seconds, 0, -1):
        if stop_event and stop_event.is_set():
            bot_state.add_log("Cooldown cancelled by user stop request.", "WARNING")
            break
        bot_state.countdown_remaining = remaining
        time.sleep(1)
        
    bot_state.countdown_remaining = 0

def safe_bring_to_front(pg):
    """Safely brings a Playwright Page to front without raising exceptions if page is closed."""
    try:
        if pg and not pg.is_closed():
            pg.bring_to_front()
    except Exception:
        pass

def find_submit_button(page):
    """
    Safely locates a visible and enabled submit/save/apply button on a page or modal:
    - Supports 'Save and Apply', 'Save & Apply', 'Submit Application', 'Submit', 'Send Application', 'Send', 'Apply Now', 'Apply', 'Continue'.
    - Checks input[type='submit'].
    - Considers accessible names, button text, and aria-labels.
    - Avoids false positives (rejects filter, search, cancel, close, reject buttons).
    - Checks visibility and enabled state.
    """
    submit_terms = [
        "save",
        "save and apply",
        "save & apply",
        "submit application",
        "send application",
        "complete application",
        "submit",
        "send",
        "apply now",
        "apply for this job",
        "apply",
        "continue",
        "next"
    ]
    unrelated_terms = ["filter", "search", "cancel", "close", "reject", "dismiss", "edit", "back", "clear", "save-job", "save job", "bookmark"]

    # 1. Try role='button' with exact or regex accessible names via Playwright get_by_role
    for term in submit_terms:
        try:
            loc = page.get_by_role("button", name=re.compile(rf"^\s*{re.escape(term)}\s*$", re.IGNORECASE))
            count = loc.count()
            for i in range(count):
                btn = loc.nth(i)
                if btn.is_visible() and btn.is_enabled():
                    btn_cls = (btn.get_attribute("class") or "").lower()
                    if any(u in btn_cls for u in ["save-job", "bookmark", "styles_save-job"]):
                        continue
                    return btn
        except Exception:
            pass

    # 2. Try input[type='submit']
    try:
        sub_inputs = page.locator("input[type='submit']")
        for i in range(sub_inputs.count()):
            sub_inp = sub_inputs.nth(i)
            if sub_inp.is_visible() and sub_inp.is_enabled():
                val = (sub_inp.get_attribute("value") or "").lower()
                if not any(un in val for un in unrelated_terms):
                    return sub_inp
    except Exception:
        pass

    # 3. Query candidate elements via standard CSS selectors (no pseudo-classes)
    candidate_selectors = [
        "button[type='submit']",
        "button.save-btn",
        "button[class*='save']",
        "button.send-btn",
        "button.apply-btn",
        "button.submit-btn",
        ".sendBtn",
        ".send-icon",
        "button[aria-label*='Save' i]",
        "button[aria-label*='Send' i]",
        "button[aria-label*='Submit' i]",
        "button[aria-label*='Apply' i]",
        "button",
        "[role='button']",
        "a.btn",
        "a.button"
    ]
    
    for sel in candidate_selectors:
        try:
            elements = page.query_selector_all(sel)
            for el in elements:
                try:
                    if not el.is_visible() or not el.is_enabled():
                        continue
                    
                    btn_cls = (el.get_attribute("class") or "").lower()
                    if any(u in btn_cls for u in ["save-job", "bookmark", "styles_save-job"]):
                        continue

                    meta = page.evaluate("""(e) => {
                        return {
                            text: (e.innerText || e.textContent || e.value || '').trim(),
                            aria: (e.getAttribute('aria-label') || '').trim()
                        };
                    }""", el)
                    
                    combined = f"{meta.get('text', '')} {meta.get('aria', '')}".lower()
                    if not combined:
                        continue
                    
                    if any(un in combined for un in unrelated_terms):
                        continue
                    
                    for term in submit_terms:
                        if term in combined:
                            return el
                except Exception:
                    continue
        except Exception:
            pass

    return None

def detect_naukri_action_button(page):
    """
    Inspects a Naukri job details page to accurately determine the application mechanism:
    Returns (action_type, element_or_locator)
    action_type can be:
      - 'ALREADY_APPLIED'
      - 'LOGIN_REQUIRED'
      - 'COMPANY_SITE'
      - 'DIRECT_APPLY'
      - None (if no action button is detected)
    """
    # 0. Check for Apply Confirmation URL/Title (e.g. saveApply or ACP)
    if page and not page.is_closed():
        try:
            url = (page.url or "").lower()
            title = (page.title() or "").lower()
            if "saveapply" in url or "myapply" in url or "apply confirmation" in title:
                return ("ALREADY_APPLIED", None)
        except Exception:
            pass

    # 1. Check for Already Applied indicator
    already_applied_locators = [
        "button:has-text('Applied')",
        "span:has-text('Applied')",
        "a:has-text('Applied')",
        "#already-applied",
        "span#already-applied",
        "button#already-applied",
        "a#already-applied",
        ".applied-badge",
        ".already-applied",
        "div:has-text('already applied')",
        "a:has-text('already applied')",
        "div:has-text('Applied to')",
        "div:has-text('Applied on')",
        "p:has-text('Applied on')",
        "span:has-text('Applied on')",
        "div[class*='already-applied']",
        "span[class*='already-applied']",
        "div[class*='apply-button-container']:has-text('Applied')",
        ".acp-container",
        ".acp-header-container"
    ]
    for sel in already_applied_locators:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                txt = (el.inner_text() or "").lower()
                if "applied" in txt or "already-applied" in sel or "acp-" in sel:
                    return ("ALREADY_APPLIED", el)
        except Exception:
            pass

    # 2. Check for Login Required
    login_locators = [
        "a:has-text('Login to apply')",
        "button:has-text('Login to apply')",
        "button:has-text('Register to apply')",
        "a:has-text('Register to apply')"
    ]
    for sel in login_locators:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                return ("LOGIN_REQUIRED", el)
        except Exception:
            pass

    # 3. Check for Apply on Company Site
    company_site_locators = [
        "button:has-text('Apply on company site')",
        "a:has-text('Apply on company site')",
        "button:has-text('Apply on employer site')",
        "a:has-text('Apply on employer site')",
        "button:has-text('Apply on company website')",
        "a:has-text('Apply on company website')",
        "button:has-text('company site')",
        "a:has-text('company site')",
        "button:has-text('Company Website')",
        "a:has-text('Company Website')",
        "button:has-text('Apply on company')",
        "a:has-text('Apply on company')",
        "#company-site-button",
        ".company-site-button"
    ]
    for sel in company_site_locators:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible() and el.is_enabled():
                return ("COMPANY_SITE", el)
        except Exception:
            pass

    # Also check if any button or link has external URL
    try:
        candidate_links = page.query_selector_all("a.apply-button, button.apply-button, #apply-button, a[class*='apply']")
        for link in candidate_links:
            if not link.is_visible() or not link.is_enabled():
                continue
            href = link.get_attribute("href") or ""
            txt = (link.inner_text() or "").lower()
            if any(term in txt for term in ["company", "employer", "external"]) or (href.startswith("http") and "naukri.com" not in href):
                return ("COMPANY_SITE", link)
    except Exception:
        pass

    # 4. Check for Direct Apply on Naukri
    direct_apply_locators = [
        "#apply-button",
        "button.apply-button",
        "button:has-text('Apply')",
        "a.apply-button",
        "a:has-text('Apply')",
        "button:has-text('Apply Now')",
        "a:has-text('Apply Now')"
    ]
    for sel in direct_apply_locators:
        try:
            elements = page.query_selector_all(sel)
            for el in elements:
                if not el.is_visible() or not el.is_enabled():
                    continue
                txt = (el.inner_text() or "").strip().lower()
                # Exclude unrelated buttons (filter, search, etc.)
                if any(bad in txt for bad in ["filter", "search", "cancel", "company", "employer", "website"]):
                    continue
                if "apply" in txt or el.get_attribute("id") == "apply-button" or "apply-button" in (el.get_attribute("class") or ""):
                    return ("DIRECT_APPLY", el)
        except Exception:
            pass

    return (None, None)

def visual_human_type(target_page, element, text: str, stop_event: threading.Event, field_name: str = ""):
    """
    100% Human-like Typing at authentic ~40 WPM:
    - Brings page to front
    - Scrolls element into view
    - Hovers mouse over element like a human
    - Clicks element to focus
    - Visually highlights input box with a glowing teal/green border
    - Clears input and types character-by-character with 40 WPM keystroke pacing (120-190ms) & natural word pauses
    """
    try:
        target_page.bring_to_front()
        element.scroll_into_view_if_needed()
        time.sleep(0.3)
        element.hover()
        time.sleep(0.2)
        
        # Visual glowing green outline around input box
        target_page.evaluate("""(el) => {
            el.style.outline = '3px solid #14b8a6';
            el.style.boxShadow = '0 0 14px rgba(20, 184, 166, 0.85)';
            el.style.backgroundColor = 'rgba(20, 184, 166, 0.08)';
            el.style.transition = 'all 0.2s ease-in-out';
        }""", element)
        time.sleep(0.25)
        element.click()
        time.sleep(0.2)
        
        if field_name:
            bot_state.add_log(f"✍️ [Typing] {field_name}: '{text}'", "INFO")
            
        element.fill(str(text))
        time.sleep(0.2)
        # Dispatch React input & change events
        target_page.evaluate("""(el) => {
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        }""", element)
        time.sleep(0.3)
        # Reset glow
        target_page.evaluate("""(el) => {
            el.style.outline = '1px solid #10b981';
            el.style.boxShadow = '';
            el.style.backgroundColor = '';
        }""", element)
    except Exception as e:
        try:
            element.fill(str(text))
        except Exception:
            pass

def fill_company_form(target_page, stop_event: threading.Event, target_role: str = "", company_name: str = "", location_hint: str = ""):
    """
    Visually autofills comprehensive application fields on company portals like a real human:
    - Auto-attaches user's PDF resume file (Abdul_Razzaque_India.pdf) to file inputs
    - Uses form_engine and qa_engine to detect, understand, answer, and validate all form fields:
      - Experience (5+ years), Notice (Immediate Joiner / 0-15 / 30 days), Currency (INR), Frequency (Yearly), Degree (BSc Computer Science)
      - Radio buttons, custom comboboxes, autocomplete, checkboxes, textareas
    - Never fabricates unknown credentials or mandatory answers; returns NEEDS_USER_INPUT and keeps tab open.
    """
    profile = get_candidate_profile()

    # Centralized Country-Based Candidate Profile
    cand_prof = getCandidateProfileByJobLocation(location_hint)
    resume_path = cand_prof.get("resume_path") or ""
    if not resume_path or not os.path.exists(resume_path):
        target_res = cand_prof.get("resume_filename", "Abdul_Razzaque_India.pdf")
        candidate_paths = [
            os.path.join(os.path.dirname(__file__), target_res),
            os.path.join(os.path.dirname(__file__), "Abdul_Razzaque_India.pdf"),
            os.path.join(os.path.dirname(__file__), "Abdul_Razzaque_Qatar.pdf"),
            r"E:\Abdur Razzaque\Abdur Razzaque Both\Abdul Razzaque Qatar.pdf",
            r"E:\Abdur Razzaque\Abdur Razzaque Both\Abdul Razzaque India.pdf"
        ]
        for cp in candidate_paths:
            if os.path.exists(cp):
                resume_path = cp
                break

    # 0. Safety boundary check: Payment / fee field detection
    payment_detected = False
    try:
        payment_detected = target_page.evaluate("""() => {
            const text = (document.body ? document.body.innerText : '').toLowerCase();
            const paymentPhrases = ['credit card', 'debit card', 'card number', 'cvv', 'cvc', 'application fee', 'processing fee', 'payment method', 'pay now', 'enter payment details', 'subscription fee'];
            const hasText = paymentPhrases.some(p => text.includes(p));
            const hasCardInp = !!document.querySelector('input[name*="card" i], input[name*="cvv" i], input[autocomplete*="cc-" i], iframe[src*="stripe" i], iframe[src*="paypal" i], iframe[src*="razorpay" i]');
            return hasText && hasCardInp;
        }""")
    except Exception:
        pass

    if payment_detected:
        bot_state.add_log("🚨 Payment or paid transaction requested on form. Blocked by safety boundary!", "ERROR")
        return {"success": False, "needs_user_input": False, "is_payment": True, "reason": "PAYMENT_BLOCKED"}

    # PASS 1: Auto-upload Resume file input (if authorized)
    if agent_config_manager.is_authorized("auto_upload_resume"):
        try:
            file_inputs = target_page.query_selector_all("input[type='file']")
            for finp in file_inputs:
                if stop_event.is_set():
                    break
                if resume_path and os.path.exists(resume_path):
                    try:
                        finp.set_input_files(resume_path)
                        bot_state.add_log(f"📎 Auto-attached candidate resume: {os.path.basename(resume_path)}", "SUCCESS")
                        human_sleep(0.5, 1.0, stop_event)
                    except Exception as e:
                        bot_state.add_log(f"Resume upload notice: {e}", "WARNING")
        except Exception:
            pass
    else:
        bot_state.add_log("Resume auto-upload disabled by agentConfig permissions.", "INFO")

    # PASS 2: Intelligent Question Detection, Understanding & Answering
    bot_state.add_log(f"📋 Running intelligent form detection & filling on {company_name or 'company portal'}...", "INFO")
    form_res = process_and_fill_complete_form(
        page=target_page,
        qa_engine_instance=qa_engine,
        stop_event=stop_event,
        company_name=company_name,
        job_title=target_role,
        logger_fn=bot_state.add_log,
        location_hint=location_hint
    )

    if form_res.get("status") == "NEEDS_USER_INPUT":
        target_page.bring_to_front()
        return {
            "success": False,
            "needs_user_input": True,
            "is_payment": False,
            "reason": form_res.get("reason", "NEEDS_USER_INPUT"),
            "unanswered_question": form_res.get("unanswered_question", "")
        }

    if form_res.get("status") == "FORM_VALIDATED":
        return {"success": True, "needs_user_input": False, "is_payment": False, "reason": "FORM_VALIDATED"}

    return {
        "success": form_res.get("success", False),
        "needs_user_input": False,
        "is_payment": False,
        "reason": form_res.get("reason", "")
    }


def handle_naukri_screening_drawer(detail_tab, stop_event: threading.Event, company: str = "", title: str = ""):
    """
    Handles Naukri's screening questionnaire drawer, chatbot popup, or screening modal:
    1. Dedicated NaukriChatPanelHandler detects chat-style drawer, extracts questions from chat bubbles,
       enters answers, verifies retention, and clicks the scoped Save button.
    2. Handles sequential questions in a loop with infinite-loop prevention.
    3. Supports quick-reply chips and multi-question form modals.
    4. NEVER closes tab or abandons form when unfamiliar questions are encountered; surfaces NEEDS_USER_INPUT.
    """
    human_sleep(1.2, 2.0, stop_event)

    # 0. Check authorization
    if not agent_config_manager.is_authorized("auto_answer_screening"):
        bot_state.add_log("Screening drawer detected, but auto_answer_screening is disabled by config. Tab kept OPEN for review.", "INFO")
        return {"status": ApplicationStatus.APPLICATION_PENDING_CONFIRMATION, "reason": "AUTO_ANSWER_SCREENING_NOT_AUTHORIZED"}

    # 0.1 Check if application was already confirmed (e.g. 1-click apply navigated to saveApply or ACP)
    is_conf, conf_reason = is_naukri_application_confirmed(detail_tab)
    if is_conf:
        return {"status": ApplicationStatus.APPLICATION_CONFIRMED, "success": True, "reason": conf_reason}

    # 1. PRIORITY: Check for Dedicated Right-Side Chat Panel (Naukri chatbot / screening drawer)
    chat_panel = naukri_chat_panel_handler.detect_chat_panel(detail_tab)
    if chat_panel and chat_panel.is_visible():
        bot_state.add_log(f"💬 Dedicated Naukri Chat Panel detected for {company}. Launching autonomous chat handler...", "INFO")
        bot_state.current_job["stage"] = ApplicationStatus.QUESTION_DETECTED
        chat_res = naukri_chat_panel_handler.process_sequential_chat_questions(
            page=detail_tab,
            qa_engine_instance=qa_engine,
            stop_event=stop_event,
            company=company,
            title=title
        )
        if chat_res.get("status") == ChatPanelState.NEEDS_USER_INPUT:
            bot_state.current_job["stage"] = ApplicationStatus.NEEDS_USER_INPUT
        elif chat_res.get("status") in [ChatPanelState.FORM_COMPLETED, ChatPanelState.APPLICATION_CONFIRMED]:
            bot_state.current_job["stage"] = ApplicationStatus.FORM_VALIDATED
        return chat_res
    
    for round_idx in range(6):
        if stop_event.is_set():
            break

        # Check if drawer, modal, or chatbot container is present
        container = detail_tab.query_selector("""
            .chatbot_drawer, 
            .drawer-wrapper, 
            .bot-container, 
            .apply-message,
            div[class*='chatbot'],
            div[class*='drawer'],
            div[class*='applyDrawer'],
            div[class*='chatContent'],
            div[class*='apply-modal'],
            div[class*='applyModal'],
            div[class*='screening'],
            div[class*='questionnaire'],
            div[class*='custom-questions'],
            div[role='dialog'],
            .apply-dialog,
            .modal-content
        """)
        
        has_screening_elements = False
        try:
            has_screening_elements = detail_tab.evaluate("""() => {
                const hasChips = Array.from(document.querySelectorAll('.chip, .botOption, button.option-btn, div.quick-reply, span.chip, .chat-chip, .option, button[class*="chip"], div[class*="chip"]')).some(el => el.offsetParent !== null);
                const hasChatInp = Array.from(document.querySelectorAll('input[placeholder*="Type" i], textarea[placeholder*="Type" i], input.chat-input, .user-input input, div[class*="chatInput"] input')).some(el => el.offsetParent !== null && !el.disabled);
                const submitTerms = ['save and apply', 'save & apply', 'submit application', 'send application', 'submit', 'send', 'continue', 'apply now'];
                const hasSubmit = Array.from(document.querySelectorAll('button, input[type="submit"], [role="button"], a.btn, a.button')).some(b => {
                    if (b.offsetParent === null || b.disabled) return false;
                    const txt = (b.innerText || b.value || b.getAttribute('aria-label') || '').toLowerCase().trim();
                    return submitTerms.some(term => txt.includes(term));
                });
                const hasInputs = Array.from(document.querySelectorAll('input:not([type="hidden"]), select, textarea')).some(el => el.offsetParent !== null && !el.disabled);
                return hasChips || hasChatInp || hasSubmit || hasInputs;
            }""")
        except Exception:
            has_screening_elements = False

        if not container and not has_screening_elements:
            break

        detail_tab.bring_to_front()
        bot_state.add_log(f"📋 Answering screening questions in Naukri drawer for {company} (Round {round_idx+1})...", "INFO")
        action_taken = False

        # --- STEP A: QUICK-REPLY CHIPS / BUTTONS IN CHATBOT ---
        chips = detail_tab.query_selector_all(".chip, .botOption, button.option-btn, div.quick-reply, span.chip, .chat-chip, .option, button[class*='chip'], div[class*='chip']")
        for chip in chips:
            try:
                if chip.is_visible():
                    chip_txt = chip.inner_text().strip().lower()
                    if not chip_txt:
                        continue
                    
                    # Notice Period Chips (Prioritize Immediate Joiner)
                    if any(k in chip_txt for k in ['immediate', '0-15', '15 day', 'less than 15', 'serving', '15', '30 day', '1 month', '30']):
                        bot_state.add_log(f"Question: Notice Period | Option clicked: '{chip.inner_text().strip()}' (Source: CANDIDATE_PROFILE)", "INFO")
                        chip.click()
                        action_taken = True
                        human_sleep(1.2, 2.0, stop_event)
                        break

                    # Experience Chips (5+ years)
                    elif any(k in chip_txt for k in ['5+ year', '5+ years', '5 years', '5 year', '5-7', '4-6', '5+', '5']):
                        bot_state.add_log(f"Question: Experience | Option clicked: '{chip.inner_text().strip()}' (Source: CANDIDATE_PROFILE)", "INFO")
                        chip.click()
                        action_taken = True
                        human_sleep(1.2, 2.0, stop_event)
                        break

                    # Location / Relocate Chips
                    elif any(k in chip_txt for k in ['mumbai', 'kurla', 'remote', 'open to relocate', 'relocate', 'onsite', 'hybrid']):
                        bot_state.add_log(f"Question: Location | Option clicked: '{chip.inner_text().strip()}' (Source: CANDIDATE_PROFILE)", "INFO")
                        chip.click()
                        action_taken = True
                        human_sleep(1.2, 2.0, stop_event)
                        break

                    # Affirmative / Yes Chips
                    elif any(chip_txt.startswith(y) or chip_txt == y for y in ['yes', 'agree', 'confirm', 'comfortable', 'available', 'i agree']):
                        bot_state.add_log(f"Question: Affirmative | Option clicked: '{chip.inner_text().strip()}' (Source: DETERMINISTIC_RULE)", "INFO")
                        chip.click()
                        action_taken = True
                        human_sleep(1.2, 2.0, stop_event)
                        break
            except Exception:
                pass

        if action_taken:
            continue

        if not agent_config_manager.is_authorized("auto_answer_screening"):
            bot_state.add_log("Screening drawer detected, but auto_answer_screening is disabled by config. Tab kept OPEN for review.", "INFO")
            return {"status": ApplicationStatus.APPLICATION_PENDING_CONFIRMATION, "reason": "AUTO_ANSWER_SCREENING_NOT_AUTHORIZED"}

        # --- Check if chat panel / screening drawer is active in this round ---
        chat_p = naukri_chat_panel_handler.detect_chat_panel(detail_tab)
        if chat_p and chat_p.is_visible():
            bot_state.add_log(f"💬 Active Naukri Chat Panel detected for {company}. Processing chat questions...", "INFO")
            chat_res = naukri_chat_panel_handler.process_sequential_chat_questions(
                page=detail_tab,
                qa_engine_instance=qa_engine,
                stop_event=stop_event,
                company=company,
                title=title
            )
            if chat_res.get("status") == ChatPanelState.NEEDS_USER_INPUT:
                bot_state.current_job["stage"] = ApplicationStatus.NEEDS_USER_INPUT
            elif chat_res.get("status") in [ChatPanelState.FORM_COMPLETED, ChatPanelState.APPLICATION_CONFIRMED]:
                bot_state.current_job["stage"] = ApplicationStatus.FORM_VALIDATED
            return chat_res

        # --- STEP B: MULTI-QUESTION FORM / MODAL FIELDS (via form_engine) ---
        detected_questions = detect_and_collect_form_questions(detail_tab)
        if detected_questions:
            bot_state.current_job["stage"] = ApplicationStatus.QUESTIONS_DETECTED
            bot_state.current_job["stage"] = ApplicationStatus.ANSWERS_GENERATED
            bot_state.current_job["stage"] = ApplicationStatus.FORM_FILLED
            
            form_res = process_and_fill_complete_form(
                page=detail_tab,
                qa_engine_instance=qa_engine,
                stop_event=stop_event,
                company_name=company,
                job_title=title,
                logger_fn=bot_state.add_log
            )
            
            if form_res.get("status") == "NEEDS_USER_INPUT":
                bot_state.current_job["stage"] = ApplicationStatus.NEEDS_USER_INPUT
                detail_tab.bring_to_front()
                return {
                    "status": ApplicationStatus.NEEDS_USER_INPUT,
                    "reason": form_res.get("reason", "NEEDS_USER_INPUT"),
                    "unanswered_question": form_res.get("unanswered_question", "")
                }
            elif form_res.get("status") == "FORM_VALIDATED":
                bot_state.current_job["stage"] = ApplicationStatus.FORM_VALIDATED
                action_taken = True

        # --- STEP C: CHATBOT INPUT WITH SEND BUTTON ---
        chat_inp = detail_tab.query_selector("""
            input[placeholder*='Type'], 
            textarea[placeholder*='Type'], 
            input.chat-input, 
            .user-input input, 
            div[class*='chatInput'] input,
            div[class*='chatbot'] input[type='text'],
            div[class*='chatbot'] input[type='number'],
            div[class*='drawer'] input[type='text'],
            div[class*='drawer'] input[type='number']
        """)

        if chat_inp and chat_inp.is_visible():
            latest_q = detail_tab.evaluate("""() => {
                const msgs = Array.from(document.querySelectorAll('.botMsg, div[class*="botMsg"], div[class*="chatMsg"], div[class*="msg"], .bot-row, p.msg, label'))
                    .filter(el => el.offsetParent !== null && el.innerText.trim().length > 3);
                return msgs.length > 0 ? msgs[msgs.length - 1].innerText.trim() : 'Screening Question';
            }""")

            res = qa_engine.process_question(
                question_text=latest_q,
                input_type=chat_inp.get_attribute("type") or "text",
                job_title=title,
                company_name=company
            )
            bot_state.add_log(f"Question: '{latest_q[:40]}' | Category: {res.get('category')} | Source: {res.get('source')}", "INFO")

            if res.get("needs_user_input"):
                bot_state.current_job["stage"] = ApplicationStatus.NEEDS_USER_INPUT
                bot_state.add_log(f"⚠️ [NEEDS_USER_INPUT] Screening chatbot question requires candidate verification: '{latest_q[:35]}' ({res.get('reason')}). Tab kept OPEN in Chrome.", "WARNING")
                detail_tab.bring_to_front()
                return {
                    "status": ApplicationStatus.NEEDS_USER_INPUT, 
                    "reason": res.get("reason", "NEEDS_USER_INPUT"),
                    "unanswered_question": latest_q
                }

            ans = res.get("answer", "")
            visual_human_type(detail_tab, chat_inp, ans, stop_event, field_name=latest_q[:25])
            action_taken = True

            # Click send button or press Enter
            send_btn = detail_tab.query_selector("""
                button.send-btn, 
                button:has-text('Send'), 
                .sendBtn, 
                .send-icon, 
                button[class*='send'], 
                button[aria-label*='Send'],
                span[class*='send']
            """)
            if send_btn and send_btn.is_visible():
                send_btn.click()
            else:
                try:
                    chat_inp.press("Enter")
                except Exception:
                    pass
            human_sleep(1.8, 2.8, stop_event)
            continue

        # --- STEP D: SUBMIT / SAVE AND APPLY / NEXT BUTTON ---
        sub_btn = find_submit_button(detail_tab)
        if sub_btn:
            try:
                is_vis = sub_btn.is_visible() if hasattr(sub_btn, 'is_visible') else True
                if is_vis:
                    if not agent_config_manager.is_authorized("auto_submit_direct"):
                        bot_state.add_log("Screening completed, but auto_submit_direct is disabled in config. Tab kept OPEN for review.", "INFO")
                        return {"status": ApplicationStatus.APPLICATION_PENDING_CONFIRMATION, "reason": "AUTO_SUBMIT_DIRECT_NOT_AUTHORIZED"}

                    bot_state.add_log(f"Clicking Submit/Save button in screening questionnaire for {company}...", "INFO")
                    sub_btn.scroll_into_view_if_needed()
                    time.sleep(0.3)
                    sub_btn.click()
                    action_taken = True
                    human_sleep(2.0, 3.5, stop_event)
            except Exception as e:
                bot_state.add_log(f"Notice while clicking submit button in drawer: {e}", "WARNING")

        if not action_taken:
            break


def handle_external_company_portal(context, detail_tab, company_tab, title: str, company: str, 
                                   loc_text: str, exp_text: str, score: int, 
                                   stop_event: threading.Event,
                                   tailored_resume_path: str = "",
                                   original_job_url: str = "",
                                   platform: str = "NAUKRI",
                                   requested_location: str = "",
                                   actual_browser_location: str = "") -> Dict[str, Any]:
    """
    Handles applications on external company career portals using the full 12-stage ExternalApplyEngine:
    - Verifies external job title & company (prevents 404/expired/mismatch)
    - Detects & reveals application form controls
    - Fills verified candidate details grounded in profile
    - Uploads tailored/verified PDF resume
    - Validates entire form pre-submission
    - Detects CAPTCHA / Login and keeps tab open safely
    - Submits and verifies confirmation
    """
    from external_apply_engine import ExternalApplyEngine
    engine = ExternalApplyEngine(bot_state=bot_state)
    result = engine.execute_external_application(
        context=context,
        detail_tab=detail_tab,
        company_tab=company_tab,
        title=title,
        company=company,
        loc_text=loc_text,
        exp_text=exp_text,
        score=score,
        tailored_resume_path=tailored_resume_path,
        original_job_url=original_job_url or (detail_tab.url if detail_tab else ""),
        platform=platform,
        stop_event=stop_event,
        requested_location=requested_location,
        actual_browser_location=actual_browser_location
    )
    if result.get("status") == "APPLICATION_CONFIRMED":
        bot_state.today_applied = get_today_applied_count()
        cooldown_timer(min_sec=bot_state.config.cooldown_min_sec, max_sec=bot_state.config.cooldown_max_sec, stop_event=stop_event, reason=f"Confirmed company website submission for {company}")
    else:
        cooldown_timer(min_sec=bot_state.config.unconfirmed_cooldown_min_sec, max_sec=bot_state.config.unconfirmed_cooldown_max_sec, stop_event=stop_event, reason=f"Safety pause for {company}")
    return result

def process_job_application(context, search_page, title: str, company: str, loc_text: str, exp_text: str, job_url: str, score: int, stop_event: threading.Event) -> Dict[str, Any]:
    """
    Unified Application Engine:
    1. Opens dedicated job details page in a fresh tab.
    2. Accurately determines if job is 'Apply on Company Site' or 'Direct Naukri Apply'.
    3. Handles new tabs, popups, and redirects (e.g. Capgemini external career portal link).
    4. Handles screening questions, verification, and reliable confirmation polling.
    5. Applies consistent safety cooldowns (distinguishing confirmed vs unconfirmed attempts vs inspected-only).
    6. Respects user stop request at every stage.
    """
    bot_state.status = "APPLYING"
    detail_tab = None
    company_tab = None

    if stop_event and stop_event.is_set():
        return {"status": ApplicationStatus.APPLICATION_SKIPPED, "success": False, "failure_reason": "STOP_REQUESTED", "attempted": False}

    if check_already_applied_db(title=title, company=company, job_url=job_url):
        bot_state.add_log(f"🔁 Job {title} @ {company} already applied or skipped in DB. Skipping.", "INFO")
        return {"status": ApplicationStatus.APPLICATION_SKIPPED, "success": False, "failure_reason": "DUPLICATE_JOB", "attempted": False}

    if not agent_config_manager.is_authorized("auto_inspect_jobs"):
        bot_state.add_log(f"auto_inspect_jobs disabled in agent config. Skipping inspection of {company}.", "INFO")
        return {"status": ApplicationStatus.APPLICATION_SKIPPED, "success": False, "failure_reason": "INSPECT_NOT_AUTHORIZED", "attempted": False}

    try:
        # Step 1: Format URL and open in new tab
        if not job_url or "http" not in job_url:
            if job_url and job_url.startswith("/"):
                full_job_url = f"https://www.naukri.com{job_url}"
            else:
                full_job_url = f"https://www.naukri.com/{job_url}" if job_url else search_page.url
        else:
            full_job_url = job_url

        bot_state.current_job["stage"] = ApplicationStatus.JOB_DETAILS_OPENED
        bot_state.add_log(f"📄 Opening job details tab for {title} @ {company}...", "INFO")
        detail_tab = context.new_page()
        safe_bring_to_front(detail_tab)

        # Handle dialog popups automatically so browser never hangs
        try:
            detail_tab.on("dialog", lambda d: d.dismiss())
        except Exception:
            pass

        retry_cfg = agent_config_manager.get_config().get("retry_policy", {"max_retries": 2, "retry_delay_sec": 5})
        max_retries = int(retry_cfg.get("max_retries", 2))
        delay_sec = int(retry_cfg.get("retry_delay_sec", 5))

        nav_success = False
        last_nav_err = None
        for nav_attempt in range(max_retries + 1):
            if stop_event and stop_event.is_set():
                break
            try:
                detail_tab.goto(full_job_url, wait_until="domcontentloaded", timeout=30000)
                nav_success = True
                human_sleep(2.5, 4.0, stop_event)
                break
            except Exception as nav_e:
                last_nav_err = nav_e
                if nav_attempt < max_retries and not (stop_event and stop_event.is_set()):
                    bot_state.add_log(f"Navigation retry {nav_attempt+1}/{max_retries} for {company} in {delay_sec}s...", "WARNING")
                    human_sleep(delay_sec, delay_sec + 0.5, stop_event)
                else:
                    bot_state.add_log(f"Could not load job details page: {nav_e}", "WARNING")

        if not nav_success:
            if detail_tab and not detail_tab.is_closed():
                detail_tab.close()
            return {"status": ApplicationStatus.APPLICATION_FAILED, "success": False, "failure_reason": f"NAV_FAILED: {last_nav_err}", "attempted": False}

        if stop_event and stop_event.is_set():
            if detail_tab and not detail_tab.is_closed():
                detail_tab.close()
            return {"status": ApplicationStatus.APPLICATION_SKIPPED, "success": False, "failure_reason": "STOP_REQUESTED", "attempted": False}

        # If landed on Gulf, abort only if NOT targeting Qatar/Gulf
        is_qatar_dest = any(k in f"{loc_text} {title} {company}".lower() for k in ["qatar", "doha", "gcc"])
        if "naukrigulf" in detail_tab.url.lower() and not is_qatar_dest:
            bot_state.add_log(f"Gulf URL detected on {company}. Non-Qatar target. Closing tab.", "WARNING")
            record_application(
                job_title=title, company_name=company, location=loc_text, job_url=full_job_url,
                status=ApplicationStatus.APPLICATION_SKIPPED, apply_type='DIRECT_NAUKRI', match_score=score,
                notes="Excluded: NaukriGulf regional posting.", failure_reason="GULF_REGION_EXCLUDED",
                experience_req=exp_text, platform="NAUKRI"
            )
            detail_tab.close()
            return {"status": ApplicationStatus.APPLICATION_SKIPPED, "success": False, "failure_reason": "GULF_REGION_EXCLUDED", "attempted": False}

        # Step 1.5: Master Prompt Section 2 & 3: Deep JD Analysis & Resume Optimization
        jd_text = ""
        try:
            jd_el = detail_tab.query_selector(".styles_JDC__dang-inner-html__73O4f, .job-desc-wrap, .dang-inner-html, section.job-desc, article")
            if jd_el:
                jd_text = jd_el.inner_text().strip()
        except Exception:
            pass
        if not jd_text:
            jd_text = f"{title} at {company} in {loc_text}. Experience: {exp_text}"

        from resume_optimizer import analyze_job_description, resume_optimizer, generate_activity_report
        jd_analysis = analyze_job_description(
            job_title=title, company=company, job_desc=jd_text, location=loc_text, job_url=full_job_url, platform="NAUKRI"
        )

        # SCENARIO C: Strict Disqualification Check
        if not jd_analysis.should_apply:
            bot_state.add_log(f"🛑 [Incompatible Role Disqualified] {title} @ {company}: {jd_analysis.disqualification_reason}", "WARNING")
            skip_rep = generate_activity_report(
                jd_analysis=jd_analysis,
                optimization_res={"success": False, "customized_path": "", "original_path": ""},
                application_status="Skipped (Incompatible Role)",
                error_msg=jd_analysis.disqualification_reason
            )
            bot_state.add_log(f"📋 Application Report:\n{skip_rep}", "INFO")
            record_application(
                job_title=title, company_name=company, location=loc_text, job_url=full_job_url,
                status=ApplicationStatus.APPLICATION_SKIPPED, apply_type='DIRECT_NAUKRI',
                match_score=jd_analysis.match_score,
                notes=f"Skipped: {jd_analysis.disqualification_reason}",
                failure_reason=jd_analysis.disqualification_reason,
                experience_req=exp_text, platform="NAUKRI",
                jd_match_analysis_json=json.dumps(jd_analysis.to_dict())
            )
            detail_tab.close()
            return {"status": ApplicationStatus.APPLICATION_SKIPPED, "success": False, "failure_reason": jd_analysis.disqualification_reason, "attempted": False}

        opt_res = resume_optimizer.optimize_resume(jd_analysis, is_india=True)
        custom_pdf = opt_res.get("customized_path") if opt_res.get("success") else resume_optimizer.get_base_resume(is_india=True)
        if opt_res.get("success"):
            bot_state.add_log(f"📄 [Resume Optimized] Generated tailored CV: {os.path.basename(custom_pdf)} (Match: {jd_analysis.match_score}%)", "SUCCESS")

        # Step 2: Locate Action Button (detect_naukri_action_button)
        action_type, action_btn = detect_naukri_action_button(detail_tab)

        # ALREADY APPLIED
        if action_type == "ALREADY_APPLIED":
            bot_state.add_log(f"ℹ️ Already applied to {title} @ {company} according to Naukri. Skipping.", "INFO")
            record_application(
                job_title=title, company_name=company, location=loc_text, job_url=full_job_url,
                status=ApplicationStatus.APPLICATION_CONFIRMED, apply_type='DIRECT_NAUKRI', match_score=score,
                notes="Already applied according to Naukri.", experience_req=exp_text
            )
            detail_tab.close()
            return {"status": ApplicationStatus.APPLICATION_CONFIRMED, "success": True, "failure_reason": "", "attempted": False}

        # LOGIN REQUIRED
        if action_type == "LOGIN_REQUIRED":
            bot_state.add_log(f"🔒 Login required for {company}. Please log in to Naukri in Chrome.", "WARNING")
            record_application(
                job_title=title, company_name=company, location=loc_text, job_url=full_job_url,
                status=ApplicationStatus.APPLICATION_FAILED, apply_type='DIRECT_NAUKRI', match_score=score,
                notes="Candidate is not logged in on Naukri. Session required.", failure_reason="LOGIN_REQUIRED",
                experience_req=exp_text
            )
            detail_tab.close()
            return {"status": ApplicationStatus.APPLICATION_FAILED, "success": False, "failure_reason": "LOGIN_REQUIRED", "attempted": False}

        # CASE 1: APPLY ON COMPANY SITE
        if action_type == "COMPANY_SITE":
            bot_state.add_log(f"🏢 'Apply on Company Site' button detected for {company}! Clicking...", "INFO")
            bot_state.current_job["stage"] = ApplicationStatus.APPLY_CLICKED
            action_btn.scroll_into_view_if_needed()
            time.sleep(0.3)
            action_btn.hover()
            time.sleep(0.3)

            pages_before = len(context.pages)
            try:
                with context.expect_page(timeout=10000) as pinfo:
                    action_btn.click()
                company_tab = pinfo.value
            except Exception:
                if len(context.pages) > pages_before:
                    company_tab = context.pages[-1]
                else:
                    company_tab = detail_tab

            human_sleep(3, 5, stop_event)
            safe_bring_to_front(company_tab)

            try:
                company_tab.wait_for_load_state("domcontentloaded", timeout=20000)
            except Exception:
                pass

            return handle_external_company_portal(
                context=context, detail_tab=detail_tab, company_tab=company_tab,
                title=title, company=company, loc_text=loc_text, exp_text=exp_text,
                score=score, stop_event=stop_event,
                tailored_resume_path=custom_pdf,
                original_job_url=full_job_url,
                platform="NAUKRI"
            )

        # CASE 2: DIRECT APPLY ON NAUKRI (OR REDIRECT VIA APPLY)
        elif action_type == "DIRECT_APPLY":
            bot_state.add_log(f"⚡ Direct Apply button detected for {title} @ {company}. Clicking Apply...", "INFO")
            bot_state.current_job["stage"] = ApplicationStatus.APPLY_CLICKED

            confirmed = False
            failure_reason = ""

            pages_before = len(context.pages)
            new_tab_opened = None
            try:
                action_btn.scroll_into_view_if_needed()
                time.sleep(0.3)
                action_btn.hover()
                time.sleep(0.2)
                
                with context.expect_page(timeout=4000) as pinfo:
                    action_btn.click()
                new_tab_opened = pinfo.value
            except Exception:
                if len(context.pages) > pages_before:
                    new_tab_opened = context.pages[-1]

            human_sleep(2.5, 4.0, stop_event)

            # SUBCASE 2A: Clicking Apply opened a new tab
            if new_tab_opened and new_tab_opened != detail_tab:
                # Check if new tab is a Naukri confirmation page (e.g. saveApply or ACP)
                is_conf, conf_reason = is_naukri_application_confirmed(new_tab_opened)
                if is_conf:
                    bot_state.add_log(f"🎉 Direct Apply confirmation detected in new tab for {company} ({conf_reason})!", "SUCCESS")
                    try:
                        new_tab_opened.close()
                    except Exception:
                        pass
                    confirmed = True
                elif "naukri.com" not in new_tab_opened.url.lower():
                    bot_state.add_log(f"🌐 Clicking Apply opened external portal in new tab for {company}!", "INFO")
                    company_tab = new_tab_opened
                    safe_bring_to_front(company_tab)
                    try:
                        company_tab.wait_for_load_state("domcontentloaded", timeout=15000)
                    except Exception:
                        pass
                    return handle_external_company_portal(
                        context=context, detail_tab=detail_tab, company_tab=company_tab,
                        title=title, company=company, loc_text=loc_text, exp_text=exp_text,
                        score=score, stop_event=stop_event,
                        tailored_resume_path=custom_pdf,
                        original_job_url=full_job_url,
                        platform="NAUKRI"
                    )

            # SUBCASE 2B: Clicking Apply redirected detail_tab to external site (not naukri.com)
            if "naukri.com" not in detail_tab.url.lower():
                bot_state.add_log(f"🌐 Direct Apply redirected to external company portal: {detail_tab.url[:70]}", "INFO")
                return handle_external_company_portal(
                    context=context, detail_tab=detail_tab, company_tab=detail_tab,
                    title=title, company=company, loc_text=loc_text, exp_text=exp_text,
                    score=score, stop_event=stop_event,
                    tailored_resume_path=custom_pdf,
                    original_job_url=full_job_url,
                    platform="NAUKRI"
                )

            # SUBCASE 2C: Standard Direct Apply on Naukri (Chatbot drawer or 1-Click apply)
            if stop_event and stop_event.is_set():
                if detail_tab and not detail_tab.is_closed():
                    detail_tab.close()
                return {"status": ApplicationStatus.APPLICATION_SKIPPED, "success": False, "failure_reason": "STOP_REQUESTED", "attempted": True}

            # Check if login modal appeared
            login_modal = detail_tab.query_selector(".login-layer, .login-modal, form[name='login-form'], div[class*='loginModal']")
            if login_modal and login_modal.is_visible():
                bot_state.add_log(f"🔒 Login modal appeared for {company}. Session login required on Naukri.", "WARNING")
                record_application(
                    job_title=title, company_name=company, location=loc_text, job_url=full_job_url,
                    status=ApplicationStatus.APPLICATION_FAILED, apply_type='DIRECT_NAUKRI', match_score=score,
                    notes="Naukri requested login credentials.", failure_reason="LOGIN_REQUIRED",
                    experience_req=exp_text
                )
                detail_tab.close()
                cooldown_timer(min_sec=bot_state.config.unconfirmed_cooldown_min_sec, max_sec=bot_state.config.unconfirmed_cooldown_max_sec, stop_event=stop_event, reason=f"Login required for {company}")
                return {"status": ApplicationStatus.APPLICATION_FAILED, "success": False, "failure_reason": "LOGIN_REQUIRED", "attempted": True}

            # Check if detail_tab itself already navigated to confirmation (e.g. saveApply)
            if not confirmed:
                is_conf, conf_reason = is_naukri_application_confirmed(detail_tab)
                if is_conf:
                    confirmed = True
                    bot_state.add_log(f"🎉 Direct Apply confirmation detected for {company} ({conf_reason})!", "SUCCESS")

            # Answer screening questions drawer / chatbot
            if not confirmed:
                bot_state.current_job["stage"] = ApplicationStatus.FORM_OPENED
                drawer_res = handle_naukri_screening_drawer(detail_tab, stop_event, company=company, title=title)

                if isinstance(drawer_res, dict):
                    if drawer_res.get("status") == ApplicationStatus.NEEDS_USER_INPUT:
                        reason = drawer_res.get("reason", "NEEDS_USER_INPUT")
                        unanswered = drawer_res.get("unanswered_question", "")
                        bot_state.add_log(f"⚠️ [NEEDS_USER_INPUT] Screening questionnaire for {company} needs candidate input: '{unanswered[:30]}' ({reason}). Tab kept OPEN in Chrome!", "WARNING")
                        safe_bring_to_front(detail_tab)
                        record_application(
                            job_title=title, company_name=company, location=loc_text, job_url=full_job_url,
                            status=ApplicationStatus.NEEDS_USER_INPUT, apply_type='DIRECT_NAUKRI', match_score=score,
                            notes=f"Screening question requires user input: {reason}. Question: {unanswered}. Tab kept open in Chrome.",
                            failure_reason=reason,
                            experience_req=exp_text
                        )
                        return {"status": ApplicationStatus.NEEDS_USER_INPUT, "success": False, "failure_reason": reason, "attempted": True}
                    elif drawer_res.get("status") in [ApplicationStatus.CONFIRMATION_TIMEOUT, ChatPanelState.CONFIRMATION_TIMEOUT] or drawer_res.get("open_form"):
                        # Double-check if page actually reached confirmation despite timeout
                        is_conf, conf_reason = is_naukri_application_confirmed(detail_tab)
                        if is_conf:
                            confirmed = True
                            bot_state.add_log(f"🎉 Application confirmed for {company} ({conf_reason})!", "SUCCESS")
                        else:
                            reason = drawer_res.get("failure_reason", "CONFIRMATION_TIMEOUT")
                            unanswered = drawer_res.get("unanswered_question", "")
                            bot_state.add_log(f"⚠️ Application questionnaire remained open or timed out for {company} (Question: '{unanswered[:30]}'). Tab kept OPEN in Chrome!", "WARNING")
                            safe_bring_to_front(detail_tab)
                            record_application(
                                job_title=title, company_name=company, location=loc_text, job_url=full_job_url,
                                status=ApplicationStatus.APPLICATION_FAILED, apply_type='DIRECT_NAUKRI', match_score=score,
                                notes=f"Questionnaire open/timed out: {reason}. Unanswered question: {unanswered}",
                                failure_reason=reason,
                                experience_req=exp_text
                            )
                            cooldown_timer(min_sec=bot_state.config.unconfirmed_cooldown_min_sec, max_sec=bot_state.config.unconfirmed_cooldown_max_sec, stop_event=stop_event, reason=f"Safety break after open form on {company}")
                            return {"status": ApplicationStatus.APPLICATION_FAILED, "success": False, "failure_reason": reason, "attempted": True}
                    elif drawer_res.get("status") == ApplicationStatus.APPLICATION_PENDING_CONFIRMATION:
                        reason = drawer_res.get("reason", "AUTO_SUBMIT_DIRECT_NOT_AUTHORIZED")
                        bot_state.add_log(f"Screening completed for {company}. Auto-submit not authorized. Tab kept OPEN for review.", "INFO")
                        safe_bring_to_front(detail_tab)
                        record_application(
                            job_title=title, company_name=company, location=loc_text, job_url=full_job_url,
                            status=ApplicationStatus.APPLICATION_PENDING_CONFIRMATION, apply_type='DIRECT_NAUKRI', match_score=score,
                            notes="Screening completed. Auto-submit not authorized. Tab kept open.",
                            failure_reason=reason,
                            experience_req=exp_text
                        )
                        return {"status": ApplicationStatus.APPLICATION_PENDING_CONFIRMATION, "success": False, "failure_reason": reason, "attempted": True}
                    elif drawer_res.get("status") in [ApplicationStatus.APPLICATION_CONFIRMED, ChatPanelState.APPLICATION_CONFIRMED]:
                        confirmed = True
                    elif drawer_res.get("status") == ChatPanelState.FORM_COMPLETED and drawer_res.get("success"):
                        confirmed = True

            bot_state.current_job["stage"] = ApplicationStatus.FORM_SUBMITTED

            # Verify Success with reliable condition-based polling (up to 8 seconds)
            if not confirmed:
                start_verify = time.time()
                while time.time() - start_verify < 8.0:
                    if stop_event and stop_event.is_set():
                        break

                    # 1. Comprehensive confirmation check on detail_tab
                    is_conf, conf_reason = is_naukri_application_confirmed(detail_tab)
                    if is_conf:
                        confirmed = True
                        bot_state.add_log(f"🎉 Application confirmed for {company} ({conf_reason})!", "SUCCESS")
                        break

                    # 2. Check all open pages in context in case saveApply opened in another tab
                    try:
                        for p in context.pages:
                            if p != detail_tab and not p.is_closed():
                                p_conf, p_reason = is_naukri_application_confirmed(p)
                                if p_conf:
                                    confirmed = True
                                    bot_state.add_log(f"🎉 Confirmation detected in tab {p.title()[:25]} ({p_reason})!", "SUCCESS")
                                    try:
                                        p.close()
                                    except Exception:
                                        pass
                                    break
                    except Exception:
                        pass

                    if confirmed:
                        break

                    # 3. Check for visible validation errors
                    has_val_err = detail_tab.evaluate("""() => {
                        const errEls = Array.from(document.querySelectorAll('.error, .alert-danger, .invalid-feedback'))
                            .filter(e => e.offsetParent !== null && (e.innerText || '').trim().length > 0);
                        return errEls.length > 0 ? errEls[0].innerText.trim() : null;
                    }""")
                    if has_val_err:
                        failure_reason = f"VALIDATION_ERROR: {has_val_err}"
                        break

                    # 4. Check action button state directly
                    act_t, _ = detect_naukri_action_button(detail_tab)
                    if act_t == "ALREADY_APPLIED":
                        confirmed = True
                        bot_state.add_log(f"🎉 Application confirmed via button state for {company}!", "SUCCESS")
                        break

                    # 5. Fallback reload at 4s if no active questionnaire is present
                    if time.time() - start_verify > 4.0:
                        has_chat = naukri_chat_panel_handler.detect_chat_panel(detail_tab)
                        if not has_chat:
                            try:
                                detail_tab.reload(wait_until="domcontentloaded")
                                time.sleep(1.0)
                                is_conf_reload, r_reason = is_naukri_application_confirmed(detail_tab)
                                if is_conf_reload:
                                    confirmed = True
                                    bot_state.add_log(f"🎉 Application confirmed after refresh for {company} ({r_reason})!", "SUCCESS")
                                    break
                            except Exception:
                                pass

                    time.sleep(0.8)

            # CRITICAL VERIFICATION: Ensure no open questionnaire panel remains before confirming
            try:
                open_panel = naukri_chat_panel_handler.detect_chat_panel(detail_tab)
                if open_panel and open_panel.is_visible():
                    rem_q = naukri_chat_panel_handler.extract_latest_question(detail_tab, open_panel)
                    if rem_q:
                        confirmed = False
                        failure_reason = f"OPEN_QUESTION_REMAINS: {rem_q}"
            except Exception:
                pass

            if confirmed:
                activity_rep = generate_activity_report(
                    jd_analysis=jd_analysis,
                    optimization_res=opt_res,
                    application_status="Applied Successfully"
                )
                bot_state.add_log(f"📋 Application Activity Report:\n{activity_rep}", "SUCCESS")
                record_application(
                    job_title=title, company_name=company, location=loc_text, job_url=full_job_url,
                    status=ApplicationStatus.APPLICATION_CONFIRMED, apply_type='DIRECT_NAUKRI', match_score=jd_analysis.match_score,
                    notes=f"Successfully applied via Naukri Direct Apply. Match: {jd_analysis.match_score}%.",
                    experience_req=exp_text, platform="NAUKRI",
                    customized_resume_path=custom_pdf,
                    original_resume_path=opt_res.get("original_path", ""),
                    cv_changes_json=json.dumps(opt_res),
                    jd_match_analysis_json=json.dumps(jd_analysis.to_dict())
                )
                bot_state.today_applied = get_today_applied_count()
                bot_state.add_log(f"✅ Application SUCCESS via Direct Apply! [{bot_state.today_applied}/{bot_state.daily_limit}] for {title} @ {company}", "SUCCESS")
                naukri_rep = format_final_application_report(
                    company_name=company,
                    job_title=title,
                    job_location=loc_text,
                    platform="Naukri",
                    application_type="Apply",
                    jd_match=f"{jd_analysis.match_score}%",
                    resume_customized="Yes" if custom_pdf else "No",
                    resume_uploaded="Yes",
                    application_status="Yes",
                    submission_verified="Yes",
                    pending_action="None"
                )
                bot_state.add_log(f"📋 Application Report (Section 7):\n{naukri_rep}", "SUCCESS")

                try:
                    detail_tab.close()
                except Exception:
                    pass

                # MANDATORY SAFETY COOLDOWN ON CONFIRMED DIRECT APPLY
                cooldown_timer(min_sec=bot_state.config.cooldown_min_sec, max_sec=bot_state.config.cooldown_max_sec, stop_event=stop_event, reason=f"Application confirmed for {company}")
                return {"status": ApplicationStatus.APPLICATION_CONFIRMED, "success": True, "failure_reason": "", "attempted": True}
            else:
                if not failure_reason:
                    failure_reason = "CONFIRMATION_TIMEOUT"
                bot_state.add_log(f"Application was not confirmed for {company}. Failure reason: {failure_reason}", "WARNING")
                record_application(
                    job_title=title, company_name=company, location=loc_text, job_url=full_job_url,
                    status=ApplicationStatus.APPLICATION_FAILED, apply_type='DIRECT_NAUKRI', match_score=score,
                    notes=f"Direct apply clicked but submission unconfirmed: {failure_reason}",
                    failure_reason=failure_reason,
                    experience_req=exp_text
                )
                has_open_form = False
                try:
                    has_open_form = detail_tab.evaluate("""() => {
                        const formContainers = Array.from(document.querySelectorAll(
                            '.chatbot_drawer, .drawer-wrapper, .bot-container, div[class*="chatbot"], div[class*="drawer"], div[class*="apply-modal"], div[class*="applyModal"], div[class*="screening"], div[class*="questionnaire"], div[role="dialog"], .apply-dialog, .modal-content, .custom-questions'
                        )).filter(c => c.offsetParent !== null && window.getComputedStyle(c).display !== 'none');
                        if (formContainers.length === 0) return false;
                        return formContainers.some(c => {
                            const inputs = Array.from(c.querySelectorAll('input:not([type="hidden"]), select, textarea'));
                            return inputs.some(i => i.offsetParent !== null && !i.disabled);
                        });
                    }""")
                except Exception:
                    pass

                if has_open_form:
                    bot_state.add_log(f"Form or questions still open on tab for {company}. Keeping tab OPEN in Chrome for review.", "WARNING")
                    safe_bring_to_front(detail_tab)
                else:
                    try:
                        detail_tab.close()
                    except Exception:
                        pass

                # CRITICAL: DO NOT SKIP COOLDOWN! Apply attempt cooldown so we don't rapid-fire click next jobs!
                cooldown_timer(min_sec=bot_state.config.unconfirmed_cooldown_min_sec, max_sec=bot_state.config.unconfirmed_cooldown_max_sec, stop_event=stop_event, reason=f"Safety break after unconfirmed application attempt for {company}")
                return {"status": ApplicationStatus.APPLICATION_FAILED, "success": False, "failure_reason": failure_reason, "attempted": True}

        else:
            # Check if job description contains an HR / careers email address
            from email_service import extract_hiring_emails, open_outlook_for_job_application
            emails = extract_hiring_emails(detail_tab, jd_text=jd_text)
            if emails:
                target_email = emails[0]
                bot_state.add_log(f"📧 [Email Application] Found hiring email for {company}: {target_email}! Opening Outlook...", "INFO")
                opened, reason = open_outlook_for_job_application(
                    recipient_email=target_email,
                    job_title=title,
                    company_name=company,
                    location=loc_text,
                    context_text=f"Company: {company}, Role: {title}"
                )
                if opened:
                    bot_state.add_log(f"✅ {reason}", "SUCCESS")
                    try:
                        detail_tab.close()
                    except Exception:
                        pass
                    cooldown_timer(min_sec=30, max_sec=60, stop_event=stop_event, reason=f"Outlook email composed for {company}")
                    return {"status": ApplicationStatus.APPLICATION_CONFIRMED, "success": True, "failure_reason": "", "attempted": True}

            # 6. Capture screenshot when button detection fails
            screenshot_path = ""
            try:
                os.makedirs("backend/screenshots", exist_ok=True)
                safe_comp = re.sub(r'[^a-zA-Z0-9]', '_', company)[:20]
                screenshot_path = f"backend/screenshots/apply_option_failed_{safe_comp}_{int(time.time())}.png"
                detail_tab.screenshot(path=screenshot_path)
            except Exception:
                pass

            bot_state.add_log(f"No active Apply or Company Site button found on page for {company}. Skipping.", "WARNING")
            record_application(
                job_title=title, company_name=company, location=loc_text, job_url=full_job_url,
                status=ApplicationStatus.APPLICATION_SKIPPED, apply_type='DIRECT_NAUKRI', match_score=score,
                skip_reason_code="APPLY_OPTION_NOT_AVAILABLE",
                failure_reason="APPLY_OPTION_NOT_AVAILABLE",
                execution_stage="ACTION_BUTTON_DETECTION",
                detailed_explanation="The job is eligible, but no application option was found after inspection.",
                notes="No active Apply or Company Site button found.",
                screenshot_reference=screenshot_path,
                experience_req=exp_text,
                platform="NAUKRI"
            )
            try:
                detail_tab.close()
            except Exception:
                pass
            human_sleep(1.5, 3.0, stop_event)
            return {"status": ApplicationStatus.APPLICATION_SKIPPED, "success": False, "failure_reason": "APPLY_OPTION_NOT_AVAILABLE", "attempted": False}

    except Exception as e:
        bot_state.add_log(f"Error while processing application for {company}: {e}", "WARNING")
        try:
            if detail_tab and not detail_tab.is_closed():
                detail_tab.close()
        except Exception:
            pass
        record_application(
            job_title=title, company_name=company, location=loc_text, job_url=job_url,
            status=ApplicationStatus.APPLICATION_FAILED, apply_type='DIRECT_NAUKRI', match_score=score,
            skip_reason_code="APPLICATION_BLOCKED",
            failure_reason="APPLICATION_BLOCKED",
            error_message=str(e),
            execution_stage="APPLICATION_EXECUTION",
            detailed_explanation=f"An application option was found, but the automation could not execute the action: {e}",
            notes=f"Exception during processing: {e}",
            experience_req=exp_text,
            platform="NAUKRI"
        )
        # Apply safety cooldown on exception after attempt
        cooldown_timer(min_sec=bot_state.config.unconfirmed_cooldown_min_sec, max_sec=bot_state.config.unconfirmed_cooldown_max_sec, stop_event=stop_event, reason=f"Safety pause after error on {company}")
        return {"status": ApplicationStatus.APPLICATION_FAILED, "success": False, "failure_reason": str(e), "attempted": True}

linkedin_engine = LinkedInEngine(
    bot_state=bot_state,
    cooldown_timer_fn=cooldown_timer,
    human_sleep_fn=human_sleep,
    external_portal_fn=handle_external_company_portal
)

naukrigulf_engine = NaukriGulfEngine(
    bot_state=bot_state,
    cooldown_timer_fn=cooldown_timer,
    human_sleep_fn=human_sleep,
    external_portal_fn=handle_external_company_portal
)

DEFAULT_TARGET_ROLES = [
    {"name": "Senior Full Stack Developer", "slug": "senior-full-stack-developer"},
    {"name": "MERN Stack Developer", "slug": "mern-stack-developer"},
    {"name": "Senior Software Engineer", "slug": "senior-software-engineer"},
    {"name": "Full Stack Developer", "slug": "full-stack-developer"},
    {"name": "Node.js Developer", "slug": "node-js-developer"},
    {"name": "React Developer", "slug": "react-developer"},
    {"name": "Next.js Developer", "slug": "next-js-developer"}
]

def is_job_title_blacklisted(title: str, desc: str = "") -> Tuple[bool, str, str]:
    """
    Candidate Technology Profile & Flexible Job Matching:
    - Evaluates role using technology_matcher.
    - APPLY for relevant mixed-technology roles (MERN + Python, MERN + .NET/C#, React + Node + Python).
    - SKIP dedicated specialist roles (Dedicated Python, Dedicated .NET, Dedicated Java).
    - Returns (is_blocked: bool, reason: str, reason_code: str)
    """
    if not title:
        return False, "", ""
    from technology_matcher import evaluate_technology_alignment
    res = evaluate_technology_alignment(title=title, desc=desc)
    if not res["should_apply"]:
        return True, res["detailed_explanation"], res.get("reason_code", "PRIMARY_SPECIALIZATION_MISMATCH")
    return False, "", ""

def format_naukri_slug(keyword: str) -> str:
    cleaned = keyword.lower().replace(".", "-").replace("/", "-")
    slug = "-".join(part for part in cleaned.split() if part)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug

def parse_target_roles(search_input: str) -> List[Dict[str, str]]:
    raw = (search_input or "").strip()
    if not raw or "all" in raw.lower() or "auto-cycle" in raw.lower() or "target" in raw.lower():
        return DEFAULT_TARGET_ROLES
    
    # Check if multiple roles separated by comma
    if "," in raw:
        items = [i.strip() for i in raw.split(",") if i.strip()]
        return [{"name": item, "slug": format_naukri_slug(item)} for item in items]
    
    # Check if matching any predefined role
    for role in DEFAULT_TARGET_ROLES:
        if role["name"].lower() == raw.lower() or role["slug"] == format_naukri_slug(raw):
            return [role]
            
    # Custom single role
    return [{"name": raw, "slug": format_naukri_slug(raw)}]

def parse_target_locations(location_input: str, default_locs: List[str] = None) -> List[str]:
    defaults = default_locs or ["Mumbai", "Pune", "Remote"]
    raw = (location_input or "").strip()
    if not raw:
        return defaults
    clean = raw.replace(" and ", ",").replace("&", ",").replace("+", ",")
    locs = [l.strip() for l in clean.split(",") if l.strip()]
    return locs if locs else defaults

def is_naukri_location_valid(loc_text: str, allowed_locations: List[str] = None) -> bool:
    """
    CRITICAL PATCH: Unified Location Matching
    Splits multi-location strings into individual locations and verifies independently.
    Never marks a job LOCATION_MISMATCH if at least one valid preferred location matches.
    """
    from location_matcher import match_location
    is_eligible, _, _ = match_location(loc_text, allowed_locations or ["Mumbai", "Pune", "Remote"])
    return is_eligible

def run_agent_sync(search_keyword: str = "All Target Roles (Auto-Cycle)", 
                   location: str = "Mumbai, Pune, Qatar, Remote", 
                   experience_years: int = 5, 
                   platform: str = "ALL",
                   naukri_locations: str = "Mumbai, Pune, Remote",
                   linkedin_locations: str = "Mumbai, Pune, Qatar, Remote",
                   naukrigulf_locations: str = "Qatar, Dubai, UAE, Saudi Arabia, Remote"):
    """Main worker thread running the Playwright Chrome CDP automation."""
    bot_state.is_running = True
    bot_state.stop_event.clear()
    bot_state.status = "CONNECTING"
    
    try:
        bot_state.config.reload()
        naukri_quota = 45
        linkedin_quota = 45
        naukrigulf_quota = 45
        bot_state.platform_quotas = {"NAUKRI": naukri_quota, "LINKEDIN": linkedin_quota, "NAUKRIGULF": naukrigulf_quota}
        bot_state.platform_applied = {
            "NAUKRI": get_today_applied_count("NAUKRI"),
            "LINKEDIN": get_today_applied_count("LINKEDIN"),
            "NAUKRIGULF": get_today_applied_count("NAUKRIGULF")
        }
        bot_state.today_applied = sum(bot_state.platform_applied.values())
        bot_state.daily_limit = 135

        platform_up = (platform or "ALL").upper()
        bot_state.add_log(f"Starting Job Copilot in Autonomous Mode. Platform: {platform_up}.", "INFO")
        bot_state.add_log(f"📊 Separate Daily Quotas: Naukri.com ({bot_state.platform_applied['NAUKRI']}/{naukri_quota}) | LinkedIn ({bot_state.platform_applied['LINKEDIN']}/{linkedin_quota}) | NaukriGulf ({bot_state.platform_applied['NAUKRIGULF']}/{naukrigulf_quota})", "INFO")

        if not agent_config_manager.is_authorized("auto_search"):
            bot_state.status = "IDLE"
            bot_state.add_log("auto_search is disabled in agent config permissions. Halting search.", "WARNING")
            bot_state.is_running = False
            return

        target_roles = parse_target_roles(search_keyword)
        role_names_str = ", ".join(r["name"] for r in target_roles)
        bot_state.add_log(f"Target Roles queued ({len(target_roles)}): {role_names_str}", "INFO")

        cdp_url = "http://127.0.0.1:9222"
        
        try:
            with sync_playwright() as p:
                bot_state.add_log(f"Connecting to Chrome on {cdp_url}...", "INFO")
                browser: Browser = p.chromium.connect_over_cdp(cdp_url)
                context = browser.contexts[0] if browser.contexts else browser.new_context()
            
                def get_safe_page(ctx):
                    try:
                        active = [pg for pg in ctx.pages if not pg.is_closed()]
                        return active[0] if active else ctx.new_page()
                    except Exception:
                        return ctx.new_page()

                bot_state.add_log("Successfully connected to existing Chrome session!", "SUCCESS")

                # --- 1. NAUKRI SEARCH CYCLE ---
                if platform_up in ("ALL", "NAUKRI") and not bot_state.stop_event.is_set():
                    naukri_today = get_today_applied_count("NAUKRI")
                    if naukri_today < naukri_quota:
                        page: Page = get_safe_page(context)
                        bot_state.add_log(f"🔷 [Naukri Engine] Starting Naukri.com search cycle (Today: {naukri_today}/{naukri_quota})...", "INFO")

                        try:
                            context.add_cookies([
                                {"name": "naukri_geo", "value": "IN", "domain": ".naukri.com", "path": "/"},
                                {"name": "n_country", "value": "IN", "domain": ".naukri.com", "path": "/"}
                            ])
                        except Exception:
                            pass

                        # Naukri.com: strictly Mumbai, Pune, and Remote (India)
                        raw_naukri_list = parse_target_locations(naukri_locations or "Mumbai, Pune, Remote", default_locs=["Mumbai", "Pune", "Remote"])
                        naukri_locs_list = []
                        for loc_item in raw_naukri_list:
                            l_low = loc_item.lower().strip()
                            if any(v in l_low for v in ["mumbai", "pune", "remote", "wfh", "navi mumbai", "thane"]):
                                if not any(d in l_low for d in ["noida", "gurugram", "gurgaon", "delhi", "ncr", "kolkata", "bengaluru", "bangalore", "hyderabad", "chennai", "qatar", "dubai"]):
                                    naukri_locs_list.append(loc_item)
                        if not naukri_locs_list:
                            naukri_locs_list = ["Mumbai", "Pune", "Remote"]

                        bot_state.add_log(f"🔷 [Naukri Engine] Target Locations ({len(naukri_locs_list)}): {', '.join(naukri_locs_list)}", "INFO")

                        for current_loc_str in naukri_locs_list:
                            if bot_state.stop_event.is_set():
                                break

                            naukri_today = get_today_applied_count("NAUKRI")
                            if naukri_today >= naukri_quota:
                                bot_state.add_log(f"🏆 Target daily quota for Naukri.com ({naukri_quota}) reached! Moving to next platform...", "SUCCESS")
                                break

                            loc_lower = current_loc_str.strip().lower()
                            is_remote = "remote" in loc_lower or "wfh" in loc_lower
                            loc_formatted = loc_lower.replace(" ", "-").replace("/", "-")

                            for role_idx, current_role in enumerate(target_roles):
                                if bot_state.stop_event.is_set():
                                    bot_state.add_log("Stop requested by user. Pausing agent.", "WARNING")
                                    break

                                naukri_today = get_today_applied_count("NAUKRI")
                                bot_state.platform_applied["NAUKRI"] = naukri_today
                                bot_state.today_applied = sum(bot_state.platform_applied.values())
                                if naukri_today >= naukri_quota:
                                    bot_state.add_log(f"🏆 Target daily quota for Naukri.com ({naukri_quota}) reached! Moving to next platform...", "SUCCESS")
                                    break

                                role_name = current_role["name"]
                                role_slug = current_role["slug"]

                                if is_remote:
                                    target_url = f"https://www.naukri.com/{role_slug}-jobs?wfhType=0&experience={experience_years}"
                                else:
                                    target_url = f"https://www.naukri.com/{role_slug}-jobs-in-{loc_formatted}?experience={experience_years}"

                                bot_state.status = "SEARCHING"
                                bot_state.add_log(f"🔎 [Naukri] [{role_idx+1}/{len(target_roles)}] Searching for '{role_name}' in {current_loc_str}: {target_url}", "INFO")

                                try:
                                    if not page or page.is_closed():
                                        page = get_safe_page(context)
                                    page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
                                    human_sleep(4, 7, bot_state.stop_event)
                                except Exception as nav_e:
                                    bot_state.add_log(f"Navigation warning for '{role_name}': {nav_e}", "WARNING")
                                    continue

                                # Extra check: if page landed on naukrigulf during Naukri India search, re-force
                                if "naukrigulf" in page.url.lower():
                                    bot_state.add_log("Detected NaukriGulf redirect during Naukri India search. Re-forcing...", "WARNING")
                                    page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
                                    human_sleep(3, 5, bot_state.stop_event)

                                # Wait for job container
                                try:
                                    page.wait_for_selector(".styles_job-listing-container__wfdNl, .cust-job-tuple, .srp-jobtuple-wrapper", timeout=12000)
                                except Exception:
                                    bot_state.add_log(f"No job cards container detected for '{role_name}'. Moving to next role...", "WARNING")
                                    continue

                                # Scroll down naturally to simulate reading
                                bot_state.add_log(f"Scrolling through '{role_name}' results like a human user...", "INFO")
                                for _ in range(3):
                                    if bot_state.stop_event.is_set():
                                        break
                                    try:
                                        if page and not page.is_closed():
                                            page.mouse.wheel(0, random.randint(300, 600))
                                    except Exception:
                                        pass
                                    human_sleep(1.2, 2.5, bot_state.stop_event)

                                # Locate job cards safely
                                if not page or page.is_closed():
                                    page = get_safe_page(context)
                                job_cards = page.query_selector_all(".cust-job-tuple, .srp-jobtuple-wrapper, article.jobTuple")
                                bot_state.add_log(f"Found {len(job_cards)} job cards on current page for '{role_name}'. Parsing...", "INFO")

                                jobs_to_process = []
                                for card in job_cards:
                                    try:
                                        title_elem = card.query_selector(".title, a.title, .job-title")
                                        company_elem = card.query_selector(".comp-name, a.subTitle, .comp-name-link")
                                        loc_elem = card.query_selector(".locWdth, .location, span.loc")
                                        exp_elem = card.query_selector(".expwdth, .experience, span.exp")
                                    
                                        t = title_elem.inner_text().strip() if title_elem else ""
                                        c = company_elem.inner_text().strip() if company_elem else ""
                                        l = loc_elem.inner_text().strip() if loc_elem else location
                                        e = exp_elem.inner_text().strip() if exp_elem else f"{experience_years} Yrs"
                                        u = title_elem.get_attribute("href") if title_elem else ""
                                    
                                        if t and c and u:
                                            jid = card.get_attribute("data-job-id") or card.get_attribute("id") or ""
                                            if not jid and u:
                                                m = re.search(r"-?(\d{6,14})(?:\?|$)", u)
                                                if m:
                                                    jid = m.group(1)
                                            jobs_to_process.append({
                                                "id": jid,
                                                "title": t,
                                                "company": c,
                                                "location": l,
                                                "experience": e,
                                                "url": u
                                            })
                                    except Exception:
                                        pass

                                if not jobs_to_process:
                                    bot_state.add_log(f"No job cards found for '{role_name}'. Proceeding to next role...", "INFO")
                                    continue

                                bot_state.add_log(f"Queued {len(jobs_to_process)} jobs to inspect for '{role_name}'.", "INFO")

                                for index, job in enumerate(jobs_to_process):
                                    if bot_state.stop_event.is_set():
                                        bot_state.add_log("Stop requested by user. Pausing agent.", "WARNING")
                                        break

                                    naukri_today = get_today_applied_count("NAUKRI")
                                    bot_state.platform_applied["NAUKRI"] = naukri_today
                                    bot_state.today_applied = sum(bot_state.platform_applied.values())
                                    if naukri_today >= naukri_quota:
                                        bot_state.add_log(f"🏆 Target daily quota for Naukri.com ({naukri_quota}) reached! Moving to next platform...", "SUCCESS")
                                        break

                                    title = job["title"]
                                    company = job["company"]
                                    loc_text = job["location"]
                                    exp_text = job["experience"]
                                    job_url = job["url"]
                                    job_id = job.get("id", "")
                                    if not job_id and job_url:
                                        m = re.search(r"-?(\d{6,14})(?:\?|$)", job_url)
                                        if m:
                                            job_id = m.group(1)

                                    bot_state.current_job = {
                                        "id": job_id,
                                        "title": title,
                                        "company": company,
                                        "location": loc_text,
                                        "experience": exp_text,
                                        "url": job_url,
                                        "role_category": role_name
                                    }

                                    bot_state.add_log(f"Inspecting [{index+1}/{len(jobs_to_process)}] ({role_name}): {title} @ {company}", "INFO")

                                    # Ignore Gulf postings during Naukri India search (NaukriGulf engine handles them!)
                                    if "naukrigulf" in (job_url or "").lower():
                                        bot_state.add_log(f"Skipping Gulf posting for {company} on Naukri India. NaukriGulf engine will process Gulf jobs separately.", "INFO")
                                        continue

                                    # INDEPENDENT ELIGIBILITY CHECK 1: Location Compatibility
                                    from location_matcher import match_location
                                    is_loc_valid, matched_locs, extracted_locs = match_location(loc_text, naukri_locs_list)
                                    if not is_loc_valid:
                                        bot_state.add_log(f"📍 Location '{loc_text}' does not match candidate preferred locations ({', '.join(naukri_locs_list)}). Skipping.", "WARNING")
                                        record_application(
                                            job_title=title,
                                            company_name=company,
                                            location=loc_text,
                                            job_url=job_url,
                                            status=ApplicationStatus.APPLICATION_SKIPPED,
                                            match_score=0,
                                            skip_reason_code="LOCATION_MISMATCH",
                                            failure_reason="LOCATION_MISMATCH",
                                            execution_stage="ELIGIBILITY_VERIFICATION",
                                            detailed_explanation=f"None of the job's listed locations ({', '.join(extracted_locs)}) matches candidate preferred locations ({', '.join(naukri_locs_list)}).",
                                            notes=f"Skipped: None of the job's listed locations ({loc_text}) match candidate target regions ({', '.join(naukri_locs_list)}).",
                                            platform="NAUKRI"
                                        )
                                        continue

                                    # INDEPENDENT ELIGIBILITY CHECK 2: Technical Skill Compatibility
                                    is_title_blocked, title_block_reason, block_reason_code = is_job_title_blacklisted(title, f"Location: {loc_text}, Experience: {exp_text}")
                                    if is_title_blocked:
                                        bot_state.add_log(f"🚫 Skipping role '{title}' @ {company}: {title_block_reason}", "INFO")
                                        record_application(
                                            job_title=title,
                                            company_name=company,
                                            location=loc_text,
                                            job_url=job_url,
                                            status=ApplicationStatus.APPLICATION_SKIPPED,
                                            match_score=0,
                                            skip_reason_code=block_reason_code or "PRIMARY_SPECIALIZATION_MISMATCH",
                                            failure_reason=block_reason_code or "PRIMARY_SPECIALIZATION_MISMATCH",
                                            execution_stage="ELIGIBILITY_VERIFICATION",
                                            detailed_explanation=f"Technical specialization check: {title_block_reason}",
                                            notes=f"Skipped: {title_block_reason}",
                                            platform="NAUKRI"
                                        )
                                        continue

                                    # INDEPENDENT ELIGIBILITY CHECK 3: Duplicate Application Status
                                    if check_already_applied_db(title=title, company=company, job_url=job_url, job_id=job_id):
                                        bot_state.add_log(f"Already applied or skipped {title} @ {company} in the past. Skipping.", "INFO")
                                        continue

                                    # INDEPENDENT ELIGIBILITY CHECK 4: Match Score Threshold (score >= 65 is eligible)
                                    bot_state.status = "EVALUATING"
                                    score, should_apply, reason = evaluate_job_relevance(title, company, f"Location: {loc_text}, Experience: {exp_text}")
                                    bot_state.add_log(f"AI Match Score: {score}% - {reason}", "INFO" if score >= 65 else "WARNING")

                                    if score < 65:
                                        bot_state.add_log(f"Job compatibility score ({score}%) is below 65% minimum threshold. Skipping.", "INFO")
                                        record_application(
                                            job_title=title,
                                            company_name=company,
                                            location=loc_text,
                                            job_url=job_url,
                                            status=ApplicationStatus.APPLICATION_SKIPPED,
                                            match_score=score,
                                            skip_reason_code="LOW_MATCH_SCORE",
                                            failure_reason="LOW_MATCH_SCORE",
                                            execution_stage="ELIGIBILITY_VERIFICATION",
                                            detailed_explanation=f"The job's compatibility score ({score}%) is below the configured threshold (65%). Reason: {reason}",
                                            notes=f"AI Skipped: Match score {score}% is below threshold 65%. {reason}",
                                            experience_req=exp_text,
                                            platform="NAUKRI"
                                        )
                                        continue

                                    # Ensure search page is alive
                                    if page is None or page.is_closed():
                                        try:
                                            page = context.new_page()
                                        except Exception:
                                            pass

                                    # Execute Unified Application Engine (Direct Naukri vs Company Portal)
                                    process_job_application(
                                        context=context,
                                        search_page=page,
                                        title=title,
                                        company=company,
                                        loc_text=loc_text,
                                        exp_text=exp_text,
                                        job_url=job_url,
                                        score=score,
                                        stop_event=bot_state.stop_event
                                    )

                                    # Return focus to main search page
                                    try:
                                        if page and not page.is_closed():
                                            page.bring_to_front()
                                    except Exception:
                                        pass

                                bot_state.add_log(f"Finished processing page for role '{role_name}'.", "INFO")
                                human_sleep(2, 4, bot_state.stop_event)

                        bot_state.add_log("🏁 Completed Naukri search cycle.", "SUCCESS")

                # --- 2. LINKEDIN SEARCH CYCLE ---
                if platform_up in ("ALL", "LINKEDIN") and not bot_state.stop_event.is_set():
                    lk_today = get_today_applied_count("LINKEDIN")
                    if lk_today < linkedin_quota:
                        lk_locs_str = linkedin_locations or "Dubai, Qatar, Mumbai, Pune, Remote"
                        bot_state.add_log(f"🔷 [LinkedIn Engine] Starting LinkedIn search cycle (Today: {lk_today}/{linkedin_quota})...", "INFO")
                        linkedin_engine.run_linkedin_search_cycle(
                            context=context,
                            target_roles=target_roles,
                            location=lk_locs_str,
                            stop_event=bot_state.stop_event,
                            quota_limit=linkedin_quota
                        )
                    else:
                        bot_state.add_log(f"LinkedIn daily quota of {linkedin_quota} reached ({lk_today}/{linkedin_quota}). Skipping LinkedIn cycle.", "INFO")

                # --- 3. NAUKRIGULF SEARCH CYCLE ---
                if platform_up in ("ALL", "NAUKRIGULF") and not bot_state.stop_event.is_set():
                    ng_today = get_today_applied_count("NAUKRIGULF")
                    if ng_today < naukrigulf_quota:
                        ng_locs_str = naukrigulf_locations or "Qatar, Dubai, UAE, Saudi Arabia, Remote"
                        bot_state.add_log(f"🔷 [NaukriGulf Engine] Starting NaukriGulf search cycle (Today: {ng_today}/{naukrigulf_quota})...", "INFO")
                        naukrigulf_engine.run_naukrigulf_search_cycle(
                            context=context,
                            target_roles=target_roles,
                            locations_str=ng_locs_str,
                            experience_years=experience_years,
                            stop_event=bot_state.stop_event,
                            quota_limit=naukrigulf_quota
                        )
                    else:
                        bot_state.add_log(f"NaukriGulf daily quota of {naukrigulf_quota} reached ({ng_today}/{naukrigulf_quota}). Skipping NaukriGulf cycle.", "INFO")

                if bot_state.stop_event.is_set():
                    bot_state.status = "STOPPED"
                    bot_state.add_log("Agent stopped by user request. Preserving state.", "WARNING")
                else:
                    bot_state.add_log("🏁 Completed full autonomous job search cycle across selected platform(s).", "SUCCESS")
                    bot_state.status = "IDLE"

        except Exception as e:
            bot_state.last_error = str(e)
            bot_state.status = "ERROR"
            bot_state.add_log(f"Agent error: {e}", "ERROR")
            if "ECONNREFUSED" in str(e) or "connect_over_cdp" in str(e):
                bot_state.add_log("Could not connect to Chrome! Please make sure Chrome was launched with --remote-debugging-port=9222.", "ERROR")
        finally:
            bot_state.is_running = False
            bot_state.countdown_remaining = 0
            if bot_state.stop_event.is_set():
                bot_state.status = "STOPPED"
            elif bot_state.status not in ["LIMIT_REACHED", "ERROR"]:
                bot_state.status = "IDLE"
    except Exception as outer_e:
        bot_state.last_error = str(outer_e)
        bot_state.status = "ERROR"
        bot_state.add_log(f"Agent startup error: {outer_e}", "ERROR")
    finally:
        bot_state.is_running = False
        bot_state.countdown_remaining = 0
        if bot_state.stop_event.is_set():
            bot_state.status = "STOPPED"

def run_naukri_agent_sync(search_keyword: str = "All Target Roles (Auto-Cycle)", location: str = "Mumbai", experience_years: int = 5):
    """Backwards compatibility wrapper for Naukri-only sync."""
    return run_agent_sync(search_keyword, location, experience_years, platform="NAUKRI")

def start_agent_thread(keyword: str, location: str, experience: int, platform: str = "ALL", 
                       naukri_locations: str = "Mumbai, Pune, Remote", 
                       linkedin_locations: str = "Mumbai, Pune, Qatar, Remote",
                       naukrigulf_locations: str = "Qatar, Dubai, UAE, Saudi Arabia, Remote"):
    if bot_state.is_running:
        return False, "Agent is already running!"
    bot_state.stop_event.clear()
    bot_state.status = "CONNECTING"
    t = threading.Thread(
        target=run_agent_sync, 
        args=(keyword, location, experience, platform, naukri_locations, linkedin_locations, naukrigulf_locations), 
        daemon=True
    )
    t.start()
    return True, f"Agent started successfully on {platform.upper()} in background."

def stop_agent():
    bot_state.stop_event.set()
    bot_state.is_running = False
    bot_state.status = "STOPPED"
    bot_state.countdown_remaining = 0
    bot_state.add_log("User requested stop. Gracefully halting.", "WARNING")
    return True, "Stop signal sent to agent."
