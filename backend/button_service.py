import re
import time
from typing import Dict, Any, List, Optional, Tuple
from playwright.sync_api import Page, Locator

class ButtonCategory:
    APPLY = "APPLY"
    CONTINUE = "CONTINUE"
    SAVE = "SAVE"
    REVIEW = "REVIEW"
    SUBMIT = "SUBMIT"
    UNRELATED = "UNRELATED"

class ButtonMetadata:
    def __init__(self, locator: Locator, text: str, category: str, is_enabled: bool, is_visible: bool, selector: str = ""):
        self.locator = locator
        self.text = text
        self.category = category
        self.is_enabled = is_enabled
        self.is_visible = is_visible
        self.selector = selector

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "category": self.category,
            "is_enabled": self.is_enabled,
            "is_visible": self.is_visible,
            "selector": self.selector
        }

class ButtonDetectionService:
    """
    Dedicated action-selection and button-detection service for multi-platform job applications:
    - Inspects visible buttons, links, submit inputs, accessible names, and form semantics.
    - Classifies actions: APPLY, CONTINUE, SAVE, REVIEW, and final SUBMIT.
    - Scopes to the active application form, dialog, or drawer.
    - Checks visibility, enabled state, and avoids clicking unrelated page controls (filters, search, cancel, close).
    - Avoids invalid native CSS selectors (never uses :has-text inside querySelector).
    - Verifies post-click DOM change or navigation.
    """

    SUBMIT_TERMS = [
        "submit application", "send application", "complete application",
        "finish application", "submit my application", "submit profile",
        "confirm and submit", "submit", "apply now"
    ]

    SAVE_TERMS = [
        "save and apply", "save & apply", "save and continue", "save & continue",
        "save application", "save changes", "save response", "save answer", "save"
    ]

    CONTINUE_TERMS = [
        "continue", "next step", "next", "proceed", "go to next step", "continue application"
    ]

    REVIEW_TERMS = [
        "review application", "review and submit", "preview application", "review", "preview"
    ]

    APPLY_TERMS = [
        "apply on company site", "apply directly", "apply now", "easy apply", "apply"
    ]

    UNRELATED_TERMS = [
        "filter", "search", "cancel", "close", "reject", "dismiss", "edit", "back",
        "clear", "reset", "delete", "remove", "sign out", "log out", "view jobs", "bookmark"
    ]

    def classify_button_text(self, text: str, aria_label: str = "", button_type: str = "") -> str:
        """Classifies button text and aria-label into semantic action category."""
        combined = f"{text} {aria_label}".lower().strip()
        combined = re.sub(r"\s+", " ", combined)

        # 1. Unrelated controls filter
        if any(un in combined for un in self.UNRELATED_TERMS):
            # Exception: 'save and apply' shouldn't be rejected
            if not any(st in combined for st in ["save", "apply", "submit", "continue", "next"]):
                return ButtonCategory.UNRELATED

        # 2. Final Submit
        for term in self.SUBMIT_TERMS:
            if re.search(rf"\b{re.escape(term)}\b", combined, re.IGNORECASE):
                return ButtonCategory.SUBMIT

        # 3. Save
        for term in self.SAVE_TERMS:
            if re.search(rf"\b{re.escape(term)}\b", combined, re.IGNORECASE):
                return ButtonCategory.SAVE

        # 4. Continue / Next Step
        for term in self.CONTINUE_TERMS:
            if re.search(rf"\b{re.escape(term)}\b", combined, re.IGNORECASE):
                return ButtonCategory.CONTINUE

        # 5. Review
        for term in self.REVIEW_TERMS:
            if re.search(rf"\b{re.escape(term)}\b", combined, re.IGNORECASE):
                return ButtonCategory.REVIEW

        # 6. Apply
        for term in self.APPLY_TERMS:
            if re.search(rf"\b{re.escape(term)}\b", combined, re.IGNORECASE):
                return ButtonCategory.APPLY

        if button_type.lower() == "submit":
            return ButtonCategory.SUBMIT

        return ButtonCategory.UNRELATED

    def detect_buttons_in_container(self, page: Page, container: Optional[Locator] = None) -> List[ButtonMetadata]:
        """
        Discovers and classifies all visible buttons inside a scoped container or page.
        Uses Playwright locators and safe DOM evaluation (no native :has-text).
        """
        root = container if container is not None else page
        detected: List[ButtonMetadata] = []

        candidate_selectors = [
            "button",
            "input[type='submit']",
            "input[type='button']",
            "[role='button']",
            "a.btn",
            "a.button",
            "a[class*='apply']",
            "a[class*='submit']",
            "a[class*='save']",
            "a[id*='apply']",
            "a[id*='submit']",
            "a[href*='apply']",
            "a"
        ]

        seen_elements = set()

        for sel in candidate_selectors:
            try:
                loc = root.locator(sel)
                count = loc.count()
                for i in range(count):
                    btn = loc.nth(i)
                    try:
                        if not btn.is_visible():
                            continue

                        meta = btn.evaluate("""(el) => {
                            const text = (el.innerText || el.textContent || el.value || '').trim();
                            const aria = (el.getAttribute('aria-label') || el.getAttribute('title') || '').trim();
                            const btype = (el.getAttribute('type') || '').trim();
                            return { text: text, aria: aria, btype: btype, disabled: el.disabled || el.getAttribute('aria-disabled') === 'true' };
                        }""")

                        text = meta.get("text", "")
                        aria = meta.get("aria", "")
                        btype = meta.get("btype", "")
                        is_disabled = meta.get("disabled", False)
                        is_enabled = not is_disabled and btn.is_enabled()

                        key = f"{text}_{aria}_{btype}_{sel}"
                        if key in seen_elements:
                            continue
                        seen_elements.add(key)

                        category = self.classify_button_text(text, aria, btype)
                        if category != ButtonCategory.UNRELATED:
                            detected.append(ButtonMetadata(
                                locator=btn,
                                text=text or aria or "Button",
                                category=category,
                                is_enabled=is_enabled,
                                is_visible=True,
                                selector=sel
                            ))
                    except Exception:
                        continue
            except Exception:
                continue

        return detected

    def find_action_button(self, page: Page, target_categories: List[str], active_container: Optional[Locator] = None) -> Optional[Locator]:
        """
        Finds the single best enabled action button matching target categories in priority order.
        Scopes to the active form or dialog if provided.
        """
        buttons = self.detect_buttons_in_container(page, active_container)

        # Try to find enabled button in requested categories priority
        for cat in target_categories:
            for b in buttons:
                if b.category == cat and b.is_enabled:
                    return b.locator

        # Fallback to disabled button if no enabled button exists yet (e.g. form validation pending)
        for cat in target_categories:
            for b in buttons:
                if b.category == cat:
                    return b.locator

        return None

    def find_form_submit_or_save_button(self, page: Page, container: Optional[Locator] = None) -> Optional[Locator]:
        """Convenience method to locate the Save, Submit, or Continue button for the current step."""
        priority = [ButtonCategory.SUBMIT, ButtonCategory.SAVE, ButtonCategory.CONTINUE, ButtonCategory.REVIEW]
        return self.find_action_button(page, priority, container)

    def execute_and_verify_button_click(self, page: Page, button_locator: Locator, timeout_sec: float = 6.0) -> Dict[str, Any]:
        """
        Safely scrolls into view, clicks the button, and waits for a condition-based outcome:
        - Navigation / URL change
        - Page-level or modal confirmation message
        - Validation errors on the page
        - Container closed
        """
        try:
            button_locator.scroll_into_view_if_needed()
            time.sleep(0.1)
            url_before = page.url

            button_locator.click()

            start_time = time.time()
            while time.time() - start_time < timeout_sec:
                time.sleep(0.5)

                # Check 1: Comprehensive confirmation check (including ACP saveApply & badges)
                is_conf, conf_reason = is_naukri_application_confirmed(page)
                if is_conf:
                    return {"success": True, "outcome": "CONFIRMED", "reason": conf_reason}

                # Check 2: Navigation occurred
                if page.url != url_before:
                    return {"success": True, "outcome": "NAVIGATED", "new_url": page.url}

                # Check 3: Visible validation errors appeared
                error_msg = page.evaluate("""() => {
                    const errs = Array.from(document.querySelectorAll('.error, .alert-danger, .invalid-feedback, span[class*="error"]'))
                        .filter(e => e.offsetParent !== null && (e.innerText || '').trim().length > 1);
                    return errs.length > 0 ? errs[0].innerText.trim() : null;
                }""")
                if error_msg:
                    return {"success": False, "outcome": "VALIDATION_ERROR", "error": error_msg}

            return {"success": True, "outcome": "CLICK_EXECUTED"}

        except Exception as e:
            return {"success": False, "outcome": "CLICK_FAILED", "error": str(e)}


