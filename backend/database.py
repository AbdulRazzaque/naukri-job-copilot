import pymysql
from pymysql.cursors import DictCursor
import os
import re
import json
import time
from typing import List, Dict, Any, Optional, Tuple

from state_machine import (
    ApplicationStatus,
    ApplicationStage,
    STATUS_PRIORITY,
    normalize_application_status,
    is_valid_status_transition
)

DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_PORT = int(os.getenv("DB_PORT", 3306))
DB_NAME = os.getenv("DB_NAME", "naukri_copilot")

def get_connection(use_database=True):
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        port=DB_PORT,
        database=DB_NAME if use_database else None,
        cursorclass=DictCursor,
        autocommit=True
    )

def init_db():
    """Initializes the database and tables if they do not exist, and runs migrations."""
    conn = get_connection(use_database=False)
    with conn.cursor() as cursor:
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
    conn.close()

    conn = get_connection(use_database=True)
    with conn.cursor() as cursor:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS job_applications (
            id INT AUTO_INCREMENT PRIMARY KEY,
            job_title VARCHAR(255) NOT NULL,
            company_name VARCHAR(255) NOT NULL,
            location VARCHAR(255),
            experience_req VARCHAR(100),
            salary_offered VARCHAR(100),
            job_url TEXT,
            status VARCHAR(50) DEFAULT 'JOB_FOUND',
            apply_type VARCHAR(50) DEFAULT 'DIRECT_NAUKRI',
            match_score INT DEFAULT 85,
            notes TEXT,
            failure_reason TEXT,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # Migration 1: Ensure status column is VARCHAR(50) instead of restricted ENUM
        try:
            cursor.execute("ALTER TABLE job_applications MODIFY COLUMN status VARCHAR(50) DEFAULT 'JOB_FOUND';")
        except Exception as e:
            print(f"[DB MIGRATION NOTICE] status column modify: {e}")

        # Migration 2: Ensure failure_reason column exists
        try:
            cursor.execute("ALTER TABLE job_applications ADD COLUMN failure_reason TEXT;")
        except Exception:
            pass  # Already exists

        # Migration 3: Ensure platform column exists (NAUKRI or LINKEDIN)
        try:
            cursor.execute("ALTER TABLE job_applications ADD COLUMN platform VARCHAR(50) DEFAULT 'NAUKRI';")
        except Exception:
            pass  # Already exists

        # Migration 4: Ensure resume customization & JD matching columns exist
        for col_def in [
            "ADD COLUMN customized_resume_path VARCHAR(500)",
            "ADD COLUMN original_resume_path VARCHAR(500)",
            "ADD COLUMN cv_changes_json TEXT",
            "ADD COLUMN jd_match_analysis_json TEXT"
        ]:
            try:
                cursor.execute(f"ALTER TABLE job_applications {col_def};")
            except Exception:
                pass  # Already exists

        # Migration 5: Standardized application execution audit columns
        for col_def in [
            "ADD COLUMN execution_stage VARCHAR(100) DEFAULT 'DISCOVERED'",
            "ADD COLUMN skip_reason_code VARCHAR(100)",
            "ADD COLUMN detailed_explanation TEXT",
            "ADD COLUMN application_attempted BOOLEAN DEFAULT FALSE",
            "ADD COLUMN application_submitted BOOLEAN DEFAULT FALSE",
            "ADD COLUMN application_confirmed BOOLEAN DEFAULT FALSE",
            "ADD COLUMN error_message TEXT",
            "ADD COLUMN screenshot_reference VARCHAR(500)",
            "ADD COLUMN external_application_url VARCHAR(500)",
            "ADD COLUMN resume_upload_status VARCHAR(50) DEFAULT 'NOT_STARTED'",
            "ADD COLUMN requested_location VARCHAR(255)",
            "ADD COLUMN actual_browser_location VARCHAR(255)"
        ]:
            try:
                cursor.execute(f"ALTER TABLE job_applications {col_def};")
            except Exception:
                pass

        # Migration 6: Centralized Application Evidence & Anti-Overwriting Columns
        for col_def in [
            "ADD COLUMN confirmation_type VARCHAR(100)",
            "ADD COLUMN confirmation_message TEXT",
            "ADD COLUMN application_reference VARCHAR(255)",
            "ADD COLUMN submitted_at TIMESTAMP NULL",
            "ADD COLUMN last_attempt_at TIMESTAMP NULL",
            "ADD COLUMN last_error_code VARCHAR(100)",
            "ADD COLUMN last_error_message TEXT",
            "ADD COLUMN status_updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
            "ADD COLUMN status_history LONGTEXT"
        ]:
            try:
                cursor.execute(f"ALTER TABLE job_applications {col_def};")
            except Exception:
                pass

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_runs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            end_time TIMESTAMP NULL,
            applied_count INT DEFAULT 0,
            target_query VARCHAR(255),
            status VARCHAR(50) DEFAULT 'RUNNING'
        );
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS agent_logs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            level VARCHAR(20) DEFAULT 'INFO',
            message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS agent_experience_memory (
            id INT AUTO_INCREMENT PRIMARY KEY,
            domain VARCHAR(255) NOT NULL,
            page_type VARCHAR(100) DEFAULT 'SCREENING_DRAWER',
            problem_pattern VARCHAR(255) NOT NULL,
            action_taken VARCHAR(255) NOT NULL,
            recovery_strategy TEXT,
            result_status VARCHAR(50) DEFAULT 'SUCCESS',
            confidence FLOAT DEFAULT 1.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS agent_reasoning_metrics (
            id INT AUTO_INCREMENT PRIMARY KEY,
            metric_name VARCHAR(100) UNIQUE NOT NULL,
            metric_value FLOAT DEFAULT 0.0,
            context TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        );
        """)

        # Initialize default metrics if not present
        default_metrics = [
            ("question_detection_accuracy", 100.0),
            ("answer_insertion_success_rate", 100.0),
            ("form_validation_success_rate", 100.0),
            ("recovery_success_rate", 100.0),
            ("false_confirmation_count", 0.0),
            ("total_recovery_attempts", 0.0),
            ("unresolved_questions_count", 0.0)
        ]
        for mname, mval in default_metrics:
            try:
                cursor.execute("""
                    INSERT IGNORE INTO agent_reasoning_metrics (metric_name, metric_value) 
                    VALUES (%s, %s)
                """, (mname, mval))
            except Exception:
                pass

    conn.close()
    print("[DB] Database and tables verified/created successfully.")

def record_experience(domain: str, page_type: str, problem_pattern: str, action_taken: str, 
                      recovery_strategy: str = "", result_status: str = "SUCCESS", confidence: float = 1.0):
    """Stores successful and unsuccessful automation patterns in persistent experience memory."""
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO agent_experience_memory 
                (domain, page_type, problem_pattern, action_taken, recovery_strategy, result_status, confidence)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (domain, page_type, problem_pattern[:255], action_taken[:255], recovery_strategy, result_status, confidence))
        conn.close()
    except Exception as e:
        print(f"[DB] Failed to record experience: {e}")

def lookup_experience(domain: str, problem_pattern: str = "") -> List[Dict[str, Any]]:
    """Retrieves relevant past experiences to guide reasoning and self-correction."""
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            if problem_pattern:
                cursor.execute("""
                    SELECT * FROM agent_experience_memory 
                    WHERE domain = %s AND problem_pattern LIKE %s 
                    ORDER BY confidence DESC, created_at DESC 
                    LIMIT 5
                """, (domain, f"%{problem_pattern}%"))
            else:
                cursor.execute("""
                    SELECT * FROM agent_experience_memory 
                    WHERE domain = %s 
                    ORDER BY confidence DESC, created_at DESC 
                    LIMIT 5
                """, (domain,))
            rows = cursor.fetchall()
        conn.close()
        return rows or []
    except Exception as e:
        print(f"[DB] Failed to lookup experience: {e}")
        return []

def update_reasoning_metric(metric_name: str, increment_by: float = 1.0, context: str = ""):
    """Updates reasoning quality metrics in persistent storage."""
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO agent_reasoning_metrics (metric_name, metric_value, context)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE 
                    metric_value = metric_value + VALUES(metric_value),
                    context = VALUES(context)
            """, (metric_name, increment_by, context))
        conn.close()
    except Exception as e:
        print(f"[DB] Failed to update metric {metric_name}: {e}")

