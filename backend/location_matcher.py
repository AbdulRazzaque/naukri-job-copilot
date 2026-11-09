"""
Unified Location Matching & Eligibility Module
===============================================
Handles normalized, multi-location parsing and independent candidate preference matching.
Supports:
- Splitting multiple locations (commas, pipes, slashes, semicolons, bullets)
- Employment mode label stripping (On-site, Hybrid, Remote)
- Independent Remote token extraction (e.g. 'India (Remote)' -> ['India', 'Remote'])
- Known aliases & localities for Mumbai, Pune, Remote, Qatar, Dubai, etc.
- Support for string or list location representations
- Never marks a job LOCATION_MISMATCH if at least one preferred location matches
"""

import re
from typing import List, Tuple, Dict, Any, Union, Optional

# Canonical alias mapping for candidate preferred locations
LOCATION_ALIASES: Dict[str, List[str]] = {
    "mumbai": [
        "mumbai", "bombay", "navi mumbai", "new mumbai", "thane", "kurla",
        "andheri", "bkc", "bandra", "powai", "worli", "dadar", "borivali",
        "goregaon", "malad", "kalyan", "dombivli", "panvel", "vashi", "belapur",
        "ghatkopar", "chembur", "mulund", "lower parel", "mumbai city",
        "mumbai suburban", "maharashtra"
    ],
    "pune": [
        "pune", "poona", "pimpri", "chinchwad", "pimpri-chinchwad", "hinjewadi",
        "hinjawadi", "magarpatta", "kharadi", "baner", "wakad", "yerwada",
        "hadapsar", "kothrud", "viman nagar", "senapati bapat road", "sb road",
        "pune district", "bhosari", "balewadi", "shivajinagar", "kalyani nagar",
        "aundh", "chakan", "talawade", "pimprichinchwad", "kondhwa", "talab chowk",
        "talab chowk, kondhwa", "talab chowk area in kondhwa"
    ],
    "remote": [
        "remote", "telecommute", "wfh", "work from home", "anywhere in india",
        "pan india", "work from anywhere", "wfa", "virtual", "anywhere",
        "home-based", "all india", "remote in india", "india (remote)"
    ],
    "qatar": [
        "qatar", "doha", "al rayyan", "al wakrah", "al khor", "lusail", "gcc"
    ],
    "dubai": [
        "dubai", "uae", "united arab emirates", "abu dhabi", "sharjah", "ajman"
    ],
    "saudi arabia": [
        "saudi arabia", "riyadh", "jeddah", "dammam", "khobar", "ksa"
    ]
}

EMPLOYMENT_MODES = [
    r"\bon-?site\b",
    r"\bhybrid\b",
    r"\boffice-?based\b",
    r"\bwork from office\b",
    r"\bwfo\b",
    r"\bin-?office\b"
]


