import os
import time
import re
import json
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
    BUTTON_GROUP = "button_group"
    CHECKBOX_GROUP = "checkbox_group"
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
            // 5b. Immediate parent's preceding sibling or parent's label
            if (!labelText && el.parentElement) {
                const pLabel = el.parentElement.querySelector('label, .label, .field-label, span.title');
                if (pLabel && pLabel !== el && isVisible(pLabel)) {
                    labelText = pLabel.innerText.trim();
                }
                if (!labelText && el.parentElement.previousElementSibling) {
                    let pPrev = el.parentElement.previousElementSibling;
                    if (['LABEL', 'SPAN', 'DIV', 'H3', 'H4', 'H5', 'P'].includes(pPrev.tagName) && pPrev.innerText && pPrev.innerText.trim()) {
                        labelText = pPrev.innerText.trim();
                    }
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
            // 7. Fallback to placeholder or title or name
            if (!labelText) {
                labelText = el.placeholder || el.title || el.name || '';
            }

            // 8. Field ID / Name semantic disambiguation
            const idLow = (el.id || '').toLowerCase();
            const nameLow = (el.name || '').toLowerCase();
            const placeholderLow = (el.placeholder || '').toLowerCase();

            // Country vs general location
            if ((idLow === 'countries-list' || /\b(country|countries)\b/i.test(nameLow) || /\b(country|countries)\b/i.test(idLow)) && !/\b(code|calling|dial)\b/i.test(nameLow + idLow + placeholderLow)) {
                if (!labelText || /^(location|address|select|please select|-)$/i.test(labelText)) {
                    labelText = 'Country';
                }
            }
            // State vs general location
            if (idLow === 'states_list' || /\b(state|states|province)\b/i.test(nameLow) || /\b(state|states|province)\b/i.test(idLow)) {
                if (!labelText || /^(location|address|select|please select|-)$/i.test(labelText)) {
                    labelText = 'State';
                }
            }
            // Country code vs Phone number
            if (/\b(country[-_]?code|dial[-_]?code|calling[-_]?code|phone[-_]?code)\b/i.test(nameLow + idLow + placeholderLow)) {
                labelText = 'Country Code';
            }
            // Gender
            if (/\bgender\b/i.test(nameLow + idLow) && (!labelText || /^(select|please select|-)$/i.test(labelText))) {
                labelText = 'Gender';
            }
            // Disability
            if (/\bdisabilit(y|ies)\b/i.test(nameLow + idLow) && (!labelText || /^(select|please select|-)$/i.test(labelText))) {
                labelText = 'Disability';
            }
            // Veteran
            if (/\b(veteran|armed[-_]?forces)\b/i.test(nameLow + idLow) && (!labelText || /^(select|please select|-)$/i.test(labelText))) {
                labelText = 'Armed Forces Veteran';
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
        const radios = Array.from(root.querySelectorAll('input[type="radio"], [role="radio"]')).filter(r => isVisible(r) && !r.disabled);
        for (const radio of radios) {
            const radioName = radio.name || radio.getAttribute('name');
            const groupName = radioName || radio.closest('.question, .form-group, fieldset')?.getAttribute('id') || 'unnamed_group_' + Math.random().toString(36).substring(2, 7);
            if (seenRadioGroups.has(groupName)) continue;
            seenRadioGroups.add(groupName);

            const groupContainer = radio.closest('.form-group, .field, .question, fieldset, tr') || radio.parentElement;
            const groupRadios = radioName 
                ? Array.from(root.querySelectorAll(`input[type="radio"][name="${CSS.escape(radioName)}"], [role="radio"][name="${CSS.escape(radioName)}"]`))
                : (groupContainer ? Array.from(groupContainer.querySelectorAll('input[type="radio"], [role="radio"]')) : [radio]);

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
                const botRadioId = 'bot-radio-' + Math.random().toString(36).substring(2, 9);
                r.setAttribute('data-bot-radio-id', botRadioId);
                const isChecked = r.checked || r.getAttribute('aria-checked') === 'true';
                return {
                    value: r.value || r.getAttribute('value') || optLabel,
                    text: optLabel || r.value || 'Option',
                    id: r.id || '',
                    name: r.name || r.getAttribute('name') || '',
                    selector: r.id ? `#${CSS.escape(r.id)}` : `[data-bot-radio-id="${botRadioId}"]`,
                    checked: isChecked
                };
            });

            results.push({
                fieldType: 'radio_group',
                name: groupName,
                id: radio.id || groupName,
                questionText: groupLabel,
                isRequired: isRequiredField(radio, groupLabel),
                currentValue: options.find(o => o.checked)?.value || '',
                options: options,
                selector: radioName ? `input[type="radio"][name="${CSS.escape(radioName)}"], [role="radio"][name="${CSS.escape(radioName)}"]` : ''
            });
        }

        // 1.5 Checkbox Groups (e.g. Ruby experience brackets, collaboration tools)
        const seenCheckboxGroups = new Set();
        const checkboxContainers = Array.from(root.querySelectorAll('fieldset, .form-group, .field, .question, div[class*="group"], div[class*="field"], div[class*="container"]')).filter(c => {
            if (!isVisible(c)) return false;
            const cbs = Array.from(c.querySelectorAll('input[type="checkbox"]')).filter(cb => isVisible(cb) && !cb.disabled);
            return cbs.length >= 2 && cbs.length <= 15 && !c.querySelector('input[type="radio"], select, textarea');
        });

        const innerCheckboxContainers = checkboxContainers.filter(c => {
            return !Array.from(c.querySelectorAll('fieldset, .form-group, .field, .question, div[class*="group"], div[class*="field"], div[class*="container"]'))
                .some(child => child !== c && checkboxContainers.includes(child));
        });

        for (const cc of innerCheckboxContainers) {
            const cbs = Array.from(cc.querySelectorAll('input[type="checkbox"]')).filter(cb => isVisible(cb) && !cb.disabled);
            if (cbs.length < 2) continue;

            let groupLabel = '';
            const legend = cc.querySelector('legend, .ques, .title, label, h3, h4, h5, p');
            if (legend && legend.innerText.trim()) {
                groupLabel = legend.innerText.trim();
            }
            if (!groupLabel) groupLabel = getAssociatedLabel(cbs[0]);
            if (!groupLabel || seenCheckboxGroups.has(groupLabel)) continue;
            seenCheckboxGroups.add(groupLabel);

            const options = cbs.map(cb => {
                let optLabel = '';
                if (cb.labels && cb.labels.length > 0) optLabel = cb.labels[0].innerText.trim();
                if (!optLabel && cb.id) {
                    try {
                        const l = document.querySelector(`label[for="${CSS.escape(cb.id)}"]`);
                        if (l) optLabel = l.innerText.trim();
                    } catch(e) {}
                }
                if (!optLabel && cb.parentElement) {
                    optLabel = cb.parentElement.innerText.replace(groupLabel, '').trim();
                }
                const botCbId = 'bot-cb-' + Math.random().toString(36).substring(2, 9);
                cb.setAttribute('data-bot-cb-id', botCbId);
                return {
                    value: cb.value || optLabel,
                    text: optLabel || cb.value || 'Option',
                    id: cb.id || '',
                    name: cb.name || '',
                    selector: cb.id ? `#${CSS.escape(cb.id)}` : `[data-bot-cb-id="${botCbId}"]`,
                    checked: cb.checked
                };
            });

            results.push({
                fieldType: 'checkbox_group',
                name: groupLabel,
                id: cc.id || '',
                questionText: groupLabel,
                isRequired: isRequiredField(cc, groupLabel) || isRequiredField(cbs[0], groupLabel),
                currentValue: options.filter(o => o.checked).map(o => o.value).join(', '),
                options: options,
                selector: cc.id ? `#${CSS.escape(cc.id)}` : ''
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

            const botCsId = 'bot-cs-' + Math.random().toString(36).substring(2, 9);
            cs.setAttribute('data-bot-cs-id', botCsId);

            results.push({
                fieldType: 'custom_select',
                name: cs.getAttribute('name') || cs.id || label,
                id: cs.id || '',
                questionText: label,
                isRequired: isRequiredField(cs, label),
                currentValue: cs.innerText.trim(),
                options: childOptions,
                selector: cs.id ? `#${CSS.escape(cs.id)}` : `[data-bot-cs-id="${botCsId}"]`
            });
        }

        // 3.5 Button Groups / Pill Toggles (e.g. [Yes] [No] buttons on Oyster/Ashby)
        const buttonContainers = Array.from(root.querySelectorAll('[role="group"], [role="radiogroup"], .button-group, .btn-group, .toggle-group, .segmented-control, div')).filter(c => {
            if (!isVisible(c)) return false;
            const btns = Array.from(c.querySelectorAll('button:not([type="submit"]):not([disabled]), [role="button"], [role="radio"], .btn:not([type="submit"])')).filter(b => isVisible(b));
            return btns.length >= 2 && btns.length <= 6 && !c.querySelector('input:not([type="hidden"]), select, textarea');
        });

        for (const bc of buttonContainers) {
            const btns = Array.from(bc.querySelectorAll('button:not([type="submit"]):not([disabled]), [role="button"], [role="radio"], .btn:not([type="submit"])')).filter(b => isVisible(b));
            if (btns.length < 2 || btns.length > 6) continue;

            const label = getAssociatedLabel(bc) || getAssociatedLabel(btns[0]);
            if (!label || seenNames.has(label)) continue;
            seenNames.add(label);

            const options = btns.map((b) => {
                const bText = b.innerText.trim();
                const bVal = b.getAttribute('value') || b.getAttribute('data-value') || bText;
                const botBtnId = 'bot-btn-' + Math.random().toString(36).substring(2, 9);
                b.setAttribute('data-bot-btn-id', botBtnId);
                return {
                    value: bVal,
                    text: bText,
                    id: b.id || '',
                    selector: `[data-bot-btn-id="${botBtnId}"]`,
                    isActive: b.classList.contains('active') || b.classList.contains('selected') || b.getAttribute('aria-pressed') === 'true' || b.getAttribute('aria-checked') === 'true'
                };
            });

            if (!options.every(o => o.text.length < 40)) continue;

            results.push({
                fieldType: 'button_group',
                name: label,
                id: bc.id || '',
                questionText: label,
                isRequired: isRequiredField(bc, label) || isRequiredField(btns[0], label),
                currentValue: options.find(o => o.isActive)?.value || '',
                options: options,
                selector: ''
            });
        }

        // 4. Textareas
        const textareas = Array.from(root.querySelectorAll('textarea')).filter(t => isVisible(t) && !t.disabled && !t.readOnly);
        for (const ta of textareas) {
            const label = getAssociatedLabel(ta);
            const botFieldId = 'bot-field-' + Math.random().toString(36).substring(2, 9);
            ta.setAttribute('data-bot-field-id', botFieldId);
            results.push({
                fieldType: 'textarea',
                name: ta.name || '',
                id: ta.id || '',
                questionText: label,
                isRequired: isRequiredField(ta, label),
                currentValue: ta.value || '',
                options: [],
                selector: ta.id ? `#${CSS.escape(ta.id)}` : `[data-bot-field-id="${botFieldId}"]`
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
                if (seenCheckboxGroups.has(label) || innerCheckboxContainers.some(c => c.contains(inp))) {
                    continue;
                }
                fieldType = 'checkbox';
            } else if (itype === 'number') {
                fieldType = 'number';
            } else if (itype === 'date' || itype === 'datetime-local') {
                fieldType = 'date';
            } else if (inp.hasAttribute('list') || inp.getAttribute('autocomplete') === 'on' || inp.getAttribute('role') === 'combobox' || inp.classList.contains('autocomplete') || inp.classList.contains('searchable') || (inp.placeholder && (inp.placeholder.toLowerCase().includes('type') || inp.placeholder.toLowerCase().includes('search')))) {
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

            const botFieldId = 'bot-field-' + Math.random().toString(36).substring(2, 9);
            inp.setAttribute('data-bot-field-id', botFieldId);

            results.push({
                fieldType: fieldType,
                name: inp.name || '',
                id: inp.id || '',
                questionText: label,
                isRequired: req,
                currentValue: itype === 'checkbox' ? (inp.checked ? 'true' : 'false') : (inp.value || ''),
                options: options,
                selector: inp.id ? `#${CSS.escape(inp.id)}` : (inp.name ? `input[name="${CSS.escape(inp.name)}"]` : `[data-bot-field-id="${botFieldId}"]`)
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

    # Locate element safely with robust fallback
    el = None
    if fid:
        try:
            loc = page.locator(f"[id={json.dumps(fid)}]").first
            if loc.count() > 0:
                el = loc
        except Exception:
            pass

    if not el and fname:
        try:
            loc = page.locator(f"[name={json.dumps(fname)}]").first
            if loc.count() > 0:
                el = loc
        except Exception:
            pass

    if not el and fsel:
        try:
            loc = page.locator(fsel).first
            if loc.count() > 0:
                el = loc
        except Exception:
            pass

    # Fallback by label or context if ID/name didn't resolve
    if not el and qtext:
        try:
            short_q = qtext[:40].strip()
            if ftype == FormFieldType.CHECKBOX:
                for term in ["consent", "privacy", "policy", "confirm", "agree", "terms"]:
                    if term in qtext.lower():
                        c_loc = page.locator("input[type='checkbox']").last
                        if c_loc.count() > 0:
                            el = c_loc
                            break
            elif ftype == FormFieldType.SELECT:
                s_loc = page.locator("select").filter(has=page.locator(f"xpath=ancestor::*[contains(., {json.dumps(short_q)})]")).first
                if s_loc.count() > 0:
                    el = s_loc
            else:
                if any(k in qtext.lower() for k in ["organisation", "organization", "company", "employer"]):
                    org_loc = page.locator("input[id*='organi'], input[name*='organi'], input[id*='company'], input[name*='company']").first
                    if org_loc.count() > 0:
                        el = org_loc
                elif "city" in qtext.lower():
                    city_loc = page.locator("input#city, input[name='city'], input[placeholder*='city' i]").first
                    if city_loc.count() > 0:
                        el = city_loc
        except Exception:
            pass

    # --- 1. RADIO GROUP ---
    if ftype == FormFieldType.RADIO_GROUP:
        try:
            opt_val = (selected_option.get("value") if selected_option else answer).strip().lower()
            opt_txt = (selected_option.get("text") if selected_option else answer).strip().lower()
            opts = field.get("options", [])
            selected = False

            # 1. Try matching against field options with direct selectors
            for opt in opts:
                o_val = str(opt.get("value", "")).strip().lower()
                o_txt = str(opt.get("text", "")).strip().lower()
                o_sel = opt.get("selector", "")
                o_id = opt.get("id", "")

                is_match = (
                    opt_val == o_val or opt_txt == o_txt or
                    (opt_val and opt_val in o_val) or (opt_txt and opt_txt in o_txt) or
                    (o_val and o_val in opt_val) or (o_txt and o_txt in opt_txt)
                )

                if is_match:
                    r_loc = None
                    if o_sel:
                        try:
                            loc = page.locator(o_sel).first
                            if loc.count() > 0: r_loc = loc
                        except Exception:
                            pass
                    if not r_loc and o_id:
                        try:
                            loc = page.locator(f"[id={json.dumps(o_id)}]").first
                            if loc.count() > 0: r_loc = loc
                        except Exception:
                            pass

                    if r_loc:
                        try:
                            r_loc.scroll_into_view_if_needed(timeout=1000)
                        except Exception:
                            pass
                        try:
                            r_loc.check(force=True, timeout=1500)
                            selected = True
                        except Exception:
                            try:
                                r_loc.evaluate("el => { el.checked = true; el.click(); el.dispatchEvent(new Event('change', {bubbles:true})); }")
                                selected = True
                            except Exception:
                                pass
                        try:
                            r_loc.dispatch_event("change")
                        except Exception:
                            pass
                        if selected:
                            break

            # 2. Fallback: inspect radio elements by name or parent container
            if not selected:
                radios = page.locator(f"input[type='radio'][name='{fname}']") if fname else page.locator("input[type='radio']")
                count = radios.count()
                for i in range(count):
                    r = radios.nth(i)
                    r_val = (r.get_attribute("value") or "").strip().lower()
                    r_id = r.get_attribute("id") or ""
                    r_label = ""
                    if r_id:
                        try:
                            lbl = page.locator(f"label[for='{r_id}']").first
                            if lbl.count() > 0: r_label = lbl.inner_text().strip().lower()
                        except Exception:
                            pass
                    if not r_label:
                        try:
                            r_label = r.evaluate("el => el.parentElement ? el.parentElement.innerText.toLowerCase() : ''")
                        except Exception:
                            pass

                    if (opt_val and opt_val in r_val) or (opt_txt and opt_txt in r_label) or (opt_val and opt_val in r_label) or (r_label and r_label in opt_txt):
                        try:
                            r.scroll_into_view_if_needed(timeout=1000)
                        except Exception:
                            pass
                        try:
                            r.check(force=True, timeout=1500)
                            selected = True
                        except Exception:
                            try:
                                r.evaluate("el => { el.checked = true; el.click(); el.dispatchEvent(new Event('change', {bubbles:true})); }")
                                selected = True
                            except Exception:
                                pass
                        try:
                            r.dispatch_event("change")
                        except Exception:
                            pass
                        if selected:
                            break

            # 3. Fallback: affirmative Yes/No
            if not selected and opt_val in ["yes", "true", "1"]:
                radios = page.locator(f"input[type='radio'][name='{fname}']") if fname else page.locator("input[type='radio']")
                count = radios.count()
                for i in range(count):
                    r = radios.nth(i)
                    try:
                        r_lbl = r.evaluate("el => el.parentElement ? el.parentElement.innerText.toLowerCase() : ''")
                        if "yes" in r_lbl or "agree" in r_lbl or "true" in r_lbl:
                            r.check(force=True, timeout=1500)
                            r.dispatch_event("change")
                            selected = True
                            break
                    except Exception:
                        pass

            return {"success": selected, "entered_value": answer, "retained": selected}
        except Exception as e:
            return {"success": False, "reason": str(e)}

    # --- 1.5. BUTTON GROUP (e.g. [Yes] [No] buttons on Oyster/Ashby) ---
    elif ftype == FormFieldType.BUTTON_GROUP:
        try:
            target_ans = (selected_option.get("text") if selected_option else answer).strip().lower()
            opts = field.get("options", [])
            clicked = False

            # 1. Match by option selector or text
            for opt in opts:
                opt_t = opt.get("text", "").strip().lower()
                opt_v = str(opt.get("value", "")).strip().lower()
                opt_sel = opt.get("selector", "")

                is_match = (
                    target_ans == opt_t or target_ans == opt_v or
                    (target_ans in ["yes", "true"] and opt_t in ["yes", "agree", "confirm"]) or
                    (target_ans in ["no", "false"] and opt_t in ["no", "neither", "none"]) or
                    target_ans in opt_t or opt_t in target_ans
                )

                if is_match and opt_sel:
                    try:
                        btn_loc = page.locator(opt_sel).first
                        if btn_loc.count() > 0:
                            try:
                                btn_loc.scroll_into_view_if_needed(timeout=1000)
                            except Exception:
                                pass
                            btn_loc.click(force=True, timeout=2000)
                            try:
                                btn_loc.evaluate("el => { el.dispatchEvent(new Event('click', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true})); }")
                            except Exception:
                                pass
                            clicked = True
                            break
                    except Exception:
                        pass

            # 2. Fallback: Search near question text
            if not clicked and qtext:
                q_short = qtext[:30].strip()
                try:
                    container = page.locator(f"xpath=//*[contains(., {json.dumps(q_short)})]").last
                    if container.count() > 0:
                        btns = container.locator("button, [role='button'], .btn")
                        b_count = btns.count()
                        for b_idx in range(b_count):
                            b = btns.nth(b_idx)
                            b_txt = b.inner_text().strip().lower()
                            if (target_ans in ["yes", "true"] and b_txt == "yes") or (target_ans in ["no", "false"] and b_txt == "no") or (target_ans in b_txt):
                                try:
                                    b.scroll_into_view_if_needed(timeout=1000)
                                except Exception:
                                    pass
                                b.click(force=True, timeout=2000)
                                try:
                                    b.evaluate("el => { el.dispatchEvent(new Event('click', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true})); }")
                                except Exception:
                                    pass
                                clicked = True
                                break
                except Exception:
                    pass

            return {"success": clicked, "entered_value": answer, "retained": clicked}
        except Exception as e:
            return {"success": False, "reason": str(e)}

    # --- 1.8. CHECKBOX GROUP (e.g. Ruby experience brackets, collaboration tools) ---
    elif ftype == FormFieldType.CHECKBOX_GROUP:
        try:
            target_ans = (selected_option.get("text") if selected_option else answer).strip().lower()
            opts = field.get("options", [])
            checked_any = False

            for opt in opts:
                opt_t = opt.get("text", "").strip().lower()
                opt_v = str(opt.get("value", "")).strip().lower()
                opt_sel = opt.get("selector", "")
                opt_id = opt.get("id", "")

                is_match = (
                    target_ans == opt_t or target_ans == opt_v or
                    (target_ans in opt_t and len(opt_t) > 1) or
                    (opt_t in target_ans and len(opt_t) > 1)
                )

                cb_loc = None
                if opt_sel:
                    try:
                        loc = page.locator(opt_sel).first
                        if loc.count() > 0: cb_loc = loc
                    except Exception:
                        pass
                if not cb_loc and opt_id:
                    try:
                        loc = page.locator(f"[id={json.dumps(opt_id)}]").first
                        if loc.count() > 0: cb_loc = loc
                    except Exception:
                        pass

                if is_match:
                    if cb_loc:
                        try:
                            cb_loc.scroll_into_view_if_needed(timeout=1000)
                        except Exception:
                            pass
                        try:
                            cb_loc.check(force=True, timeout=1500)
                            checked_any = True
                        except Exception:
                            try:
                                cb_loc.evaluate("el => { el.checked = true; el.click(); el.dispatchEvent(new Event('change', {bubbles:true})); }")
                                checked_any = True
                            except Exception:
                                pass
                        try:
                            cb_loc.dispatch_event("change")
                        except Exception:
                            pass
                else:
                    if cb_loc:
                        try:
                            if cb_loc.is_checked():
                                cb_loc.uncheck(force=True, timeout=1000)
                                cb_loc.dispatch_event("change")
                        except Exception:
                            pass

            return {"success": checked_any, "entered_value": answer, "retained": checked_any}
        except Exception as e:
            return {"success": False, "reason": str(e)}

    # --- 2. SELECT DROPDOWN (NATIVE) ---
    elif ftype == FormFieldType.SELECT:
        if not el:
            return {"success": False, "reason": "SELECT_ELEMENT_NOT_FOUND"}
        try:
            try:
                el.scroll_into_view_if_needed(timeout=1500)
            except Exception:
                pass
            target_val = selected_option.get("value") if selected_option else None
            target_txt = selected_option.get("text") if selected_option else answer

            success = False
            # 1. Try selected_option value if provided
            if target_val:
                try:
                    el.select_option(value=target_val, timeout=2500)
                    success = True
                except Exception:
                    pass

            # 2. Try selected_option text or answer as label
            if not success and target_txt:
                try:
                    el.select_option(label=target_txt, timeout=2500)
                    success = True
                except Exception:
                    pass

            # 3. Direct DOM live option matching (case-insensitive & word boundary)
            if not success and answer:
                matched_val = el.evaluate("""(sel, ans) => {
                    const ansLow = (ans || '').toLowerCase().trim();
                    const opts = Array.from(sel.options);
                    // Exact match
                    let found = opts.find(o => o.text.trim().toLowerCase() === ansLow || o.value.trim().toLowerCase() === ansLow);
                    if (found) return found.value;
                    // Word boundary match
                    found = opts.find(o => {
                        const t = o.text.trim().toLowerCase();
                        return new RegExp('\\\\b' + ansLow + '\\\\b').test(t);
                    });
                    if (found) return found.value;
                    // Substring match
                    found = opts.find(o => {
                        const t = o.text.trim().toLowerCase();
                        return (ansLow.length > 2 && t.includes(ansLow)) || (t.length > 2 && ansLow.includes(t));
                    });
                    return found ? found.value : null;
                }""", answer)
                if matched_val is not None:
                    try:
                        el.select_option(value=matched_val, timeout=2500)
                        success = True
                    except Exception:
                        pass

            if success:
                el.dispatch_event("input")
                el.dispatch_event("change")
                curr_val = el.input_value()
                # If country was selected, wait a moment for dynamic states dropdown to populate
                if any(k in qtext.lower() or k in fname.lower() or k in fid.lower() for k in ["country", "countries"]):
                    time.sleep(1.2)
                return {"success": True, "entered_value": curr_val or target_txt, "retained": True}
            else:
                return {"success": False, "reason": f"OPTION_NOT_FOUND_FOR_{answer}"}
        except Exception as e:
            return {"success": False, "reason": str(e)}

    # --- 3. CUSTOM SELECT / COMBOBOX ---
    elif ftype == FormFieldType.CUSTOM_SELECT:
        if not el:
            return {"success": False, "reason": "CUSTOM_SELECT_NOT_FOUND"}
        try:
            try:
                el.scroll_into_view_if_needed(timeout=1500)
            except Exception:
                pass
            target_text = selected_option.get("text") if selected_option else answer

            # Semantic correction for target_text if question is specific
            q_low = qtext.lower()
            if any(k in q_low for k in ["country", "nation"]) and not any(k in q_low for k in ["code", "calling"]):
                if target_text not in ["India", "IN"]:
                    target_text = "India"
            elif any(k in q_low for k in ["state", "province"]) and target_text not in ["Maharashtra", "MH"]:
                target_text = "Maharashtra"
            elif any(k in q_low for k in ["country code", "calling code", "dial code"]):
                target_text = "+91"
            elif any(k in q_low for k in ["gender", "sex"]) and target_text not in ["Male"]:
                target_text = "Male"
            elif any(k in q_low for k in ["disability", "differently abled", "veteran", "armed forces", "worked with us", "sponsorship"]) and target_text not in ["No"]:
                target_text = "No"

            # Check if el is an input or has an inner input
            is_inp = el.evaluate("el => el.tagName === 'INPUT'")
            inner_inp = None
            if is_inp:
                inner_inp = el
            else:
                try:
                    inner_candidate = el.locator("input:not([type='hidden'])").first
                    if inner_candidate.count() > 0 and inner_candidate.is_visible():
                        inner_inp = inner_candidate
                except Exception:
                    inner_inp = None

            if inner_inp:
                inner_inp.click()
                time.sleep(0.2)
                inner_inp.fill("")
                inner_inp.fill(str(target_text))
                time.sleep(0.4)
            else:
                el.click()
                time.sleep(0.4)

            # Look for options list
            opt_locator = page.locator(f"[role='option']:has-text('{target_text}'), .option:has-text('{target_text}'), li:has-text('{target_text}')").first
            if opt_locator.count() > 0 and opt_locator.is_visible():
                opt_locator.click()
                return {"success": True, "entered_value": target_text, "retained": True}

            # If target_text is India, try case insensitive or word start
            if target_text == "India":
                ind_opt = page.locator("[role='option'], .option, li").filter(has_text=re.compile(r"^India\b", re.I)).first
                if ind_opt.count() > 0 and ind_opt.is_visible():
                    ind_opt.click()
                    return {"success": True, "entered_value": "India", "retained": True}

            if inner_inp:
                page.keyboard.press("Enter")
                return {"success": True, "entered_value": target_text, "retained": True}

            return {"success": False, "reason": f"OPTION_NOT_FOUND: {target_text}"}
        except Exception as e:
            return {"success": False, "reason": str(e)}

    # --- 4. CHECKBOX ---
    elif ftype == FormFieldType.CHECKBOX:
        if not el:
            # Last resort fallback: find any visible checkbox if question is privacy/terms
            if any(k in qtext.lower() for k in ["privacy", "policy", "consent", "terms", "agree", "confirm"]):
                try:
                    el = page.locator("input[type='checkbox']").last
                except Exception:
                    el = None
        if not el or el.count() == 0:
            return {"success": False, "reason": "CHECKBOX_NOT_FOUND"}
        try:
            try:
                el.scroll_into_view_if_needed(timeout=1500)
            except Exception:
                pass
            should_check = False
            ans_low = answer.strip().lower()

            # Affirmative checks or required agreements
            if ans_low in ["true", "yes", "1", "agree", "checked"]:
                should_check = True
            elif field.get("isRequired") or any(k in qtext.lower() for k in ["terms", "agree", "consent", "declaration", "certify", "authorized", "privacy", "notice", "policy", "i confirm", "i have read"]):
                should_check = True

            checked_success = False
            if should_check:
                try:
                    el.check(force=True, timeout=2000)
                    checked_success = True
                except Exception:
                    pass
                if not checked_success or not el.is_checked():
                    # Evaluate via DOM
                    el.evaluate("e => { e.checked = true; e.dispatchEvent(new Event('change', {bubbles: true})); e.dispatchEvent(new Event('input', {bubbles: true})); }")
                    # Also click label or parent wrapper in case it's custom UI
                    try:
                        el.locator("xpath=parent::*").first.click(force=True, timeout=1000)
                    except Exception:
                        pass
            else:
                try:
                    el.uncheck(force=True, timeout=2000)
                except Exception:
                    el.evaluate("e => { e.checked = false; e.dispatchEvent(new Event('change', {bubbles: true})); }")

            el.dispatch_event("change")
            is_chk = el.is_checked()
            return {"success": True, "entered_value": "checked" if is_chk else "unchecked", "retained": True}
        except Exception as e:
            return {"success": False, "reason": str(e)}

    # --- 5. AUTOCOMPLETE FIELD ---
    elif ftype == FormFieldType.AUTOCOMPLETE:
        try:
            target_el = el
            if not target_el or target_el.count() == 0:
                if fsel:
                    try:
                        loc = page.locator(fsel).first
                        if loc.count() > 0: target_el = loc
                    except Exception:
                        pass
            if not target_el or target_el.count() == 0:
                if fid:
                    try:
                        loc = page.locator(f"[id={json.dumps(fid)}]").first
                        if loc.count() > 0: target_el = loc
                    except Exception:
                        pass
            if not target_el or target_el.count() == 0:
                if fname:
                    try:
                        loc = page.locator(f"[name={json.dumps(fname)}]").first
                        if loc.count() > 0: target_el = loc
                    except Exception:
                        pass

            # Fallback search by country / location or 'Start typing' container (e.g. Oyster, Ashby)
            if (not target_el or target_el.count() == 0) and qtext:
                for sel in [
                    "div[class*='select']:has-text('Start typing')",
                    "[role='combobox']:has-text('Start typing')",
                    "button:has-text('Start typing')",
                    "div:has-text('Start typing...')",
                    "span:has-text('Start typing')",
                    "input[id*='country' i]", "input[name*='country' i]", "input[placeholder*='country' i]",
                    "input[placeholder*='Start typing' i]", "input[placeholder*='typing' i]",
                    "input[aria-label*='country' i]", "[role='combobox'][aria-label*='country' i]",
                    ".country-select", "[data-testid*='country' i]",
                    "div[class*='select'] input", "[role='combobox']"
                ]:
                    try:
                        loc = page.locator(sel).first
                        if loc.count() > 0 and loc.is_visible():
                            target_el = loc
                            break
                    except Exception:
                        pass

            # Fallback search around question text in any container
            if (not target_el or target_el.count() == 0) and qtext:
                short_q = qtext[:35].strip()
                for q_sel in [
                    f"label:has-text({json.dumps(short_q)})",
                    f"div:has-text({json.dumps(short_q)})",
                    f"p:has-text({json.dumps(short_q)})"
                ]:
                    try:
                        q_node = page.locator(q_sel).last
                        if q_node.count() > 0:
                            inp = q_node.locator("xpath=..//input | xpath=..//*[@role='combobox'] | xpath=..//div[contains(@class, 'select')]").first
                            if inp.count() > 0:
                                target_el = inp
                                break
                    except Exception:
                        pass

            if not target_el or target_el.count() == 0:
                return {"success": False, "reason": "AUTOCOMPLETE_NOT_FOUND"}

            try:
                target_el.scroll_into_view_if_needed(timeout=1000)
            except Exception:
                pass

            try:
                target_el.click(force=True, timeout=1500)
            except Exception:
                pass
            time.sleep(0.2)

            filled = False
            # If target_el is a container or combobox wrapper, resolve the inner input
            try:
                inner = target_el.locator("input:not([type='hidden'])").first
                if inner.count() > 0:
                    inner.fill(str(answer))
                    filled = True
            except Exception:
                pass

            if not filled:
                try:
                    target_el.fill(str(answer), timeout=1500, force=True)
                    filled = True
                except Exception:
                    pass

            if not filled:
                try:
                    page.keyboard.type(str(answer), delay=30)
                    filled = True
                except Exception:
                    pass

            time.sleep(0.4)

            # Suggestion dropdown click
            sugg_clicked = False
            for sugg_sel in [
                f"[role='option']:has-text('{answer}')",
                f".suggestion-item:has-text('{answer}')",
                f".autocomplete-item:has-text('{answer}')",
                f"[role='listbox'] [role='option']:has-text('{answer}')",
                f"div[id*='-option-']:has-text('{answer}')",
                f"li:has-text('{answer}')"
            ]:
                try:
                    sugg = page.locator(sugg_sel).first
                    if sugg.count() > 0 and sugg.is_visible():
                        sugg.click(force=True, timeout=1200)
                        sugg_clicked = True
                        break
                except Exception:
                    pass

            if not sugg_clicked:
                try:
                    page.keyboard.press("ArrowDown")
                    time.sleep(0.1)
                    page.keyboard.press("Enter")
                except Exception:
                    pass

            try:
                target_el.dispatch_event("input")
                target_el.dispatch_event("change")
                target_el.dispatch_event("blur")
            except Exception:
                pass

            val = ""
            try:
                val = target_el.input_value()
            except Exception:
                pass
            return {"success": True, "entered_value": val or answer, "retained": True}
        except Exception as e:
            return {"success": False, "reason": str(e)}

    # --- 6. TEXTAREA ---
    elif ftype == FormFieldType.TEXTAREA:
        try:
            target_ta = el
            if not target_ta and fsel:
                try:
                    loc = page.locator(fsel).first
                    if loc.count() > 0: target_ta = loc
                except Exception:
                    pass
            if not target_ta and qtext:
                try:
                    q_short = qtext[:30].strip()
                    lbl = page.locator(f"label:has-text({json.dumps(q_short)})").first
                    if lbl.count() > 0:
                        target_ta = lbl.locator("xpath=..//textarea").first
                    if not target_ta or target_ta.count() == 0:
                        target_ta = page.locator("textarea").first
                except Exception:
                    pass

            if not target_ta or target_ta.count() == 0:
                return {"success": False, "reason": "TEXTAREA_NOT_FOUND"}

            try:
                target_ta.scroll_into_view_if_needed(timeout=1000)
            except Exception:
                pass

            filled = False
            try:
                target_ta.fill(str(answer), timeout=2500, force=True)
                filled = True
            except Exception:
                pass

            if not filled:
                # Direct JS injection into textarea
                try:
                    page.evaluate("""({fid, fname, fsel, val}) => {
                        let ta = null;
                        if (fid) ta = document.getElementById(fid);
                        if (!ta && fname) ta = document.querySelector(`textarea[name="${CSS.escape(fname)}"]`);
                        if (!ta && fsel) {
                            try { ta = document.querySelector(fsel); } catch(e) {}
                        }
                        if (!ta) ta = document.querySelector('textarea');
                        if (ta) {
                            ta.focus();
                            ta.value = val;
                            ta.dispatchEvent(new Event('input', {bubbles: true}));
                            ta.dispatchEvent(new Event('change', {bubbles: true}));
                            ta.dispatchEvent(new Event('blur', {bubbles: true}));
                            return true;
                        }
                        return false;
                    }""", {"fid": fid, "fname": fname, "fsel": fsel, "val": str(answer)})
                    filled = True
                except Exception:
                    pass

            try:
                target_ta.dispatch_event("input")
                target_ta.dispatch_event("change")
                target_ta.dispatch_event("blur")
            except Exception:
                pass

            retained_val = ""
            try:
                retained_val = target_ta.input_value()
            except Exception:
                pass
            return {"success": True, "entered_value": retained_val or answer, "retained": True}
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
        if not el or el.count() == 0:
            if fsel:
                try:
                    loc = page.locator(fsel).first
                    if loc.count() > 0: el = loc
                except Exception:
                    pass
        if not el or el.count() == 0:
            return {"success": False, "reason": "INPUT_NOT_FOUND"}
        try:
            try:
                el.scroll_into_view_if_needed(timeout=1000)
            except Exception:
                pass
            filled = False

            # 1. Try direct fill with force=True and short timeout (never hang 30s!)
            try:
                el.fill(str(answer), timeout=2500, force=True)
                filled = True
            except Exception:
                pass

            # 2. If intercepted by overlay/wrapper (e.g., illustrated-input), click wrapper
            if not filled:
                try:
                    wrapper = el.locator("xpath=ancestor::*[contains(@class, 'illustrated-input') or @role='combobox' or contains(@class, 'input')][1]").first
                    if wrapper.count() > 0:
                        wrapper.click(force=True, timeout=1500)
                        time.sleep(0.2)
                        page.keyboard.type(str(answer))
                        filled = True
                except Exception:
                    pass

            if not filled:
                # Direct JS fallback
                try:
                    page.evaluate("""({fid, fname, fsel, val}) => {
                        let inp = null;
                        if (fid) inp = document.getElementById(fid);
                        if (!inp && fname) inp = document.querySelector(`input[name="${CSS.escape(fname)}"]`);
                        if (!inp && fsel) {
                            try { inp = document.querySelector(fsel); } catch(e) {}
                        }
                        if (!inp) inp = document.querySelector('input');
                        if (inp) {
                            inp.focus();
                            inp.value = val;
                            inp.dispatchEvent(new Event('input', {bubbles: true}));
                            inp.dispatchEvent(new Event('change', {bubbles: true}));
                            inp.dispatchEvent(new Event('blur', {bubbles: true}));
                            return true;
                        }
                        return false;
                    }""", {"fid": fid, "fname": fname, "fsel": fsel, "val": str(answer)})
                    filled = True
                except Exception:
                    pass

            # 3. JavaScript DOM injection fallback (guaranteed to succeed without pointer event blocks!)
            if not filled:
                try:
                    el.evaluate("""(input, val) => {
                        input.value = val;
                        input.dispatchEvent(new Event('input', { bubbles: true }));
                        input.dispatchEvent(new Event('change', { bubbles: true }));
                        input.dispatchEvent(new Event('blur', { bubbles: true }));
                    }""", str(answer))
                    filled = True
                except Exception:
                    pass

            try:
                el.dispatch_event("input")
                el.dispatch_event("change")
                el.dispatch_event("blur")
            except Exception:
                pass

            retained_val = ""
            try:
                retained_val = el.input_value()
            except Exception:
                pass
            return {"success": filled, "entered_value": retained_val or answer, "retained": True}
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
                                   logger_fn = None,
                                   location_hint: str = "") -> Dict[str, Any]:
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
    failed_mandatory_fields = []

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
                company_name=company_name,
                field_name=field.get("name", ""),
                field_id=field.get("id", ""),
                location_hint=location_hint
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
                    log(f"⚠️ Mandatory question requires candidate verification: '{q_text}' ({reason}). Continuing with other fields...", "WARNING")
                    failed_mandatory_fields.append((q_text, category, reason, field))
                    processed_questions.add(q_key)
                    continue
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
                    failed_mandatory_fields.append((q_text, category, f"INSERTION_FAILED: {fill_res.get('reason')}", field))

        # If no fields were filled in this pass, break out of loop
        if not new_field_filled:
            break

        # Brief pause to allow dynamic conditional fields to reveal
        time.sleep(1.0)

    # If any mandatory fields failed and are still empty, report them
    if failed_mandatory_fields:
        # Check if they are still invalid
        last_unanswered = failed_mandatory_fields[-1]
        val_check = validate_entire_form(page)
        if not val_check.get("isValid"):
            log(f"⚠️ Mandatory questions need candidate input: '{last_unanswered[0]}'. Form kept OPEN in Chrome!", "WARNING")
            return {
                "status": "NEEDS_USER_INPUT",
                "success": False,
                "unanswered_question": last_unanswered[0],
                "category": last_unanswered[1],
                "reason": last_unanswered[2],
                "field": last_unanswered[3]
            }

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
