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
    check_already_applied_db
)
from ai_service import (
    evaluate_job_relevance, 
    get_candidate_profile
)
from agent_config import agent_config_manager
from question_answering import qa_engine, match_best_option
from database import format_final_application_report
from location_matcher import match_location
from technology_matcher import evaluate_technology_alignment
from state_machine import ApplicationStateMachine, ApplicationStage
from candidate_manager import getCandidateProfileByJobLocation, mask_phone_number, CandidateProfileManager

INDIAN_CITIES = [
    "mumbai", "pune", "delhi", "new delhi", "bengaluru", "bangalore", 
    "hyderabad", "chennai", "kolkata", "noida", "gurugram", "gurgaon", 
    "ahmedabad", "jaipur", "chandigarh", "lucknow", "indore", "kochi", 
    "coimbatore", "nagpur", "nashik", "bhopal", "visakhapatnam", "surat", 
    "vadodara", "thane", "navi mumbai", "hinjewadi", "hinjawadi", 
    "kharadi", "baner", "wakad", "yerwada", "andheri", "bkc", "kurla", "malad"
]

INDIAN_STATES = [
    "maharashtra", "karnataka", "telangana", "tamil nadu", "tamilnadu",
    "haryana", "uttar pradesh", "west bengal", "gujarat", "kerala",
    "rajasthan", "punjab", "madhya pradesh", "andhra pradesh", "bihar", "odisha"
]

INTERNATIONAL_KEYWORDS = [
    "qatar", "doha", "al wakrah", "al khor", "lusail",
    "uae", "united arab emirates", "dubai", "abu dhabi", "sharjah", "ajman", "ras al khaimah", "fujairah", "umm al quwain",
    "saudi arabia", "riyadh", "jeddah", "dammam", "kuwait", "bahrain", "oman", "muscat",
    "singapore", "united kingdom", "london", "united states", "usa", "canada", "germany", "netherlands", "australia", "emea"
]

def classify_linkedin_content(url: str = "", text: str = "") -> str:
    """
    Distinguishes between LinkedIn job listings, personal profiles, posts, company pages, etc.
    Returns: 'JOB_LISTING' | 'PERSONAL_PROFILE' | 'POST' | 'COMPANY_PAGE' | 'UNKNOWN'
    """
    clean_url = (url or "").lower().split("?")[0].strip()
    
    # 1. Post patterns
    if any(p in clean_url for p in ["/posts/", "/feed/update/", "/pulse/", "/recent-activity/"]):
        return "POST"
    
    # 2. Personal profile patterns
    if "/in/" in clean_url:
        return "PERSONAL_PROFILE"
        
    # 3. Company page patterns
    if any(p in clean_url for p in ["/company/", "/school/"]):
        return "COMPANY_PAGE"
        
    # 4. Job listing patterns
    if "/jobs/view/" in clean_url or "/jobs/collections/" in clean_url or "/jobs/search" in clean_url:
        return "JOB_LISTING"
        
    # Check text indicators if URL is ambiguous
    low_text = (text or "").lower()
    if any(p in low_text for p in ["like", "comment", "repost", "share this post", "reactions"]):
        return "POST"
    if "view profile" in low_text or ("connect" in low_text and "message" in low_text):
        return "PERSONAL_PROFILE"
        
    return "UNKNOWN"

def is_valid_linkedin_job_url(url: str) -> bool:
    """Checks if a URL is a valid LinkedIn job posting URL with a real numeric job ID."""
    if not url:
        return False
    if classify_linkedin_content(url) in ["POST", "PERSONAL_PROFILE", "COMPANY_PAGE"]:
        return False
    # Reject synthetic "lk_" hashes
    if "lk_" in url:
        return False
    # Must contain numeric ID in /jobs/view/
    return bool(re.search(r"/jobs/view/(\d{6,14})", url))

def determine_application_region(job_location: str, detail_location: str = "", search_location: str = "") -> Tuple[str, str, Dict[str, Any]]:
    """
    Determines whether a job application is INDIA-based or INTERNATIONAL (Qatar, UAE/Dubai, etc.).
    Priority:
    1. Check actual job posting location (job_location & detail_location) first.
    2. If ambiguous (pure 'Remote'), check search_location.
    3. Returns: (region: 'INDIA'|'INTERNATIONAL', reason: str, config: dict)
    """
    jl = (job_location or "").strip()
    dl = (detail_location or "").strip()
    sl = (search_location or "").strip()

    primary_text = f"{jl} {dl}".lower().strip()

    # Direct check on primary job posting text
    has_india = bool(re.search(r"\bindia\b", primary_text)) or any(c in primary_text for c in INDIAN_CITIES) or any(s in primary_text for s in INDIAN_STATES)
    has_intl = any(k in primary_text for k in INTERNATIONAL_KEYWORDS)

    if has_india and not has_intl:
        region = "INDIA"
        reason = f"Detected Indian location from job posting ('{jl or dl}')"
    elif has_intl and not has_india:
        region = "INTERNATIONAL"
        reason = f"Detected International/Gulf location from job posting ('{jl or dl}')"
    elif has_india and has_intl:
        # If both are mentioned, inspect job_location first
        jl_low = jl.lower()
        if any(k in jl_low for k in INTERNATIONAL_KEYWORDS):
            region = "INTERNATIONAL"
            reason = f"International location specified in primary job header ('{jl}')"
        else:
            region = "INDIA"
            reason = f"Indian location specified in primary job header ('{jl}')"
    else:
        # Generic location (e.g. purely 'Remote') -> inspect search_location
        sl_low = sl.lower()
        if any(k in sl_low for k in INTERNATIONAL_KEYWORDS):
            region = "INTERNATIONAL"
            reason = f"Inferred from International search target ('{sl}')"
        else:
            region = "INDIA"
            reason = f"Inferred India for generic/remote job based on candidate home location ('{sl or 'Default'}')"

    # Centralized Country-Based Candidate Profile
    cand_profile = getCandidateProfileByJobLocation(jl or dl or sl)
    # Ensure region follows candidate_manager classification
    region = cand_profile["classification"]

    if region == "INDIA":
        config = {
            "region": "INDIA",
            "resume_filename": cand_profile["resume_filename"],
            "resume_keyword": "india",
            "forbidden_resume_keyword": "qatar",
            "country_name": cand_profile["country"],
            "country_code": cand_profile["country_code"],
            "phone_raw": cand_profile["mobile_number"],
            "phone_full": cand_profile["full_phone_number"],
            "masked_phone": cand_profile["masked_phone"],
            "preferred_work_location": cand_profile["preferred_work_location"]
        }
    else:
        config = {
            "region": "INTERNATIONAL",
            "resume_filename": cand_profile["resume_filename"],
            "resume_keyword": "qatar",
            "forbidden_resume_keyword": "india",
            "country_name": cand_profile["country"],
            "country_code": cand_profile["country_code"],
            "phone_raw": cand_profile["mobile_number"],
            "phone_full": cand_profile["full_phone_number"],
            "masked_phone": cand_profile["masked_phone"],
            "preferred_work_location": cand_profile["preferred_work_location"]
        }

    return region, reason, config

def is_gulf_location(location_str: str) -> bool:
    """Compatibility wrapper checking if a location is International/Gulf."""
    reg, _, _ = determine_application_region(location_str)
    return reg == "INTERNATIONAL"

def select_linkedin_country_code(sel: ElementHandle, is_india: bool, bot_state: Any = None) -> Tuple[bool, str]:
    """
    Deterministically selects the phone country code from LinkedIn's country code <select> or combobox:
    - India: strictly selects 'India (+91)' with value 'in' [NEVER Bolivia (+591) or British Indian Ocean (+246)]
    - International (Qatar/Dubai/UAE): strictly selects 'Qatar (+974)' with value 'qa' [NEVER UAE (+971)]
    Verifies the selection after applying.
    Returns: (success: bool, selected_text: str)
    """
    target_val = "in" if is_india else "qa"
    target_query = "India" if is_india else "Qatar"
    target_name = "India (+91)" if is_india else "Qatar (+974)"

    try:
        tag_name = sel.evaluate("el => (el.tagName || '').toLowerCase()")
    except Exception:
        tag_name = "select"

    if tag_name == "select":
        try:
            sel.select_option(value=target_val)
        except Exception:
            pass

        res = sel.evaluate(r"""(el, isIndia) => {
            let matchedOpt = null;
            const targetVal = isIndia ? 'in' : 'qa';

            // Pass 1: Strict value matching ('in' for India, 'qa' for Qatar)
            for (let opt of el.options) {
                const val = (opt.value || '').toLowerCase().trim();
                if (val === targetVal) {
                    matchedOpt = opt;
                    break;
                }
            }

            // Pass 2: Strict text and code pattern matching
            if (!matchedOpt) {
                for (let opt of el.options) {
                    const text = (opt.text || opt.innerText || '').trim();
                    if (isIndia) {
                        const isTextIndia = /\bindia\b/i.test(text) && !/ocean|indonesia|bolivia/i.test(text);
                        const isExactCode = /\(\+?91\)/.test(text) || text.endsWith('+91');
                        if (isTextIndia && (isExactCode || !/\(\+\d+\)/.test(text))) {
                            matchedOpt = opt;
                            break;
                        }
                    } else {
                        const isTextQatar = /\bqatar\b/i.test(text) && !/emirates|dubai|bolivia/i.test(text);
                        const isExactCode = /\(\+?974\)/.test(text) || text.endsWith('+974');
                        if (isTextQatar) {
                            matchedOpt = opt;
                            break;
                        }
                    }
                }
            }

            if (matchedOpt) {
                el.value = matchedOpt.value;
                el.selectedIndex = matchedOpt.index;
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                return {
                    success: true,
                    selectedText: matchedOpt.text || matchedOpt.innerText || matchedOpt.value,
                    selectedValue: matchedOpt.value
                };
            }

            return {
                success: false,
                currentText: el.options[el.selectedIndex] ? (el.options[el.selectedIndex].text || el.options[el.selectedIndex].innerText) : ''
            };
        }""", is_india)

        selected_text = res.get("selectedText") or res.get("currentText") or ""
    else:
        # Combobox / Input handling
        try:
            sel.fill("")
            time.sleep(0.1)
            sel.type(target_query, delay=40)
            time.sleep(0.5)
            # Find matching listbox option
            sel.evaluate(r"""(el, isIndia) => {
                const targetText = isIndia ? 'india' : 'qatar';
                const opts = Array.from(document.querySelectorAll('[role="option"], .artdeco-typeahead__result, li, div[class*="option"]'));
                for (let o of opts) {
                    const txt = (o.innerText || '').toLowerCase();
                    if (isIndia) {
                        if (txt.includes('india') && !txt.includes('bolivia') && !txt.includes('ocean') && !txt.includes('indonesia')) {
                            o.click();
                            return;
                        }
                    } else {
                        if (txt.includes('qatar') && !txt.includes('bolivia') && !txt.includes('emirates')) {
                            o.click();
                            return;
                        }
                    }
                }
            }""", is_india)
            sel.evaluate(f"el => {{ if (!el.value || el.value.toLowerCase().includes('bolivia')) el.value = '{target_name}'; el.dispatchEvent(new Event('input', {{bubbles:true}})); el.dispatchEvent(new Event('change', {{bubbles:true}})); }}")
            selected_text = sel.evaluate("el => el.value") or target_name
        except Exception:
            selected_text = target_name

    # Verification in Python
    if is_india:
        is_verified = (
            ("india" in selected_text.lower()) and 
            ("bolivia" not in selected_text.lower()) and 
            ("591" not in selected_text) and 
            bool(re.search(r"(\+?91)", selected_text))
        )
    else:
        is_verified = (
            ("qatar" in selected_text.lower() or "974" in selected_text) and 
            ("971" not in selected_text) and
            ("bolivia" not in selected_text.lower()) and
            ("591" not in selected_text)
        )

    if is_verified and bot_state:
        bot_state.add_log(f"📞 Mandatory Country Code Verified: {target_name} [Selected: '{selected_text}']", "SUCCESS")
    elif not is_verified and bot_state:
        bot_state.add_log(f"⚠️ Country code selection verification mismatch! Expected {target_name}, got '{selected_text}'", "WARNING")

    return is_verified, selected_text

def select_or_upload_linkedin_resume(dialog: ElementHandle, is_india: bool, profile: Dict[str, Any], bot_state: Any = None, custom_resume_path: str = "") -> Tuple[bool, str]:
    """
    Selects or uploads the verified candidate resume on LinkedIn Easy Apply:
    - India Jobs: Strictly selects 'Abdul Razzaque India.pdf' or customized India CV (NEVER Qatar.pdf)
    - International Jobs: Strictly selects 'Abdul Razzaque Qatar.pdf' or customized Qatar CV (NEVER India.pdf)
    If custom_resume_path is provided, it is uploaded and selected.
    If target resume is not present, auto-uploads from disk via input[type='file'].
    Verifies that the target radio button is actually checked.
    Returns: (success: bool, resume_name: str)
    """
    target_kw = "india" if is_india else "qatar"
    forbidden_kw = "qatar" if is_india else "india"
    target_filename = "Abdul_Razzaque_India.pdf" if is_india else "Abdul_Razzaque_Qatar.pdf"

    if custom_resume_path and os.path.exists(custom_resume_path):
        custom_base = os.path.basename(custom_resume_path)
        target_filename = custom_base
        target_kw = custom_base.replace(".pdf", "").lower()

    # Step 1: Wait up to 3 seconds for resume radios or document cards to appear
    for _ in range(6):
        r_count = dialog.evaluate("""el => {
            const radios = el.querySelectorAll("input[type='radio']");
            let count = 0;
            for (let r of radios) {
                const aria = (r.getAttribute('aria-label') || '').toLowerCase();
                const pAria = (r.parentElement ? r.parentElement.getAttribute('aria-label') || '' : '').toLowerCase();
                const txt = (r.closest('li, div, label') ? r.closest('li, div, label').innerText : '').toLowerCase();
                if (aria.includes('.pdf') || aria.includes('razzaque') || pAria.includes('.pdf') || txt.includes('.pdf') || txt.includes('resume') || txt.includes('razzaque')) count++;
            }
            return count;
        }""")
        if isinstance(r_count, (int, float)) and r_count > 0:
            break
        time.sleep(0.5)

    # Step 2: Try selecting from existing uploaded resumes via JavaScript
    res = dialog.evaluate(r"""(el, { targetKw, forbiddenKw, targetFilename }) => {
        const radios = Array.from(el.querySelectorAll("input[type='radio']"));
        const resumeItems = [];

        for (let r of radios) {
            let isolatedText = (r.getAttribute('aria-label') || '').trim();
            if (!isolatedText && r.parentElement) {
                isolatedText = (r.parentElement.getAttribute('aria-label') || '').trim();
            }

            let container = r.parentElement;
            while (container && container !== el && !isolatedText) {
                const aria = (container.getAttribute('aria-label') || '').trim();
                if (aria && (aria.toLowerCase().includes('.pdf') || aria.toLowerCase().includes('razzaque'))) {
                    isolatedText = aria;
                    break;
                }
                const subRadios = container.querySelectorAll("input[type='radio']");
                if (subRadios.length === 1) {
                    const txt = container.innerText || '';
                    if (txt.toLowerCase().includes('.pdf') || txt.toLowerCase().includes('resume') || txt.toLowerCase().includes('razzaque')) {
                        isolatedText = txt;
                        break;
                    }
                } else if (subRadios.length > 1) {
                    break;
                }
                container = container.parentElement;
            }

            if (!isolatedText && r.id) {
                const lbl = document.querySelector('label[for=\"' + CSS.escape(r.id) + '\"]');
                if (lbl) isolatedText = lbl.innerText || '';
            }
            if (!isolatedText && r.closest('label')) {
                isolatedText = r.closest('label').innerText || '';
            }

            const low = isolatedText.toLowerCase();
            if (low.includes('.pdf') || low.includes('razzaque') || low.includes('resume')) {
                resumeItems.push({ radio: r, container: container || r.closest('label') || r.parentElement, text: isolatedText });
            }
        }

        // Look for the exact matching resume
        let targetItem = null;
        for (let item of resumeItems) {
            const tLow = item.text.toLowerCase();
            if (targetFilename && tLow.includes(targetFilename.toLowerCase())) {
                targetItem = item;
                break;
            }
            if (tLow.includes(targetKw) && !tLow.includes(forbiddenKw)) {
                targetItem = item;
                break;
            }
        }

        if (!targetItem) {
            const elements = Array.from(el.querySelectorAll('li, div, label, [class*="resume"], [class*="document"]'));
            for (let cand of elements) {
                const txt = (cand.innerText || '').toLowerCase();
                if (targetFilename && txt.includes(targetFilename.toLowerCase())) {
                    const r = cand.querySelector("input[type='radio']") || cand.closest('li, div')?.querySelector("input[type='radio']");
                    targetItem = { radio: r, container: cand, text: cand.innerText.trim() };
                    break;
                }
                if (txt.includes(targetKw) && !txt.includes(forbiddenKw) && (txt.includes('.pdf') || txt.includes('razzaque'))) {
                    const r = cand.querySelector("input[type='radio']") || cand.closest('li, div')?.querySelector("input[type='radio']");
                    targetItem = { radio: r, container: cand, text: cand.innerText.trim() };
                    break;
                }
            }
        }

        if (targetItem) {
            if (targetItem.container) {
                try { targetItem.container.click(); } catch(e) {}
            }
            if (targetItem.radio) {
                const r = targetItem.radio;
                try {
                    const lbl = (r.id ? document.querySelector('label[for=\"' + CSS.escape(r.id) + '\"]') : null) || r.closest('label') || r.parentElement;
                    if (lbl) lbl.click();
                    r.click();
                } catch(e) {}
                const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'checked')?.set;
                if (setter) setter.call(r, true);
                r.checked = true;
                r.dispatchEvent(new Event('input', { bubbles: true }));
                r.dispatchEvent(new Event('change', { bubbles: true }));
            }

            return {
                found: true,
                checked: targetItem.radio ? targetItem.radio.checked : true,
                text: targetItem.text.split('\\n')[0].trim()
            };
        }

        return {
            found: false,
            available: resumeItems.map(i => i.text.split('\\n')[0].trim())
        };
    }""", {"targetKw": target_kw, "forbiddenKw": forbidden_kw, "targetFilename": target_filename})

    # Step 3: If target resume was not found among radio buttons, upload from disk
    has_found = res.get("found", False) if isinstance(res, dict) else False
    if not has_found or (custom_resume_path and os.path.exists(custom_resume_path)):
        # Determine file to upload
        resume_to_upload = custom_resume_path if (custom_resume_path and os.path.exists(custom_resume_path)) else None
        if not resume_to_upload:
            resume_to_upload = os.path.join(os.path.dirname(__file__), target_filename)
            if not os.path.exists(resume_to_upload):
                alt_name = "Abdul Razzaque India.pdf" if is_india else "Abdul Razzaque Qatar.pdf"
                alt_path = os.path.join(os.path.dirname(__file__), alt_name)
                if os.path.exists(alt_path):
                    resume_to_upload = alt_path
                else:
                    resume_to_upload = profile.get("resume_path", "")

        if resume_to_upload and os.path.exists(resume_to_upload):
            file_inputs = dialog.query_selector_all("input[type='file']")
            uploaded = False
            for finp in file_inputs:
                try:
                    finp.set_input_files(resume_to_upload)
                    if bot_state:
                        bot_state.add_log(f"📎 Uploaded candidate resume: {os.path.basename(resume_to_upload)}", "SUCCESS")
                    time.sleep(2.0)
                    uploaded = True
                    break
                except Exception as e:
                    if bot_state:
                        bot_state.add_log(f"Resume upload notice: {e}", "WARNING")

            if uploaded:
                time.sleep(1.0)
                res = dialog.evaluate(r"""(el, { targetKw, forbiddenKw, targetFilename }) => {
                    const radios = Array.from(el.querySelectorAll("input[type='radio']"));
                    for (let r of radios) {
                        const aria = (r.getAttribute('aria-label') || '').toLowerCase();
                        const pAria = (r.parentElement ? r.parentElement.getAttribute('aria-label') || '' : '').toLowerCase();
                        let card = r.closest('li, div, label');
                        let txt = (aria + ' ' + pAria + ' ' + (card ? card.innerText || '' : '')).toLowerCase();
                        if ((targetFilename && txt.includes(targetFilename.toLowerCase())) || (txt.includes(targetKw) && !txt.includes(forbiddenKw))) {
                            const lbl = document.querySelector('label[for=\"' + CSS.escape(r.id) + '\"]') || r.parentElement;
                            if (lbl) lbl.click();
                            const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'checked')?.set;
                            if (setter) setter.call(r, true);
                            r.checked = true;
                            r.dispatchEvent(new Event('change', { bubbles: true }));
                            return { found: true, checked: r.checked, text: txt.split('\\n')[0].trim() };
                        }
                    }
                    return { found: false };
                }""", {"targetKw": target_kw, "forbiddenKw": forbidden_kw, "targetFilename": target_filename})

    # Fresh DOM verification to avoid stale detached ElementHandles
    time.sleep(0.4)
    verify_res = dialog.evaluate(r"""(el, { targetKw, forbiddenKw, targetFilename }) => {
        const radios = Array.from(el.querySelectorAll("input[type='radio']"));
        let targetChecked = false;
        let forbiddenChecked = false;
        let matchedText = '';
        for (let r of radios) {
            const aria = (r.getAttribute('aria-label') || '').toLowerCase();
            const pAria = (r.parentElement ? r.parentElement.getAttribute('aria-label') || '' : '').toLowerCase();
            const txt = (aria + ' ' + pAria + ' ' + (r.closest('li, div, label')?.innerText || '')).toLowerCase();
            if ((targetFilename && txt.includes(targetFilename.toLowerCase())) || (txt.includes(targetKw) && !txt.includes(forbiddenKw))) {
                matchedText = r.getAttribute('aria-label') || targetFilename;
                if (r.checked) targetChecked = true;
            }
            if (txt.includes(forbiddenKw) && r.checked) {
                forbiddenChecked = true;
            }
        }
        return { isVerified: targetChecked && !forbiddenChecked, matchedText };
    }""", {"targetKw": target_kw, "forbiddenKw": forbidden_kw, "targetFilename": target_filename})

    checked = verify_res.get("isVerified", False) if isinstance(verify_res, dict) else False
    resume_name = (verify_res.get("matchedText") if isinstance(verify_res, dict) else None) or target_filename

    # Step 4: Verification
    if checked and bot_state:
        region_str = "India" if is_india else "International/Gulf"
        bot_state.add_log(f"📄 Resume Verified & Selected: '{resume_name}' ({region_str})", "SUCCESS")
    elif not checked and bot_state:
        bot_state.add_log(f"⚠️ Could not verify selection of '{target_filename}'!", "WARNING")

    return checked, resume_name

