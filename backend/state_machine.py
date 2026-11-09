"""
Centralized Application State Machine & Status Lifecycle Manager
Single source of truth for all job application lifecycles across platforms
(LinkedIn Easy Apply, LinkedIn External, Naukri, NaukriGulf, Company Portals).

Statuses:
- DISCOVERED: Job card/posting identified in search results or listing
- ELIGIBILITY_CHECKED: Location, technology, and experience eligibility verified
- APPLYING: Application workflow initiated (modal or company tab opened)
- FORM_IN_PROGRESS: Application form fields actively being filled and validated
- FORM_COMPLETED: All form questions answered and verified pre-submission
- SUBMISSION_PENDING: Final submit button clicked, awaiting confirmation
- APPLIED: Verified submission confirmation evidence received (terminal success)
- SUBMITTED_PENDING_CONFIRMATION: Submit clicked or completed, confirmation uncertain (terminal pending)
- NEEDS_INPUT: Human intervention required (CAPTCHA, OTP, login, missing info)
- SKIPPED: Ineligible or intentionally skipped during eligibility evaluation
- FAILED: Technical or network exception during application execution
- ALREADY_APPLIED: Verified that candidate has already applied previously
"""

import os
import time
import json
from enum import Enum
from typing import Dict, Any, List, Optional, Tuple

try:
    from enum import EnumType as _EnumMetaClass
except ImportError:
    from enum import EnumMeta as _EnumMetaClass

class ApplicationStatusMeta(_EnumMetaClass):
    """
    Robust Metaclass for ApplicationStatus and ApplicationStage:
    Guarantees that ANY legacy stage or attribute lookup never raises AttributeError.
    If an unknown or legacy attribute is accessed, it dynamically maps it to a canonical status or string.
    """
    def __getattr__(cls, name):
        try:
            return super().__getattr__(name)
        except AttributeError:
            norm = normalize_application_status(name)
            try:
                return super().__getattr__(norm)
            except (AttributeError, KeyError):
                return name

class ApplicationStatus(str, Enum, metaclass=ApplicationStatusMeta):
    DISCOVERED = "DISCOVERED"
    ELIGIBILITY_CHECKED = "ELIGIBILITY_CHECKED"
    APPLYING = "APPLYING"
    FORM_IN_PROGRESS = "FORM_IN_PROGRESS"
    FORM_COMPLETED = "FORM_COMPLETED"
    SUBMISSION_PENDING = "SUBMISSION_PENDING"
    APPLIED = "APPLIED"
    SUBMITTED_PENDING_CONFIRMATION = "SUBMITTED_PENDING_CONFIRMATION"
    NEEDS_INPUT = "NEEDS_INPUT"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"
    ALREADY_APPLIED = "ALREADY_APPLIED"

    # Backward-compatibility alias references & historical pipeline stages
    APPLICATION_CONFIRMED = "APPLIED"
    APPLICATION_SKIPPED = "SKIPPED"
    APPLICATION_FAILED = "FAILED"
    NEEDS_USER_ACTION = "NEEDS_INPUT"
    NEEDS_USER_INPUT = "NEEDS_INPUT"
    REDIRECT_REVIEW = "SUBMITTED_PENDING_CONFIRMATION"
    APPLICATION_PENDING_CONFIRMATION = "SUBMITTED_PENDING_CONFIRMATION"
    JOB_VERIFIED = "ELIGIBILITY_CHECKED"
    APPLICATION_INITIATED = "APPLYING"
    APPLY_OPTION_DETECTED = "APPLYING"
    APPLICATION_OPENED = "APPLYING"
    EXTERNAL_APPLICATION_OPENED = "APPLYING"
    APPLY_OPTION_NOT_AVAILABLE = "SKIPPED"
    JOB_DETAILS_OPENED = "DISCOVERED"
    APPLY_CLICKED = "APPLYING"
    QUESTION_DETECTED = "FORM_IN_PROGRESS"
    QUESTIONS_DETECTED = "FORM_IN_PROGRESS"
    ANSWERS_GENERATED = "FORM_IN_PROGRESS"
    FORM_DETECTED = "FORM_IN_PROGRESS"
    FORM_OPENED = "FORM_IN_PROGRESS"
    FORM_FILLED = "FORM_COMPLETED"
    FORM_VALIDATED = "FORM_COMPLETED"
    FORM_SUBMITTED = "SUBMISSION_PENDING"
    APPLICATION_SUBMITTED = "SUBMISSION_PENDING"
    SUBMISSION_VERIFIED = "APPLIED"
    APPLICATION_SUBMITTED_CONFIRMED = "APPLIED"
    APPLICATION_ATTEMPTED_UNCONFIRMED = "SUBMITTED_PENDING_CONFIRMATION"
    CONFIRMATION_TIMEOUT = "FAILED"
    CONFIRMATION_UNCERTAIN = "SUBMITTED_PENDING_CONFIRMATION"
    APPLICATION_BLOCKED = "FAILED"
    DUPLICATE_JOB = "ALREADY_APPLIED"
    SUBMISSION_VERIFICATION = "SUBMISSION_PENDING"

