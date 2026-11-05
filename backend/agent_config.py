import os
import json
from typing import Dict, Any, Tuple

CONFIG_FILE_PATH = os.path.join(os.path.dirname(__file__), "agent_config.json")

DEFAULT_CONFIG: Dict[str, Any] = {
    "mode": "AUTONOMOUS",
    "permissions": {
        "auto_search": True,
        "auto_inspect_jobs": True,
        "auto_fill_forms": True,
        "auto_upload_resume": True,
        "auto_answer_screening": True,
        "auto_submit_direct": True,
        "auto_submit_company_portal": True,
        "bypass_captcha": False,
        "allow_payments": False,
        "allow_sensitive_info": False
    },
    "safety_boundaries": {
        "block_payments": True,
        "block_sensitive_fields": True,
        "block_unverified_facts": True,
        "max_daily_applications": 135,
        "max_daily_naukri": 45,
        "max_daily_linkedin": 45,
        "max_daily_naukrigulf": 45
    },
    "cooldown": {
        "confirmed_min_sec": 120,
        "confirmed_max_sec": 180,
        "unconfirmed_min_sec": 45,
        "unconfirmed_max_sec": 75
    },
    "retry_policy": {
        "max_retries": 2,
        "retry_delay_sec": 5
    }
}

class AgentConfigManager:
    def __init__(self, config_path: str = CONFIG_FILE_PATH):
        self.config_path = config_path
        self._config: Dict[str, Any] = {}
        self.load()

    def load(self) -> Dict[str, Any]:
        """Loads configuration from disk, creating default file if missing."""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Merge defaults with loaded data to ensure all keys exist
                    merged = json.loads(json.dumps(DEFAULT_CONFIG))
                    for k, v in data.items():
                        if isinstance(v, dict) and k in merged:
                            merged[k].update(v)
                        else:
                            merged[k] = v
                    self._config = merged
                    return self._config
            except Exception as e:
                print(f"[CONFIG] Error reading {self.config_path}: {e}. Using defaults.")
        
        self._config = json.loads(json.dumps(DEFAULT_CONFIG))
        self.save()
        return self._config

    def save(self) -> bool:
        """Persists current configuration to disk."""
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2)
            return True
        except Exception as e:
            print(f"[CONFIG] Error saving {self.config_path}: {e}")
            return False

    def get_config(self) -> Dict[str, Any]:
        return self._config

    def update_config(self, new_data: Dict[str, Any]) -> Dict[str, Any]:
        for k, v in new_data.items():
            if isinstance(v, dict) and k in self._config:
                self._config[k].update(v)
            else:
                self._config[k] = v
        self.save()
        return self._config

    def is_authorized(self, action_name: str) -> bool:
        """
        Checks if an action is explicitly authorized in the agent configuration.
        In Autonomous mode, all authorized routine actions run without repeated approval prompts.
        """
        perms = self._config.get("permissions", {})
        return bool(perms.get(action_name, False))

    def is_action_safe(self, action_type: str, details: Dict[str, Any] = None) -> Tuple[bool, str]:
        """
        Enforces safety boundaries:
        - Blocks payments / fees
        - Blocks sensitive credentials (SSN, credit card, bank info)
        - Blocks unauthorized security bypasses
        """
        safety = self._config.get("safety_boundaries", {})
        perms = self._config.get("permissions", {})
        details = details or {}

        # 1. Payment check
        if action_type == "payment":
            if safety.get("block_payments", True) or not perms.get("allow_payments", False):
                return False, "PAYMENT_BLOCKED: Payments and paid transactions are forbidden by safety policy."

        # 2. Sensitive info check
        if action_type == "sensitive_info":
            if safety.get("block_sensitive_fields", True) or not perms.get("allow_sensitive_info", False):
                return False, "SENSITIVE_INFO_BLOCKED: Entering payment cards or national IDs is forbidden."

        # 3. Security / CAPTCHA bypass
        if action_type == "captcha_bypass":
            if not perms.get("bypass_captcha", False):
                return False, "CAPTCHA_BYPASS_BLOCKED: Autonomous CAPTCHA cracking is disallowed. Requires user verification."

        # 4. Unknown facts fabrication
        if action_type == "unverified_fact":
            if safety.get("block_unverified_facts", True):
                return False, "FABRICATION_BLOCKED: Fabricating unrecorded personal facts is disallowed. Marked as NEEDS_USER_INPUT."

        return True, "AUTHORIZED"

agent_config_manager = AgentConfigManager()
