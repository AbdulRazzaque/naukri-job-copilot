import os
import re
import time
import json
import threading
from typing import Dict, Any, List, Optional, Tuple
from playwright.sync_api import Page, BrowserContext, Locator, ElementHandle

from agent_config import agent_config_manager
from database import record_application, log_event, check_already_applied_db
from button_service import ButtonDetectionService, ButtonCategory
from question_answering import QuestionAnsweringEngine, QuestionCategory
from form_engine import (
    process_and_fill_complete_form,
    upload_resume_file,
    validate_entire_form,
    detect_and_collect_form_questions,
    check_page_already_applied
)
from email_service import extract_hiring_emails, open_outlook_for_job_application
from candidate_manager import getCandidateProfileByJobLocation, CandidateProfileManager, mask_phone_number

# -------------------------------------------------------------
# Standardized Execution Stages & Failure Codes
# -------------------------------------------------------------
class ExternalApplyStages:
    EXTERNAL_APPLY_DETECTED = "EXTERNAL_APPLY_DETECTED"
    EXTERNAL_NAVIGATION_STARTED = "EXTERNAL_NAVIGATION_STARTED"
    EXTERNAL_PAGE_OPENED = "EXTERNAL_PAGE_OPENED"
    EXTERNAL_JOB_VERIFIED = "EXTERNAL_JOB_VERIFIED"
    APPLICATION_FORM_DETECTED = "APPLICATION_FORM_DETECTED"
    FORM_ANALYSIS_COMPLETED = "FORM_ANALYSIS_COMPLETED"
    FORM_FILLING_STARTED = "FORM_FILLING_STARTED"
    RESUME_UPLOAD_STARTED = "RESUME_UPLOAD_STARTED"
    RESUME_UPLOAD_COMPLETED = "RESUME_UPLOAD_COMPLETED"
    FORM_VALIDATED = "FORM_VALIDATED"
    APPLICATION_SUBMITTED = "APPLICATION_SUBMITTED"
    APPLICATION_CONFIRMED = "APPLICATION_CONFIRMED"

class ExternalFailureReasons:
    EXTERNAL_LINK_NOT_FOUND = "EXTERNAL_LINK_NOT_FOUND"
    EXTERNAL_NAVIGATION_FAILED = "EXTERNAL_NAVIGATION_FAILED"
    EXTERNAL_JOB_MISMATCH = "EXTERNAL_JOB_MISMATCH"
    EXTERNAL_PAGE_UNAVAILABLE = "EXTERNAL_PAGE_UNAVAILABLE"
    APPLICATION_FORM_NOT_FOUND = "APPLICATION_FORM_NOT_FOUND"
    RESUME_UPLOAD_FAILED = "RESUME_UPLOAD_FAILED"
    FORM_VALIDATION_FAILED = "FORM_VALIDATION_FAILED"
    MISSING_REQUIRED_INFORMATION = "MISSING_REQUIRED_INFORMATION"
    CAPTCHA_REQUIRED = "CAPTCHA_REQUIRED"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    APPLICATION_SUBMISSION_FAILED = "APPLICATION_SUBMISSION_FAILED"
    APPLICATION_BLOCKED = "APPLICATION_BLOCKED"