# ApplicationStage alias for full backward compatibility across all modules
ApplicationStage = ApplicationStatus

# Status priority for anti-overwriting protection (Higher score = higher precedence)
STATUS_PRIORITY: Dict[str, int] = {
    "APPLIED": 100,
    "ALREADY_APPLIED": 95,
    "SUBMITTED_PENDING_CONFIRMATION": 80,
    "NEEDS_INPUT": 70,
    "SUBMISSION_PENDING": 65,
    "FORM_COMPLETED": 60,
    "FORM_IN_PROGRESS": 50,
    "APPLYING": 40,
    "ELIGIBILITY_CHECKED": 30,
    "DISCOVERED": 20,
    "SKIPPED": 10,
    "FAILED": 10,
}

def normalize_application_status(val: Any) -> str:
    """Normalizes any incoming legacy or current status string to the canonical 12 statuses."""
    if not val:
        return ApplicationStatus.DISCOVERED.value
    if hasattr(val, "value"):
        val = val.value
    val_upper = str(val).strip().upper()
    mapping = {
        "APPLICATION_CONFIRMED": "APPLIED",
        "APPLIED": "APPLIED",
        "ALREADY_APPLIED": "ALREADY_APPLIED",
        "SUBMITTED_PENDING_CONFIRMATION": "SUBMITTED_PENDING_CONFIRMATION",
        "APPLICATION_PENDING_CONFIRMATION": "SUBMITTED_PENDING_CONFIRMATION",
        "REDIRECT_REVIEW": "SUBMITTED_PENDING_CONFIRMATION",
        "NEEDS_INPUT": "NEEDS_INPUT",
        "NEEDS_USER_INPUT": "NEEDS_INPUT",
        "NEEDS_USER_ACTION": "NEEDS_INPUT",
        "SUBMISSION_PENDING": "SUBMISSION_PENDING",
        "SUBMISSION_VERIFIED": "APPLIED",
        "FORM_COMPLETED": "FORM_COMPLETED",
        "FORM_IN_PROGRESS": "FORM_IN_PROGRESS",
        "APPLYING": "APPLYING",
        "APPLICATION_OPENED": "APPLYING",
        "EXTERNAL_APPLICATION_OPENED": "APPLYING",
        "APPLY_OPTION_DETECTED": "APPLYING",
        "ELIGIBILITY_CHECKED": "ELIGIBILITY_CHECKED",
        "JOB_VERIFIED": "DISCOVERED",
        "DISCOVERED": "DISCOVERED",
        "JOB_FOUND": "DISCOVERED",
        "SKIPPED": "SKIPPED",
        "APPLICATION_SKIPPED": "SKIPPED",
        "APPLY_OPTION_NOT_AVAILABLE": "SKIPPED",
        "FAILED": "FAILED",
        "APPLICATION_FAILED": "FAILED",
        "CONFIRMATION_TIMEOUT": "FAILED"
    }
    return mapping.get(val_upper, val_upper)

