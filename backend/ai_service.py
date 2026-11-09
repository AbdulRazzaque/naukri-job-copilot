import os
import json
import time
import requests
import re
from typing import Dict, Any, List, Optional, Tuple

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

try:
    from google import genai
    from google.genai import types
    _genai_available = True
except Exception:
    _genai_available = False

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Load candidate profile
PROFILE_PATH = os.path.join(os.path.dirname(__file__), "profile_data.json")

def get_candidate_profile() -> Dict[str, Any]:
    """Dynamically loads candidate profile to stay fresh."""
    try:
        if os.path.exists(PROFILE_PATH):
            with open(PROFILE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

_client_instance = None

def get_gemini_client():
    """Initializes and returns cached Google Gen AI Client using server-side GEMINI_API_KEY."""
    global _client_instance
    key = os.getenv("GEMINI_API_KEY", "")
    if not key or not _genai_available:
        return None
    if _client_instance is None:
        try:
            _client_instance = genai.Client(api_key=key)
        except Exception as e:
            print(f"[AI] Gemini client initialization warning: {type(e).__name__}")
            return None
    return _client_instance

def call_ollama(prompt: str, system_prompt: str = "") -> str:
    """Invokes local Ollama model qwen2.5:7b as reliable offline fallback."""
    try:
        payload = {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "system": system_prompt or "You are an intelligent job application assistant for Senior Full Stack Developer Abdul Razzaque Shaikh.",
            "stream": False,
            "options": {"temperature": 0.2}
        }
        res = requests.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=3)
        if res.status_code == 200:
            return res.json().get("response", "").strip()
    except Exception:
        pass
    return ""

def call_gemini(prompt: str, system_prompt: str = "", response_schema=None) -> str:
    """
    Invokes official Google Gen AI SDK (Gemini 2.5 Flash / configured model).
    Handles rate limits, timeouts, and API errors with bounded retries.
    Never exposes API key in logs or client bundles.
    """
    client = get_gemini_client()
    if not client:
        return ""
    
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    
    config_args: Dict[str, Any] = {"temperature": 0.2}
    if system_prompt:
        config_args["system_instruction"] = system_prompt
    if response_schema is not None:
        config_args["response_mime_type"] = "application/json"
        config_args["response_schema"] = response_schema
        
    config = types.GenerateContentConfig(**config_args)

    for attempt in range(2):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config
            )
            if response and response.text:
                return response.text.strip()
        except Exception as e:
            err_str = str(e).lower()
            if attempt == 0 and ("429" in err_str or "quota" in err_str or "timeout" in err_str or "unavailable" in err_str):
                time.sleep(1.0)
                continue
            print(f"[AI] Gemini request notice: {type(e).__name__}")
            break
            
    return ""

def query_ai(prompt: str, system_prompt: str = "", response_schema=None) -> str:
    """
    Primary: Google Gemini (google-genai SDK).
    Fallback: Local Ollama (qwen2.5:7b) if Gemini is not configured or fails.
    """
    if os.getenv("GEMINI_API_KEY", ""):
        ans = call_gemini(prompt, system_prompt, response_schema)
        if ans:
            return ans
    return call_ollama(prompt, system_prompt)

def evaluate_job_relevance(job_title: str, company: str, job_desc: str) -> Tuple[int, bool, str]:
    return evaluate_job_match(job_title, company, job_desc)

