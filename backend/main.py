from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import json
import os

from database import init_db, get_dashboard_stats, get_recent_applications
from bot_engine import bot_state, start_agent_thread, stop_agent
from agent_config import agent_config_manager

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        init_db()
    except Exception as e:
        print(f"[DB ERROR] Could not initialize database: {e}")
        print("[HINT] Make sure MySQL is running (e.g. start MySQL in XAMPP).")
    yield

app = FastAPI(title="Naukri Job Copilot API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PROFILE_PATH = os.path.join(os.path.dirname(__file__), "profile_data.json")

class StartAgentRequest(BaseModel):
    keyword: str = "All Target Roles (Auto-Cycle)"
    location: str = "Mumbai, Pune, Qatar, Remote"
    naukri_locations: str = "Mumbai, Pune, Remote"
    linkedin_locations: str = "Mumbai, Pune, Qatar, Remote"
    naukrigulf_locations: str = "Qatar, Dubai, UAE, Saudi Arabia, Remote"
    experience: int = 5
    platform: str = "ALL"

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "Naukri Job Copilot API"}

@app.get("/api/status")
def get_bot_status():
    return bot_state.to_dict()

@app.get("/api/stats")
def get_stats():
    return get_dashboard_stats()

@app.get("/api/logs")
def get_logs(limit: int = 100, level: str = None):
    logs = bot_state.logs
    if level and level.upper() != "ALL":
        logs = [l for l in logs if l.get("level", "").upper() == level.upper()]
    return logs[:limit]