def get_reasoning_metrics() -> Dict[str, Any]:
    """Retrieves current reasoning quality metrics."""
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT metric_name, metric_value, context FROM agent_reasoning_metrics")
            rows = cursor.fetchall()
        conn.close()
        return {r["metric_name"]: r["metric_value"] for r in rows} if rows else {}
    except Exception as e:
        print(f"[DB] Failed to get metrics: {e}")
        return {}

def get_today_applied_count(platform: str = None) -> int:
    """Returns number of jobs successfully applied/submitted today (CURDATE), optionally filtered by platform."""
    conn = get_connection()
    with conn.cursor() as cursor:
        if platform and platform.upper() != "ALL":
            plat = platform.upper()
            if plat in ("NAUKRIGULF", "GULF"):
                cursor.execute("""
                    SELECT COUNT(*) as count 
                    FROM job_applications 
                    WHERE DATE(applied_at) = CURDATE() 
                      AND (status IN ('APPLIED', 'APPLICATION_CONFIRMED') OR (status = 'APPLICATION_PENDING_CONFIRMATION' AND application_submitted = 1))
                      AND UPPER(platform) IN ('NAUKRIGULF', 'GULF')
                """)
            else:
                cursor.execute("""
                    SELECT COUNT(*) as count 
                    FROM job_applications 
                    WHERE DATE(applied_at) = CURDATE() 
                      AND (status IN ('APPLIED', 'APPLICATION_CONFIRMED') OR (status = 'APPLICATION_PENDING_CONFIRMATION' AND application_submitted = 1))
                      AND UPPER(platform) = %s
                """, (plat,))
        else:
            cursor.execute("""
                SELECT COUNT(*) as count 
                FROM job_applications 
                WHERE DATE(applied_at) = CURDATE() 
                  AND (status IN ('APPLIED', 'APPLICATION_CONFIRMED') OR (status = 'APPLICATION_PENDING_CONFIRMATION' AND application_submitted = 1))
            """)
        row = cursor.fetchone()
        conn.close()
        return row["count"] if row else 0

def get_today_platform_counts() -> Dict[str, int]:
    """Returns today's confirmed application counts categorized per platform."""
    return {
        "NAUKRI": get_today_applied_count("NAUKRI"),
        "LINKEDIN": get_today_applied_count("LINKEDIN"),
        "NAUKRIGULF": get_today_applied_count("NAUKRIGULF"),
        "TOTAL": get_today_applied_count()
    }

def map_to_skip_reason_code(failure_reason: str, notes: str = "", match_score: int = None) -> str:
    """Standardizes arbitrary failure messages into official skipReasonCodes."""
    combined = f"{failure_reason or ''} {notes or ''}".lower()
    if "location_not_found" in combined or "location missing" in combined:
        return "LOCATION_NOT_FOUND"
    if any(k in combined for k in ["primary_specialization_mismatch", "specialization_mismatch", "dedicated python", "dedicated .net", "dedicated java", "dedicated c#"]):
        return "PRIMARY_SPECIALIZATION_MISMATCH"
    if any(k in combined for k in ["location", "outside candidate target", "region", "city"]):
        return "LOCATION_MISMATCH"
    if any(k in combined for k in ["experience", "years of experience"]):
        return "EXPERIENCE_MISMATCH"
    if any(k in combined for k in ["disqualified", "technology_not_allowed", "fundamental", "skill", "unverified specialization"]):
        return "REQUIRED_SKILL_MISSING"
    if any(k in combined for k in ["low_match_score", "low_ai_score", "not match software", "score <", "below 65%"]):
        if match_score is not None and match_score >= 65:
            return "REQUIRED_SKILL_MISSING" if failure_reason else "ELIGIBILITY_CRITERIA_UNMET"
        return "LOW_MATCH_SCORE"
    if any(k in combined for k in ["already applied", "already-applied"]):
        return "ALREADY_APPLIED"
    if any(k in combined for k in ["duplicate", "duplicate_job"]):
        return "DUPLICATE_JOB"
    if any(k in combined for k in ["login_required", "log in", "login to apply"]):
        return "LOGIN_REQUIRED"
    if any(k in combined for k in ["captcha", "turnstile", "recaptcha"]):
        return "CAPTCHA_REQUIRED"
    if any(k in combined for k in ["no_apply_button", "apply_not_found", "no active apply", "no active apply or easy apply button", "apply_option_not_available"]):
        return "APPLY_OPTION_NOT_AVAILABLE"
    if any(k in combined for k in ["needs_user_input", "user input", "verification", "stop_requested"]):
        return "USER_APPROVAL_REQUIRED"
    if any(k in combined for k in ["application_blocked", "timeout", "selector timeout", "exception", "crash"]):
        return "APPLICATION_BLOCKED"
    if any(k in combined for k in ["expired", "closed"]):
        return "JOB_EXPIRED"
    return "ELIGIBILITY_CRITERIA_UNMET"