def extract_location_tokens(raw_location: Union[str, List[str], None]) -> List[str]:
    """
    Splits multi-location inputs (string or array) into normalized individual location tokens.
    Handles delimiters: comma, semicolon, pipe, slash, bullets, newlines, and connector words.
    Extracts embedded employment modes like 'Remote' into independent tokens.
    """
    if raw_location is None:
        return []

    # If already a list or tuple, flatten into strings
    raw_strings: List[str] = []
    if isinstance(raw_location, (list, tuple, set)):
        for item in raw_location:
            if item:
                raw_strings.append(str(item))
    else:
        raw_strings.append(str(raw_location))

    tokens: List[str] = []

    for text in raw_strings:
        if not text:
            continue

        # Check if text contains Remote/WFH before stripping
        t_low = text.lower()
        has_remote = any(r in t_low for r in ["remote", "wfh", "work from home", "telecommute", "virtual"])

        # Split on common delimiters: comma, semicolon, pipe, slash, bullets, newline
        # Also split on ' and ', ' or ', ' & '
        parts = re.split(r"[,;|/\n•·\t]|\s+and\s+|\s+or\s+|\s+&\s+", text, flags=re.IGNORECASE)

        for part in parts:
            p = part.strip()
            if not p:
                continue

            # Check if this part specifically has (Remote) or Remote
            part_has_remote = any(r in p.lower() for r in ["remote", "wfh", "work from home", "telecommute"])

            # Clean out employment mode tags like (On-site), (Hybrid), [On-site]
            clean_part = p
            for mode_pat in EMPLOYMENT_MODES:
                clean_part = re.sub(mode_pat, "", clean_part, flags=re.IGNORECASE)

            # Also strip surrounding parentheses or brackets
            clean_part = re.sub(r"[\(\)\[\]\{\}]", " ", clean_part).strip()
            # Collapse multiple spaces
            clean_part = re.sub(r"\s+", " ", clean_part).strip()

            if clean_part:
                tokens.append(clean_part)

            if part_has_remote and "remote" not in [t.lower() for t in tokens]:
                tokens.append("Remote")

        # If overall raw text explicitly had remote and tokens didn't capture it
        if has_remote and "remote" not in [t.lower() for t in tokens]:
            tokens.append("Remote")

    # De-duplicate while preserving original casing
    seen = set()
    unique_tokens = []
    for tok in tokens:
        tok_low = tok.lower().strip()
        if tok_low and tok_low not in seen:
            seen.add(tok_low)
            unique_tokens.append(tok.strip())

    return unique_tokens


def normalize_preferred_locations(preferred: Union[str, List[str], None]) -> List[str]:
    """
    Normalizes candidate preferred locations into a clean list of canonical location strings.
    Defaults to ['Mumbai', 'Pune', 'Remote'] if empty.
    """
    if not preferred:
        return ["Mumbai", "Pune", "Remote"]

    if isinstance(preferred, str):
        # Split on comma, semicolon, pipe, slash
        items = re.split(r"[,;|/]", preferred)
        items = [i.strip() for i in items if i.strip()]
    elif isinstance(preferred, (list, tuple, set)):
        items = [str(i).strip() for i in preferred if str(i).strip()]
    else:
        items = ["Mumbai", "Pune", "Remote"]

    return items if items else ["Mumbai", "Pune", "Remote"]


def match_location(job_location: Union[str, List[str], None], 
                   preferred_locations: Union[str, List[str], None] = None) -> Tuple[bool, List[str], List[str]]:
    """
    Evaluates whether at least ONE of the job's listed locations matches candidate preferences.
    
    Returns:
    (is_eligible: bool, matched_preferences: List[str], all_extracted_locations: List[str])

    Rules:
    - Splits multiple locations and compares each independently.
    - Never rejects a job simply because other locations (e.g. Hyderabad, Bengaluru) are present.
    - Matches aliases (e.g. Navi Mumbai, Thane -> Mumbai; Hinjewadi -> Pune; WFH -> Remote).
    - Ignores case differences.
    """
    target_prefs = normalize_preferred_locations(preferred_locations)
    job_loc_tokens = extract_location_tokens(job_location)

    if not job_loc_tokens or not str(job_location or "").strip():
        # Job location is missing or empty
        return False, [], []

    matched_prefs: List[str] = []

    for pref in target_prefs:
        pref_norm = pref.lower().strip()

        # Find known aliases for this preference
        aliases = [pref_norm]
        for key, alias_list in LOCATION_ALIASES.items():
            if pref_norm == key or pref_norm in alias_list:
                aliases.extend(alias_list)
        aliases = list(set(aliases))

        # Check if ANY job location token matches any alias
        for job_tok in job_loc_tokens:
            jt_low = job_tok.lower().strip()
            
            # Exact equality or substring match for multi-word localities
            is_token_match = False
            for alias in aliases:
                # Whole word match or exact equivalence
                pattern = r"\b" + re.escape(alias) + r"\b"
                if re.search(pattern, jt_low) or jt_low == alias or (len(alias) >= 4 and alias in jt_low):
                    is_token_match = True
                    break

            if is_token_match:
                if pref not in matched_prefs:
                    matched_prefs.append(pref)
                break

    is_eligible = len(matched_prefs) > 0
    return is_eligible, matched_prefs, job_loc_tokens


