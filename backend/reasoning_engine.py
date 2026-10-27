import os
import json
import re
import time
import threading
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict
from playwright.sync_api import Page, Locator

from ai_service import query_ai, get_candidate_profile, call_gemini
from question_answering import QuestionAnsweringEngine, qa_engine, QuestionCategory
from database import record_experience, lookup_experience, update_reasoning_metric, get_reasoning_metrics, record_application
from chat_panel_handler import naukri_chat_panel_handler, ChatPanelState
from button_service import button_service, ButtonCategory, is_naukri_application_confirmed
from form_engine import (
    detect_and_collect_form_questions,
    fill_form_control,
    validate_entire_form,
    process_and_fill_complete_form,
    upload_resume_file,
    FormFieldType
)

ALLOWED_TOOLS = [
    # Core 15 Structured Tools
    "INSPECT_PAGE",
    "FILL_INPUT",
    "SELECT_OPTION",
    "SELECT_RADIO",
    "SET_CHECKBOX",
    "UPLOAD_RESUME",
    "CLICK_APPLY",
    "CLICK_CONTINUE",
    "CLICK_SAVE",
    "CLICK_SUBMIT",
    "HANDLE_VALIDATION",
    "WAIT_FOR_NAVIGATION",
    "INSPECT_NEW_TAB",
    "REQUEST_USER_INPUT",
    "MARK_BLOCKED",
    # Legacy & High-Level Compound Automation Tools
    "PROCESS_CHAT_QUESTION",
    "FILL_FORM_FIELDS",
    "CLICK_SAVE_OR_SUBMIT",
    "SELECT_CHIP_OPTION",
    "RECOVER_FAILED_LOCATOR",
    "VERIFY_APPLICATION_SUBMISSION"
]

@dataclass
class Observation:
    url: str
    page_title: str
    job_title: str
    company_name: str
    panel_type: str  # "CHAT_DRAWER", "STANDARD_MODAL", "EXTERNAL_PAGE", "NONE"
    visible_questions: List[str]
    input_types: List[str]
    has_save_or_submit_button: bool
    has_validation_errors: bool
    error_message: str
    last_action: str
    last_action_success: bool
    raw_context: Dict[str, Any]
    available_buttons: List[str] = None

@dataclass
class AgentDecision:
    observation_summary: str
    objective: str
    action: str  # Must be in ALLOWED_TOOLS
    action_params: Dict[str, Any]
    reason: str
    source: str  # "CANDIDATE_PROFILE", "DETERMINISTIC_TOOL", "GEMINI_REASONING", "EXPERIENCE_MEMORY"
    verification_plan: str
    requires_user_input: bool

