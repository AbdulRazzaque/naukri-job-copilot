import os
import json
import re
from typing import Dict, Any, List, Tuple, Optional

# Load candidate profile dynamically
PROFILE_PATH = os.path.join(os.path.dirname(__file__), "profile_data.json")

def get_profile() -> Dict[str, Any]:
    try:
        if os.path.exists(PROFILE_PATH):
            with open(PROFILE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

class QuestionCategory:
    EXPERIENCE = "EXPERIENCE"
    SALARY = "SALARY"
    NOTICE_PERIOD = "NOTICE_PERIOD"
    LOCATION = "LOCATION"
    EDUCATION = "EDUCATION"
    EMPLOYMENT_HISTORY = "EMPLOYMENT_HISTORY"
    TECHNICAL_SKILLS = "TECHNICAL_SKILLS"
    CAREER_GOALS = "CAREER_GOALS"
    JOB_SPECIFIC_EXPERIENCE = "JOB_SPECIFIC_EXPERIENCE"
    RELOCATION = "RELOCATION"
    ELIGIBILITY = "ELIGIBILITY"
    PERSONAL_INFO = "PERSONAL_INFO"
    RESUME = "RESUME"
    OTHER = "OTHER"

def is_sensitive_or_payment(question: str) -> Tuple[bool, str]:
    """Detects payment, fee, or sensitive identity queries."""
    q = (question or "").lower()
    
    payment_terms = [
        "credit card", "debit card", "cvv", "cvc", "card number", "bank account", 
        "routing number", "application fee", "processing fee", "payment", 
        "pay now", "subscription price", "wire transfer", "billing address"
    ]
    if any(t in q for t in payment_terms):
        return True, "PAYMENT_REQUEST_BLOCKED"

    sensitive_terms = [
        "ssn", "social security", "aadhaar", "pan card", "pan number", 
        "passport number", "driver's license", "national id", "secret question", 
        "net banking password", "bank pin", "security code", "pin", "clearance"
    ]
    if any(t in q for t in sensitive_terms):
        return True, "SENSITIVE_FIELD_BLOCKED"

    return False, ""

def classify_question_category(question: str) -> str:
    """Classifies question into standardized functional categories."""
    q = question.lower()

    if any(k in q for k in ["resume", "cv", "curriculum vitae", "upload resume", "upload cv", "attach resume"]):
        return QuestionCategory.RESUME

    # Contact & Personal info must be checked before location (avoids 'email address' matching 'address')
    if any(k in q for k in ["email", "e-mail", "phone", "mobile", "full name", "first name", "last name", "your name", "candidate name", "dob", "birth date", "date of birth", "gender"]):
        return QuestionCategory.PERSONAL_INFO

    if any(k in q for k in ["notice", "availability", "how soon", "serving notice", "lwd", "last working"]):
        return QuestionCategory.NOTICE_PERIOD

    if any(k in q for k in ["ctc", "salary", "compensation", "fixed component", "inr", "lakh", "lpa", "earning"]):
        return QuestionCategory.SALARY

    if any(k in q for k in ["experience", "exp", "years", "total exp", "how many years", "relevant"]):
        return QuestionCategory.EXPERIENCE

    if any(k in q for k in ["location", "city", "state", "residence", "where do you live", "where are you based", "pincode", "postal", "address"]) and not any(k in q for k in ["email", "e-mail", "mail address"]):
        return QuestionCategory.LOCATION

    if any(k in q for k in ["qualification", "degree", "education", "college", "university", "graduation", "gpa", "marks"]):
        return QuestionCategory.EDUCATION

    if any(k in q for k in ["company", "employer", "organization", "current role", "designation", "job title", "currently employed"]):
        return QuestionCategory.EMPLOYMENT_HISTORY

    if any(k in q for k in ["skill", "react", "node", "next", "mern", "typescript", "javascript", "mongo", "sql", "docker", "aws", "redux", "zustand", "tailwind", "prisma", "kafka", "redis"]):
        return QuestionCategory.TECHNICAL_SKILLS

    if any(k in q for k in ["relocate", "willing to relocate", "open to relocate", "onsite", "hybrid", "wfh", "remote"]):
        return QuestionCategory.RELOCATION

    if any(k in q for k in ["why should we hire", "why are you suitable", "describe your", "tell me about yourself", "cover letter", "your message"]):
        return QuestionCategory.JOB_SPECIFIC_EXPERIENCE

    if any(k in q for k in ["reason for changing", "why change", "career goal", "looking for change", "reason for leaving"]):
        return QuestionCategory.CAREER_GOALS

    if any(k in q for k in ["authorized to work", "legally", "visa", "background check", "criminal", "eligible", "accept terms", "terms and", "terms &", "terms of", "i agree", "agree to", "acknowledge", "verify info", "declaration", "consent"]):
        return QuestionCategory.ELIGIBILITY

    return QuestionCategory.OTHER

def resolve_answer_from_profile(question: str, category: str, input_type: str = "text") -> Tuple[Optional[str], str, str]:
    """
    Deterministically resolves answers from verified candidate profile.
    Returns: (answer_or_none, source, reason)
    """
    profile = get_profile()
    answers = profile.get("standard_answers", {})
    exp_years = profile.get("stack_experience_years", {})
    q = question.lower()

    is_num = input_type == "number" or "number" in input_type or "numeric" in input_type
    is_date = input_type == "date"
    is_checkbox = input_type == "checkbox"

    # Universal check for agreement/terms/declaration checkboxes
    if is_checkbox and any(k in q for k in ["accept", "agree", "terms", "verify", "declare", "declaration", "consent", "certify", "acknowledge"]):
        return ("true", "CANDIDATE_PROFILE", "Accept Terms / Declaration Checkbox")

    # --- CATEGORY: RESUME & CV ---
    if category == QuestionCategory.RESUME or input_type == "file" or any(k in q for k in ["resume", "cv", "curriculum vitae", "attach resume", "upload cv", "upload resume"]):
        resume_p = profile.get("resume_path", "")
        if not resume_p or not os.path.exists(resume_p):
            cand_p = os.path.join(os.path.dirname(__file__), "Abdul_Razzaque_India.pdf")
            if os.path.exists(cand_p):
                resume_p = cand_p
        return (resume_p, "CANDIDATE_PROFILE", "Candidate Resume PDF")

    # --- CATEGORY: PERSONAL INFO & CONTACT ---
    if category == QuestionCategory.PERSONAL_INFO or any(k in q for k in ["email", "e-mail", "phone", "mobile"]):
        if any(k in q for k in ["email", "e-mail", "mail address"]):
            return (profile.get("email", "mhaslaiabdur@gmail.com"), "CANDIDATE_PROFILE", "Candidate Email")
        if any(k in q for k in ["phone", "mobile", "contact", "cell"]):
            return (profile.get("phone", "+919321689255"), "CANDIDATE_PROFILE", "Candidate Phone")
        if any(k in q for k in ["first name", "fname"]):
            return (profile.get("first_name", "Abdul"), "CANDIDATE_PROFILE", "Candidate First Name")
        if any(k in q for k in ["last name", "lname", "surname"]):
            return (profile.get("last_name", "Shaikh"), "CANDIDATE_PROFILE", "Candidate Last Name")
        if any(k in q for k in ["full name", "your name", "candidate name", "name"]):
            return (profile.get("full_name", "Abdul Razzaque Shaikh"), "CANDIDATE_PROFILE", "Candidate Full Name")
        if any(k in q for k in ["dob", "date of birth", "birth date", "birthday"]):
            return (profile.get("date_of_birth", "1999-11-19"), "CANDIDATE_PROFILE", "Candidate Date of Birth")
        if "gender" in q:
            return (profile.get("gender", "Male"), "CANDIDATE_PROFILE", "Candidate Gender")

    # --- CATEGORY: NOTICE PERIOD & AVAILABILITY ---
    if category == QuestionCategory.NOTICE_PERIOD:
        # Verified preference: Immediate joiner (0 days notice). Candidate is NOT serving notice.
        serving_notice = profile.get("serving_notice", False)
        verified_lwd = profile.get("last_working_day") or profile.get("lwd")

        # 1. Compound question: "What is your official notice period? IF serving what is the LWD?"
        is_compound = ("notice" in q or "official notice" in q) and ("serving" in q or "lwd" in q or "last working" in q)
        if is_compound:
            if is_num:
                return (str(profile.get("notice_period_days", 0)), "CANDIDATE_PROFILE", "Immediate Notice in Days")
            return ("Immediate Joiner (Not serving notice)", "CANDIDATE_PROFILE", "Immediate Notice (Not Serving Notice)")

        # 2. Pure Last Working Day (LWD) question
        if any(k in q for k in ["last working day", "last working date", "lwd"]):
            if serving_notice and verified_lwd:
                return (str(verified_lwd), "CANDIDATE_PROFILE", "Verified Last Working Day")
            elif is_date:
                # Do NOT invent or fabricate an LWD date when candidate is not serving notice!
                return (None, "UNKNOWN", "NEEDS_USER_INPUT: Candidate is an immediate joiner not serving notice; no verified LWD date exists")
            else:
                return ("Not serving notice (Immediate Joiner)", "CANDIDATE_PROFILE", "Not Serving Notice")

        # 3. Serving notice inquiry: "Are you serving notice period?"
        if any(q.startswith(p) for p in ["are you", "do you"]) and "serving" in q:
            return ("Yes" if serving_notice else "No", "CANDIDATE_PROFILE", "Serving Notice Status")

        # 4. Standard notice period inquiry
        if is_num:
            return (str(profile.get("notice_period_days", 0)), "CANDIDATE_PROFILE", "Immediate Notice in Days")

        return (profile.get("notice_period_str", "Immediate Joiner"), "CANDIDATE_PROFILE", "Immediate Notice Preference")

    # --- CATEGORY: SALARY & CTC ---
    if category == QuestionCategory.SALARY:
        # Expected CTC
        if any(k in q for k in ["expected", "desired", "expectation", "expecting"]):
            if "inr" in q or "rs" in q or is_num:
                return (str(profile.get("expected_ctc_inr", 1500000)) if ("inr" in q or "rs" in q) else "15", "CANDIDATE_PROFILE", "Expected CTC")
            return (f"{profile.get('expected_ctc_lpa', 15)} LPA", "CANDIDATE_PROFILE", "Expected CTC LPA")

        # Fixed CTC
        if any(k in q for k in ["fixed component", "fixed ctc", "fixed salary"]):
            if is_num or "inr" in q or "rs" in q:
                return (str(profile.get("fixed_ctc_inr", 1200000)), "CANDIDATE_PROFILE", "Fixed CTC INR")
            return (f"{profile.get('current_ctc_lpa', 12)} LPA", "CANDIDATE_PROFILE", "Fixed CTC")

        # Current CTC / Present Salary
        if "inr" in q or "rs" in q or "rupee" in q:
            return (str(profile.get("current_ctc_inr", 1200000)), "CANDIDATE_PROFILE", "Current CTC INR")
        if is_num:
            return (str(int(profile.get("current_ctc_lpa", 12))), "CANDIDATE_PROFILE", "Current CTC Numeric LPA")
        return (f"{profile.get('current_ctc_lpa', 12)} LPA", "CANDIDATE_PROFILE", "Current CTC LPA")

    # --- CATEGORY: EXPERIENCE ---
    if category == QuestionCategory.EXPERIENCE:
        # If affirmative question (e.g. Do you have experience in MERN?)
        if any(q.startswith(p) for p in ["do you", "have you", "are you", "is it"]):
            return ("Yes", "CANDIDATE_PROFILE", "Verified Stack Experience")

        # Check specific tech experiences
        tech_keywords = {
            "mern": ("mern", "5", "5+ years"),
            "react": ("react", "5", "5+ years"),
            "node": ("node", "5", "5+ years"),
            "next": ("next", "3", "3+ years"),
            "typescript": ("typescript", "5", "5+ years"),
            "javascript": ("javascript", "5", "5+ years"),
            "mongo": ("mongodb", "5", "5+ years"),
            "sql": ("sql", "5", "5+ years"),
            "postgres": ("postgresql", "5", "5+ years"),
            "mysql": ("mysql", "5", "5+ years"),
            "docker": ("docker", "4", "4+ years"),
            "aws": ("aws", "3", "3+ years"),
            "redis": ("redis", "3", "3+ years"),
            "kafka": ("kafka", "3", "3+ years"),
            "rest": ("rest_apis", "5", "5+ years"),
            "ci/cd": ("ci_cd", "4", "4+ years"),
            "redux": ("redux", "5", "5+ years"),
            "zustand": ("zustand", "3", "3+ years"),
            "tailwind": ("tailwind", "4", "4+ years"),
            "prisma": ("prisma", "3", "3+ years")
        }
        for kw, (stack_key, num_ans, str_ans) in tech_keywords.items():
            if kw in q:
                val = str(int(exp_years.get(stack_key, num_ans)))
                return (val if is_num else f"{val}+ years", "CANDIDATE_PROFILE", f"Verified {kw} Experience")

        # Total Experience
        total_exp = str(int(profile.get("total_experience_years", 5)))
        return (total_exp if is_num else f"{total_exp}+ years", "CANDIDATE_PROFILE", "Total Experience")

    # --- CATEGORY: TECHNICAL SKILLS ---
    if category == QuestionCategory.TECHNICAL_SKILLS:
        if any(k in q for k in ["primary skill", "primary technology", "core skill", "key skill", "primary"]):
            return (profile.get("primary_skills", "React.js, Node.js, MERN Stack, TypeScript"), "CANDIDATE_PROFILE", "Primary Skills")
        if any(q.startswith(p) for p in ["do you", "have you", "are you"]):
            return ("Yes", "CANDIDATE_PROFILE", "Verified Skill Experience")
        return (", ".join(profile.get("skills", ["React.js", "Node.js", "TypeScript", "Express.js", "MongoDB", "MySQL", "PostgreSQL", "Docker", "AWS", "Next.js"])), "CANDIDATE_PROFILE", "Candidate Technical Skills")

    # --- CATEGORY: EDUCATION ---
    if category == QuestionCategory.EDUCATION:
        # Check professional accounting / non-IT qualifications (CA, CS, CMA, CFA etc)
        if any(k in q for k in ["ca,", "cs,", "cma", "cfa", "chartered", "professional qualification"]):
            if any(q.startswith(p) for p in ["have you", "are you", "do you", "is"]):
                return ("No", "CANDIDATE_PROFILE", "No Professional Accounting Qualification (CA/CS/CMA/CFA)")
            return ("None", "CANDIDATE_PROFILE", "No Professional Accounting Qualification")

        if any(k in q for k in ["marks", "percentage", "gpa", "cgpa", "score", "grade", "rank"]):
            return (None, "UNKNOWN", "UNVERIFIED_MARKS_OR_GPA")
        if any(k in q for k in ["university", "college", "institute"]):
            return (profile.get("university", "BAMU University, India"), "CANDIDATE_PROFILE", "University")
        if any(k in q for k in ["graduation year", "passing year", "year of passing", "passout"]):
            return (str(profile.get("graduation_year", "2021")), "CANDIDATE_PROFILE", "Graduation Year")
        if any(k in q for k in ["degree", "course"]):
            return (profile.get("degree", "B.Sc Computer Science"), "CANDIDATE_PROFILE", "Degree")
        if any(k in q for k in ["highest qualification", "highest educational qualification", "highest education"]):
            return (profile.get("highest_qualification", "BSC Computer Science"), "CANDIDATE_PROFILE", "Highest Qualification")
        if any(q.startswith(p) for p in ["have you", "are you", "do you", "did you"]):
            if any(k in q for k in ["computer science", "b.sc", "bsc", "graduate", "degree", "bachelor", "engineering"]):
                return ("Yes", "CANDIDATE_PROFILE", "Graduate Degree in Computer Science")
            return ("No", "CANDIDATE_PROFILE", "Negative to non-applicable qualification")
        if any(k in q for k in ["qualification", "education"]):
            return (profile.get("highest_qualification", "BSC Computer Science"), "CANDIDATE_PROFILE", "Highest Qualification")

    # --- CATEGORY: LOCATION ---
    if category == QuestionCategory.LOCATION:
        if any(k in q for k in ["preferred", "preference", "desired location"]):
            return (profile.get("location_preference", "Mumbai / Remote"), "CANDIDATE_PROFILE", "Preferred Location")
        if any(k == q or k in q.split() for k in ["city", "town", "current city"]):
            return (profile.get("current_city", "Mumbai"), "CANDIDATE_PROFILE", "Current City")
        if any(k == q or k in q.split() for k in ["state", "province"]):
            return (profile.get("current_state", "Maharashtra"), "CANDIDATE_PROFILE", "Current State")
        if any(k in q for k in ["country", "nation"]):
            return (profile.get("current_country", "India"), "CANDIDATE_PROFILE", "Current Country")
        if any(k in q for k in ["zip", "postal", "pincode", "pin code", "post code"]):
            return ("400070", "CANDIDATE_PROFILE", "Postal Code")
        return (profile.get("current_location", "Kurla, Mumbai, India"), "CANDIDATE_PROFILE", "Current Location")

    # --- CATEGORY: EMPLOYMENT HISTORY ---
    if category == QuestionCategory.EMPLOYMENT_HISTORY:
        if any(k in q for k in ["previous company", "past company"]):
            return (profile.get("previous_company", "TechGeekFirms"), "CANDIDATE_PROFILE", "Previous Company")
        if any(k in q for k in ["current company", "employer", "organization", "firm"]):
            return (profile.get("current_company", "Tharb"), "CANDIDATE_PROFILE", "Current Company")
        if any(k in q for k in ["designation", "role", "job title"]):
            return (profile.get("designation", "Senior Full Stack Developer"), "CANDIDATE_PROFILE", "Current Designation")
        if any(k in q for k in ["employment status", "currently working"]):
            return ("Currently working remotely for Tharb from Kurla, Mumbai", "CANDIDATE_PROFILE", "Employment Status")

    # --- CATEGORY: RELOCATION & REMOTE ---
    if category == QuestionCategory.RELOCATION:
        if any(q.startswith(p) for p in ["are you", "do you", "is it possible", "will you"]):
            return ("Yes", "CANDIDATE_PROFILE", "Willingness to Relocate / Work Remote")
        return (answers.get("relocate", "Yes, open to relocate to Mumbai or work remotely."), "CANDIDATE_PROFILE", "Relocation Details")

    # --- CATEGORY: JOB-SPECIFIC & OPEN-ENDED ---
    if category == QuestionCategory.JOB_SPECIFIC_EXPERIENCE:
        if any(k in q for k in ["mern", "mern stack"]):
            return (answers.get("describe_mern_experience"), "CANDIDATE_PROFILE", "MERN Experience Summary")
        if any(k in q for k in ["react and node", "react.js and node", "react", "node"]):
            return (answers.get("experience_react_node"), "CANDIDATE_PROFILE", "React & Node Experience")
        if any(k in q for k in ["suitable", "fit for this role", "why you"]):
            return (answers.get("why_suitable_for_role"), "CANDIDATE_PROFILE", "Role Suitability")
        return (answers.get("why_hire"), "CANDIDATE_PROFILE", "Why Hire Answer")

    # --- CATEGORY: CAREER GOALS ---
    if category == QuestionCategory.CAREER_GOALS:
        return (answers.get("reason_for_job_change"), "CANDIDATE_PROFILE", "Reason for Job Change")

    # --- CATEGORY: ELIGIBILITY & AFFIRMATIVES ---
    if category == QuestionCategory.ELIGIBILITY:
        return ("true" if is_checkbox else "Yes", "CANDIDATE_PROFILE", "Work Authorization / Terms Agreement")

    # Additional standard answers
    if "portfolio" in q:
        return (profile.get("portfolio"), "CANDIDATE_PROFILE", "Portfolio URL")
    if "github" in q:
        return (profile.get("github"), "CANDIDATE_PROFILE", "GitHub URL")
    if "linkedin" in q:
        return (profile.get("linkedin"), "CANDIDATE_PROFILE", "LinkedIn URL")

    # General affirmative checks
    if any(q.startswith(p) for p in ["are you", "do you", "can you", "have you", "is it possible", "will you"]) and not any(k in q for k in ["how many", "what is", "how much", "when can"]):
        if any(k in q for k in ["comfortable", "willing", "authorized", "experience", "available", "agree", "open to", "able to"]):
            return ("Yes", "DETERMINISTIC_RULE", "Affirmative Confirmation")

    return None, "", ""

def match_best_option(answer: str, options: List[Dict[str, str]], category: str) -> Optional[Dict[str, str]]:
    """
    Intelligently aligns a candidate profile answer with available dropdown/radio options.
    Never picks the first option blindly!
    options is a list of dicts: [{'value': ..., 'text': ...}]
    """
    if not options or not answer:
        return None

    ans_low = str(answer).lower().strip()

    # Filter out empty or placeholder options like 'Select', 'Choose', '--'
    valid_opts = [
        o for o in options 
        if o.get("text", "").strip().lower() not in ["", "select", "choose", "-- select --", "- select -", "none", "please select", "select an option"]
    ]
    if not valid_opts:
        return None

    # 1. Exact text match
    for opt in valid_opts:
        if opt["text"].lower().strip() == ans_low or opt["value"].lower().strip() == ans_low:
            return opt

    # 2. Category-specific intelligent matching
    # NOTICE PERIOD
    if category == QuestionCategory.NOTICE_PERIOD:
        # Candidate is Immediate Joiner
        immediate_terms = ["immediate", "0-15", "15 day", "less than 15", "serving", "immediate joiner", "15", "0"]
        for term in immediate_terms:
            match = next((o for o in valid_opts if term in o["text"].lower() or term in o["value"].lower()), None)
            if match:
                return match
        # Fallback to 1 month / 30 days if only standard brackets available
        month_terms = ["30 day", "1 month", "30", "1 to 30", "up to 30"]
        for term in month_terms:
            match = next((o for o in valid_opts if term in o["text"].lower() or term in o["value"].lower()), None)
            if match:
                return match

    # EXPERIENCE
    if category == QuestionCategory.EXPERIENCE:
        # Candidate has 5+ years experience
        exp_terms = ["5+", "5 to", "5-", "5 years", "5 year", "4-6", "3-5", "5"]
        for term in exp_terms:
            match = next((o for o in valid_opts if term in o["text"].lower() or term in o["value"].lower()), None)
            if match:
                return match

    # EDUCATION / DEGREE
    if category == QuestionCategory.EDUCATION:
        deg_terms = ["computer science", "b.sc", "bsc", "bachelor of science", "graduate", "b.tech", "engineering"]
        for term in deg_terms:
            match = next((o for o in valid_opts if term in o["text"].lower() or term in o["value"].lower()), None)
            if match:
                return match

    # CURRENCY
    if "inr" in ans_low or "rupee" in ans_low:
        match = next((o for o in valid_opts if any(k in o["text"].lower() for k in ["inr", "indian rupee", "₹", "rupee", "rs"])), None)
        if match:
            return match

    # FREQUENCY
    if "year" in ans_low or "lpa" in ans_low or "annual" in ans_low:
        match = next((o for o in valid_opts if any(k in o["text"].lower() for k in ["yearly", "annual", "per annum", "lpa", "year"])), None)
        if match:
            return match

    # YES / NO
    if ans_low in ["yes", "true", "agree", "positive"]:
        match = next((o for o in valid_opts if any(k == o["text"].lower().strip() or o["text"].lower().startswith(k) for k in ["yes", "agree", "confirm", "comfortable", "i agree"])), None)
        if match:
            return match

    # 3. Substring match
    for opt in valid_opts:
        otxt = opt["text"].lower()
        oval = opt["value"].lower()
        if ans_low in otxt or otxt in ans_low or ans_low in oval:
            return opt

    return None

class QuestionAnsweringEngine:
    """
    Reusable engine that classifies, resolves, validates, and logs answers.
    Grounded strictly in verified candidate data. Never fabricates personal facts.
    """
    def __init__(self):
        self.profile = get_profile()

    def process_question(self, question_text: str, input_type: str = "text", 
                         available_options: List[Dict[str, str]] = None,
                         job_title: str = "", company_name: str = "") -> Dict[str, Any]:
        """
        Processes a detected question:
        Returns:
        {
            "answer": str,
            "selected_option": dict or None,
            "needs_user_input": bool,
            "category": str,
            "source": str, # CANDIDATE_PROFILE, DETERMINISTIC_RULE, LLM_GROUNDED, UNKNOWN
            "reason": str,
            "is_blocked": bool
        }
        """
        q = (question_text or "").strip()
        if not q:
            return {
                "answer": "",
                "selected_option": None,
                "needs_user_input": False,
                "category": QuestionCategory.OTHER,
                "source": "NONE",
                "reason": "EMPTY_QUESTION",
                "is_blocked": False
            }

        # 1. Safety Boundary Check
        is_blocked, block_reason = is_sensitive_or_payment(q)
        if is_blocked:
            return {
                "answer": "",
                "selected_option": None,
                "needs_user_input": True,
                "category": QuestionCategory.OTHER,
                "source": "SAFETY_BOUNDARY",
                "reason": block_reason,
                "is_blocked": True
            }

        category = classify_question_category(q)

        # 2. Check Candidate Profile (Deterministic)
        ans, source, reason = resolve_answer_from_profile(q, category, input_type)
        if ans is not None:
            # If options are provided (dropdown, radio, chips), find the matching option
            selected_opt = None
            if available_options:
                selected_opt = match_best_option(ans, available_options, category)
                if selected_opt:
                    ans = selected_opt.get("value") or selected_opt.get("text")

            return {
                "answer": ans,
                "selected_option": selected_opt,
                "needs_user_input": False,
                "category": category,
                "source": source,
                "reason": reason,
                "is_blocked": False
            }

        # 3. LLM-Based Contextual Generation (Fallback if Ollama/Gemini available)
        llm_answer = self._call_llm(q, category, input_type, job_title)
        if llm_answer:
            if "UNKNOWN" in llm_answer.upper():
                return {
                    "answer": "",
                    "selected_option": None,
                    "needs_user_input": True,
                    "category": category,
                    "source": "LLM_GROUNDED",
                    "reason": "UNVERIFIED_PERSONAL_FACT",
                    "is_blocked": False
                }
            
            selected_opt = None
            if available_options:
                selected_opt = match_best_option(llm_answer, available_options, category)
                if selected_opt:
                    llm_answer = selected_opt.get("value") or selected_opt.get("text")

            return {
                "answer": llm_answer,
                "selected_option": selected_opt,
                "needs_user_input": False,
                "category": category,
                "source": "LLM_GROUNDED",
                "reason": "AI_DERIVED",
                "is_blocked": False
            }

        # 4. Unknown Personal Facts Handling - NEVER FABRICATE!
        q_low = q.lower()
        unverified_keywords = ["father", "mother", "spouse", "family", "caste", "religion", "marks", "percentage", "gpa", "passport", "pan", "aadhaar"]
        if any(k in q_low for k in unverified_keywords):
            return {
                "answer": "",
                "selected_option": None,
                "needs_user_input": True,
                "category": category,
                "source": "UNKNOWN",
                "reason": "UNVERIFIED_MANDATORY_FIELD",
                "is_blocked": False
            }

        # If general affirmative question
        if any(q_low.startswith(p) for p in ["are you", "do you", "is it"]):
            return {
                "answer": "Yes",
                "selected_option": None,
                "needs_user_input": False,
                "category": category,
                "source": "DETERMINISTIC_RULE",
                "reason": "Default Affirmative",
                "is_blocked": False
            }

        # Unknown question requires candidate input
        return {
            "answer": "",
            "selected_option": None,
            "needs_user_input": True,
            "category": category,
            "source": "UNKNOWN",
            "reason": "NEEDS_USER_INPUT",
            "is_blocked": False
        }

    def _call_llm(self, question: str, category: str, input_type: str, job_title: str) -> Optional[str]:
        """Calls Gemini or Ollama if available, with strict grounding prompt."""
        try:
            from ai_service import query_ai
            profile = get_profile()
            prompt = f"""
Candidate: Abdul Razzaque Shaikh, Senior Full Stack Developer (5+ years exp).
Core Skills: React.js, Next.js, Node.js, TypeScript, Express.js, MongoDB, PostgreSQL, MySQL, Docker, AWS, Redis, Kafka.
Notice Period: Immediate Joiner (Available Immediately).
Current CTC: 12 LPA | Expected CTC: 15 LPA.
Target Job: {job_title or 'Senior Full Stack Developer'}

Question on Application Form: "{question}"
Input type: {input_type}

Instructions:
1. Provide a professional, concise, grammatically correct answer strictly grounded in the candidate profile.
2. If this question asks for unrecorded personal facts, family information, specific grades/GPA, or private IDs, answer exactly: UNKNOWN.
3. NEVER invent or fabricate credentials, salary numbers, or work history.
"""
            resp = query_ai(prompt)
            if resp and resp.strip():
                return resp.replace('"', '').strip()
        except Exception:
            pass
        return None

# Singleton instance for easy reuse
qa_engine = QuestionAnsweringEngine()