def check_application_eligibility(
    match_score: int,
    is_technical_compatible: bool,
    technical_disqualification_reason: str = "",
    job_location: Union[str, List[str], None] = "",
    preferred_locations: Union[str, List[str], None] = None,
    experience_req: str = "",
    min_score_threshold: int = 65,
    is_job_available: bool = True,
    is_already_applied: bool = False
) -> Dict[str, Any]:
    """
    Evaluates independent eligibility criteria in strict hierarchical order:
    1. Technical skill compatibility (DISQUALIFIED -> REQUIRED_SKILL_MISSING)
    2. Duplicate application check (ALREADY_APPLIED / DUPLICATE_JOB)
    3. Job availability (JOB_EXPIRED)
    4. Location compatibility (LOCATION_MISMATCH)
    5. Match score threshold (score >= 65 -> LOW_MATCH_SCORE)
    
    A failure in one condition never overwrites another condition's true reason.
    Returns:
    {
      "is_eligible": bool,
      "skip_reason_code": str,
      "detailed_explanation": str,
      "execution_stage": str,
      "matched_locations": List[str]
    }
    """
    # 1. Technical skill compatibility
    if not is_technical_compatible:
        reason = technical_disqualification_reason or "Job title/description requires unverified technologies (e.g. Java/Spring Boot/.NET/PHP)."
        return {
            "is_eligible": False,
            "skip_reason_code": "REQUIRED_SKILL_MISSING",
            "detailed_explanation": f"Technical skill compatibility check failed: {reason}",
            "execution_stage": "ELIGIBILITY_VERIFICATION",
            "matched_locations": []
        }

    # 2. Duplicate application status
    if is_already_applied:
        return {
            "is_eligible": False,
            "skip_reason_code": "ALREADY_APPLIED",
            "detailed_explanation": "Candidate has already applied to this company/position in the past.",
            "execution_stage": "ELIGIBILITY_VERIFICATION",
            "matched_locations": []
        }

    # 3. Job availability
    if not is_job_available:
        return {
            "is_eligible": False,
            "skip_reason_code": "JOB_EXPIRED",
            "detailed_explanation": "The job posting has expired or is no longer accepting applications.",
            "execution_stage": "ELIGIBILITY_VERIFICATION",
            "matched_locations": []
        }

    # 4. Location compatibility
    raw_loc = (job_location if isinstance(job_location, str) else ", ".join(job_location or [])).strip()
    if not raw_loc:
        return {
            "is_eligible": False,
            "skip_reason_code": "LOCATION_NOT_FOUND",
            "detailed_explanation": "Actual job location is missing or could not be verified from listing elements.",
            "execution_stage": "ELIGIBILITY_VERIFICATION",
            "matched_locations": []
        }

    is_loc_match, matched_locs, extracted = match_location(job_location, preferred_locations)
    if not is_loc_match:
        pref_list = normalize_preferred_locations(preferred_locations)
        return {
            "is_eligible": False,
            "skip_reason_code": "LOCATION_MISMATCH",
            "detailed_explanation": f"None of the job's listed locations ({', '.join(extracted)}) matches candidate preferred locations ({', '.join(pref_list)}).",
            "execution_stage": "ELIGIBILITY_VERIFICATION",
            "matched_locations": []
        }

    # 5. Match score threshold: minimum threshold is 65% (score >= 65 is eligible)
    if match_score < min_score_threshold:
        return {
            "is_eligible": False,
            "skip_reason_code": "LOW_MATCH_SCORE",
            "detailed_explanation": f"The job's compatibility score ({match_score}%) is below the configured threshold ({min_score_threshold}%).",
            "execution_stage": "ELIGIBILITY_VERIFICATION",
            "matched_locations": matched_locs
        }

    # All independent checks passed!
    return {
        "is_eligible": True,
        "skip_reason_code": "",
        "detailed_explanation": f"Eligible for application. Matched locations: {', '.join(matched_locs)}. Score: {match_score}%.",
        "execution_stage": "ACTION_BUTTON_DETECTION",
        "matched_locations": matched_locs
    }

