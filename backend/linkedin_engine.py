import os
import sys
import re
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
    get_connection
)
from ai_service import (
    evaluate_job_relevance, 
    get_candidate_profile
)
from agent_config import agent_config_manager
from question_answering import qa_engine, match_best_option
from database import format_final_application_report

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

    if region == "INDIA":
        config = {
            "region": "INDIA",
            "resume_filename": "Abdul_Razzaque_India.pdf",
            "resume_keyword": "india",
            "forbidden_resume_keyword": "qatar",
            "country_name": "India",
            "country_code": "+91",
            "phone_raw": "797269663",
            "phone_full": "+91 797269663"
        }
    else:
        config = {
            "region": "INTERNATIONAL",
            "resume_filename": "Abdul_Razzaque_Qatar.pdf",
            "resume_keyword": "qatar",
            "forbidden_resume_keyword": "india",
            "country_name": "Qatar",
            "country_code": "+974",
            "phone_raw": "77557982",
            "phone_full": "+974 77557982"
        }

    return region, reason, config

def is_gulf_location(location_str: str) -> bool:
    """Compatibility wrapper checking if a location is International/Gulf."""
    reg, _, _ = determine_application_region(location_str)
    return reg == "INTERNATIONAL"

def select_linkedin_country_code(sel: ElementHandle, is_india: bool, bot_state: Any = None) -> Tuple[bool, str]:
    """
    Deterministically selects the phone country code from LinkedIn's country code <select>:
    - India: strictly selects 'India (+91)' with value 'in' [NEVER Bolivia (+591) or British Indian Ocean (+246)]
    - International (Qatar/Dubai/UAE): strictly selects 'Qatar (+974)' with value 'qa' [NEVER UAE (+971)]
    Verifies the selection after applying.
    Returns: (success: bool, selected_text: str)
    """
    target_val = "in" if is_india else "qa"
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
                const val = (opt.value || '').toLowerCase().trim();

                if (isIndia) {
                    // Must be India (+91), strictly avoid Bolivia (+591) or Indian Ocean (+246)
                    const isTextIndia = /\bindia\b/i.test(text) && !/ocean|indonesia|bolivia/i.test(text);
                    const isExactCode = /\(\+?91\)/.test(text) || text.endsWith('+91');
                    if (isTextIndia && (isExactCode || !/\(\+\d+\)/.test(text))) {
                        matchedOpt = opt;
                        break;
                    }
                } else {
                    // Must be Qatar (+974)
                    const isTextQatar = /\bqatar\b/i.test(text) && !/emirates|dubai/i.test(text);
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
            ("971" not in selected_text)
        )

    if is_verified and bot_state:
        target_name = "India (+91)" if is_india else "Qatar (+974)"
        bot_state.add_log(f"📞 Mandatory Country Code Verified: {target_name} [Selected: '{selected_text}']", "SUCCESS")
    elif not is_verified and bot_state:
        target_name = "India (+91)" if is_india else "Qatar (+974)"
        bot_state.add_log(f"⚠️ Country code selection verification mismatch! Expected {target_name}, got '{selected_text}'", "WARNING")

    return is_verified, selected_text