def find_existing_application_record(cursor, job_url: str = "", company_name: str = "", job_title: str = "", external_url: str = "") -> Optional[Dict[str, Any]]:
    """Locates an existing record for this job using multiple robust identifiers."""
    conditions = []
    params = []
    
    if job_url:
        conditions.append("job_url = %s")
        params.append(job_url)
        clean_url = job_url.split("?")[0]
        if clean_url != job_url:
            conditions.append("job_url LIKE %s")
            params.append(f"{clean_url}%")
        m = re.search(r"/jobs/view/(\d+)", job_url)
        if m:
            extracted_id = m.group(1)
            conditions.append("(job_url LIKE %s OR external_application_url LIKE %s)")
            params.extend([f"%{extracted_id}%", f"%{extracted_id}%"])
            
    if external_url and external_url != "about:blank":
        clean_ext = external_url.split("?")[0].split("#")[0].rstrip("/")
        if clean_ext:
            conditions.append("external_application_url = %s")
            params.append(external_url)
            conditions.append("external_application_url LIKE %s")
            params.append(f"{clean_ext}%")
            
    if job_title and company_name:
        conditions.append("(LOWER(TRIM(job_title)) = LOWER(TRIM(%s)) AND LOWER(TRIM(company_name)) = LOWER(TRIM(%s)))")
        params.extend([job_title, company_name])

    if not conditions:
        return None

    sql = f"""
        SELECT id, status, execution_stage, application_attempted, application_submitted, 
               application_confirmed, confirmation_type, confirmation_message, status_history
        FROM job_applications 
        WHERE ({' OR '.join(conditions)})
        ORDER BY id DESC
        LIMIT 1
    """
    cursor.execute(sql, tuple(params))
    return cursor.fetchone()