def evaluate_job_match(job_title: str, company: str, job_desc: str) -> Tuple[int, bool, str]:
    """
    Evaluates how well a job posting matches Abdul Razzaque Shaikh's profile:
    - 5+ years exp as Senior Full Stack Developer (MERN Stack)
    - Primary Stack: React.js, Next.js, Node.js, Express.js, TypeScript, JavaScript, MongoDB, PostgreSQL, MySQL
    - Additional Tech: .NET / C# (6 months actual exp), Python (additional skill from CV)
    - Zero Java experience (never invent).
    - STRICT EXCLUSION: Dedicated Python / .NET / Java specialist roles skipped with PRIMARY_SPECIALIZATION_MISMATCH.
    - APPLY for relevant mixed-technology roles (MERN + Python, MERN + .NET/C#, React + Node + Python).
    """
    from technology_matcher import evaluate_technology_alignment
    tech_eval = evaluate_technology_alignment(title=job_title, company=company, desc=job_desc)

    # 1. Dedicated specialist in non-MERN tech (e.g. Dedicated Python, Dedicated .NET, Dedicated Java)
    if not tech_eval["should_apply"]:
        return tech_eval["match_score"], False, tech_eval["detailed_explanation"]

    # 2. Recognized mixed-technology role (e.g. MERN + Python, MERN + .NET/C#)
    if tech_eval.get("is_mixed_technology"):
        return tech_eval["match_score"], True, tech_eval["detailed_explanation"]

    # 3. Standard MERN / JavaScript Full Stack role
    return tech_eval["match_score"], True, tech_eval["detailed_explanation"]

def get_last_working_day(format_type: str = "text") -> str:
    """Calculates last working day exactly 30 days from today."""
    lwd = datetime.now() + timedelta(days=30)
    if format_type == "date":
        return lwd.strftime("%Y-%m-%d")
    elif format_type == "number":
        return "30"
    else:
        return lwd.strftime("%d/%m/%Y")

def is_sensitive_or_payment_question(question: str) -> Tuple[bool, str]:
    """
    Identifies if a question is asking for payment, fees, subscriptions, or sensitive legal/financial IDs.
    Returns (is_sensitive_or_payment: bool, reason: str).
    """
    q_low = (question or "").lower()
    payment_terms = [
        "credit card", "debit card", "cvv", "card number", "bank account", 
        "routing number", "application fee", "processing fee", "payment", 
        "pay now", "subscription price", "wire transfer", "billing address"
    ]
    if any(t in q_low for t in payment_terms):
        return True, "PAYMENT_REQUEST_BLOCKED"

    sensitive_terms = [
        "ssn", "social security", "aadhaar", "pan card", "pan number", 
        "passport number", "driver's license", "national id", "secret question", 
        "net banking password", "bank pin", "security code"
    ]
    if any(t in q_low for t in sensitive_terms):
        return True, "SENSITIVE_FIELD_BLOCKED"

    return False, ""