@app.get("/api/applications")
def list_applications(limit: int = 100, status: str = None, platform: str = None):
    from database import map_to_skip_reason_code
    apps = get_recent_applications(limit=limit)
    if platform and platform.upper() != "ALL":
        apps = [a for a in apps if (a.get("platform") or "NAUKRI").upper() == platform.upper()]
    if status and status.upper() != "ALL":
        status_up = status.upper()
        if status_up == "APPLIED":
            apps = [a for a in apps if a.get("status") in ("APPLIED", "APPLICATION_CONFIRMED") or (a.get("status") in ("APPLICATION_PENDING_CONFIRMATION", "REDIRECT_REVIEW") and a.get("application_submitted"))]
        elif status_up in ("REDIRECT_REVIEW", "PENDING"):
            apps = [a for a in apps if a.get("status") in ("REDIRECT_REVIEW", "APPLICATION_PENDING_CONFIRMATION") and not a.get("application_submitted")]
        elif status_up == "SKIPPED":
            apps = [a for a in apps if a.get("status") in ("SKIPPED", "APPLICATION_SKIPPED")]
        elif status_up == "FAILED":
            apps = [a for a in apps if a.get("status") in ("FAILED", "APPLICATION_FAILED")]
        elif status_up in ("NEEDS_USER_INPUT", "NEEDS_INPUT"):
            apps = [a for a in apps if a.get("status") in ("NEEDS_USER_INPUT",)]
        else:
            apps = [a for a in apps if a.get("status") == status_up]

    # Normalize fields for backward compatibility and populate audit keys
    formatted = []
    for a in apps:
        item = dict(a)
        st = (item.get("status") or "").upper()
        
        # Backfill skip_reason_code and detailed_explanation if empty
        if not item.get("skip_reason_code") and st in ("SKIPPED", "APPLICATION_SKIPPED"):
            item["skip_reason_code"] = map_to_skip_reason_code(item.get("failure_reason"), item.get("notes"), match_score=item.get("match_score"))

        code = item.get("skip_reason_code")
        # STRICT VALIDATION: Score >= 65% must never be LOW_MATCH_SCORE
        if item.get("match_score", 0) >= 65 and code == "LOW_MATCH_SCORE":
            code = "APPLY_OPTION_NOT_AVAILABLE"
            item["skip_reason_code"] = code

        if not item.get("detailed_explanation") or (code != "LOW_MATCH_SCORE" and "below" in (item.get("detailed_explanation") or "").lower()):
            if code == "LOCATION_NOT_FOUND":
                item["detailed_explanation"] = "Actual job location is missing or could not be verified from listing elements."
            elif code == "LOCATION_MISMATCH":
                item["detailed_explanation"] = f"None of the job's listed locations ({item.get('location', '')}) matches candidate preferred locations."
            elif code == "PRIMARY_SPECIALIZATION_MISMATCH":
                item["detailed_explanation"] = "Dedicated specialist role in non-primary technology. Candidate specializes in MERN Stack."
            elif code == "LOW_MATCH_SCORE":
                item["detailed_explanation"] = f"The job's compatibility score ({item.get('match_score', 0)}%) is below the configured threshold (65%)."
            elif code == "APPLY_OPTION_NOT_AVAILABLE":
                item["detailed_explanation"] = "The job is eligible, but no application option was found after inspection."
            elif code == "APPLICATION_BLOCKED":
                item["detailed_explanation"] = f"An application option was found, but the automation could not execute the action: {item.get('failure_reason') or item.get('notes')}"
            else:
                item["detailed_explanation"] = item.get("notes") or item.get("failure_reason") or ""
        if not item.get("execution_stage"):
            if st in ("APPLIED", "APPLICATION_CONFIRMED"):
                item["execution_stage"] = "SUBMISSION_VERIFICATION"
            elif st in ("REDIRECT_REVIEW", "APPLICATION_PENDING_CONFIRMATION", "NEEDS_USER_INPUT"):
                item["execution_stage"] = "EXTERNAL_PORTAL_HANDOFF"
            elif item.get("skip_reason_code") in ("LOCATION_MISMATCH", "LOCATION_NOT_FOUND", "REQUIRED_SKILL_MISSING", "PRIMARY_SPECIALIZATION_MISMATCH", "LOW_MATCH_SCORE", "ALREADY_APPLIED", "DUPLICATE_JOB", "EXPERIENCE_MISMATCH"):
                item["execution_stage"] = "ELIGIBILITY_VERIFICATION"
            elif item.get("skip_reason_code") in ("APPLY_OPTION_NOT_AVAILABLE", "LOGIN_REQUIRED"):
                item["execution_stage"] = "ACTION_BUTTON_DETECTION"
            else:
                item["execution_stage"] = "DISCOVERED"

        # Add camelCase representations
        item["jobId"] = item.get("id")
        item["companyName"] = item.get("company_name")
        item["jobTitle"] = item.get("job_title")
        item["jobLocation"] = item.get("location")
        item["jobUrl"] = item.get("job_url")
        item["matchScore"] = item.get("match_score")
        item["applicationStatus"] = item.get("status")
        item["executionStage"] = item.get("execution_stage")
        item["skipReasonCode"] = item.get("skip_reason_code")
        item["detailedExplanation"] = item.get("detailed_explanation")
        item["applicationAttempted"] = bool(item.get("application_attempted") or st in ("APPLIED", "APPLICATION_CONFIRMED", "APPLICATION_PENDING_CONFIRMATION", "NEEDS_USER_INPUT"))
        item["applicationSubmitted"] = bool(item.get("application_submitted") or st in ("APPLIED", "APPLICATION_CONFIRMED"))
        item["applicationConfirmed"] = bool(item.get("application_confirmed") or st in ("APPLIED", "APPLICATION_CONFIRMED"))
        item["errorMessage"] = item.get("error_message") or item.get("failure_reason") or ""
        item["screenshotReference"] = item.get("screenshot_reference") or ""
        item["externalApplicationUrl"] = item.get("external_application_url") or ""
        item["resumeUploadStatus"] = item.get("resume_upload_status") or "NOT_STARTED"
        item["appliedAt"] = item.get("applied_at")

        formatted.append(item)

    return formatted