def is_valid_status_transition(current_status: str, next_status: str) -> Tuple[bool, str]:
    """
    Strict transition validation.
    Enforces terminal state integrity and prevents accidental status overwriting.
    """
    c = normalize_application_status(current_status)
    n = normalize_application_status(next_status)

    # 1. Terminal State Protection: Once APPLIED or ALREADY_APPLIED, no downgrades allowed!
    if c in ("APPLIED", "ALREADY_APPLIED"):
        if n in ("APPLIED", "ALREADY_APPLIED"):
            return True, "Re-confirming applied status"
        return False, f"Illegal transition: Application is already permanently {c}. Cannot overwrite with {n}."

    # 2. SUBMITTED_PENDING_CONFIRMATION protection: Cannot downgrade to SKIPPED, FAILED, APPLYING, etc.
    if c == "SUBMITTED_PENDING_CONFIRMATION":
        if n in ("APPLIED", "NEEDS_INPUT", "SUBMITTED_PENDING_CONFIRMATION"):
            return True, f"Valid resolution from {c} to {n}"
        return False, f"Illegal transition: Submission was attempted ({c}). Cannot demote to {n}."

    # 3. NEEDS_INPUT protection: Cannot downgrade to SKIPPED or FAILED by background timeout
    if c == "NEEDS_INPUT":
        if n in ("APPLYING", "FORM_IN_PROGRESS", "FORM_COMPLETED", "SUBMISSION_PENDING", "SUBMITTED_PENDING_CONFIRMATION", "APPLIED", "NEEDS_INPUT", "FAILED"):
            return True, f"Resuming or resolving from {c}"
        return False, f"Illegal transition: Application is awaiting candidate action ({c}). Cannot demote to {n}."

    # 4. Standard sequential transitions
    VALID_NEXT = {
        "DISCOVERED": ["ELIGIBILITY_CHECKED", "SKIPPED", "FAILED", "ALREADY_APPLIED"],
        "ELIGIBILITY_CHECKED": ["APPLYING", "SKIPPED", "ALREADY_APPLIED", "FAILED"],
        "APPLYING": ["FORM_IN_PROGRESS", "SUBMISSION_PENDING", "NEEDS_INPUT", "FAILED", "ALREADY_APPLIED"],
        "FORM_IN_PROGRESS": ["FORM_COMPLETED", "NEEDS_INPUT", "FAILED"],
        "FORM_COMPLETED": ["SUBMISSION_PENDING", "SUBMITTED_PENDING_CONFIRMATION", "NEEDS_INPUT", "FAILED"],
        "SUBMISSION_PENDING": ["APPLIED", "SUBMITTED_PENDING_CONFIRMATION", "NEEDS_INPUT", "FAILED"],
        "SKIPPED": [],
        "FAILED": ["APPLYING"]  # Allow explicit retry
    }

    allowed = VALID_NEXT.get(c, [])
    if n in allowed or n == c:
        return True, "Valid sequential transition"

    # Priority advancement (e.g. verified evidence arrives directly)
    if STATUS_PRIORITY.get(n, 0) > STATUS_PRIORITY.get(c, 0):
        return True, f"Advancing from {c} to higher priority state {n}"

    return False, f"Invalid transition from {c} to {n}"


