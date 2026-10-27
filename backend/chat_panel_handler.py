import re
import time
import threading
from typing import Dict, Any, List, Optional, Tuple
from playwright.sync_api import Page, Locator

from question_answering import QuestionAnsweringEngine, QuestionCategory, qa_engine
from database import record_experience, lookup_experience, update_reasoning_metric
from button_service import is_naukri_application_confirmed

class ChatPanelState:
    QUESTION_DETECTED = "QUESTION_DETECTED"
    ANSWER_GENERATED = "ANSWER_GENERATED"
    ANSWER_INSERTED = "ANSWER_INSERTED"
    ANSWER_SAVED = "ANSWER_SAVED"
    NEXT_QUESTION_PENDING = "NEXT_QUESTION_PENDING"
    NEEDS_USER_INPUT = "NEEDS_USER_INPUT"
    FORM_COMPLETED = "FORM_COMPLETED"
    APPLICATION_SUBMITTED = "APPLICATION_SUBMITTED"
    APPLICATION_CONFIRMED = "APPLICATION_CONFIRMED"
    CONFIRMATION_TIMEOUT = "CONFIRMATION_TIMEOUT"

class NaukriChatPanelHandler:
    """
    Dedicated Handler for Naukri.com right-side chat-style application drawer / screening panel:
    1. Scopes search to visible application drawer/panel container.
    2. Accurately extracts questions from bot message bubbles (.botMsg, .chatMsg, .msgText).
       NEVER uses the input placeholder ("Type message here...") as the question text.
    3. Locates chat input/textarea using multi-strategy locators (getByPlaceholder, scoped selectors).
    4. Enters generated answers and triggers input/change events.
    5. Verifies that entered values are retained before clicking Save.
    6. Locates and validates scoped Save button (checks visible & enabled).
    7. Evaluates state transitions (next question, panel closed, or confirmation).
    8. Handles sequential questions in a loop with infinite-loop prevention.
    9. On unverified mandatory questions: marks NEEDS_USER_INPUT and keeps tab open without closing.
    """

    PANEL_SELECTORS = [
        "._chatBotContainer",
        "div[class*='chatBotContainer' i]",
        "div[id*='ChatbotContainer' i]",
        "div[class*='chatbot_Overlay' i]",
        ".chatbot_Overlay",
        ".chatbot_drawer",
        ".drawer-wrapper",
        "div[class*='chatbot' i]",
        "div[class*='chatPanel' i]",
        "div[class*='drawer' i]",
        "div[class*='applyDrawer' i]",
        "div[class*='chatContent' i]",
        "div[role='dialog']",
        ".apply-dialog",
        ".modal-content"
    ]

    QUESTION_SELECTORS = [
        ".botMsg",
        ".chatMsg",
        "div[class*='botMsg']",
        "div[class*='chatMsg']",
        "div[class*='msgText']",
        ".msgText",
        ".bot-row",
        "p.msg",
        "div.msg",
        ".chat-question",
        "div[class*='questionBubble']",
        "div[class*='botMessage']",
        "div[class*='bot_msg']"
    ]

    def __init__(self, logger_fn=None):
        self.logger = logger_fn or (lambda msg, level="INFO": print(f"[{level}] {msg}"))

    def detect_chat_panel(self, page: Page) -> Optional[Locator]:
        """Detects if a right-side chat-style application panel or screening drawer is visible."""
        found_any_panel_element = False

        for sel in self.PANEL_SELECTORS:
            try:
                loc = page.locator(sel)
                count = loc.count()
                for i in range(count):
                    candidate = loc.nth(i)
                    if candidate.is_visible():
                        # Verify it contains chat elements (bot bubbles or chat input or chips)
                        has_chat = candidate.evaluate("""(el) => {
                            const isVis = e => e && e.offsetParent !== null && window.getComputedStyle(e).display !== 'none';
                            const hasBubble = Array.from(el.querySelectorAll('.botMsg, .chatMsg, [class*="botMsg" i], [class*="chatMsg" i], [class*="msgText" i], .msgText, .bot-row, p.msg, div.msg')).some(isVis);
                            const hasInput = Array.from(el.querySelectorAll('textarea, input[placeholder*="Type" i], input.chat-input, [class*="chatInput" i]')).some(isVis);
                            const hasChips = Array.from(el.querySelectorAll('.chip, .botOption, [class*="chip" i]')).some(isVis);
                            return hasBubble || hasInput || hasChips;
                        }""")
                        if has_chat:
                            return candidate
            except Exception:
                continue

        # Fallback: check if page body has VISIBLE chat bubbles and chat input or chatbot container
        try:
            has_page_chat = page.evaluate("""() => {
                const isVis = el => el && el.offsetParent !== null && window.getComputedStyle(el).display !== 'none' && window.getComputedStyle(el).visibility !== 'hidden';
                const hasBubble = Array.from(document.querySelectorAll('.botMsg, .chatMsg, [class*="botMsg" i], [class*="chatMsg" i], [class*="msgText" i], .msgText, p.msg, div[class*="msg" i]')).some(isVis);
                const hasInput = Array.from(document.querySelectorAll('input[placeholder*="Type" i], textarea[placeholder*="Type" i], input.chat-input, ._chatBotContainer input, div[class*="chatBotContainer" i] input')).some(isVis);
                const hasContainer = document.querySelector('._chatBotContainer, .chatbot_Overlay, div[class*="chatBotContainer" i]') !== null;
                return (hasBubble && hasInput) || (hasContainer && hasInput);
            }""")
            if has_page_chat:
                for c_sel in ["._chatBotContainer", "div[class*='chatBotContainer' i]", ".chatbot_drawer", "div[class*='chatbot' i]"]:
                    c_loc = page.locator(c_sel)
                    if c_loc.count() > 0 and c_loc.first.is_visible():
                        return c_loc.first
                return page.locator("body")
        except Exception:
            pass

        return None

    def extract_latest_question(self, page: Page, panel: Optional[Locator] = None) -> Optional[str]:
        """
        Reads the actual question displayed inside the chat bubbles.
        NEVER returns the input field's placeholder text.
        Filters out candidate answers, file bubbles, and informational bot notices.
        """
        root = panel if panel is not None else page.locator("body")
        
        try:
            question_text = root.evaluate("""(container) => {
                const isVis = e => e && e.offsetParent !== null && window.getComputedStyle(e).display !== 'none';
                const selectors = [
                    '.botMsg', '.chatMsg', 'div[class*="botMsg" i]', 'div[class*="chatMsg" i]',
                    'div[class*="msgText" i]', '.msgText', '.bot-row', 'p.msg', 'div.msg',
                    '.chat-question', 'div[class*="questionBubble" i]', 'div[class*="botMessage" i]',
                    'div[class*="bot_msg" i]', 'div[class*="bot-msg" i]', 'div[class*="bubble" i]'
                ];
                
                const ignorePhrases = [
                    'file upload was unsuccessful',
                    'please try again',
                    'thank you for showing interest',
                    'kindly answer all the recruiter',
                    'type message here',
                    'please answer the questions'
                ];

                const bubbles = [];
                for (const sel of selectors) {
                    const matches = container.querySelectorAll(sel);
                    for (const m of matches) {
                        if (isVis(m) && !bubbles.some(b => b.el === m)) {
                            const tag = m.tagName.toLowerCase();
                            if (tag !== 'input' && tag !== 'textarea' && tag !== 'button') {
                                const cls = (m.className || '').toLowerCase();
                                if (cls.includes('user') || cls.includes('outgoing') || cls.includes('candidate') || cls.includes('right')) {
                                    continue;
                                }
                                const text = (m.innerText || m.textContent || '').trim();
                                if (/\\.(pdf|docx?|txt)$/i.test(text)) continue;
                                if (text.length > 2 && !text.toLowerCase().includes('type message here')) {
                                    bubbles.push({ el: m, text: text, top: m.getBoundingClientRect().top });
                                }
                            }
                        }
                    }
                }
                
                if (bubbles.length === 0) return null;
                bubbles.sort((a, b) => a.top - b.top);
                
                for (let i = bubbles.length - 1; i >= 0; i--) {
                    const t = bubbles[i].text.toLowerCase();
                    if (!ignorePhrases.some(phrase => t.includes(phrase))) {
                        return bubbles[i].text;
                    }
                }
                return bubbles[bubbles.length - 1].text;
            }""")

            if question_text and isinstance(question_text, str) and len(question_text.strip()) > 1:
                clean_q = re.sub(r"\s+", " ", question_text).strip()
                return clean_q
        except Exception as e:
            self.logger(f"Error evaluating latest question bubble: {e}", "WARNING")

        # Fallback: check standard labels inside drawer
        try:
            label_text = root.evaluate("""(container) => {
                const labels = Array.from(container.querySelectorAll('label, .question-title, .screening-q, h3, h4'))
                    .filter(el => el.offsetParent !== null && el.innerText.trim().length > 3);
                return labels.length > 0 ? labels[labels.length - 1].innerText.trim() : null;
            }""")
            if label_text:
                return re.sub(r"\s+", " ", label_text).strip()
        except Exception:
            pass

        return None

    def locate_chat_input(self, page: Page, panel: Optional[Locator] = None) -> Optional[Locator]:
        """
        Locates the visible input or textarea associated with the question.
        Supports 'Type message here...' placeholder without relying exclusively on it.
        """
        root = panel if panel is not None else page

        # Strategy 1: Playwright getByPlaceholder matching "Type message here..." (case-insensitive regex)
        try:
            loc = root.get_by_placeholder(re.compile(r"type\s*(message)?\s*here", re.I))
            for i in range(loc.count()):
                el = loc.nth(i)
                if el.is_visible() and el.is_enabled():
                    return el
        except Exception:
            pass

        # Strategy 2: Textarea inside panel
        try:
            textareas = root.locator("textarea")
            for i in range(textareas.count()):
                ta = textareas.nth(i)
                if ta.is_visible() and ta.is_enabled():
                    return ta
        except Exception:
            pass

        # Strategy 3: Scoped input selectors
        candidate_selectors = [
            "div.textArea[contenteditable='true']",
            "div.textArea",
            "div[class*='textArea' i][contenteditable='true']",
            "div[class*='textArea' i]",
            "[contenteditable='true']",
            "input[placeholder*='Type message' i]",
            "textarea[placeholder*='Type message' i]",
            "input[placeholder*='Type' i]",
            "textarea[placeholder*='Type' i]",
            "input[placeholder*='answer' i]",
            "textarea[placeholder*='answer' i]",
            "input[placeholder*='reply' i]",
            "input[placeholder*='enter' i]",
            "input[placeholder*='write' i]",
            "input.chat-input",
            "textarea.chat-input",
            ".user-input input",
            ".user-input textarea",
            "div[class*='chatInput' i] input",
            "div[class*='chatInput' i] textarea",
            "div[class*='chatbot' i] input[type='text']",
            "div[class*='drawer' i] input[type='text']",
            "[role='textbox']",
            "input[type='text']:not([disabled])",
            "input:not([type='hidden']):not([disabled]):not([type='checkbox']):not([type='radio'])"
        ]

        roots = [root]
        if root != page:
            roots.append(page)

        for r in roots:
            for sel in candidate_selectors:
                try:
                    candidates = r.locator(sel)
                    for i in range(candidates.count()):
                        cand = candidates.nth(i)
                        if cand.is_visible() and cand.is_enabled():
                            return cand
                except Exception:
                    continue

        return None

    def extract_chat_options(self, page: Page, panel: Optional[Locator] = None) -> List[Dict[str, Any]]:
        """
        Extracts visible quick-reply chips, pill buttons, or radio choices associated with the question.
        Returns a list of dicts: [{"locator": loc, "text": clean_text, "value": val}]
        """
        chip_selectors = [
            "label.ssrc__label",
            "label[class*='ssrc__label']",
            ".ssrc__radio-btn-container label",
            "label[class*='radio' i]",
            "label[class*='chip' i]",
            "div.ssrc__radio-btn-container label",
            ".chip",
            ".botOption",
            "button.option-btn",
            "div.quick-reply",
            "div[class*='quickReply' i]",
            "div[class*='quick-reply' i]",
            "span.chip",
            ".chat-chip",
            "div[class*='chat-chip' i]",
            ".option",
            "button[class*='chip' i]",
            "div[class*='chip' i]",
            "span[class*='chip' i]",
            "div[class*='pill' i]",
            "span[class*='pill' i]",
            "button[class*='pill' i]",
            "div[class*='choice' i]",
            "button[class*='choice' i]",
            "span[class*='choice' i]",
            "div[class*='radio' i]",
            "[role='radio']",
            "input[type='radio']",
            ".bot-option",
            "div[class*='botOption' i]",
            "div[class*='bot-option' i]",
            ".chatContent button",
            ".chatContent label",
            ".chatContent [role='button']"
        ]
        
        ignored_button_words = ["save", "submit", "send", "close", "cancel", "dismiss", "back", "next", "attach", "upload", "clear"]
        options = []
        seen_texts = set()

        roots = [panel, page] if panel is not None else [page]
        for root_el in roots:
            for sel in chip_selectors:
                try:
                    candidates = root_el.locator(sel)
                    for i in range(candidates.count()):
                        cand = candidates.nth(i)
                        if cand.is_visible():
                            try:
                                txt = cand.evaluate("""el => {
                                    if (el.tagName === 'INPUT' && el.labels && el.labels.length > 0) {
                                        return (el.labels[0].innerText || el.labels[0].textContent || '').trim();
                                    }
                                    return (el.innerText || el.textContent || el.value || '').trim();
                                }""")
                            except Exception:
                                txt = (cand.inner_text() or "").strip()
                            if not txt or len(txt) > 120:
                                continue
                            txt_low = txt.lower()
                            if any(u in txt_low for u in ignored_button_words):
                                continue
                            if txt_low in seen_texts:
                                continue
                            seen_texts.add(txt_low)
                            val = ""
                            try:
                                val = cand.evaluate("""el => {
                                    if (el.value) return el.value;
                                    if (el.getAttribute('data-value')) return el.getAttribute('data-value');
                                    if (el.htmlFor) {
                                        const inp = document.getElementById(el.htmlFor);
                                        if (inp && inp.value) return inp.value;
                                    }
                                    return '';
                                }""")
                            except Exception:
                                try:
                                    val = cand.get_attribute("value") or ""
                                except Exception:
                                    pass
                            options.append({
                                "locator": cand,
                                "text": txt,
                                "value": val or txt
                            })
                except Exception:
                    continue
            if options:
                break

        return options

    def _find_matching_option(self, available_options: List[Dict[str, Any]], answer: str, category: str = "") -> Optional[Dict[str, Any]]:
        """Intelligently matches an answer string against extracted chat options."""
        if not available_options or not answer:
            return None
        ans_low = answer.strip().lower()
        
        # 1. Exact match
        for opt in available_options:
            otxt = opt["text"].strip().lower()
            oval = opt["value"].strip().lower()
            if otxt == ans_low or oval == ans_low:
                return opt

        # 2. Location & Relocation matching (e.g. Mumbai, Kurla, Willing to relocate)
        if category in [QuestionCategory.RELOCATION, QuestionCategory.LOCATION] or "mumbai" in ans_low or ans_low in ["yes", "true"]:
            loc_terms = [
                "currently residing in mumbai", "residing in mumbai", "reside in mumbai",
                "i currently reside in mumbai", "mumbai", "kurla", "willing to relocate to mumbai",
                "open to relocate to mumbai", "willing to relocate", "open to relocate", "relocate",
                "yes", "yes, residing", "yes, willing", "both", "agree"
            ]
            for term in loc_terms:
                match = next((o for o in available_options if term in o["text"].lower() or term in o["value"].lower()), None)
                if match:
                    return match

        # 3. Technical Skills matching (e.g. Node.js vs Golang)
        if category == QuestionCategory.TECHNICAL_SKILLS or any(k in ans_low for k in ["node", "react", "mern", "typescript"]):
            if "node" in ans_low:
                match = next((o for o in available_options if any(k in o["text"].lower() or k in o["value"].lower() for k in ["node.js", "nodejs", "node js", "node"])), None)
                if match:
                    return match
            if "react" in ans_low:
                match = next((o for o in available_options if any(k in o["text"].lower() or k in o["value"].lower() for k in ["react.js", "reactjs", "react js", "react"])), None)
                if match:
                    return match

        # 4. Notice Period matching
        if category == QuestionCategory.NOTICE_PERIOD or "immediate" in ans_low:
            for term in ["immediate", "0-15", "15 day", "less than 15", "serving", "15", "30 day", "1 month", "30", "0"]:
                match = next((o for o in available_options if term in o["text"].lower() or term in o["value"].lower()), None)
                if match:
                    return match

        # 5. Experience matching
        if category == QuestionCategory.EXPERIENCE or "year" in ans_low or "5" in ans_low:
            for term in ["5+", "5 to", "5-", "5 years", "5 year", "4-6", "3-5", "5"]:
                match = next((o for o in available_options if term in o["text"].lower() or term in o["value"].lower()), None)
                if match:
                    return match

        # 6. Yes / Affirmative matching
        if ans_low in ["yes", "true", "agree", "positive"]:
            for term in ["yes", "agree", "confirm", "comfortable", "i agree", "available", "willing", "residing"]:
                match = next((o for o in available_options if term in o["text"].lower() or term in o["value"].lower()), None)
                if match:
                    return match

        # 7. Substring matching
        for opt in available_options:
            otxt = opt["text"].strip().lower()
            oval = opt["value"].strip().lower()
            if ans_low in otxt or otxt in ans_low or (len(ans_low) > 3 and ans_low in oval):
                return opt

        return None

    def _is_button_enabled(self, loc: Locator) -> bool:
        """
        Checks whether a button or clickable div is enabled, verifying both
        Playwright is_enabled() and CSS classes like .disabled or disabled attribute.
        """
        try:
            if not loc.is_enabled():
                return False
            is_disabled = loc.evaluate("""el => {
                if (el.disabled || el.getAttribute('aria-disabled') === 'true') return true;
                if (el.classList && el.classList.contains('disabled')) return true;
                if (el.closest('.disabled') || el.closest('[disabled]')) return true;
                return false;
            }""")
            return not is_disabled
        except Exception:
            try:
                return loc.is_enabled()
            except Exception:
                return True

    def _get_element_value(self, loc: Locator) -> str:
        """
        Safely retrieves the entered text/value from input, textarea, or contenteditable element.
        Avoids Playwright's input_value() exception on contenteditable divs.
        """
        try:
            val = loc.evaluate("""el => {
                if (el.isContentEditable) {
                    return (el.innerText || el.textContent || '').trim();
                }
                if (el.value !== undefined && el.value !== null && el.value !== '') {
                    return String(el.value).trim();
                }
                return (el.innerText || el.textContent || '').trim();
            }""")
            if val:
                return val
        except Exception:
            pass

        try:
            return loc.input_value().strip()
        except Exception:
            pass

        try:
            return (loc.inner_text() or "").strip()
        except Exception:
            return ""

    def locate_save_button(self, page: Page, panel: Optional[Locator] = None) -> Optional[Locator]:
        """
        Locates the correct Save / Save and Apply button within the relevant panel.
        Checks that it is visible and enabled before returning.
        Avoids cancel, close, cross, dismiss, or bookmark ("Save Job") buttons.
        """
        root = panel if panel is not None else page
        unrelated = ["close", "cancel", "dismiss", "reject", "back", "clear", "save-job", "save job", "bookmark"]

        # Strategy 1: Playwright getByRole button with exact/regex name for "Save", "Save and Apply", "Submit", "Send"
        save_names = [
            re.compile(r"^\s*save\s*$", re.I),
            re.compile(r"^\s*save\s*(and|&)\s*apply\s*$", re.I),
            re.compile(r"^\s*submit\s*$", re.I),
            re.compile(r"^\s*send\s*$", re.I)
        ]

        for name_regex in save_names:
            try:
                loc = root.get_by_role("button", name=name_regex)
                for i in range(loc.count()):
                    btn = loc.nth(i)
                    if btn.is_visible() and self._is_button_enabled(btn):
                        btn_cls = (btn.get_attribute("class") or "").lower()
                        if any(u in btn_cls for u in ["save-job", "bookmark", "styles_save-job"]):
                            continue
                        return btn
            except Exception:
                pass

        # Strategy 2: Scoped CSS selectors within panel
        candidate_selectors = [
            # Naukri chatbot specific send/save buttons
            ".sendMsg",
            "div.sendMsg",
            "div[class*='sendMsg' i]",
            "div.sendMsgbtn_container .sendMsg",
            "div.send:not(.disabled) .sendMsg",
            "div.send:not(.disabled)",
            "div[class*='sendMsgbtn_container' i] [class*='sendMsg' i]",
            # Generic button selectors
            "button.save-btn",
            "button[class*='save']",
            "button:has-text('Save')",
            "button:has-text('Save and Apply')",
            "button:has-text('Save & Apply')",
            "button:has-text('Send')",
            "button:has-text('Submit')",
            "button.send-btn",
            "button.submit-btn",
            ".sendBtn",
            "input[type='submit'][value*='Save' i]",
            "button[type='submit']",
            "[role='button']:has-text('Save')",
            "[role='button']:has-text('Submit')"
        ]

        for sel in candidate_selectors:
            try:
                candidates = root.locator(sel)
                for i in range(candidates.count()):
                    cand = candidates.nth(i)
                    if cand.is_visible() and self._is_button_enabled(cand):
                        btn_cls = (cand.get_attribute("class") or "").lower()
                        if any(u in btn_cls for u in ["save-job", "bookmark", "styles_save-job"]):
                            continue
                        btn_text = (cand.inner_text() or cand.get_attribute("value") or cand.get_attribute("aria-label") or "").lower().strip()
                        if not any(u in btn_text for u in unrelated):
                            return cand
            except Exception:
                continue

        return None

    def fill_and_verify_answer(self, page: Page, input_loc: Locator, answer: str) -> bool:
        """
        Enters the generated answer using Playwright interactions.
        Handles both standard input/textarea elements and contenteditable divs.
        Triggers input and change events and verifies the entered value is retained.
        """
        if not answer:
            return False

        try:
            input_loc.scroll_into_view_if_needed()
            input_loc.click()
            time.sleep(0.1)

            # Determine if element is contenteditable
            is_editable = False
            try:
                is_editable = input_loc.evaluate("el => !!el.isContentEditable")
            except Exception:
                pass

            if is_editable:
                # Clear contenteditable container cleanly
                input_loc.evaluate("""el => {
                    el.innerText = '';
                    el.textContent = '';
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                }""")
                time.sleep(0.05)
                try:
                    input_loc.fill(answer)
                except Exception:
                    input_loc.type(answer, delay=15)
            else:
                try:
                    input_loc.fill("")
                    time.sleep(0.05)
                    input_loc.fill(answer)
                except Exception:
                    input_loc.type(answer, delay=15)

            time.sleep(0.1)
            # Dispatch necessary events for React/Angular/Vue bindings
            input_loc.dispatch_event("input")
            input_loc.dispatch_event("change")
            time.sleep(0.1)

            # Verify that the entered value is retained
            val = self._get_element_value(input_loc)
            if val and (answer.lower() in val.lower() or val.strip() == answer.strip()):
                return True

            # Fallback: re-clear and type character-by-character
            input_loc.click()
            if is_editable:
                input_loc.evaluate("""el => {
                    el.innerText = '';
                    el.textContent = '';
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                }""")
            else:
                try:
                    input_loc.fill("")
                except Exception:
                    pass

            input_loc.type(answer, delay=20)
            input_loc.dispatch_event("input")
            input_loc.dispatch_event("change")
            time.sleep(0.1)

            val = self._get_element_value(input_loc)
            return bool(val and (answer.lower() in val.lower() or val.strip() == answer.strip()))

        except Exception as e:
            self.logger(f"Error filling and verifying answer: {e}", "WARNING")
            return False

    def click_save_and_wait_transition(self, page: Page, save_btn: Locator, initial_question: str, timeout_sec: float = 6.0) -> Dict[str, Any]:
        """
        Clicks Save and waits condition-based for the resulting UI state.
        Determines whether the question was accepted, the panel advanced to another question, or the panel closed.
        """
        try:
            save_btn.scroll_into_view_if_needed()
            time.sleep(0.1)
            save_btn.click()
            self.logger("💾 Scoped Save button clicked.", "INFO")
        except Exception as e:
            self.logger(f"Failed to click Save button: {e}", "ERROR")
            return {"transition": "CLICK_FAILED", "error": str(e)}

        return self.wait_for_transition(page, initial_question, timeout_sec)

    def submit_chat_input_and_wait_transition(self, page: Page, chat_input: Locator, panel: Optional[Locator], initial_question: str, timeout_sec: float = 6.0) -> Dict[str, Any]:
        """
        Submits answer via Enter key or send icon button when no Save button exists in the chat interface.
        """
        try:
            chat_input.press("Enter")
            self.logger("⌨️ Pressed Enter on chat input.", "INFO")
            time.sleep(0.3)
        except Exception as e:
            self.logger(f"Notice while pressing Enter on chat input: {e}", "WARNING")

        # Also check for send button/icon inside panel or near input
        try:
            root = panel if panel is not None else page
            send_selectors = [
                ".sendBtn", "button.send-btn", "button[class*='send']", ".send-icon",
                "button[aria-label*='Send' i]", "span[class*='send' i]", "svg[class*='send' i]",
                "div[class*='send' i]"
            ]
            for sel in send_selectors:
                loc = root.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    loc.first.click()
                    self.logger("📤 Clicked send button.", "INFO")
                    time.sleep(0.3)
                    break
        except Exception:
            pass

        return self.wait_for_transition(page, initial_question, timeout_sec)

    def wait_for_transition(self, page: Page, initial_question: str, timeout_sec: float = 6.0) -> Dict[str, Any]:
        """
        Waits condition-based for resulting chat UI state:
        Determines whether the question was accepted, the panel advanced to another question, or the panel closed.
        """
        start_time = time.time()
        while time.time() - start_time < timeout_sec:
            time.sleep(0.5)

            # Check 0: Did page transition to confirmation (saveApply, ACP, or toast)?
            is_conf, conf_reason = is_naukri_application_confirmed(page)
            if is_conf:
                return {"transition": "CONFIRMED", "reason": conf_reason}

            # Check 1: Did the panel close?
            panel = self.detect_chat_panel(page)
            if not panel or not panel.is_visible():
                return {"transition": "PANEL_CLOSED"}

            # Check 2: Did a success indicator appear?
            has_success = page.evaluate("""() => {
                const text = Array.from(document.querySelectorAll('.botMsg, .chatContent, div[class*="botMsg"], div[class*="chatMsg"], .bot-row, p.msg, div.apply-message, .success-title'))
                    .map(el => (el.innerText || '').toLowerCase())
                    .join(' ');
                return text.includes('application has been sent') || 
                       text.includes('applied successfully') || 
                       text.includes('application received') || 
                       text.includes('thank you for applying') ||
                       text.includes('applied on') ||
                       text.includes('applied to') ||
                       text.includes('already applied');
            }""")
            if has_success:
                return {"transition": "CONFIRMED"}

            # Check 3: Did a validation error appear?
            has_error = page.evaluate("""() => {
                const errEls = Array.from(document.querySelectorAll('.error, .alert-danger, .invalid-feedback, span[class*="error"]'))
                    .filter(e => e.offsetParent !== null && (e.innerText || '').trim().length > 0);
                return errEls.length > 0 ? errEls[0].innerText.trim() : null;
            }""")
            if has_error:
                return {"transition": "VALIDATION_ERROR", "error": has_error}

            # Check 4: Did a new question bubble appear?
            current_q = self.extract_latest_question(page, panel)
            if current_q and current_q.lower().strip() != initial_question.lower().strip():
                return {"transition": "NEXT_QUESTION", "question": current_q}

            # Check 5: Was input cleared and disabled or save button hidden?
            input_cleared = page.evaluate("""() => {
                const inp = document.querySelector('input[placeholder*="Type" i], textarea[placeholder*="Type" i], input.chat-input');
                return inp ? inp.value === '' : true;
            }""")
            if input_cleared and time.time() - start_time > 2.0:
                # Could be transitioning to next question or closing
                pass

        # Timeout reached while panel still open
        panel = self.detect_chat_panel(page)
        current_q = self.extract_latest_question(page, panel)
        return {
            "transition": "TIMEOUT",
            "current_question": current_q,
            "panel_open": panel is not None and panel.is_visible()
        }

    def process_sequential_chat_questions(
        self,
        page: Page,
        qa_engine_instance: QuestionAnsweringEngine,
        stop_event: threading.Event,
        company: str = "",
        title: str = "",
        max_rounds: int = 8
    ) -> Dict[str, Any]:
        """
        Executes the question-answer-save loop for the Naukri chat panel:
        1. Detects visible question panel.
        2. Extracts actual question displayed in chat bubble.
        3. Answers notice period, LWD, and screening questions accurately via candidate profile.
        4. Fills input field and verifies retention.
        5. Clicks Save and waits condition-based for state transition.
        6. Repeats for sequential questions with infinite-loop prevention.
        7. On unverified mandatory questions: marks NEEDS_USER_INPUT and keeps tab open.
        """
        processed_questions: List[str] = []
        consecutive_same_q = 0
        last_seen_q = ""

        for round_idx in range(1, max_rounds + 1):
            if stop_event and stop_event.is_set():
                return {"status": "STOP_REQUESTED", "success": False}

            panel = self.detect_chat_panel(page)
            if not panel or not panel.is_visible():
                self.logger("Chat panel not visible or closed.", "INFO")
                return {"status": ChatPanelState.FORM_COMPLETED, "success": True}

            # Extract the actual question from the chat bubble
            question = self.extract_latest_question(page, panel)
            if not question:
                # Check for quick-reply chips in panel
                chips_clicked = self._handle_quick_reply_chips(page, panel, stop_event)
                if chips_clicked:
                    time.sleep(1.5)
                    continue
                self.logger("No question bubble detected in visible chat panel.", "INFO")
                break

            self.logger(f"💬 Chat Question (Round {round_idx}): '{question}'", "INFO")
            update_reasoning_metric("question_detection_count", 1.0, f"Detected: {question[:30]}")

            # Infinite loop protection
            if question == last_seen_q:
                consecutive_same_q += 1
                if consecutive_same_q >= 3:
                    self.logger(f"Question repeated 3 times without advancing: '{question}'. Marking NEEDS_USER_INPUT.", "WARNING")
                    update_reasoning_metric("unresolved_questions_count", 1.0, question[:40])
                    return {
                        "status": ChatPanelState.NEEDS_USER_INPUT,
                        "reason": f"Repeated question not advancing: '{question}'",
                        "unanswered_question": question
                    }
            else:
                consecutive_same_q = 1
                last_seen_q = question

            # 1. Check for quick-reply chips / options in the panel first
            available_options = self.extract_chat_options(page, panel)

            # 2. Locate chat input / textarea
            chat_input = self.locate_chat_input(page, panel)
            input_type = "select" if available_options else "text"
            if chat_input:
                try:
                    input_type = chat_input.get_attribute("type") or "text"
                    if chat_input.evaluate("el => el.tagName.toLowerCase()") == "textarea":
                        input_type = "textarea"
                except Exception:
                    pass

            # 3. Generate verified answer from candidate profile, passing options if detected
            opt_payload = [{"text": o["text"], "value": o["value"]} for o in available_options] if available_options else None
            qa_res = qa_engine_instance.process_question(
                question_text=question,
                input_type=input_type,
                available_options=opt_payload,
                job_title=title,
                company_name=company
            )

            # Check if mandatory question requires candidate input
            if qa_res.get("needs_user_input"):
                self.logger(f"⚠️ [NEEDS_USER_INPUT] Screening question requires candidate input: '{question}' ({qa_res.get('reason')}). Tab kept OPEN in Chrome!", "WARNING")
                update_reasoning_metric("unresolved_questions_count", 1.0, question[:40])
                page.bring_to_front()
                return {
                    "status": ChatPanelState.NEEDS_USER_INPUT,
                    "reason": qa_res.get("reason", "NEEDS_USER_INPUT"),
                    "unanswered_question": question
                }

            answer = qa_res.get("answer", "")
            if not answer and not qa_res.get("selected_option"):
                self.logger(f"No answer generated for question: '{question}'. Marking NEEDS_USER_INPUT.", "WARNING")
                update_reasoning_metric("unresolved_questions_count", 1.0, question[:40])
                page.bring_to_front()
                return {
                    "status": ChatPanelState.NEEDS_USER_INPUT,
                    "reason": "EMPTY_ANSWER_GENERATED",
                    "unanswered_question": question
                }

            self.logger(f"💡 Generated Answer: '{answer}' (Source: {qa_res.get('source')})", "INFO")

            # 4. PATH A: If option chips/buttons are present, match and click
            option_clicked = False
            if available_options:
                matched_opt = None
                sel_opt = qa_res.get("selected_option")
                if sel_opt:
                    matched_opt = next((o for o in available_options if o["text"].strip().lower() == sel_opt["text"].strip().lower() or o["value"].strip().lower() == sel_opt.get("value", "").strip().lower()), None)
                if not matched_opt:
                    matched_opt = self._find_matching_option(available_options, answer, qa_res.get("category", ""))
                
                if matched_opt:
                    try:
                        opt_loc = matched_opt["locator"]
                        opt_loc.scroll_into_view_if_needed()
                        time.sleep(0.2)
                        opt_loc.click()
                        self.logger(f"✅ Option clicked: '{matched_opt['text']}' (Source: {qa_res.get('source')})", "SUCCESS")
                        option_clicked = True
                        time.sleep(0.5)

                        # Check if a Save button appeared/is enabled
                        save_btn = self.locate_save_button(page, panel)
                        if save_btn and save_btn.is_visible() and self._is_button_enabled(save_btn):
                            transition_res = self.click_save_and_wait_transition(page, save_btn, initial_question=question)
                        else:
                            transition_res = self.wait_for_transition(page, initial_question=question, timeout_sec=4.0)

                        t_type = transition_res.get("transition")
                        self.logger(f"UI Transition Result: {t_type}", "INFO")
                        processed_questions.append(question)

                        if t_type == "PANEL_CLOSED":
                            self.logger("🎉 Chat panel closed successfully after option selection.", "SUCCESS")
                            return {"status": ChatPanelState.FORM_COMPLETED, "success": True, "processed": processed_questions}
                        elif t_type == "CONFIRMED":
                            self.logger("🎉 Application confirmation detected inside chat panel!", "SUCCESS")
                            return {"status": ChatPanelState.APPLICATION_CONFIRMED, "success": True, "processed": processed_questions}
                        elif t_type in ["NEXT_QUESTION", "TIMEOUT"]:
                            continue
                    except Exception as opt_err:
                        self.logger(f"Notice while clicking option chip: {opt_err}", "WARNING")

            if option_clicked:
                continue

            # 5. PATH B: Fill Text Input
            if not chat_input or not chat_input.is_visible():
                # Attempt recovery: look for quick-reply chips matching answer
                chip_match = self._click_matching_chip(page, panel, answer)
                if chip_match:
                    time.sleep(1.5)
                    continue

                # Fallback: check general quick reply chips
                chip_recovered = self._handle_quick_reply_chips(page, panel, stop_event)
                if chip_recovered:
                    time.sleep(1.5)
                    continue

                self.logger("Chat input field not found or not visible.", "WARNING")
                record_experience("naukri.com", "chat_panel", "INPUT_NOT_FOUND", "locate_chat_input", "RECOVER_INPUT_LOCATOR", "FAILED", 0.3)
                page.bring_to_front()
                return {
                    "status": ChatPanelState.NEEDS_USER_INPUT,
                    "reason": "CHAT_INPUT_NOT_FOUND",
                    "unanswered_question": question
                }

            # Fill and verify the answer
            inserted = self.fill_and_verify_answer(page, chat_input, answer)
            if not inserted:
                self.logger(f"Failed to verify retention of answer: '{answer}' in chat input.", "WARNING")
                # Self-correction: retry with type
                try:
                    chat_input.click()
                    is_editable = False
                    try:
                        is_editable = chat_input.evaluate("el => !!el.isContentEditable")
                    except Exception:
                        pass
                    if is_editable:
                        chat_input.evaluate("el => { el.innerText = ''; el.textContent = ''; }")
                    else:
                        try:
                            chat_input.fill("")
                        except Exception:
                            pass
                    chat_input.type(answer, delay=25)
                    chat_input.dispatch_event("input")
                    chat_input.dispatch_event("change")
                    val = self._get_element_value(chat_input)
                    inserted = bool(val and (answer.lower() in val.lower() or val.strip() == answer.strip()))
                except Exception:
                    pass

                if not inserted:
                    update_reasoning_metric("answer_insertion_failure", 1.0, question[:30])
                    page.bring_to_front()
                    return {
                        "status": ChatPanelState.NEEDS_USER_INPUT,
                        "reason": "ANSWER_INSERTION_UNVERIFIED",
                        "unanswered_question": question
                    }

            self.logger(f"✅ Answer inserted and verified: '{answer}'", "SUCCESS")
            update_reasoning_metric("answer_insertion_success_count", 1.0, question[:30])

            # Check for Save button or submit directly via Enter/send icon
            save_btn = self.locate_save_button(page, panel)
            if save_btn and save_btn.is_visible() and self._is_button_enabled(save_btn):
                transition_res = self.click_save_and_wait_transition(page, save_btn, initial_question=question)
            else:
                self.logger("No Save button in chat panel. Submitting answer via Enter key / send icon...", "INFO")
                transition_res = self.submit_chat_input_and_wait_transition(page, chat_input, panel, initial_question=question)

            t_type = transition_res.get("transition")
            self.logger(f"UI Transition Result: {t_type}", "INFO")

            processed_questions.append(question)

            if t_type == "PANEL_CLOSED":
                self.logger("🎉 Chat panel closed successfully after saving answer.", "SUCCESS")
                record_experience("naukri.com", "chat_panel", "CHAT_QUESTION_ANSWERED", "FILL_AND_SAVE", "PANEL_CLOSED", "SUCCESS", 1.0)
                return {"status": ChatPanelState.FORM_COMPLETED, "success": True, "processed": processed_questions}

            elif t_type == "CONFIRMED":
                self.logger("🎉 Application confirmation detected inside chat panel!", "SUCCESS")
                record_experience("naukri.com", "chat_panel", "CHAT_APPLICATION_CONFIRMED", "FILL_AND_SAVE", "CONFIRMED", "SUCCESS", 1.0)
                return {"status": ChatPanelState.APPLICATION_CONFIRMED, "success": True, "processed": processed_questions}

            elif t_type == "NEXT_QUESTION":
                self.logger(f"Next screening question appeared: '{transition_res.get('question')}'. Continuing loop...", "INFO")
                time.sleep(1.0)
                continue

            elif t_type == "VALIDATION_ERROR":
                err = transition_res.get("error", "Validation error")
                self.logger(f"Validation error after clicking Save: {err}. Tab kept OPEN.", "WARNING")
                update_reasoning_metric("form_validation_failure", 1.0, err[:40])
                page.bring_to_front()
                return {
                    "status": ChatPanelState.NEEDS_USER_INPUT,
                    "reason": f"VALIDATION_ERROR: {err}",
                    "unanswered_question": question
                }

            elif t_type == "TIMEOUT":
                if transition_res.get("panel_open"):
                    self.logger(f"Panel still open after save for question: '{question}'. Tab kept OPEN in Chrome.", "WARNING")
                    page.bring_to_front()
                    return {
                        "status": ChatPanelState.CONFIRMATION_TIMEOUT,
                        "success": False,
                        "failure_reason": "CONFIRMATION_TIMEOUT",
                        "unanswered_question": question,
                        "open_form": True
                    }

        # Check final state after max rounds
        panel_end = self.detect_chat_panel(page)
        if panel_end and panel_end.is_visible():
            rem_q = self.extract_latest_question(page, panel_end)
            if rem_q:
                page.bring_to_front()
                return {
                    "status": ChatPanelState.NEEDS_USER_INPUT,
                    "reason": "MAX_ROUNDS_REACHED_PANEL_OPEN",
                    "unanswered_question": rem_q
                }

        return {"status": ChatPanelState.FORM_COMPLETED, "success": True, "processed": processed_questions}

    def _handle_quick_reply_chips(self, page: Page, panel: Optional[Locator], stop_event: threading.Event) -> bool:
        """Handles any quick-reply chips or option buttons visible in the chat panel."""
        try:
            chip_opts = self.extract_chat_options(page, panel)
            for opt in chip_opts:
                txt = opt["text"].strip().lower()
                chip = opt["locator"]

                # Location / Relocate Chips (Mumbai / Kurla)
                if any(k in txt for k in ['currently residing in mumbai', 'residing in mumbai', 'reside in mumbai', 'mumbai', 'kurla', 'willing to relocate', 'open to relocate', 'relocate', 'remote']):
                    self.logger(f"Clicked Location chip: '{opt['text']}'", "INFO")
                    chip.click()
                    return True
                # Tech Skills Chips (Node.js / React.js)
                elif any(k in txt for k in ['node.js', 'node js', 'nodejs', 'react.js', 'react js', 'react', 'mern', 'typescript', 'javascript', 'express', 'mongodb', 'mysql', 'postgresql']):
                    self.logger(f"Clicked Tech Skill chip: '{opt['text']}'", "INFO")
                    chip.click()
                    return True
                # Notice Period Chips (Prioritize Immediate Joiner)
                elif any(k in txt for k in ['immediate', '0-15', '15 day', 'less than 15', 'serving', '15', '30 day', '1 month', '30', '0']):
                    self.logger(f"Clicked Notice Period chip: '{opt['text']}'", "INFO")
                    chip.click()
                    return True
                # Experience Chips (5+ years)
                elif any(k in txt for k in ['5+ year', '5+ years', '5 years', '5 year', '5-7', '4-6', '5+', '5']):
                    self.logger(f"Clicked Experience chip: '{opt['text']}'", "INFO")
                    chip.click()
                    return True
                # Affirmative / Yes
                elif any(txt.startswith(y) or txt == y for y in ['yes', 'agree', 'confirm', 'comfortable', 'available', 'i agree', 'residing', 'willing']):
                    self.logger(f"Clicked Affirmative chip: '{opt['text']}'", "INFO")
                    chip.click()
                    return True
        except Exception:
            pass
        return False

    def _click_matching_chip(self, page: Page, panel: Optional[Locator], answer: str) -> bool:
        """Attempts to match answer to an available chip button."""
        try:
            chip_opts = self.extract_chat_options(page, panel)
            matched = self._find_matching_option(chip_opts, answer)
            if matched:
                matched["locator"].scroll_into_view_if_needed()
                time.sleep(0.2)
                matched["locator"].click()
                self.logger(f"Matched and clicked option chip: '{matched['text']}'", "INFO")
                return True
        except Exception:
            pass
        return False

naukri_chat_panel_handler = NaukriChatPanelHandler()
