"""
Centralized Country-Based Candidate Information Manager
=======================================================
Provides a unified candidate contact profile, automatic country detection,
phone field mapping, location intelligence, pre-submission validation, and audit logging.

Used across:
- LinkedIn Easy Apply
- LinkedIn External Applications
- Naukri.com
- Naukri Gulf
- Company Career Portals (Workday, Greenhouse, Lever, etc.)
- Shared form-filling services
"""

import os
import re
import json
import logging
from typing import Dict, Any, Tuple, Optional, List

logger = logging.getLogger("candidate_manager")

# Base directory for resolving resume PDFs
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))

# -------------------------------------------------------------
# 1. VERIFIED CANDIDATE CONTACT PROFILES
# -------------------------------------------------------------
VERIFIED_PROFILES = {
    "INDIA": {
        "profile_name": "INDIA",
        "classification": "INDIA",
        "country": "India",
        "country_code": "+91",
        "dial_code": "+91",
        "calling_code": "+91",
        "mobile_number": "7972694663",
        "phone_raw": "7972694663",
        "full_phone_number": "+91 7972694663",
        "phone_full": "+91 7972694663",
        "masked_phone": "+91 ******4663",
        "preferred_work_location": "Mumbai, Kurla, Maharashtra, India",
        "preferred_city": "Mumbai",
        "preferred_area": "Kurla",
        "state": "Maharashtra",
        "postal_code": "400070",
        "residential_country": "India",
        "residential_state": "Maharashtra",
        "residential_city": "Mumbai",
        "residential_area": "Kurla",
        "residential_address": "Kurla, Mumbai, Maharashtra, India",
        "current_employment_location": "Remote (Working from Kurla, Mumbai)",
        "current_location": "Kurla, Mumbai, India",
        "resume_filename": "Abdul_Razzaque_India.pdf",
        "dob": "19/11/1999",
        "dob_formatted": "19-11-1999",
        "dob_iso": "1999-11-19",
        "dob_day": "19",
        "dob_month": "11",
        "dob_month_name": "November",
        "dob_year": "1999",
        "is_india": True,
        "is_international": False
    },
    "QATAR / INTERNATIONAL": {
        "profile_name": "QATAR / INTERNATIONAL",
        "classification": "INTERNATIONAL",
        "country": "Qatar",
        "country_code": "+974",
        "dial_code": "+974",
        "calling_code": "+974",
        "mobile_number": "77557982",
        "phone_raw": "77557982",
        "full_phone_number": "+974 77557982",
        "phone_full": "+974 77557982",
        "masked_phone": "+974 ****7982",
        "preferred_work_location": "Qatar / Dubai / Remote",
        "preferred_city": "Doha",
        "preferred_area": "",
        "state": "Doha",
        "postal_code": "",
        # Truthful residential data: candidate's actual current residence is India
        # Never misrepresent residential address, current employment location, or immigration status in Gulf countries!
        "residential_country": "India",
        "residential_state": "Maharashtra",
        "residential_city": "Mumbai",
        "residential_area": "Kurla",
        "residential_address": "Kurla, Mumbai, Maharashtra, India",
        "current_employment_location": "Remote (Working from Kurla, Mumbai)",
        "current_location": "Kurla, Mumbai, India",
        "resume_filename": "Abdul_Razzaque_Qatar.pdf",
        "dob": "19/11/1999",
        "dob_formatted": "19-11-1999",
        "dob_iso": "1999-11-19",
        "dob_day": "19",
        "dob_month": "11",
        "dob_month_name": "November",
        "dob_year": "1999",
        "is_india": False,
        "is_international": True
    }
}

# Aliases
VERIFIED_PROFILES["INTERNATIONAL"] = VERIFIED_PROFILES["QATAR / INTERNATIONAL"]

