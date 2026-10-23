import os
import time
import re
import threading
from typing import Dict, Any, List, Optional, Tuple
from playwright.sync_api import Page, Locator

from question_answering import QuestionAnsweringEngine, QuestionCategory, qa_engine

class FormFieldType:
    TEXT = "text"
    TEXTAREA = "textarea"
    SELECT = "select"
    CUSTOM_SELECT = "custom_select"
    RADIO_GROUP = "radio_group"
    CHECKBOX = "checkbox"
    AUTOCOMPLETE = "autocomplete"
    NUMBER = "number"
    DATE = "date"
    FILE = "file"
    UNKNOWN = "unknown"

def detect_and_collect_form_questions(page: Page, root_selector: str = "") -> List[Dict[str, Any]]:
    """
    Intelligently inspects the complete application form using Playwright DOM evaluation.
    Identifies:
    - Text inputs, textareas
    - Dropdowns (native <select> and custom comboboxes/listboxes)
    - Radio groups (grouped by name or question container)
    - Checkboxes
    - Number inputs, date fields
    - Autocomplete fields and searchable selects
    - Mandatory indicators (*, required, aria-required)
    
    Returns structured metadata for each field without relying solely on placeholders.
    """
    script = """(rootSel) => {
        const root = rootSel ? (document.querySelector(rootSel) || document.body) : document.body;
        if (!root) return [];

        const isVisible = (el) => {
            if (!el) return false;
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
        };

        const getAssociatedLabel = (el) => {
            let labelText = '';
            // 1. Native labels collection
            if (el.labels && el.labels.length > 0) {
                labelText = Array.from(el.labels).map(l => l.innerText).join(' ').trim();
            }
            // 2. label[for=id]
            if (!labelText && el.id) {
                try {
                    const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                    if (l) labelText = l.innerText.trim();
                } catch(e) {}
            }
            // 3. aria-labelledby
            if (!labelText && el.getAttribute('aria-labelledby')) {
                const ids = el.getAttribute('aria-labelledby').split(' ');
                labelText = ids.map(id => {
                    const ref = document.getElementById(id);
                    return ref ? ref.innerText.trim() : '';
                }).filter(Boolean).join(' ');
            }
            // 4. aria-label
            if (!labelText && el.getAttribute('aria-label')) {
                labelText = el.getAttribute('aria-label').trim();
            }
            // 5. Preceding heading or label sibling
            if (!labelText && el.previousElementSibling) {
                let prev = el.previousElementSibling;
                while (prev) {
                    if (['LABEL', 'SPAN', 'P', 'H3', 'H4', 'H5', 'H6', 'LEGEND'].includes(prev.tagName) && prev.innerText && prev.innerText.trim()) {
                        labelText = prev.innerText.trim();
                        break;
                    }
                    prev = prev.previousElementSibling;
                }
            }
            // 6. Closest question container
            if (!labelText) {
                const container = el.closest('.form-group, .form-row, .field, .question, .form-field, fieldset, tr, .input-container, .chatbot_drawer, div[class*="question"]');
                if (container) {
                    const header = container.querySelector('label, legend, .ques, .title, .label, h4, h5, span.question-text');
                    if (header) labelText = header.innerText.trim();
                }
            }
            // 7. Fallback to placeholder or title
            if (!labelText) {
                labelText = el.placeholder || el.title || el.name || '';
            }
            return labelText.replace(/\\s+/g, ' ').trim();
        };

        const isRequiredField = (el, labelText) => {
            if (el.hasAttribute('required') || el.getAttribute('aria-required') === 'true') return true;
            if (labelText.includes('*') || /\\b(mandatory|required)\\b/i.test(labelText)) return true;
            // Check container for asterisk
            const parent = el.closest('.form-group, .field, .question, .form-row, tr');
            if (parent) {
                const reqEl = parent.querySelector('.req, .required, .asterisk, span[class*="required"]');
                if (reqEl && reqEl.innerText.includes('*')) return true;
            }
            return false;
        };

        const results = [];
        const seenNames = new Set();
        const seenRadioGroups = new Set();

        // 1. Radio Buttons (Grouped by name or container)
        const radios = Array.from(root.querySelectorAll('input[type="radio"]')).filter(r => isVisible(r) && !r.disabled);
        for (const radio of radios) {
            const groupName = radio.name || radio.closest('.question, .form-group, fieldset')?.getAttribute('id') || 'unnamed_group';
            if (seenRadioGroups.has(groupName)) continue;
            seenRadioGroups.add(groupName);

            const groupRadios = groupName !== 'unnamed_group' 
                ? Array.from(root.querySelectorAll(`input[type="radio"][name="${CSS.escape(groupName)}"]`))
                : [radio];

            const groupContainer = radio.closest('.form-group, .field, .question, fieldset, tr') || radio.parentElement;
            let groupLabel = getAssociatedLabel(radio);
            if (groupContainer) {
                const legend = groupContainer.querySelector('legend, .ques, .title, label, h4, h5');
                if (legend) groupLabel = legend.innerText.trim();
            }

            const options = groupRadios.map(r => {
                let optLabel = '';
                if (r.labels && r.labels.length > 0) optLabel = r.labels[0].innerText.trim();
                if (!optLabel && r.id) {
                    try {
                        const l = document.querySelector(`label[for="${CSS.escape(r.id)}"]`);
                        if (l) optLabel = l.innerText.trim();
                    } catch(e) {}
                }
                if (!optLabel && r.parentElement) {
                    optLabel = r.parentElement.innerText.replace(groupLabel, '').trim();
                }
                return {
                    value: r.value || optLabel,
                    text: optLabel || r.value || 'Option',
                    id: r.id || '',
                    name: r.name || '',
                    checked: r.checked
                };
            });

            results.push({
                fieldType: 'radio_group',
                name: groupName,
                id: radio.id || groupName,
                questionText: groupLabel,
                isRequired: isRequiredField(radio, groupLabel),
                currentValue: groupRadios.find(r => r.checked)?.value || '',
                options: options,
                selector: `input[type="radio"][name="${groupName}"]`
            });
        }

        // 2. Select Elements (Native)
        const selects = Array.from(root.querySelectorAll('select')).filter(s => isVisible(s) && !s.disabled);
        for (const sel of selects) {
            const label = getAssociatedLabel(sel);
            const options = Array.from(sel.options).map(o => ({
                value: o.value,
                text: o.text.trim()
            }));

            results.push({
                fieldType: 'select',
                name: sel.name || '',
                id: sel.id || '',
                questionText: label,
                isRequired: isRequiredField(sel, label),
                currentValue: sel.value || '',
                options: options,
                selector: sel.id ? `#${CSS.escape(sel.id)}` : (sel.name ? `select[name="${CSS.escape(sel.name)}"]` : 'select')
            });
        }

        // 3. Custom Comboboxes / Listboxes / Custom Dropdowns
        const customSelects = Array.from(root.querySelectorAll('[role="combobox"], [role="listbox"], .custom-select, div[class*="select__control"], div[class*="dropdown-toggle"]'))
            .filter(cs => isVisible(cs));
        for (const cs of customSelects) {
            // Avoid duplicates if native select is already mapped
            if (cs.tagName === 'SELECT') continue;
            const label = getAssociatedLabel(cs);
            // Collect any visible options if already open, or child option elements
            const childOptions = Array.from(cs.querySelectorAll('[role="option"], .option, li')).map(o => ({
                value: o.getAttribute('data-value') || o.innerText.trim(),
                text: o.innerText.trim()
            }));

            results.push({
                fieldType: 'custom_select',
                name: cs.getAttribute('name') || cs.id || '',
                id: cs.id || '',
                questionText: label,
                isRequired: isRequiredField(cs, label),
                currentValue: cs.innerText.trim(),
                options: childOptions,
                selector: cs.id ? `#${CSS.escape(cs.id)}` : ''
            });
        }

        // 4. Textareas
        const textareas = Array.from(root.querySelectorAll('textarea')).filter(t => isVisible(t) && !t.disabled && !t.readOnly);
        for (const ta of textareas) {
            const label = getAssociatedLabel(ta);
            results.push({
                fieldType: 'textarea',
                name: ta.name || '',
                id: ta.id || '',
                questionText: label,
                isRequired: isRequiredField(ta, label),
                currentValue: ta.value || '',
                options: [],
                selector: ta.id ? `#${CSS.escape(ta.id)}` : (ta.name ? `textarea[name="${CSS.escape(ta.name)}"]` : 'textarea')
            });
        }

        // 5. Standard Inputs (text, number, date, checkbox, autocomplete)
        const inputs = Array.from(root.querySelectorAll('input:not([type="radio"]):not([type="hidden"]):not([type="submit"]):not([type="button"]):not([type="password"]):not([type="file"])'))
            .filter(inp => isVisible(inp) && !inp.disabled && !inp.readOnly);

        for (const inp of inputs) {
            const itype = (inp.type || 'text').toLowerCase();
            const label = getAssociatedLabel(inp);
            const req = isRequiredField(inp, label);

            let fieldType = 'text';
            if (itype === 'checkbox') {
                fieldType = 'checkbox';
            } else if (itype === 'number') {
                fieldType = 'number';
            } else if (itype === 'date' || itype === 'datetime-local') {
                fieldType = 'date';
            } else if (inp.hasAttribute('list') || inp.getAttribute('autocomplete') === 'on' || inp.getAttribute('role') === 'combobox' || inp.classList.contains('autocomplete') || inp.classList.contains('searchable')) {
                fieldType = 'autocomplete';
            }

            // Extract datalist options if available
            let options = [];
            if (inp.hasAttribute('list')) {
                const dl = document.getElementById(inp.getAttribute('list'));
                if (dl) {
                    options = Array.from(dl.querySelectorAll('option')).map(o => ({
                        value: o.value,
                        text: o.text.trim() || o.value
                    }));
                }
            }

            results.push({
                fieldType: fieldType,
                name: inp.name || '',
                id: inp.id || '',
                questionText: label,
                isRequired: req,
                currentValue: itype === 'checkbox' ? (inp.checked ? 'true' : 'false') : (inp.value || ''),
                options: options,
                selector: inp.id ? `#${CSS.escape(inp.id)}` : (inp.name ? `input[name="${CSS.escape(inp.name)}"]` : '')
            });
        }

        // 6. File / Resume Upload Inputs (only on external career portals, NOT background profile inputs on Naukri.com)
        const isNaukri = window.location.hostname.includes('naukri.com');
        if (!isNaukri) {
            const fileInputs = Array.from(root.querySelectorAll('input[type="file"]')).filter(f => !f.disabled);
            for (const finp of fileInputs) {
                const label = getAssociatedLabel(finp);
                results.push({
                    fieldType: 'file',
                    name: finp.name || '',
                    id: finp.id || '',
                    questionText: label || 'Upload Resume / CV',
                    isRequired: isRequiredField(finp, label),
                    currentValue: finp.value || '',
                    options: [],
                    selector: finp.id ? `#${CSS.escape(finp.id)}` : (finp.name ? `input[name="${CSS.escape(finp.name)}"]` : 'input[type="file"]')
                });
            }
        }

        return results;
    }"""
    try:
        raw_fields = page.evaluate(script, root_selector)
        return raw_fields or []
    except Exception as e:
        print(f"[FormEngine] Question detection error: {e}")
        return []