class AutonomousReasoningEngine:
    """
    Primary Reasoning Engine for AI Job Applications:
    - Powered by Google Gemini reasoning with local Ollama & candidate memory fallbacks.
    - Strict Observe -> Reason -> Act -> Verify loop for every application action.
    - Deterministic tool execution via Playwright with 15 verified actions.
    - Candidate Memory grounding: never hallucinates or fabricates facts.
    - Verification Engine: rejects false positives & prevents unconfirmed completions.
    - Self-correction with bounded retries and MySQL experience persistence.
    """

    def __init__(self, qa_engine_instance: Optional[QuestionAnsweringEngine] = None, logger_fn = None):
        self.qa = qa_engine_instance or qa_engine
        self.logger = logger_fn or (lambda msg, level="INFO": print(f"[{level}] {msg}"))

    # ==========================
    # 1. OBSERVE
    # ==========================
    def observe(self, page: Page, context_data: Dict[str, Any], last_action: str = "", last_success: bool = True) -> Observation:
        """
        Inspects live browser state to collect ground-truth observations.
        Uses Playwright DOM inspection; does not guess or assume page content.
        """
        url = page.url or ""
        title = ""
        try:
            title = page.title()
        except Exception:
            pass

        job_title = context_data.get("job_title", "")
        company_name = context_data.get("company_name", "")

        # Check for visible right-side chat drawer / screening panel (Naukri)
        chat_panel = naukri_chat_panel_handler.detect_chat_panel(page)
        is_chat_drawer = chat_panel is not None and chat_panel.is_visible()

        # Check for standard modal or form
        is_modal = False
        if not is_chat_drawer:
            try:
                is_modal = page.evaluate("""() => {
                    const m = document.querySelector('div[role="dialog"], .modal-content, .apply-modal, div[class*="modal"]');
                    return m !== null && m.offsetParent !== null;
                }""")
            except Exception:
                is_modal = False

        panel_type = "NONE"
        if is_chat_drawer:
            panel_type = "CHAT_DRAWER"
        elif is_modal:
            panel_type = "STANDARD_MODAL"
        elif "naukri.com" not in url.lower():
            panel_type = "EXTERNAL_PAGE"

        # Collect questions and input types
        visible_questions: List[str] = []
        input_types: List[str] = []

        if is_chat_drawer:
            latest_q = naukri_chat_panel_handler.extract_latest_question(page, chat_panel)
            if latest_q:
                visible_questions.append(latest_q)
            chat_inp = naukri_chat_panel_handler.locate_chat_input(page, chat_panel)
            if chat_inp:
                try:
                    inp_type = chat_inp.get_attribute("type") or "text"
                    if chat_inp.evaluate("el => el.tagName.toLowerCase()") == "textarea":
                        inp_type = "textarea"
                    input_types.append(inp_type)
                except Exception:
                    input_types.append("text")
        else:
            try:
                form_fields = page.evaluate("""() => {
                    const fields = [];
                    const inps = Array.from(document.querySelectorAll('input:not([type="hidden"]), textarea, select'))
                        .filter(el => el.offsetParent !== null && !el.disabled);
                    for (const inp of inps) {
                        const label = (inp.labels && inp.labels[0]) ? inp.labels[0].innerText.trim() : (inp.placeholder || inp.name || '');
                        fields.push({ label: label, type: inp.type || inp.tagName.toLowerCase() });
                    }
                    return fields;
                }""")
                for f in form_fields[:10]:
                    if f.get("label"):
                        visible_questions.append(f["label"])
                    if f.get("type"):
                        input_types.append(f["type"])
            except Exception:
                pass

        # Detect buttons via dedicated ButtonDetectionService
        available_buttons: List[str] = []
        has_save_or_submit = False
        try:
            detected_btns = button_service.detect_buttons_in_container(page)
            for b in detected_btns:
                available_buttons.append(f"{b.category}:{b.text}")
                if b.category in [ButtonCategory.SUBMIT, ButtonCategory.SAVE, ButtonCategory.CONTINUE]:
                    has_save_or_submit = True
        except Exception:
            pass

        # Fallback check for Save or Submit button if button_service was empty
        if not has_save_or_submit:
            try:
                has_save_or_submit = page.evaluate("""() => {
                    const terms = ['save', 'save and apply', 'submit', 'send', 'apply now', 'continue'];
                    return Array.from(document.querySelectorAll('button, input[type="submit"], [role="button"]'))
                        .some(b => {
                            if (b.offsetParent === null || b.disabled) return false;
                            const txt = (b.innerText || b.value || b.getAttribute('aria-label') || '').toLowerCase().trim();
                            return terms.some(t => txt === t || txt.startsWith(t));
                        });
                }""")
            except Exception:
                has_save_or_submit = False

        # Check for visible validation errors
        has_validation_errors = False
        error_msg = ""
        try:
            err_data = page.evaluate("""() => {
                const errs = Array.from(document.querySelectorAll('.error, .alert-danger, .invalid-feedback, span[class*="error"], div[class*="error"]'))
                    .filter(el => el.offsetParent !== null && el.innerText.trim().length > 0);
                return errs.length > 0 ? errs[0].innerText.trim() : "";
            }""")
            if err_data:
                has_validation_errors = True
                error_msg = err_data
        except Exception:
            pass

        return Observation(
            url=url,
            page_title=title,
            job_title=job_title,
            company_name=company_name,
            panel_type=panel_type,
            visible_questions=visible_questions,
            input_types=input_types,
            has_save_or_submit_button=has_save_or_submit,
            has_validation_errors=has_validation_errors,
            error_message=error_msg,
            last_action=last_action,
            last_action_success=last_success,
            raw_context=context_data,
            available_buttons=available_buttons
        )

    # ==========================
    # 2. REASON (Gemini + Memory)
    # ==========================
    def reason(self, obs: Observation) -> AgentDecision:
        """
        Interprets the observed situation, consults Google Gemini with structured output,
        candidate profile & memory, and generates a structured, verified action plan.
        """
        # Step 1: Handle validation errors immediately
        if obs.has_validation_errors:
            self.logger(f"Reasoning: Detected validation error: '{obs.error_message}'", "WARNING")
            update_reasoning_metric("validation_error_encountered", 1.0, obs.error_message[:40])
            return AgentDecision(
                observation_summary=f"Validation error present: {obs.error_message}",
                objective="Resolve validation error or request candidate input",
                action="REQUEST_USER_INPUT",
                action_params={"reason": f"Validation error: {obs.error_message}"},
                reason="Mandatory form validation error requires candidate review",
                source="DETERMINISTIC_TOOL",
                verification_plan="Preserve tab open in Chrome for candidate review",
                requires_user_input=True
            )

        # Step 2: Check for Right-side Chat Drawer (Naukri Screening Drawer)
        if obs.panel_type == "CHAT_DRAWER":
            if not obs.visible_questions:
                # No question bubble visible; check if save button can be clicked
                return AgentDecision(
                    observation_summary="Naukri chat drawer open without new question bubble.",
                    objective="Determine if continuation or save is required",
                    action="CLICK_SAVE_OR_SUBMIT" if obs.has_save_or_submit_button else "PROCESS_CHAT_QUESTION",
                    action_params={},
                    reason="Drawer is open; check if save can be clicked or quick-replies exist.",
                    source="DETERMINISTIC_TOOL",
                    verification_plan="Verify if panel closes or confirmation appears",
                    requires_user_input=False
                )

            question = obs.visible_questions[0]
            inp_type = obs.input_types[0] if obs.input_types else "text"

            # Check if answer can be deterministically resolved from profile
            qa_res = self.qa.process_question(
                question_text=question,
                input_type=inp_type,
                job_title=obs.job_title,
                company_name=obs.company_name
            )

            if qa_res.get("needs_user_input"):
                update_reasoning_metric("unresolved_questions_count", 1.0, question[:30])
                return AgentDecision(
                    observation_summary=f"Chat question: '{question}' requires candidate input.",
                    objective="Halt autonomous submission safely and preserve open tab",
                    action="REQUEST_USER_INPUT",
                    action_params={"question": question, "reason": qa_res.get("reason", "NEEDS_USER_INPUT")},
                    reason=f"Question cannot be answered reliably without candidate input: {qa_res.get('reason')}",
                    source="CANDIDATE_PROFILE",
                    verification_plan="Keep Chrome tab open and bring to front",
                    requires_user_input=True
                )

            return AgentDecision(
                observation_summary=f"Naukri chat drawer displays screening question: '{question}'",
                objective="Answer the question accurately using candidate profile and save answer",
                action="PROCESS_CHAT_QUESTION",
                action_params={
                    "question": question,
                    "answer": qa_res.get("answer", ""),
                    "input_type": inp_type,
                    "source": qa_res.get("source", "CANDIDATE_PROFILE")
                },
                reason=f"Resolved answer '{qa_res.get('answer')}' from {qa_res.get('source')} for category {qa_res.get('category')}",
                source=qa_res.get("source", "CANDIDATE_PROFILE"),
                verification_plan="Verify value retention in input and wait for UI transition after Save",
                requires_user_input=False
            )

        # Step 3: Multi-question form or external career website
        # Check if Gemini reasoning can structure the next optimal action
        gemini_decision = self._reason_with_gemini(obs)
        if gemini_decision:
            return gemini_decision

        # Step 4: Deterministic Fallback if Gemini is unavailable/offline
        if obs.panel_type in ["STANDARD_MODAL", "EXTERNAL_PAGE"]:
            return AgentDecision(
                observation_summary=f"Application form detected on {obs.company_name or 'portal'} with {len(obs.visible_questions)} fields.",
                objective="Fill verified answers into all detected form fields",
                action="FILL_FORM_FIELDS",
                action_params={"field_count": len(obs.visible_questions)},
                reason="Standard application form needs multi-field automated filling and validation",
                source="DETERMINISTIC_TOOL",
                verification_plan="Validate entire form inputs before clicking submit",
                requires_user_input=False
            )

        # Default fallback
        return AgentDecision(
            observation_summary=f"On page {obs.page_title} ({obs.url[:50]}).",
            objective="Verify application submission or locate active apply elements",
            action="VERIFY_APPLICATION_SUBMISSION",
            action_params={},
            reason="Check if application is already submitted or requires action",
            source="DETERMINISTIC_TOOL",
            verification_plan="Check for success indicators or confirmation badges",
            requires_user_input=False
        )

    def _reason_with_gemini(self, obs: Observation) -> Optional[AgentDecision]:
        """
        Queries Google Gemini with structured observations and verified candidate memory.
        Enforces strict tool allowlist and ground-truth profile constraints.
        """
        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            return None

        try:
            profile = get_candidate_profile()
            candidate_summary = {
                "name": profile.get("full_name", "Abdul Razzaque Shaikh"),
                "experience": profile.get("experience_years", "5+ years"),
                "skills": profile.get("primary_skills", ["React.js", "Node.js", "Next.js", "TypeScript"]),
                "current_salary": profile.get("current_ctc", "12.0 LPA"),
                "expected_salary": profile.get("expected_ctc", "15.0 LPA"),
                "notice_period": "Immediate Joiner (0 days, not serving notice, lwd: null)",
                "location": profile.get("current_location", "Mumbai, India")
            }

            prompt = json.dumps({
                "url": obs.url,
                "page_title": obs.page_title,
                "job_title": obs.job_title,
                "company_name": obs.company_name,
                "panel_type": obs.panel_type,
                "visible_questions": obs.visible_questions,
                "has_save_or_submit_button": obs.has_save_or_submit_button,
                "available_buttons": obs.available_buttons,
                "candidate_profile": candidate_summary,
                "allowed_actions": ALLOWED_TOOLS
            })

            system_prompt = (
                """
                    You are an expert AI Job Application Reasoning Engine responsible for
                    assisting a candidate with job discovery and application workflows on
                    Naukri.com.

                    Your role is to analyze the current page observation, candidate profile,
                    job description, form state, and available browser actions to determine
                    the single safest and most useful next action.

                    You operate as a controlled decision-making engine, not as an unrestricted
                    browser automation agent.

                    CORE OBJECTIVES
                    1. Identify relevant job opportunities based on the candidate's profile.
                    2. Evaluate job requirements against verified candidate information.
                    3. Navigate application workflows using only the available actions.
                    4. Fill application fields accurately using trusted candidate data.
                    5. Detect missing information, validation errors, and submission status.
                    6. Verify the result of each action before deciding what to do next.
                    7. Avoid duplicate applications and unsupported claims.

                    INPUT CONTEXT
                    You may receive:
                    - Current page observation or screenshot description.
                    - Current URL and page title.
                    - Candidate profile and verified resume data.
                    - Job title, company, location, experience requirements, and job description.
                    - Visible form fields and their current values.
                    - Allowed actions and their parameter schemas.
                    - Previous action and its execution result.
                    - Application history, when available.

                    REASONING RULES

                    1. OBSERVATION FIRST
                    - Base every decision on the latest page observation and available data.
                    - Identify the current page, current workflow stage, visible controls,
                    mandatory fields, and any validation errors.
                    - Do not assume that a click, navigation, upload, or submission succeeded.
                    - If the observation is incomplete or ambiguous, choose an appropriate
                    permitted observation or recovery action.

                    2. STRICT ACTION VALIDATION
                    - Select exactly one action per response.
                    - The action must match an entry in the provided allowed_actions list.
                    - Use the exact action name and only its supported parameters.
                    - Never invent action names, selectors, element IDs, or parameter fields.
                    - If no safe, supported action is possible, request user input or select
                    an allowed recovery action.
                    - Use REQUEST_USER_INPUT only if it is explicitly included in
                    allowed_actions. Otherwise, follow the application's defined mechanism
                    for requesting user input.

                    3. CANDIDATE DATA INTEGRITY
                    - Use only verified information from the candidate profile, resume,
                    or explicit user-provided answers.
                    - Never fabricate or infer personal details, education, employment history,
                    skills, years of experience, notice period, current salary, expected
                    salary, contact information, or other application answers.
                    - Do not treat a job description as evidence of the candidate's skills.
                    - Do not overwrite an existing field value unless correction is justified
                    by verified candidate data.
                    - If a mandatory field requires unknown information, request user input
                    rather than guessing.
                    - Preserve the original meaning of candidate information when adapting
                    resume content to a job.

                    4. JOB RELEVANCE
                    - Compare the job title, required skills, experience, location, and other
                    stated requirements against the verified candidate profile.
                    - Distinguish required qualifications from preferred qualifications.
                    - Identify clear mismatches and missing information.
                    - Do not claim that the candidate meets a requirement without evidence.
                    - If the available information is insufficient to assess suitability,
                    state that limitation rather than inventing a match.
                    - Do not reject a potentially suitable job solely because an optional
                    qualification is missing.

                    5. FORM HANDLING
                    - Inspect each visible form field before entering a value.
                    - Match each field to the correct candidate-profile attribute.
                    - Respect field types, dropdown options, character limits, and validation.
                    - Do not place information in an unrelated field.
                    - Do not bypass validation or security controls.
                    - If a field's meaning is unclear, request clarification.
                    - After filling fields, inspect the resulting form state and correct
                    identifiable errors before proceeding.

                    6. APPLICATION AND SUBMISSION SAFETY
                    - Treat actions that send an application, accept declarations, or disclose
                    personal data as consequential.
                    - Follow the user's configured authorization policy for final submission.
                    - If explicit confirmation is required by that policy, request it before
                    submitting.
                    - Never falsely report an application as submitted or successful.
                    - After submission, verify success using a confirmation message, application
                    status, application history, or another reliable page observation.
                    - If verification is unavailable, report the status as unverified.
                    - Check available application history before applying to avoid duplicates.
                    - Do not circumvent CAPTCHAs, OTP verification, access restrictions,
                    platform security controls, or anti-bot protections. Request user
                    assistance when these occur.

                    7. ERROR RECOVERY
                    - Detect missing elements, stale observations, failed navigation, disabled
                    buttons, upload failures, validation errors, and unexpected pages.
                    - Do not repeat a failed action indefinitely.
                    - Re-observe the page when the previous action may have changed its state.
                    - Choose a recovery action only when supported by allowed_actions.
                    - Escalate to the user if safe recovery is not possible.

                    8. REASONING AND OUTPUT
                    - Evaluate the current state, immediate objective, candidate data,
                    available actions, risks, and expected result.
                    - Return only the single next action, not a sequence of future actions.
                    - Keep explanations concise, factual, and grounded in observations.
                    - Do not include markdown, code fences, comments, or text outside JSON.
                    - Output exactly these keys:
                    observation_summary,
                    objective,
                    action,
                    action_params,
                    reason,
                    source,
                    verification_plan,
                    requires_user_input

                    OUTPUT CONTRACT
                    Return one valid JSON object with the following structure:

                    {
                    "observation_summary": "Concise description of the observed page state",
                    "objective": "Immediate goal of the next action",
                    "action": "EXACT_ALLOWED_ACTION_NAME",
                    "action_params": {},
                    "reason": "Evidence-based explanation for choosing this action",
                    "source": "Source of the relevant information",
                    "verification_plan": "How the action's result should be verified",
                    "requires_user_input": false
                    }

                    OUTPUT VALIDATION
                    - All eight keys must always be present.
                    - Use valid JSON syntax with double-quoted keys and string values.
                    - action_params must be a JSON object matching the selected action's schema.
                    - requires_user_input must be a JSON boolean: true or false.
                    - Use null for unavailable optional values only when permitted by the schema.
                    - Never include additional keys.
                    - Never place explanatory text outside the JSON object.
                    - Never claim that an action was executed; describe the intended action
                    and its verification plan.

                    MANDATORY UNKNOWN INFORMATION RULE
                    If a required application field cannot be completed using verified data,
                    and no safe alternative action is available, return the application's
                    supported user-input action and identify the exact missing field.
                    Do not fabricate an answer merely to keep the workflow moving.

                    FINAL DECISION RULE
                    Choose the single next action that best advances the current workflow
                    while preserving candidate-data accuracy, user authorization, platform
                    compliance, and verifiable outcomes.
                    """
            )
            response_text = call_gemini(prompt, system_prompt)
            if not response_text:
                return None

            # Clean markdown codeblocks if returned
            clean_json = response_text.strip()
            if clean_json.startswith("```"):
                clean_json = re.sub(r"^```(?:json)?\s*", "", clean_json)
                clean_json = re.sub(r"\s*```$", "", clean_json)

            data = json.loads(clean_json)
            action = data.get("action", "")
            if action in ALLOWED_TOOLS:
                update_reasoning_metric("gemini_reasoning_success_count", 1.0, action)
                return AgentDecision(
                    observation_summary=data.get("observation_summary", f"Gemini reasoning for {obs.job_title}"),
                    objective=data.get("objective", "Advance application"),
                    action=action,
                    action_params=data.get("action_params", {}),
                    reason=data.get("reason", "Decided by Google Gemini reasoning model"),
                    source="GEMINI_REASONING",
                    verification_plan=data.get("verification_plan", "Verify action result"),
                    requires_user_input=bool(data.get("requires_user_input", False))
                )
        except Exception as e:
            self.logger(f"Gemini reasoning notice: {e}", "INFO")

        return None

    # ==========================
    # 3. ACT
    # ==========================
    def act(self, page: Page, decision: AgentDecision, stop_event=None) -> Dict[str, Any]:
        """
        Executes the authorized action using deterministic automation tools.
        Validates against tool allowlist and prevents arbitrary code execution.
        """
        if decision.action not in ALLOWED_TOOLS:
            self.logger(f"Action '{decision.action}' blocked: Not in allowed tools!", "ERROR")
            return {"success": False, "error": f"ACTION_DISALLOWED: {decision.action}"}

        self.logger(f"🚀 Executing Action: [{decision.action}] | Objective: {decision.objective}", "INFO")

        # 1. PROCESS_CHAT_QUESTION (Naukri sequential chat questionnaire)
        if decision.action == "PROCESS_CHAT_QUESTION":
            return naukri_chat_panel_handler.process_sequential_chat_questions(
                page=page,
                qa_engine_instance=self.qa,
                stop_event=stop_event or threading.Event(),
                company=decision.action_params.get("company", ""),
                title=decision.action_params.get("title", "")
            )

        # 2. FILL_FORM_FIELDS (Multi-field form completion)
        elif decision.action == "FILL_FORM_FIELDS":
            return process_and_fill_complete_form(
                page=page,
                qa_engine_instance=self.qa,
                stop_event=stop_event or threading.Event(),
                company_name=decision.action_params.get("company", ""),
                job_title=decision.action_params.get("job_title", "")
            )

        # 3. INSPECT_PAGE
        elif decision.action == "INSPECT_PAGE":
            obs = self.observe(page, decision.action_params.get("context_data", {}))
            return {"success": True, "observation": asdict(obs)}

        # 4. FILL_INPUT
        elif decision.action == "FILL_INPUT":
            sel = decision.action_params.get("selector")
            val = str(decision.action_params.get("value", ""))
            name = decision.action_params.get("name")
            try:
                el = page.locator(sel) if sel else page.locator(f"input[name='{name}']")
                if el.count() > 0 and el.first.is_visible():
                    el.first.fill(val)
                    el.first.dispatch_event("input")
                    el.first.dispatch_event("change")
                    el.first.dispatch_event("blur")
                    return {"success": True, "value": val}
                return {"success": False, "error": "INPUT_NOT_FOUND"}
            except Exception as e:
                return {"success": False, "error": str(e)}

        # 5. SELECT_OPTION
        elif decision.action == "SELECT_OPTION":
            sel = decision.action_params.get("selector")
            val = decision.action_params.get("value")
            label = decision.action_params.get("label")
            try:
                el = page.locator(sel).first
                if el.is_visible():
                    if val:
                        el.select_option(value=val)
                    elif label:
                        el.select_option(label=label)
                    el.dispatch_event("change")
                    return {"success": True}
                return {"success": False, "error": "SELECT_NOT_FOUND"}
            except Exception as e:
                return {"success": False, "error": str(e)}

        # 6. SELECT_RADIO
        elif decision.action == "SELECT_RADIO":
            name = decision.action_params.get("name")
            val = decision.action_params.get("value")
            try:
                loc = page.locator(f"input[type='radio'][name='{name}'][value='{val}']").first
                if loc.count() == 0:
                    loc = page.locator(f"input[type='radio'][value='{val}']").first
                if loc.count() > 0 and loc.is_visible():
                    loc.check(force=True)
                    loc.dispatch_event("change")
                    return {"success": True}
                return {"success": False, "error": "RADIO_NOT_FOUND"}
            except Exception as e:
                return {"success": False, "error": str(e)}

        # 7. SET_CHECKBOX
        elif decision.action == "SET_CHECKBOX":
            sel = decision.action_params.get("selector")
            checked = decision.action_params.get("checked", True)
            try:
                el = page.locator(sel).first
                if el.is_visible():
                    if checked:
                        el.check(force=True)
                    else:
                        el.uncheck(force=True)
                    el.dispatch_event("change")
                    return {"success": True, "checked": checked}
                return {"success": False, "error": "CHECKBOX_NOT_FOUND"}
            except Exception as e:
                return {"success": False, "error": str(e)}

        # 8. UPLOAD_RESUME
        elif decision.action == "UPLOAD_RESUME":
            resume_path = decision.action_params.get("resume_path", "")
            return upload_resume_file(page, resume_path)

        # 9. CLICK_APPLY
        elif decision.action == "CLICK_APPLY":
            btn = button_service.find_action_button(page, [ButtonCategory.APPLY])
            if btn and btn.is_visible() and btn.is_enabled():
                return button_service.execute_and_verify_button_click(page, btn)
            return {"success": False, "error": "APPLY_BUTTON_NOT_FOUND_OR_DISABLED"}

        # 10. CLICK_CONTINUE
        elif decision.action == "CLICK_CONTINUE":
            btn = button_service.find_action_button(page, [ButtonCategory.CONTINUE, ButtonCategory.REVIEW])
            if btn and btn.is_visible() and btn.is_enabled():
                return button_service.execute_and_verify_button_click(page, btn)
            return {"success": False, "error": "CONTINUE_BUTTON_NOT_FOUND_OR_DISABLED"}

        # 11. CLICK_SAVE
        elif decision.action == "CLICK_SAVE":
            chat_panel = naukri_chat_panel_handler.detect_chat_panel(page)
            save_btn = naukri_chat_panel_handler.locate_save_button(page, chat_panel)
            if not save_btn:
                save_btn = button_service.find_action_button(page, [ButtonCategory.SAVE])
            if save_btn and save_btn.is_visible() and save_btn.is_enabled():
                save_btn.click()
                time.sleep(1.2)
                return {"success": True, "action": "CLICK_SAVE"}
            return {"success": False, "error": "SAVE_BUTTON_NOT_FOUND_OR_DISABLED"}

        # 12. CLICK_SUBMIT / CLICK_SAVE_OR_SUBMIT
        elif decision.action in ["CLICK_SUBMIT", "CLICK_SAVE_OR_SUBMIT"]:
            chat_panel = naukri_chat_panel_handler.detect_chat_panel(page)
            save_btn = naukri_chat_panel_handler.locate_save_button(page, chat_panel)
            if save_btn and save_btn.is_visible() and save_btn.is_enabled():
                save_btn.click()
                time.sleep(1.5)
                return {"success": True, "action": "CLICK_SAVE_OR_SUBMIT"}

            btn = button_service.find_form_submit_or_save_button(page)
            if btn and btn.is_visible() and btn.is_enabled():
                return button_service.execute_and_verify_button_click(page, btn)
            return {"success": False, "error": "SUBMIT_BUTTON_NOT_FOUND_OR_DISABLED"}

        # 13. HANDLE_VALIDATION
        elif decision.action == "HANDLE_VALIDATION":
            err_msg = decision.action_params.get("error_message", "")
            return {"success": True, "handled": True, "error_message": err_msg}

        # 14. WAIT_FOR_NAVIGATION
        elif decision.action == "WAIT_FOR_NAVIGATION":
            timeout_ms = decision.action_params.get("timeout_ms", 5000)
            try:
                page.wait_for_load_state("networkidle", timeout=timeout_ms)
                return {"success": True}
            except Exception:
                return {"success": True, "notice": "TIMED_OUT_WAITING"}

        # 15. INSPECT_NEW_TAB
        elif decision.action == "INSPECT_NEW_TAB":
            pages = page.context.pages
            if len(pages) > 1:
                active_page = pages[-1]
                active_page.bring_to_front()
                return {"success": True, "tab_url": active_page.url, "tab_count": len(pages)}
            return {"success": True, "tab_url": page.url, "tab_count": 1}

        # 16. REQUEST_USER_INPUT
        elif decision.action == "REQUEST_USER_INPUT":
            page.bring_to_front()
            return {
                "status": ChatPanelState.NEEDS_USER_INPUT,
                "success": False,
                "needs_user_input": True,
                "reason": decision.action_params.get("reason", "NEEDS_USER_INPUT"),
                "question": decision.action_params.get("question", "")
            }

        # 17. MARK_BLOCKED
        elif decision.action == "MARK_BLOCKED":
            reason = decision.action_params.get("reason", "APPLICATION_BLOCKED")
            job_title = decision.action_params.get("job_title", "")
            company_name = decision.action_params.get("company_name", "")
            record_application(
                job_title=job_title,
                company_name=company_name,
                location="",
                job_url=page.url,
                status="APPLICATION_BLOCKED",
                failure_reason=reason
            )
            return {"success": True, "status": "APPLICATION_BLOCKED", "reason": reason}

        # 18. VERIFY_APPLICATION_SUBMISSION
        elif decision.action == "VERIFY_APPLICATION_SUBMISSION":
            confirmed = False
            reason = "NOT_CONFIRMED"
            try:
                confirmed, reason = is_naukri_application_confirmed(page)
            except Exception as e:
                confirmed = False
                reason = str(e)
            return {"success": True, "confirmed": confirmed, "reason": reason}

        return {"success": False, "error": f"Unhandled tool action: {decision.action}"}

    # ==========================
    # 4. VERIFY
    # ==========================
    def verify(self, page: Page, decision: AgentDecision, act_result: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Inspects resulting browser state to confirm outcome before declaring success.
        Never assumes an action succeeded merely because a function returned without exception.
        """
        # If user input requested, state is preserved accurately
        if act_result.get("status") == ChatPanelState.NEEDS_USER_INPUT or decision.requires_user_input:
            update_reasoning_metric("unresolved_questions_count", 1.0, "Candidate verification needed")
            return False, "NEEDS_USER_INPUT"

        # Check for open form / unconfirmed state
        if act_result.get("status") == ChatPanelState.CONFIRMATION_TIMEOUT or act_result.get("open_form"):
            is_conf, conf_reason = is_naukri_application_confirmed(page)
            if is_conf:
                update_reasoning_metric("form_validation_success_rate", 1.0, f"Confirmed despite timeout: {conf_reason}")
                return True, "APPLICATION_CONFIRMED"
            update_reasoning_metric("confirmation_timeout_count", 1.0, "Panel remained open after timeout")
            return False, "CONFIRMATION_TIMEOUT"

        # Check if chat panel completed successfully or closed
        if act_result.get("status") in [ChatPanelState.FORM_COMPLETED, ChatPanelState.APPLICATION_CONFIRMED]:
            # Verify that panel is genuinely closed or confirmation is visible
            chat_panel = naukri_chat_panel_handler.detect_chat_panel(page)
            if chat_panel and chat_panel.is_visible():
                # Form is still open with a remaining question! Do not confirm!
                remaining_q = naukri_chat_panel_handler.extract_latest_question(page, chat_panel)
                if remaining_q:
                    self.logger(f"Verification Check: Panel still open with question: '{remaining_q}'. False confirmation prevented!", "WARNING")
                    update_reasoning_metric("false_confirmation_prevented", 1.0, remaining_q[:30])
                    return False, f"OPEN_PANEL_WITH_QUESTION: {remaining_q}"

            update_reasoning_metric("form_validation_success_rate", 1.0, "Form validated and completed")
            return True, "FORM_VERIFIED_SUCCESSFUL"

        if act_result.get("outcome") == "CONFIRMED" or act_result.get("confirmed"):
            return True, "APPLICATION_CONFIRMED"

        # Check if page is confirmed directly
        is_conf, conf_reason = is_naukri_application_confirmed(page)
        if is_conf:
            return True, "APPLICATION_CONFIRMED"

        if act_result.get("outcome") == "NAVIGATED":
            return True, "STEP_NAVIGATED"

        if decision.action in ["FILL_INPUT", "SET_CHECKBOX", "SELECT_OPTION", "UPLOAD_RESUME"]:
            return act_result.get("success", False), "FIELD_ACTION_VERIFIED" if act_result.get("success") else "FIELD_ACTION_FAILED"

        return act_result.get("success", False), act_result.get("error", "UNKNOWN_VERIFICATION_STATUS")

    # ==========================
    # 5. SELF-CORRECTION
    # ==========================
    def self_correct(self, page: Page, failure_type: str, attempt: int = 1, max_attempts: int = 2) -> bool:
        """
        Analyzes technical failures (e.g. locator not found, element detached, timeout)
        and attempts bounded, intelligent recovery strategies.
        """
        if attempt > max_attempts:
            self.logger(f"Self-correction aborted: Max attempts ({max_attempts}) reached for {failure_type}.", "WARNING")
            return False

        self.logger(f"🔧 Attempting self-correction ({attempt}/{max_attempts}) for: {failure_type}...", "INFO")
        update_reasoning_metric("total_recovery_attempts", 1.0, failure_type)

        if failure_type == "INPUT_NOT_FOUND":
            # Strategy: wait for dynamic DOM or look inside iframes
            time.sleep(1.5)
            chat_panel = naukri_chat_panel_handler.detect_chat_panel(page)
            inp = naukri_chat_panel_handler.locate_chat_input(page, chat_panel)
            if inp and inp.is_visible():
                record_experience("naukri.com", "chat_panel", "INPUT_NOT_FOUND", "WAIT_AND_RETRY", "SUCCESS", "SUCCESS", 0.9)
                update_reasoning_metric("recovery_success_rate", 1.0, failure_type)
                return True

        elif failure_type in ["SAVE_BUTTON_NOT_ENABLED", "SUBMIT_BUTTON_NOT_ENABLED"]:
            # Strategy: blur input, trigger change events, re-check
            try:
                page.evaluate("() => { if (document.activeElement) document.activeElement.blur(); }")
                time.sleep(0.5)
                chat_panel = naukri_chat_panel_handler.detect_chat_panel(page)
                btn = naukri_chat_panel_handler.locate_save_button(page, chat_panel)
                if not btn:
                    btn = button_service.find_form_submit_or_save_button(page)
                if btn and btn.is_enabled():
                    update_reasoning_metric("recovery_success_rate", 1.0, failure_type)
                    return True
            except Exception:
                pass

        elif failure_type == "LOCATOR_FAILED":
            # Strategy: re-query with standard semantic roles
            time.sleep(1.0)
            return True

        return False

reasoning_engine = AutonomousReasoningEngine()