def record_application(job_title: str, company_name: str, location: str, job_url: str, 
                       status: str = 'APPLIED', apply_type: str = 'DIRECT_NAUKRI', 
                       match_score: int = 85, notes: str = "", 
                       experience_req: str = "", salary_offered: str = "",
                       failure_reason: str = "", platform: str = "NAUKRI",
                       customized_resume_path: str = "", original_resume_path: str = "",
                       cv_changes_json: str = "", jd_match_analysis_json: str = "",
                       execution_stage: str = "", skip_reason_code: str = "",
                       detailed_explanation: str = "", application_attempted: bool = None,
                       application_submitted: bool = None, application_confirmed: bool = None,
                       error_message: str = "", screenshot_reference: str = "",
                       external_application_url: str = "", resume_upload_status: str = "NOT_STARTED",
                       requested_location: str = "", actual_browser_location: str = "",
                       confirmation_type: str = "", confirmation_message: str = "",
                       application_reference: str = "") -> int:
    canonical_status = normalize_application_status(status)

    # Enforce boolean consistency based on canonical status
    if canonical_status in ('APPLIED', 'ALREADY_APPLIED'):
        application_attempted = True if application_attempted is None else application_attempted
        application_submitted = True if application_submitted is None else application_submitted
        application_confirmed = True if application_confirmed is None else application_confirmed
        execution_stage = execution_stage or "SUBMISSION_VERIFIED"
        detailed_explanation = detailed_explanation or notes or "Successfully applied and confirmed."
        if not confirmation_type:
            confirmation_type = "VERIFIED_CONFIRMATION"
    elif canonical_status == 'SUBMITTED_PENDING_CONFIRMATION':
        application_attempted = True if application_attempted is None else application_attempted
        application_submitted = True if application_submitted is None else application_submitted
        application_confirmed = False if application_confirmed is None else application_confirmed
        execution_stage = execution_stage or "SUBMISSION_PENDING"
        detailed_explanation = detailed_explanation or notes or failure_reason or "Submission attempted; awaiting explicit confirmation."
    elif canonical_status == 'NEEDS_INPUT':
        application_attempted = True if application_attempted is None else application_attempted
        application_submitted = False if application_submitted is None else application_submitted
        application_confirmed = False if application_confirmed is None else application_confirmed
        execution_stage = execution_stage or "FORM_IN_PROGRESS"
        detailed_explanation = detailed_explanation or notes or failure_reason or "Human intervention required (CAPTCHA, OTP, login, or missing info)."
    elif canonical_status == 'FAILED':
        application_attempted = True if application_attempted is None else application_attempted
        application_submitted = False if application_submitted is None else application_submitted
        application_confirmed = False if application_confirmed is None else application_confirmed
        error_message = error_message or failure_reason or notes
        execution_stage = execution_stage or "APPLICATION_EXECUTION"
        if not skip_reason_code:
            skip_reason_code = "APPLICATION_BLOCKED"
        if not detailed_explanation:
            detailed_explanation = f"Application execution encountered error: {error_message}"
    elif canonical_status == 'SKIPPED':
        application_attempted = False if application_attempted is None else application_attempted
        application_submitted = False if application_submitted is None else application_submitted
        application_confirmed = False if application_confirmed is None else application_confirmed
        if not skip_reason_code:
            skip_reason_code = map_to_skip_reason_code(failure_reason, notes, match_score=match_score)
        if match_score is not None and match_score >= 65 and skip_reason_code == "LOW_MATCH_SCORE":
            skip_reason_code = "REQUIRED_SKILL_MISSING" if failure_reason else "ELIGIBILITY_CRITERIA_UNMET"
        if not detailed_explanation:
            detailed_explanation = notes or failure_reason or f"Skipped with code {skip_reason_code}."
        if not execution_stage:
            execution_stage = "ELIGIBILITY_VERIFICATION"
    else:
        application_attempted = False if application_attempted is None else application_attempted
        application_submitted = False if application_submitted is None else application_submitted
        application_confirmed = False if application_confirmed is None else application_confirmed
        execution_stage = execution_stage or "DISCOVERED"
        detailed_explanation = detailed_explanation or notes

    timestamp_str = time.strftime("%Y-%m-%d %H:%M:%S")

    conn = get_connection()
    with conn.cursor() as cursor:
        existing = find_existing_application_record(
            cursor=cursor,
            job_url=job_url,
            company_name=company_name,
            job_title=job_title,
            external_url=external_application_url
        )

        if existing:
            app_id = existing["id"]
            existing_status = normalize_application_status(existing.get("status"))

            is_valid, transition_reason = is_valid_status_transition(existing_status, canonical_status)
            if not is_valid:
                # Anti-Overwrite Guard: Block attempt to demote a confirmed or pending application!
                log_msg = f"🛑 [Anti-Overwrite Guard] Blocked attempt to overwrite application {app_id} ({company_name} - {job_title}) status '{existing_status}' with '{canonical_status}': {transition_reason}"
                print(log_msg)
                # Keep existing high-priority status, but update metadata non-destructively
                cursor.execute("""
                    UPDATE job_applications 
                    SET last_attempt_at = NOW(),
                        notes = CASE WHEN %s != '' THEN CONCAT(COALESCE(notes, ''), ' | ', %s) ELSE notes END
                    WHERE id = %s
                """, (notes, notes, app_id))
                conn.close()
                return app_id

            # Parse existing history
            curr_hist = []
            try:
                if existing.get("status_history"):
                    curr_hist = json.loads(existing["status_history"])
            except Exception:
                curr_hist = []
            curr_hist.append({
                "timestamp": timestamp_str,
                "from": existing_status,
                "to": canonical_status,
                "stage": execution_stage,
                "reason": notes or detailed_explanation
            })
            new_hist_json = json.dumps(curr_hist)

            # Atomic conditional update
            cursor.execute("""
                UPDATE job_applications
                SET status = %s,
                    execution_stage = %s,
                    application_attempted = GREATEST(COALESCE(application_attempted, 0), %s),
                    application_submitted = GREATEST(COALESCE(application_submitted, 0), %s),
                    application_confirmed = GREATEST(COALESCE(application_confirmed, 0), %s),
                    confirmation_type = COALESCE(NULLIF(%s, ''), confirmation_type),
                    confirmation_message = COALESCE(NULLIF(%s, ''), confirmation_message),
                    application_reference = COALESCE(NULLIF(%s, ''), application_reference),
                    submitted_at = CASE WHEN %s IN ('APPLIED', 'SUBMITTED_PENDING_CONFIRMATION') AND submitted_at IS NULL THEN NOW() ELSE submitted_at END,
                    last_attempt_at = NOW(),
                    last_error_code = COALESCE(NULLIF(%s, ''), last_error_code),
                    last_error_message = COALESCE(NULLIF(%s, ''), last_error_message),
                    notes = COALESCE(NULLIF(%s, ''), notes),
                    detailed_explanation = COALESCE(NULLIF(%s, ''), detailed_explanation),
                    external_application_url = COALESCE(NULLIF(%s, ''), external_application_url),
                    screenshot_reference = COALESCE(NULLIF(%s, ''), screenshot_reference),
                    resume_upload_status = COALESCE(NULLIF(%s, ''), resume_upload_status),
                    status_history = %s,
                    status_updated_at = NOW()
                WHERE id = %s
            """, (
                canonical_status, execution_stage,
                1 if application_attempted else 0,
                1 if application_submitted else 0,
                1 if application_confirmed else 0,
                confirmation_type, confirmation_message, application_reference,
                canonical_status,
                skip_reason_code or failure_reason,
                error_message or failure_reason,
                notes, detailed_explanation, external_application_url, screenshot_reference,
                resume_upload_status, new_hist_json, app_id
            ))
            conn.close()
            return app_id

        # Insert new record
        initial_history = json.dumps([{
            "timestamp": timestamp_str,
            "from": None,
            "to": canonical_status,
            "stage": execution_stage,
            "reason": notes or detailed_explanation
        }])

        cursor.execute("""
            INSERT INTO job_applications 
            (job_title, company_name, location, job_url, status, apply_type, match_score, notes, experience_req, salary_offered, failure_reason, platform,
             customized_resume_path, original_resume_path, cv_changes_json, jd_match_analysis_json,
             execution_stage, skip_reason_code, detailed_explanation, application_attempted, application_submitted, application_confirmed, error_message, screenshot_reference,
             external_application_url, resume_upload_status, requested_location, actual_browser_location,
             confirmation_type, confirmation_message, application_reference, submitted_at, last_attempt_at, last_error_code, last_error_message, status_history)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            job_title, company_name, location, job_url, canonical_status, apply_type, match_score, notes, experience_req, salary_offered, failure_reason, platform.upper(),
            customized_resume_path, original_resume_path, cv_changes_json, jd_match_analysis_json,
            execution_stage, skip_reason_code, detailed_explanation,
            1 if application_attempted else 0,
            1 if application_submitted else 0,
            1 if application_confirmed else 0,
            error_message, screenshot_reference,
            external_application_url, resume_upload_status, requested_location, actual_browser_location,
            confirmation_type, confirmation_message, application_reference,
            timestamp_str if canonical_status in ('APPLIED', 'SUBMITTED_PENDING_CONFIRMATION') else None,
            timestamp_str, skip_reason_code or failure_reason, error_message or failure_reason, initial_history
        ))
        app_id = cursor.lastrowid
        conn.close()
        return app_id

def update_application_status(app_id: int, new_status: str, reason: str = "",
                              confirmation_type: str = "", confirmation_message: str = "",
                              application_reference: str = "", screenshot_reference: str = "") -> bool:
    """
    Direct atomic status transition helper.
    Respects anti-overwriting constraints.
    """
    canonical_status = normalize_application_status(new_status)
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT id, status, status_history FROM job_applications WHERE id = %s", (app_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return False

        current_status = normalize_application_status(row.get("status"))
        is_valid, expl = is_valid_status_transition(current_status, canonical_status)
        if not is_valid:
            print(f"🛑 [Anti-Overwrite Guard] Blocked update_application_status for #{app_id}: {expl}")
            conn.close()
            return False

        curr_hist = []
        try:
            if row.get("status_history"):
                curr_hist = json.loads(row["status_history"])
        except Exception:
            curr_hist = []
        curr_hist.append({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "from": current_status,
            "to": canonical_status,
            "reason": reason
        })

        is_applied = canonical_status in ('APPLIED', 'ALREADY_APPLIED')
        is_pending = canonical_status == 'SUBMITTED_PENDING_CONFIRMATION'

        cursor.execute("""
            UPDATE job_applications
            SET status = %s,
                application_confirmed = CASE WHEN %s THEN 1 ELSE application_confirmed END,
                application_submitted = CASE WHEN %s OR %s THEN 1 ELSE application_submitted END,
                confirmation_type = COALESCE(NULLIF(%s, ''), confirmation_type),
                confirmation_message = COALESCE(NULLIF(%s, ''), confirmation_message),
                application_reference = COALESCE(NULLIF(%s, ''), application_reference),
                screenshot_reference = COALESCE(NULLIF(%s, ''), screenshot_reference),
                submitted_at = CASE WHEN (%s OR %s) AND submitted_at IS NULL THEN NOW() ELSE submitted_at END,
                status_history = %s,
                status_updated_at = NOW()
            WHERE id = %s
        """, (
            canonical_status,
            1 if is_applied else 0,
            1 if is_applied else 0,
            1 if is_pending else 0,
            confirmation_type, confirmation_message, application_reference, screenshot_reference,
            1 if is_applied else 0,
            1 if is_pending else 0,
            json.dumps(curr_hist), app_id
        ))
        conn.close()
        return True

def log_event(message: str, level: str = "INFO"):
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO agent_logs (level, message) VALUES (%s, %s)", (level, message))
        conn.close()
    except Exception as e:
        print(f"[{level}] {message} (DB log failed: {e})")

def normalize_job_title(t: str) -> str:
    """Normalizes job titles for fuzzy deduplication."""
    if not t:
        return ""
    t = t.lower().strip()
    t = re.sub(r"\(.*?\)", "", t)
    t = re.sub(r"[-–|/]\s*(dubai|mumbai|qatar|doha|india|uae|remote|hybrid|bangalore|pune|delhi|london|us|uk|level shoes).*", "", t, flags=re.I)
    t = re.sub(r"\bsr\.?\b", "senior", t)
    t = re.sub(r"\bjr\.?\b", "junior", t)
    t = re.sub(r"\bfull[\s-]?stack\b", "fullstack", t)
    t = re.sub(r"\b(engineer|programmer|coder)\b", "developer", t)
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()

def normalize_company_name(c: str) -> str:
    """Normalizes company names for fuzzy deduplication."""
    if not c:
        return ""
    c = c.lower().strip()
    c = re.sub(r"\b(technologies|technology|solutions|services|pvt|ltd|limited|inc|llc|group|corp|corporation)\b", "", c)
    c = re.sub(r"[^a-z0-9\s]", " ", c)
    return re.sub(r"\s+", " ", c).strip()

def check_already_applied_db(title: str = "", company: str = "", job_url: str = "", job_id: str = "", external_url: str = "", include_skipped: bool = True) -> bool:
    """
    Checks if a job record with this URL, ID, external destination URL, or title & company
    has already been processed (Applied, Confirmed, Pending, or Skipped).
    Prevents re-visiting or re-applying to the same job role or external portal.
    """
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            conditions = []
            params = []
            if job_url:
                conditions.append("job_url = %s")
                params.append(job_url)
                clean_url = job_url.split("?")[0]
                if clean_url != job_url:
                    conditions.append("job_url LIKE %s")
                    params.append(f"{clean_url}%")
                m = re.search(r"(?:/jobs/view/|currentJobId=)(\d{6,14})", job_url)
                if m and len(m.group(1)) >= 6:
                    extracted_id = m.group(1)
                    conditions.append("(job_url LIKE %s OR external_application_url LIKE %s)")
                    params.extend([f"%{extracted_id}%", f"%{extracted_id}%"])
            if job_id and len(str(job_id).strip()) >= 6:
                clean_jid = str(job_id).strip()
                conditions.append("(job_url LIKE %s OR external_application_url LIKE %s)")
                params.extend([f"%{clean_jid}%", f"%{clean_jid}%"])
            if external_url:
                clean_ext = external_url.split("?")[0].split("#")[0].rstrip("/")
                if clean_ext and clean_ext != "about:blank":
                    conditions.append("external_application_url = %s")
                    params.append(external_url)
                    conditions.append("external_application_url LIKE %s")
                    params.append(f"{clean_ext}%")
                    m_ext = re.search(r"https?://([^/]+/[^?#]+)", clean_ext)
                    if m_ext:
                        path_part = m_ext.group(1)
                        conditions.append("external_application_url LIKE %s")
                        params.append(f"%{path_part}%")
            if title and company:
                conditions.append("(LOWER(TRIM(job_title)) = LOWER(TRIM(%s)) AND LOWER(TRIM(company_name)) = LOWER(TRIM(%s)))")
                params.extend([title, company])

                # Token-based normalized title & company match
                clean_comp = company.strip().lower()
                clean_title = re.sub(r"\s*[-–—|(/].*$", "", title).strip()
                if clean_comp and len(clean_comp) >= 2 and clean_title and len(clean_title) >= 3:
                    conditions.append("(LOWER(company_name) LIKE %s AND LOWER(job_title) LIKE %s)")
                    params.extend([f"%{clean_comp}%", f"%{clean_title.lower()}%"])

                nc = normalize_company_name(company)
                if nc and nc != clean_comp and len(nc) >= 3 and clean_title and len(clean_title) >= 5:
                    conditions.append("(LOWER(company_name) LIKE %s AND LOWER(job_title) LIKE %s)")
                    params.extend([f"%{nc}%", f"%{clean_title.lower()}%"])

                nt = normalize_job_title(title)
                if nt and nc:
                    conditions.append("(LOWER(company_name) LIKE %s AND LOWER(job_title) LIKE %s)")
                    params.extend([f"%{nc}%", f"%{nt}%"])

            if not conditions:
                conn.close()
                return False

            if include_skipped:
                status_clause = """(
                    status IN (
                        'APPLIED', 'APPLICATION_CONFIRMED', 'ALREADY_APPLIED',
                        'SUBMITTED_PENDING_CONFIRMATION', 'APPLICATION_PENDING_CONFIRMATION',
                        'REDIRECT_REVIEW', 'NEEDS_INPUT', 'NEEDS_USER_INPUT', 'NEEDS_USER_ACTION',
                        'SKIPPED', 'APPLICATION_SKIPPED', 'FAILED', 'APPLICATION_FAILED',
                        'FORM_IN_PROGRESS', 'FORM_COMPLETED', 'SUBMISSION_PENDING', 'APPLYING', 'DISCOVERED', 'ELIGIBILITY_CHECKED'
                    )
                    OR (skip_reason_code IS NOT NULL AND skip_reason_code != '')
                    OR (application_submitted = 1)
                    OR (application_attempted = 1)
                )"""
            else:
                status_clause = """(
                    status IN (
                        'APPLIED', 'APPLICATION_CONFIRMED', 'ALREADY_APPLIED',
                        'SUBMITTED_PENDING_CONFIRMATION', 'APPLICATION_PENDING_CONFIRMATION',
                        'REDIRECT_REVIEW', 'NEEDS_INPUT', 'NEEDS_USER_INPUT', 'NEEDS_USER_ACTION'
                    )
                    OR (application_submitted = 1)
                )"""

            sql = f"""
                SELECT id FROM job_applications 
                WHERE ({' OR '.join(conditions)})
                  AND {status_clause}
                LIMIT 1
            """
            cursor.execute(sql, tuple(params))
            row = cursor.fetchone()
            conn.close()
            return row is not None
    except Exception as e:
        print(f"[DB] check_already_applied_db error: {e}")
        return False

# Backward-compatibility alias
is_job_already_processed = check_already_applied_db

def get_recent_applications(limit: int = 50) -> List[Dict[str, Any]]:
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT * FROM job_applications 
            ORDER BY applied_at DESC 
            LIMIT %s
        """, (limit,))
        rows = cursor.fetchall() or []
        conn.close()

        # Augment with both canonical camelCase and snake_case properties
        for r in rows:
            canonical_status = normalize_application_status(r.get("status"))
            r["applicationStatus"] = canonical_status
            r["applicationStage"] = r.get("execution_stage") or "DISCOVERED"
            r["submissionAttempted"] = bool(r.get("application_attempted"))
            r["submissionConfirmed"] = bool(r.get("application_confirmed"))
            r["confirmationType"] = r.get("confirmation_type")
            r["confirmationMessage"] = r.get("confirmation_message")
            r["applicationReference"] = r.get("application_reference")
            r["submittedAt"] = r.get("submitted_at")
            r["lastAttemptAt"] = r.get("last_attempt_at")
            r["lastErrorCode"] = r.get("last_error_code") or r.get("skip_reason_code")
            r["lastErrorMessage"] = r.get("last_error_message") or r.get("error_message") or r.get("failure_reason")
            r["externalApplicationUrl"] = r.get("external_application_url")
            r["sourceJobUrl"] = r.get("job_url")
            r["statusUpdatedAt"] = r.get("status_updated_at")
            r["statusHistory"] = r.get("status_history")
            # Preserve status as canonical
            r["status"] = canonical_status

        return rows