def is_naukri_application_confirmed(page: Page) -> Tuple[bool, str]:
    """
    Comprehensive verification to determine if a Naukri application succeeded:
    1. Checks if page navigated to Apply Confirmation Page (/myapply/saveApply, multiApplyResp=200).
    2. Checks page title 'Apply Confirmation'.
    3. Checks Apply Confirmation Page DOM containers (.acp-container, .acp-header-container, text 'Applied to "..."').
    4. Checks page-level badges (#already-applied, .already-applied, 'Applied', [class*='apply-button-container']:has-text('Applied')).
    5. Checks toast/banner success alerts ('applied successfully', 'application has been sent', 'application received', etc.).
    6. Checks chat drawer success text.
    """
    if not page:
        return False, "PAGE_NONE"

    try:
        if page.is_closed():
            return False, "PAGE_CLOSED"

        url = (page.url or "").lower()
        title = (page.title() or "").lower()

        # 1. URL-level confirmation indicators (saveApply / ACP)
        if "saveapply" in url or "myapply" in url:
            if "multiapplyresp" in url and "200" in url:
                return True, "URL_MULTI_APPLY_200"
            return True, "URL_SAVE_APPLY_CONFIRMED"

        # 2. Title-level confirmation
        if "apply confirmation" in title:
            return True, "TITLE_APPLY_CONFIRMATION"

        # 3. DOM-level Apply Confirmation Page (ACP) elements
        is_acp = page.evaluate("""() => {
            const hasAcp = !!document.querySelector('.acp-container, .acp-header-container, .acp-header, div[class*="acp-"]');
            const hasAppliedTo = Array.from(document.querySelectorAll('h1, h2, h3, div, p, span'))
                .some(e => {
                    const txt = (e.innerText || '').toLowerCase().trim();
                    return txt.startsWith('applied to') || txt.includes('applied to "');
                });
            return hasAcp || hasAppliedTo;
        }""")
        if is_acp:
            return True, "DOM_ACP_CONTAINER_FOUND"

        # 4. Job details page badge & button elements
        has_badge = page.evaluate("""() => {
            const sels = [
                '#already-applied',
                '.already-applied',
                '.applied-badge',
                '.apply-message',
                '.success-message',
                'span#already-applied',
                'button#already-applied',
                'a#already-applied',
                'div[class*="already-applied"]',
                'span[class*="already-applied"]',
                'div[class*="apply-button-container"]'
            ];
            for (const s of sels) {
                const els = document.querySelectorAll(s);
                for (const el of els) {
                    if (el.offsetParent !== null) {
                        const txt = (el.innerText || '').toLowerCase().trim();
                        if (txt.includes('applied') || txt.includes('application sent')) {
                            return true;
                        }
                    }
                }
            }
            return false;
        }""")
        if has_badge:
            return True, "DOM_ALREADY_APPLIED_BADGE"

        # 5. Toast / snackbar notifications
        has_toast = page.evaluate("""() => {
            const toastEls = Array.from(document.querySelectorAll('.toast, .toaster, .n-toast, .snackbar, div[class*="toast"], div[class*="snackbar"], .server-message, .apply-message'))
                .filter(e => e.offsetParent !== null);
            const successTerms = [
                'applied successfully', 'successfully applied', 'application has been sent',
                'application received', 'thank you for applying', 'already applied',
                'applied to', 'applied on', 'application submitted', 'profile sent', 'resume sent'
            ];
            for (const t of toastEls) {
                const txt = (t.innerText || '').toLowerCase();
                if (successTerms.some(term => txt.includes(term))) return true;
            }
            return false;
        }""")
        if has_toast:
            return True, "TOAST_CONFIRMATION_FOUND"

        # 6. Chat drawer success message
        has_chat_success = page.evaluate("""() => {
            const chatEls = Array.from(document.querySelectorAll('.botMsg, .chatContent, div[class*="botMsg"], div[class*="chatMsg"], .bot-row, p.msg, div.apply-message, .success-title'))
                .filter(e => e.offsetParent !== null);
            const text = chatEls.map(el => (el.innerText || '').toLowerCase()).join(' ');
            return text.includes('application has been sent') || 
                   text.includes('applied successfully') || 
                   text.includes('application received') || 
                   text.includes('thank you for applying') ||
                   text.includes('applied on') ||
                   text.includes('already applied') ||
                   text.includes('applied to');
        }""")
        if has_chat_success:
            return True, "CHAT_SUCCESS_MESSAGE_FOUND"

    except Exception as e:
        return False, f"VERIFY_ERROR: {e}"

    return False, "NOT_CONFIRMED"


button_service = ButtonDetectionService()