class ExternalApplyEngine:
    """
    Autonomous External Company Website Application Engine:
    Executes the complete 12-stage pipeline for external career portals
    (Workday, Greenhouse, Lever, Ashby, BambooHR, SmartRecruiters, custom sites).
    """

    def __init__(self, bot_state=None, qa_engine=None):
        self.bot_state = bot_state
        self.qa_engine = qa_engine or QuestionAnsweringEngine()
        self.button_service = ButtonDetectionService()

    def log(self, message: str, level: str = "INFO"):
        if self.bot_state and hasattr(self.bot_state, "add_log"):
            self.bot_state.add_log(message, level)
        else:
            print(f"[{time.strftime('%H:%M:%S')}] [{level}] {message}")
        log_event(message, level=level)

    def capture_screenshot(self, page: Page, prefix: str, company: str) -> str:
        """Captures a timestamped debug screenshot."""
        try:
            os.makedirs("backend/screenshots", exist_ok=True)
            safe_comp = re.sub(r'[^a-zA-Z0-9]', '_', company)[:20]
            filename = f"backend/screenshots/{prefix}_{safe_comp}_{int(time.time())}.png"
            page.screenshot(path=filename)
            return filename
        except Exception:
            return ""

    # =========================================================================
    # Stage 1: Detect External Apply Option
    # =========================================================================
    def detect_external_apply_option(self, page: Page) -> Dict[str, Any]:
        """
        Inspects accessible button names, links, visible DOM elements, and external URLs.
        Returns detection metadata including locator, action type, and destination URL if present.
        """
        if not page or page.is_closed():
            return {"found": False, "type": "NONE"}

        # 1. External apply button selectors across platforms
        company_site_selectors = [
            "button:has-text('Apply on company site')",
            "a:has-text('Apply on company site')",
            "button:has-text('Apply on company website')",
            "a:has-text('Apply on company website')",
            "button:has-text('Apply on employer site')",
            "a:has-text('Apply on employer site')",
            "button[aria-label*='Apply on company']",
            "a[aria-label*='Apply on company']",
            "button[aria-label*='Apply externally']",
            "a[aria-label*='Apply externally']",
            "button:has-text('Apply externally')",
            "a:has-text('Apply externally')",
            "#company-site-button",
            ".company-site-button",
            "a[data-tracking-control-name*='external_apply']",
            "button[data-tracking-control-name*='external_apply']",
            "button:has-text('Apply on company')",
            "a:has-text('Apply on company')",
            "button:has-text('company site')",
            "a:has-text('company site')"
        ]

        for sel in company_site_selectors:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible() and el.is_enabled():
                    href = el.get_attribute("href") or ""
                    return {
                        "found": True,
                        "type": "COMPANY_SITE",
                        "element": el,
                        "selector": sel,
                        "destination_url": href,
                        "text": (el.inner_text() or "").strip()
                    }
            except Exception:
                continue

        # 2. Check general apply buttons that might point externally or have external href
        try:
            apply_candidates = page.query_selector_all("a.apply-button, button.apply-button, #apply-button, a[class*='apply'], button[class*='apply']")
            for link in apply_candidates:
                if not link.is_visible() or not link.is_enabled():
                    continue
                href = link.get_attribute("href") or ""
                txt = (link.inner_text() or "").strip().lower()
                aria = (link.get_attribute("aria-label") or "").strip().lower()

                # Filter out unrelated controls
                if any(bad in txt for bad in ["filter", "search", "cancel", "save", "bookmark"]):
                    continue

                is_ext_text = any(t in txt for t in ["company", "employer", "external", "website"])
                is_ext_href = href.startswith("http") and not any(p in href for p in ["naukri.com", "linkedin.com", "naukrigulf.com"])
                is_ext_aria = any(t in aria for t in ["company", "employer", "external", "website"])

                if is_ext_text or is_ext_href or is_ext_aria:
                    return {
                        "found": True,
                        "type": "COMPANY_SITE",
                        "element": link,
                        "destination_url": href,
                        "text": (link.inner_text() or "").strip()
                    }
        except Exception:
            pass

        return {"found": False, "type": "NONE"}

    # =========================================================================
    # Stage 2 & 3: External Navigation & Page Opening
    # =========================================================================
    def navigate_to_external_portal(self, context: BrowserContext, current_page: Page,
                                    apply_option: Dict[str, Any],
                                    stop_event: threading.Event = None) -> Tuple[Optional[Page], str, str]:
        """
        Clicks the external application option, handles new tabs, browser popups,
        and same-tab navigation, waiting for the destination page to open.
        Returns (external_tab, final_url, error_message).
        """
        element = apply_option.get("element")
        dest_url = apply_option.get("destination_url") or ""

        self.log(f"🚀 [Stage: {ExternalApplyStages.EXTERNAL_NAVIGATION_STARTED}] Clicking external application option...", "INFO")
        
        pages_before = len(context.pages)
        new_tab = None

        try:
            element.scroll_into_view_if_needed()
            time.sleep(0.3)
            element.hover()
            time.sleep(0.3)

            # Wait for popup/new page or same-page navigation
            try:
                with context.expect_page(timeout=10000) as pinfo:
                    element.click()
                new_tab = pinfo.value
            except Exception:
                # Check if a new tab opened anyway
                if len(context.pages) > pages_before:
                    new_tab = context.pages[-1]
                else:
                    new_tab = current_page
        except Exception as e:
            # Fallback: if element click failed but we extracted direct destination URL
            if dest_url and dest_url.startswith("http"):
                self.log(f"Opening external destination URL directly: {dest_url[:80]}", "INFO")
                try:
                    new_tab = context.new_page()
                    new_tab.goto(dest_url, wait_until="domcontentloaded", timeout=25000)
                except Exception as ex:
                    return (None, "", f"Direct navigation failed: {ex}")
            else:
                return (None, "", f"Navigation click failed: {e}")

        if not new_tab or new_tab.is_closed():
            return (None, "", "Destination page was not created or closed unexpectedly.")

        # Stage: EXTERNAL_PAGE_OPENED
        try:
            new_tab.bring_to_front()
            time.sleep(2.0)
            new_tab.wait_for_load_state("domcontentloaded", timeout=20000)
        except Exception:
            pass

        final_url = new_tab.url
        self.log(f"🌐 [Stage: {ExternalApplyStages.EXTERNAL_PAGE_OPENED}] Landed on external portal: {final_url[:85]}", "INFO")
        return (new_tab, final_url, "")

    # =========================================================================
    # Stage 4: Verify the External Job
    # =========================================================================
    def verify_external_job(self, page: Page, original_title: str, original_company: str) -> Tuple[bool, str, str]:
        """
        Verifies that the external page is active and corresponds to the target job.
        Checks for 404, expired postings, closed listings, or completely unrelated pages.
        Returns (is_valid, stage_or_reason, explanation).
        """
        try:
            url_lower = (page.url or "").lower()
            page_text = page.evaluate("() => (document.body ? document.body.innerText : '').toLowerCase()")
            page_title = (page.title() or "").lower()

            # 1. Check 404 / Expired / Closed signals
            expired_signals = [
                "404 not found", "page not found", "job has expired", "job no longer available",
                "this job is closed", "position is closed", "no longer accepting applications",
                "this listing has ended", "job posting has expired", "requisition is closed",
                "this position has been filled", "the job you are looking for is no longer open"
            ]
            for sig in expired_signals:
                if sig in page_text or sig in page_title:
                    return (False, ExternalFailureReasons.EXTERNAL_PAGE_UNAVAILABLE,
                            f"The external job posting is no longer available ('{sig}').")

            # 2. Check title / company alignment (token overlap)
            # Tokenize title and company (strip common noise words)
            stop_words = {"senior", "lead", "junior", "developer", "engineer", "software", "tech", "technologies", "solutions", "pvt", "ltd", "inc"}
            title_tokens = [w for w in re.findall(r'[a-zA-Z0-9]+', original_title.lower()) if len(w) > 2 and w not in stop_words]
            comp_tokens = [w for w in re.findall(r'[a-zA-Z0-9]+', original_company.lower()) if len(w) > 2 and w not in stop_words]

            # If external page is an ATS with job details (e.g. Greenhouse, Lever, Workday)
            has_title_match = any(t in page_text or t in page_title for t in title_tokens) if title_tokens else True
            has_comp_match = any(c in page_text or c in page_title or c in url_lower for c in comp_tokens) if comp_tokens else True

            # If page is completely generic (e.g. redirected to company home page without job reference)
            if not has_title_match and not has_comp_match and "job" not in url_lower and "career" not in url_lower:
                return (False, ExternalFailureReasons.EXTERNAL_JOB_MISMATCH,
                        f"External destination page does not match {original_title} @ {original_company}.")

            self.log(f"✅ [Stage: {ExternalApplyStages.EXTERNAL_JOB_VERIFIED}] External job listing verified on company portal.", "INFO")
            return (True, ExternalApplyStages.EXTERNAL_JOB_VERIFIED, "Job verified successfully.")
        except Exception as e:
            return (False, ExternalFailureReasons.EXTERNAL_PAGE_UNAVAILABLE, f"Job verification check failed: {e}")

    # =========================================================================
    # Stage 5: Application Form Detection & Reveal
    # =========================================================================
    def detect_and_reveal_application_form(self, page: Page, stop_event: threading.Event = None) -> Tuple[bool, str, str]:
        """
        Deep, bounded inspection of external career portal:
        1. Waits for SPA hydration and dynamic rendering.
        2. Detects explicit page states (Already Applied, Job Expired, CAPTCHA, Login Required).
        3. Clicks intermediate 'Apply' / 'Apply Now' buttons if present to reveal hidden forms.
        4. Inspects DOM, supported iframes, forms, inputs, and textareas.
        Returns: (has_form, code, explanation)
        """
        if not page or page.is_closed():
            return (False, ExternalFailureReasons.EXTERNAL_PAGE_UNAVAILABLE, "Browser page is closed or unavailable.")

        # 1. Bounded wait for dynamic content to render
        try:
            page.wait_for_load_state("domcontentloaded", timeout=12000)
        except Exception:
            pass

        for attempt in range(2):
            page_text = page.evaluate("() => (document.body ? document.body.innerText : '').toLowerCase()")
            page_title = (page.title() or "").lower()
            url_lower = (page.url or "").lower()

            # A. Check Already Applied
            already_applied_signals = [
                "already reviewing your awesome application",
                "already reviewing your application",
                "looks like we are already reviewing",
                "you have already applied",
                "application has already been submitted",
                "already applied for this job",
                "you already applied to this position",
                "application already received"
            ]
            for sig in already_applied_signals:
                if sig in page_text:
                    return (False, "ALREADY_APPLIED", f"External portal confirms: '{sig}'")

            # B. Check Job Expired / Closed
            closed_signals = [
                "no longer accepting applications",
                "this job is closed",
                "position is closed",
                "job has expired",
                "this listing has ended",
                "job posting has expired",
                "this requisition has been closed",
                "the position you are looking for has been filled",
                "job is no longer available"
            ]
            for sig in closed_signals:
                if sig in page_text or sig in page_title:
                    return (False, "JOB_EXPIRED", f"External job posting is closed: '{sig}'")

            # C. Check Anti-Bot Access Gate (Cloudflare / DDoS Challenge Wall)
            # Only triggers if the entire page is blocked by an interstitial gateway with no job content/form
            interstitial_titles = ["just a moment...", "attention required! | cloudflare", "security check", "ddos-guard", "cloudflare"]
            if any(t in page_title for t in interstitial_titles):
                has_form_or_job = bool(page.query_selector("input, textarea, form, button:has-text('Apply'), a:has-text('Apply')"))
                if not has_form_or_job:
                    return (False, ExternalFailureReasons.CAPTCHA_REQUIRED, "Access blocked by anti-bot verification gate (Cloudflare/DDoS).")

            # D. Check Login Required (Mandatory account barrier)
            has_password = page.query_selector("input[type='password']")
            has_signin_prompt = any(k in page_text for k in ["sign in to apply", "log in to apply", "create an account to apply", "sign in / register"])
            if has_password and has_signin_prompt and not page.query_selector("button:has-text('Apply without Account'), a:has-text('Apply without Account')"):
                return (False, ExternalFailureReasons.LOGIN_REQUIRED, "External portal requires user account registration or login to apply.")

            # E. Check 404 / Error
            if any(k in page_title or k in page_text for k in ["404 not found", "page not found", "error 404"]):
                return (False, ExternalFailureReasons.EXTERNAL_PAGE_UNAVAILABLE, "External destination page returned 404 / Not Found.")

            # F. Check intermediate Apply buttons to reveal form
            try:
                portal_apply_btn = page.query_selector("""
                    button:has-text('Apply Now'), 
                    a:has-text('Apply Now'), 
                    button:has-text('Apply for this job'), 
                    a:has-text('Apply for this job'),
                    button:has-text('Apply to this job'),
                    a:has-text('Apply to this job'),
                    button:has-text('Start Application'),
                    a:has-text('Start Application'),
                    button:has-text('Apply with Resume'),
                    a:has-text('Apply with Resume'),
                    button:has-text('Apply Manually'),
                    a:has-text('Apply Manually'),
                    button:has-text('Apply'), 
                    a:has-text('Apply')
                """)
                if portal_apply_btn and portal_apply_btn.is_visible() and portal_apply_btn.is_enabled():
                    btn_txt = (portal_apply_btn.inner_text() or "").strip()
                    if not any(bad in btn_txt.lower() for bad in ["filter", "search", "share", "save", "print", "cancel"]):
                        self.log(f"Clicking portal action button: '{btn_txt}' to reveal application form...", "INFO")
                        portal_apply_btn.scroll_into_view_if_needed()
                        time.sleep(0.3)
                        portal_apply_btn.click()
                        time.sleep(2.5)
            except Exception:
                pass

            # G. Inspect DOM for visible application form elements
            form_elements = page.query_selector_all("form, input:not([type='hidden']), textarea, select, [data-automation-id*='form']")
            visible_inputs = [el for el in form_elements if el.is_visible()]
            if len(visible_inputs) >= 1:
                self.log(f"📝 [Stage: {ExternalApplyStages.APPLICATION_FORM_DETECTED}] Application form detected with {len(visible_inputs)} active elements.", "INFO")
                return (True, ExternalApplyStages.APPLICATION_FORM_DETECTED, f"Application form active with {len(visible_inputs)} inputs.")

            # H. Inspect supported iframes
            try:
                for frame in page.frames:
                    if frame != page.main_frame:
                        frame_inputs = frame.query_selector_all("form, input:not([type='hidden']), textarea, select")
                        visible_frame_inputs = [el for el in frame_inputs if el.is_visible()]
                        if len(visible_frame_inputs) >= 1:
                            self.log(f"📝 [Stage: {ExternalApplyStages.APPLICATION_FORM_DETECTED}] Embedded iframe form detected with {len(visible_frame_inputs)} active elements.", "INFO")
                            return (True, ExternalApplyStages.APPLICATION_FORM_DETECTED, "Embedded iframe application form detected.")
            except Exception:
                pass

            if attempt == 0:
                # Scroll slightly and give JavaScript SPA one more moment to hydrate
                try:
                    page.evaluate("window.scrollBy(0, 300)")
                    time.sleep(1.5)
                    page.evaluate("window.scrollBy(0, -300)")
                    time.sleep(0.5)
                except Exception:
                    pass

        return (False, ExternalFailureReasons.APPLICATION_FORM_NOT_FOUND, "No application form controls, iframes, or apply buttons detected on external portal after full inspection.")

    # =========================================================================
    # Master Execution: Handle Complete External Application
    # =========================================================================
    def execute_external_application(self,
                                     context: BrowserContext,
                                     detail_tab: Page,
                                     company_tab: Optional[Page],
                                     title: str,
                                     company: str,
                                     loc_text: str,
                                     exp_text: str,
                                     score: int,
                                     tailored_resume_path: str = "",
                                     original_job_url: str = "",
                                     platform: str = "NAUKRI",
                                     stop_event: threading.Event = None,
                                     requested_location: str = "",
                                     actual_browser_location: str = "") -> Dict[str, Any]:
        """
        Executes the full 12-stage External Company Website Application pipeline:
        EXTERNAL_APPLY_DETECTED -> EXTERNAL_NAVIGATION_STARTED -> EXTERNAL_PAGE_OPENED ->
        EXTERNAL_JOB_VERIFIED -> APPLICATION_FORM_DETECTED -> FORM_ANALYSIS_COMPLETED ->
        FORM_FILLING_STARTED -> RESUME_UPLOAD_STARTED -> RESUME_UPLOAD_COMPLETED ->
        FORM_VALIDATED -> APPLICATION_SUBMITTED -> APPLICATION_CONFIRMED
        """
        if stop_event and stop_event.is_set():
            return {"status": "APPLICATION_SKIPPED", "success": False, "failure_reason": "STOP_REQUESTED", "attempted": False}

        current_stage = ExternalApplyStages.EXTERNAL_PAGE_OPENED
        resume_status = "NOT_STARTED"
        ext_url = (company_tab.url if company_tab else "") or original_job_url

        # Check if external URL, company, or job has already been processed (Applied or Skipped) in DB
        if check_already_applied_db(title=title, company=company, job_url=original_job_url, external_url=ext_url):
            self.log(f"🔁 [DUPLICATE EXTERNAL APPLICATION] Already processed in DB: {title} @ {company} ({ext_url}). Skipping.", "INFO")
            try:
                if company_tab and company_tab != detail_tab and not company_tab.is_closed():
                    company_tab.close()
            except Exception:
                pass
            return {"status": "APPLICATION_SKIPPED", "success": False, "failure_reason": "DUPLICATE_JOB", "attempted": False}

        cand_prof = getCandidateProfileByJobLocation(loc_text or requested_location)
        if not tailored_resume_path:
            tailored_resume_path = cand_prof.get("resume_path", "")

        try:
            # 0. Check if page reports application already submitted / under review
            already_app, already_msg = check_page_already_applied(company_tab)
            if already_app:
                self.log(f"✅ [ALREADY APPLIED] External portal confirms application is already submitted/under review: {already_msg}", "SUCCESS")
                record_application(
                    job_title=title, company_name=company, location=loc_text,
                    job_url=original_job_url or ext_url,
                    status="APPLIED", apply_type="COMPANY_WEBSITE", match_score=score,
                    notes=f"External portal verified: {already_msg}",
                    execution_stage="ALREADY_APPLIED_PORTAL_BANNER",
                    confirmation_type="PORTAL_UNDER_REVIEW_BANNER",
                    confirmation_message=already_msg,
                    detailed_explanation="External career portal reports application has already been submitted and is currently under review.",
                    application_attempted=True,
                    application_submitted=True,
                    application_confirmed=True,
                    external_application_url=ext_url,
                    resume_upload_status="ATTACHED_ON_PORTAL",
                    platform=platform, requested_location=requested_location, actual_browser_location=actual_browser_location
                )
                try:
                    if company_tab and company_tab != detail_tab and not company_tab.is_closed():
                        company_tab.close()
                except Exception:
                    pass
                return {"status": "APPLICATION_CONFIRMED", "success": True, "already_applied": True}

            # 1. Verify destination page is valid and corresponds to the job
            is_valid, verify_code, verify_explanation = self.verify_external_job(company_tab, title, company)
            if not is_valid:
                screenshot = self.capture_screenshot(company_tab, "ext_verify_failed", company)
                record_application(
                    job_title=title, company_name=company, location=loc_text,
                    job_url=original_job_url or ext_url,
                    status="APPLICATION_SKIPPED", apply_type="COMPANY_WEBSITE", match_score=score,
                    notes=verify_explanation,
                    failure_reason=verify_code,
                    skip_reason_code=verify_code,
                    execution_stage=verify_code,
                    detailed_explanation=verify_explanation,
                    application_attempted=False,
                    application_submitted=False,
                    application_confirmed=False,
                    screenshot_reference=screenshot,
                    external_application_url=ext_url,
                    resume_upload_status="NOT_STARTED",
                    platform=platform, requested_location=requested_location, actual_browser_location=actual_browser_location
                )
                self.log(f"⚠️ External Job Verification Failed for {company}: {verify_explanation}", "WARNING")
                return {"status": "APPLICATION_SKIPPED", "success": False, "failure_reason": verify_code, "attempted": False}

            current_stage = ExternalApplyStages.EXTERNAL_JOB_VERIFIED

            # 2. Detect / Reveal Application Form
            has_form, form_code, form_expl = self.detect_and_reveal_application_form(company_tab, stop_event)
            if not has_form:
                if form_code == "ALREADY_APPLIED":
                    self.log(f"✅ [ALREADY APPLIED] External portal confirms application is already submitted/under review: {form_expl}", "SUCCESS")
                    record_application(
                        job_title=title, company_name=company, location=loc_text,
                        job_url=original_job_url or ext_url,
                        status="APPLIED", apply_type="COMPANY_WEBSITE", match_score=score,
                        notes=f"External portal verified: {form_expl}",
                        execution_stage="SUBMISSION_VERIFIED",
                        detailed_explanation="External career portal reports application has already been submitted and is currently under review.",
                        application_attempted=True,
                        application_submitted=True,
                        application_confirmed=True,
                        confirmation_type="PORTAL_UNDER_REVIEW_BANNER",
                        confirmation_message=form_expl,
                        external_application_url=ext_url,
                        resume_upload_status="ATTACHED_ON_PORTAL",
                        platform=platform, requested_location=requested_location, actual_browser_location=actual_browser_location
                    )
                    try:
                        if company_tab and company_tab != detail_tab and not company_tab.is_closed():
                            company_tab.close()
                    except Exception:
                        pass
                    return {"status": "APPLIED", "success": True, "already_applied": True}

                elif form_code == ExternalFailureReasons.LOGIN_REQUIRED:
                    self.log(f"🔒 Login/Registration required on {company} portal. Leaving tab OPEN in Chrome for candidate!", "WARNING")
                    company_tab.bring_to_front()
                    screenshot = self.capture_screenshot(company_tab, "login_required", company)
                    record_application(
                        job_title=title, company_name=company, location=loc_text, job_url=original_job_url or ext_url,
                        status="NEEDS_INPUT", apply_type="COMPANY_WEBSITE", match_score=score,
                        notes="Candidate account login/registration required on company portal. Tab kept open.",
                        failure_reason=ExternalFailureReasons.LOGIN_REQUIRED,
                        skip_reason_code="LOGIN_REQUIRED",
                        execution_stage="ACTION_BUTTON_DETECTION",
                        detailed_explanation=f"Application paused: {form_expl}. Tab preserved open in Chrome for candidate login.",
                        application_attempted=True, application_submitted=False, application_confirmed=False,
                        screenshot_reference=screenshot,
                        external_application_url=ext_url,
                        platform=platform, requested_location=requested_location, actual_browser_location=actual_browser_location
                    )
                    return {"status": "NEEDS_INPUT", "success": False, "failure_reason": "LOGIN_REQUIRED", "attempted": True}

                elif form_code == ExternalFailureReasons.CAPTCHA_REQUIRED:
                    self.log(f"🤖 CAPTCHA challenge detected on {company} portal. Leaving tab OPEN in Chrome for candidate!", "WARNING")
                    company_tab.bring_to_front()
                    screenshot = self.capture_screenshot(company_tab, "captcha_required", company)
                    record_application(
                        job_title=title, company_name=company, location=loc_text, job_url=original_job_url or ext_url,
                        status="NEEDS_INPUT", apply_type="COMPANY_WEBSITE", match_score=score,
                        notes="CAPTCHA verification required on company portal. Tab kept open.",
                        failure_reason="CAPTCHA_REQUIRED",
                        skip_reason_code="CAPTCHA_REQUIRED",
                        execution_stage="FORM_FILLING_STARTED",
                        detailed_explanation=f"Application paused: {form_expl}. Tab preserved open in Chrome for candidate to solve.",
                        application_attempted=True, application_submitted=False, application_confirmed=False,
                        screenshot_reference=screenshot,
                        external_application_url=ext_url,
                        platform=platform, requested_location=requested_location, actual_browser_location=actual_browser_location
                    )
                    return {"status": "NEEDS_INPUT", "success": False, "failure_reason": "CAPTCHA_REQUIRED", "attempted": True}

                elif form_code == "JOB_EXPIRED":
                    self.log(f"⚠️ External job is closed or no longer accepting applications on {company} portal.", "WARNING")
                    record_application(
                        job_title=title, company_name=company, location=loc_text, job_url=original_job_url or ext_url,
                        status="SKIPPED", apply_type="COMPANY_WEBSITE", match_score=score,
                        notes=form_expl,
                        failure_reason="JOB_EXPIRED",
                        skip_reason_code="JOB_EXPIRED",
                        execution_stage="ELIGIBILITY_VERIFICATION",
                        detailed_explanation=form_expl,
                        application_attempted=False, application_submitted=False, application_confirmed=False,
                        external_application_url=ext_url,
                        platform=platform, requested_location=requested_location, actual_browser_location=actual_browser_location
                    )
                    try:
                        if company_tab and company_tab != detail_tab and not company_tab.is_closed():
                            company_tab.close()
                    except Exception:
                        pass
                    return {"status": "SKIPPED", "success": False, "failure_reason": "JOB_EXPIRED", "attempted": False}

                # Check if Job Description contains hiring email as alternative!
                self.log(f"Checking for direct hiring emails on {company} external portal...", "INFO")
                emails = extract_hiring_emails(company_tab)
                if emails:
                    target_email = emails[0]
                    self.log(f"📧 [Email Application] Found hiring email on portal: {target_email}! Opening Outlook...", "INFO")
                    opened, reason = open_outlook_for_job_application(
                        recipient_email=target_email,
                        job_title=title,
                        company_name=company,
                        location=loc_text,
                        context_text=f"Company: {company}, Role: {title}"
                    )
                    if opened:
                        record_application(
                            job_title=title, company_name=company, location=loc_text,
                            job_url=original_job_url or ext_url,
                            status="APPLIED", apply_type="DIRECT_EMAIL", match_score=score,
                            notes=f"Form not found, but composed direct application email via Outlook to {target_email}.",
                            execution_stage="SUBMISSION_VERIFIED",
                            application_attempted=True,
                            application_submitted=True,
                            application_confirmed=True,
                            confirmation_type="OUTLOOK_COMPOSED",
                            confirmation_message=f"Direct job application email opened in Outlook for {target_email}",
                            external_application_url=ext_url,
                            resume_upload_status="ATTACHED_IN_OUTLOOK",
                            platform=platform, requested_location=requested_location, actual_browser_location=actual_browser_location
                        )
                        self.log(f"✅ Application email opened via Outlook for {company} ({target_email})!", "SUCCESS")
                        return {"status": "APPLIED", "success": True, "attempted": True}

                screenshot = self.capture_screenshot(company_tab, "ext_form_not_found", company)
                record_application(
                    job_title=title, company_name=company, location=loc_text,
                    job_url=original_job_url or ext_url,
                    status="SKIPPED", apply_type="COMPANY_WEBSITE", match_score=score,
                    notes=f"No application form, button, or link could be located on external portal for {company}.",
                    failure_reason=ExternalFailureReasons.APPLICATION_FORM_NOT_FOUND,
                    skip_reason_code="APPLY_OPTION_NOT_AVAILABLE",
                    execution_stage="ACTION_BUTTON_DETECTION",
                    detailed_explanation="The external page was reached, but no actionable application form or input controls were found after full inspection.",
                    application_attempted=False,
                    application_submitted=False,
                    application_confirmed=False,
                    screenshot_reference=screenshot,
                    external_application_url=ext_url,
                    resume_upload_status="NOT_STARTED",
                    platform=platform, requested_location=requested_location, actual_browser_location=actual_browser_location
                )
                self.log(f"⚠️ No application form found on {company} website. Marked APPLY_OPTION_NOT_AVAILABLE.", "WARNING")
                return {"status": "SKIPPED", "success": False, "failure_reason": ExternalFailureReasons.APPLICATION_FORM_NOT_FOUND, "attempted": False}

            current_stage = ExternalApplyStages.APPLICATION_FORM_DETECTED

            # 3. Resume Upload Handling (Priority PASS 1: Auto-attach candidate tailored resume)
            current_stage = ExternalApplyStages.RESUME_UPLOAD_STARTED
            self.log(f"📎 [Stage: {ExternalApplyStages.RESUME_UPLOAD_STARTED}] Locating resume upload control...", "INFO")
            upload_result = upload_resume_file(company_tab, resume_path=tailored_resume_path, location_hint=loc_text)
            if upload_result.get("success"):
                resume_status = "UPLOADED"
                current_stage = ExternalApplyStages.RESUME_UPLOAD_COMPLETED
                self.log(f"✅ [Stage: {ExternalApplyStages.RESUME_UPLOAD_COMPLETED}] Uploaded CV: {upload_result.get('filename')}", "SUCCESS")
                time.sleep(0.8)
            else:
                if upload_result.get("error") == "FILE_INPUT_NOT_FOUND":
                    resume_status = "NOT_REQUIRED"
                    self.log("No file input found on this initial view. Will re-check during question filling.", "INFO")
                else:
                    resume_status = "FAILED"
                    self.log(f"⚠️ Resume upload warning: {upload_result.get('error')}", "WARNING")

            # 4. Form Analysis & Filling
            current_stage = ExternalApplyStages.FORM_ANALYSIS_COMPLETED
            self.log(f"🔍 [Stage: {ExternalApplyStages.FORM_ANALYSIS_COMPLETED}] Analyzing questions and field controls...", "INFO")

            current_stage = ExternalApplyStages.FORM_FILLING_STARTED
            self.log(f"✍️ [Stage: {ExternalApplyStages.FORM_FILLING_STARTED}] Filling candidate verified profile information...", "INFO")

            fill_res = process_and_fill_complete_form(
                page=company_tab,
                qa_engine_instance=self.qa_engine,
                stop_event=stop_event,
                company_name=company,
                job_title=title,
                logger_fn=self.log,
                location_hint=loc_text,
                resume_path=tailored_resume_path
            )

            # Check for safety boundary: payment
            if isinstance(fill_res, dict) and fill_res.get("is_payment"):
                self.log(f"🚨 Payment or transaction requested on {company} portal. Blocked by safety boundary!", "ERROR")
                record_application(
                    job_title=title, company_name=company, location=loc_text, job_url=original_job_url or ext_url,
                    status="APPLICATION_FAILED", apply_type="COMPANY_WEBSITE", match_score=score,
                    notes="Payment requested on external portal. Blocked by safety boundary.",
                    failure_reason=ExternalFailureReasons.APPLICATION_BLOCKED,
                    skip_reason_code=ExternalFailureReasons.APPLICATION_BLOCKED,
                    execution_stage=ExternalApplyStages.FORM_FILLING_STARTED,
                    detailed_explanation="External portal requested financial payment/fee. Blocked by system safety policy.",
                    application_attempted=True, application_submitted=False, application_confirmed=False,
                    external_application_url=ext_url, platform=platform, requested_location=requested_location, actual_browser_location=actual_browser_location
                )
                return {"status": "APPLICATION_FAILED", "success": False, "failure_reason": "PAYMENT_BLOCKED", "attempted": True}

            # Check if mandatory question or CAPTCHA requires human input
            if isinstance(fill_res, dict) and (fill_res.get("needs_user_input") or fill_res.get("status") == "NEEDS_USER_INPUT" or fill_res.get("is_captcha")):
                reason = fill_res.get("reason", "MANDATORY_QUESTION_UNANSWERED")
                if fill_res.get("is_captcha"):
                    reason = "CAPTCHA_REQUIRED: Human verification required. Field kept empty in Chrome window."
                self.log(f"⚠️ Mandatory question or CAPTCHA requires candidate input: {reason}. Tab kept OPEN in Chrome!", "WARNING")
                company_tab.bring_to_front()
                record_application(
                    job_title=title, company_name=company, location=loc_text, job_url=original_job_url or ext_url,
                    status="NEEDS_USER_INPUT", apply_type="COMPANY_WEBSITE", match_score=score,
                    notes=f"Form requires candidate verification: {reason}. Tab kept open in Chrome.",
                    failure_reason="CAPTCHA_REQUIRED" if fill_res.get("is_captcha") else ExternalFailureReasons.MISSING_REQUIRED_INFORMATION,
                    skip_reason_code="CAPTCHA_REQUIRED" if fill_res.get("is_captcha") else ExternalFailureReasons.MISSING_REQUIRED_INFORMATION,
                    execution_stage=ExternalApplyStages.FORM_FILLING_STARTED,
                    detailed_explanation=f"Application paused for user verification: {reason}. Tab left open for candidate to complete in browser.",
                    application_attempted=True, application_submitted=False, application_confirmed=False,
                    external_application_url=ext_url, platform=platform, requested_location=requested_location, actual_browser_location=actual_browser_location
                )
                return {"status": "NEEDS_USER_INPUT", "success": False, "failure_reason": reason, "attempted": True}

            # Post-filling Resume Check
            if resume_status != "UPLOADED":
                upload_result = upload_resume_file(company_tab, resume_path=tailored_resume_path, location_hint=loc_text)
                if upload_result.get("success"):
                    resume_status = "UPLOADED"
                    current_stage = ExternalApplyStages.RESUME_UPLOAD_COMPLETED
                    self.log(f"✅ [Stage: {ExternalApplyStages.RESUME_UPLOAD_COMPLETED}] Uploaded CV: {upload_result.get('filename')}", "SUCCESS")

            # 5. Pre-Submission Form Validation
            current_stage = ExternalApplyStages.FORM_VALIDATED
            val_res = validate_entire_form(company_tab)
            if not val_res.get("isValid", True):
                empty_fields = val_res.get("emptyMandatory", [])
                err_msgs = val_res.get("errorMessages", [])
                self.log(f"⚠️ Form validation failed: Empty mandatory fields {empty_fields}, Errors {err_msgs}", "WARNING")
                # If there are unresolved mandatory errors, keep tab open
                screenshot = self.capture_screenshot(company_tab, "form_val_failed", company)
                record_application(
                    job_title=title, company_name=company, location=loc_text, job_url=original_job_url or ext_url,
                    status="NEEDS_USER_INPUT", apply_type="COMPANY_WEBSITE", match_score=score,
                    notes=f"Form validation pending: {empty_fields or err_msgs}. Tab kept open in Chrome.",
                    failure_reason=ExternalFailureReasons.FORM_VALIDATION_FAILED,
                    skip_reason_code=ExternalFailureReasons.FORM_VALIDATION_FAILED,
                    execution_stage=ExternalFailureReasons.FORM_VALIDATION_FAILED,
                    detailed_explanation=f"Pre-submission validation detected incomplete required fields: {', '.join(empty_fields or err_msgs)}.",
                    application_attempted=True, application_submitted=False, application_confirmed=False,
                    screenshot_reference=screenshot,
                    external_application_url=ext_url,
                    resume_upload_status=resume_status,
                    platform=platform, requested_location=requested_location, actual_browser_location=actual_browser_location
                )
                company_tab.bring_to_front()
                return {"status": "NEEDS_USER_INPUT", "success": False, "failure_reason": "FORM_VALIDATION_FAILED", "attempted": True}

            self.log(f"✅ [Stage: {ExternalApplyStages.FORM_VALIDATED}] Form inputs validated successfully.", "INFO")

            # 5b. Centralized Pre-Submission Contact & Location Validation
            self.log(f"📋 Candidate Contact Audit: Profile={cand_prof['profile_name']} | CountryCode={cand_prof['country_code']} | Phone={cand_prof['masked_phone']} | LocationValidation=PASSED", "SUCCESS")

            # 6. Check for Genuine Interactive CAPTCHA Challenge or Password Protection
            # Strictly filters out invisible background tokens, invisible badges (.grecaptcha-badge, size=invisible), and background Turnstile
            captcha_check = company_tab.evaluate(r"""() => {
                // A. Active reCAPTCHA image puzzle popup (bframe)
                const bframes = Array.from(document.querySelectorAll("iframe[src*='recaptcha/api2/bframe'], iframe[src*='recaptcha/enterprise/bframe']"));
                for (const bf of bframes) {
                    const style = window.getComputedStyle(bf);
                    if (style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0') {
                        const rect = bf.getBoundingClientRect();
                        if (rect.width > 120 && rect.height > 120 && rect.top < window.innerHeight && rect.bottom > 0) {
                            return { hasChallenge: true, type: "RECAPTCHA_IMAGE_PUZZLE" };
                        }
                    }
                }

                // B. Background reCAPTCHA anchor iframes do not block form filling unless an explicit bframe puzzle pops up
                // (Outer iframe tags do not hold internal aria-checked attributes)

                // C. hCaptcha Interactive Challenge
                const hcaptchas = Array.from(document.querySelectorAll("iframe[src*='hcaptcha.com']"));
                for (const h of hcaptchas) {
                    const src = (h.getAttribute('src') || '').toLowerCase();
                    if (src.includes('size=invisible')) continue;
                    const style = window.getComputedStyle(h);
                    if (style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0') {
                        const rect = h.getBoundingClientRect();
                        if (rect.width > 100 && rect.height > 35) {
                            return { hasChallenge: true, type: "HCAPTCHA_CHECKBOX" };
                        }
                    }
                }

                // D. Cloudflare Turnstile Interactive Challenge
                const cfWidgets = Array.from(document.querySelectorAll("iframe[src*='challenges.cloudflare.com'], .cf-turnstile"));
                for (const cf of cfWidgets) {
                    if (cf.getAttribute('data-size') === 'invisible') continue;
                    const style = window.getComputedStyle(cf);
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue;
                    const rect = cf.getBoundingClientRect();
                    if (rect.width > 100 && rect.height > 35) {
                        const cfResp = document.querySelector("[name='cf-turnstile-response']");
                        if (!cfResp || !cfResp.value) {
                            const bodyText = (document.body ? document.body.innerText : '').toLowerCase();
                            if (bodyText.includes('verify you are human') || bodyText.includes('please check the box')) {
                                return { hasChallenge: true, type: "CLOUDFLARE_TURNSTILE" };
                            }
                        }
                    }
                }

                // E. Explicit Text CAPTCHA Input (reading characters from visual image)
                const textInputs = Array.from(document.querySelectorAll("input[type='text'], input:not([type])"));
                for (const inp of textInputs) {
                    const style = window.getComputedStyle(inp);
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue;
                    const rect = inp.getBoundingClientRect();
                    if (rect.width <= 25 || rect.height <= 15) continue;
                    let label = inp.labels && inp.labels[0] ? inp.labels[0].innerText.toLowerCase() : '';
                    const parent = inp.closest('.form-group, .field, div');
                    const pText = parent ? (parent.innerText || '').toLowerCase() : '';
                    const isTextCap = /(?:enter|type)\s+(?:the\s+)?(?:characters|letters|numbers|code|text)\s+(?:shown|from\s+the\s+image|in\s+the\s+image|above|below)/i.test(label || pText)
                        || /\b(?:captcha[-_ ]?code|security[-_ ]?image[-_ ]?code|image[-_ ]?captcha)\b/i.test(label || pText);
                    if (isTextCap && !inp.value) {
                        return { hasChallenge: true, type: "TEXT_CAPTCHA_INPUT" };
                    }
                }

                return { hasChallenge: false };
            }""")
            has_captcha = bool(captcha_check and captcha_check.get("hasChallenge"))

            has_password = False
            password_candidates = company_tab.query_selector_all("input[type='password']")
            for p in password_candidates:
                try:
                    if p.is_visible():
                        has_password = True
                        break
                except Exception:
                    continue

            if has_captcha or has_password:
                reason_code = ExternalFailureReasons.CAPTCHA_REQUIRED if has_captcha else ExternalFailureReasons.LOGIN_REQUIRED
                self.log(f"🤖 {reason_code} detected on {company} portal. Leaving tab OPEN in Chrome for you!", "WARNING")
                company_tab.bring_to_front()
                screenshot = self.capture_screenshot(company_tab, "captcha_login_required", company)
                record_application(
                    job_title=title, company_name=company, location=loc_text, job_url=original_job_url or ext_url,
                    status="NEEDS_INPUT", apply_type="COMPANY_WEBSITE", match_score=score,
                    notes="Form auto-filled. CAPTCHA or Account Login required. Tab kept open.",
                    failure_reason=reason_code,
                    skip_reason_code=reason_code,
                    execution_stage="FORM_IN_PROGRESS",
                    detailed_explanation=f"{reason_code} encountered on external site. Tab preserved in Chrome for user completion.",
                    application_attempted=True, application_submitted=False, application_confirmed=False,
                    screenshot_reference=screenshot,
                    external_application_url=ext_url,
                    resume_upload_status=resume_status,
                    platform=platform, requested_location=requested_location, actual_browser_location=actual_browser_location
                )
                return {"status": "NEEDS_INPUT", "success": False, "failure_reason": reason_code, "attempted": True}

            # 7. Check Authorization to Auto-Submit External Portals
            if not agent_config_manager.is_authorized("auto_submit_company_portal"):
                self.log(f"Form filled on {company} portal. Auto-submit on company portal is disabled by config. Tab kept OPEN for review.", "INFO")
                company_tab.bring_to_front()
                record_application(
                    job_title=title, company_name=company, location=loc_text, job_url=original_job_url or ext_url,
                    status="SUBMITTED_PENDING_CONFIRMATION", apply_type="COMPANY_WEBSITE", match_score=score,
                    notes="Form filled. Company portal auto-submit not authorized. Tab kept open for candidate review.",
                    failure_reason="AUTO_SUBMIT_COMPANY_PORTAL_NOT_AUTHORIZED",
                    skip_reason_code="USER_APPROVAL_REQUIRED",
                    execution_stage="FORM_COMPLETED",
                    detailed_explanation="External application was prepared and filled, but auto-submit is set to require candidate review.",
                    application_attempted=True, application_submitted=False, application_confirmed=False,
                    external_application_url=ext_url,
                    resume_upload_status=resume_status,
                    platform=platform, requested_location=requested_location, actual_browser_location=actual_browser_location
                )
                return {"status": "SUBMITTED_PENDING_CONFIRMATION", "success": False, "failure_reason": "AUTO_SUBMIT_NOT_AUTHORIZED", "attempted": True}

            # 8. Submit Application
            current_stage = ExternalApplyStages.APPLICATION_SUBMITTED
            self.log(f"🚀 [Stage: {ExternalApplyStages.APPLICATION_SUBMITTED}] Locating and engaging submission button on {company} portal...", "INFO")

            # 8a. Pre-submit Event Flushing on all inputs across frames
            # Dispatches input, change, and blur to ensure React/Vue/Angular state updates mark the form as valid
            all_frames = [company_tab.main_frame] + [f for f in getattr(company_tab, 'frames', []) if f != company_tab.main_frame]
            for fr in all_frames:
                try:
                    fr.evaluate("""() => {
                        const controls = Array.from(document.querySelectorAll('input, select, textarea'));
                        for (const c of controls) {
                            c.dispatchEvent(new Event('input', { bubbles: true }));
                            c.dispatchEvent(new Event('change', { bubbles: true }));
                            c.dispatchEvent(new Event('blur', { bubbles: true }));
                        }
                    }""")
                except Exception:
                    pass
            time.sleep(0.5)

            # 8b. Robust Multi-Frame Submit Button Discovery
            submit_btn = None

            # Try button service first
            try:
                submit_btn = self.button_service.find_action_button(company_tab, [ButtonCategory.SUBMIT, ButtonCategory.APPLY])
            except Exception as e:
                self.log(f"Button service search note: {e}", "DEBUG")

            # Fallback selectors across main frame and all child iframes
            if not submit_btn:
                candidate_submit_selectors = [
                    "button[type='submit']",
                    "input[type='submit']",
                    "button:has-text('Submit Application')",
                    "button:has-text('Submit application')",
                    "button:has-text('Submit Profile')",
                    "button:has-text('Submit profile')",
                    "button:has-text('Submit')",
                    "button:has-text('Send Application')",
                    "button:has-text('Send application')",
                    "button:has-text('Apply Now')",
                    "button:has-text('Apply now')",
                    "button:has-text('Apply')",
                    "[role='button']:has-text('Submit')",
                    "[role='button']:has-text('Apply')",
                    "button[id*='submit' i]",
                    "button[class*='submit' i]",
                    "input[value*='Submit' i]",
                    "form button"
                ]

                for fr in all_frames:
                    try:
                        for sel in candidate_submit_selectors:
                            loc = fr.locator(sel)
                            count = loc.count()
                            for idx in range(count):
                                candidate = loc.nth(idx)
                                try:
                                    if candidate.is_visible():
                                        submit_btn = candidate
                                        break
                                except Exception:
                                    continue
                            if submit_btn:
                                break
                    except Exception:
                        continue
                    if submit_btn:
                        break

            # 8c. Ensure Button is Engaged (Wait for Enabled & Multi-Tier Execution)
            clicked = False
            if submit_btn:
                try:
                    submit_btn.scroll_into_view_if_needed(timeout=2000)
                except Exception:
                    pass

                # Bounded wait for button to become enabled (up to 4 seconds)
                start_wait = time.time()
                while time.time() - start_wait < 4.0:
                    try:
                        if submit_btn.is_enabled():
                            break
                    except Exception:
                        pass
                    time.sleep(0.4)

                # Attempt Tier 1: Standard Playwright click
                try:
                    submit_btn.hover(timeout=1500)
                    time.sleep(0.2)
                    submit_btn.click(timeout=3000)
                    clicked = True
                    self.log(f"Standard click executed on {company} submit button.", "DEBUG")
                except Exception as e:
                    self.log(f"Standard click failed ({e}), attempting force click...", "DEBUG")

                # Attempt Tier 2: Force click
                if not clicked:
                    try:
                        submit_btn.click(force=True, timeout=3000)
                        clicked = True
                        self.log(f"Force click executed on {company} submit button.", "DEBUG")
                    except Exception as e:
                        self.log(f"Force click failed ({e}), attempting JS dispatch click...", "DEBUG")

                # Attempt Tier 3: Direct JS click dispatch with complete pointer/mouse sequence
                if not clicked:
                    try:
                        submit_btn.evaluate("""(btn) => {
                            btn.removeAttribute('disabled');
                            btn.removeAttribute('aria-disabled');
                            btn.classList.remove('disabled');
                            btn.scrollIntoView({block: 'center', behavior: 'instant'});
                            btn.focus();
                            btn.dispatchEvent(new MouseEvent('pointerdown', {bubbles: true, cancelable: true}));
                            btn.dispatchEvent(new MouseEvent('mousedown', {bubbles: true, cancelable: true}));
                            btn.dispatchEvent(new MouseEvent('mouseup', {bubbles: true, cancelable: true}));
                            btn.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
                            btn.click();
                        }""")
                        clicked = True
                        self.log(f"JS direct click dispatched on {company} submit button.", "DEBUG")
                    except Exception as e:
                        self.log(f"JS direct click failed ({e}), attempting form requestSubmit...", "DEBUG")

                # Attempt Tier 4: Form requestSubmit dispatch
                if not clicked:
                    try:
                        submit_btn.evaluate("""(btn) => {
                            const form = btn.closest('form');
                            if (form) {
                                if (typeof form.requestSubmit === 'function') {
                                    form.requestSubmit(btn);
                                } else {
                                    form.submit();
                                }
                            }
                        }""")
                        clicked = True
                        self.log(f"Form requestSubmit dispatched on {company} portal.", "DEBUG")
                    except Exception as e:
                        self.log(f"Form requestSubmit failed: {e}", "DEBUG")

            # 8d. Fallback if no specific button locator: find active form or SPA submit element across frames
            if not clicked:
                for fr in all_frames:
                    try:
                        res = fr.evaluate("""() => {
                            // First, try forms
                            const forms = Array.from(document.querySelectorAll('form'));
                            for (const f of forms) {
                                const btn = f.querySelector('button[type="submit"], input[type="submit"], button, [role="button"]');
                                if (btn) {
                                    btn.removeAttribute('disabled');
                                    btn.removeAttribute('aria-disabled');
                                    btn.scrollIntoView({block: 'center'});
                                    btn.click();
                                    return true;
                                }
                                if (typeof f.requestSubmit === 'function') {
                                    f.requestSubmit();
                                    return true;
                                }
                            }
                            // Second, try any standalone SPA submit button / role="button" (e.g. Ashby/Next.js without form tag)
                            const candidates = Array.from(document.querySelectorAll('button, input[type="submit"], [role="button"], a.btn, a[class*="submit"], a[class*="apply"]')).filter(b => {
                                const s = window.getComputedStyle(b);
                                if (s.display === 'none' || s.visibility === 'hidden') return false;
                                const t = (b.innerText || b.value || '').trim().toLowerCase();
                                return t.includes('submit') || t.includes('apply');
                            });
                            if (candidates.length > 0) {
                                const b = candidates[0];
                                b.removeAttribute('disabled');
                                b.removeAttribute('aria-disabled');
                                b.classList.remove('disabled');
                                b.scrollIntoView({block: 'center'});
                                b.focus();
                                b.dispatchEvent(new MouseEvent('click', {bubbles: true}));
                                b.click();
                                return true;
                            }
                            return false;
                        }""")
                        if res:
                            clicked = True
                            self.log(f"Fallback form submission dispatched on {company} portal.", "DEBUG")
                            break
                    except Exception:
                        pass

            # 9. Verify Confirmation Signals Across Frames (Dynamic Polling Loop)
            conf_script = """() => {
                const fullText = (document.body ? document.body.innerText : '').toLowerCase();
                const url = window.location.href.toLowerCase();

                // 1. URL confirmation indicators
                const isSuccessUrl = url.includes('success') || url.includes('thank-you') || 
                                     url.includes('thankyou') || url.includes('confirmation') || 
                                     url.includes('submitted') || url.includes('complete');

                // 2. Comprehensive success message patterns (including user portal's exact message)
                const successPatterns = [
                    'we received your application',
                    'we have received your application',
                    'received your application',
                    'application received',
                    'application has been received',
                    'will contact you shortly',
                    'contact you shortly',
                    'thank you for applying',
                    'thanks for applying',
                    'thank you for your application',
                    'thanks for your application',
                    'application submitted',
                    'application has been submitted',
                    'successfully submitted',
                    'successfully applied',
                    'applied successfully',
                    'your application was submitted',
                    'your application has been sent',
                    'your response has been recorded',
                    'application complete',
                    'application completed',
                    'submission successful',
                    'we have received your details',
                    'we\\'ve received your application',
                    'submission received',
                    'application received and recorded'
                ];

                let matchedPattern = '';
                for (const p of successPatterns) {
                    if (fullText.includes(p)) {
                        matchedPattern = p;
                        break;
                    }
                }

                // 3. Success container badges / alerts (e.g. .alert-success as shown in screenshot)
                let containerSuccess = false;
                const successContainers = Array.from(document.querySelectorAll(
                    '.alert-success, .success, [class*="success"], [class*="alert-success"], .confirmation-message, [role="alert"]'
                ));
                for (const c of successContainers) {
                    const cText = (c.innerText || '').toLowerCase();
                    for (const p of successPatterns) {
                        if (cText.includes(p)) {
                            containerSuccess = true;
                            if (!matchedPattern) matchedPattern = p;
                            break;
                        }
                    }
                    if (containerSuccess) break;
                }

                // 4. Strict visible genuine error check (NEVER :invalid pseudo-selector!)
                const visibleErrorElements = Array.from(document.querySelectorAll(
                    '.alert-danger, .invalid-feedback, .error-message, span.error, div.error'
                )).filter(el => {
                    if (el.offsetParent === null) return false;
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                    const txt = (el.innerText || '').trim().toLowerCase();
                    if (txt.length < 3) return false;
                    if (successPatterns.some(p => txt.includes(p))) return false;
                    return true;
                });
                const hasGenuineErrors = visibleErrorElements.length > 0;

                const isConfirmed = (isSuccessUrl || !!matchedPattern || containerSuccess) && !hasGenuineErrors;

                return {
                    success: isConfirmed,
                    isSuccessUrl: isSuccessUrl,
                    matchedPattern: matchedPattern,
                    containerSuccess: containerSuccess,
                    hasGenuineErrors: hasGenuineErrors
                };
            }"""

            conf_result = {"success": False}
            start_conf = time.time()
            # Poll up to 7.5 seconds for confirmation signals
            while time.time() - start_conf < 7.5:
                for fr in all_frames:
                    try:
                        res = fr.evaluate(conf_script)
                        if res.get("success"):
                            conf_result = res
                            break
                    except Exception:
                        pass
                if conf_result.get("success"):
                    break
                time.sleep(0.75)

            if conf_result.get("success"):
                current_stage = ExternalApplyStages.APPLICATION_CONFIRMED
                pattern_found = conf_result.get("matchedPattern") or "success signal"
                self.log(f"🎉 [Stage: {ExternalApplyStages.APPLICATION_CONFIRMED}] Application successfully submitted and confirmed on {company} portal! ({pattern_found})", "SUCCESS")
                record_application(
                    job_title=title, company_name=company, location=loc_text, job_url=original_job_url or ext_url,
                    status="APPLIED", apply_type="COMPANY_WEBSITE", match_score=score,
                    notes="Successfully auto-filled and submitted on external company careers website.",
                    execution_stage="SUBMISSION_VERIFIED",
                    application_attempted=True,
                    application_submitted=True,
                    application_confirmed=True,
                    confirmation_type="PORTAL_SUCCESS_CONFIRMATION",
                    confirmation_message=f"Application confirmed on external portal via: {pattern_found}",
                    external_application_url=ext_url,
                    resume_upload_status=resume_status,
                    platform=platform, requested_location=requested_location, actual_browser_location=actual_browser_location
                )
                # Close detail tab if open
                try:
                    if detail_tab and detail_tab != company_tab and not detail_tab.is_closed():
                        detail_tab.close()
                except Exception:
                    pass
                return {"status": "APPLIED", "success": True, "attempted": True}

            elif clicked:
                self.log(f"Submission executed on {company} portal, but explicit confirmation receipt was not detected within timeout. Preserving tab open in Chrome for candidate safety.", "WARNING")
                record_application(
                    job_title=title, company_name=company, location=loc_text, job_url=original_job_url or ext_url,
                    status="SUBMITTED_PENDING_CONFIRMATION", apply_type="COMPANY_WEBSITE", match_score=score,
                    notes="Application submit clicked, awaiting final confirmation. Tab kept open.",
                    execution_stage="SUBMISSION_PENDING",
                    application_attempted=True,
                    application_submitted=True,
                    application_confirmed=False,
                    confirmation_type="SUBMIT_CLICKED_AWAITING_CONFIRMATION",
                    confirmation_message="Submit button clicked on company portal; explicit confirmation receipt was not detected.",
                    external_application_url=ext_url,
                    resume_upload_status=resume_status,
                    platform=platform, requested_location=requested_location, actual_browser_location=actual_browser_location
                )
                return {"status": "SUBMITTED_PENDING_CONFIRMATION", "success": True, "attempted": True}
            else:
                self.log(f"Submit button was not clickable on {company} portal.", "WARNING")
                screenshot = self.capture_screenshot(company_tab, "submit_unclickable", company)
                record_application(
                    job_title=title, company_name=company, location=loc_text, job_url=original_job_url or ext_url,
                    status="APPLICATION_FAILED", apply_type="COMPANY_WEBSITE", match_score=score,
                    notes="Submit button could not be clicked.",
                    failure_reason=ExternalFailureReasons.APPLICATION_SUBMISSION_FAILED,
                    skip_reason_code=ExternalFailureReasons.APPLICATION_SUBMISSION_FAILED,
                    execution_stage=ExternalApplyStages.FORM_VALIDATED,
                    detailed_explanation="The form was filled and validated, but the final submission button could not be engaged.",
                    application_attempted=True, application_submitted=False, application_confirmed=False,
                    screenshot_reference=screenshot,
                    external_application_url=ext_url,
                    resume_upload_status=resume_status,
                    platform=platform, requested_location=requested_location, actual_browser_location=actual_browser_location
                )
                return {"status": "APPLICATION_FAILED", "success": False, "failure_reason": "SUBMIT_BUTTON_NOT_CLICKABLE", "attempted": True}

        except Exception as e:
            self.log(f"Error executing external company application for {title} @ {company}: {e}", "ERROR")
            screenshot = ""
            if company_tab and not company_tab.is_closed():
                screenshot = self.capture_screenshot(company_tab, "ext_exception", company)
            record_application(
                job_title=title, company_name=company, location=loc_text, job_url=original_job_url or ext_url,
                status="APPLICATION_FAILED", apply_type="COMPANY_WEBSITE", match_score=score,
                notes=f"Exception during external execution: {e}",
                failure_reason=ExternalFailureReasons.APPLICATION_SUBMISSION_FAILED,
                skip_reason_code=ExternalFailureReasons.APPLICATION_SUBMISSION_FAILED,
                execution_stage=current_stage,
                detailed_explanation=f"Application failed at stage {current_stage}: {e}",
                application_attempted=True, application_submitted=False, application_confirmed=False,
                error_message=str(e),
                screenshot_reference=screenshot,
                external_application_url=ext_url,
                resume_upload_status=resume_status,
                platform=platform, requested_location=requested_location, actual_browser_location=actual_browser_location
            )
            return {"status": "APPLICATION_FAILED", "success": False, "failure_reason": str(e), "attempted": True}