@app.get("/api/application/{app_id}/report")
def get_application_report(app_id: int):
    """Returns the Master Section 8 Activity & Resume Optimization Report for an application."""
    from database import get_connection
    from resume_optimizer import JDAnalysis, generate_activity_report
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM job_applications WHERE id = %s", (app_id,))
        app = cursor.fetchone()
        conn.close()

    if not app:
        return {"error": "Application not found"}

    try:
        jd_dict = json.loads(app.get("jd_match_analysis_json") or "{}")
        jd_analysis = JDAnalysis(
            job_title=app.get("job_title", ""),
            company=app.get("company_name", ""),
            location=app.get("location", ""),
            job_url=app.get("job_url", ""),
            platform=app.get("platform", "GENERAL"),
            full_jd=""
        )
        jd_analysis.match_type = jd_dict.get("match_type", "STRONG_MATCH")
        jd_analysis.match_score = app.get("match_score", 85)
        jd_analysis.should_apply = jd_dict.get("should_apply", True)
        jd_analysis.disqualification_reason = app.get("failure_reason", "") or jd_dict.get("disqualification_reason", "")
        jd_analysis.matching_skills = jd_dict.get("matching_skills", ["React.js", "Node.js", "TypeScript", "MongoDB"])
        jd_analysis.missing_skills = jd_dict.get("missing_skills", [])
        jd_analysis.focus_areas = jd_dict.get("focus_areas", ["fullstack"])

        opt_res = json.loads(app.get("cv_changes_json") or "{}")
        if not opt_res:
            opt_res = {
                "success": bool(app.get("customized_resume_path")),
                "customized_path": app.get("customized_resume_path", ""),
                "original_path": app.get("original_resume_path", ""),
                "summary_before": "Standard MERN Developer summary",
                "summary_after": "Tailored alignment with role requirements",
                "skills_highlighted": jd_analysis.matching_skills[:8],
                "focus_areas": jd_analysis.focus_areas
            }

        status_text = "Applied Successfully" if app.get("status") in ("APPLIED", "APPLICATION_CONFIRMED") else (
            f"Skipped ({app.get('failure_reason', 'Incompatible')})" if app.get("status") in ("SKIPPED", "APPLICATION_SKIPPED") else app.get("status")
        )

        report = generate_activity_report(
            jd_analysis=jd_analysis,
            optimization_res=opt_res,
            application_status=status_text,
            error_msg=app.get("failure_reason", "")
        )
        return {"report": report, "application": app}
    except Exception as e:
        return {"error": str(e), "application": app}

@app.get("/api/config")
def get_agent_config():
    """Returns persistent AgentConfig including permissions and safety boundaries."""
    return agent_config_manager.get_config()

@app.post("/api/config")
def update_agent_config(new_config: dict):
    """Updates and persists AgentConfig across restarts."""
    updated = agent_config_manager.update_config(new_config)
    return {"status": "success", "message": "Agent configuration updated and persisted successfully", "config": updated}

@app.post("/api/start")
def start_bot(req: StartAgentRequest):
    success, msg = start_agent_thread(
        keyword=req.keyword,
        location=req.location,
        experience=req.experience,
        platform=req.platform,
        naukri_locations=req.naukri_locations,
        linkedin_locations=req.linkedin_locations,
        naukrigulf_locations=req.naukrigulf_locations
    )
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg, "state": bot_state.to_dict()}

@app.post("/api/stop")
def stop_bot():
    success, msg = stop_agent()
    return {"message": msg, "state": bot_state.to_dict()}

@app.get("/api/check-chrome")
def check_chrome_cdp():
    """Checks if Chrome is actively running on port 9222 with remote debugging."""
    try:
        res = requests.get("http://127.0.0.1:9222/json/version", timeout=2)
        if res.status_code == 200:
            data = res.json()
            return {
                "connected": True, 
                "browser": data.get("Browser", "Chrome"),
                "webSocketDebuggerUrl": data.get("webSocketDebuggerUrl")
            }
    except Exception:
        pass
    return {
        "connected": False,
        "browser": None,
        "message": "Chrome is not running on port 9222. Please start Chrome with --remote-debugging-port=9222"
    }

@app.get("/api/profile")
def get_profile():
    if os.path.exists(PROFILE_PATH):
        with open(PROFILE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

@app.post("/api/profile")
def update_profile(updated_data: dict):
    with open(PROFILE_PATH, "w", encoding="utf-8") as f:
        json.dump(updated_data, f, indent=2)
    return {"status": "success", "message": "Profile updated successfully"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