def get_dashboard_stats() -> Dict[str, Any]:
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT COUNT(*) as total 
            FROM job_applications 
            WHERE (status IN ('APPLIED', 'APPLICATION_CONFIRMED', 'ALREADY_APPLIED') 
               OR (status IN ('SUBMITTED_PENDING_CONFIRMATION', 'APPLICATION_PENDING_CONFIRMATION', 'REDIRECT_REVIEW') AND application_submitted = 1))
        """)
        total_applied = cursor.fetchone()["total"]

        cursor.execute("""
            SELECT COUNT(*) as today 
            FROM job_applications 
            WHERE (DATE(applied_at) = CURDATE() OR (submitted_at IS NOT NULL AND DATE(submitted_at) = CURDATE())) 
              AND (status IN ('APPLIED', 'APPLICATION_CONFIRMED', 'ALREADY_APPLIED') 
               OR (status IN ('SUBMITTED_PENDING_CONFIRMATION', 'APPLICATION_PENDING_CONFIRMATION', 'REDIRECT_REVIEW') AND application_submitted = 1))
        """)
        today_applied = cursor.fetchone()["today"]

        cursor.execute("SELECT COUNT(*) as redirect FROM job_applications WHERE status IN ('REDIRECT_REVIEW', 'APPLICATION_PENDING_CONFIRMATION', 'SUBMITTED_PENDING_CONFIRMATION')")
        total_redirects = cursor.fetchone()["redirect"]

        cursor.execute("SELECT COUNT(*) as failed FROM job_applications WHERE status IN ('FAILED', 'APPLICATION_FAILED', 'CONFIRMATION_TIMEOUT')")
        total_failed = cursor.fetchone()["failed"]

        cursor.execute("SELECT COUNT(*) as needs_input FROM job_applications WHERE status IN ('NEEDS_INPUT', 'NEEDS_USER_INPUT', 'NEEDS_USER_ACTION')")
        total_needs_input = cursor.fetchone()["needs_input"]

        cursor.execute("SELECT COUNT(*) as blocked FROM job_applications WHERE status IN ('APPLICATION_BLOCKED', 'BLOCKED')")
        total_blocked = cursor.fetchone()["blocked"]

        cursor.execute("SELECT COUNT(*) as completed FROM job_applications WHERE status IN ('FORM_COMPLETED', 'APPLICATION_CONFIRMED', 'APPLIED', 'FORM_SUBMITTED', 'ALREADY_APPLIED')")
        total_completed = cursor.fetchone()["completed"]

        # Aggregate common failure causes
        cursor.execute("""
            SELECT failure_reason, COUNT(*) as count 
            FROM job_applications 
            WHERE failure_reason IS NOT NULL AND failure_reason != '' AND TRIM(failure_reason) != ''
            GROUP BY failure_reason 
            ORDER BY count DESC 
            LIMIT 5
        """)
        common_causes = cursor.fetchall() or []

        naukri_applied = 0
        linkedin_applied = 0
        naukrigulf_applied = 0

        try:
            # All-time applied counts per platform
            cursor.execute("""
                SELECT COUNT(*) as cnt 
                FROM job_applications 
                WHERE UPPER(platform) = 'NAUKRI' 
                  AND (status IN ('APPLIED', 'APPLICATION_CONFIRMED', 'ALREADY_APPLIED') OR (status IN ('SUBMITTED_PENDING_CONFIRMATION', 'APPLICATION_PENDING_CONFIRMATION', 'REDIRECT_REVIEW') AND application_submitted = 1))
            """)
            naukri_applied = cursor.fetchone()["cnt"]

            cursor.execute("""
                SELECT COUNT(*) as cnt 
                FROM job_applications 
                WHERE UPPER(platform) = 'LINKEDIN' 
                  AND (status IN ('APPLIED', 'APPLICATION_CONFIRMED', 'ALREADY_APPLIED') OR (status IN ('SUBMITTED_PENDING_CONFIRMATION', 'APPLICATION_PENDING_CONFIRMATION', 'REDIRECT_REVIEW') AND application_submitted = 1))
            """)
            linkedin_applied = cursor.fetchone()["cnt"]

            cursor.execute("""
                SELECT COUNT(*) as cnt 
                FROM job_applications 
                WHERE UPPER(platform) IN ('NAUKRIGULF', 'GULF') 
                  AND (status IN ('APPLIED', 'APPLICATION_CONFIRMED', 'ALREADY_APPLIED') OR (status IN ('SUBMITTED_PENDING_CONFIRMATION', 'APPLICATION_PENDING_CONFIRMATION', 'REDIRECT_REVIEW') AND application_submitted = 1))
            """)
            naukrigulf_applied = cursor.fetchone()["cnt"]

            # Today's applied counts per platform (CURDATE) using centralized get_today_applied_count
            today_naukri = get_today_applied_count("NAUKRI")
            today_linkedin = get_today_applied_count("LINKEDIN")
            today_naukrigulf = get_today_applied_count("NAUKRIGULF")
        except Exception:
            naukri_applied = total_applied
            linkedin_applied = 0
            naukrigulf_applied = 0
            today_naukri = 0
            today_linkedin = 0
            today_naukrigulf = 0

        conn.close()
        return {
            # Legacy metrics for existing frontend components
            "total_applied": total_applied,
            "today_applied": today_applied,
            "daily_safe_limit": 135,
            "remaining_today": max(0, 135 - today_applied),
            "external_redirects": total_redirects,
            "failed_attempts": total_failed,
            "needs_user_input": total_needs_input,
            # Platform breakdown metrics (All-time)
            "naukri_applied": naukri_applied,
            "linkedin_applied": linkedin_applied,
            "naukrigulf_applied": naukrigulf_applied,
            # Individual Daily Platform Quotas & Progress
            "today_naukri": today_naukri,
            "today_linkedin": today_linkedin,
            "today_naukrigulf": today_naukrigulf,
            "quota_naukri": 45,
            "quota_linkedin": 45,
            "quota_naukrigulf": 45,
            "remaining_naukri": max(0, 45 - today_naukri),
            "remaining_linkedin": max(0, 45 - today_linkedin),
            "remaining_naukrigulf": max(0, 45 - today_naukrigulf),
            # Enhanced dashboard summary metrics
            "completed_applications": total_completed,
            "confirmed_submissions": total_applied,
            "pending_user_input": total_needs_input,
            "blocked_applications": total_blocked,
            "failed_applications": total_failed,
            "common_failure_causes": common_causes
        }

def reconcile_existing_records() -> Dict[str, Any]:
    """
    Reconciles existing records according to user specifications (Section 8):
    1. Lead Software Engineer – Atain:
       Easy Apply form completed, Chrome kept open for review.
       Reconciles stale SKIPPED row (1853) and pending confirmation row (1946) to NEEDS_INPUT ("Requires Candidate Action: Easy Apply form completed, tab kept open in Chrome").
    2. Senior MERN Stack Engineer – Ajackus (id 1947):
       Reconciles to NEEDS_INPUT ("Requires Candidate Action: Airtable form requires candidate verification").
    3. Full Stack Developer – IRIS Business Services (id 1944):
       Reconciles to NEEDS_INPUT ("Requires Candidate Action: CAPTCHA verification required in open browser window").
    4. Sokin (rows 1875, 1894, etc.):
       Confirmed received and under review by Sokin career portal. Ensure APPLIED.
    5. All records with APPLICATION_FORM_NOT_FOUND:
       Clarifies status and ensures they are classified accurately.
    6. All records where submission was attempted (application_submitted = 1) but confirmation was uncertain:
       Ensure status is SUBMITTED_PENDING_CONFIRMATION, never SKIPPED.
    """
    conn = get_connection()
    reconciled_count = 0
    details = []
    with conn.cursor() as cursor:
        # 1. Lead Software Engineer – Atain
        cursor.execute("""
            UPDATE job_applications
            SET status = 'NEEDS_INPUT',
                execution_stage = 'FORM_COMPLETED',
                skip_reason_code = 'USER_APPROVAL_REQUIRED',
                failure_reason = 'USER_CONFIRMATION_REQUIRED',
                notes = 'Easy Apply form completed. Tab kept open in Chrome for candidate confirmation.',
                detailed_explanation = 'Easy Apply multi-step modal completed; preserved open in Chrome for candidate review and final submission.',
                application_attempted = 1,
                application_submitted = 0,
                application_confirmed = 0
            WHERE company_name LIKE '%Atain%'
        """)
        if cursor.rowcount > 0:
            reconciled_count += cursor.rowcount
            details.append(f"Reconciled {cursor.rowcount} Atain record(s) to NEEDS_INPUT (Form completed, tab open in Chrome)")

        # 2. Senior MERN Stack Engineer – Ajackus
        cursor.execute("""
            UPDATE job_applications
            SET status = 'NEEDS_INPUT',
                execution_stage = 'FORM_IN_PROGRESS',
                skip_reason_code = 'MISSING_REQUIRED_INFORMATION',
                failure_reason = 'MISSING_REQUIRED_INFORMATION',
                notes = 'Form requires candidate verification: Airtable required field verification. Tab kept open in Chrome.',
                detailed_explanation = 'Airtable external application form paused for candidate field verification. Tab left open in Chrome.',
                application_attempted = 1,
                application_submitted = 0,
                application_confirmed = 0
            WHERE company_name LIKE '%Ajackus%'
        """)
        if cursor.rowcount > 0:
            reconciled_count += cursor.rowcount
            details.append(f"Reconciled {cursor.rowcount} Ajackus record(s) to NEEDS_INPUT (Airtable form verification)")

        # 3. Full Stack Developer – IRIS Business Services
        cursor.execute("""
            UPDATE job_applications
            SET status = 'NEEDS_INPUT',
                execution_stage = 'FORM_IN_PROGRESS',
                skip_reason_code = 'CAPTCHA_REQUIRED',
                failure_reason = 'CAPTCHA_REQUIRED',
                notes = 'Form requires candidate verification: CAPTCHA_REQUIRED: Human verification required. Field kept empty in Chrome window. Tab kept open.',
                detailed_explanation = 'Keka careers portal presented CAPTCHA verification. Form kept open in Chrome for user to complete.',
                application_attempted = 1,
                application_submitted = 0,
                application_confirmed = 0
            WHERE company_name LIKE '%IRIS%'
        """)
        if cursor.rowcount > 0:
            reconciled_count += cursor.rowcount
            details.append(f"Reconciled {cursor.rowcount} IRIS Business Services record(s) to NEEDS_INPUT (CAPTCHA required)")

        # 3.5 Spurious EXTERNAL_APPLICATION_OPENED Crash Cleanup
        cursor.execute("""
            DELETE FROM job_applications
            WHERE error_message LIKE '%EXTERNAL_APPLICATION_OPENED%'
        """)
        if cursor.rowcount > 0:
            reconciled_count += cursor.rowcount
            details.append(f"Cleaned up {cursor.rowcount} spurious crash record(s) from EXTERNAL_APPLICATION_OPENED exception.")

        # 4. Sokin confirmed records
        cursor.execute("""
            UPDATE job_applications
            SET status = 'APPLIED',
                execution_stage = 'SUBMISSION_VERIFIED',
                application_attempted = 1,
                application_submitted = 1,
                application_confirmed = 1,
                confirmation_type = 'PORTAL_UNDER_REVIEW_BANNER',
                confirmation_message = 'Sokin career portal verified application received and currently under review.',
                skip_reason_code = NULL,
                failure_reason = NULL
            WHERE company_name LIKE '%Sokin%' 
              AND (status IN ('APPLICATION_CONFIRMED', 'APPLIED') OR external_application_url LIKE '%sokin%')
        """)
        if cursor.rowcount > 0:
            reconciled_count += cursor.rowcount
            details.append(f"Reconciled {cursor.rowcount} Sokin record(s) to APPLIED (Confirmed under review on portal)")

        # 5. All records where submission was attempted but confirmation was not stored
        cursor.execute("""
            UPDATE job_applications
            SET status = 'SUBMITTED_PENDING_CONFIRMATION',
                execution_stage = 'SUBMISSION_PENDING',
                detailed_explanation = 'Submission action occurred, but final confirmation is pending verification.'
            WHERE application_submitted = 1 
              AND application_confirmed = 0 
              AND status IN ('SKIPPED', 'APPLICATION_SKIPPED', 'FAILED', 'APPLICATION_FAILED', 'REDIRECT_REVIEW')
        """)
        if cursor.rowcount > 0:
            reconciled_count += cursor.rowcount
            details.append(f"Reconciled {cursor.rowcount} record(s) with attempted submission to SUBMITTED_PENDING_CONFIRMATION")

        # 6. Normalize legacy statuses across all records
        cursor.execute("UPDATE job_applications SET status = 'APPLIED' WHERE status = 'APPLICATION_CONFIRMED'")
        cursor.execute("UPDATE job_applications SET status = 'SKIPPED' WHERE status = 'APPLICATION_SKIPPED'")
        cursor.execute("UPDATE job_applications SET status = 'FAILED' WHERE status = 'APPLICATION_FAILED'")
        cursor.execute("UPDATE job_applications SET status = 'NEEDS_INPUT' WHERE status IN ('NEEDS_USER_INPUT', 'NEEDS_USER_ACTION')")
        cursor.execute("UPDATE job_applications SET status = 'SUBMITTED_PENDING_CONFIRMATION' WHERE status = 'APPLICATION_PENDING_CONFIRMATION'")

    conn.close()
    return {"reconciled_count": reconciled_count, "details": details}

def log_application_contact_audit(job_id: str, company_name: str, job_title: str,
                                  job_location: str, detected_country: str,
                                  candidate_profile: str, country_code: str,
                                  phone_validation: str = "PASSED",
                                  location_validation: str = "PASSED",
                                  submission_status: str = "SUBMITTED",
                                  masked_phone: str = "") -> None:
    """
    Records standardized Country-Based Contact & Location Audit entry (Section 8).
    Always masks candidate phone numbers in ordinary dashboard logs.
    """
    log_msg = (
        f"📝 [CONTACT AUDIT] JobID: {job_id or 'N/A'} | Company: {company_name} | "
        f"Title: {job_title} | Location: {job_location} | Country: {detected_country} | "
        f"Profile: {candidate_profile} | CountryCode: {country_code} | "
        f"Phone: {masked_phone} | PhoneValidation: {phone_validation} | "
        f"LocationValidation: {location_validation} | Status: {submission_status}"
    )
    log_event(log_msg, level="SUCCESS" if submission_status in ("SUBMITTED", "CONFIRMED", "APPLICATION_CONFIRMED") else "INFO")

def format_final_application_report(company_name: str, job_title: str, job_location: str = "",
                                    platform: str = "LinkedIn", application_type: str = "Easy Apply",
                                    resume_status: str = "Uploaded", phone_number: str = "+91 ******4663",
                                    country_code: str = "+91", email_verification: str = "Not Required",
                                    form_validation: str = "Passed", application_status: str = "Yes",
                                    jd_match: str = "85%", resume_customized: str = "Yes",
                                    resume_uploaded: str = "Yes", submission_verified: str = "Yes",
                                    pending_action: str = "None",
                                    detected_country: str = "India",
                                    candidate_profile: str = "INDIA",
                                    phone_validation: str = "PASSED",
                                    location_validation: str = "PASSED") -> str:
    """
    Mandatory Job Application Execution Report (Section 7 standard table format).
    """
    from datetime import datetime
    app_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Normalize application submitted status to Yes / No
    sub_val = "Yes" if any(w in application_status.lower() for w in ["submitted", "applied", "confirmed", "yes", "success"]) else application_status

    report = f"""
### Final Application Report
| Field | Details |
|---|---|
| Platform | {platform} |
| Company | {company_name or 'N/A'} |
| Job Title | {job_title or 'N/A'} |
| Location | {job_location or 'N/A'} |
| Detected Country | {detected_country} |
| Candidate Profile | {candidate_profile} |
| Selected Country Code | {country_code} |
| Contact Phone | {phone_number} |
| Phone Validation | {phone_validation} |
| Location Validation | {location_validation} |
| JD Match | {jd_match} |
| Apply Option | {application_type} |
| Resume Customized | {resume_customized} |
| Resume Uploaded | {resume_uploaded} |
| Application Submitted | {sub_val} |
| Submission Verified | {submission_verified} |
| Pending Action | {pending_action} |
"""
    return report.strip()

if __name__ == "__main__":
    init_db()