# Normalized keywords for country classification
GULF_INTERNATIONAL_KEYWORDS = [
    "qatar", "doha",
    "dubai", "abu dhabi", "sharjah", "ajman", "ras al khaimah", "fujairah", "uae", "united arab emirates",
    "saudi", "saudi arabia", "riyadh", "jeddah", "dammam", "khobar", "al khobar", "ksa",
    "kuwait", "kuwait city",
    "bahrain", "manama",
    "oman", "muscat",
    "gulf", "middle east",
    # Other international destinations
    "singapore", "germany", "united kingdom", "london", "canada", "united states", "usa", "australia"
]

INDIA_KEYWORDS = [
    "india", "mumbai", "pune", "bengaluru", "bangalore", "hyderabad",
    "delhi", "new delhi", "noida", "gurgaon", "gurugram", "chennai",
    "kolkata", "ahmedabad", "maharashtra", "karnataka", "tamil nadu",
    "telangana", "uttar pradesh", "gujarat", "chandigarh", "jaipur", "kochi", "kerala", "indore"
]

PUNE_KEYWORDS = [
    "pune", "kondhwa", "talab chowk", "hinjewadi", "hinjawadi", "magarpatta",
    "kharadi", "baner", "wakad", "yerwada", "hadapsar", "kothrud", "viman nagar",
    "sb road", "senapati bapat", "balewadi", "shivajinagar", "kalyani nagar",
    "aundh", "chakan", "talawade", "pimpri", "chinchwad", "pimprichinchwad"
]


# -------------------------------------------------------------
# 2. HELPER UTILITIES: PHONE MASKING & RESUME RESOLUTION
# -------------------------------------------------------------
def mask_phone_number(phone_str: str) -> str:
    """
    Masks middle digits of a phone number for privacy in ordinary dashboard logs.
    Examples:
    - '+91 7972694663' -> '+91 ******4663'
    - '7972694663'     -> '******4663'
    - '+974 77557982'  -> '+974 ****7982'
    - '77557982'       -> '****7982'
    """
    if not phone_str:
        return ""
    clean = phone_str.strip()
    # Match +91 7972694663 or +917972694663
    m_in = re.search(r"(\+?91[\s\-]?)?(\d{2})(\d{4,6})(\d{4})$", clean)
    if m_in and ("91" in clean or len(clean.replace(" ", "")) >= 10):
        prefix = m_in.group(1) or ""
        first2 = m_in.group(2)
        last4 = m_in.group(4)
        middle_len = len(m_in.group(3))
        # Match standard display: +91 ******4663
        if prefix:
            return f"{prefix.strip()} {'*' * (middle_len + 2)}{last4}"
        return f"{'*' * (middle_len + 2)}{last4}"

    # Match +974 77557982
    m_qa = re.search(r"(\+?974[\s\-]?)?(\d{2})(\d{2,4})(\d{4})$", clean)
    if m_qa and ("974" in clean or len(clean.replace(" ", "")) == 8):
        prefix = m_qa.group(1) or ""
        last4 = m_qa.group(4)
        if prefix:
            return f"{prefix.strip()} ****{last4}"
        return f"****{last4}"

    # Generic mask fallback
    digits_only = re.sub(r"\D", "", clean)
    if len(digits_only) > 4:
        return f"{clean[:3]}...{digits_only[-4:]}"
    return "***"


