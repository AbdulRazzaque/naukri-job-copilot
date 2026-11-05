import pymysql
from pymysql.cursors import DictCursor
import os
from typing import List, Dict, Any, Optional

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
    """Returns number of jobs successfully applied today (CURDATE), optionally filtered by platform."""
    conn = get_connection()
    with conn.cursor() as cursor:
        if platform and platform.upper() != "ALL":
            plat = platform.upper()
            if plat in ("NAUKRIGULF", "GULF"):
                cursor.execute("""
                    SELECT COUNT(*) as count 
                    FROM job_applications 
                    WHERE DATE(applied_at) = CURDATE() 
                      AND status IN ('APPLIED', 'APPLICATION_CONFIRMED')
                      AND UPPER(platform) IN ('NAUKRIGULF', 'GULF')
                """)
            else:
                cursor.execute("""
                    SELECT COUNT(*) as count 
                    FROM job_applications 
                    WHERE DATE(applied_at) = CURDATE() 
                      AND status IN ('APPLIED', 'APPLICATION_CONFIRMED')
                      AND UPPER(platform) = %s
                """, (plat,))
        else:
            cursor.execute("""
                SELECT COUNT(*) as count 
                FROM job_applications 
                WHERE DATE(applied_at) = CURDATE() 
                  AND status IN ('APPLIED', 'APPLICATION_CONFIRMED')
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

def record_application(job_title: str, company_name: str, location: str, job_url: str, 
                       status: str = 'APPLICATION_CONFIRMED', apply_type: str = 'DIRECT_NAUKRI', 
                       match_score: int = 85, notes: str = "", 
                       experience_req: str = "", salary_offered: str = "",
                       failure_reason: str = "", platform: str = "NAUKRI") -> int:
    conn = get_connection()
    with conn.cursor() as cursor:
        try:
            cursor.execute("""
                INSERT INTO job_applications 
                (job_title, company_name, location, job_url, status, apply_type, match_score, notes, experience_req, salary_offered, failure_reason, platform)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (job_title, company_name, location, job_url, status, apply_type, match_score, notes, experience_req, salary_offered, failure_reason, platform.upper()))
        except Exception:
            # Fallback if platform column is not present
            try:
                cursor.execute("""
                    INSERT INTO job_applications 
                    (job_title, company_name, location, job_url, status, apply_type, match_score, notes, experience_req, salary_offered, failure_reason)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (job_title, company_name, location, job_url, status, apply_type, match_score, notes, experience_req, salary_offered, failure_reason))
            except Exception:
                # Fallback if failure_reason is also not present
                combined_notes = f"[{platform.upper()}] {notes} | Failure: {failure_reason}".strip(" |") if failure_reason else f"[{platform.upper()}] {notes}"
                cursor.execute("""
                    INSERT INTO job_applications 
                    (job_title, company_name, location, job_url, status, apply_type, match_score, notes, experience_req, salary_offered)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (job_title, company_name, location, job_url, status, apply_type, match_score, combined_notes, experience_req, salary_offered))

        app_id = cursor.lastrowid
        conn.close()
        return app_id

def log_event(message: str, level: str = "INFO"):
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO agent_logs (level, message) VALUES (%s, %s)", (level, message))
        conn.close()
    except Exception as e:
        print(f"[{level}] {message} (DB log failed: {e})")

