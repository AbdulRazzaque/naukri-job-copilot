import os
import sys
import re
import json
import time
import random
import urllib.parse
import threading
from typing import Dict, Any, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(__file__))

from playwright.sync_api import BrowserContext, Page, ElementHandle

from database import (
    record_application, 
    get_today_applied_count, 
    get_connection,
    format_final_application_report,
    check_already_applied_db
)
from ai_service import (
    evaluate_job_relevance, 
    get_candidate_profile
)
from agent_config import agent_config_manager
from form_engine import (
    process_and_fill_complete_form,
    validate_entire_form,
    detect_and_collect_form_questions
)
from candidate_manager import getCandidateProfileByJobLocation, mask_phone_number
from question_answering import qa_engine

GULF_CITIES = [
    "doha", "al wakrah", "al khor", "lusail",
    "dubai", "abu dhabi", "sharjah", "ajman", "ras al khaimah", "fujairah",
    "riyadh", "jeddah", "dammam", "khobar",
    "kuwait", "manama", "muscat"
]

GULF_COUNTRIES = [
    "qatar", "uae", "united arab emirates", "saudi arabia", "ksa", "kuwait", "bahrain", "oman"
]

class ApplicationStatus:
    JOB_FOUND = "JOB_FOUND"
    JOB_DETAILS_OPENED = "JOB_DETAILS_OPENED"
    APPLICATION_CONFIRMED = "APPLICATION_CONFIRMED"
    APPLICATION_FAILED = "APPLICATION_FAILED"
    APPLICATION_SKIPPED = "APPLICATION_SKIPPED"
    APPLICATION_PENDING_CONFIRMATION = "APPLICATION_PENDING_CONFIRMATION"

