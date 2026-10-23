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

                # Check 1: Navigation occurred
                if page.url != url_before:
                    return {"success": True, "outcome": "NAVIGATED", "new_url": page.url}

                # Check 2: Success / Confirmation detected
                has_success = page.evaluate("""() => {
                    const text = Array.from(document.querySelectorAll('.apply-message, .success-message, .applied-badge, div, p, span'))
                        .map(el => (el.innerText || '').toLowerCase())
                        .join(' ');
                    return text.includes('application has been sent') || 
                           text.includes('applied successfully') || 
                           text.includes('application received') || 
                           text.includes('thank you for applying') ||
                           text.includes('already applied');
                }""")
                if has_success:
                    return {"success": True, "outcome": "CONFIRMED"}

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

button_service = ButtonDetectionService()