def get_recent_applications(limit: int = 50) -> List[Dict[str, Any]]:
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT * FROM job_applications 
            ORDER BY applied_at DESC 
            LIMIT %s
        """, (limit,))
        rows = cursor.fetchall()
        conn.close()
        return rows

def get_dashboard_stats() -> Dict[str, Any]:
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) as total FROM job_applications WHERE status IN ('APPLIED', 'APPLICATION_CONFIRMED')")
        total_applied = cursor.fetchone()["total"]

        cursor.execute("SELECT COUNT(*) as today FROM job_applications WHERE DATE(applied_at) = CURDATE() AND status IN ('APPLIED', 'APPLICATION_CONFIRMED')")
        today_applied = cursor.fetchone()["today"]

        cursor.execute("SELECT COUNT(*) as redirect FROM job_applications WHERE status IN ('REDIRECT_REVIEW', 'APPLICATION_PENDING_CONFIRMATION')")
        total_redirects = cursor.fetchone()["redirect"]

        cursor.execute("SELECT COUNT(*) as failed FROM job_applications WHERE status IN ('FAILED', 'APPLICATION_FAILED', 'CONFIRMATION_TIMEOUT')")
        total_failed = cursor.fetchone()["failed"]

        cursor.execute("SELECT COUNT(*) as needs_input FROM job_applications WHERE status IN ('NEEDS_USER_INPUT')")
        total_needs_input = cursor.fetchone()["needs_input"]

        cursor.execute("SELECT COUNT(*) as blocked FROM job_applications WHERE status IN ('APPLICATION_BLOCKED', 'BLOCKED')")
        total_blocked = cursor.fetchone()["blocked"]

        cursor.execute("SELECT COUNT(*) as completed FROM job_applications WHERE status IN ('FORM_COMPLETED', 'APPLICATION_CONFIRMED', 'APPLIED', 'FORM_SUBMITTED')")
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
        today_naukri = 0
        today_linkedin = 0
        today_naukrigulf = 0

        try:
            # All-time applied counts per platform
            cursor.execute("SELECT COUNT(*) as cnt FROM job_applications WHERE UPPER(platform) = 'NAUKRI' AND status IN ('APPLIED', 'APPLICATION_CONFIRMED')")
            naukri_applied = cursor.fetchone()["cnt"]
            cursor.execute("SELECT COUNT(*) as cnt FROM job_applications WHERE UPPER(platform) = 'LINKEDIN' AND status IN ('APPLIED', 'APPLICATION_CONFIRMED')")
            linkedin_applied = cursor.fetchone()["cnt"]
            cursor.execute("SELECT COUNT(*) as cnt FROM job_applications WHERE UPPER(platform) IN ('NAUKRIGULF', 'GULF') AND status IN ('APPLIED', 'APPLICATION_CONFIRMED')")
            naukrigulf_applied = cursor.fetchone()["cnt"]

            # Today's applied counts per platform (CURDATE)
            cursor.execute("SELECT COUNT(*) as cnt FROM job_applications WHERE UPPER(platform) = 'NAUKRI' AND status IN ('APPLIED', 'APPLICATION_CONFIRMED') AND DATE(applied_at) = CURDATE()")
            today_naukri = cursor.fetchone()["cnt"]
            cursor.execute("SELECT COUNT(*) as cnt FROM job_applications WHERE UPPER(platform) = 'LINKEDIN' AND status IN ('APPLIED', 'APPLICATION_CONFIRMED') AND DATE(applied_at) = CURDATE()")
            today_linkedin = cursor.fetchone()["cnt"]
            cursor.execute("SELECT COUNT(*) as cnt FROM job_applications WHERE UPPER(platform) IN ('NAUKRIGULF', 'GULF') AND status IN ('APPLIED', 'APPLICATION_CONFIRMED') AND DATE(applied_at) = CURDATE()")
            today_naukrigulf = cursor.fetchone()["cnt"]
        except Exception:
            naukri_applied = total_applied
            linkedin_applied = 0
            naukrigulf_applied = 0

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

def format_final_application_report(company_name: str, job_title: str, job_location: str,
                                    platform: str = "LinkedIn", application_type: str = "Easy Apply",
                                    resume_status: str = "Uploaded", phone_number: str = "+91 797269663",
                                    country_code: str = "+91", email_verification: str = "Not Required",
                                    form_validation: str = "Passed", application_status: str = "Submitted") -> str:
    """
    MASTER PROMPT SECTION 17:
    Standard Final Application Report markdown generator.
    """
    from datetime import datetime
    app_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report = f"""
### Final Application Report
| Field | Details |
|---|---|
| Company Name | {company_name or 'N/A'} |
| Job Designation | {job_title or 'N/A'} |
| Job Location | {job_location or 'N/A'} |
| Application Platform | {platform} |
| Application Type | {application_type} |
| Resume | {resume_status} |
| Phone Number | {phone_number} |
| Country Code | {country_code} |
| Email Verification | {email_verification} |
| Form Validation | {form_validation} |
| Application Status | {application_status} |
| Application Date | {app_date} |
"""
    return report.strip()

if __name__ == "__main__":
    init_db()