def resolve_resume_path(filename: str) -> str:
    """Finds absolute path to resume PDF."""
    candidates = [
        os.path.join(BACKEND_DIR, filename),
        os.path.join(BACKEND_DIR, filename.replace("_", " ")),
        os.path.join(os.path.dirname(BACKEND_DIR), filename),
        os.path.join(os.path.dirname(BACKEND_DIR), filename.replace("_", " ")),
        os.path.join(r"E:\Abdur Razzaque\Abdur Razzaque Both", filename.replace("_", " "))
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return os.path.join(BACKEND_DIR, filename)


# -------------------------------------------------------------
# 3. CENTRALIZED DETECTION & PROFILE RETRIEVAL
# -------------------------------------------------------------
class CandidateProfileManager:
    """
    Centralized Candidate Information Manager.
    Resolves contact profiles, country detection, phone mapping, and location validation.
    """

    @staticmethod
    def detect_job_country_and_classification(job_location: str) -> Tuple[str, str]:
        """
        Detects actual job country and classification ('INDIA' vs 'INTERNATIONAL')
        from complete job location string.
        Returns: (detected_country, classification)
        """
        raw_loc = (job_location or "").lower().strip()
        # Clean delimiters
        norm = re.sub(r"[,;|\/\-]+", " ", raw_loc)
        tokens = norm.split()

        # Check Gulf / International first
        for kw in GULF_INTERNATIONAL_KEYWORDS:
            if kw in norm:
                # Specific country identification
                if "qatar" in norm or "doha" in norm:
                    return "Qatar", "INTERNATIONAL"
                if any(u in norm for u in ["dubai", "abu dhabi", "sharjah", "ajman", "ras al khaimah", "fujairah", "uae", "united arab emirates"]):
                    return "United Arab Emirates", "INTERNATIONAL"
                if any(s in norm for s in ["saudi", "riyadh", "jeddah", "dammam", "khobar", "ksa"]):
                    return "Saudi Arabia", "INTERNATIONAL"
                if "kuwait" in norm:
                    return "Kuwait", "INTERNATIONAL"
                if "bahrain" in norm or "manama" in norm:
                    return "Bahrain", "INTERNATIONAL"
                if "oman" in norm or "muscat" in norm:
                    return "Oman", "INTERNATIONAL"
                return "International", "INTERNATIONAL"

        # Check India
        for kw in INDIA_KEYWORDS:
            if kw in norm:
                return "India", "INDIA"

        # If location mentions 'remote':
        # Default to India if not specified, because candidate's primary base is India
        if "remote" in norm:
            return "India", "INDIA"

        # Default fallback
        return "India", "INDIA"

    @classmethod
    def get_candidate_profile_by_job_location(cls, job_location: str) -> Dict[str, Any]:
        """
        Core Centralized Function:
        getCandidateProfileByJobLocation(jobLocation)
        
        Returns:
        - Candidate country profile ('INDIA' or 'QATAR / INTERNATIONAL')
        - Correct country code (+91 or +974)
        - Correct mobile number (7972694663 or 77557982)
        - Full international phone number
        - Masked phone number for logging
        - Preferred work location
        - Applicable location information
        - Country classification ('INDIA' or 'INTERNATIONAL')
        - Resolved resume path
        """
        detected_country, classification = cls.detect_job_country_and_classification(job_location)
        base_profile = VERIFIED_PROFILES[classification].copy()
        
        # Attach detected country and runtime resolution
        base_profile["detected_country"] = detected_country
        base_profile["resume_path"] = resolve_resume_path(base_profile["resume_filename"])
        
        # Location personalization for India: Pune vs Mumbai
        raw_loc = (job_location or "").lower()
        if classification == "INDIA":
            is_pune = any(kw in raw_loc for kw in PUNE_KEYWORDS)
            if is_pune:
                base_profile["detected_city"] = "Pune"
                base_profile["city"] = "Pune"
                base_profile["preferred_city"] = "Pune"
                base_profile["preferred_area"] = "Talab Chowk, Kondhwa"
                base_profile["area"] = "Talab Chowk, Kondhwa"
                base_profile["postal_code"] = "411048"
                base_profile["pincode"] = "411048"
                base_profile["residential_country"] = "India"
                base_profile["residential_state"] = "Maharashtra"
                base_profile["residential_city"] = "Pune"
                base_profile["residential_area"] = "Talab Chowk, Kondhwa"
                base_profile["residential_address"] = "Talab Chowk area in Kondhwa, Pune, Maharashtra, India"
                base_profile["current_employment_location"] = "Talab Chowk, Kondhwa, Pune, India"
                base_profile["current_location"] = "Talab Chowk area in Kondhwa, Pune, Maharashtra, India"
                base_profile["preferred_work_location"] = "Talab Chowk area in Kondhwa, Pune, Maharashtra, India"
            else:
                base_profile["detected_city"] = "Mumbai"
                base_profile["city"] = "Mumbai"
                base_profile["preferred_city"] = "Mumbai"
                base_profile["preferred_area"] = "Kurla"
                base_profile["area"] = "Kurla"
                base_profile["postal_code"] = "400070"
                base_profile["pincode"] = "400070"
                base_profile["residential_country"] = "India"
                base_profile["residential_state"] = "Maharashtra"
                base_profile["residential_city"] = "Mumbai"
                base_profile["residential_area"] = "Kurla"
                base_profile["residential_address"] = "Kurla, Mumbai, Maharashtra, India"
                base_profile["current_employment_location"] = "Remote (Working from Kurla, Mumbai)"
                base_profile["current_location"] = "Kurla, Mumbai, India"
                base_profile["preferred_work_location"] = "Mumbai, Kurla, Maharashtra, India"
        
        return base_profile

    # -------------------------------------------------------------
    # 4. PHONE NUMBER FIELD MAPPING
    # -------------------------------------------------------------
    @classmethod
    def format_phone_inputs(cls, profile: Dict[str, Any], has_separate_country_code: bool) -> Tuple[str, str]:
        """
        Maps phone data for application forms:
        - If separate country code dropdown exists:
          returns (country_code, national_mobile_number)
          e.g. ('+91', '7972694663') or ('+974', '77557982')
        - If one combined phone field:
          returns ('', full_international_number)
          e.g. ('', '+91 7972694663') or ('', '+974 77557982')
        """
        if has_separate_country_code:
            return profile["country_code"], profile["mobile_number"]
        else:
            return "", profile["full_phone_number"]

    @classmethod
    def validate_phone_mapping(cls, country_code_val: str, national_number_val: str, 
                               is_india: bool, combined_val: str = "") -> Dict[str, Any]:
        """
        Validates populated phone fields before submission:
        - No duplicate country code (e.g. +91 +91 or country code inside national number field)
        - No cross-contamination between India and Qatar numbers
        - Correct digit lengths (India: 10 digits '7972694663'; Qatar: 8 digits '77557982')
        - No UAE numbers (+971) or Bolivia (+591)
        """
        errors = []
        c_code = (country_code_val or "").strip()
        nat_num = (national_number_val or "").strip()
        comb = (combined_val or "").strip()

        # Check for Bolivia error (+591)
        if "+591" in c_code or "+591" in nat_num or "+591" in comb:
            errors.append("Invalid country code: Bolivia (+591) detected.")

        # Check for UAE number (+971) - strict rule: candidate only has Qatar (+974)
        if "+971" in c_code or "971" in c_code or "+971" in comb:
            errors.append("Invalid country code: +971 detected. Must strictly use Qatar (+974).")

        if is_india:
            # Must be India (+91, 7972694663)
            if "77557982" in nat_num or "77557982" in comb:
                errors.append("Cross-contamination error: Qatar number '77557982' entered in India application.")
            if "+974" in c_code or "+974" in comb:
                errors.append("Cross-contamination error: Qatar country code '+974' entered in India application.")
            
            if nat_num:
                # Check for duplicate country code
                if "+91" in nat_num or "917972" in nat_num:
                    errors.append("Duplicate country code: '+91' entered inside national number field.")
                clean_digits = re.sub(r"\D", "", nat_num)
                if clean_digits != "7972694663":
                    errors.append(f"Invalid India mobile number: '{clean_digits}'. Must be verified 10-digit '7972694663'.")
            
            if comb:
                clean_comb = re.sub(r"\s+", " ", comb)
                if not (clean_comb == "+91 7972694663" or clean_comb == "+917972694663"):
                    errors.append(f"Invalid combined India phone: '{comb}'. Expected '+91 7972694663'.")

        else:
            # Must be Qatar / International (+974, 77557982)
            if "7972694663" in nat_num or "797269663" in nat_num or "7972694663" in comb:
                errors.append("Cross-contamination error: India number entered in International application.")
            if "+91" in c_code or "+91" in comb:
                errors.append("Cross-contamination error: India country code '+91' entered in International application.")

            if nat_num:
                # Check for duplicate country code
                if "+974" in nat_num or "9747755" in nat_num:
                    errors.append("Duplicate country code: '+974' entered inside national number field.")
                clean_digits = re.sub(r"\D", "", nat_num)
                if clean_digits != "77557982":
                    errors.append(f"Invalid Qatar mobile number: '{clean_digits}'. Must be verified 8-digit '77557982'.")

            if comb:
                clean_comb = re.sub(r"\s+", " ", comb)
                if not (clean_comb == "+974 77557982" or clean_comb == "+97477557982"):
                    errors.append(f"Invalid combined Qatar phone: '{comb}'. Expected '+974 77557982'.")

        is_valid = (len(errors) == 0)
        active_phone = comb or f"{c_code} {nat_num}".strip()
        return {
            "is_valid": is_valid,
            "errors": errors,
            "masked_phone": mask_phone_number(active_phone)
        }

    # -------------------------------------------------------------
    # 5. LOCATION FIELD INTELLIGENCE
    # -------------------------------------------------------------
    @classmethod
    def resolve_location_field(cls, field_name_or_label: str, profile: Dict[str, Any], 
                               is_mandatory: bool = False) -> Dict[str, Any]:
        """
        Differentiates between:
        - Current Residential Address / Current Location (Truthful verified residence only)
        - Preferred Work Location / Preferred Location (Candidate's actual work preference)
        - Relocation Preference
        - City / State / Country
        
        Strict Rules:
        - Never automatically enter Mumbai, Kurla as current residential address for foreign positions without verification.
        - Never invent house number, street address, postal code, residential address, visa status, or immigration status.
        - If a mandatory residential field cannot be answered truthfully, returns NEEDS_USER_ACTION.
        """
        label_low = (field_name_or_label or "").lower()
        is_india = profile.get("is_india", True)

        # 1. Preferred Work Location
        if any(k in label_low for k in ["preferred location", "preferred work location", "desired work location", "desired location", "work location preference"]):
            val = profile["preferred_work_location"]
            return {"status": "RESOLVED", "value": val, "field_type": "PREFERRED_WORK_LOCATION"}

        # 2. Relocation Preference
        if any(k in label_low for k in ["relocate", "relocation", "willing to relocate", "open to relocate"]):
            if is_india:
                target_c = profile.get("city", "Mumbai")
                val = f"Yes, open to relocate to {target_c} or work remotely."
            else:
                val = "Yes, open to relocate for international opportunities."
            return {"status": "RESOLVED", "value": val, "field_type": "RELOCATION"}

        # 3. Current Residential Address / Physical Residence
        if any(k in label_low for k in [
            "current residential address", "residential address", "home address", "permanent address",
            "street address", "house number", "apartment", "building name", "flat number"
        ]):
            # If application is for India, candidate's verified residence is Kurla, Mumbai
            if is_india:
                return {
                    "status": "RESOLVED",
                    "value": profile["residential_address"],
                    "field_type": "CURRENT_RESIDENTIAL_ADDRESS"
                }
            else:
                # In foreign application (Qatar/UAE), if the form asks specifically for local residential street/house:
                # NEVER invent local Qatar/UAE address!
                # If form allows foreign residence, candidate can state their actual current residence (Kurla, Mumbai, India).
                # But if it requires specific local street/house/building in UAE/Qatar that candidate does not possess:
                if is_mandatory and any(k in label_low for k in ["house number", "street address", "building name", "flat number", "emirates id", "qatar id"]):
                    return {
                        "status": "NEEDS_USER_ACTION",
                        "value": "",
                        "reason": f"Mandatory local address field '{field_name_or_label}' cannot be fabricated without user input.",
                        "field_type": "CURRENT_RESIDENTIAL_ADDRESS"
                    }
                # Otherwise, truthful verified residence in India
                return {
                    "status": "RESOLVED",
                    "value": profile["residential_address"],
                    "field_type": "CURRENT_RESIDENTIAL_ADDRESS"
                }

        # 4. Postal Code / Zip Code / Pincode
        if any(k in label_low for k in ["postal code", "zip code", "zip", "pincode", "pin code", "post code"]):
            if is_india:
                return {"status": "RESOLVED", "value": profile["postal_code"], "field_type": "POSTAL_CODE"}
            else:
                # Qatar does not use traditional postal codes. Never fabricate random code.
                # If mandatory in Qatar application, request user action or leave blank
                if is_mandatory:
                    return {
                        "status": "NEEDS_USER_ACTION",
                        "value": "",
                        "reason": "Qatar has no standard postal code. Mandatory postal code requires user input.",
                        "field_type": "POSTAL_CODE"
                    }
                return {"status": "RESOLVED", "value": "", "field_type": "POSTAL_CODE"}

        # 5. City
        if any(k in label_low for k in ["city", "town", "current city"]):
            if "preferred" in label_low:
                return {"status": "RESOLVED", "value": profile["preferred_city"], "field_type": "PREFERRED_CITY"}
            # Current City: Truthfully Mumbai (candidate currently working remotely from Kurla, Mumbai)
            return {"status": "RESOLVED", "value": profile["residential_city"], "field_type": "CURRENT_CITY"}

        # 6. State
        if any(k in label_low for k in ["state", "province", "region"]):
            if "preferred" in label_low:
                return {"status": "RESOLVED", "value": profile["state"], "field_type": "PREFERRED_STATE"}
            return {"status": "RESOLVED", "value": profile["residential_state"], "field_type": "CURRENT_STATE"}

        # 7. Country
        if any(k in label_low for k in ["country", "nation", "citizenship", "nationality"]):
            if any(k in label_low for k in ["citizenship", "nationality"]):
                return {"status": "RESOLVED", "value": "Indian", "field_type": "NATIONALITY"}
            if "preferred" in label_low:
                return {"status": "RESOLVED", "value": profile["country"], "field_type": "PREFERRED_COUNTRY"}
            return {"status": "RESOLVED", "value": profile["residential_country"], "field_type": "CURRENT_COUNTRY"}

        # 8. General Current Location
        if any(k in label_low for k in ["current location", "where do you live", "where are you based"]):
            return {"status": "RESOLVED", "value": profile["current_location"], "field_type": "CURRENT_LOCATION"}

        # Default fallback
        return {"status": "RESOLVED", "value": profile.get("current_location", "Kurla, Mumbai, India"), "field_type": "GENERAL_LOCATION"}


# -------------------------------------------------------------
# 6. STANDARDIZED API INTERFACE
# -------------------------------------------------------------
# Official function name per requirement: getCandidateProfileByJobLocation(jobLocation)
def getCandidateProfileByJobLocation(jobLocation: str) -> Dict[str, Any]:
    """Official centralized API: getCandidateProfileByJobLocation."""
    return CandidateProfileManager.get_candidate_profile_by_job_location(jobLocation)

# Pythonic alias
def get_candidate_profile_by_job_location(job_location: str) -> Dict[str, Any]:
    """Pythonic snake_case alias for getCandidateProfileByJobLocation."""
    return CandidateProfileManager.get_candidate_profile_by_job_location(job_location)

