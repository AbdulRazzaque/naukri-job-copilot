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

@app.get("/api/applications")
def list_applications(limit: int = 100, status: str = None, platform: str = None):
    apps = get_recent_applications(limit=limit)
    if platform and platform.upper() != "ALL":
        apps = [a for a in apps if (a.get("platform") or "NAUKRI").upper() == platform.upper()]
    if status and status.upper() != "ALL":
        status_up = status.upper()
        if status_up == "APPLIED":
            apps = [a for a in apps if a.get("status") in ("APPLIED", "APPLICATION_CONFIRMED")]
        elif status_up in ("REDIRECT_REVIEW", "PENDING"):
            apps = [a for a in apps if a.get("status") in ("REDIRECT_REVIEW", "APPLICATION_PENDING_CONFIRMATION")]
        elif status_up == "SKIPPED":
            apps = [a for a in apps if a.get("status") in ("SKIPPED", "APPLICATION_SKIPPED")]
        elif status_up == "FAILED":
            apps = [a for a in apps if a.get("status") in ("FAILED", "APPLICATION_FAILED")]
        elif status_up in ("NEEDS_USER_INPUT", "NEEDS_INPUT"):
            apps = [a for a in apps if a.get("status") in ("NEEDS_USER_INPUT",)]
        else:
            apps = [a for a in apps if a.get("status") == status_up]
    return apps

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