class ApplicationStateMachine:
    """
    Centralized Application State Machine Service:
    Manages and validates state transitions for an individual job application.
    Maintains an append-only status history with timestamps and evidence.
    """

    def __init__(self, job_info: Dict[str, Any] = None, bot_state=None, initial_status: str = "DISCOVERED"):
        self.job_info = job_info or {}
        self.bot_state = bot_state
        self.job_id = self.job_info.get("id", "") or self.job_info.get("job_id", "")
        self.title = self.job_info.get("title", "Unknown Title")
        self.company = self.job_info.get("company", "Unknown Company")
        self.url = self.job_info.get("url", "")
        self.history: List[Dict[str, Any]] = []

        norm_init = normalize_application_status(initial_status)
        try:
            self.current_state = ApplicationStatus(norm_init)
        except ValueError:
            self.current_state = ApplicationStatus.DISCOVERED

        # Record initial discovery event
        self._record_transition(
            from_state=None,
            to_state=self.current_state,
            reason="Job card discovered in search results",
            screenshot_path="",
            evidence={}
        )

    def transition(self, new_state: Any, reason: str = "",
                   screenshot_path: str = "", evidence: Optional[Dict[str, Any]] = None) -> ApplicationStatus:
        """
        Validates, executes, and records a state transition.
        Prevents illegal downgrades or status overwriting.
        """
        norm_next_str = normalize_application_status(new_state)
        current_str = self.current_state.value

        is_valid, explanation = is_valid_status_transition(current_str, norm_next_str)
        if not is_valid:
            warn_msg = f"🛑 [STATE MACHINE BLOCKED] {self.company} ({self.title}): Cannot transition {current_str} ➔ {norm_next_str} | Reason: {explanation}"
            if self.bot_state and hasattr(self.bot_state, "add_log"):
                self.bot_state.add_log(warn_msg, "WARNING")
            else:
                print(warn_msg)
            return self.current_state

        from_state = self.current_state
        try:
            self.current_state = ApplicationStatus(norm_next_str)
        except ValueError:
            self.current_state = ApplicationStatus(norm_next_str)

        self._record_transition(
            from_state=from_state,
            to_state=self.current_state,
            reason=reason,
            screenshot_path=screenshot_path,
            evidence=evidence or {}
        )
        return self.current_state

    def _record_transition(self, from_state: Optional[ApplicationStatus], to_state: ApplicationStatus,
                           reason: str, screenshot_path: str, evidence: Dict[str, Any]):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        from_val = from_state.value if from_state else None
        to_val = to_state.value if hasattr(to_state, "value") else str(to_state)

        entry = {
            "timestamp": timestamp,
            "job_id": self.job_id,
            "title": self.title,
            "company": self.company,
            "url": self.url,
            "from_state": from_val,
            "to_state": to_val,
            "reason": reason,
            "screenshot_path": screenshot_path,
            "evidence": evidence
        }
        self.history.append(entry)

        from_name = from_val or "START"
        to_name = to_val
        log_msg = f"🔄 [STATE MACHINE] {self.company} ({self.title}) [{self.job_id}]: {from_name} ➔ {to_name}"
        if reason:
            log_msg += f" | Reason: {reason}"
        if screenshot_path:
            log_msg += f" | Screenshot: {os.path.basename(screenshot_path)}"

        if self.bot_state and hasattr(self.bot_state, "add_log"):
            level = "SUCCESS" if to_name in ["APPLIED", "ALREADY_APPLIED"] else ("WARNING" if to_name in ["NEEDS_INPUT", "SKIPPED"] else "INFO")
            self.bot_state.add_log(log_msg, level)
        else:
            print(log_msg)

        try:
            from database import log_event
            log_event(log_msg, level="INFO")
        except Exception:
            pass

    def get_history(self) -> List[Dict[str, Any]]:
        return self.history

    def get_history_json(self) -> str:
        return json.dumps(self.history)

    def is_terminal(self) -> bool:
        return self.current_state in [
            ApplicationStatus.APPLIED,
            ApplicationStatus.ALREADY_APPLIED,
            ApplicationStatus.SUBMITTED_PENDING_CONFIRMATION,
            ApplicationStatus.SKIPPED,
            ApplicationStatus.FAILED
        ]