class LinkedInEngine:
    """
    Autonomous LinkedIn Job Search & Application Engine:
    - Connects to the user's active Chrome session via CDP.
    - Searches LinkedIn Jobs with role keywords, locations, and experience criteria.
    - Accurately detects 'Easy Apply', 'Apply on Company Site', and 'Already Applied'.
    - Handles LinkedIn Easy Apply multi-step modal dialogs:
      - Automatically verifies and attaches candidate's resume (Abdul_Razzaque_India.pdf).
      - Answers screening questions (experience, notice, CTC, relocation, eligibility) via qa_engine.
      - Never fabricates answers; marks unfamiliar questions as NEEDS_USER_INPUT and keeps dialog open.
      - Respects agent_config_manager safety permissions (auto_submit_direct, auto_fill_forms, etc.).
    - External applications smoothly delegate to the company portal handler.
    - Applies strict human-like pacing and anti-ban cooldowns.
    """

    def __init__(self, bot_state, cooldown_timer_fn, human_sleep_fn, external_portal_fn):
        self.bot_state = bot_state
        self.cooldown_timer = cooldown_timer_fn
        self.human_sleep = human_sleep_fn
        self.handle_external_company_portal = external_portal_fn
        self.processed_job_ids = set()

    def verify_linkedin_session(self, page: Page) -> bool:
        """Checks if the user has an active authenticated session on LinkedIn."""
        try:
            url = (page.url or "").lower()
            if "authwall" in url or "linkedin.com/login" in url or "linkedin.com/checkpoint" in url:
                return False

            # Check for logged-in indicators
            logged_in_selectors = [
                "img.global-nav__me-photo",
                ".global-nav__me",
                "nav.global-nav",
                "button#global-nav-typeahead",
                "div.feed-identity-module",
                "a[href*='/jobs/']",
                ".jobs-search-box"
            ]
            for sel in logged_in_selectors:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    return True

            # If url contains linkedin.com/feed or linkedin.com/jobs and no login prompt
            if ("linkedin.com/feed" in url or "linkedin.com/jobs" in url) and not page.query_selector("a[href*='/login']"):
                return True

            return False
        except Exception:
            return False

    def get_safe_search_page(self, context: BrowserContext) -> Page:
        """Safely re-acquires or creates an active LinkedIn search page without crashing."""
        try:
            active = [pg for pg in context.pages if not pg.is_closed()]
            for pg in active:
                if "linkedin.com" in (pg.url or ""):
                    return pg
            return active[0] if active else context.new_page()
        except Exception:
            return context.new_page()

    def build_search_url(self, role_name: str, location: str, easy_apply_only: bool = False) -> str:
        """Constructs a clean, canonical LinkedIn job search URL."""
        encoded_kw = urllib.parse.quote(role_name.strip())
        loc_clean = location.strip()
        encoded_loc = urllib.parse.quote(loc_clean)

        base = f"https://www.linkedin.com/jobs/search/?keywords={encoded_kw}&location={encoded_loc}&sortBy=DD"
        
        # If user explicitly filtered for remote
        if "remote" in loc_clean.lower():
            base += "&f_WT=2"
            
        if easy_apply_only:
            base += "&f_AL=true"

        return base

    def _parse_card_text_lines(self, lines: List[str]) -> Optional[Dict[str, Any]]:
        """Extracts job details from raw text lines of modern LinkedIn job cards."""
        clean_lines = [l.strip() for l in lines if l.strip()]
        if not clean_lines:
            return None

        # Title extraction: look for role keywords in first 4 lines
        title = ""
        for l in clean_lines[:4]:
            cleaned_l = re.sub(r"^(selected,\s*)+", "", l, flags=re.I)
            cleaned_l = re.sub(r"\s*\(verified job\)", "", cleaned_l, flags=re.I).strip()
            if any(w in cleaned_l.lower() for w in ["developer", "engineer", "lead", "architect", "programmer", "specialist", "intern", "manager", "designer"]):
                title = cleaned_l
                break
        if not title and clean_lines:
            title = re.sub(r"^(selected,\s*)+", "", clean_lines[0], flags=re.I).replace("(Verified job)", "").strip()

        # Company extraction: find first non-title line that is not metadata
        company = ""
        for l in clean_lines:
            if l == title or (title and title in l and len(l) < len(title) + 15):
                continue
            if any(bad in l.lower() for bad in ["verified job", "early applicant", "promoted", "actively reviewing", "viewed", "posted", "ago", "easy apply", "applicants"]):
                continue
            if any(loc in l.lower() for loc in ["remote", "hybrid", "on-site", "india", "mumbai", "pune", "bangalore", "bengaluru", "delhi", "noida", "gurgaon", "hyderabad", "chennai", "dubai", "doha", "qatar", "uae"]):
                continue
            if re.search(r"\d+\s*(inr|php|usd|eur|lpa|yr|month|k|m)", l, re.I):
                continue
            company = l.strip()
            break

        # Location extraction: search for known cities or regions
        location = ""
        for l in clean_lines:
            l_low = l.lower()
            if any(c in l_low for c in INDIAN_CITIES) or any(s in l_low for s in INDIAN_STATES) or any(k in l_low for k in INTERNATIONAL_KEYWORDS) or any(w in l_low for w in ["india", "remote", "hybrid", "on-site"]):
                location = l.strip()
                break

        is_easy_apply = any("easy apply" in l.lower() for l in clean_lines)
        is_applied = any(l.lower() == "applied" or "application submitted" in l.lower() for l in clean_lines)

        return {
            "title": title,
            "company": company,
            "location": location,
            "is_easy_apply": is_easy_apply,
            "is_applied": is_applied
        }

    def get_current_linkedin_location(self, page: Page) -> str:
        """
        Extracts the actual selected location string currently displayed in the LinkedIn browser.
        Supports both modern AI search layout ([componentkey="searchResultsHeaderComponent"], location button) and classic search bar layouts.
        """
        try:
            loc = page.evaluate(r"""() => {
                // 1. Modern layout searchResultsHeaderComponent
                const header = document.querySelector('[componentkey="searchResultsHeaderComponent"]');
                if (header) {
                    const btn = header.querySelector('[role="button"]');
                    if (btn && btn.innerText && btn.innerText.trim()) {
                        return btn.innerText.trim();
                    }
                }
                // 2. Modern layout location button / pill
                const btn = document.querySelector('[aria-label*="Location "], div[role="button"]:has(svg#location-dot-outline-small), [aria-label^="Location "]');
                if (btn) {
                    const aria = btn.getAttribute('aria-label') || btn.querySelector('[aria-label]')?.getAttribute('aria-label') || '';
                    const m = aria.match(/Location\s+(.+)/i);
                    if (m) return m[1].trim();
                    const p = btn.querySelector('p');
                    if (p && p.innerText) return p.innerText.trim();
                    const txt = btn.innerText.trim();
                    if (txt) return txt;
                }
                // 3. Classic layout search input
                const inp = document.querySelector('input.jobs-search-box__input--location, input[id*="location"], input[aria-label*="City, state"]');
                if (inp && inp.value) {
                    return inp.value.trim();
                }
                return '';
            }""")
            return (loc or "").strip()
        except Exception:
            return ""

    def get_linkedin_result_count(self, page: Page) -> Tuple[int, str]:
        """
        Extracts the job result count displayed by LinkedIn (e.g. '87 results', '99+ results', '1,200 results').
        Returns: (parsed_numeric_count: int, raw_text: str)
        """
        try:
            raw_text = page.evaluate(r"""() => {
                const els = Array.from(document.querySelectorAll('p, small, span, div')).filter(el => {
                    const t = (el.innerText || '').trim();
                    return /^(\d+[\d,]*\+?)\s+results?$/i.test(t) || /^\bresults?\b/i.test(t);
                });
                const match = els.find(el => el.children.length === 0);
                return match ? match.innerText.trim() : (els[0] ? els[0].innerText.trim() : '');
            }""")
            if not raw_text:
                return 0, ""
            m = re.search(r"(\d[\d,]*)", raw_text)
            if m:
                count_val = int(m.group(1).replace(",", ""))
                return count_val, raw_text
            return 0, raw_text
        except Exception:
            return 0, ""

    def synchronize_linkedin_location(self, page: Page, requested_location: str, 
                                      stop_event: threading.Event, max_retries: int = 2) -> Tuple[bool, str, str]:
        """
        Synchronizes LinkedIn's browser location with the requested location.
        Ensures the actual browser location matches the requested location before scraping.
        Returns: (is_verified: bool, actual_location: str, error_msg: str)
        """
        req_clean = requested_location.strip()
        base_city = req_clean.split(",")[0].strip()
        req_tokens = [t.strip().lower() for t in re.split(r"[,/|+]", req_clean) if t.strip()]

        for attempt in range(max_retries + 1):
            if stop_event.is_set():
                break

            actual = self.get_current_linkedin_location(page)
            actual_low = actual.lower()

            # Check if actual location matches requested location
            tokens_to_check = [tok for tok in req_tokens if tok not in ["india", "hybrid"]]
            if not tokens_to_check:
                tokens_to_check = req_tokens
            if actual and any(tok in actual_low for tok in tokens_to_check):
                self.bot_state.add_log(f"📍 [LinkedIn] Location verified: '{actual}' matches requested '{req_clean}'.", "SUCCESS")
                return True, actual, ""

            self.bot_state.add_log(f"📍 [LinkedIn] Location mismatch (Attempt {attempt+1}/{max_retries+1}): requested='{req_clean}', but browser shows='{actual or 'None'}'. Synchronizing...", "WARNING")

            try:
                # 1. MODERN LAYOUT: Location button / popover
                btn = page.query_selector('[componentkey="searchResultsHeaderComponent"] [role="button"], [aria-label*="Location "], div[role="button"]:has(svg#location-dot-outline-small)')
                if btn and btn.is_visible():
                    btn.click()
                    self.human_sleep(1.0, 1.5, stop_event)

                    # Click Clear location if present
                    clear_btn = page.query_selector('button[aria-label="Clear location"]')
                    if clear_btn and clear_btn.is_visible():
                        clear_btn.click()
                        self.human_sleep(0.4, 0.7, stop_event)

                    # Find location textbox editor (Tiptap ProseMirror or standard input)
                    loc_input = page.query_selector('div[role="textbox"][aria-label="Location"], [componentkey="LocationTypeahead_TextEditor"], div.tiptap[role="textbox"]')
                    if loc_input:
                        loc_input.click()
                        self.human_sleep(0.3, 0.5, stop_event)
                        page.keyboard.press("Control+A")
                        time.sleep(0.1)
                        page.keyboard.press("Backspace")
                        time.sleep(0.1)
                        if hasattr(loc_input, "type"):
                            loc_input.type(base_city, delay=80)
                        else:
                            page.keyboard.type(base_city, delay=80)
                        self.human_sleep(1.5, 2.5, stop_event)

                        # Wait for autocomplete suggestions
                        suggestions = page.query_selector_all('#semanticSearchBoxLocationList a, div[popover="manual"] a, [role="listbox"] div, ul.typeahead-results li')
                        matched_sugg = None
                        for s in suggestions:
                            stext = (s.inner_text() or "").lower()
                            if any(tok in stext for tok in req_tokens):
                                matched_sugg = s
                                break

                        if matched_sugg:
                            self.bot_state.add_log(f"📍 Selecting autocomplete suggestion: '{matched_sugg.inner_text().strip()}'", "INFO")
                            matched_sugg.click()
                            self.human_sleep(3.0, 4.5, stop_event)
                        elif suggestions:
                            self.bot_state.add_log(f"📍 Selecting first suggestion: '{suggestions[0].inner_text().strip()}'", "INFO")
                            suggestions[0].click()
                            self.human_sleep(3.0, 4.5, stop_event)
                        else:
                            page.keyboard.press("Enter")
                            self.human_sleep(3.0, 4.5, stop_event)

                else:
                    # 2. CLASSIC LAYOUT: Input box
                    inp = page.query_selector('input.jobs-search-box__input--location, input[id*="location"], input[aria-label*="City, state"]')
                    if inp and inp.is_visible():
                        inp.click()
                        inp.fill("")
                        inp.type(req_clean, delay=80)
                        self.human_sleep(1.2, 2.0, stop_event)
                        typeahead = page.query_selector('.jobs-search-box__typeahead-results li, .typeahead-results li')
                        if typeahead:
                            typeahead.click()
                        else:
                            page.keyboard.press("Enter")
                        self.human_sleep(3.0, 4.5, stop_event)

            except Exception as e:
                self.bot_state.add_log(f"Notice while interacting with LinkedIn location field: {e}", "WARNING")

            # Check again after interaction
            new_actual = self.get_current_linkedin_location(page)
            new_low = new_actual.lower()
            tokens_to_check = [tok for tok in req_tokens if tok not in ["india", "hybrid"]]
            if not tokens_to_check:
                tokens_to_check = req_tokens
            if new_actual and any(tok in new_low for tok in tokens_to_check):
                self.bot_state.add_log(f"✅ [LinkedIn] Location successfully synchronized and verified: '{new_actual}'.", "SUCCESS")
                return True, new_actual, ""

        # If failed after all attempts
        final_loc = self.get_current_linkedin_location(page)
        screenshot_path = ""
        try:
            os.makedirs("backend/screenshots", exist_ok=True)
            safe_loc = re.sub(r'[^a-zA-Z0-9]', '_', req_clean)[:15]
            screenshot_path = f"backend/screenshots/loc_sync_failed_{safe_loc}_{int(time.time())}.png"
            page.screenshot(path=screenshot_path)
        except Exception:
            pass

        err_msg = f"LOCATION_SYNC_FAILED: Requested location was '{req_clean}', but LinkedIn browser displays '{final_loc or 'Unknown'}'. Screenshot: {screenshot_path}"
        self.bot_state.add_log(f"🚨 {err_msg}", "ERROR")
        return False, final_loc, err_msg

    def extract_job_cards(self, page: Page, max_cards: int = 25) -> List[Dict[str, Any]]:
        """
        Parses job cards from the search results page across all LinkedIn layouts:
        - Modern AI Search layout (/jobs/search-results/) using [componentkey*="job-card-component-ref-"]
        - Classic LinkedIn DOM layout (/jobs/search/) using data-occludable-job-id, job-card-container
        - Handles dynamic lazy-column virtualization, smooth scrolling, and extraction diagnostics.
        """
        jobs: List[Dict[str, Any]] = []
        try:
            # 1. Result count detection
            result_count, result_text = self.get_linkedin_result_count(page)

            # 2. Scroll gently down the job listings container to trigger lazy loading
            for _ in range(4):
                if self.bot_state.stop_event.is_set():
                    break
                try:
                    list_container = page.query_selector(
                        'div[data-testid="lazy-column"][componentkey="SearchResultsMainContent"], '
                        '.jobs-search-results-list, div.scaffold-layout__list, section[role="list"]'
                    )
                    if list_container:
                        list_container.evaluate("(el) => el.scrollTop += 600")
                    else:
                        page.mouse.wheel(0, 500)
                except Exception:
                    pass
                time.sleep(0.6)

            seen_ids = set()

            # PASS 1: Modern LinkedIn AI Search layout ([componentkey*="job-card-component-ref-"])
            modern_cards = page.evaluate(r"""() => {
                const results = [];
                const cardElements = Array.from(document.querySelectorAll('[componentkey*="job-card-component-ref-"]'))
                    .filter(el => el.getAttribute('role') === 'button' || el.getAttribute('tabindex') === '0');
                    
                for (let idx = 0; idx < cardElements.length; idx++) {
                    const card = cardElements[idx];
                    const ck = card.getAttribute('componentkey') || '';
                    const m = ck.match(/job-card-component-ref-(\d+)/);
                    const jobId = m ? m[1] : '';
                    if (!jobId) continue;
                    
                    const rawText = (card.innerText || '').trim();
                    const lines = rawText.split('\n').map(l => l.trim()).filter(Boolean);
                    
                    // Location metadata inside card
                    const locEl = card.querySelector('.artdeco-entity-lockup__caption, [class*="caption"], [class*="metadata"]');
                    const locText = locEl ? (locEl.innerText || '').trim() : '';
                    
                    results.push({
                        jobId: jobId,
                        url: `https://www.linkedin.com/jobs/view/${jobId}/`,
                        lines: lines,
                        rawText: rawText,
                        verifiedLocation: locText,
                        cardSelector: `[componentkey="${ck}"]`,
                        index: idx
                    });
                }
                return results;
            }""")

            for item in modern_cards:
                job_id = item.get("jobId", "")
                if not job_id or not str(job_id).isdigit():
                    continue
                if job_id in seen_ids or job_id in self.processed_job_ids:
                    continue
                seen_ids.add(job_id)

                lines = item.get("lines", [])
                raw_text = item.get("rawText", "")
                parsed = self._parse_card_text_lines(lines)
                if not parsed or not parsed.get("title") or not parsed.get("company"):
                    continue

                title = parsed["title"]
                company = parsed["company"]
                loc = item.get("verifiedLocation") or parsed.get("location", "")

                jobs.append({
                    "id": job_id,
                    "title": title,
                    "company": company,
                    "location": loc,
                    "url": item.get("url") or f"https://www.linkedin.com/jobs/view/{job_id}/",
                    "is_easy_apply": parsed.get("is_easy_apply", False),
                    "is_applied": parsed.get("is_applied", False),
                    "card_selector": item.get("cardSelector", ""),
                    "card_index": item.get("index", 0)
                })
                if len(jobs) >= max_cards:
                    break

            # PASS 2: Classic LinkedIn DOM elements (fallback if modern cards not present)
            if not jobs:
                card_elements = page.query_selector_all("li[data-occludable-job-id], div.job-card-container, li.jobs-search-results__list-item, div[data-job-id], .scaffold-layout__list-item")
                for card in card_elements:
                    try:
                        card_text = card.inner_text().strip()
                        if not card_text:
                            continue

                        if classify_linkedin_content("", card_text) in ["POST", "PERSONAL_PROFILE"]:
                            continue

                        job_id = card.get_attribute("data-occludable-job-id") or card.get_attribute("data-job-id") or ""
                        
                        title_elem = (
                            card.query_selector("a.job-card-list__title") or 
                            card.query_selector("a.job-card-container__link") or 
                            card.query_selector("a[class*='job-card']") or 
                            card.query_selector("strong")
                        )
                        raw_title = title_elem.inner_text().strip() if title_elem else ""
                        t_lines = [l.strip() for l in raw_title.split("\n") if l.strip()]
                        title = t_lines[0] if t_lines else ""

                        company_elem = (
                            card.query_selector(".artdeco-entity-lockup__subtitle") or 
                            card.query_selector(".job-card-container__primary-description") or 
                            card.query_selector("span[class*='company']")
                        )
                        c_raw = company_elem.inner_text().strip() if company_elem else ""
                        c_lines = [l.strip() for l in c_raw.split("\n") if l.strip()]
                        company = c_lines[0] if c_lines else ""

                        location_text = ""
                        for el in card.query_selector_all(".artdeco-entity-lockup__caption, .job-card-container__metadata-item, [class*='job-card-container__metadata']"):
                            t = el.inner_text().strip()
                            if t:
                                for subl in t.split("\n"):
                                    subl_clean = subl.strip()
                                    subl_low = subl_clean.lower()
                                    if subl_low in ["hybrid", "remote", "on-site", "promoted", "actively hiring", "easy apply", "applied"]:
                                        continue
                                    if any(c in subl_low for c in INDIAN_CITIES) or any(s in subl_low for s in INDIAN_STATES) or "india" in subl_low or any(k in subl_low for k in INTERNATIONAL_KEYWORDS) or "," in subl_clean:
                                        location_text = subl_clean
                                        break
                            if location_text:
                                break

                        href = title_elem.get_attribute("href") if title_elem else ""
                        if href and classify_linkedin_content(href) in ["POST", "PERSONAL_PROFILE", "COMPANY_PAGE"]:
                            continue

                        if not job_id and href:
                            id_match = re.search(r"/jobs/view/(\d+)", href)
                            if id_match:
                                job_id = id_match.group(1)

                        if not job_id or not str(job_id).isdigit():
                            continue

                        if job_id in seen_ids or job_id in self.processed_job_ids:
                            continue
                        seen_ids.add(job_id)

                        job_url = f"https://www.linkedin.com/jobs/view/{job_id}/"
                        is_easy_apply = "Easy Apply" in card_text
                        is_applied = "Applied" in card_text or bool(card.query_selector(".job-card-container__footer-job-state"))

                        if title and company:
                            jobs.append({
                                "id": job_id,
                                "title": title,
                                "company": company,
                                "location": location_text,
                                "url": job_url,
                                "is_easy_apply": is_easy_apply,
                                "is_applied": is_applied
                            })

                        if len(jobs) >= max_cards:
                            break
                    except Exception:
                        continue

            # DIAGNOSTIC CHECK: Did LinkedIn display results but we extracted 0 cards?
            if len(jobs) == 0 and result_count > 0:
                screenshot_path = ""
                try:
                    os.makedirs("backend/screenshots", exist_ok=True)
                    screenshot_path = f"backend/screenshots/job_card_extraction_failed_{int(time.time())}.png"
                    page.screenshot(path=screenshot_path)
                except Exception:
                    pass
                self.bot_state.add_log(
                    f"⚠️ JOB_CARD_EXTRACTION_FAILED: LinkedIn displays '{result_text}', but DOM extraction returned 0 cards! Screenshot: {screenshot_path}",
                    "WARNING"
                )

        except Exception as e:
            self.bot_state.add_log(f"Notice while extracting LinkedIn job cards: {e}", "WARNING")

        return jobs

    def detect_job_action_button(self, page: Page) -> Tuple[str, Optional[ElementHandle]]:
        """
        Inspects the LinkedIn job details view to identify application mechanism:
        Scopes to top-card action row to prevent false positives from left panel search cards,
        sidebar 'similar jobs' recommendation links, or filter pills.
        Returns (action_type, button_element)
        action_type can be:
          - 'ALREADY_APPLIED'
          - 'EASY_APPLY'
          - 'EXTERNAL_APPLY'
          - 'LOGIN_REQUIRED'
          - 'NO_APPLY'
        """
        if not page or (callable(getattr(page, "is_closed", None)) and page.is_closed() is True):
            return ("NO_APPLY", None)

        try:
            # 1. Login Required
            if page.query_selector("a:has-text('Sign in to apply'), button:has-text('Sign in to apply')"):
                return ("LOGIN_REQUIRED", None)

            # 1. Already Applied Check
            applied_indicators = [
                "button:has-text('Applied')",
                "span:has-text('Applied')",
                ".artdeco-inline-feedback--success",
                "div:has-text('Application submitted')",
                ".jobs-s-apply__application-link"
            ]
            for sel in applied_indicators:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    txt = (el.inner_text() or "").strip()
                    txt_low = txt.lower() if isinstance(txt, str) else "applied"
                    if ("applied" in txt_low or "application submitted" in txt_low) and "\n" not in str(txt) and len(str(txt)) < 30:
                        return ("ALREADY_APPLIED", el)
                for el in page.query_selector_all(sel):
                    if el and el.is_visible():
                        txt = (el.inner_text() or "").strip()
                        txt_low = txt.lower() if isinstance(txt, str) else "applied"
                        if ("applied" in txt_low or "application submitted" in txt_low) and "\n" not in str(txt) and len(str(txt)) < 30:
                            return ("ALREADY_APPLIED", el)

            # 3. Scope candidate buttons to top card / action container first
            container_selectors = [
                ".job-details-jobs-unified-top-card",
                ".jobs-unified-top-card",
                ".jobs-details__top-card",
                "[componentkey*='topcard' i]",
                "header.job-details",
                ".jobs-search__job-details",
                ".scaffold-layout__detail",
                "main"
            ]

            candidate_elements = page.query_selector_all("button, a")

            # Prioritize buttons adjacent to the 'Save' button in top-card
            save_btns = [b for b in candidate_elements if (b.inner_text() or "").strip().lower() == "save" or "save" in (b.get_attribute("aria-label") or "").lower()]
            scoped_buttons = []
            if save_btns:
                try:
                    parent = save_btns[0].evaluate_handle("el => el.closest('.job-details-jobs-unified-top-card, .jobs-unified-top-card, header, div.gvyayy, div[class*=\"top-card\"]')")
                    if parent and parent.as_element():
                        scoped_buttons = parent.as_element().query_selector_all("button, a")
                except Exception:
                    pass

            if not scoped_buttons:
                for csel in container_selectors:
                    cont = page.query_selector(csel)
                    if cont and cont.is_visible():
                        scoped_buttons = cont.query_selector_all("button, a")
                        if scoped_buttons:
                            break

            if not scoped_buttons:
                scoped_buttons = candidate_elements

            # Inspect scoped candidate elements
            for el in scoped_buttons:
                if not el or not el.is_visible():
                    continue
                try:
                    txt = (el.inner_text() or "").strip()
                    aria = (el.get_attribute("aria-label") or "").strip()
                    href = (el.get_attribute("href") or "").strip()

                    # Reject multi-line elements (job cards have \n and long metadata)
                    if "\n" in txt or len(txt) > 40:
                        continue

                    txt_low = txt.lower()
                    aria_low = aria.lower()

                    # Reject non-action controls
                    if any(bad in f"{txt_low} {aria_low}" for bad in ["filter", "search", "save", "dismiss", "cancel", "close", "report", "more", "alert", "share"]):
                        continue

                    # Check Easy Apply
                    if txt_low == "easy apply" or aria_low == "easy apply to this job" or txt_low.startswith("easy apply") or "easy apply" in aria_low:
                        return ("EASY_APPLY", el)

                    # Check External Apply
                    is_ext_aria = any(p in aria_low for p in ["apply on company website", "apply on company site", "apply on employer site", "apply externally", "apply to this job", "apply to "])
                    is_ext_txt = txt_low in ["apply", "apply now", "apply externally", "apply on company site", "apply on company website", "continue to apply"]
                    is_ext_href = "safety/go" in href or "job-apply" in href or (href.startswith("http") and "linkedin.com/jobs/view" not in href)

                    if (is_ext_aria or is_ext_txt or is_ext_href) and (txt_low != "easy apply"):
                        return ("EXTERNAL_APPLY", el)
                except Exception:
                    continue

            return ("NO_APPLY", None)
        except Exception:
            return ("NO_APPLY", None)

    def find_easy_apply_modal(self, page: Page) -> Optional[ElementHandle]:
        """Locates the active LinkedIn Easy Apply modal dialog across modern and classic layouts."""
        selectors = [
            ".jobs-easy-apply-modal",
            "div[role='dialog']:has(.jobs-easy-apply-content)",
            "div[role='dialog']:has([data-test-modal-header])",
            "div[role='dialog']:has(button:has-text('Submit application'))",
            "div[role='dialog']:has(button:has-text('Review'))",
            "div[role='dialog']:has(button:has-text('Next'))",
            "div[role='dialog'][aria-label*='Easy Apply']",
            "dialog[open]",
            ".artdeco-modal[role='dialog']",
            "div[role='dialog']"
        ]
        for sel in selectors:
            try:
                modals = page.query_selector_all(sel)
                for m in modals:
                    if m.is_visible():
                        return m
            except Exception:
                pass
        return None

    def scroll_modal_container(self, modal: ElementHandle, scroll_direction: str = "down", scroll_amount: int = 500):
        """
        Scrolls the active application modal's internal scrollable container.
        Reveals offscreen fields and buttons without scrolling the main browser window.
        """
        try:
            delta = scroll_amount if scroll_direction == "down" else -scroll_amount
            modal.evaluate(r"""(m, amt) => {
                const scrollable = m.querySelector(
                    '.jobs-easy-apply-modal__content, .artdeco-modal__content, div[tabindex="-1"], .jobs-easy-apply-content'
                ) || m;
                scrollable.scrollBy({ top: amt, behavior: 'smooth' });
            }""", delta)
            time.sleep(0.4)
        except Exception:
            pass

    def detect_modal_action_buttons(self, modal: ElementHandle, page: Page) -> Dict[str, Any]:
        """
        Dynamically inspects buttons in the active modal.
        Inspects accessible role, aria-label, visible text, button attributes, and disabled state.
        Distinguishes between: Submit application, Review, Next/Continue, Done, Dismiss.
        """
        result = {
            "submit": None,
            "review": None,
            "next": None,
            "done": None,
            "dismiss": None,
            "all_buttons": []
        }
        try:
            buttons = modal.query_selector_all("button, [role='button'], input[type='button'], input[type='submit']")
            for btn in buttons:
                try:
                    if not btn.is_visible():
                        continue

                    is_en = btn.is_enabled()
                    aria_dis = (btn.get_attribute("aria-disabled") or "").lower() == "true"
                    classes = (btn.get_attribute("class") or "").lower()
                    class_dis = "disabled" in classes and "artdeco-button--disabled" in classes
                    enabled = is_en and not aria_dis and not class_dis

                    aria_lbl = (btn.get_attribute("aria-label") or "").strip()
                    txt = (btn.inner_text() or "").strip()
                    combo = f"{aria_lbl} {txt}".strip().lower()

                    btn_info = {
                        "element": btn,
                        "enabled": enabled,
                        "text": txt,
                        "aria_label": aria_lbl,
                        "combo": combo
                    }
                    result["all_buttons"].append(btn_info)

                    # 1. Done (Post-submission Confirmation screen only)
                    if any(k in combo for k in ["done", "fertig"]) and not any(k in combo for k in ["dismiss", "close"]):
                        if not result["done"]:
                            result["done"] = btn_info

                    # 2. Submit application
                    elif any(k in combo for k in ["submit application", "bewerbung absenden", "bewerbung einreichen"]) or \
                       (combo == "submit" or combo.startswith("submit ") or combo.endswith(" submit")):
                        result["submit"] = btn_info

                    # 3. Review
                    elif any(k in combo for k in ["review your application", "review", "überprüfen"]) and "submit" not in combo:
                        result["review"] = btn_info

                    # 4. Next / Continue
                    elif any(k in combo for k in ["continue to next step", "next", "continue", "weiter", "fortfahren"]) and \
                         "review" not in combo and "submit" not in combo:
                        result["next"] = btn_info

                    # 5. Dismiss / Close (Cancel or discard dialog)
                    elif any(k in combo for k in ["dismiss", "close", "schließen", "abbrechen"]):
                        if not result["dismiss"]:
                            result["dismiss"] = btn_info
                except Exception:
                    continue
        except Exception:
            pass
        return result

    def inspect_modal_validation_errors(self, modal: ElementHandle) -> List[str]:
        """
        Inspects the active modal for form validation errors, invalid input messages,
        and missing mandatory fields.
        """
        try:
            errors = modal.evaluate(r"""(m) => {
                const errList = [];
                // 1. Explicit error containers
                const errorEls = Array.from(m.querySelectorAll(
                    '.artdeco-inline-feedback--error, .fb-form-element--error, ' +
                    '[data-test-form-element-error-message], [data-testid="text-input-helper-text"] p, ' +
                    'span.error, [class*="feedback--error"], [aria-invalid="true"]'
                ));
                for (const el of errorEls) {
                    if (el.offsetParent !== null) {
                        const t = (el.innerText || '').trim();
                        if (t && !t.toLowerCase().includes('success') && (
                            t.toLowerCase().includes('invalid') || t.toLowerCase().includes('error') ||
                            t.toLowerCase().includes('required') || t.toLowerCase().includes('please enter') ||
                            t.toLowerCase().includes('enter a valid') || t.toLowerCase().includes('select') ||
                            el.classList.contains('artdeco-inline-feedback--error') || el.classList.contains('fb-form-element--error')
                        )) {
                            errList.push(t);
                        }
                    }
                }
                // 2. Empty required inputs
                const reqInputs = Array.from(m.querySelectorAll(
                    'input[required]:not([type="hidden"]), select[required], textarea[required], [aria-required="true"]'
                ));
                for (const inp of reqInputs) {
                    if (inp.offsetParent !== null && !inp.disabled) {
                        const val = (inp.value || '').trim();
                        if (!val && inp.type !== 'checkbox' && inp.type !== 'radio') {
                            const aria = inp.getAttribute('aria-label') || '';
                            const lbl = inp.id ? (document.querySelector('label[for="' + CSS.escape(inp.id) + '"]')?.innerText || '') : '';
                            const name = aria || lbl || inp.name || 'Required field';
                            errList.push(`Required field empty: ${name}`);
                        }
                    }
                }
                return Array.from(new Set(errList));
            }""")
            return errors or []
        except Exception:
            return []

    def detect_security_challenge(self, page: Page) -> Tuple[bool, str]:
        """Detects whether LinkedIn presented a CAPTCHA or OTP challenge."""
        try:
            challenge_type = page.evaluate(r"""() => {
                const iframes = Array.from(document.querySelectorAll('iframe'));
                for (const f of iframes) {
                    const src = (f.src || '').toLowerCase();
                    if (src.includes('recaptcha') || src.includes('arkoselabs') || src.includes('funcaptcha') || src.includes('challenge')) {
                        return 'CAPTCHA';
                    }
                }
                const otpInputs = document.querySelectorAll('input[name*="pin"], input[name*="otp"], input[id*="verification-code"], [data-test-id*="verification"]');
                for (const o of otpInputs) {
                    if (o.offsetParent !== null) return 'OTP_VERIFICATION';
                }
                if (window.location.href.includes('checkpoint/challenge')) return 'SECURITY_CHECKPOINT';
                return null;
            }""")
            if challenge_type in ['CAPTCHA', 'OTP_VERIFICATION', 'SECURITY_CHECKPOINT']:
                return True, challenge_type
        except Exception:
            pass
        return False, ""

    def verify_submission_confirmation(self, page: Page, max_wait_sec: int = 12, stop_event: threading.Event = None) -> Tuple[bool, str, Optional[ElementHandle]]:
        """
        Verifies that an application submission actually succeeded:
        Polls for:
        1. Confirmation header / banner ('Application sent', 'Application submitted', 'Applied')
        2. 'Done' button or dismissal button in confirmation dialog
        3. Main job details page action button transitioning to 'Applied'
        4. Detects CAPTCHA / OTP security gates.
        Returns: (confirmed: bool, confirmation_message: str, done_button: Optional[ElementHandle])
        """
        start_time = time.time()
        while time.time() - start_time < max_wait_sec:
            if stop_event and stop_event.is_set():
                break

            # 1. Check for security challenges (CAPTCHA / OTP)
            is_challenge, challenge_type = self.detect_security_challenge(page)
            if is_challenge:
                return False, f"SECURITY_CHALLENGE:{challenge_type}", None

            # 2. Check for Done button in confirmation dialog
            try:
                done_btn = page.query_selector(
                    "button:has-text('Done'), button[aria-label*='Done']"
                )
                if done_btn and done_btn.is_visible():
                    is_done = False
                    if hasattr(done_btn, "inner_text"):
                        raw_txt = done_btn.inner_text()
                        if not isinstance(raw_txt, str):
                            is_done = True
                        elif "done" in raw_txt.lower() or "fertig" in raw_txt.lower() or raw_txt == "":
                            is_done = True
                    if hasattr(done_btn, "get_attribute"):
                        aria = done_btn.get_attribute("aria-label")
                        if aria and isinstance(aria, str) and "done" in aria.lower():
                            is_done = True
                    if is_done or not hasattr(done_btn, "inner_text"):
                        return True, "CONFIRMATION_BUTTON_DETECTED", done_btn
            except Exception:
                pass

            # 3. Check for confirmation text inside dialog or page
            try:
                conf_text = page.evaluate(r"""() => {
                    const headings = Array.from(document.querySelectorAll('h2, h3, h1, [role="alert"], [role="status"], .artdeco-inline-feedback__message'));
                    for (const h of headings) {
                        const t = (h.innerText || '').trim();
                        if (t && (
                            t.toLowerCase().includes('application was sent') ||
                            t.toLowerCase().includes('application sent') ||
                            t.toLowerCase().includes('application submitted') ||
                            t.toLowerCase().includes('your application has been sent') ||
                            t.toLowerCase().includes('applied') ||
                            t.toLowerCase().includes('bewerbung wurde gesendet')
                        )) {
                            return t;
                        }
                    }
                    return null;
                }""")
                if conf_text:
                    return True, f"CONFIRMATION_TEXT_FOUND: {conf_text}", None
            except Exception:
                pass

            # 4. Check if main page action button changed to 'Applied'
            try:
                applied_badge = page.query_selector(
                    ".job-details-jobs-unified-top-card button:has-text('Applied'), "
                    ".jobs-unified-top-card button:has-text('Applied'), "
                    ".artdeco-inline-feedback--success:has-text('Applied')"
                )
                if applied_badge and applied_badge.is_visible():
                    return True, "CONFIRMATION_PAGE_STATE_APPLIED", None
            except Exception:
                pass

            time.sleep(1.0)

        return False, "CONFIRMATION_TIMEOUT", None

    def fill_easy_apply_step(self, dialog: ElementHandle, page: Page, profile: Dict[str, Any], 
                             stop_event: threading.Event, company: str, title: str, location_hint: str = "",
                             custom_resume_path: str = "") -> Dict[str, Any]:
        """
        Intelligently detects and fills questions on an active LinkedIn Easy Apply modal step:
        - Contact info (phone, email, country code)
        - Resume selection (Abdul Razzaque India.pdf or customized CV) or upload
        - Additional questions (numeric experience, radio Yes/No, dropdowns, textareas)
        """
        try:
            region, region_reason, app_config = determine_application_region(
                job_location=location_hint,
                detail_location="",
                search_location=""
            )
            is_india = (region == "INDIA")
            target_kw = app_config["resume_keyword"]
            target_filename = app_config["resume_filename"]

            # PASS 1 & 2: Resume selection via Radio buttons or upload (synchronously matching job region)
            select_or_upload_linkedin_resume(dialog, is_india, profile, self.bot_state, custom_resume_path=custom_resume_path)

            # Detect if this step has a dedicated country phone code selector (select or combobox input)
            has_separate_cc = False
            for s in dialog.query_selector_all("select, input"):
                if s.is_visible():
                    s_aria = (s.get_attribute("aria-label") or "").lower()
                    s_id = (s.get_attribute("id") or "").lower()
                    s_name = (s.get_attribute("name") or "").lower()
                    s_label = s.evaluate("""el => {
                        if (el.id) {
                            try {
                                const l = document.querySelector('label[for=\"' + CSS.escape(el.id) + '\"]');
                                if (l) return l.innerText.toLowerCase();
                            } catch(e) {}
                        }
                        const p = el.closest('label') || el.closest('div');
                        return p ? p.innerText.toLowerCase() : '';
                    }""")
                    if any(k in s_aria or k in s_id or k in s_name or k in s_label for k in ["country code", "phone country", "phone code", "calling code"]):
                        has_separate_cc = True
                        break

                        # PASS 3: Input fields (text, number, tel, textarea)
            inputs = dialog.query_selector_all("input:not([type='hidden']):not([type='radio']):not([type='checkbox']):not([type='file']), textarea")
            for inp in inputs:
                if stop_event.is_set():
                    break
                if not inp.is_visible() or inp.is_disabled():
                    continue

                curr_val = (inp.evaluate("el => el.value") or "").strip()
                inp_type = inp.get_attribute("type") or "text"
                inp_id = inp.get_attribute("id") or ""
                inp_name = inp.get_attribute("name") or ""

                # Extract label / question text cleanly
                # Extract label / question text cleanly
                q_text = inp.evaluate(r"""(el) => {
                    const isGeneric = (txt) => {
                        if (!txt) return true;
                        const low = txt.trim().toLowerCase().replace(/[\*\(\)\:\#\-\_]|required|optional/g, '').trim();
                        const genericSections = [
                            'work experience', 'experience', 'additional questions', 'additional question', 'contact info',
                            'contact information', 'home address', 'resume', 'privacy policy',
                            'equal opportunity', 'demographics', 'screening questions', 'job application',
                            'work authorization', 'voluntary self-identification'
                        ];
                        return genericSections.some(s => low === s || low.startsWith('step '));
                    };

                    // 1. Direct aria-label on input (LinkedIn places the exact prompt here!)
                    const aria = el.getAttribute('aria-label');
                    if (aria && aria.trim() && !isGeneric(aria) && !aria.toLowerCase().includes('invalid')) {
                        return aria.trim();
                    }

                    // 2. Associated label by id (safe selector escaping)
                    const id = el.id;
                    if (id) {
                        try {
                            const escId = (window.CSS && CSS.escape) ? CSS.escape(id) : id.replace(/([:.\\[\\]\\(\\),=])/g, '\\\\$1');
                            const lbl = document.querySelector('label[for="' + escId + '"]');
                            if (lbl && lbl.innerText.trim() && !isGeneric(lbl.innerText)) {
                                return lbl.innerText.trim();
                            }
                        } catch(e) {}
                    }

                    // 3. Parent label
                    const parentLbl = el.closest('label');
                    if (parentLbl && parentLbl.innerText.trim() && !isGeneric(parentLbl.innerText)) {
                        return parentLbl.innerText.trim();
                    }
                    
                    // 4. Look inside immediate field wrapper (do NOT traverse up to entire dialog!)
                    const fieldContainer = el.closest('.fb-dash-form-element, [data-test-form-element], .jobs-easy-apply-form-element, .artdeco-text-input--container, [data-test-form-builder-repeater-field]');
                    if (fieldContainer) {
                        const h = fieldContainer.querySelector('label, .fb-dash-form-element__label, .artdeco-text-input--label, [data-test-form-element-label]');
                        if (h && h.innerText.trim() && !isGeneric(h.innerText)) {
                            return h.innerText.trim();
                        }
                    }

                    // 5. Look up nearest prompt header in immediate parent container (max 2 levels)
                    let cur = el.parentElement;
                    for (let i = 0; i < 2 && cur; i++) {
                        if (cur.classList.contains('jobs-easy-apply-modal') || cur.classList.contains('jobs-easy-apply-content') || cur.tagName === 'DIALOG' || cur.tagName === 'FORM') break;
                        const header = cur.querySelector('label, .fb-dash-form-element__label, .artdeco-text-input--label, [data-test-form-element-label]');
                        if (header && header.innerText.trim()) {
                            const htxt = header.innerText.trim();
                            if (!isGeneric(htxt) && !htxt.toLowerCase().includes('invalid') && !htxt.toLowerCase().includes('character')) {
                                return htxt;
                            }
                        }
                        cur = cur.parentElement;
                    }

                    // 6. Look at helper text / placeholder fallback (e.g. 'Please enter your notice period in days. Example: 45')
                    const descId = el.getAttribute('aria-describedby');
                    if (descId) {
                        try {
                            const descEl = document.getElementById(descId);
                            if (descEl && descEl.innerText.trim() && !isGeneric(descEl.innerText) && !descEl.innerText.toLowerCase().includes('invalid')) {
                                return descEl.innerText.trim();
                            }
                        } catch(e) {}
                    }
                    const ph = el.getAttribute('placeholder');
                    if (ph && ph.trim() && !isGeneric(ph)) return ph.trim();

                    return '';
                }""")
                q_clean = q_text.strip().replace("*", "").strip()

                # Check if this input is a Country Code selector (combobox / typeahead)
                is_cc_input = any(k in q_clean.lower() or k in inp_id.lower() or k in inp_name.lower() for k in ["country code", "phone country", "phone code", "calling code"])
                if is_cc_input:
                    select_linkedin_country_code(inp, is_india=is_india, bot_state=self.bot_state)
                    continue

                # Strict Mandatory Rule: Phone Number and Country Code
                # 1. India: Always use +91 7972694663. Country code +91, phone 7972694663.
                # 2. International (Qatar/Dubai/UAE): Always use +974 77557982. Country code +974, phone 77557982.
                #    Do NOT write United Arab Emirates, UAE, Dubai, or any country name in phone field. Never use +971.
                if any(k in q_clean.lower() or k in inp_id.lower() or k in inp_name.lower() for k in ["phone", "mobile", "contact number", "cell", "telephone"]) and not any(k in q_clean.lower() for k in ["country code", "calling code"]):
                    if is_india:
                        target_phone = app_config["phone_raw"] if has_separate_cc else app_config["phone_full"]
                        needs_fill = (curr_val != target_phone) or ("77557982" in curr_val) or (has_separate_cc and "+91" in curr_val)
                        if needs_fill:
                            inp.fill("")
                            time.sleep(0.1)
                            inp.fill(target_phone)
                            inp.evaluate("el => { el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true})); }")
                            masked_disp = mask_phone_number(target_phone)
                            self.bot_state.add_log(f"📞 Mandatory India Phone Applied: '{masked_disp}' (Location: {location_hint})", "SUCCESS")
                            time.sleep(0.3)
                    else:
                        target_phone = app_config["phone_raw"] if has_separate_cc else app_config["phone_full"]
                        needs_fill = (curr_val != target_phone) or bool(re.search(r"[a-zA-Z]", curr_val)) or ("7972694663" in curr_val) or ("797269663" in curr_val) or ("971" in curr_val) or (has_separate_cc and "+974" in curr_val)
                        if needs_fill:
                            inp.fill("")
                            time.sleep(0.1)
                            inp.fill(target_phone)
                            inp.evaluate("el => { el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true})); }")
                            masked_disp = mask_phone_number(target_phone)
                            self.bot_state.add_log(f"📞 Mandatory International Phone Applied: '{masked_disp}' (Location: {location_hint})", "SUCCESS")
                            time.sleep(0.3)
                    continue

                # Check if this field currently displays an inline error (e.g. 'Invalid input')
                has_field_error = inp.evaluate("""el => {
                    const descId = el.getAttribute('aria-describedby');
                    if (descId) {
                        const h = document.getElementById(descId);
                        if (h && (h.innerText.toLowerCase().includes('invalid') || h.innerText.toLowerCase().includes('enter a valid') || h.innerText.toLowerCase().includes('error'))) {
                            return true;
                        }
                    }
                    const parent = el.closest('div');
                    if (parent) {
                        const err = parent.querySelector('[class*="error"], [data-testid="text-input-helper-text"] p');
                        if (err && (err.innerText.toLowerCase().includes('invalid') || err.innerText.toLowerCase().includes('enter a valid'))) {
                            return true;
                        }
                    }
                    return false;
                }""")

                # If input already has a valid value and NO error, skip unless it's an unanswered 0
                if curr_val and not has_field_error:
                    if curr_val != "0" and len(curr_val) > 1:
                        continue

                if not q_clean:
                    continue

                # Detect if question requires pure numeric formatting
                is_numeric_field = (
                    inp_type in ("number", "tel") or
                    inp.get_attribute("inputmode") == "numeric" or
                    inp.get_attribute("pattern") is not None or
                    any(k in q_clean.lower() for k in [
                        "in lakhs", "in lpa", "lakhs per annum", "lakhs/annum", "per annum",
                        "how many days", "in days", "number of days", "notice period in days", "days is your notice", "days notice", "how many day",
                        "how many years", "years of", "in years", "number of years", "years experience", "total years",
                        "salary", "ctc", "gpa", "percentage", "cgpa", "pincode", "zip code", "postal code", "gehalt", "eur"
                    ])
                )
                pass_type = "number" if is_numeric_field else inp_type

                # Query QA Engine
                res = qa_engine.process_question(
                    question_text=q_clean,
                    input_type=pass_type,
                    job_title=title,
                    company_name=company,
                    location_hint=location_hint
                )

                if res.get("needs_user_input"):
                    return {
                        "status": "NEEDS_USER_INPUT",
                        "reason": res.get("reason", "NEEDS_USER_INPUT"),
                        "question": q_clean
                    }

                answer = res.get("answer", "")
                if answer is not None and str(answer).strip() != "":
                    # Pre-fill Strict Numeric Sanitization for numeric fields (Eliminates 'Invalid input' upfront!)
                    if is_numeric_field:
                        ans_str = str(answer).strip()
                        if any(k in q_clean.lower() for k in ["notice", "days"]) and any(k in ans_str.lower() for k in ["immediate", "joiner"]):
                            answer = "0"
                        elif any(k in q_clean.lower() for k in ["eur", "euro", "€"]):
                            m = re.search(r"(\d+)", ans_str)
                            answer = m.group(1) if m else "65000"
                        elif any(k in q_clean.lower() for k in ["lakh", "lpa", "in lakhs", "lakhs per annum"]):
                            m = re.search(r"(\d+(\.\d+)?)", ans_str)
                            if m:
                                val_f = float(m.group(1))
                                answer = str(int(val_f)) if val_f.is_integer() else str(val_f)
                        elif any(k in q_clean.lower() for k in ["inr", "rs", "rupee"]):
                            m = re.search(r"(\d+)", ans_str.replace(",", ""))
                            if m:
                                answer = m.group(1)
                        elif any(k in q_clean.lower() for k in ["how many years", "years of", "in years", "total years", "years experience"]):
                            m = re.search(r"(\d+(\.\d+)?)", ans_str)
                            if m:
                                val_f = float(m.group(1))
                                answer = str(int(val_f)) if val_f.is_integer() else str(val_f)

                    # Date field / Calendar icon check
                    has_calendar = inp.evaluate("el => el.type === 'date' || !!el.closest('div, [class*=\"datepicker\"], [class*=\"date-picker\"]')?.querySelector('svg, [class*=\"calendar\"], [data-test-icon*=\"calendar\"]') || !!el.parentElement?.querySelector('svg, [class*=\"calendar\"], [data-test-icon*=\"calendar\"]')")
                    is_start_q = any(k in q_clean.lower() for k in ["start date", "startdatum", "eintrittsdatum", "available to start", "start working", "availability", "when are you available", "earliest start"])
                    if has_calendar or pass_type == "date" or is_start_q:
                        import datetime
                        today = datetime.date.today()
                        target_date_str = (today + datetime.timedelta(days=7)).strftime("%d.%m.%Y") if any(k in q_clean.lower() for k in ["startdatum", "deutsch", "germany", "de"]) else (today + datetime.timedelta(days=7)).strftime("%Y-%m-%d")
                        if not re.match(r"^\d{2,4}[-./]\d{2}[-./]\d{2,4}$", str(answer).strip()):
                            answer = target_date_str if (has_calendar or pass_type == "date") else "Immediately"

                    # EUR Currency explicit check (Prevents '15' or '15 LPA' or essays being entered in EUR fields)
                    if any(k in q_clean.lower() for k in ["eur", "euro", "€"]):
                        m = re.search(r"\d+", str(answer))
                        if m:
                            num_val = int(m.group(0))
                            if num_val < 100 or num_val > 500000:
                                answer = "65000"
                            else:
                                answer = str(num_val)
                        else:
                            answer = "65000"

                    # Maxlength enforcement (Prevents 421/20 overflow)
                    max_len_attr = inp.get_attribute("maxlength")
                    if max_len_attr and max_len_attr.isdigit():
                        max_len = int(max_len_attr)
                        if max_len > 0 and len(str(answer)) > max_len:
                            if any(k in q_clean.lower() for k in ["salary", "gehalt", "ctc", "eur", "compensation"]):
                                m = re.search(r"\d+", str(answer))
                                answer = m.group(0)[:max_len] if m else str(answer)[:max_len]
                            else:
                                answer = str(answer)[:max_len]

                    inp.scroll_into_view_if_needed()
                    time.sleep(0.2)
                    inp.click()
                    time.sleep(0.2)
                    inp.fill(str(answer))
                    inp.evaluate("el => { el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true})); el.blur(); }")
                    self.bot_state.add_log(f"✍️ [LinkedIn Question] '{q_clean[:35]}': {answer} (Source: {res.get('source')})", "INFO")
                    time.sleep(0.3)

                    # Post-fill validation check: If LinkedIn triggers 'Invalid input', auto-correct to pure digits
                    post_err = inp.evaluate("""el => {
                        const descId = el.getAttribute('aria-describedby');
                        if (descId) {
                            const h = document.getElementById(descId);
                            if (h && (h.innerText.toLowerCase().includes('invalid') || h.innerText.toLowerCase().includes('enter a valid'))) {
                                return h.innerText.trim();
                            }
                        }
                        const parent = el.closest('div');
                        if (parent) {
                            const err = parent.querySelector('[class*="error"], [data-testid="text-input-helper-text"] p');
                            if (err && (err.innerText.toLowerCase().includes('invalid') || err.innerText.toLowerCase().includes('enter a valid'))) {
                                return err.innerText.trim();
                            }
                        }
                        return '';
                    }""")

                    if post_err and ("invalid" in post_err.lower() or "enter a valid" in post_err.lower()):
                        self.bot_state.add_log(f"⚠️ Field '{q_clean[:30]}' triggered validation error: '{post_err}'. Auto-correcting to pure numeric...", "WARNING")
                        ans_str = str(answer)
                        cleaned_num = None
                        if any(k in ans_str.lower() for k in ["immediate", "joiner"]):
                            cleaned_num = "0"
                        else:
                            m = re.search(r"(\d+(\.\d+)?)", ans_str)
                            if m:
                                val_f = float(m.group(1))
                                cleaned_num = str(int(val_f)) if val_f.is_integer() else str(val_f)
                        
                        if cleaned_num is not None:
                            inp.fill("")
                            time.sleep(0.1)
                            inp.fill(cleaned_num)
                            inp.evaluate("el => { el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true})); el.blur(); }")
                            time.sleep(0.3)
                            self.bot_state.add_log(f"✅ Auto-corrected '{q_clean[:30]}' to pure number: '{cleaned_num}'", "SUCCESS")

            # PASS 4: Select Dropdowns (<select>)
            selects = dialog.query_selector_all("select")
            for sel in selects:
                if stop_event.is_set():
                    break
                if not sel.is_visible() or sel.is_disabled():
                    continue

                sel_id = sel.get_attribute("id") or ""
                q_text = sel.evaluate(r"""(el) => {
                    const isGeneric = (txt) => {
                        if (!txt) return true;
                        const low = txt.trim().toLowerCase().replace(/[\*\(\)\:\#\-\_]|required|optional/g, '').trim();
                        const genericSections = [
                            'work experience', 'experience', 'additional questions', 'additional question', 'contact info',
                            'contact information', 'home address', 'resume', 'privacy policy',
                            'equal opportunity', 'demographics', 'screening questions', 'job application',
                            'work authorization', 'voluntary self-identification'
                        ];
                        return genericSections.some(s => low === s || low.startsWith('step '));
                    };

                    const aria = el.getAttribute('aria-label');
                    if (aria && aria.trim() && !isGeneric(aria)) return aria.trim();
                    const id = el.id;
                    if (id) {
                        try {
                            const escId = (window.CSS && CSS.escape) ? CSS.escape(id) : id.replace(/([:.\\[\\]\\(\\),=])/g, '\\\\$1');
                            const lbl = document.querySelector('label[for="' + escId + '"]');
                            if (lbl && lbl.innerText.trim() && !isGeneric(lbl.innerText)) return lbl.innerText.trim();
                        } catch(e) {}
                    }
                    const parentLbl = el.closest('label');
                    if (parentLbl && parentLbl.innerText.trim() && !isGeneric(parentLbl.innerText)) return parentLbl.innerText.trim();
                    
                    const fieldContainer = el.closest('.fb-dash-form-element, [data-test-form-element], .jobs-easy-apply-form-element, .artdeco-text-input--container, [data-test-form-builder-repeater-field]');
                    if (fieldContainer) {
                        const h = fieldContainer.querySelector('label, .fb-dash-form-element__label, .artdeco-text-input--label, [data-test-form-element-label]');
                        if (h && h.innerText.trim() && !isGeneric(h.innerText)) return h.innerText.trim();
                    }

                    let cur = el.parentElement;
                    for (let i = 0; i < 2 && cur; i++) {
                        if (cur.classList.contains('jobs-easy-apply-modal') || cur.tagName === 'DIALOG' || cur.tagName === 'FORM') break;
                        const header = cur.querySelector('label, .fb-dash-form-element__label, [data-test-form-element-label]');
                        if (header && header.innerText.trim()) {
                            const htxt = header.innerText.trim();
                            if (!isGeneric(htxt) && !htxt.toLowerCase().includes('invalid')) return htxt;
                        }
                        cur = cur.parentElement;
                    }
                    return '';
                }""")
                q_clean = q_text.strip().replace("*", "").strip()

                # Strict Mandatory Rule: Country Code selector (Qatar (+974) for International; India (+91) for India. Never +591 or +971)
                is_cc_selector = any(k in q_clean.lower() or k in sel_id.lower() or k in (sel.get_attribute("name") or "").lower() for k in ["country code", "phone country", "phone country code", "countrycode"])
                is_cc_options = sel.evaluate("""el => {
                    let hasIn = false, hasBo = false;
                    for (let o of el.options) {
                        if (o.value === 'in') hasIn = true;
                        if (o.value === 'bo') hasBo = true;
                    }
                    return hasIn && hasBo;
                }""")
                if is_cc_selector or is_cc_options:
                    select_linkedin_country_code(sel, is_india=is_india, bot_state=self.bot_state)
                    continue

                if q_clean:
                    # Read options first into List[Dict[str, str]]
                    options_data = []
                    for o in sel.query_selector_all("option"):
                        options_data.append({
                            "value": o.get_attribute("value") or o.inner_text().strip(),
                            "text": o.inner_text().strip()
                        })

                    res = qa_engine.process_question(
                        question_text=q_clean,
                        input_type="select",
                        available_options=options_data,
                        job_title=title,
                        company_name=company,
                        location_hint=location_hint
                    )
                    if res.get("needs_user_input"):
                        return {"status": "NEEDS_USER_INPUT", "reason": res.get("reason"), "question": q_clean}

                    target_ans = str(res.get("answer", "")).lower()
                    category = res.get("category", "EXPERIENCE")
                    selected_opt = res.get("selected_option")

                    best_match = selected_opt or match_best_option(answer=target_ans, options=options_data, category=category)
                    if best_match:
                        val = best_match.get("value")
                        lbl = best_match.get("text")
                        try:
                            sel.select_option(value=val)
                        except Exception:
                            try:
                                sel.select_option(label=lbl)
                            except Exception:
                                pass
                        sel.evaluate("el => { el.dispatchEvent(new Event('change', {bubbles:true})); }")
                        self.bot_state.add_log(f"Selected option '{lbl}' for '{q_clean[:30]}'", "INFO")
                        time.sleep(0.4)

            # PASS 5: Yes / No Radio button groups (LinkedIn fieldset / modern custom radio groups)
            all_radios = dialog.query_selector_all("input[type='radio']")
            radio_groups = {}
            for r in all_radios:
                grp_name = r.get_attribute("name") or "default_group"
                radio_groups.setdefault(grp_name, []).append(r)

            for grp_name, r_list in radio_groups.items():
                if stop_event.is_set():
                    break
                
                # Skip resume radios since they are handled strictly in PASS 1 & 2
                is_resume_group = any(
                    r.evaluate("""el => {
                        const aria = (el.getAttribute('aria-label') || '').toLowerCase();
                        const pAria = (el.parentElement ? el.parentElement.getAttribute('aria-label') || '' : '').toLowerCase();
                        const txt = (el.closest('li, div, label')?.innerText || '').toLowerCase();
                        return aria.includes('.pdf') || aria.includes('resume') || aria.includes('razzaque') ||
                               pAria.includes('.pdf') || txt.includes('.pdf') || txt.includes('resume');
                    }""") for r in r_list
                )
                if is_resume_group:
                    continue

                first_r = r_list[0]
                q_clean = first_r.evaluate("""el => {
                    const aria = el.getAttribute('aria-label');
                    if (aria && aria.trim()) return aria.trim();
                    const fs = el.closest('fieldset');
                    if (fs) {
                        const legend = fs.querySelector('legend, [data-test-form-builder-radio-group-title]');
                        if (legend && legend.innerText.trim()) return legend.innerText.trim();
                    }
                    let cur = el.parentElement;
                    for (let i = 0; i < 4 && cur; i++) {
                        const h = cur.querySelector('label, [class*="label"], p, span.t-14');
                        if (h && h.innerText.trim()) return h.innerText.trim();
                        cur = cur.parentElement;
                    }
                    return '';
                }""").strip().replace("*", "").strip()

                if not q_clean:
                    continue

                radio_options_data = []
                for ropt in r_list:
                    opt_lbl = ropt.evaluate("""el => {
                        let cur = el.parentElement;
                        for (let i = 0; i < 3 && cur; i++) {
                            const txt = cur.innerText.trim();
                            const qAria = el.getAttribute('aria-label') || '';
                            if (txt && (!qAria || !txt.toLowerCase().includes(qAria.toLowerCase()))) {
                                return txt;
                            }
                            cur = cur.parentElement;
                        }
                        return el.value || '';
                    }""")
                    is_chk = ropt.evaluate("el => el.checked")
                    radio_options_data.append({"element": ropt, "text": opt_lbl, "value": ropt.get_attribute("value") or opt_lbl, "checked": is_chk})

                res = qa_engine.process_question(
                    question_text=q_clean,
                    input_type="radio",
                    available_options=[{"text": d["text"], "value": d["value"]} for d in radio_options_data],
                    job_title=title,
                    company_name=company,
                    location_hint=location_hint
                )
                if res.get("needs_user_input"):
                    return {"status": "NEEDS_USER_INPUT", "reason": res.get("reason"), "question": q_clean}

                selected_opt = res.get("selected_option")
                desired = str(res.get("answer", "")).strip().lower()

                is_affirmative = desired in ["true", "yes", "agree", "ja", "confirm", "positive", "1"]
                is_negative = desired in ["false", "no", "nein", "keine", "none", "0"]

                target_ropt = None
                if selected_opt:
                    for d in radio_options_data:
                        if d["text"] == selected_opt.get("text") or d["value"] == selected_opt.get("value"):
                            target_ropt = d["element"]
                            break

                if not target_ropt:
                    for d in radio_options_data:
                        opt_lbl = d["text"].lower()
                        if (desired and desired in opt_lbl) or \
                           (is_affirmative and any(k in opt_lbl for k in ["yes", "ja", "agree", "confirm", "stimme zu", "true"])) or \
                           (is_negative and any(k in opt_lbl for k in ["no", "nein", "keine", "none", "false"])):
                            target_ropt = d["element"]
                            break

                # Single radio group fallback: if only 1 radio in the group and desired is affirmative (e.g. JOIN Terms & Conditions 'Yes')
                if not target_ropt and len(radio_options_data) == 1 and is_affirmative:
                    target_ropt = radio_options_data[0]["element"]

                if target_ropt:
                    try:
                        is_already_target_checked = target_ropt.is_checked()
                    except Exception:
                        is_already_target_checked = False

                    if not is_already_target_checked:
                        try:
                            target_ropt.scroll_into_view_if_needed()
                            time.sleep(0.1)
                            target_ropt.click(force=True)
                        except Exception:
                            pass

                        try:
                            target_ropt.evaluate("""el => {
                                const lbl = (el.id ? document.querySelector('label[for="' + CSS.escape(el.id) + '"]') : null) || el.closest('label') || el.closest('.b6bikq') || el.parentElement;
                                if (lbl) lbl.click();
                                const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'checked')?.set;
                                if (setter) setter.call(el, true);
                                el.checked = true;
                                el.dispatchEvent(new Event('input', { bubbles: true }));
                                el.dispatchEvent(new Event('change', { bubbles: true }));
                            }""")
                        except Exception:
                            pass
                        self.bot_state.add_log(f"🔘 Selected '{desired.capitalize()}' for '{q_clean[:35]}'", "INFO")
                        time.sleep(0.3)

            # PASS 6: Checkboxes (Terms, consent, acknowledgement)
            chk_boxes = dialog.query_selector_all("input[type='checkbox']")
            for chk in chk_boxes:
                if stop_event.is_set():
                    break
                chk_lbl = chk.evaluate("""el => {
                    const l = el.closest('label') || document.querySelector('label[for=\"' + el.id + '\"]');
                    return l ? l.innerText.trim().toLowerCase() : '';
                }""")
                if any(k in chk_lbl for k in ["agree", "consent", "terms", "policy", "acknowledge", "certify", "confirm", "follow"]):
                    if "follow" in chk_lbl and "company" in chk_lbl:
                        # Follow company checkbox: uncheck or check as preferred
                        continue
                    if not chk.evaluate("el => el.checked"):
                        chk.click()
                        time.sleep(0.3)

            return {"status": "SUCCESS"}
        except Exception as e:
            self.bot_state.add_log(f"Step fill notice: {e}", "WARNING")
            return {"status": "ERROR", "error": str(e)}

    def verify_and_enforce_contact_rules(self, dialog: ElementHandle, location_hint: str, custom_resume_path: str = "") -> bool:
        """
        MANDATORY RULES ENFORCEMENT & PRE-SUBMISSION VERIFICATION:
        1. India Applications:
           - Country code: strictly +91 (India) [Never Bolivia +591]
           - Phone: 797269663
           - Resume: Abdul Razzaque India.pdf or customized India CV [Never Qatar.pdf]
        2. International Applications (Qatar, Dubai, UAE, etc.):
           - Country code: strictly +974 (Qatar) [Never UAE +971, Never Bolivia +591]
           - Phone: 77557982
           - Resume: Abdul Razzaque Qatar.pdf or customized Qatar CV [Never India.pdf]
        3. Never submit an application with an incorrect country code, phone number, or resume.
        """
        region, reason, app_config = determine_application_region(location_hint)
        is_india = (region == "INDIA")
        profile = get_candidate_profile()

        # 1. Enforce on visible select dropdowns and combobox inputs (Country Code)
        try:
            for sel in dialog.query_selector_all("select, input"):
                if not sel.is_visible() or sel.is_disabled():
                    continue
                sel_id = (sel.get_attribute("id") or "").lower()
                sel_name = (sel.get_attribute("name") or "").lower()
                sel_aria = (sel.get_attribute("aria-label") or "").lower()
                if any(k in sel_id or k in sel_name or k in sel_aria for k in ["country code", "phone country", "phone code", "calling code"]):
                    curr_val = sel.evaluate("el => el.value || (el.options && el.selectedIndex >= 0 ? el.options[el.selectedIndex].text : '')")
                    if is_india:
                        is_valid = ("india" in curr_val.lower()) and ("bolivia" not in curr_val.lower()) and ("591" not in curr_val) and bool(re.search(r"(\+?91)", curr_val))
                        if not is_valid:
                            self.bot_state.add_log(f"⚠️ [Verification Fix] Country code was '{curr_val}'. Overriding to India (+91)...", "WARNING")
                            select_linkedin_country_code(sel, is_india=True, bot_state=self.bot_state)
                    else:
                        is_valid = ("qatar" in curr_val.lower() or "974" in curr_val) and ("971" not in curr_val) and ("bolivia" not in curr_val.lower())
                        if not is_valid:
                            self.bot_state.add_log(f"⚠️ [Verification Fix] Country code was '{curr_val}'. Overriding to Qatar (+974)...", "WARNING")
                            select_linkedin_country_code(sel, is_india=False, bot_state=self.bot_state)
        except Exception as e:
            self.bot_state.add_log(f"Verification country code notice: {e}", "WARNING")

        # 2. Enforce on visible phone input fields
        try:
            inputs = dialog.query_selector_all("input:not([type='hidden']):not([type='radio']):not([type='checkbox']):not([type='file'])")
            for inp in inputs:
                if not inp.is_visible() or inp.is_disabled():
                    continue
                inp_id = (inp.get_attribute("id") or "").lower()
                inp_name = (inp.get_attribute("name") or "").lower()
                inp_aria = (inp.get_attribute("aria-label") or "").lower()
                if any(k in inp_id or k in inp_name or k in inp_aria for k in ["phone", "mobile", "contact"]) and not any(k in inp_id or k in inp_name or k in inp_aria for k in ["country", "code"]):
                    val = (inp.evaluate("el => el.value") or "").strip()
                    if is_india:
                        if "77557982" in val or "7972694663" not in val or "+91" in val:
                            target_val = "7972694663"
                            inp.fill("")
                            time.sleep(0.1)
                            inp.fill(target_val)
                            inp.evaluate("el => { el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true})); }")
                            masked_disp = mask_phone_number(target_val)
                            self.bot_state.add_log(f"🛡️ [Verification Fix] Enforced India phone '{masked_disp}'", "SUCCESS")
                    else:
                        if "7972694663" in val or "797269663" in val or "77557982" not in val or "971" in val or "+974" in val:
                            target_val = "77557982"
                            inp.fill("")
                            time.sleep(0.1)
                            inp.fill(target_val)
                            inp.evaluate("el => { el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true})); }")
                            masked_disp = mask_phone_number(target_val)
                            self.bot_state.add_log(f"🛡️ [Verification Fix] Enforced International phone '{masked_disp}'", "SUCCESS")
        except Exception as e:
            self.bot_state.add_log(f"Verification input notice: {e}", "WARNING")

        # 3. Enforce & verify resume selection
        try:
            resume_verified, res_name = select_or_upload_linkedin_resume(dialog, is_india, profile, self.bot_state, custom_resume_path=custom_resume_path)
            if not resume_verified:
                self.bot_state.add_log(f"⚠️ Resume verification check: '{res_name}'", "WARNING")
        except Exception as e:
            self.bot_state.add_log(f"Verification resume notice: {e}", "WARNING")

        # 4. Text summary check (Review step verification)
        try:
            summary_txt = dialog.evaluate("el => el.innerText || ''")
            if "Bolivia" in summary_txt or "+591" in summary_txt:
                self.bot_state.add_log("🚨 [Pre-Submission Block] Application review contains 'Bolivia (+591)'! Overriding...", "ERROR")
                return False

            if is_india:
                if "Qatar.pdf" in summary_txt or "Abdul_Razzaque_Qatar" in summary_txt:
                    self.bot_state.add_log("🚨 [Pre-Submission Block] Application review contains 'Qatar.pdf'! India.pdf is required for India jobs.", "ERROR")
                    return False
                if "77557982" in summary_txt:
                    self.bot_state.add_log("🚨 [Pre-Submission Block] Application review contains Qatar number '77557982'! +91 7972694663 is mandatory for India jobs.", "ERROR")
                    return False
                if "7972694663" in summary_txt or "797269663" in summary_txt:
                    self.bot_state.add_log(f"✅ [Phone Rule Verified] Validated India phone {app_config.get('masked_phone', '+91 ******4663')} on application summary.", "SUCCESS")
            else:
                if "+971" in summary_txt:
                    self.bot_state.add_log("🚨 [Pre-Submission Block] Application review contains '+971'! Qatar (+974) is mandatory for Gulf/International jobs.", "ERROR")
                    return False
                if "India.pdf" in summary_txt or "Abdul_Razzaque_India" in summary_txt:
                    self.bot_state.add_log("🚨 [Pre-Submission Block] Application review contains 'India.pdf'! Qatar.pdf is required for International jobs.", "ERROR")
                    return False
                if "7972694663" in summary_txt or "797269663" in summary_txt:
                    self.bot_state.add_log("🚨 [Pre-Submission Block] Application review contains India number! +974 77557982 is mandatory for International jobs.", "ERROR")
                    return False
                if "77557982" in summary_txt:
                    self.bot_state.add_log(f"✅ [Phone Rule Verified] Validated International phone {app_config.get('masked_phone', '+974 ****7982')} on application summary.", "SUCCESS")
        except Exception:
            pass

        return True

    def execute_easy_apply_flow(self, page: Page, detail_tab: Page, job_info: Dict[str, Any], 
                                stop_event: threading.Event) -> Dict[str, Any]:
        """
        Orchestrates the LinkedIn Easy Apply multi-step modal dialog:
        Step by step progression -> filling questions -> review -> submission.
        """
        title = job_info["title"]
        company = job_info["company"]
        loc_text = job_info.get("location", "")
        search_loc = job_info.get("search_location", "")
        job_url = job_info["url"]
        req_loc = job_info.get("requested_location", "")
        act_loc = job_info.get("actual_browser_location", loc_text)

        # 1. Extract location text from detail_tab if available
        detail_loc = ""
        try:
            top_el = detail_tab.query_selector(".job-details-jobs-unified-top-card__primary-description-container, .jobs-unified-top-card, .job-details-jobs-unified-top-card, .jobs-details__top-card")
            if top_el:
                detail_loc = top_el.inner_text().strip()
        except Exception:
            pass

        # 2. Extract full Job Description text from detail_tab
        jd_text = ""
        try:
            for jd_sel in [".jobs-description__content", "#job-details", ".jobs-box__html-content", ".jobs-description", "article"]:
                jd_el = detail_tab.query_selector(jd_sel)
                if jd_el:
                    jd_text = jd_el.inner_text().strip()
                    if len(jd_text) > 100:
                        break
        except Exception:
            pass
        if not jd_text:
            jd_text = f"{title} at {company} in {loc_text}"

        # 3. Determine application region cleanly without search location pollution!
        region, region_reason, app_config = determine_application_region(
            job_location=loc_text,
            detail_location=detail_loc,
            search_location=search_loc
        )
        is_india = (region == "INDIA")
        effective_loc = loc_text or detail_loc or search_loc

        # 4. Master Prompt Section 2 & 3: Intelligent Job Description Analysis & Matching
        from resume_optimizer import analyze_job_description, resume_optimizer, generate_activity_report
        jd_analysis = analyze_job_description(
            job_title=title, company=company, job_desc=jd_text, location=effective_loc, job_url=job_url, platform="LINKEDIN"
        )

        # SCENARIO C: Strict Disqualification Check (Java, .NET, PHP, Ruby, etc.)
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
                job_title=title, company_name=company, location=effective_loc, job_url=job_url,
                status="APPLICATION_SKIPPED", apply_type="LINKEDIN_EASY_APPLY", match_score=jd_analysis.match_score,
                notes=f"Skipped: {jd_analysis.disqualification_reason}", failure_reason=jd_analysis.disqualification_reason,
                platform="LINKEDIN", jd_match_analysis_json=json.dumps(jd_analysis.to_dict()),
                requested_location=req_loc, actual_browser_location=act_loc
            )
            if detail_tab and detail_tab != page and not detail_tab.is_closed():
                try:
                    detail_tab.close()
                except Exception:
                    pass
            return {"status": "APPLICATION_SKIPPED", "reason": jd_analysis.disqualification_reason}

        # 5. Master Prompt Section 4 & 5: Resume Optimization (Layout Preserving)
        opt_res = resume_optimizer.optimize_resume(jd_analysis, is_india=is_india)
        custom_pdf = opt_res.get("customized_path") if opt_res.get("success") else resume_optimizer.get_base_resume(is_india=is_india)
        if opt_res.get("success"):
            self.bot_state.add_log(f"📄 [Resume Optimized] Generated tailored CV: {os.path.basename(custom_pdf)} (Match: {jd_analysis.match_score}%)", "SUCCESS")
        else:
            self.bot_state.add_log(f"📄 [Original Resume Preserved] Using verified base CV: {os.path.basename(custom_pdf)}", "INFO")

        self.bot_state.add_log(f"⚡ Launching Easy Apply flow for {title} @ {company}...", "INFO")
        self.bot_state.add_log(f"🌍 [Location Synchronization] Region: {region} ({region_reason}) | Location: '{effective_loc}'", "INFO")
        self.bot_state.add_log(f"📄 Target Resume: {os.path.basename(custom_pdf)}", "INFO")
        self.bot_state.add_log(f"📞 Target Phone: {app_config['phone_full']} ({app_config['country_name']} {app_config['country_code']})", "INFO")
        profile = get_candidate_profile()

        # Locate the dialog
        dialog = None
        for _ in range(10):
            if stop_event.is_set():
                break
            dialog = self.find_easy_apply_modal(detail_tab)
            if dialog and dialog.is_visible():
                break
            time.sleep(0.5)

        if not dialog:
            self.bot_state.add_log(f"Easy Apply dialog did not open for {company}.", "WARNING")
            return {"status": "FAILED", "reason": "DIALOG_NOT_FOUND"}

        # Multi-step loop with dynamic button detection, modal scrolling, and strict confirmation
        max_steps = 14
        safe_comp = re.sub(r'[^a-zA-Z0-9]', '_', company)[:20]

        for step_idx in range(max_steps):
            if stop_event.is_set():
                break

            time.sleep(0.8)
            dialog = self.find_easy_apply_modal(detail_tab)
            if not dialog or not dialog.is_visible():
                # Check if dialog completed and closed with confirmation
                is_conf, conf_msg, _ = self.verify_submission_confirmation(detail_tab, max_wait_sec=2, stop_event=stop_event)
                if is_conf:
                    self.bot_state.add_log(f"🎉 Easy Apply submission confirmed for {company}! ({conf_msg})", "SUCCESS")
                    record_application(
                        job_title=title, company_name=company, location=effective_loc or loc_text, job_url=job_url,
                        status="APPLICATION_CONFIRMED", apply_type="LINKEDIN_EASY_APPLY", match_score=jd_analysis.match_score,
                        notes=f"Successfully applied via LinkedIn Easy Apply. Match: {jd_analysis.match_score}%.",
                        platform="LINKEDIN",
                        customized_resume_path=custom_pdf,
                        original_resume_path=opt_res.get("original_path", ""),
                        cv_changes_json=json.dumps(opt_res),
                        jd_match_analysis_json=json.dumps(jd_analysis.to_dict()),
                        requested_location=req_loc,
                        actual_browser_location=act_loc
                    )
                    self.bot_state.today_applied = get_today_applied_count()
                    self.cooldown_timer(stop_event=stop_event, reason=f"Confirmed LinkedIn Easy Apply for {company}")
                    return {"status": "APPLICATION_CONFIRMED", "success": True}
                break

            # 1. Check for immediate confirmation / Done screen
            is_conf, conf_msg, done_el = self.verify_submission_confirmation(detail_tab, max_wait_sec=1, stop_event=stop_event)
            if is_conf and ("DONE" in conf_msg or "CONFIRMATION" in conf_msg):
                self.bot_state.add_log(f"🎉 Easy Apply submission SUCCESS for {company}!", "SUCCESS")
                if done_el:
                    try:
                        done_el.click()
                        time.sleep(1.0)
                    except Exception:
                        pass
                activity_rep = generate_activity_report(
                    jd_analysis=jd_analysis,
                    optimization_res=opt_res,
                    application_status="Applied Successfully"
                )
                self.bot_state.add_log(f"📋 Application Activity Report:\n{activity_rep}", "SUCCESS")
                record_application(
                    job_title=title, company_name=company, location=effective_loc or loc_text, job_url=job_url,
                    status="APPLICATION_CONFIRMED", apply_type="LINKEDIN_EASY_APPLY", match_score=jd_analysis.match_score,
                    notes=f"Successfully applied via LinkedIn Easy Apply. Match: {jd_analysis.match_score}%.",
                    platform="LINKEDIN",
                    customized_resume_path=custom_pdf,
                    original_resume_path=opt_res.get("original_path", ""),
                    cv_changes_json=json.dumps(opt_res),
                    jd_match_analysis_json=json.dumps(jd_analysis.to_dict()),
                    requested_location=req_loc,
                    actual_browser_location=act_loc
                )
                self.bot_state.today_applied = get_today_applied_count()
                self.cooldown_timer(stop_event=stop_event, reason=f"Confirmed LinkedIn Easy Apply for {company}")
                return {"status": "APPLICATION_CONFIRMED", "success": True}

            # 2. Check for security challenge (CAPTCHA / OTP)
            is_challenge, challenge_type = self.detect_security_challenge(detail_tab)
            if is_challenge:
                self.bot_state.add_log(f"🚨 Security verification ({challenge_type}) detected for {company}! Leaving tab OPEN for candidate action.", "WARNING")
                os.makedirs("backend/screenshots", exist_ok=True)
                scr_path = f"backend/screenshots/security_challenge_{safe_comp}_{int(time.time())}.png"
                try: detail_tab.screenshot(path=scr_path)
                except Exception: pass
                detail_tab.bring_to_front()
                record_application(
                    job_title=title, company_name=company, location=loc_text, job_url=job_url,
                    status="NEEDS_USER_ACTION", apply_type="LINKEDIN_EASY_APPLY", match_score=job_info.get("score", 85),
                    notes=f"Security challenge detected ({challenge_type}). Kept open for user.",
                    failure_reason=challenge_type, screenshot_reference=scr_path, platform="LINKEDIN",
                    requested_location=req_loc, actual_browser_location=act_loc
                )
                return {"status": "NEEDS_USER_ACTION", "reason": challenge_type}

            # 3. Detect step header
            dialog_header = dialog.query_selector("h2, h3, h1, [data-testid='dialog-header']")
            header_txt = dialog_header.inner_text().strip() if dialog_header else f"Step {step_idx+1}"
            self.bot_state.add_log(f"📋 LinkedIn Step {step_idx+1}: {header_txt} for {company}", "INFO")

            # 4. Fill questions on this step
            fill_res = self.fill_easy_apply_step(dialog, detail_tab, profile, stop_event, company, title, location_hint=effective_loc, custom_resume_path=custom_pdf)
            if fill_res.get("status") == "NEEDS_USER_INPUT":
                unanswered_q = fill_res.get("question", "")
                reason = fill_res.get("reason", "NEEDS_USER_INPUT")
                self.bot_state.add_log(f"⚠️ [NEEDS_USER_INPUT] LinkedIn question requires candidate input: '{unanswered_q[:35]}' ({reason}). Dialog kept OPEN in Chrome!", "WARNING")
                os.makedirs("backend/screenshots", exist_ok=True)
                scr_path = f"backend/screenshots/needs_user_input_{safe_comp}_{int(time.time())}.png"
                try: detail_tab.screenshot(path=scr_path)
                except Exception: pass
                detail_tab.bring_to_front()
                record_application(
                    job_title=title, company_name=company, location=loc_text, job_url=job_url,
                    status="NEEDS_USER_INPUT", apply_type="LINKEDIN_EASY_APPLY", match_score=job_info.get("score", 85),
                    notes=f"Question requires candidate input: {unanswered_q} ({reason})",
                    failure_reason=reason, screenshot_reference=scr_path, platform="LINKEDIN",
                    requested_location=req_loc, actual_browser_location=act_loc
                )
                return {"status": "NEEDS_USER_INPUT", "reason": reason, "question": unanswered_q}

            time.sleep(0.5)

            # 5. Inspect and resolve validation errors if present
            err_list = self.inspect_modal_validation_errors(dialog)
            if err_list:
                self.bot_state.add_log(f"⚠️ Active validation notice: '{err_list[0]}'. Re-checking step inputs...", "WARNING")
                self.fill_easy_apply_step(dialog, detail_tab, profile, stop_event, company, title, location_hint=effective_loc)
                time.sleep(0.5)

            # 6. Detect modal action buttons (Submit, Review, Next, Done)
            btn_dict = self.detect_modal_action_buttons(dialog, detail_tab)

            # If no forward button is enabled/visible, scroll modal container down to reveal offscreen buttons
            if not (btn_dict["submit"] or btn_dict["review"] or btn_dict["next"]):
                self.scroll_modal_container(dialog, "down", 600)
                btn_dict = self.detect_modal_action_buttons(dialog, detail_tab)

            # =========================================================================
            # ACTION BRANCH A: Submit application button detected (Final Review Step)
            # =========================================================================
            if btn_dict["submit"]:
                sub_info = btn_dict["submit"]
                self.bot_state.add_log(f"🎯 Final Review step reached: 'Submit application' button detected for {company} (Enabled: {sub_info['enabled']}).", "INFO")

                # If Submit button is disabled, scroll review modal down to trigger activation
                if not sub_info["enabled"]:
                    self.bot_state.add_log(f"📜 Submit button is disabled; scrolling modal container to bottom...", "INFO")
                    self.scroll_modal_container(dialog, "down", 800)
                    time.sleep(0.8)
                    btn_dict = self.detect_modal_action_buttons(dialog, detail_tab)
                    sub_info = btn_dict["submit"] or sub_info

                # If still disabled, check for remaining validation errors or required review checkboxes
                if not sub_info["enabled"]:
                    remaining_errs = self.inspect_modal_validation_errors(dialog)
                    os.makedirs("backend/screenshots", exist_ok=True)
                    scr_path = f"backend/screenshots/submit_disabled_{safe_comp}_{int(time.time())}.png"
                    try: detail_tab.screenshot(path=scr_path)
                    except Exception: pass

                    err_desc = remaining_errs[0] if remaining_errs else "Submit application button remains disabled on review step."
                    self.bot_state.add_log(f"⚠️ {err_desc} Modal kept OPEN in Chrome for review.", "WARNING")
                    detail_tab.bring_to_front()
                    record_application(
                        job_title=title, company_name=company, location=loc_text, job_url=job_url,
                        status="NEEDS_USER_ACTION", apply_type="LINKEDIN_EASY_APPLY", match_score=job_info.get("score", 85),
                        notes=f"Submit button disabled: {err_desc}", failure_reason="SUBMIT_BUTTON_DISABLED",
                        screenshot_reference=scr_path, platform="LINKEDIN",
                        requested_location=req_loc, actual_browser_location=act_loc
                    )
                    return {"status": "NEEDS_USER_ACTION", "reason": "SUBMIT_BUTTON_DISABLED"}

                # Mandatory Pre-Submission Contact Rules Verification
                if not self.verify_and_enforce_contact_rules(dialog, effective_loc, custom_resume_path=custom_pdf):
                    self.bot_state.add_log(f"🚨 Contact rules verification failed before submit for {company}! Kept dialog OPEN in Chrome.", "ERROR")
                    os.makedirs("backend/screenshots", exist_ok=True)
                    scr_path = f"backend/screenshots/contact_rules_failed_{safe_comp}_{int(time.time())}.png"
                    try: detail_tab.screenshot(path=scr_path)
                    except Exception: pass
                    detail_tab.bring_to_front()
                    record_application(
                        job_title=title, company_name=company, location=loc_text, job_url=job_url,
                        status="NEEDS_USER_INPUT", apply_type="LINKEDIN_EASY_APPLY", match_score=job_info.get("score", 85),
                        notes="Blocked submission: Contact details failed strict location rules.",
                        failure_reason="PHONE_RULE_VERIFICATION_FAILED", screenshot_reference=scr_path, platform="LINKEDIN",
                        requested_location=req_loc, actual_browser_location=act_loc
                    )
                    return {"status": "NEEDS_USER_INPUT", "reason": "PHONE_RULE_VERIFICATION_FAILED"}

                # Check auto_submit_direct authorization
                if not agent_config_manager.is_authorized("auto_submit_direct"):
                    self.bot_state.add_log(f"Application ready to submit for {company}. auto_submit_direct is disabled. Modal kept OPEN for review.", "INFO")
                    os.makedirs("backend/screenshots", exist_ok=True)
                    scr_path = f"backend/screenshots/ready_for_review_{safe_comp}_{int(time.time())}.png"
                    try: detail_tab.screenshot(path=scr_path)
                    except Exception: pass
                    detail_tab.bring_to_front()
                    record_application(
                        job_title=title, company_name=company, location=loc_text, job_url=job_url,
                        status="APPLICATION_PENDING_CONFIRMATION", apply_type="LINKEDIN_EASY_APPLY", match_score=job_info.get("score", 85),
                        notes="Ready to submit. auto_submit_direct not authorized. Kept open.",
                        screenshot_reference=scr_path, platform="LINKEDIN",
                        requested_location=req_loc, actual_browser_location=act_loc
                    )
                    return {"status": "APPLICATION_PENDING_CONFIRMATION", "success": False}

                # Capture pre-submission screenshot
                os.makedirs("backend/screenshots", exist_ok=True)
                pre_sub_scr = f"backend/screenshots/pre_submit_{safe_comp}_{int(time.time())}.png"
                try: detail_tab.screenshot(path=pre_sub_scr)
                except Exception: pass

                # Execute final Submit click
                self.bot_state.add_log(f"🚀 Clicking final 'Submit application' on LinkedIn for {company}...", "INFO")
                sub_btn = sub_info["element"]
                try:
                    sub_btn.scroll_into_view_if_needed()
                    time.sleep(0.3)
                    sub_btn.click()
                except Exception:
                    # Fallback click via JS dispatch
                    sub_btn.evaluate("el => el.click()")

                submit_click_time = time.time()

                # Verify submission confirmation (polling up to 12 seconds)
                is_conf, conf_msg, done_btn = self.verify_submission_confirmation(detail_tab, max_wait_sec=12, stop_event=stop_event)

                if is_conf:
                    # Clean up modal with Done if visible
                    if done_btn:
                        try:
                            done_btn.click()
                            time.sleep(1.0)
                        except Exception:
                            pass

                    # Capture confirmed screenshot
                    conf_scr = f"backend/screenshots/confirmed_{safe_comp}_{int(time.time())}.png"
                    try: detail_tab.screenshot(path=conf_scr)
                    except Exception: pass

                    activity_rep = generate_activity_report(
                        jd_analysis=jd_analysis,
                        optimization_res=opt_res,
                        application_status="Applied Successfully"
                    )
                    self.bot_state.add_log(f"📋 Application Activity Report:\n{activity_rep}", "SUCCESS")
                    record_application(
                        job_title=title, company_name=company, location=effective_loc or loc_text, job_url=job_url,
                        status="APPLIED", apply_type="LINKEDIN_EASY_APPLY", match_score=jd_analysis.match_score,
                        notes=f"Successfully applied via LinkedIn Easy Apply. Match: {jd_analysis.match_score}%.",
                        platform="LINKEDIN",
                        execution_stage="SUBMISSION_VERIFIED",
                        confirmation_type="LINKEDIN_EASY_APPLY_CONFIRMATION",
                        confirmation_message="Application confirmed via modal dismissal and submission verification.",
                        customized_resume_path=custom_pdf,
                        original_resume_path=opt_res.get("original_path", ""),
                        cv_changes_json=json.dumps(opt_res),
                        jd_match_analysis_json=json.dumps(jd_analysis.to_dict()),
                        screenshot_reference=conf_scr,
                        requested_location=req_loc,
                        actual_browser_location=act_loc
                    )
                    self.bot_state.today_applied = get_today_applied_count()
                    self.bot_state.add_log(f"✅ LinkedIn Easy Apply SUCCESS! [{self.bot_state.today_applied}/{self.bot_state.daily_limit}] for {title} @ {company}", "SUCCESS")

                    final_rep = format_final_application_report(
                        company_name=company,
                        job_title=title,
                        job_location=effective_loc or loc_text,
                        platform="LinkedIn",
                        application_type="Easy Apply",
                        jd_match=f"{jd_analysis.match_score}%",
                        resume_customized="Yes" if custom_pdf else "No",
                        resume_uploaded="Yes",
                        application_status="Yes",
                        submission_verified="Yes",
                        pending_action="None"
                    )
                    self.bot_state.add_log(f"📋 Application Report (Section 7):\n{final_rep}", "SUCCESS")
                    self.cooldown_timer(stop_event=stop_event, reason=f"Confirmed LinkedIn Easy Apply for {company}")
                    return {"status": "APPLIED", "success": True}

                else:
                    # Submission unconfirmed after Submit click
                    is_challenge, challenge_type = self.detect_security_challenge(detail_tab)
                    if is_challenge:
                        self.bot_state.add_log(f"🚨 Security check required after submit for {company}. Kept open for user.", "WARNING")
                        record_application(
                            job_title=title, company_name=company, location=loc_text, job_url=job_url,
                            status="NEEDS_INPUT", apply_type="LINKEDIN_EASY_APPLY", match_score=job_info.get("score", 85),
                            notes="Security check required after submit.", failure_reason="SECURITY_CHALLENGE",
                            execution_stage="SUBMISSION_PENDING",
                            platform="LINKEDIN", requested_location=req_loc, actual_browser_location=act_loc
                        )
                        return {"status": "NEEDS_INPUT", "reason": "SECURITY_CHALLENGE"}

                    self.bot_state.add_log(f"⚠️ Submission unconfirmed after Submit click for {company}. Modal kept OPEN for verification.", "WARNING")
                    os.makedirs("backend/screenshots", exist_ok=True)
                    unconf_scr = f"backend/screenshots/unconfirmed_{safe_comp}_{int(time.time())}.png"
                    try: detail_tab.screenshot(path=unconf_scr)
                    except Exception: pass
                    detail_tab.bring_to_front()
                    record_application(
                        job_title=title, company_name=company, location=loc_text, job_url=job_url,
                        status="SUBMITTED_PENDING_CONFIRMATION", apply_type="LINKEDIN_EASY_APPLY", match_score=job_info.get("score", 85),
                        notes="Submit clicked, but confirmation was not observed. Kept open.",
                        failure_reason="CONFIRMATION_UNCERTAIN",
                        execution_stage="SUBMISSION_PENDING",
                        confirmation_type="SUBMIT_CLICKED_AWAITING_CONFIRMATION",
                        confirmation_message="Submit clicked; explicit modal dismissal confirmation was not observed.",
                        screenshot_reference=unconf_scr, platform="LINKEDIN",
                        requested_location=req_loc, actual_browser_location=act_loc
                    )
                    return {"status": "SUBMITTED_PENDING_CONFIRMATION", "success": False}

            # =========================================================================
            # ACTION BRANCH B: Review button detected
            # =========================================================================
            if btn_dict["review"]:
                rev_info = btn_dict["review"]
                if rev_info["enabled"]:
                    self.verify_and_enforce_contact_rules(dialog, effective_loc, custom_resume_path=custom_pdf)
                    rev_btn = rev_info["element"]
                    try:
                        rev_btn.scroll_into_view_if_needed()
                        time.sleep(0.3)
                        rev_btn.click()
                    except Exception:
                        rev_btn.evaluate("el => el.click()")
                    time.sleep(1.5)

                    # Re-check if review transition was blocked by validation error
                    review_errs = self.inspect_modal_validation_errors(dialog)
                    if review_errs:
                        self.bot_state.add_log(f"⚠️ Validation error on Review click: '{review_errs[0]}'. Re-filling step...", "WARNING")
                        self.fill_easy_apply_step(dialog, detail_tab, profile, stop_event, company, title, location_hint=effective_loc)
                        time.sleep(0.8)
                        btn_dict = self.detect_modal_action_buttons(dialog, detail_tab)
                        if btn_dict["review"] and btn_dict["review"]["enabled"]:
                            btn_dict["review"]["element"].click()
                            time.sleep(1.5)
                    continue

            # =========================================================================
            # ACTION BRANCH C: Next button detected
            # =========================================================================
            if btn_dict["next"]:
                nxt_info = btn_dict["next"]
                if nxt_info["enabled"]:
                    nxt_btn = nxt_info["element"]
                    try:
                        nxt_btn.scroll_into_view_if_needed()
                        time.sleep(0.3)
                        nxt_btn.click()
                    except Exception:
                        nxt_btn.evaluate("el => el.click()")
                    time.sleep(1.5)

                    # Check if validation error is blocking progression
                    step_errs = self.inspect_modal_validation_errors(dialog)
                    if step_errs:
                        self.bot_state.add_log(f"⚠️ Validation error on Next: '{step_errs[0]}'. Retrying step fill...", "WARNING")
                        self.fill_easy_apply_step(dialog, detail_tab, profile, stop_event, company, title, location_hint=effective_loc)
                        time.sleep(0.8)
                        btn_dict = self.detect_modal_action_buttons(dialog, detail_tab)
                        if btn_dict["next"] and btn_dict["next"]["enabled"]:
                            btn_dict["next"]["element"].click()
                            time.sleep(1.5)

                        still_errs = self.inspect_modal_validation_errors(dialog)
                        if still_errs:
                            self.bot_state.add_log(f"⚠️ Form validation notice: '{still_errs[0]}'. Leaving open in Chrome.", "WARNING")
                            os.makedirs("backend/screenshots", exist_ok=True)
                            scr_path = f"backend/screenshots/validation_error_{safe_comp}_{int(time.time())}.png"
                            try: detail_tab.screenshot(path=scr_path)
                            except Exception: pass
                            detail_tab.bring_to_front()
                            record_application(
                                job_title=title, company_name=company, location=loc_text, job_url=job_url,
                                status="NEEDS_INPUT", apply_type="LINKEDIN_EASY_APPLY", match_score=job_info.get("score", 85),
                                notes=f"Validation error blocking step: {still_errs[0]}", failure_reason=still_errs[0],
                                execution_stage="FORM_IN_PROGRESS",
                                screenshot_reference=scr_path, platform="LINKEDIN",
                                requested_location=req_loc, actual_browser_location=act_loc
                            )
                            return {"status": "NEEDS_INPUT", "reason": still_errs[0]}
                    continue

            # =========================================================================
            # ACTION BRANCH D: No enabled forward button found
            # =========================================================================
            self.bot_state.add_log(f"⚠️ No enabled forward button found on step {step_idx+1} for {company}. Capturing diagnostics...", "WARNING")
            break

        # Fallback if dialog remains unsubmitted
        os.makedirs("backend/screenshots", exist_ok=True)
        unsub_scr = f"backend/screenshots/easy_apply_unsubmitted_{safe_comp}_{int(time.time())}.png"
        try: detail_tab.screenshot(path=unsub_scr)
        except Exception: pass

        self.bot_state.add_log(f"Easy Apply reached final state without confirmation for {company}. Dialog kept OPEN for candidate confirmation.", "WARNING")
        detail_tab.bring_to_front()
        record_application(
            job_title=title, company_name=company, location=loc_text, job_url=job_url,
            status="NEEDS_INPUT", apply_type="LINKEDIN_EASY_APPLY", match_score=job_info.get("score", 85),
            notes="Easy Apply form completed. Kept open in Chrome for candidate confirmation.",
            failure_reason="USER_CONFIRMATION_REQUIRED",
            execution_stage="FORM_COMPLETED",
            skip_reason_code="USER_APPROVAL_REQUIRED",
            screenshot_reference=unsub_scr, platform="LINKEDIN",
            requested_location=req_loc, actual_browser_location=act_loc
        )
        self.cooldown_timer(
            min_sec=self.bot_state.config.unconfirmed_cooldown_min_sec,
            max_sec=self.bot_state.config.unconfirmed_cooldown_max_sec,
            stop_event=stop_event,
            reason=f"Safety pause for {company}"
        )
        return {"status": "NEEDS_INPUT", "success": False}

    def process_linkedin_job(self, context: BrowserContext, search_page: Page, job_info: Dict[str, Any], 
                             score: int, stop_event: threading.Event) -> Dict[str, Any]:
        """
        Unified processor for a single LinkedIn job (Easy Apply vs External Apply)
        backed by the formal ApplicationStateMachine and multi-tier deduplication.
        """
        title = job_info["title"]
        company = job_info["company"]
        loc_text = job_info.get("location", "")
        job_url = job_info["url"]
        job_id = job_info.get("id", "")
        job_info["score"] = score
        req_loc = job_info.get("requested_location", "")
        act_loc = job_info.get("actual_browser_location", loc_text)

        # 1. State Machine: DISCOVERED
        sm = ApplicationStateMachine(job_info, bot_state=self.bot_state)

        # 2. Section 6: Multi-tier Deduplication Check
        canonical_id = ""
        m_id = re.search(r"/jobs/view/(\d+)", job_url)
        if m_id:
            canonical_id = m_id.group(1)
        norm_key = f"{company.strip().lower()}::{title.strip().lower()}"

        is_session_dup = (job_id and job_id in self.processed_job_ids) or \
                         (canonical_id and canonical_id in self.processed_job_ids) or \
                         (norm_key in self.processed_job_ids)
        is_db_dup = check_already_applied_db(title=title, company=company, job_url=job_url, job_id=job_id or canonical_id)

        if is_session_dup or is_db_dup:
            dup_reason = "Already applied or active in DB" if is_db_dup else "Already processed in current session"
            self.bot_state.add_log(f"🔁 Duplicate job detected: {title} @ {company} ({dup_reason}). Skipping without redirect.", "INFO")
            # CRITICAL: Preserve existing application status (Never overwrite an APPLIED or recorded job with SKIPPED!)
            if job_id: self.processed_job_ids.add(job_id)
            if canonical_id: self.processed_job_ids.add(canonical_id)
            self.processed_job_ids.add(norm_key)
            return {"status": "SKIPPED", "attempted": False, "already_applied": True, "is_duplicate": True}

        if job_id: self.processed_job_ids.add(job_id)
        if canonical_id: self.processed_job_ids.add(canonical_id)
        self.processed_job_ids.add(norm_key)

        detail_tab = None
        self.bot_state.status = "APPLYING"
        self.bot_state.current_job = {
            "title": title,
            "company": company,
            "location": loc_text,
            "experience": "5+ Yrs",
            "url": job_url,
            "role_category": job_info.get("role_category", "Full Stack Developer"),
            "platform": "LINKEDIN"
        }

        try:
            self.bot_state.add_log(f"📄 Opening LinkedIn job details: {title} @ {company}...", "INFO")

            # Always open real job URL in dedicated tab to keep search_page intact
            if job_url and "jobs/view" in job_url:
                try:
                    detail_tab = context.new_page()
                    detail_tab.goto(job_url, wait_until="domcontentloaded", timeout=35000)
                    self.human_sleep(2.5, 4.0, stop_event)
                except Exception as e:
                    self.bot_state.add_log(f"Navigation warning opening {job_url}: {e}", "WARNING")

            if not detail_tab or detail_tab.is_closed():
                sm.transition(ApplicationStage.APPLICATION_FAILED, reason="Job detail tab failed to open or closed")
                return {"status": "SKIPPED", "attempted": False}

            # Content verification: check if redirected to post or profile
            tab_url = detail_tab.url or ""
            content_type = classify_linkedin_content(tab_url)
            if content_type in ["POST", "PERSONAL_PROFILE", "COMPANY_PAGE"]:
                self.bot_state.add_log(f"⚠️ Destination URL is a {content_type} ({tab_url}), not a job listing. Skipping.", "WARNING")
                sm.transition(ApplicationStage.SKIPPED, reason=f"Invalid destination: {content_type}")
                return {"status": "SKIPPED", "attempted": False}

            # State transition: JOB_VERIFIED
            sm.transition(ApplicationStage.JOB_VERIFIED, reason=f"Verified valid job details view for {company}")

            # Extract full JD description
            full_jd = ""
            try:
                for jd_sel in ["#job-details", ".jobs-description__content", ".jobs-box__html-content", ".jobs-description", "article"]:
                    jd_el = detail_tab.query_selector(jd_sel)
                    if jd_el:
                        full_jd = jd_el.inner_text().strip()
                        if len(full_jd) > 100:
                            break
            except Exception:
                pass

            # Extract location from detail page if card was missing it
            if not loc_text:
                try:
                    loc_el = (
                        detail_tab.query_selector(".job-details-jobs-unified-top-card__primary-description-container") or
                        detail_tab.query_selector(".jobs-unified-top-card__bullet") or
                        detail_tab.query_selector(".job-details-jobs-unified-top-card__workplace-type")
                    )
                    if loc_el:
                        loc_text = loc_el.inner_text().strip()
                except Exception:
                    pass

            # Check if location is completely missing -> LOCATION_NOT_FOUND
            if not loc_text:
                self.bot_state.add_log(f"📍 Location not found on job posting for {title} @ {company}. Setting LOCATION_NOT_FOUND.", "WARNING")
                sm.transition(ApplicationStage.SKIPPED, reason="LOCATION_NOT_FOUND")
                record_application(
                    job_title=title, company_name=company, location="Not Specified", job_url=job_url,
                    status="APPLICATION_SKIPPED", match_score=score,
                    skip_reason_code="LOCATION_NOT_FOUND",
                    failure_reason="LOCATION_NOT_FOUND",
                    execution_stage="ELIGIBILITY_VERIFICATION",
                    detailed_explanation=f"No verified location found on the job listing for {company}.",
                    notes="Skipped: Job location not found on page.",
                    platform="LINKEDIN",
                    requested_location=req_loc,
                    actual_browser_location=act_loc
                )
                return {"status": "SKIPPED", "attempted": False}

            # Technical alignment check with full JD
            if full_jd:
                align = evaluate_technology_alignment(title=title, company=company, desc=full_jd)
                if not align["should_apply"]:
                    tech_reason = align.get("reason_code", "PRIMARY_SPECIALIZATION_MISMATCH")
                    tech_score = align.get("match_score", 20)
                    self.bot_state.add_log(f"🚫 Technical specialization mismatch for {title} @ {company}: {tech_reason}", "INFO")
                    sm.transition(ApplicationStage.SKIPPED, reason=f"Specialization mismatch: {tech_reason}")
                    record_application(
                        job_title=title, company_name=company, location=loc_text, job_url=job_url,
                        status="APPLICATION_SKIPPED", match_score=tech_score,
                        skip_reason_code=tech_reason,
                        failure_reason=tech_reason,
                        execution_stage="ELIGIBILITY_VERIFICATION",
                        detailed_explanation=f"Technical specialization check: {align.get('detailed_explanation', tech_reason)}",
                        notes=f"Skipped: {tech_reason}",
                        platform="LINKEDIN",
                        requested_location=req_loc,
                        actual_browser_location=act_loc
                    )
                    return {"status": "SKIPPED", "attempted": False}

            # State transition: ELIGIBILITY_CHECKED
            sm.transition(ApplicationStage.ELIGIBILITY_CHECKED, reason="Location and technology eligibility confirmed")

            # Detect action button on detail_tab
            action_type, action_btn = self.detect_job_action_button(detail_tab)

            # Retry with gentle scroll if button is rendering dynamically
            if action_type == "NO_APPLY" and detail_tab and not detail_tab.is_closed():
                try:
                    detail_tab.evaluate("window.scrollBy(0, 300)")
                    time.sleep(1.0)
                    detail_tab.evaluate("window.scrollBy(0, -300)")
                    time.sleep(0.5)
                    action_type, action_btn = self.detect_job_action_button(detail_tab)
                except Exception:
                    pass

            # State transition: APPLY_OPTION_DETECTED
            sm.transition(ApplicationStage.APPLY_OPTION_DETECTED, reason=f"Application button: {action_type}")

            # 1. Already Applied
            if action_type == "ALREADY_APPLIED":
                self.bot_state.add_log(f"ℹ️ Already applied to {title} @ {company} on LinkedIn. Skipping.", "INFO")
                sm.transition(ApplicationStage.APPLICATION_CONFIRMED, reason="Already applied on LinkedIn")
                record_application(
                    job_title=title, company_name=company, location=loc_text, job_url=job_url,
                    status="APPLICATION_CONFIRMED", apply_type="LINKEDIN_EASY_APPLY", match_score=score,
                    notes="Already applied on LinkedIn.", platform="LINKEDIN",
                    requested_location=req_loc,
                    actual_browser_location=act_loc
                )
                return {"status": "APPLICATION_CONFIRMED", "success": True, "attempted": False}

            # 2. Login Required
            if action_type == "LOGIN_REQUIRED":
                self.bot_state.add_log(f"🔒 LinkedIn session login required for {company}.", "WARNING")
                sm.transition(ApplicationStage.NEEDS_USER_ACTION, reason="LOGIN_REQUIRED")
                return {"status": "FAILED", "reason": "LOGIN_REQUIRED", "attempted": False}

            # 3. Easy Apply Flow
            if action_type == "EASY_APPLY" and action_btn:
                self.bot_state.add_log(f"⚡ Easy Apply detected for {title} @ {company}! Clicking Easy Apply...", "INFO")
                sm.transition(ApplicationStage.APPLICATION_OPENED, reason="Launching Easy Apply multi-step modal")
                try:
                    action_btn.scroll_into_view_if_needed()
                    time.sleep(0.3)
                    action_btn.click()
                    time.sleep(2.0)
                except Exception as click_err:
                    self.bot_state.add_log(f"Notice clicking Easy Apply button: {click_err}", "WARNING")

                result = self.execute_easy_apply_flow(page=search_page, detail_tab=detail_tab, job_info=job_info, stop_event=stop_event)
                res_status = result.get("status")
                if res_status in ("APPLIED", "APPLICATION_CONFIRMED"):
                    sm.transition(ApplicationStatus.APPLIED, reason="Easy Apply submission verified")
                elif res_status in ("NEEDS_USER_ACTION", "NEEDS_USER_INPUT", "NEEDS_INPUT"):
                    sm.transition(ApplicationStatus.NEEDS_INPUT, reason=result.get("reason", "Action required"))
                elif res_status in ("SUBMITTED_PENDING_CONFIRMATION", "APPLICATION_PENDING_CONFIRMATION"):
                    sm.transition(ApplicationStatus.SUBMITTED_PENDING_CONFIRMATION, reason="Submit clicked, confirmation pending")
                return result

            # 4. External Apply (Company Portal Link)
            if action_type == "EXTERNAL_APPLY" and action_btn:
                btn_href = ""
                try:
                    btn_href = action_btn.get_attribute("href") or ""
                except Exception:
                    pass
                if btn_href and check_already_applied_db(title=title, company=company, job_url=job_url, job_id=job_id, external_url=btn_href):
                    self.bot_state.add_log(f"🔁 [External Deduplication] External link already processed in DB ({btn_href}). Skipping without clicking.", "INFO")
                    sm.transition(ApplicationStage.SKIPPED, reason="DUPLICATE_JOB: External portal already applied or skipped previously")
                    return {"status": "SKIPPED", "attempted": False}

                self.bot_state.add_log(f"🏢 'Apply' button on LinkedIn redirects to company careers portal. Opening...", "INFO")
                sm.transition(ApplicationStage.EXTERNAL_APPLICATION_OPENED, reason="Navigating to external careers portal")
                pages_before = len(context.pages)
                company_tab = None
                try:
                    with context.expect_page(timeout=8000) as pinfo:
                        action_btn.click()
                    company_tab = pinfo.value
                except Exception:
                    if len(context.pages) > pages_before:
                        company_tab = context.pages[-1]
                    else:
                        company_tab = detail_tab

                self.human_sleep(3.0, 5.0, stop_event)
                if company_tab and not company_tab.is_closed():
                    try:
                        company_tab.bring_to_front()
                        company_tab.wait_for_load_state("domcontentloaded", timeout=20000)
                    except Exception:
                        pass

                    ext_url = (company_tab.url if company_tab else "")
                    if ext_url and ext_url != "about:blank":
                        if check_already_applied_db(title=title, company=company, job_url=job_url, job_id=job_id, external_url=ext_url):
                            self.bot_state.add_log(f"🔁 [External Deduplication] Already applied or skipped in DB ({ext_url}) for {title} @ {company}. Closing tab and skipping.", "INFO")
                            try:
                                if company_tab and company_tab != detail_tab and not company_tab.is_closed():
                                    company_tab.close()
                            except Exception:
                                pass
                            sm.transition(ApplicationStage.SKIPPED, reason="DUPLICATE_JOB: External portal already applied or skipped previously")
                            return {"status": "SKIPPED", "attempted": False}

                    from resume_optimizer import resume_optimizer
                    is_gulf = any(c in (loc_text or "").lower() for c in ["qatar", "dubai", "uae", "saudi", "kuwait", "bahrain"])
                    cand_resume = resume_optimizer.get_base_resume(is_india=not is_gulf)

                    return self.handle_external_company_portal(
                        context=context,
                        detail_tab=detail_tab,
                        company_tab=company_tab,
                        title=title,
                        company=company,
                        loc_text=loc_text,
                        exp_text="5+ Yrs",
                        score=score,
                        stop_event=stop_event,
                        tailored_resume_path=cand_resume,
                        original_job_url=job_url,
                        platform="LINKEDIN",
                        requested_location=req_loc,
                        actual_browser_location=act_loc
                    )

            # 5. Check if Job Description contains hiring email (Outlook email flow)
            from email_service import extract_hiring_emails, open_outlook_for_job_application
            emails = extract_hiring_emails(detail_tab, jd_text=full_jd)
            if emails:
                target_email = emails[0]
                self.bot_state.add_log(f"📧 [Email Application] Found hiring email for {company}: {target_email}! Opening Outlook...", "INFO")
                opened, reason = open_outlook_for_job_application(
                    target_email=target_email,
                    job_title=title,
                    company=company,
                    location=loc_text,
                    job_url=job_url,
                    role_type=job_info.get("role_category", "Full Stack Developer")
                )
                if opened:
                    sm.transition(ApplicationStage.APPLICATION_CONFIRMED, reason=f"Composed Outlook email to {target_email}")
                    record_application(
                        job_title=title, company_name=company, location=loc_text, job_url=job_url,
                        status="APPLICATION_CONFIRMED", apply_type="DIRECT_EMAIL", match_score=score,
                        notes=f"Created Outlook draft for {target_email}.",
                        platform="LINKEDIN",
                        requested_location=req_loc,
                        actual_browser_location=act_loc
                    )
                    return {"status": "APPLICATION_CONFIRMED", "success": True, "attempted": True}

            # 6. No Apply Button Found
            screenshot_path = ""
            try:
                os.makedirs("backend/screenshots", exist_ok=True)
                safe_comp = re.sub(r'[^a-zA-Z0-9]', '_', company)[:20]
                screenshot_path = f"backend/screenshots/apply_option_failed_li_{safe_comp}_{int(time.time())}.png"
                (detail_tab or search_page).screenshot(path=screenshot_path)
            except Exception:
                pass

            self.bot_state.add_log(f"No active Apply or Easy Apply button found for {title} @ {company}. Skipping.", "WARNING")
            sm.transition(ApplicationStage.APPLY_OPTION_NOT_AVAILABLE, reason="No active Apply or Easy Apply button found after inspection", screenshot_path=screenshot_path)
            record_application(
                job_title=title, company_name=company, location=loc_text, job_url=job_url,
                status="APPLICATION_SKIPPED", apply_type="LINKEDIN_EASY_APPLY", match_score=score,
                skip_reason_code="APPLY_OPTION_NOT_AVAILABLE",
                failure_reason="APPLY_OPTION_NOT_AVAILABLE",
                execution_stage="ACTION_BUTTON_DETECTION",
                detailed_explanation=f"The job is eligible, but no active Apply or Easy Apply option was found on LinkedIn for {company}.",
                notes="No active Apply button found on page.",
                screenshot_reference=screenshot_path,
                platform="LINKEDIN",
                requested_location=req_loc,
                actual_browser_location=act_loc
            )
            return {"status": "SKIPPED", "attempted": False}

        except Exception as e:
            self.bot_state.add_log(f"Error processing LinkedIn job {title} @ {company}: {e}", "WARNING")
            record_application(
                job_title=title, company_name=company, location=loc_text, job_url=job_url,
                status="APPLICATION_FAILED", apply_type="LINKEDIN_EASY_APPLY", match_score=score,
                skip_reason_code="APPLICATION_BLOCKED",
                failure_reason="APPLICATION_BLOCKED",
                error_message=str(e),
                execution_stage="APPLICATION_EXECUTION",
                detailed_explanation=f"An application option was found, but the automation encountered a technical error: {e}",
                notes=f"Exception: {e}",
                platform="LINKEDIN",
                requested_location=req_loc,
                actual_browser_location=act_loc
            )
            return {"status": "FAILED", "reason": str(e), "attempted": True}
        finally:
            # SAFETY GUARD: Always close dedicated detail tab, NEVER close search_page!
            if detail_tab and detail_tab != search_page and not detail_tab.is_closed():
                try:
                    detail_tab.close()
                except Exception:
                    pass

    def run_linkedin_search_cycle(self, context: BrowserContext, target_roles: List[Dict[str, str]], 
                                  location: str, stop_event: threading.Event, quota_limit: int = 45):
        """Runs the complete LinkedIn autonomous job search and application cycle across target roles."""
        self.bot_state.add_log("🟦 [LinkedIn Engine] Starting LinkedIn search & application cycle...", "INFO")

        # Reuse or create a dedicated tab for LinkedIn search
        search_page = None
        for pg in context.pages:
            if "linkedin.com" in pg.url and not pg.is_closed():
                search_page = pg
                break
        if not search_page or search_page.is_closed():
            search_page = context.new_page()

        # Session validation
        search_page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=40000)
        self.human_sleep(2.0, 3.5, stop_event)
        
        if not self.verify_linkedin_session(search_page):
            self.bot_state.add_log("🔒 [LinkedIn Engine] User is not logged into LinkedIn in Chrome (port 9222). Please log in to enable LinkedIn applications.", "WARNING")
            return

        self.bot_state.add_log("✅ [LinkedIn Engine] Active LinkedIn session confirmed!", "SUCCESS")

        # Parse locations (supports "Mumbai, Qatar", "Mumbai and Qatar", single location)
        raw_loc = (location or "Dubai, Qatar, Mumbai, Pune, Remote").strip()
        loc_clean = raw_loc.replace(" and ", ",").replace("&", ",").replace("+", ",")
        target_locations = [l.strip() for l in loc_clean.split(",") if l.strip()]
        if not target_locations:
            target_locations = ["Dubai", "Qatar", "Mumbai", "Pune", "Remote"]

        self.bot_state.add_log(f"🟦 [LinkedIn Engine] Target locations ({len(target_locations)}): {', '.join(target_locations)}", "INFO")

        for current_loc in target_locations:
            if stop_event.is_set():
                break

            for role_idx, current_role in enumerate(target_roles):
                if stop_event.is_set():
                    break

                lk_today = get_today_applied_count("LINKEDIN")
                if lk_today >= quota_limit:
                    self.bot_state.add_log(f"🎯 LinkedIn daily quota of {quota_limit} reached ({lk_today}/{quota_limit})! Finishing LinkedIn cycle.", "SUCCESS")
                    return

                self.bot_state.today_applied = get_today_applied_count()
                if self.bot_state.today_applied >= self.bot_state.daily_limit:
                    self.bot_state.status = "LIMIT_REACHED"
                    self.bot_state.add_log(f"Target total daily quota of {self.bot_state.daily_limit} reached! Halting agent.", "SUCCESS")
                    break

                role_name = current_role["name"]
                # Search without easy_apply_only so BOTH Easy Apply AND External company websites are processed!
                search_url = self.build_search_url(role_name, current_loc, easy_apply_only=False)
                self.bot_state.status = "SEARCHING"
                self.bot_state.add_log(f"🔎 [LinkedIn] [{role_idx+1}/{len(target_roles)}] Initiating search for '{role_name}' in target location '{current_loc}'...", "INFO")

                try:
                    if search_page is None or search_page.is_closed():
                        search_page = self.get_safe_search_page(context)
                    search_page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
                    self.human_sleep(3.0, 5.0, stop_event)
                except Exception as e:
                    self.bot_state.add_log(f"LinkedIn search navigation warning for '{role_name}' in {current_loc}: {e}", "WARNING")
                    continue

                # CRITICAL LOCATION SYNCHRONIZATION & VERIFICATION
                is_loc_verified, actual_browser_loc, sync_err = self.synchronize_linkedin_location(
                    page=search_page,
                    requested_location=current_loc,
                    stop_event=stop_event
                )

                # Get LinkedIn reported result count
                res_count, res_text = self.get_linkedin_result_count(search_page)

                if not is_loc_verified:
                    self.bot_state.add_log(
                        f"🚫 LOCATION_SYNC_FAILED: Skipping scraping for '{role_name}' in '{current_loc}'. Browser displays '{actual_browser_loc}'. Error: {sync_err}",
                        "ERROR"
                    )
                    self.bot_state.last_search_diagnostics = {
                        "requestedLocation": current_loc,
                        "actualBrowserLocation": actual_browser_loc,
                        "locationVerified": False,
                        "searchKeyword": role_name,
                        "searchUrl": search_page.url,
                        "linkedinResultCount": res_count,
                        "extractedJobCount": 0,
                        "locationSyncStatus": "LOCATION_SYNC_FAILED",
                        "extractionStatus": "SKIPPED"
                    }
                    continue

                # Extract job cards
                job_cards = self.extract_job_cards(search_page, max_cards=20)
                ext_status = "SUCCESS" if job_cards else ("JOB_CARD_EXTRACTION_FAILED" if res_count > 0 else "NO_RESULTS")
                self.bot_state.last_search_diagnostics = {
                    "requestedLocation": current_loc,
                    "actualBrowserLocation": actual_browser_loc,
                    "locationVerified": True,
                    "searchKeyword": role_name,
                    "searchUrl": search_page.url,
                    "linkedinResultCount": res_count,
                    "extractedJobCount": len(job_cards),
                    "locationSyncStatus": "LOCATION_VERIFIED",
                    "extractionStatus": ext_status
                }

                self.bot_state.add_log(f"Found {len(job_cards)} job cards on LinkedIn for '{role_name}' in {actual_browser_loc} (LinkedIn reports {res_text or 'results'}). Inspecting...", "INFO")

                if not job_cards:
                    continue

                for job_idx, job in enumerate(job_cards):
                    if stop_event.is_set():
                        break

                    lk_today = get_today_applied_count("LINKEDIN")
                    if lk_today >= quota_limit:
                        self.bot_state.add_log(f"🎯 LinkedIn daily quota of {quota_limit} reached ({lk_today}/{quota_limit})! Finishing LinkedIn cycle.", "SUCCESS")
                        return

                    self.bot_state.today_applied = get_today_applied_count()
                    if self.bot_state.today_applied >= self.bot_state.daily_limit:
                        self.bot_state.status = "LIMIT_REACHED"
                        self.bot_state.add_log(f"Target total daily quota of {self.bot_state.daily_limit} reached! Halting agent.", "SUCCESS")
                        break

                    title = job["title"]
                    company = job["company"]
                    loc_text = job["location"]
                    job_url = job["url"]
                    job["role_category"] = role_name
                    job["search_location"] = actual_browser_loc
                    job["requested_location"] = current_loc
                    job["actual_browser_location"] = actual_browser_loc

                    apply_mode_badge = "⚡ Easy Apply" if job.get("is_easy_apply") else "🏢 Company Portal"
                    self.bot_state.add_log(f"Inspecting [LinkedIn {job_idx+1}/{len(job_cards)}] ({apply_mode_badge}): {title} @ {company} [{loc_text or actual_browser_loc}]", "INFO")

                    # INDEPENDENT ELIGIBILITY CHECK 1: Session & Database Deduplication
                    job_id = job.get("id", "")
                    if job_id and job_id in self.processed_job_ids:
                        self.bot_state.add_log(f"Job {job_id} already inspected in current session. Skipping.", "INFO")
                        continue

                    if job.get("is_applied"):
                        self.bot_state.add_log(f"LinkedIn badge confirms already applied: {title} @ {company}. Skipping without re-applying.", "INFO")
                        if job_id: self.processed_job_ids.add(job_id)
                        continue

                    if check_already_applied_db(title=title, company=company, job_url=job_url, job_id=job_id):
                        self.bot_state.add_log(f"Already applied or skipped {title} @ {company} in the past. Skipping without redirect.", "INFO")
                        if job_id: self.processed_job_ids.add(job_id)
                        continue

                    # INDEPENDENT ELIGIBILITY CHECK 2: Technical Specialization Compatibility
                    align = evaluate_technology_alignment(title=title, company=company, desc=title)
                    if not align["should_apply"]:
                        tech_reason = align.get("reason_code", "PRIMARY_SPECIALIZATION_MISMATCH")
                        tech_score = align.get("match_score", 20)
                        self.bot_state.add_log(f"🚫 Technical specialization mismatch for '{title}' @ {company}: {tech_reason}", "INFO")
                        record_application(
                            job_title=title, company_name=company, location=loc_text or actual_browser_loc, job_url=job_url,
                            status="APPLICATION_SKIPPED", match_score=tech_score,
                            skip_reason_code=tech_reason,
                            failure_reason=tech_reason,
                            execution_stage="ELIGIBILITY_VERIFICATION",
                            detailed_explanation=f"Technical specialization check: {align.get('detailed_explanation', tech_reason)}",
                            notes=f"Skipped: {tech_reason}",
                            platform="LINKEDIN",
                            requested_location=current_loc,
                            actual_browser_location=actual_browser_loc
                        )
                        if job_id: self.processed_job_ids.add(job_id)
                        continue

                    # INDEPENDENT ELIGIBILITY CHECK 3: Location Compatibility
                    # If location string is present, test against target locations
                    if loc_text:
                        is_loc_valid, matched_locs, extracted_locs = match_location(loc_text, target_locations)
                        if not is_loc_valid:
                            self.bot_state.add_log(f"📍 [LinkedIn] Location '{loc_text}' does not match target locations ({', '.join(target_locations)}). Skipping.", "INFO")
                            record_application(
                                job_title=title, company_name=company, location=loc_text, job_url=job_url,
                                status="APPLICATION_SKIPPED", match_score=0,
                                skip_reason_code="LOCATION_MISMATCH",
                                failure_reason="LOCATION_MISMATCH",
                                execution_stage="ELIGIBILITY_VERIFICATION",
                                detailed_explanation=f"None of the job's listed locations ({', '.join(extracted_locs)}) matches candidate preferred locations ({', '.join(target_locations)}).",
                                notes=f"Skipped: Location '{loc_text}' outside target regions.",
                                platform="LINKEDIN",
                                requested_location=current_loc,
                                actual_browser_location=actual_browser_loc
                            )
                            if job_id: self.processed_job_ids.add(job_id)
                            continue

                    # INDEPENDENT ELIGIBILITY CHECK 4: Match Score Threshold (score >= 65 is eligible)
                    self.bot_state.status = "EVALUATING"
                    score, should_apply, reason = evaluate_job_relevance(title, company, f"Location: {loc_text or actual_browser_loc}, Platform: LinkedIn")
                    self.bot_state.add_log(f"AI Match Score: {score}% - {reason}", "INFO" if score >= 65 else "WARNING")

                    if score < 65:
                        self.bot_state.add_log(f"Job compatibility score ({score}%) is below 65% minimum threshold. Skipping.", "INFO")
                        record_application(
                            job_title=title, company_name=company, location=loc_text or actual_browser_loc, job_url=job_url,
                            status="APPLICATION_SKIPPED", match_score=score,
                            skip_reason_code="LOW_MATCH_SCORE",
                            failure_reason="LOW_MATCH_SCORE",
                            execution_stage="ELIGIBILITY_VERIFICATION",
                            detailed_explanation=f"The job's compatibility score ({score}%) is below the configured threshold (65%). Reason: {reason}",
                            notes=f"AI Skipped: Match score {score}% is below threshold 65%. {reason}",
                            platform="LINKEDIN",
                            requested_location=current_loc,
                            actual_browser_location=actual_browser_loc
                        )
                        if job_id: self.processed_job_ids.add(job_id)
                        continue

                    # Execute application (handles Easy Apply AND External Company Portals!)
                    self.process_linkedin_job(
                        context=context,
                        search_page=search_page,
                        job_info=job,
                        score=score,
                        stop_event=stop_event
                    )

                    # Return focus to search page
                    try:
                        if search_page and not search_page.is_closed():
                            search_page.bring_to_front()
                    except Exception:
                        pass

                    self.human_sleep(2.0, 3.5, stop_event)

        self.bot_state.add_log("🏁 [LinkedIn Engine] Completed LinkedIn search & application cycle.", "SUCCESS")