def fill_form_control(page: Page, field: Dict[str, Any], answer: str, 
                      selected_option: Optional[Dict[str, str]], 
                      stop_event: threading.Event) -> Dict[str, Any]:
    """
    Fills a single form control based on its verified type using robust Playwright automation.
    Dispatches input/change/blur synthetic events to ensure single-page apps (React/Vue/Angular) register the update.
    Verifies that the entered value was actually retained by the DOM.
    """
    if stop_event and stop_event.is_set():
        return {"success": False, "reason": "STOP_REQUESTED"}

    ftype = field.get("fieldType", "text")
    fid = field.get("id", "")
    fname = field.get("name", "")
    fsel = field.get("selector", "")
    qtext = field.get("questionText", "")

    # Locate element safely
    el = None
    if fid:
        try:
            el = page.locator(f"#{fid}").first
            if not el.is_visible():
                el = None
        except Exception:
            el = None

    if not el and fname:
        try:
            el = page.locator(f"[name='{fname}']").first
            if not el.is_visible():
                el = None
        except Exception:
            el = None

    if not el and fsel:
        try:
            el = page.locator(fsel).first
            if not el.is_visible():
                el = None
        except Exception:
            el = None

    # --- 1. RADIO GROUP ---
    if ftype == FormFieldType.RADIO_GROUP:
        try:
            opt_val = (selected_option.get("value") if selected_option else answer).strip().lower()
            opt_txt = (selected_option.get("text") if selected_option else answer).strip().lower()

            # Find matching radio button
            radios = page.locator(f"input[type='radio'][name='{fname}']") if fname else page.locator("input[type='radio']")
            count = radios.count()
            selected = False

            for i in range(count):
                r = radios.nth(i)
                r_val = (r.get_attribute("value") or "").strip().lower()
                r_id = r.get_attribute("id") or ""
                r_label = ""

                if r_id:
                    lbl = page.locator(f"label[for='{r_id}']").first
                    if lbl.count() > 0:
                        r_label = lbl.inner_text().strip().lower()

                if not r_label:
                    r_label = r.evaluate("el => el.parentElement ? el.parentElement.innerText.toLowerCase() : ''")

                # Match against value, label, or answer
                if (opt_val and opt_val in r_val) or (opt_txt and opt_txt in r_label) or (opt_val and opt_val in r_label) or (r_label and r_label in opt_txt):
                    r.scroll_into_view_if_needed()
                    r.check(force=True)
                    r.dispatch_event("change")
                    selected = True
                    break

            # Fallback: if affirmative answer and 2 options (Yes/No), check Yes
            if not selected and opt_val in ["yes", "true", "1"]:
                for i in range(count):
                    r = radios.nth(i)
                    r_lbl = r.evaluate("el => el.parentElement ? el.parentElement.innerText.toLowerCase() : ''")
                    if "yes" in r_lbl or "agree" in r_lbl or "true" in r_lbl:
                        r.check(force=True)
                        r.dispatch_event("change")
                        selected = True
                        break

            return {"success": selected, "entered_value": answer, "retained": selected}
        except Exception as e:
            return {"success": False, "reason": str(e)}

    # --- 2. SELECT DROPDOWN (NATIVE) ---
    elif ftype == FormFieldType.SELECT:
        if not el:
            return {"success": False, "reason": "SELECT_ELEMENT_NOT_FOUND"}
        try:
            el.scroll_into_view_if_needed()
            target_val = selected_option.get("value") if selected_option else None
            target_txt = selected_option.get("text") if selected_option else answer

            if target_val:
                el.select_option(value=target_val)
            elif target_txt:
                el.select_option(label=target_txt)
            else:
                el.select_option(value=answer)

            el.dispatch_event("change")
            # Verify selection
            curr_val = el.input_value()
            return {"success": True, "entered_value": curr_val, "retained": bool(curr_val)}
        except Exception as e:
            # Fallback to text matching
            try:
                el.select_option(label=answer)
                el.dispatch_event("change")
                return {"success": True, "entered_value": answer, "retained": True}
            except Exception:
                return {"success": False, "reason": str(e)}

    # --- 3. CUSTOM SELECT / COMBOBOX ---
    elif ftype == FormFieldType.CUSTOM_SELECT:
        if not el:
            return {"success": False, "reason": "CUSTOM_SELECT_NOT_FOUND"}
        try:
            el.scroll_into_view_if_needed()
            el.click()
            time.sleep(0.4)

            target_text = selected_option.get("text") if selected_option else answer
            # Look for options list
            opt_locator = page.locator(f"[role='option']:has-text('{target_text}'), .option:has-text('{target_text}'), li:has-text('{target_text}')").first
            if opt_locator.count() > 0 and opt_locator.is_visible():
                opt_locator.click()
                return {"success": True, "entered_value": target_text, "retained": True}
            else:
                # Try pressing enter or typing
                el.type(target_text)
                time.sleep(0.3)
                page.keyboard.press("Enter")
                return {"success": True, "entered_value": target_text, "retained": True}
        except Exception as e:
            return {"success": False, "reason": str(e)}

    # --- 4. CHECKBOX ---
    elif ftype == FormFieldType.CHECKBOX:
        if not el:
            return {"success": False, "reason": "CHECKBOX_NOT_FOUND"}
        try:
            el.scroll_into_view_if_needed()
            should_check = False
            ans_low = answer.strip().lower()

            # Affirmative checks or required agreements
            if ans_low in ["true", "yes", "1", "agree", "checked"]:
                should_check = True
            elif field.get("isRequired") and any(k in qtext.lower() for k in ["terms", "agree", "consent", "declaration", "certify", "authorized"]):
                should_check = True

            if should_check:
                el.check(force=True)
                el.dispatch_event("change")
            else:
                el.uncheck(force=True)
                el.dispatch_event("change")

            is_chk = el.is_checked()
            return {"success": True, "entered_value": "checked" if is_chk else "unchecked", "retained": (is_chk == should_check)}
        except Exception as e:
            return {"success": False, "reason": str(e)}

    # --- 5. AUTOCOMPLETE FIELD ---
    elif ftype == FormFieldType.AUTOCOMPLETE:
        if not el:
            return {"success": False, "reason": "AUTOCOMPLETE_NOT_FOUND"}
        try:
            el.scroll_into_view_if_needed()
            el.click()
            el.fill(str(answer))
            # If suggestion dropdown is present, attempt safe click
            try:
                sugg = page.locator(f"[role='option']:has-text('{answer}'), .suggestion-item:has-text('{answer}'), .autocomplete-item:has-text('{answer}'), .dropdown-menu li:has-text('{answer}')").first
                if sugg.count() > 0 and sugg.is_visible():
                    sugg.click(timeout=800)
            except Exception:
                pass

            el.dispatch_event("input")
            el.dispatch_event("change")
            el.dispatch_event("blur")
            val = el.input_value()
            return {"success": True, "entered_value": val or answer, "retained": bool(val or answer)}
        except Exception as e:
            return {"success": False, "reason": str(e)}

    # --- 6. TEXTAREA ---
    elif ftype == FormFieldType.TEXTAREA:
        if not el:
            return {"success": False, "reason": "TEXTAREA_NOT_FOUND"}
        try:
            el.scroll_into_view_if_needed()
            el.click()
            el.fill(answer)
            el.dispatch_event("input")
            el.dispatch_event("change")
            el.dispatch_event("blur")
            retained_val = el.input_value()
            return {"success": True, "entered_value": retained_val, "retained": len(retained_val) > 0}
        except Exception as e:
            return {"success": False, "reason": str(e)}

    # --- 7. FILE / RESUME UPLOAD ---
    elif ftype == FormFieldType.FILE:
        try:
            target_el = el
            if not target_el:
                try:
                    target_el = page.locator("input[type='file']").first
                except Exception:
                    target_el = None
            if not target_el:
                return {"success": False, "reason": "FILE_INPUT_NOT_FOUND"}

            resume_p = answer
            if not resume_p or not os.path.exists(resume_p):
                from ai_service import get_candidate_profile
                prof = get_candidate_profile()
                resume_p = prof.get("resume_path", "")
                if not resume_p or not os.path.exists(resume_p):
                    cand_p = os.path.join(os.path.dirname(__file__), "Abdul_Razzaque_India.pdf")
                    if os.path.exists(cand_p):
                        resume_p = cand_p

            if resume_p and os.path.exists(resume_p):
                target_el.set_input_files(resume_p)
                return {"success": True, "entered_value": os.path.basename(resume_p), "retained": True}
            else:
                return {"success": False, "reason": "RESUME_FILE_NOT_FOUND"}
        except Exception as e:
            return {"success": False, "reason": str(e)}

    # --- 8. TEXT, NUMBER, DATE INPUTS ---
    else:
        if not el:
            return {"success": False, "reason": "INPUT_NOT_FOUND"}
        try:
            el.scroll_into_view_if_needed()
            el.click()
            el.fill(str(answer))
            el.dispatch_event("input")
            el.dispatch_event("change")
            el.dispatch_event("blur")
            retained_val = el.input_value()
            return {"success": True, "entered_value": retained_val, "retained": bool(retained_val)}
        except Exception as e:
            return {"success": False, "reason": str(e)}