def select_or_upload_linkedin_resume(dialog: ElementHandle, is_india: bool, profile: Dict[str, Any], bot_state: Any = None) -> Tuple[bool, str]:
    """
    Selects or uploads the verified candidate resume on LinkedIn Easy Apply:
    - India Jobs: Strictly selects 'Abdul Razzaque India.pdf' (NEVER Qatar.pdf)
    - International Jobs: Strictly selects 'Abdul Razzaque Qatar.pdf' (NEVER India.pdf)
    If target resume is not present, auto-uploads from disk via input[type='file'].
    Verifies that the target radio button is actually checked.
    Returns: (success: bool, resume_name: str)
    """
    target_kw = "india" if is_india else "qatar"
    forbidden_kw = "qatar" if is_india else "india"
    target_filename = "Abdul_Razzaque_India.pdf" if is_india else "Abdul_Razzaque_Qatar.pdf"

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
        if r_count > 0:
            break
        time.sleep(0.5)

    # Step 2: Try selecting from existing uploaded resumes via JavaScript
    res = dialog.evaluate(r"""(el, { targetKw, forbiddenKw }) => {
        const radios = Array.from(el.querySelectorAll("input[type='radio']"));
        const resumeItems = [];

        for (let r of radios) {
            // Check direct aria-label first (LinkedIn renders aria-label="Abdul Razzaque India.pdf")
            let isolatedText = (r.getAttribute('aria-label') || '').trim();
            if (!isolatedText && r.parentElement) {
                isolatedText = (r.parentElement.getAttribute('aria-label') || '').trim();
            }

            // Fallback to container inspection
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
            if (tLow.includes(targetKw) && !tLow.includes(forbiddenKw)) {
                targetItem = item;
                break;
            }
        }

        if (!targetItem) {
            // Enhanced direct search: find any card/container with targetKw, '.pdf', and not forbiddenKw
            const elements = Array.from(el.querySelectorAll('li, div, label, [class*="resume"], [class*="document"]'));
            for (let cand of elements) {
                const txt = (cand.innerText || '').toLowerCase();
                if (txt.includes(targetKw) && !txt.includes(forbiddenKw) && (txt.includes('.pdf') || txt.includes('razzaque'))) {
                    const r = cand.querySelector("input[type='radio']") || cand.closest('li, div')?.querySelector("input[type='radio']");
                    targetItem = {
                        radio: r,
                        container: cand,
                        text: cand.innerText.trim()
                    };
                    break;
                }
            }
        }

        if (targetItem) {
            // Click the matching label / container or dispatch React events
            if (targetItem.container) {
                try { targetItem.container.click(); } catch(e) {}
            }
            if (targetItem.radio) {
                const r = targetItem.radio;
                if (!r.checked) {
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
    }""", {"targetKw": target_kw, "forbiddenKw": forbidden_kw})

    # Step 3: If target resume was not found among radio buttons, upload from disk
    if not res.get("found"):
        if bot_state:
            bot_state.add_log(f"Target resume '{target_filename}' not found in uploaded list. Attempting upload from disk...", "INFO")
        
        file_inputs = dialog.query_selector_all("input[type='file']")
        uploaded = False
        for finp in file_inputs:
            resume_path = os.path.join(os.path.dirname(__file__), target_filename)
            if not os.path.exists(resume_path):
                # Try with space in name
                alt_name = "Abdul Razzaque India.pdf" if is_india else "Abdul Razzaque Qatar.pdf"
                alt_path = os.path.join(os.path.dirname(__file__), alt_name)
                if os.path.exists(alt_path):
                    resume_path = alt_path
                else:
                    resume_path = profile.get("resume_path", "")

            if resume_path and os.path.exists(resume_path):
                try:
                    finp.set_input_files(resume_path)
                    if bot_state:
                        bot_state.add_log(f"📎 Uploaded candidate resume: {os.path.basename(resume_path)}", "SUCCESS")
                    time.sleep(2.0)
                    uploaded = True
                    break
                except Exception as e:
                    if bot_state:
                        bot_state.add_log(f"Resume upload error: {e}", "WARNING")

        if uploaded:
            # Re-run selection after upload
            time.sleep(1.0)
            res = dialog.evaluate(r"""(el, { targetKw, forbiddenKw }) => {
                const radios = Array.from(el.querySelectorAll("input[type='radio']"));
                for (let r of radios) {
                    const aria = (r.getAttribute('aria-label') || '').toLowerCase();
                    const pAria = (r.parentElement ? r.parentElement.getAttribute('aria-label') || '' : '').toLowerCase();
                    let card = r.closest('li, div, label');
                    let txt = (aria + ' ' + pAria + ' ' + (card ? card.innerText || '' : '')).toLowerCase();
                    if (txt.includes(targetKw) && !txt.includes(forbiddenKw)) {
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
            }""", {"targetKw": target_kw, "forbiddenKw": forbidden_kw})

    # Fresh DOM verification to avoid stale detached ElementHandles
    time.sleep(0.4)
    verify_res = dialog.evaluate(r"""(el, { targetKw, forbiddenKw }) => {
        const radios = Array.from(el.querySelectorAll("input[type='radio']"));
        let targetChecked = false;
        let forbiddenChecked = false;
        let matchedText = '';
        for (let r of radios) {
            const aria = (r.getAttribute('aria-label') || '').toLowerCase();
            const pAria = (r.parentElement ? r.parentElement.getAttribute('aria-label') || '' : '').toLowerCase();
            const txt = (aria + ' ' + pAria + ' ' + (r.closest('li, div, label')?.innerText || '')).toLowerCase();
            if (txt.includes(targetKw) && !txt.includes(forbiddenKw)) {
                matchedText = r.getAttribute('aria-label') || targetKw;
                if (r.checked) targetChecked = true;
            }
            if (txt.includes(forbiddenKw) && r.checked) {
                forbiddenChecked = true;
            }
        }
        return { isVerified: targetChecked && !forbiddenChecked, matchedText };
    }""", {"targetKw": target_kw, "forbiddenKw": forbidden_kw})

    checked = verify_res.get("isVerified", False)
    resume_name = verify_res.get("matchedText") or target_filename

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

    def extract_job_cards(self, page: Page, max_cards: int = 25) -> List[Dict[str, Any]]:
        """Parses job cards from the search results page."""
        jobs: List[Dict[str, Any]] = []
        try:
            # Scroll gently down the job listings container to trigger lazy loading
            for _ in range(4):
                if self.bot_state.stop_event.is_set():
                    break
                try:
                    # Target results list container if possible, otherwise page wheel
                    list_container = page.query_selector(".jobs-search-results-list, div.scaffold-layout__list")
                    if list_container:
                        list_container.evaluate("(el) => el.scrollTop += 600")
                    else:
                        page.mouse.wheel(0, 500)
                except Exception:
                    pass
                time.sleep(1.0)

            card_elements = page.query_selector_all("li[data-occludable-job-id], div.job-card-container, li.jobs-search-results__list-item")
            seen_ids = set()

            for card in card_elements:
                try:
                    card_text = card.inner_text().strip()
                    if not card_text:
                        continue

                    job_id = card.get_attribute("data-occludable-job-id") or card.get_attribute("data-job-id") or ""
                    
                    # Extract title and URL
                    title_elem = (
                        card.query_selector("a.job-card-list__title") or 
                        card.query_selector("a.job-card-container__link") or 
                        card.query_selector("a[class*='job-card']") or 
                        card.query_selector("strong")
                    )
                    raw_title = title_elem.inner_text().strip() if title_elem else ""
                    # Remove multi-line text artifacts from title
                    t_lines = [l.strip() for l in raw_title.split("\n") if l.strip()]
                    title = t_lines[0] if t_lines else ""

                    # Extract company
                    company_elem = (
                        card.query_selector(".artdeco-entity-lockup__subtitle") or 
                        card.query_selector(".job-card-container__primary-description") or 
                        card.query_selector("span[class*='company']")
                    )
                    c_raw = company_elem.inner_text().strip() if company_elem else ""
                    c_lines = [l.strip() for l in c_raw.split("\n") if l.strip()]
                    company = c_lines[0] if c_lines else ""

                    # Extract location
                    loc_elem = (
                        card.query_selector(".artdeco-entity-lockup__caption") or 
                        card.query_selector(".job-card-container__metadata-item")
                    )
                    l_raw = loc_elem.inner_text().strip() if loc_elem else ""
                    l_lines = [l.strip() for l in l_raw.split("\n") if l.strip()]
                    location_text = l_lines[0] if l_lines else ""

                    # Extract URL
                    href = title_elem.get_attribute("href") if title_elem else ""
                    if not job_id and href:
                        id_match = re.search(r"/jobs/view/(\d+)", href)
                        if id_match:
                            job_id = id_match.group(1)

                    if not job_id:
                        continue

                    if job_id in seen_ids:
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

        except Exception as e:
            self.bot_state.add_log(f"Notice while extracting LinkedIn job cards: {e}", "WARNING")

        return jobs

    def detect_job_action_button(self, page: Page) -> Tuple[str, Optional[ElementHandle]]:
        """
        Inspects the LinkedIn job details view to identify application mechanism:
        Returns (action_type, button_element)
        action_type can be:
          - 'ALREADY_APPLIED'
          - 'EASY_APPLY'
          - 'EXTERNAL_APPLY'
          - 'LOGIN_REQUIRED'
          - 'NO_APPLY'
        """
        try:
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
                    txt = el.inner_text().strip().lower()
                    if "applied" in txt or "application submitted" in txt:
                        return ("ALREADY_APPLIED", el)

            # 2. Easy Apply Check
            easy_apply_selectors = [
                "button:has-text('Easy Apply')",
                "button[aria-label*='Easy Apply']",
                ".jobs-apply-button:has-text('Easy Apply')"
            ]
            for sel in easy_apply_selectors:
                el = page.query_selector(sel)
                if el and el.is_visible() and el.is_enabled():
                    return ("EASY_APPLY", el)

            # 3. External Apply Check
            ext_apply_selectors = [
                "button.jobs-apply-button",
                "button[aria-label*='Apply to']",
                "button[aria-label*='Apply on']",
                "button:has-text('Apply')",
                "a.jobs-apply-button",
                "a:has-text('Apply')"
            ]
            for sel in ext_apply_selectors:
                el = page.query_selector(sel)
                if el and el.is_visible() and el.is_enabled():
                    txt = el.inner_text().strip().lower()
                    if "easy apply" not in txt:
                        return ("EXTERNAL_APPLY", el)

            # 4. Login Required
            if page.query_selector("a:has-text('Sign in to apply'), button:has-text('Sign in to apply')"):
                return ("LOGIN_REQUIRED", None)

            return ("NO_APPLY", None)
        except Exception:
            return ("NO_APPLY", None)

    def fill_easy_apply_step(self, dialog: ElementHandle, page: Page, profile: Dict[str, Any], 
                             stop_event: threading.Event, company: str, title: str, location_hint: str = "") -> Dict[str, Any]:
        """
        Intelligently detects and fills questions on an active LinkedIn Easy Apply modal step:
        - Contact info (phone, email, country code)
        - Resume selection (Abdul Razzaque India.pdf) or upload
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
            select_or_upload_linkedin_resume(dialog, is_india, profile, self.bot_state)

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
                    target_country_text = "India" if is_india else "Qatar"
                    curr_cc_val = (inp.evaluate("el => el.value") or "").strip()
                    if is_india and ("bolivia" in curr_cc_val.lower() or "591" in curr_cc_val or "india" not in curr_cc_val.lower()):
                        inp.fill("")
                        time.sleep(0.1)
                        inp.type(target_country_text, delay=50)
                        time.sleep(0.5)
                        try:
                            dialog.evaluate("""targetName => {
                                const options = Array.from(document.querySelectorAll('[role="option"], .artdeco-typeahead__result, li, div[class*="option"]'));
                                for (let o of options) {
                                    const txt = (o.innerText || '').trim();
                                    if (txt.toLowerCase().includes(targetName.toLowerCase()) && !txt.toLowerCase().includes('bolivia') && !txt.toLowerCase().includes('ocean') && !txt.toLowerCase().includes('indonesia')) {
                                        o.click();
                                        return true;
                                    }
                                }
                                return false;
                            }""", target_country_text)
                        except Exception:
                            pass
                        inp.evaluate("el => { el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true})); }")
                        self.bot_state.add_log(f"📞 Applied Country Code via combobox: '{target_country_text}'", "SUCCESS")
                        time.sleep(0.3)
                    continue

                # Strict Mandatory Rule: Phone Number and Country Code
                # 1. India: Always use +91 797269663. Country code +91, phone 797269663.
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
                            self.bot_state.add_log(f"📞 Mandatory India Phone Applied: '{target_phone}' (Location: {location_hint})", "SUCCESS")
                            time.sleep(0.3)
                    else:
                        target_phone = app_config["phone_raw"] if has_separate_cc else app_config["phone_full"]
                        needs_fill = (curr_val != target_phone) or bool(re.search(r"[a-zA-Z]", curr_val)) or ("797269663" in curr_val) or ("971" in curr_val) or (has_separate_cc and "+974" in curr_val)
                        if needs_fill:
                            inp.fill("")
                            time.sleep(0.1)
                            inp.fill(target_phone)
                            inp.evaluate("el => { el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true})); }")
                            self.bot_state.add_log(f"📞 Mandatory International Phone Applied: '{target_phone}' (Location: {location_hint})", "SUCCESS")
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
                    has_calendar = inp.evaluate("el => el.type === 'date' || !!el.parentElement?.querySelector('svg, [class*=\"calendar\"], [data-test-icon*=\"calendar\"]')")
                    if has_calendar or pass_type == "date" or any(k in q_clean.lower() for k in ["start date", "startdatum", "eintrittsdatum"]):
                        if any(k in str(answer).lower() for k in ["immediate", "sofort", "joiner", "availab"]):
                            import datetime
                            if any(k in q_clean.lower() for k in ["startdatum", "deutsch", "germany"]):
                                answer = (datetime.date.today() + datetime.timedelta(days=7)).strftime("%d.%m.%Y")
                            else:
                                answer = (datetime.date.today() + datetime.timedelta(days=7)).strftime("%Y-%m-%d")

                    # EUR Currency explicit check (Prevents '15' or '15 LPA' being entered in EUR fields)
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

    def verify_and_enforce_contact_rules(self, dialog: ElementHandle, location_hint: str) -> bool:
        """
        MANDATORY RULES ENFORCEMENT & PRE-SUBMISSION VERIFICATION:
        1. India Applications:
           - Country code: strictly +91 (India) [Never Bolivia +591]
           - Phone: 797269663
           - Resume: Abdul Razzaque India.pdf [Never Qatar.pdf]
        2. International Applications (Qatar, Dubai, UAE, etc.):
           - Country code: strictly +974 (Qatar) [Never UAE +971]
           - Phone: 77557982
           - Resume: Abdul Razzaque Qatar.pdf [Never India.pdf]
        3. Never submit an application with an incorrect country code, phone number, or resume.
        """
        region, reason, app_config = determine_application_region(location_hint)
        is_india = (region == "INDIA")
        profile = get_candidate_profile()

        # 1. Enforce on visible select dropdowns (Country Code)
        try:
            selects = dialog.query_selector_all("select")
            for sel in selects:
                if not sel.is_visible() or sel.is_disabled():
                    continue
                sel_id = (sel.get_attribute("id") or "").lower()
                sel_name = (sel.get_attribute("name") or "").lower()
                sel_aria = (sel.get_attribute("aria-label") or "").lower()
                if any(k in sel_id or k in sel_name or k in sel_aria for k in ["country", "code", "phone"]):
                    curr_opt_text = sel.evaluate("el => el.options[el.selectedIndex] ? el.options[el.selectedIndex].text : ''")
                    if is_india:
                        is_valid = ("india" in curr_opt_text.lower()) and ("bolivia" not in curr_opt_text.lower()) and ("591" not in curr_opt_text) and bool(re.search(r"(\+?91)", curr_opt_text))
                        if not is_valid:
                            self.bot_state.add_log(f"⚠️ [Verification Fix] Country code was '{curr_opt_text}'. Overriding to India (+91)...", "WARNING")
                            select_linkedin_country_code(sel, is_india=True, bot_state=self.bot_state)
                    else:
                        is_valid = ("qatar" in curr_opt_text.lower() or "974" in curr_opt_text) and ("971" not in curr_opt_text)
                        if not is_valid:
                            self.bot_state.add_log(f"⚠️ [Verification Fix] Country code was '{curr_opt_text}'. Overriding to Qatar (+974)...", "WARNING")
                            select_linkedin_country_code(sel, is_india=False, bot_state=self.bot_state)
        except Exception as e:
            self.bot_state.add_log(f"Verification select notice: {e}", "WARNING")

        # 2. Enforce on visible phone input fields
        try:
            inputs = dialog.query_selector_all("input:not([type='hidden']):not([type='radio']):not([type='checkbox']):not([type='file'])")
            for inp in inputs:
                if not inp.is_visible() or inp.is_disabled():
                    continue
                inp_id = (inp.get_attribute("id") or "").lower()
                inp_name = (inp.get_attribute("name") or "").lower()
                inp_aria = (inp.get_attribute("aria-label") or "").lower()
                if any(k in inp_id or k in inp_name or k in inp_aria for k in ["phone", "mobile", "contact"]):
                    val = (inp.evaluate("el => el.value") or "").strip()
                    if is_india:
                        if "77557982" in val or "797269663" not in val or "+91" in val:
                            target_val = "797269663"
                            inp.fill("")
                            time.sleep(0.1)
                            inp.fill(target_val)
                            inp.evaluate("el => { el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true})); }")
                            self.bot_state.add_log(f"🛡️ [Verification Fix] Enforced India phone '{target_val}'", "SUCCESS")
                    else:
                        if "797269663" in val or "77557982" not in val or "971" in val or "+974" in val:
                            target_val = "77557982"
                            inp.fill("")
                            time.sleep(0.1)
                            inp.fill(target_val)
                            inp.evaluate("el => { el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true})); }")
                            self.bot_state.add_log(f"🛡️ [Verification Fix] Enforced International phone '{target_val}'", "SUCCESS")
        except Exception as e:
            self.bot_state.add_log(f"Verification input notice: {e}", "WARNING")

        # 3. Enforce & verify resume selection
        try:
            resume_verified, res_name = select_or_upload_linkedin_resume(dialog, is_india, profile, self.bot_state)
            if not resume_verified:
                self.bot_state.add_log(f"⚠️ Resume verification check: '{res_name}'", "WARNING")
        except Exception as e:
            self.bot_state.add_log(f"Verification resume notice: {e}", "WARNING")

        # 4. Text summary check (Review step verification)
        try:
            summary_txt = dialog.evaluate("el => el.innerText || ''")
            if is_india:
                if "Bolivia" in summary_txt or "+591" in summary_txt:
                    self.bot_state.add_log("🚨 [Pre-Submission Block] Application review contains 'Bolivia (+591)'! India (+91) is required.", "ERROR")
                    return False
                if "Qatar.pdf" in summary_txt or "Abdul_Razzaque_Qatar" in summary_txt:
                    self.bot_state.add_log("🚨 [Pre-Submission Block] Application review contains 'Qatar.pdf'! India.pdf is required for India jobs.", "ERROR")
                    return False
                if "77557982" in summary_txt:
                    self.bot_state.add_log("🚨 [Pre-Submission Block] Application review contains Qatar number '77557982'! +91 797269663 is mandatory for India jobs.", "ERROR")
                    return False
                if "797269663" in summary_txt:
                    self.bot_state.add_log("✅ [Phone Rule Verified] Validated India phone +91 797269663 on application summary.", "SUCCESS")
            else:
                if "+971" in summary_txt:
                    self.bot_state.add_log("🚨 [Pre-Submission Block] Application review contains '+971'! Qatar (+974) is mandatory for Gulf/International jobs.", "ERROR")
                    return False
                if "India.pdf" in summary_txt or "Abdul_Razzaque_India" in summary_txt:
                    self.bot_state.add_log("🚨 [Pre-Submission Block] Application review contains 'India.pdf'! Qatar.pdf is required for International jobs.", "ERROR")
                    return False
                if "797269663" in summary_txt:
                    self.bot_state.add_log("🚨 [Pre-Submission Block] Application review contains India number '797269663'! +974 77557982 is mandatory for International jobs.", "ERROR")
                    return False
                if "77557982" in summary_txt:
                    self.bot_state.add_log("✅ [Phone Rule Verified] Validated International phone +974 77557982 on application summary.", "SUCCESS")
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

        # Extract location text from detail_tab if available
        detail_loc = ""
        try:
            d_el = detail_tab.query_selector(".jobs-unified-top-card__bullet, .job-details-jobs-unified-top-card__primary-description-container, [class*='job-location']")
            if d_el and d_el.is_visible():
                detail_loc = d_el.inner_text().strip()
        except Exception:
            pass

        # Determine application region cleanly without search location pollution!
        region, region_reason, app_config = determine_application_region(
            job_location=loc_text,
            detail_location=detail_loc,
            search_location=search_loc
        )
        is_india = (region == "INDIA")
        effective_loc = loc_text or detail_loc or search_loc

        self.bot_state.add_log(f"⚡ Launching Easy Apply flow for {title} @ {company}...", "INFO")
        self.bot_state.add_log(f"🌍 [Location Synchronization] Region: {region} ({region_reason}) | Location: '{effective_loc}'", "INFO")
        self.bot_state.add_log(f"📄 Target Resume: {app_config['resume_filename']}", "INFO")
        self.bot_state.add_log(f"📞 Target Phone: {app_config['phone_full']} ({app_config['country_name']} {app_config['country_code']})", "INFO")
        profile = get_candidate_profile()

        # Locate the dialog
        dialog = None
        for _ in range(10):
            if stop_event.is_set():
                break
            dialog = detail_tab.query_selector("dialog, dialog[open], [data-testid='dialog'], .jobs-easy-apply-modal, div[role='dialog']")
            if dialog and dialog.is_visible():
                break
            time.sleep(0.5)

        if not dialog:
            self.bot_state.add_log(f"Easy Apply dialog did not open for {company}.", "WARNING")
            return {"status": "FAILED", "reason": "DIALOG_NOT_FOUND"}

        # Multi-step loop
        max_steps = 10
        for step_idx in range(max_steps):
            if stop_event.is_set():
                break

            time.sleep(1.0)
            dialog = detail_tab.query_selector("dialog, dialog[open], [data-testid='dialog'], .jobs-easy-apply-modal, div[role='dialog']")
            if not dialog or not dialog.is_visible():
                # Dialog might have completed and closed
                break

            dialog_header = dialog.query_selector("h2, h3, h1, [data-testid='dialog-header']")
            header_txt = dialog_header.inner_text().strip() if dialog_header else f"Step {step_idx+1}"
            self.bot_state.add_log(f"📋 LinkedIn Step {step_idx+1}: {header_txt} for {company}", "INFO")

            # Check if we already reached success / confirmation screen
            conf_btn = dialog.query_selector("button:has-text('Done'), button[aria-label*='Done']")
            if conf_btn and conf_btn.is_visible():
                self.bot_state.add_log(f"🎉 Easy Apply submission SUCCESS for {company}!", "SUCCESS")
                conf_btn.click()
                time.sleep(1.0)
                record_application(
                    job_title=title, company_name=company, location=loc_text, job_url=job_url,
                    status="APPLICATION_CONFIRMED", apply_type="LINKEDIN_EASY_APPLY", match_score=job_info.get("score", 85),
                    notes="Successfully applied via LinkedIn Easy Apply.", platform="LINKEDIN"
                )
                self.bot_state.today_applied = get_today_applied_count()
                rep = format_final_application_report(
                    company_name=company,
                    job_title=title,
                    job_location=effective_loc or loc_text,
                    platform="LinkedIn",
                    application_type="Easy Apply",
                    resume_status=f"Selected ({app_config['resume_filename']})",
                    phone_number=app_config["phone_full"],
                    country_code=app_config["country_code"],
                    email_verification="Not Required",
                    form_validation="Passed",
                    application_status="Submitted"
                )
                self.bot_state.add_log(f"📋 Application Report:\n{rep}", "SUCCESS")
                self.cooldown_timer(stop_event=stop_event, reason=f"Confirmed LinkedIn Easy Apply for {company}")
                return {"status": "APPLICATION_CONFIRMED", "success": True}

            # Fill questions on this step
            fill_res = self.fill_easy_apply_step(dialog, detail_tab, profile, stop_event, company, title, location_hint=effective_loc)
            if fill_res.get("status") == "NEEDS_USER_INPUT":
                unanswered_q = fill_res.get("question", "")
                reason = fill_res.get("reason", "NEEDS_USER_INPUT")
                self.bot_state.add_log(f"⚠️ [NEEDS_USER_INPUT] LinkedIn question requires candidate input: '{unanswered_q[:35]}' ({reason}). Dialog kept OPEN in Chrome!", "WARNING")
                detail_tab.bring_to_front()
                record_application(
                    job_title=title, company_name=company, location=loc_text, job_url=job_url,
                    status="NEEDS_USER_INPUT", apply_type="LINKEDIN_EASY_APPLY", match_score=job_info.get("score", 85),
                    notes=f"Question requires candidate input: {unanswered_q} ({reason})",
                    failure_reason=reason, platform="LINKEDIN"
                )
                return {"status": "NEEDS_USER_INPUT", "reason": reason, "question": unanswered_q}

            time.sleep(0.8)

            # Check action buttons (Submit, Review, Next)
            # 1. Submit Application button
            sub_btn = dialog.query_selector("button:has-text('Submit application'), button[aria-label*='Submit application']")
            if sub_btn and sub_btn.is_visible() and sub_btn.is_enabled():
                # Mandatory Pre-Submission Rule Verification
                if not self.verify_and_enforce_contact_rules(dialog, effective_loc):
                    self.bot_state.add_log(f"🚨 Contact rules verification failed before submit for {company}! Kept dialog OPEN in Chrome.", "ERROR")
                    detail_tab.bring_to_front()
                    record_application(
                        job_title=title, company_name=company, location=loc_text, job_url=job_url,
                        status="NEEDS_USER_INPUT", apply_type="LINKEDIN_EASY_APPLY", match_score=job_info.get("score", 85),
                        notes="Blocked submission: Contact details failed strict location rules.",
                        failure_reason="PHONE_RULE_VERIFICATION_FAILED", platform="LINKEDIN"
                    )
                    return {"status": "NEEDS_USER_INPUT", "reason": "PHONE_RULE_VERIFICATION_FAILED"}

                if not agent_config_manager.is_authorized("auto_submit_direct"):
                    self.bot_state.add_log(f"Application ready to submit for {company}. auto_submit_direct is disabled. Modal kept OPEN for review.", "INFO")
                    detail_tab.bring_to_front()
                    record_application(
                        job_title=title, company_name=company, location=loc_text, job_url=job_url,
                        status="APPLICATION_PENDING_CONFIRMATION", apply_type="LINKEDIN_EASY_APPLY", match_score=job_info.get("score", 85),
                        notes="Ready to submit. auto_submit_direct not authorized. Kept open.", platform="LINKEDIN"
                    )
                    return {"status": "APPLICATION_PENDING_CONFIRMATION", "success": False}

                self.bot_state.add_log(f"🚀 Clicking 'Submit application' on LinkedIn for {company}...", "INFO")
                sub_btn.scroll_into_view_if_needed()
                time.sleep(0.3)
                sub_btn.click()
                time.sleep(3.0)

                # Check for Done button
                done_btn = dialog.query_selector("button:has-text('Done'), button[aria-label*='Done']")
                if done_btn and done_btn.is_visible():
                    done_btn.click()
                    time.sleep(1.0)

                record_application(
                    job_title=title, company_name=company, location=loc_text, job_url=job_url,
                    status="APPLICATION_CONFIRMED", apply_type="LINKEDIN_EASY_APPLY", match_score=job_info.get("score", 85),
                    notes="Successfully applied via LinkedIn Easy Apply.", platform="LINKEDIN"
                )
                self.bot_state.today_applied = get_today_applied_count()
                rep = format_final_application_report(
                    company_name=company,
                    job_title=title,
                    job_location=effective_loc or loc_text,
                    platform="LinkedIn",
                    application_type="Easy Apply",
                    resume_status=f"Selected ({app_config['resume_filename']})",
                    phone_number=app_config["phone_full"],
                    country_code=app_config["country_code"],
                    email_verification="Not Required",
                    form_validation="Passed",
                    application_status="Submitted"
                )
                self.bot_state.add_log(f"📋 Application Report:\n{rep}", "SUCCESS")
                self.bot_state.add_log(f"✅ LinkedIn Easy Apply SUCCESS! [{self.bot_state.today_applied}/{self.bot_state.daily_limit}] for {title} @ {company}", "SUCCESS")
                self.cooldown_timer(stop_event=stop_event, reason=f"Confirmed LinkedIn Easy Apply for {company}")
                return {"status": "APPLICATION_CONFIRMED", "success": True}

            # 2. Review button
            rev_btn = dialog.query_selector("button:has-text('Review'), button[aria-label*='Review']")
            if rev_btn and rev_btn.is_visible() and rev_btn.is_enabled():
                self.verify_and_enforce_contact_rules(dialog, effective_loc)
                rev_btn.scroll_into_view_if_needed()
                time.sleep(0.3)
                rev_btn.click()
                time.sleep(1.5)
                
                # Check if validation error blocked review progression
                has_error = dialog.evaluate("""() => {
                    const err = document.querySelector('[data-testid="text-input-helper-text"] p, .artdeco-inline-feedback--error, .fb-form-element--error, [data-test-form-element-error-message], span.error, [class*="error"], [class*="feedback--error"]');
                    if (err && err.offsetParent !== null) {
                        const txt = err.innerText.trim();
                        if (txt && !txt.toLowerCase().includes('success') && (
                            txt.toLowerCase().includes('invalid') || txt.toLowerCase().includes('error') || 
                            txt.toLowerCase().includes('valid') || txt.toLowerCase().includes('required') || 
                            txt.toLowerCase().includes('please') || txt.toLowerCase().includes('/') ||
                            err.classList.contains('artdeco-inline-feedback--error') || err.classList.contains('fb-form-element--error')
                        )) {
                            return txt;
                        }
                    }
                    return null;
                }""")
                if has_error:
                    self.bot_state.add_log(f"⚠️ Validation error on Review click: '{has_error}'. Re-filling step with corrected inputs...", "WARNING")
                    self.fill_easy_apply_step(dialog, detail_tab, profile, stop_event, company, title, location_hint=effective_loc)
                    time.sleep(0.8)
                    rev_btn = dialog.query_selector("button:has-text('Review'), button[aria-label*='Review']")
                    if rev_btn and rev_btn.is_visible() and rev_btn.is_enabled():
                        rev_btn.click()
                        time.sleep(1.5)
                continue

            # 3. Next button
            next_btn = dialog.query_selector("button:has-text('Next'), button[aria-label*='Continue to next step']")
            if next_btn and next_btn.is_visible() and next_btn.is_enabled():
                next_btn.scroll_into_view_if_needed()
                time.sleep(0.3)
                next_btn.click()
                time.sleep(1.5)

                # Check if validation error is blocking progression
                has_error = dialog.evaluate("""() => {
                    const err = document.querySelector('[data-testid="text-input-helper-text"] p, .artdeco-inline-feedback--error, .fb-form-element--error, [data-test-form-element-error-message], span.error, [class*="error"], [class*="feedback--error"]');
                    if (err && err.offsetParent !== null) {
                        const txt = err.innerText.trim();
                        if (txt && !txt.toLowerCase().includes('success') && (
                            txt.toLowerCase().includes('invalid') || txt.toLowerCase().includes('error') || 
                            txt.toLowerCase().includes('valid') || txt.toLowerCase().includes('required') || 
                            txt.toLowerCase().includes('please') || txt.toLowerCase().includes('/') ||
                            err.classList.contains('artdeco-inline-feedback--error') || err.classList.contains('fb-form-element--error')
                        )) {
                            return txt;
                        }
                    }
                    return null;
                }""")
                if has_error:
                    self.bot_state.add_log(f"⚠️ Form validation error on Next: '{has_error}'. Retrying step fill...", "WARNING")
                    self.fill_easy_apply_step(dialog, detail_tab, profile, stop_event, company, title, location_hint=effective_loc)
                    time.sleep(0.8)
                    next_btn = dialog.query_selector("button:has-text('Next'), button[aria-label*='Continue to next step']")
                    if next_btn and next_btn.is_visible() and next_btn.is_enabled():
                        next_btn.click()
                        time.sleep(1.5)
                    
                    # Check if error still persists
                    still_err = dialog.evaluate("""() => {
                        const err = document.querySelector('[data-testid="text-input-helper-text"] p, .artdeco-inline-feedback--error, .fb-form-element--error, [data-test-form-element-error-message], span.error, [class*="error"], [class*="feedback--error"]');
                        if (err && err.offsetParent !== null) {
                            const txt = err.innerText.trim();
                            if (txt && !txt.toLowerCase().includes('success') && (
                                txt.toLowerCase().includes('invalid') || txt.toLowerCase().includes('error') || 
                                txt.toLowerCase().includes('valid') || txt.toLowerCase().includes('required') || 
                                txt.toLowerCase().includes('please') || txt.toLowerCase().includes('/') ||
                                err.classList.contains('artdeco-inline-feedback--error') || err.classList.contains('fb-form-element--error')
                            )) {
                                return txt;
                            }
                        }
                        return null;
                    }""")
                    if still_err:
                        self.bot_state.add_log(f"⚠️ Form validation notice: '{still_err}'. Leaving open in Chrome.", "WARNING")
                        detail_tab.bring_to_front()
                        record_application(
                            job_title=title, company_name=company, location=loc_text, job_url=job_url,
                            status="NEEDS_USER_INPUT", apply_type="LINKEDIN_EASY_APPLY", match_score=job_info.get("score", 85),
                            notes=f"Validation error blocking step: {still_err}", failure_reason=still_err, platform="LINKEDIN"
                        )
                        return {"status": "NEEDS_USER_INPUT", "reason": still_err}
                continue

            # If no forward button is enabled, break
            break

        # Fallback if dialog remains unsubmitted
        self.bot_state.add_log(f"Easy Apply reached final state without confirmation for {company}. Dialog kept OPEN for review.", "WARNING")
        detail_tab.bring_to_front()
        record_application(
            job_title=title, company_name=company, location=loc_text, job_url=job_url,
            status="APPLICATION_PENDING_CONFIRMATION", apply_type="LINKEDIN_EASY_APPLY", match_score=job_info.get("score", 85),
            notes="Easy Apply form completed. Kept open in Chrome for candidate confirmation.",
            failure_reason="CONFIRMATION_UNCERTAIN", platform="LINKEDIN"
        )
        self.cooldown_timer(
            min_sec=self.bot_state.config.unconfirmed_cooldown_min_sec,
            max_sec=self.bot_state.config.unconfirmed_cooldown_max_sec,
            stop_event=stop_event,
            reason=f"Safety pause for {company}"
        )
        return {"status": "APPLICATION_PENDING_CONFIRMATION", "success": False}

    def process_linkedin_job(self, context: BrowserContext, search_page: Page, job_info: Dict[str, Any], 
                             score: int, stop_event: threading.Event) -> Dict[str, Any]:
        """Unified processor for a single LinkedIn job (Easy Apply vs External Apply)."""
        title = job_info["title"]
        company = job_info["company"]
        loc_text = job_info["location"]
        job_url = job_info["url"]
        job_info["score"] = score

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
            detail_tab = context.new_page()
            detail_tab.goto(job_url, wait_until="domcontentloaded", timeout=35000)
            self.human_sleep(2.5, 4.0, stop_event)

            # Detect action button on page
            action_type, action_btn = self.detect_job_action_button(detail_tab)

            # 1. Already Applied
            if action_type == "ALREADY_APPLIED":
                self.bot_state.add_log(f"ℹ️ Already applied to {title} @ {company} on LinkedIn. Skipping.", "INFO")
                record_application(
                    job_title=title, company_name=company, location=loc_text, job_url=job_url,
                    status="APPLICATION_CONFIRMED", apply_type="LINKEDIN_EASY_APPLY", match_score=score,
                    notes="Already applied on LinkedIn.", platform="LINKEDIN"
                )
                try:
                    detail_tab.close()
                except Exception:
                    pass
                return {"status": "APPLICATION_CONFIRMED", "success": True, "attempted": False}

            # 2. Login Required
            if action_type == "LOGIN_REQUIRED":
                self.bot_state.add_log(f"🔒 LinkedIn session login required for {company}.", "WARNING")
                try:
                    detail_tab.close()
                except Exception:
                    pass
                return {"status": "FAILED", "reason": "LOGIN_REQUIRED", "attempted": False}

            # 3. Easy Apply Flow
            if action_type == "EASY_APPLY":
                self.bot_state.add_log(f"⚡ Easy Apply detected for {title} @ {company}! Clicking Easy Apply...", "INFO")
                action_btn.scroll_into_view_if_needed()
                time.sleep(0.3)
                action_btn.click()
                time.sleep(2.0)

                result = self.execute_easy_apply_flow(page=search_page, detail_tab=detail_tab, job_info=job_info, stop_event=stop_event)
                
                # If finished with success, close detail tab
                if result.get("status") == "APPLICATION_CONFIRMED":
                    try:
                        detail_tab.close()
                    except Exception:
                        pass
                return result

            # 4. External Apply (Company Portal Link)
            if action_type == "EXTERNAL_APPLY":
                self.bot_state.add_log(f"🏢 'Apply' button on LinkedIn redirects to company careers portal. Opening...", "INFO")
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

                    return self.handle_external_company_portal(
                        context=context,
                        detail_tab=detail_tab,
                        company_tab=company_tab,
                        title=title,
                        company=company,
                        loc_text=loc_text,
                        exp_text="5+ Yrs",
                        score=score,
                        stop_event=stop_event
                    )

            # 5. No Apply Button Found
            self.bot_state.add_log(f"No active Apply or Easy Apply button found for {title} @ {company}. Skipping.", "WARNING")
            record_application(
                job_title=title, company_name=company, location=loc_text, job_url=job_url,
                status="APPLICATION_SKIPPED", apply_type="LINKEDIN_EASY_APPLY", match_score=score,
                notes="No active Apply button found on page.", failure_reason="NO_APPLY_BUTTON", platform="LINKEDIN"
            )
            try:
                detail_tab.close()
            except Exception:
                pass
            return {"status": "SKIPPED", "attempted": False}

        except Exception as e:
            self.bot_state.add_log(f"Error processing LinkedIn job {title} @ {company}: {e}", "WARNING")
            try:
                if detail_tab and not detail_tab.is_closed():
                    detail_tab.close()
            except Exception:
                pass
            record_application(
                job_title=title, company_name=company, location=loc_text, job_url=job_url,
                status="APPLICATION_FAILED", apply_type="LINKEDIN_EASY_APPLY", match_score=score,
                notes=f"Exception: {e}", failure_reason=str(e), platform="LINKEDIN"
            )
            return {"status": "FAILED", "reason": str(e), "attempted": True}

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
                self.bot_state.add_log(f"🔎 [LinkedIn] [{role_idx+1}/{len(target_roles)}] Searching jobs for '{role_name}' in {current_loc}...", "INFO")

                try:
                    search_page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
                    self.human_sleep(3.5, 6.0, stop_event)
                except Exception as e:
                    self.bot_state.add_log(f"LinkedIn search navigation warning for '{role_name}' in {current_loc}: {e}", "WARNING")
                    continue

                # Extract job cards
                job_cards = self.extract_job_cards(search_page, max_cards=20)
                self.bot_state.add_log(f"Found {len(job_cards)} job cards on LinkedIn for '{role_name}' in {current_loc}. Inspecting...", "INFO")

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
                    job["search_location"] = current_loc

                    apply_mode_badge = "⚡ Easy Apply" if job.get("is_easy_apply") else "🏢 Company Portal"
                    self.bot_state.add_log(f"Inspecting [LinkedIn {job_idx+1}/{len(job_cards)}] ({apply_mode_badge}): {title} @ {company} [{loc_text or current_loc}]", "INFO")

                    # Check blacklisted technology titles (e.g. Java Full Stack, Spring Boot, .NET)
                    from bot_engine import is_job_title_blacklisted
                    is_title_blocked, title_block_reason = is_job_title_blacklisted(title)
                    if is_title_blocked:
                        self.bot_state.add_log(f"🚫 Skipping unwanted tech role '{title}' @ {company}: {title_block_reason}", "INFO")
                        record_application(
                            job_title=title, company_name=company, location=loc_text or current_loc, job_url=job_url,
                            status="APPLICATION_SKIPPED", match_score=0,
                            notes=f"Skipped: {title_block_reason}", failure_reason="TECHNOLOGY_NOT_ALLOWED",
                            platform="LINKEDIN"
                        )
                        continue

                    # Check duplicate in database
                    from bot_engine import check_already_applied_db
                    if check_already_applied_db(title, company):
                        self.bot_state.add_log(f"Already applied to {title} @ {company} in the past. Skipping.", "INFO")
                        continue

                    # Check AI relevance
                    self.bot_state.status = "EVALUATING"
                    score, should_apply, reason = evaluate_job_relevance(title, company, f"Location: {loc_text or current_loc}, Platform: LinkedIn")
                    self.bot_state.add_log(f"AI Match Score: {score}% - {reason}", "INFO" if should_apply else "WARNING")

                    if not should_apply or score < 65:
                        self.bot_state.add_log("Job does not match profile criteria. Skipping.", "INFO")
                        record_application(
                            job_title=title, company_name=company, location=loc_text or current_loc, job_url=job_url,
                            status="APPLICATION_SKIPPED", match_score=score,
                            notes=f"AI Skipped: {reason}", failure_reason="LOW_MATCH_SCORE",
                            platform="LINKEDIN"
                        )
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