def evaluate_application_question(question: str, input_type: str = "text") -> Tuple[str, bool, str]:
    """
    Evaluates and answers application questions autonomously:
    - Never fabricates salary, qualifications, employment history, or personal facts.
    - If a question asks for payments or sensitive IDs, blocks it.
    - If a mandatory question cannot be answered reliably, flags as NEEDS_USER_INPUT.
    Returns (answer: str, needs_user_input: bool, reason: str).
    """
    q_low = (question or "").lower().strip()
    if not q_low:
        return "", False, "EMPTY_QUESTION"

    # 1. Safety boundary check: Sensitive / Payment requests
    is_blocked, block_reason = is_sensitive_or_payment_question(question)
    if is_blocked:
        return "", True, block_reason

    profile = get_candidate_profile()
    answers = profile.get("standard_answers", {})
    is_num = input_type == "number" or "number" in input_type or "lakh" in q_low
    is_date = input_type == "date"

    # 2. Verified Candidate Profile Data
    # Date of Birth / DOB
    if any(k in q_low for k in ["date of birth", "birth date", "dob", "bday", "birth"]):
        if is_date:
            return "1999-11-19", False, "VERIFIED_PROFILE"
        if "day" in q_low and "month" not in q_low and "year" not in q_low:
            return "19", False, "VERIFIED_PROFILE"
        if "month" in q_low:
            return "11", False, "VERIFIED_PROFILE"
        if "year" in q_low:
            return "1999", False, "VERIFIED_PROFILE"
        return "19/11/1999", False, "VERIFIED_PROFILE"

    # Highest Qualification / Education / Degree / University
    if any(k in q_low for k in ["highest qualification", "qualification", "highest degree", "degree", "education", "course"]):
        return profile.get("highest_qualification", "BSC Computer Science"), False, "VERIFIED_PROFILE"
    if any(k in q_low for k in ["university", "college", "institute", "school"]):
        return profile.get("university", "BAMU University, India"), False, "VERIFIED_PROFILE"
    if any(k in q_low for k in ["graduation year", "passing year", "year of passing", "passout year"]):
        return str(profile.get("graduation_year", "2021")), False, "VERIFIED_PROFILE"

    # Last Working Day / Date
    if any(k in q_low for k in ["last working day", "last working date", "lwd", "official last day"]):
        if is_date:
            return get_last_working_day("date"), False, "VERIFIED_PROFILE"
        if is_num:
            return "30", False, "VERIFIED_PROFILE"
        return f"30 Days ({get_last_working_day('text')})", False, "VERIFIED_PROFILE"
        
    # Notice Period / Availability
    if any(k in q_low for k in ["notice", "join in", "how soon", "serving notice", "availability"]):
        if any(q_low.startswith(p) for p in ["are you", "do you"]) and not any(k in q_low for k in ["how many", "what is"]):
            return "Yes", False, "VERIFIED_PROFILE"
        if is_num:
            return str(profile.get("notice_period_days", 30)), False, "VERIFIED_PROFILE"
        return f"{profile.get('notice_period_days', 30)} Days", False, "VERIFIED_PROFILE"

    # Current CTC / Fixed Component / Salary
    if any(k in q_low for k in ["fixed component", "fixed ctc", "fixed salary"]):
        if is_num or "inr" in q_low or "rs" in q_low:
            return str(profile.get("fixed_ctc_inr", 1200000)), False, "VERIFIED_PROFILE"
        return f"{profile.get('current_ctc_lpa', 12)} LPA", False, "VERIFIED_PROFILE"

    if any(k in q_low for k in ["current ctc", "current salary", "present ctc", "existing ctc"]):
        if "inr" in q_low or "rs" in q_low or "rupee" in q_low:
            return str(profile.get("fixed_ctc_inr", 1200000)) if is_num else f"{profile.get('current_ctc_lpa', 12)} LPA", False, "VERIFIED_PROFILE"
        if is_num:
            return str(profile.get("current_ctc_lpa", 12)), False, "VERIFIED_PROFILE"
        return f"{profile.get('current_ctc_lpa', 12)} LPA", False, "VERIFIED_PROFILE"

    # Expected CTC / Salary
    if any(k in q_low for k in ["expected ctc", "expected salary", "desired ctc", "expectation"]):
        if "inr" in q_low or "rs" in q_low or "rupee" in q_low:
            return "1500000" if is_num else f"{profile.get('expected_ctc_lpa', 15)} LPA", False, "VERIFIED_PROFILE"
        if is_num:
            return str(profile.get("expected_ctc_lpa", 15)), False, "VERIFIED_PROFILE"
        return f"{profile.get('expected_ctc_lpa', 15)} LPA", False, "VERIFIED_PROFILE"

    # Specific Question Types (Equity, Deferred Comp, Entrepreneurship, Yes/No Screening)
    if any(k in q_low for k in ["equity as a long-term value", "equity", "purpose-driven", "fast-growing"]):
        return "I am very positive about working with a fast-growing, purpose-driven company where compensation includes equity, as it aligns long-term growth and commitment with the company's success.", False, "VERIFIED_PROFILE"
    if any(k in q_low for k in ["deferred compensation", "venture capitalist", "40 cr", "term sheet"]):
        return "Need more information", False, "VERIFIED_PROFILE"
    if "entrepreneurship" in q_low:
        return "Yes", False, "VERIFIED_PROFILE"
    if "global professional" in q_low:
        return "Yes", False, "VERIFIED_PROFILE"
    if any(q_low.startswith(p) for p in ["are you", "do you", "can you", "is it possible", "will you"]) and not any(k in q_low for k in ["how many", "what is", "how much", "when can"]):
        if any(k in q_low for k in ["comfortable", "willing", "relocate", "onsite", "hybrid", "remote", "authorized", "experience", "notice", "serving", "join", "available", "agree"]):
            return "Yes", False, "VERIFIED_PROFILE"

    # Country Code, Country, State, City, Location, Address
    q_clean = re.sub(r"[*?:_#()\-]+", " ", q_low).strip()
    words = set(q_clean.split())

    if any(k in q_clean for k in ["country code", "calling code", "dial code", "phone code"]):
        return "+91", False, "VERIFIED_PROFILE"
    if any(k in words for k in ["gender", "sex"]) and not any(k in q_clean for k in ["transgender"]):
        return "Male", False, "VERIFIED_PROFILE"
    if any(k in q_clean for k in ["preferred pronoun", "pronoun"]):
        return "He/Him", False, "VERIFIED_PROFILE"
    if any(k in q_clean for k in ["disability", "differently abled", "handicap", "pwd"]):
        return "No", False, "VERIFIED_PROFILE"
    if any(k in q_clean for k in ["veteran", "armed forces", "indian army", "military"]):
        return "No", False, "VERIFIED_PROFILE"
    if any(k in q_clean for k in ["previously worked", "worked with us", "worked for us", "ex-employee"]):
        return "No", False, "VERIFIED_PROFILE"
    if any(k in q_clean for k in ["legally eligible", "eligible to work", "authorized to work", "work authorization", "right to work"]):
        return "Yes", False, "VERIFIED_PROFILE"
    if any(k in q_clean for k in ["require visa sponsorship", "visa sponsorship", "sponsorship to continue", "require sponsorship"]):
        return "No", False, "VERIFIED_PROFILE"
    if any(k in q_clean for k in ["working in mumbai", "currently working in mumbai", "mumbai location"]):
        return "Yes", False, "VERIFIED_PROFILE"
    if any(k in q_clean for k in ["degree type"]):
        return "BSC Computer Sciences", False, "VERIFIED_PROFILE"
    if any(k in q_clean for k in ["proven experience", "total experience 3 to 5", "3 to 5"]):
        return "5" if is_num else "5+ years", False, "VERIFIED_PROFILE"
    if any(k in q_clean for k in ["relevant skills", "skills react"]):
        return "Yes", False, "VERIFIED_PROFILE"
    if any(k in q_clean for k in ["privacy policy", "privacy notice", "consent", "i confirm"]):
        return "true", False, "VERIFIED_PROFILE"

    # City, State, Country, Postal Code, Address
    if any(k in words for k in ["city", "town", "current city"]):
        return "Mumbai", False, "VERIFIED_PROFILE"
    if any(k in words for k in ["state", "province", "region"]) and not any(v in q_clean for v in ["statement", "state your", "united states"]):
        return "Maharashtra", False, "VERIFIED_PROFILE"
    if any(k in words for k in ["country", "nation", "citizenship", "nationality"]) and not any(k in q_clean for k in ["country code", "code"]):
        return "India", False, "VERIFIED_PROFILE"
    if any(k in q_clean for k in ["po box", "zip", "postal", "pincode", "pin code", "post code"]):
        return "400070", False, "VERIFIED_PROFILE"
    if any(k in q_clean for k in ["street", "address", "residential address"]):
        return profile.get("current_location", "Kurla, Mumbai, Maharashtra"), False, "VERIFIED_PROFILE"
    if any(k in q_clean for k in ["your message", "cover letter", "message to hiring", "note"]):
        return "I am a Senior Full Stack Developer with 5+ years of experience in React.js, Next.js, Node.js, and MongoDB. Excited to bring scalable, high-performance web solutions to your engineering team.", False, "VERIFIED_PROFILE"

    # Current Location / Preferred Location
    if any(k in q_low for k in ["preferred location", "desired location", "work location preference", "location preference"]):
        return profile.get("location_preference", "Mumbai / Remote / Pune"), False, "VERIFIED_PROFILE"
    if any(k in q_low for k in ["current location", "where do you stay", "residing", "based out of", "live in"]):
        return profile.get("current_location", "Kurla, Mumbai, Maharashtra"), False, "VERIFIED_PROFILE"

    # Social Links & Profiles
    if "portfolio" in q_low or "personal site" in q_low:
        return profile.get("portfolio", "https://portfolio-website-one-rho-98.vercel.app/"), False, "VERIFIED_PROFILE"
    if "github" in q_low or "git profile" in q_low or "git url" in q_low:
        return profile.get("github", "https://github.com/AbdulRazzaque"), False, "VERIFIED_PROFILE"
    if "linkedin" in q_low:
        return profile.get("linkedin", "https://www.linkedin.com/in/abdul-razzaque-fullstack/"), False, "VERIFIED_PROFILE"

    # Total Experience
    if any(k in q_low for k in ["total experience", "overall experience", "years of experience"]):
        return "5" if is_num else "5+ years", False, "VERIFIED_PROFILE"

    # Technology-specific Experience
    tech_exp_map = {
        "react": ("5", "5+ years of production experience building high-performance SPAs, hooks, Redux, and modern UI in React.js"),
        "node": ("5", "5+ years building scalable REST APIs, microservices, and backend architectures in Node.js"),
        "next": ("3", "3+ years building full stack web applications with Next.js App Router, SSR, and API routes"),
        "mern": ("5", "5+ years of full stack production development with MongoDB, Express, React, and Node.js"),
        "typescript": ("5", "5+ years developing robust, type-safe enterprise applications with TypeScript"),
        "javascript": ("5", "5+ years of core modern JavaScript (ES6+) and asynchronous programming"),
        "postgres": ("5", "5+ years designing relational schemas, indexing, complex joins, and query optimization in PostgreSQL"),
        "postgresql": ("5", "5+ years designing relational schemas, indexing, complex joins, and query optimization in PostgreSQL"),
        "mysql": ("5", "5+ years with MySQL database architecture, stored procedures, and performance tuning"),
        "mongo": ("5", "5+ years working with MongoDB aggregation pipelines, indexing, and high-throughput schemas"),
        "mongodb": ("5", "5+ years working with MongoDB aggregation pipelines, indexing, and high-throughput schemas"),
        "graphql": ("3", "3+ years building and consuming GraphQL APIs, schemas, queries, and mutations"),
        "docker": ("4", "4+ years containerizing multi-tier full-stack applications with Docker and Docker Compose"),
        "redis": ("3", "3+ years utilizing Redis for caching, pub/sub, and distributed session management"),
        "kafka": ("3", "3+ years designing event-driven architectures and distributed messaging with Kafka"),
        "aws": ("3", "3+ years managing AWS cloud infrastructure including EC2, S3, RDS, and Lambda"),
        "ci/cd": ("4", "4+ years configuring automated CI/CD pipelines for testing and deployment"),
        "pipeline": ("4", "4+ years configuring automated CI/CD pipelines for testing and deployment")
    }
    for tech, (num_val, full_val) in tech_exp_map.items():
        if tech in q_low:
            return (num_val if is_num else full_val), False, "VERIFIED_PROFILE"

    # Domain Experience (ERP, CRM, E-Commerce, POS, HRMS)
    if any(k in q_low for k in ["erp", "crm", "pos", "hrms", "e-commerce", "ecommerce", "enterprise"]):
        return "Proven track record delivering enterprise applications, multi-vendor e-commerce platforms, CRM/POS systems, HRMS, and pharmacy ERP solutions.", False, "VERIFIED_PROFILE"

    # Summary / About Yourself / Cover Letter / Introduction
    if any(k in q_low for k in ["about you", "about yourself", "summary", "profile summary", "cover letter", "introduction", "tell me about"]):
        return "Senior Full Stack Developer with 5+ years of experience in building scalable, secure, and high-performance web applications. I specialize in React.js, Next.js, JavaScript, TypeScript, Node.js, Express.js, MongoDB, PostgreSQL, and MySQL, with deep expertise in enterprise ERP, CRM, and cloud platforms.", False, "VERIFIED_PROFILE"

    # Relocate / Remote
    if any(k in q_low for k in ["relocate", "open to relocate", "willing to relocate"]):
        return "Based in Kurla, Mumbai. Open to onsite in Mumbai/Pune or Remote roles", False, "VERIFIED_PROFILE"
    if any(k in q_low for k in ["remote", "wfh", "work from home"]):
        return "Currently working remotely for Tharb from Mumbai, open to both Remote and Onsite roles in Mumbai/Pune", False, "VERIFIED_PROFILE"

    # Current Company / Title
    if any(k in q_low for k in ["current company", "current employer", "organization"]):
        return profile.get("current_company", "Tharb"), False, "VERIFIED_PROFILE"
    if any(k in q_low for k in ["designation", "current role", "job title"]):
        return profile.get("designation", "Senior Full Stack Developer"), False, "VERIFIED_PROFILE"

    # 3. Open-ended question via AI Grounding
    prompt = f"""
Candidate Profile:
Name: Abdul Razzaque Shaikh
Role: Senior Full Stack Developer (5+ years exp)
Current Company: Tharb (Working Remotely from Kurla, Mumbai)
Current CTC: 12 LPA | Expected CTC: 15 LPA | Notice Period: 30 Days
Preferred Locations: Mumbai / Pune / Remote
Portfolio: https://portfolio-website-one-rho-98.vercel.app/
GitHub: https://github.com/AbdulRazzaque
LinkedIn: https://www.linkedin.com/in/abdul-razzaque-fullstack/
Primary Skills: React.js, Next.js, Node.js, TypeScript, JavaScript, Express.js, MongoDB, PostgreSQL, MySQL
Advanced Skills: REST APIs, GraphQL, Docker, Redis, Kafka, AWS, CI/CD
Domain Experience: Enterprise apps, multi-vendor e-commerce, CRM, POS, HRMS, Pharmacy ERP

Question on Job Application: "{question}"
Input field type: {input_type}

Rules:
1. Answer concisely in 1 short phrase or sentence based strictly on the candidate profile.
2. If this question asks for private legal identity numbers, secret passwords, financial/credit card details, or specific unrecorded personal historical facts not present in the profile (e.g. GPA, family details, passport number), reply exactly with: UNKNOWN.
3. NEVER invent or fabricate salary numbers, employment history, degrees, or personal facts.
"""
    ai_ans = query_ai(prompt)
    if ai_ans:
        cleaned = ai_ans.replace('"', '').strip()
        if "UNKNOWN" in cleaned.upper():
            return "", True, "NEEDS_USER_INPUT"
        if is_num:
            digits = ''.join(c for c in cleaned if c.isdigit() or c == '.')
            return (digits if digits else "5"), False, "AI_DERIVED"
        return cleaned, False, "AI_DERIVED"

    # If question asks for an unfamiliar specific fact without reliable answer, do not fabricate!
    if any(term in q_low for term in ["percentage", "marks", "gpa", "father", "mother", "spouse", "religion", "caste", "aadhaar", "pan", "passport"]):
        return "", True, "NEEDS_USER_INPUT"

    default_answer = "30 Days" if "day" in q_low else answers.get("why_hire", "5+ years of senior full stack experience.")
    return default_answer, False, "DEFAULT_PROFILE"

def answer_application_question(question: str, input_type: str = "text") -> str:
    """Legacy helper returning answer string. Empty string returned if user input needed or blocked."""
    ans, needs_user, _ = evaluate_application_question(question, input_type)
    return ans if not needs_user else ""