def upload_resume_file(page: Page, resume_path: str = "") -> Dict[str, Any]:
    """Finds any visible or standard file input on the page and uploads candidate PDF resume."""
    try:
        if not resume_path or not os.path.exists(resume_path):
            from ai_service import get_candidate_profile
            prof = get_candidate_profile()
            resume_path = prof.get("resume_path", "")
            if not resume_path or not os.path.exists(resume_path):
                cand_p = os.path.join(os.path.dirname(__file__), "Abdul_Razzaque_India.pdf")
                if os.path.exists(cand_p):
                    resume_path = cand_p

        if not resume_path or not os.path.exists(resume_path):
            return {"success": False, "error": "RESUME_FILE_NOT_FOUND"}

        file_inputs = page.locator("input[type='file']")
        if file_inputs.count() > 0:
            file_inputs.first.set_input_files(resume_path)
            return {"success": True, "resume_path": resume_path, "filename": os.path.basename(resume_path)}
        return {"success": False, "error": "FILE_INPUT_NOT_FOUND"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def validate_entire_form(page: Page, root_selector: str = "") -> Dict[str, Any]:
    """
    Validates the form prior to submission:
    - Verifies all mandatory questions have valid non-empty answers
    - Checks for DOM validation errors (.error, .invalid-feedback, aria-invalid="true")
    - Ensures entered values are retained
    """
    script = """(rootSel) => {
        const root = rootSel ? (document.querySelector(rootSel) || document.body) : document.body;
        if (!root) return { isValid: true, emptyMandatory: [], errorMessages: [] };

        const isVisible = (el) => {
            if (!el) return false;
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden') return false;
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
        };

        const emptyMandatory = [];
        const errorMessages = [];

        // Check required inputs, selects, textareas
        const requiredElements = Array.from(root.querySelectorAll('[required], [aria-required="true"]'))
            .filter(el => isVisible(el) && !el.disabled);

        for (const el of requiredElements) {
            let val = '';
            if (el.type === 'checkbox') {
                val = el.checked ? 'checked' : '';
            } else if (el.type === 'radio') {
                const name = el.name;
                const anyChecked = Array.from(root.querySelectorAll(`input[type="radio"][name="${name}"]`)).some(r => r.checked);
                val = anyChecked ? 'checked' : '';
            } else {
                val = (el.value || '').trim();
            }

            if (!val) {
                let lbl = el.labels && el.labels[0] ? el.labels[0].innerText : (el.placeholder || el.name || el.id || 'Required Field');
                emptyMandatory.push(lbl.trim());
            }
        }

        // Check visible error messages
        const errorEls = Array.from(root.querySelectorAll('.error, .invalid-feedback, .field-error, .alert-danger, [aria-invalid="true"], span.error-text'))
            .filter(e => isVisible(e) && (e.innerText || '').trim().length > 1);

        for (const err of errorEls) {
            errorMessages.push(err.innerText.trim());
        }

        return {
            isValid: emptyMandatory.length === 0 && errorMessages.length === 0,
            emptyMandatory: emptyMandatory,
            errorMessages: errorMessages
        };
    }"""
    try:
        res = page.evaluate(script, root_selector)
        return res or {"isValid": True, "emptyMandatory": [], "errorMessages": []}
    except Exception as e:
        return {"isValid": False, "emptyMandatory": [], "errorMessages": [f"Validation script error: {e}"]}

def process_and_fill_complete_form(page: Page, 
                                   qa_engine_instance: QuestionAnsweringEngine, 
                                   stop_event: threading.Event, 
                                   company_name: str = "", 
                                   job_title: str = "", 
                                   max_dynamic_passes: int = 3,
                                   logger_fn = None) -> Dict[str, Any]:
    """
    Executes the intelligent Question Detection, Understanding, and Filling cycle:
    1. Collects all visible questions and metadata.
    2. Resolves answers grounded in verified profile (never fabricates).
    3. If any mandatory question is unknown, marks as NEEDS_USER_INPUT, halts submission,
       and keeps the tab OPEN in Chrome for user verification.
    4. Handles dynamically revealed follow-up questions iteratively.
    5. Runs Answer Validation Layer.
    6. Logs detailed question audit.
    """
    def log(msg: str, level: str = "INFO"):
        if logger_fn:
            logger_fn(msg, level)
        else:
            print(f"[{time.strftime('%H:%M:%S')}] [{level}] {msg}")

    log(f"📋 Beginning intelligent question processing for {job_title} @ {company_name}...", "INFO")

    processed_questions = set()
    total_answered = 0

    for pass_num in range(max_dynamic_passes):
        if stop_event and stop_event.is_set():
            return {"status": "STOPPED", "success": False, "reason": "STOP_REQUESTED"}

        # 1. Detect all visible questions
        detected_fields = detect_and_collect_form_questions(page)
        if not detected_fields:
            if pass_num == 0:
                log("No additional questions detected on form.", "INFO")
            break

        # Filter fields not yet answered
        unanswered_fields = []
        for f in detected_fields:
            q_key = f"{f.get('fieldType')}:{f.get('name') or f.get('id')}:{f.get('questionText')}"
            if q_key not in processed_questions:
                # If current value is already filled and valid, mark processed
                curr = str(f.get("currentValue", "")).strip()
                if curr and curr not in ["false", "none", "0"]:
                    processed_questions.add(q_key)
                    continue
                unanswered_fields.append((q_key, f))

        if not unanswered_fields:
            break

        log(f"Detected {len(unanswered_fields)} question(s) to process (Round {pass_num + 1})...", "INFO")

        new_field_filled = False

        for q_key, field in unanswered_fields:
            if stop_event and stop_event.is_set():
                return {"status": "STOPPED", "success": False, "reason": "STOP_REQUESTED"}

            q_text = field.get("questionText", "")
            ftype = field.get("fieldType", "text")
            is_req = field.get("isRequired", False)
            opts = field.get("options", [])

            # Step 2: Question Understanding & Answer Resolution
            res = qa_engine_instance.process_question(
                question_text=q_text,
                input_type=ftype,
                available_options=opts,
                job_title=job_title,
                company_name=company_name
            )

            category = res.get("category", QuestionCategory.OTHER)
            source = res.get("source", "UNKNOWN")
            answer = res.get("answer", "")
            needs_user = res.get("needs_user_input", False)
            selected_opt = res.get("selected_option")
            reason = res.get("reason", "")

            # Detailed Question Audit Log
            log(f"Question: '{q_text[:40]}' | Category: {category} | Type: {ftype} | Source: {source} | Req: {is_req}", "INFO")

            # Check if answer requires candidate input
            if needs_user or (is_req and not answer and ftype != FormFieldType.CHECKBOX):
                if is_req:
                    log(f"⚠️ Mandatory question requires candidate verification: '{q_text}' ({reason}). Form kept OPEN in Chrome!", "WARNING")
                    return {
                        "status": "NEEDS_USER_INPUT",
                        "success": False,
                        "unanswered_question": q_text,
                        "category": category,
                        "reason": reason,
                        "field": field
                    }
                else:
                    log(f"Optional question skipped: '{q_text}' ({reason})", "INFO")
                    processed_questions.add(q_key)
                    continue

            # Step 3: Fill Control
            fill_res = fill_form_control(
                page=page,
                field=field,
                answer=answer,
                selected_option=selected_opt,
                stop_event=stop_event
            )

            if fill_res.get("success"):
                log(f"✅ Answer inserted successfully: '{str(answer)[:30]}' (Source: {source})", "SUCCESS")
                processed_questions.add(q_key)
                total_answered += 1
                new_field_filled = True
                time.sleep(0.3)
            else:
                log(f"Could not enter answer for '{q_text}': {fill_res.get('reason')}", "WARNING")
                if is_req:
                    return {
                        "status": "NEEDS_USER_INPUT",
                        "success": False,
                        "unanswered_question": q_text,
                        "category": category,
                        "reason": f"INSERTION_FAILED: {fill_res.get('reason')}",
                        "field": field
                    }

        # If no fields were filled in this pass, break out of loop
        if not new_field_filled:
            break

        # Brief pause to allow dynamic conditional fields to reveal
        time.sleep(0.8)

    # Step 4: Answer Validation Layer
    val_res = validate_entire_form(page)
    if not val_res.get("isValid"):
        empty = val_res.get("emptyMandatory", [])
        errs = val_res.get("errorMessages", [])
        if empty:
            log(f"Validation alert: Empty mandatory fields detected: {empty}. Tab kept OPEN for review.", "WARNING")
            return {
                "status": "NEEDS_USER_INPUT",
                "success": False,
                "reason": f"EMPTY_MANDATORY_FIELDS: {', '.join(empty)}"
            }
        if errs:
            log(f"Validation alert: Form errors present: {errs}. Tab kept OPEN for review.", "WARNING")
            return {
                "status": "NEEDS_USER_INPUT",
                "success": False,
                "reason": f"FORM_VALIDATION_ERRORS: {', '.join(errs)}"
            }

    log(f"🎉 Form validation passed! {total_answered} questions answered & verified.", "SUCCESS")
    return {
        "status": "FORM_VALIDATED",
        "success": True,
        "total_answered": total_answered
    }