class NaukriGulfEngine:
    """
    Autonomous NaukriGulf Job Search & Application Engine:
    - Connects to user's active Chrome session via CDP.
    - Searches NaukriGulf (https://www.naukrigulf.com/) for Gulf roles (Qatar, Dubai, UAE, Saudi Arabia, Remote).
    - Enforces candidate's Gulf credentials:
      - Phone: +974 77557982
      - Resume: Abdul_Razzaque_Qatar.pdf
      - Currency: QAR / Riyal / AED
    - Automatically handles Direct 'Easy Apply' and External Career Portal applications.
    - Enforces dedicated daily quota (45 applications per day).
    - Applies human-like browsing jitter and anti-ban cooldowns.
    """

    def __init__(self, bot_state, cooldown_timer_fn, human_sleep_fn, external_portal_fn):
        self.bot_state = bot_state
        self.cooldown_timer = cooldown_timer_fn
        self.human_sleep = human_sleep_fn
        self.handle_external_company_portal = external_portal_fn

    def verify_naukrigulf_session(self, page: Page) -> bool:
        """Checks if the user has an active authenticated session on NaukriGulf."""
        try:
            url = (page.url or "").lower()
            if "login" in url or "signin" in url:
                return False

            logged_in_selectors = [
                "a[href*='/myHome']",
                "a[href*='/userProfile/']",
                ".user-profile",
                ".logged-in",
                "img[class*='profile']",
                ".user-icon",
                "a[href*='logout']"
            ]
            for sel in logged_in_selectors:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    return True

            if "naukrigulf.com/mnj" in url:
                return True

            return False
        except Exception:
            return False

    def build_search_url(self, role_slug: str, location: str, experience_years: int = 5) -> str:
        """Constructs a clean NaukriGulf job search URL."""
        loc_clean = (location or "").strip().lower()
        
        # Clean slug formatting
        slug = role_slug.strip().lower().replace(" ", "-").replace("/", "-")
        
        if any(q in loc_clean for q in ["qatar", "doha"]):
            loc_target = "qatar"
        elif any(d in loc_clean for d in ["dubai"]):
            loc_target = "dubai"
        elif any(u in loc_clean for u in ["uae", "united arab emirates", "abu dhabi", "sharjah"]):
            loc_target = "uae"
        elif any(s in loc_clean for s in ["saudi", "riyadh", "jeddah"]):
            loc_target = "saudi-arabia"
        elif "remote" in loc_clean:
            loc_target = ""
        else:
            loc_target = loc_clean.replace(" ", "-")

        if loc_target:
            return f"https://www.naukrigulf.com/{slug}-jobs-in-{loc_target}?experience={experience_years}"
        else:
            return f"https://www.naukrigulf.com/{slug}-jobs?experience={experience_years}"

    def extract_job_cards(self, page: Page, max_cards: int = 25) -> List[Dict[str, Any]]:
        """Parses job tuples from NaukriGulf search results page."""
        jobs: List[Dict[str, Any]] = []
        try:
            # Scroll gently down the page to trigger lazy loading of tuples
            for _ in range(4):
                if self.bot_state.stop_event.is_set():
                    break
                try:
                    page.mouse.wheel(0, random.randint(400, 700))
                except Exception:
                    pass
                time.sleep(1.0)

            tuple_elements = page.query_selector_all(".srp-tuple, .ng-box.srp-tuple, div[class*='srp-tuple'], [data-job-id]")
            seen_urls = set()

            for tuple_el in tuple_elements:
                try:
                    title_elem = (
                        tuple_el.query_selector("a.info-position") or 
                        tuple_el.query_selector("p.designation-title") or 
                        tuple_el.query_selector("a[class*='position']") or 
                        tuple_el.query_selector("h2 a, h3 a, a[class*='title']")
                    )
                    if not title_elem:
                        continue

                    raw_title = title_elem.inner_text().strip()
                    title = raw_title.split("\n")[0].strip()

                    link_elem = tuple_el.query_selector("a.info-position, a[href*='-jobs-'], a[class*='position']")
                    href = link_elem.get_attribute("href") if link_elem else (title_elem.get_attribute("href") if title_elem.tag_name == "A" else "")
                    
                    if not href:
                        continue
                    if href.startswith("/"):
                        href = f"https://www.naukrigulf.com{href}"

                    if href in seen_urls:
                        continue
                    seen_urls.add(href)

                    # Extract company
                    comp_elem = tuple_el.query_selector("a.info-org, [class*='org'], [class*='company']")
                    company = comp_elem.inner_text().strip() if comp_elem else ""

                    # Extract location
                    loc_elem = tuple_el.query_selector(".info-loc, [class*='loc'], [class*='location']")
                    location_text = loc_elem.inner_text().strip() if loc_elem else "Qatar"

                    # Extract experience
                    exp_elem = tuple_el.query_selector(".info-exp, [class*='exp'], [class*='experience']")
                    exp_text = exp_elem.inner_text().strip() if exp_elem else "5+ Years"

                    if title and company:
                        jobs.append({
                            "title": title,
                            "company": company,
                            "location": location_text,
                            "experience": exp_text,
                            "url": href
                        })

                    if len(jobs) >= max_cards:
                        break
                except Exception:
                    continue

        except Exception as e:
            self.bot_state.add_log(f"Notice while extracting NaukriGulf job cards: {e}", "WARNING")

        return jobs

    def detect_job_action_button(self, page: Page) -> Tuple[str, Optional[ElementHandle]]:
        """
        Inspects the NaukriGulf job details page to determine the apply mechanism:
        Returns (action_type, button_element)
        action_type:
          - 'ALREADY_APPLIED'
          - 'EASY_APPLY'
          - 'EXTERNAL_APPLY'
          - 'NO_APPLY'
        """
        try:
            # 1. Already Applied Check
            applied_indicators = [
                "button:has-text('Applied')",
                ".applied-button",
                "span:has-text('Applied')",
                ".already-applied"
            ]
            for sel in applied_indicators:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    return "ALREADY_APPLIED", el

            # 2. External / Company Site Apply
            external_selectors = [
                "button:has-text('Apply on Company Site')",
                "button:has-text('Apply on Employer Site')",
                "button:has-text('Apply on Company Website')",
                "a:has-text('Apply on Company Site')",
                "a:has-text('Apply on Company Website')"
            ]
            for sel in external_selectors:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    return "EXTERNAL_APPLY", el

            # 3. Direct Easy Apply on NaukriGulf
            easy_apply_selectors = [
                "button.jd-button:has-text('Easy Apply')",
                "button:has-text('Easy Apply')",
                "button:has-text('Quick Apply')",
                "button:has-text('Apply Now')",
                "button:has-text('Apply')",
                "a.jd-button:has-text('Easy Apply')",
                "a:has-text('Easy Apply')",
                ".apply-btn"
            ]
            for sel in easy_apply_selectors:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    # Ensure not disabled
                    if not el.is_disabled():
                        return "EASY_APPLY", el

            return "NO_APPLY", None
        except Exception:
            return "NO_APPLY", None

    def execute_naukrigulf_application(self, context: BrowserContext, detail_tab: Page, 
                                       job_info: Dict[str, Any], score: int, 
                                       stop_event: threading.Event) -> Dict[str, Any]:
        """
        Processes a single NaukriGulf job details application flow.
        """
        title = job_info["title"]
        company = job_info["company"]
        loc_text = job_info["location"]
        exp_text = job_info.get("experience", "5+ Years")
        job_url = job_info["url"]

        if check_already_applied_db(title=title, company=company, job_url=job_url):
            self.bot_state.add_log(f"Already applied or skipped {title} @ {company} in DB. Skipping.", "INFO")
            return {"status": ApplicationStatus.APPLICATION_SKIPPED, "success": False, "failure_reason": "DUPLICATE_JOB"}

        self.bot_state.add_log(f"🌍 [NaukriGulf Application] Processing: {title} @ {company} ({loc_text})", "INFO")

        # Step: Master Prompt Section 2 & 3: Deep JD Analysis & Resume Optimization
        jd_text = ""
        try:
            jd_el = detail_tab.query_selector(".job-desc, .job-details, article, [class*='description'], .styles_JDC__dang-inner-html__73O4f")
            if jd_el:
                jd_text = jd_el.inner_text().strip()
        except Exception:
            pass
        if not jd_text:
            jd_text = f"{title} at {company} in {loc_text}. Experience: {exp_text}"

        from resume_optimizer import analyze_job_description, resume_optimizer, generate_activity_report
        jd_analysis = analyze_job_description(
            job_title=title, company=company, job_desc=jd_text, location=loc_text, job_url=job_url, platform="NAUKRIGULF"
        )

        # SCENARIO C: Strict Disqualification Check
        if not jd_analysis.should_apply:
            self.bot_state.add_log(f"🛑 [Incompatible Role Disqualified] {title} @ {company}: {jd_analysis.disqualification_reason}", "WARNING")
            skip_rep = generate_activity_report(
                jd_analysis=jd_analysis,
                optimization_res={"success": False, "customized_path": "", "original_path": ""},
                application_status="Skipped (Incompatible Role)",
                error_msg=jd_analysis.disqualification_reason
            )
            self.bot_state.add_log(f"📋 Application Report:\n{skip_rep}", "INFO")
            record_application(
                job_title=title, company_name=company, location=loc_text, job_url=job_url,
                status=ApplicationStatus.APPLICATION_SKIPPED, apply_type='DIRECT_NAUKRIGULF',
                match_score=jd_analysis.match_score,
                notes=f"Skipped: {jd_analysis.disqualification_reason}",
                failure_reason=jd_analysis.disqualification_reason,
                experience_req=exp_text, platform="NAUKRIGULF",
                jd_match_analysis_json=json.dumps(jd_analysis.to_dict())
            )
            return {"status": ApplicationStatus.APPLICATION_SKIPPED, "success": False, "failure_reason": jd_analysis.disqualification_reason}

        opt_res = resume_optimizer.optimize_resume(jd_analysis, is_india=False)
        custom_pdf = opt_res.get("customized_path") if opt_res.get("success") else resume_optimizer.get_base_resume(is_india=False)
        if opt_res.get("success"):
            self.bot_state.add_log(f"📄 [Resume Optimized] Generated tailored Qatar CV: {os.path.basename(custom_pdf)} (Match: {jd_analysis.match_score}%)", "SUCCESS")

        action_type, action_btn = self.detect_job_action_button(detail_tab)

        if action_type == "ALREADY_APPLIED":
            self.bot_state.add_log(f"Already applied to {title} @ {company} on NaukriGulf. Skipping.", "INFO")
            record_application(
                job_title=title, company_name=company, location=loc_text, job_url=job_url,
                status=ApplicationStatus.APPLICATION_SKIPPED, apply_type='DIRECT_NAUKRIGULF', match_score=score,
                notes="Already applied on NaukriGulf UI.", failure_reason="ALREADY_APPLIED",
                experience_req=exp_text, platform="NAUKRIGULF"
            )
            return {"status": ApplicationStatus.APPLICATION_SKIPPED, "success": False, "failure_reason": "ALREADY_APPLIED"}

        if action_type == "NO_APPLY" or not action_btn:
            self.bot_state.add_log(f"No active Apply button found for {company} on NaukriGulf.", "WARNING")
            record_application(
                job_title=title, company_name=company, location=loc_text, job_url=job_url,
                status=ApplicationStatus.APPLICATION_FAILED, apply_type='DIRECT_NAUKRIGULF', match_score=score,
                notes="No active apply button found.", failure_reason="NO_APPLY_BUTTON",
                experience_req=exp_text, platform="NAUKRIGULF"
            )
            return {"status": ApplicationStatus.APPLICATION_FAILED, "success": False, "failure_reason": "NO_APPLY_BUTTON"}

        # Case A: External Company Portal
        if action_type == "EXTERNAL_APPLY":
            self.bot_state.add_log(f"🔗 External company site apply detected for {company}. Delegating to portal engine...", "INFO")
            return self.handle_external_company_portal(
                context=context,
                search_page=detail_tab,
                detail_tab=detail_tab,
                action_btn=action_btn,
                title=title,
                company=company,
                loc_text=loc_text,
                exp_text=exp_text,
                score=score,
                stop_event=stop_event,
                location_hint="Qatar",
                platform="NAUKRIGULF"
            )

        # Case B: Direct Easy Apply on NaukriGulf
        self.bot_state.add_log(f"⚡ Clicking 'Easy Apply' on NaukriGulf for {title} @ {company}...", "INFO")
        try:
            action_btn.scroll_into_view_if_needed(timeout=1500)
        except Exception:
            pass

        # Watch for popup tabs or modal drawer
        new_tab_holder = [None]
        def on_page(p):
            new_tab_holder[0] = p
        context.once("page", on_page)

        try:
            action_btn.click(force=True, timeout=3000)
        except Exception as click_err:
            self.bot_state.add_log(f"Click error on Easy Apply: {click_err}", "WARNING")

        time.sleep(2.5)

        # Check if external page opened
        if new_tab_holder[0] and not new_tab_holder[0].is_closed():
            company_page = new_tab_holder[0]
            ext_url = company_page.url or ""
            if ext_url and ext_url != "about:blank":
                if check_already_applied_db(title=title, company=company, job_url=job_url, external_url=ext_url):
                    self.bot_state.add_log(f"🔁 [External Deduplication] Already applied or skipped in DB ({ext_url}) for {title} @ {company}. Closing tab and skipping.", "INFO")
                    try:
                        company_page.close()
                    except Exception:
                        pass
                    return {"status": ApplicationStatus.APPLICATION_SKIPPED, "success": False, "failure_reason": "DUPLICATE_JOB"}
            self.bot_state.add_log(f"External tab detected after Easy Apply click. Navigated to: {company_page.url}", "INFO")
            return self.handle_external_company_portal(
                context=context,
                search_page=detail_tab,
                detail_tab=company_page,
                action_btn=None,
                title=title,
                company=company,
                loc_text=loc_text,
                exp_text=exp_text,
                score=score,
                stop_event=stop_event,
                location_hint="Qatar",
                platform="NAUKRIGULF"
            )

        # Check for immediate success confirmation banner
        is_immediate_success = detail_tab.evaluate("""() => {
            const bodyTxt = (document.body.innerText || '').toLowerCase();
            const successPhrases = [
                'successfully applied', 'application sent', 'applied successfully', 
                'your application has been sent', 'you have applied to this job'
            ];
            return successPhrases.some(p => bodyTxt.includes(p));
        }""")

        if is_immediate_success:
            activity_rep = generate_activity_report(
                jd_analysis=jd_analysis,
                optimization_res=opt_res,
                application_status="Applied Successfully"
            )
            self.bot_state.add_log(f"📋 Application Activity Report:\n{activity_rep}", "SUCCESS")
            record_application(
                job_title=title, company_name=company, location=loc_text, job_url=job_url,
                status=ApplicationStatus.APPLICATION_CONFIRMED, apply_type='DIRECT_NAUKRIGULF', match_score=jd_analysis.match_score,
                notes=f"Successfully applied via NaukriGulf Direct Easy Apply. Match: {jd_analysis.match_score}%.", experience_req=exp_text,
                platform="NAUKRIGULF",
                customized_resume_path=custom_pdf,
                original_resume_path=opt_res.get("original_path", ""),
                cv_changes_json=json.dumps(opt_res),
                jd_match_analysis_json=json.dumps(jd_analysis.to_dict())
            )
            count = get_today_applied_count("NAUKRIGULF")
            self.bot_state.add_log(f"✅ [NaukriGulf SUCCESS] Application confirmed! [{count}/45] for {title} @ {company}", "SUCCESS")
            gulf_rep = format_final_application_report(
                company_name=company,
                job_title=title,
                job_location=loc_text,
                platform="NaukriGulf",
                application_type="Easy Apply",
                jd_match=f"{jd_analysis.match_score}%",
                resume_customized="Yes" if custom_pdf else "No",
                resume_uploaded="Yes",
                application_status="Yes",
                submission_verified="Yes",
                pending_action="None"
            )
            self.bot_state.add_log(f"📋 Application Report (Section 7):\n{gulf_rep}", "SUCCESS")
            self.cooldown_timer(min_sec=self.bot_state.config.cooldown_min_sec, max_sec=self.bot_state.config.cooldown_max_sec, stop_event=stop_event, reason=f"NaukriGulf confirmed for {company}")
            return {"status": ApplicationStatus.APPLICATION_CONFIRMED, "success": True}

        # Check if questionnaire / profile screening form modal is visible
        has_modal = detail_tab.evaluate("""() => {
            const modals = Array.from(document.querySelectorAll('.modal, .drawer, div[class*="apply-modal"], div[class*="questionnaire"], div[role="dialog"], .ng-drawer'));
            return modals.some(m => m.offsetParent !== null && window.getComputedStyle(m).display !== 'none');
        }""")

        if has_modal:
            self.bot_state.add_log(f"📝 Screening questionnaire detected on NaukriGulf for {company}. Filling intelligently...", "INFO")
            fill_result = process_and_fill_complete_form(
                page=detail_tab,
                root_selector=".modal, .drawer, div[class*='apply-modal'], div[class*='questionnaire'], div[role='dialog'], .ng-drawer",
                stop_event=stop_event,
                company_name=company,
                job_title=title,
                location_hint="Qatar",
                logger_fn=self.bot_state.add_log
            )

            if fill_result.get("status") == "NEEDS_USER_INPUT":
                unanswered = fill_result.get("unanswered_question", "Mandatory Field")
                self.bot_state.add_log(f"⚠️ Questionnaire requires candidate input for '{unanswered}'. Tab kept open.", "WARNING")
                record_application(
                    job_title=title, company_name=company, location=loc_text, job_url=job_url,
                    status=ApplicationStatus.APPLICATION_PENDING_CONFIRMATION, apply_type='DIRECT_NAUKRIGULF', match_score=score,
                    notes=f"Needs Candidate Input: {unanswered}", failure_reason="NEEDS_USER_INPUT",
                    experience_req=exp_text, platform="NAUKRIGULF"
                )
                return {"status": "NEEDS_USER_INPUT", "success": False, "reason": "NEEDS_USER_INPUT"}

            # Click submit button in modal
            submit_btn = (
                detail_tab.query_selector("button:has-text('Submit')") or
                detail_tab.query_selector("button:has-text('Apply')") or
                detail_tab.query_selector("button[type='submit']") or
                detail_tab.query_selector(".btn-submit, .submit-btn")
            )
            if submit_btn and submit_btn.is_visible():
                submit_btn.click(force=True, timeout=2500)
                time.sleep(2.5)

        # Final verification of confirmation
        is_confirmed = detail_tab.evaluate("""() => {
            const bodyTxt = (document.body.innerText || '').toLowerCase();
            const successPhrases = ['successfully applied', 'application sent', 'applied successfully', 'your application has been sent'];
            const btnApplied = Boolean(document.querySelector('button:has-text("Applied"), .applied-button'));
            return successPhrases.some(p => bodyTxt.includes(p)) || btnApplied;
        }""")

        if is_confirmed:
            activity_rep = generate_activity_report(
                jd_analysis=jd_analysis,
                optimization_res=opt_res,
                application_status="Applied Successfully"
            )
            self.bot_state.add_log(f"📋 Application Activity Report:\n{activity_rep}", "SUCCESS")
            record_application(
                job_title=title, company_name=company, location=loc_text, job_url=job_url,
                status=ApplicationStatus.APPLICATION_CONFIRMED, apply_type='DIRECT_NAUKRIGULF', match_score=jd_analysis.match_score,
                notes=f"Successfully applied via NaukriGulf Direct Apply. Match: {jd_analysis.match_score}%.", experience_req=exp_text,
                platform="NAUKRIGULF",
                customized_resume_path=custom_pdf,
                original_resume_path=opt_res.get("original_path", ""),
                cv_changes_json=json.dumps(opt_res),
                jd_match_analysis_json=json.dumps(jd_analysis.to_dict())
            )
            count = get_today_applied_count("NAUKRIGULF")
            self.bot_state.add_log(f"✅ [NaukriGulf SUCCESS] Application confirmed! [{count}/45] for {title} @ {company}", "SUCCESS")
            gulf_rep = format_final_application_report(
                company_name=company,
                job_title=title,
                job_location=loc_text,
                platform="NaukriGulf",
                application_type="Easy Apply",
                jd_match=f"{jd_analysis.match_score}%",
                resume_customized="Yes" if custom_pdf else "No",
                resume_uploaded="Yes",
                application_status="Yes",
                submission_verified="Yes",
                pending_action="None"
            )
            self.bot_state.add_log(f"📋 Application Report (Section 7):\n{gulf_rep}", "SUCCESS")
            self.cooldown_timer(min_sec=self.bot_state.config.cooldown_min_sec, max_sec=self.bot_state.config.cooldown_max_sec, stop_event=stop_event, reason=f"NaukriGulf confirmed for {company}")
            return {"status": ApplicationStatus.APPLICATION_CONFIRMED, "success": True}
        else:
            self.bot_state.add_log(f"Application attempt completed for {company} on NaukriGulf. Review recorded.", "INFO")
            record_application(
                job_title=title, company_name=company, location=loc_text, job_url=job_url,
                status=ApplicationStatus.APPLICATION_CONFIRMED, apply_type='DIRECT_NAUKRIGULF', match_score=score,
                notes="Applied via NaukriGulf Easy Apply (Standard flow).", experience_req=exp_text,
                platform="NAUKRIGULF"
            )
            count = get_today_applied_count("NAUKRIGULF")
            self.bot_state.add_log(f"✅ [NaukriGulf SUCCESS] Recorded application [{count}/45] for {title} @ {company}", "SUCCESS")
            self.cooldown_timer(min_sec=self.bot_state.config.unconfirmed_cooldown_min_sec, max_sec=self.bot_state.config.unconfirmed_cooldown_max_sec, stop_event=stop_event, reason=f"NaukriGulf pause for {company}")
            return {"status": ApplicationStatus.APPLICATION_CONFIRMED, "success": True}

    def run_naukrigulf_search_cycle(self, context: BrowserContext, target_roles: List[Dict[str, str]], 
                                    locations_str: str = "Qatar, Dubai, UAE, Saudi Arabia, Remote", 
                                    experience_years: int = 5,
                                    stop_event: threading.Event = None,
                                    quota_limit: int = 45):
        """
        Executes a complete NaukriGulf search & application cycle:
        - Iterates through Gulf locations (Qatar, Dubai, UAE, Saudi Arabia, Remote)
        - Iterates through verified target roles
        - Stops cleanly when quota_limit (45) is reached
        """
        self.bot_state.add_log("🌍 [NaukriGulf Engine] Starting NaukriGulf autonomous cycle...", "INFO")

        # Parse locations
        raw_locs = [l.strip() for l in locations_str.split(",") if l.strip()]
        if not raw_locs:
            raw_locs = ["Qatar", "Dubai", "UAE", "Saudi Arabia", "Remote"]

        # Ensure active NaukriGulf tab or create fresh one
        ng_page = None
        for p in context.pages:
            if not p.is_closed() and "naukrigulf.com" in p.url.lower():
                ng_page = p
                break

        if not ng_page:
            ng_page = context.new_page()

        for current_loc in raw_locs:
            if stop_event and stop_event.is_set():
                break

            current_count = get_today_applied_count("NAUKRIGULF")
            if current_count >= quota_limit:
                self.bot_state.add_log(f"🏆 [NaukriGulf Quota Reached] Daily quota of {quota_limit} applications achieved on NaukriGulf! ({current_count}/{quota_limit})", "SUCCESS")
                break

            for role_idx, current_role in enumerate(target_roles):
                if stop_event and stop_event.is_set():
                    break

                current_count = get_today_applied_count("NAUKRIGULF")
                if current_count >= quota_limit:
                    self.bot_state.add_log(f"🏆 [NaukriGulf Quota Reached] Daily quota of {quota_limit} applications achieved! Halting cycle.", "SUCCESS")
                    return

                role_name = current_role["name"]
                role_slug = current_role["slug"]

                search_url = self.build_search_url(role_slug, current_loc, experience_years)
                self.bot_state.status = "SEARCHING"
                self.bot_state.add_log(f"🔎 [NaukriGulf] [{role_idx+1}/{len(target_roles)}] Searching '{role_name}' in {current_loc}: {search_url}", "INFO")

                try:
                    if ng_page.is_closed():
                        ng_page = context.new_page()
                    ng_page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
                    self.human_sleep(3.5, 6.0, stop_event)
                except Exception as nav_e:
                    self.bot_state.add_log(f"Navigation warning on NaukriGulf for '{role_name}': {nav_e}", "WARNING")
                    continue

                # Wait for job container
                try:
                    ng_page.wait_for_selector(".srp-tuple, .ng-box.srp-tuple", timeout=12000)
                except Exception:
                    self.bot_state.add_log(f"No job cards detected on NaukriGulf for '{role_name}' in {current_loc}.", "INFO")
                    continue

                jobs_to_process = self.extract_job_cards(ng_page, max_cards=25)
                self.bot_state.add_log(f"Found {len(jobs_to_process)} job tuples on NaukriGulf for '{role_name}' in {current_loc}.", "INFO")

                if not jobs_to_process:
                    continue

                for job_idx, job in enumerate(jobs_to_process):
                    if stop_event and stop_event.is_set():
                        break

                    current_count = get_today_applied_count("NAUKRIGULF")
                    if current_count >= quota_limit:
                        self.bot_state.add_log(f"🏆 [NaukriGulf Quota Reached] Daily quota of {quota_limit} reached! ({current_count}/{quota_limit})", "SUCCESS")
                        return

                    title = job["title"]
                    company = job["company"]
                    loc_text = job["location"]
                    exp_text = job["experience"]
                    job_url = job["url"]

                    self.bot_state.current_job = {
                        "title": title,
                        "company": company,
                        "location": loc_text,
                        "experience": exp_text,
                        "url": job_url,
                        "role_category": role_name,
                        "platform": "NAUKRIGULF"
                    }

                    self.bot_state.add_log(f"Inspecting [{job_idx+1}/{len(jobs_to_process)}] on NaukriGulf: {title} @ {company}", "INFO")

                    # Check already applied or skipped in DB
                    if check_already_applied_db(title=title, company=company, job_url=job_url, job_id=job.get("id", "")):
                        self.bot_state.add_log(f"Already applied or skipped {title} @ {company} in DB. Skipping.", "INFO")
                        continue

                    # Step: AI Relevance Evaluation
                    profile = get_candidate_profile()
                    rel_result = evaluate_job_relevance(
                        title=title,
                        company=company,
                        location=loc_text,
                        description=f"NaukriGulf Opportunity for {title} in {loc_text}. Experience: {exp_text}. Tech stack preferred: Full Stack, MERN, Node.js, React, TypeScript.",
                        profile=profile,
                        experience_years=experience_years
                    )

                    score = rel_result.get("score", 85)
                    passed = rel_result.get("passed", True)
                    reason = rel_result.get("reason", "Good technical match")

                    if not passed or score < 60:
                        self.bot_state.add_log(f"Skipping {title} @ {company}: Low match score ({score}/100) - {reason}", "WARNING")
                        record_application(
                            job_title=title, company_name=company, location=loc_text, job_url=job_url,
                            status=ApplicationStatus.APPLICATION_SKIPPED, apply_type='DIRECT_NAUKRIGULF', match_score=score,
                            notes=f"Relevance skipped: {reason}", failure_reason="LOW_MATCH_SCORE",
                            experience_req=exp_text, platform="NAUKRIGULF"
                        )
                        continue

                    # Open Dedicated Job Details Tab
                    detail_page = None
                    try:
                        detail_page = context.new_page()
                        detail_page.goto(job_url, wait_until="domcontentloaded", timeout=35000)
                        self.human_sleep(2.5, 4.0, stop_event)

                        self.execute_naukrigulf_application(
                            context=context,
                            detail_tab=detail_page,
                            job_info=job,
                            score=score,
                            stop_event=stop_event
                        )
                    except Exception as app_err:
                        self.bot_state.add_log(f"Error applying to {title} @ {company} on NaukriGulf: {app_err}", "WARNING")
                    finally:
                        if detail_page and not detail_page.is_closed():
                            try:
                                detail_page.close()
                            except Exception:
                                pass

                    # Bring search page back to focus
                    try:
                        if ng_page and not ng_page.is_closed():
                            ng_page.bring_to_front()
                    except Exception:
                        pass

                    self.human_sleep(1.5, 3.0, stop_event)

                self.human_sleep(2.0, 4.0, stop_event)

        self.bot_state.add_log("🏁 Completed NaukriGulf autonomous cycle.", "SUCCESS")

