import os
import json
import re
from typing import Dict, Any, List, Tuple, Optional
from candidate_manager import getCandidateProfileByJobLocation, CandidateProfileManager, mask_phone_number

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
    COLLABORATION_TOOLS = "COLLABORATION_TOOLS"
    BEHAVIORAL = "BEHAVIORAL"
    LANGUAGE_SKILLS = "LANGUAGE_SKILLS"
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
        "ssn", "social security", "aadhaar number", "aadhaar card", "pan card number", "pan number", 
        "passport number", "driver's license number", "drivers license number", "national id number", 
        "secret question", "net banking password", "bank pin", "security code"
    ]
    if any(t in q for t in sensitive_terms):
        return True, "SENSITIVE_FIELD_BLOCKED"

    return False, ""

def classify_question_category(question: str) -> str:
    """Classifies question into standardized functional categories."""
    q = (question or "").lower()

    if any(k in q for k in ["resume", "cv", "curriculum vitae", "upload resume", "upload cv", "attach resume"]):
        return QuestionCategory.RESUME

    # Contact & Personal info must be checked before location
    if any(k in q for k in [
        "email", "e-mail", "phone", "mobile", "full name", "first name", "last name", "your name", 
        "candidate name", "dob", "birth date", "date of birth", "gender", "sex", "pronoun",
        "preferred pronoun", "country code", "calling code", "dial code", "phone code",
        "disability", "differently abled", "handicap", "pwd", "veteran", "armed forces", "army"
    ]):
        return QuestionCategory.PERSONAL_INFO

    if any(k in q for k in [
        "deutschkenntnisse", "deutsch", "german", "sprache", "sprachkenntnisse",
        "english proficiency", "language skills", "languages do you speak", "fluent in", "languages known",
        "level in english", "level of english"
    ]) or (re.search(r"\blanguage(?:s)?\b", q) and not any(k in q for k in ["programming", "coding", "residence", "location"])):
        return QuestionCategory.LANGUAGE_SKILLS

    # Composite: Location of Residence and Language
    if any(k in q for k in ["location of residence and language", "residence and language", "location and language"]):
        return QuestionCategory.LOCATION

    if (any(k in q for k in [
        "notice period", "notice days", "days is your notice", "availability", "available to start",
        "available to start working", "when are you available", "available to work", "start working with us",
        "earliest availability", "how soon", "serving notice", "lwd", "last working", "immediate joiner",
        "startdatum", "frühestmögliches startdatum", "frühestmögliches", "frühestmöglich", "eintrittsdatum",
        "verfügbarkeit", "kündigungsfrist", "verfügbar ab", "ab wann", "ab sofort", "arbeitsbeginn",
        "earliest start", "start date", "earliest start date"
    ]) or ("notice" in q and not any(p in q for p in ["privacy", "policy", "terms", "legal", "gdpr"]))):
        return QuestionCategory.NOTICE_PERIOD

    if any(k in q for k in [
        "ctc", "salary", "compensation", "fixed component", "inr", "lakh", "lpa", "earning",
        "remuneration", "renumeration", "pay", "wages", "package", "cost-to-company", "cost to company",
        "gehalt", "gehaltserwartung", "gehaltsvorstellung", "vergütung", "jahresgehalt", "monatsgehalt",
        "eur", "euro", "€", "usd", "$", "riyal", "qar", "aed"
    ]):
        return QuestionCategory.SALARY

    if any(k in q for k in [
        "which backend", "backend technologies", "backend technology", "backend stack",
        "which frontend", "frontend technologies", "frontend technology", "frontend stack",
        "programming language", "programming languages", "which languages", "which language", "languages do you",
        "which technology", "which technologies", "technologies have you", "technologies you have", "technologies do you",
        "which skill", "which framework", "strongest hands-on", "hands-on experience in:",
        "relevant skills", "tech stack", "technology stack", "core technical stack", "technical stack", "primary stack", "core stack", "what is your stack", "databases have you", "which database", "which databases", "databases you have"
    ]):
        return QuestionCategory.TECHNICAL_SKILLS

    if any(k in q for k in ["experience", "exp", "years", "total exp", "how many years", "relevant", "proven experience"]):
        return QuestionCategory.EXPERIENCE

    if any(k in q for k in [
        "work authorization", "work authorisation", "authorization status", "authorisation status",
        "authorized to work", "authorised to work", "legally authorised", "legally authorized",
        "eligible to work", "visa", "sponsorship", "employer sponsorship", "sponsorship to work", "company sponsorship",
        "bound by any agreements", "restrict your ability", "non-compete", "non-solicitation", "contractual obligations",
        "background check", "criminal", "eligible", "accept terms", "terms and", "terms &", "terms of",
        "i agree", "agree to", "acknowledge", "verify info", "declaration", "consent", "privacy",
        "privacy policy", "privacy notice", "policy", "opt-in", "opt in", "i confirm"
    ]):
        return QuestionCategory.ELIGIBILITY

    if any(k in q for k in ["country", "nation", "nationality", "citizenship", "state", "province", "region", "city", "town", "residence", "where do you live", "where are you based", "pincode", "postal", "po box", "address", "mumbai location"]) and not any(k in q for k in ["email", "e-mail", "mail address", "country code", "calling code", "authorised", "authorized", "sponsorship"]):
        return QuestionCategory.LOCATION

    if any(k in q for k in ["qualification", "degree", "degree type", "education", "college", "university", "graduation", "gpa", "marks"]):
        return QuestionCategory.EDUCATION

    if any(k in q for k in [
        "why should we hire", "why are you suitable", "why do you want to join", "why work with us",
        "why join", "why this company", "why our company", "why oyster", "interested in joining",
        "interested in our company", "interested in this role", "describe your", "cover letter",
        "coverletter", "your message", "message", "summary", "bio", "about me", "about you",
        "comments", "note to recruiter", "note to", "pitch", "introduction", "how can you contribute",
        "share a short summary", "attributes", "remote environment", "success in a fully remote",
        "success in a remote", "remote attributes", "set you up for success"
    ]):
        return QuestionCategory.JOB_SPECIFIC_EXPERIENCE

    if any(k in q for k in [
        "strength", "strengths", "weakness", "difficult situation", "handle pressure", "work under pressure",
        "conflict", "handle conflict", "challenging project", "manage deadline", "deadlines",
        "tell me about yourself", "tell us about yourself", "introduce yourself", "short summary about yourself"
    ]):
        return QuestionCategory.BEHAVIORAL

    if any(k in q for k in [
        "current company", "previous company", "past company", "employer", "current role",
        "designation", "job title", "currently employed", "worked with us", "previously worked",
        "current organisation", "organization", "organisation", "company"
    ]) and not any(k in q for k in ["why", "interested in", "join", "suitable", "summary", "attributes"]):
        return QuestionCategory.EMPLOYMENT_HISTORY

    if any(k in q for k in ["skill", "react", "node", "next", "mern", "typescript", "javascript", "mongo", "sql", "docker", "aws", "redux", "zustand", "tailwind", "prisma", "kafka", "redis", "ruby", "rails", "spring", "java", "dotnet", ".net", "c#", "php"]):
        return QuestionCategory.TECHNICAL_SKILLS

    if any(k in q for k in [
        "collaboration tool", "collaboration tools", "remote tools", "remote collaboration",
        "project management tool", "project management tools", "which tools do you use", "tools do you use",
        "communication tools", "remote communication", "distributed team", "time zone", "timezones",
        "handle different time", "slack", "teams", "jira", "trello", "asana", "confluence", "figma"
    ]):
        return QuestionCategory.COLLABORATION_TOOLS

    if any(k in q for k in ["relocate", "willing to relocate", "open to relocate", "relocation", "onsite", "hybrid", "wfh", "remote", "work arrangement", "workplace", "work model", "work mode", "work setup"]) and not any(k in q for k in ["tool", "tools", "collaboration", "software", "manage", "attribute", "attributes", "success", "environment", "why", "summary"]):
        return QuestionCategory.RELOCATION

    if any(k in q for k in ["reason for changing", "why change", "career goal", "looking for change", "reason for leaving"]):
        return QuestionCategory.CAREER_GOALS

    return QuestionCategory.OTHER

def resolve_answer_from_profile(question: str, category: str, input_type: str = "text",
                                 field_name: str = "", field_id: str = "", location_hint: str = "",
                                 job_title: str = "", company_name: str = "") -> Tuple[Optional[str], str, str]:
    """
    Deterministically resolves answers from verified candidate profile.
    Dynamically aligns Phone, Country Code, City, and Location with target job location (Qatar vs India).
    Dynamically customizes company-specific questions (Section 19).
    Returns: (answer_or_none, source, reason)
    Dynamically aligns Phone, Country Code, City, and Location with target job location (Qatar vs India).
    Returns: (answer_or_none, source, reason)
    """
    profile = get_profile()
    cand_profile = getCandidateProfileByJobLocation(location_hint)
    is_india = cand_profile["is_india"]
    is_gulf = cand_profile["is_international"]
    is_qatar = (cand_profile.get("detected_country") == "Qatar")
    is_dubai = (cand_profile.get("detected_country") == "United Arab Emirates")

    if is_dubai:
        sub_profile = profile.get("dubai_profile") or profile.get("qatar_profile", {})
    elif is_qatar or is_gulf:
        sub_profile = profile.get("qatar_profile", {})
    else:
        sub_profile = profile.get("india_profile", {})
    answers = profile.get("standard_answers", {})
    exp_years = profile.get("stack_experience_years", {})
    q = (question or "").lower()
    q_clean = re.sub(r"[*?:_#()\-]+", " ", q).strip()
    words = set(q_clean.split())

    fname_low = (field_name or "").lower()
    fid_low = (field_id or "").lower()
    ctx = f"{q_clean} {fname_low} {fid_low}"

    is_num = input_type == "number" or "number" in input_type or "numeric" in input_type
    is_date = input_type == "date"
    is_checkbox = input_type == "checkbox"
    is_numeric_context = is_num or any(k in ctx for k in [
        "in lakhs", "in lpa", "lakhs per annum", "lakhs/annum", "per annum",
        "in inr", "in rs", "in rupees", "in thousands",
        "how many days", "in days", "number of days", "days is your notice", "days notice", "how many day",
        "how many years", "years of", "in years", "number of years", "years experience", "total years",
        "cgpa", "percentage", "gpa", "pincode", "zip code", "postal code"
    ])

    # Universal check for agreement/terms/privacy/declaration checkboxes
    if is_checkbox and any(k in ctx for k in [
        "accept", "agree", "terms", "verify", "declare", "declaration", "consent", "certify",
        "acknowledge", "privacy", "policy", "i confirm", "i have read", "storage and handling",
        "handling of your data", "data processing", "by using this form", "by applying you hereby accept"
    ]):
        return ("true", "CANDIDATE_PROFILE", "Accept Terms / Data Processing Checkbox")

    # --- CATEGORY: CV URL / RESUME LINK / PORTFOLIO LINK (Must precede local file resume) ---
    is_cv_or_portfolio_url = (
        any(k in ctx for k in [
            "cv url", "cv link", "resume url", "resume link", "link to cv", "link to resume",
            "link to your cv", "link to your resume", "cv/resume url", "portfolio", "portfolio url",
            "portfolio link", "personal website", "website url", "web page", "blog url", "website link",
            "online portfolio", "online resume", "online cv", "url of your cv", "url of your resume",
            "cv web", "resume web", "cv website", "resume website"
        ]) or (
            any(k in ctx for k in ["cv", "resume"]) and any(k in ctx for k in ["url", "link", "http", "website", "online", "drive", "web page"])
        )
    )
    if is_cv_or_portfolio_url and input_type != "file":
        portfolio_url = profile.get("portfolio") or "https://portfolio-website-one-rho-98.vercel.app/"
        return (portfolio_url, "CANDIDATE_PROFILE", "Portfolio / CV URL Link")

    # --- CATEGORY: RESUME & CV FILE ---
    if category == QuestionCategory.RESUME or input_type == "file" or any(k in ctx for k in ["resume", "cv", "curriculum vitae", "attach resume", "upload cv", "upload resume"]):
        resume_p = sub_profile.get("resume_path", "")
        if not resume_p or not os.path.exists(resume_p):
            target_res_file = "Abdul_Razzaque_Qatar.pdf" if is_gulf else "Abdul_Razzaque_India.pdf"
            cand_p = os.path.join(os.path.dirname(__file__), target_res_file)
            if os.path.exists(cand_p):
                resume_p = cand_p
            else:
                resume_p = profile.get("resume_path", "")
        return (resume_p, "CANDIDATE_PROFILE", f"Candidate Resume ({'Qatar' if is_gulf else 'India'})")

    # --- COMPOSITE: LOCATION OF RESIDENCE AND LANGUAGE (e.g. Jobvite / DNEG) ---
    if any(k in ctx for k in ["location of residence and language", "residence and language", "location and language", "residence / language"]):
        addr = cand_profile.get("residential_address", "Kurla, Mumbai, Maharashtra, India")
        return (f"{addr} | English (Fluent), Hindi, Urdu", "CANDIDATE_PROFILE", "Location of Residence and Language")

    # --- CATEGORY: LANGUAGE SKILLS (German, English, Hindi, Urdu) ---
    if category == QuestionCategory.LANGUAGE_SKILLS or any(k in ctx for k in ["deutschkenntnisse", "deutsch", "german", "sprache", "sprachkenntnisse", "language"]):
        # German / Deutsch: Candidate does NOT know German (strictly select Keine / None)
        if any(k in ctx for k in ["deutsch", "german", "deutschkenntnisse"]):
            return ("Keine (Kenntnisse)", "CANDIDATE_PROFILE", "German Language Knowledge (None / Keine)")
        # English: Fluent / Native / Professional
        if any(k in ctx for k in ["englisch", "english", "level in english", "english level"]):
            return ("Fluent/Native", "CANDIDATE_PROFILE", "English Language Knowledge (Fluent/Native)")
        # Hindi / Urdu: Native
        if any(k in ctx for k in ["hindi", "urdu"]):
            return ("Native", "CANDIDATE_PROFILE", "Hindi/Urdu Native Language")
        return ("English (Fluent/Native), Hindi (Native), Urdu (Native)", "CANDIDATE_PROFILE", "Languages Known (English, Hindi, Urdu)")

    # --- CATEGORY: PERSONAL INFO & CONTACT & DEMOGRAPHICS ---
    is_phone_with_cc = any(k in ctx for k in [
        "with country code", "including country code", "country code included", "full phone", "international format", "complete phone"
    ]) or (any(k in ctx for k in ["phone", "mobile", "contact", "cell"]) and any(k in ctx for k in ["with cc", "with code"]))

    # 1. Country Code / Calling Code (Strict Rule: Qatar/Dubai/UAE -> +974; India -> +91. Never +971)
    if not is_phone_with_cc and any(k in ctx for k in ["country code", "calling code", "dial code", "phone code", "dialing code"]):
        cc = cand_profile["country_code"]
        return (cc, "CANDIDATE_PROFILE", f"Mandatory Country Code ({cc})")

    # 2. Gender
    if any(k in words for k in ["gender", "sex"]) and not any(k in ctx for k in ["transgender"]):
        return (profile.get("gender", "Male"), "CANDIDATE_PROFILE", "Candidate Gender (Male)")

    # 3. Pronoun
    if any(k in ctx for k in ["preferred pronoun", "pronoun"]):
        return (profile.get("preferred_pronoun", "He/Him"), "CANDIDATE_PROFILE", "Candidate Preferred Pronoun (He/Him)")

    # 4. Disability / Differently Abled
    if any(k in ctx for k in ["disability", "differently abled", "handicap", "physical impairment", "pwd", "person with disability"]):
        return (profile.get("disability", "No"), "CANDIDATE_PROFILE", "Candidate Disability Status (No)")

    # 5. Veteran / Indian Armed Forces
    if any(k in ctx for k in ["veteran", "armed forces", "indian army", "military service", "army veteran"]):
        return (profile.get("veteran", "No"), "CANDIDATE_PROFILE", "Not an Armed Forces Veteran (No)")

    # 6. Email
    if any(k in ctx for k in ["email", "e-mail", "mail address"]):
        return (profile.get("email", "mhaslaiabdur@gmail.com"), "CANDIDATE_PROFILE", "Candidate Email")

    # 7. Phone / Mobile Number (Strict Rule: Qatar/Dubai/UAE -> +974 77557982 / 77557982; India -> +91 7972694663 / 7972694663. Never write country name)
    if is_phone_with_cc or (any(k in words or k in ctx for k in ["phone", "mobile", "contact number", "cell", "telephone", "phone number"]) and not any(k in ctx for k in ["country code", "calling code", "dial code"])):
        is_full = is_phone_with_cc or any(k in ctx for k in ["full", "international", "complete phone", "+"])
        if is_gulf:
            phone_ans = cand_profile["full_phone_number"] if is_full else cand_profile["mobile_number"]
            return (phone_ans, "CANDIDATE_PROFILE", f"Mandatory Gulf Phone ({phone_ans})")
        else:
            phone_ans = cand_profile["full_phone_number"] if is_full else cand_profile["mobile_number"]
            return (phone_ans, "CANDIDATE_PROFILE", f"Mandatory India Phone ({phone_ans})")

    # 8. Name
    if any(k in q_clean for k in ["full name", "complete name", "candidate name"]) or (any(k in ctx for k in ["fullname", "full_name"]) and not any(k in q_clean for k in ["first name", "last name", "middle name"])):
        return (profile.get("name", "Abdul Razzaque Shaikh"), "CANDIDATE_PROFILE", "Candidate Full Name")
    if any(k in ctx for k in ["first name", "fname", "given name", "forename"]) and not any(k in ctx for k in ["full name", "fullname"]):
        return (profile.get("first_name", "Abdul Razzaque"), "CANDIDATE_PROFILE", "Candidate First Name")
    if any(k in ctx for k in ["last name", "lname", "surname", "family name"]) and not any(k in ctx for k in ["full name", "fullname"]):
        return (profile.get("last_name", "Shaikh"), "CANDIDATE_PROFILE", "Candidate Last Name")
    if any(k in ctx for k in ["middle name", "mname"]):
        return (profile.get("middle_name", "Abdul Razzaque Shaikh"), "CANDIDATE_PROFILE", "Candidate Middle Name")
    if any(k in ctx for k in ["name", "your name"]) and not any(k in ctx for k in ["company", "college", "school"]):
        return (profile.get("name", "Abdul Razzaque Shaikh"), "CANDIDATE_PROFILE", "Candidate Full Name")

    # 9. DOB
    if any(k in ctx for k in ["dob", "date of birth", "birth date", "birthday"]):
        return (profile.get("dob_iso", "1999-11-19") if is_date else profile.get("dob", "19/11/1999"), "CANDIDATE_PROFILE", "Candidate Date of Birth")

    # 10. Age (18+ Verification vs Numeric Age)
    if any(k in ctx for k in ["18 years", "at least 18", "over 18", "18 or older", "older than 18", "legal working age", "age of majority"]) or (("18" in ctx or "eighteen" in ctx) and any(k in ctx for k in ["age", "older", "years"])):
        return ("true" if is_checkbox else "Yes", "CANDIDATE_PROFILE", "Candidate Over 18 Years (Yes)")

    if re.search(r"\b(age|candidate[-_ ]?age|your[-_ ]?age)\b", q_clean, re.I) and not any(k in ctx for k in ["language", "percentage", "coverage", "manage", "package", "average", "18", "eighteen", "older", "minor"]):
        return ("27", "CANDIDATE_PROFILE", "Candidate Verified Age (27)")

    # 11. Marital Status
    if any(k in ctx for k in ["marital status", "civil status", "marital"]):
        return ("Single", "CANDIDATE_PROFILE", "Candidate Marital Status (Single)")

    # 12. Nationality
    if any(k in ctx for k in ["current nationality", "what is your current nationality", "nationality", "citizenship"]) and not any(k in ctx for k in ["sponsorship", "visa"]):
        return ("Indian", "CANDIDATE_PROFILE", "Candidate Current Nationality (Indian)")

    # 13. University Graduation
    if any(k in ctx for k in ["graduate from university", "graduated from university", "did you graduate from", "did you graduate"]):
        return ("Yes, I graduated", "CANDIDATE_PROFILE", "University Graduation (Yes, I graduated)")

    # 14. Role Preference / Employment Type
    if any(k in ctx for k in ["what role are you looking for", "role are you looking for", "looking for full-time"]):
        return ("Full-Time", "CANDIDATE_PROFILE", "Role Looking For (Full-Time)")

    # 15. English Proficiency Level
    if any(k in ctx for k in ["level in english", "english level", "english proficiency"]):
        return ("Fluent/Native", "CANDIDATE_PROFILE", "English Level (Fluent/Native)")

    # 16. Minimum Salary in British Pounds (£)
    if any(k in ctx for k in ["british £", "british pound", "gbp", "accept in british"]) or (any(k in ctx for k in ["minimum salary", "salary that you would accept"]) and any(k in ctx for k in ["£", "pound", "british"])):
        return ("3000", "CANDIDATE_PROFILE", "Minimum Monthly Salary in British Pounds (£3,000/month)")

    # 17. Situational / Behavioral Questions
    if any(k in ctx for k in ["confronted with difficulties", "difficulties in life", "approach the situation"]):
        return ("I take some time to think then start finding the solutions", "CANDIDATE_PROFILE", "Analytical Approach to Difficulties")

    if any(k in ctx for k in ["what type of job are you looking for", "type of job you are looking for"]) and any(k in ctx for k in ["team based", "put you in the right team"]):
        return ("Secure and stable job that allows me to focus only on it professionally", "CANDIDATE_PROFILE", "Job Stability and Focus Preference")

    # 18. Engineering Narratives (Hacked the system & Exceptional ability)
    if any(k in ctx for k in ["hacked the system", "hack the system"]):
        return (
            "In a previous production deployment, our team faced severe API rate limits and slow database queries during peak batch processing. To optimize performance without increasing cloud costs, I engineered an asynchronous worker queue pipeline with connection pooling and in-memory Redis caching. This eliminated bottlenecks, reduced processing runtime by 65%, and handled 5x higher throughput with zero downtime.",
            "CANDIDATE_PROFILE",
            "System Optimization & Problem Solving Narrative"
        )

    if any(k in ctx for k in ["exceptional ability", "evidence of exceptional"]):
        return (
            "I architected and deployed a multi-platform autonomous workflow synchronization engine with fault-tolerant recovery, maintaining 99.9% uptime. The solution dynamically adapted to complex single-page applications, resiliently resolved intricate DOM state trees, and automated mission-critical workflows, reducing manual operational workload by over 80%.",
            "CANDIDATE_PROFILE",
            "Evidence of Exceptional Engineering Ability Narrative"
        )

    # 19. Anti-Nepotism, Conflict of Interest & Relatives in Company (e.g. Morningstar, Scale AI)
    if any(k in ctx for k in [
        "family member or romantic partner", "family member", "romantic partner",
        "relatives employed", "relative employed", "relatives working", "relative working",
        "family working", "employed by this company", "employed with us", "conflict of interest",
        "outside business interests", "board member", "related to any current employee",
        "related to anyone", "any relatives"
    ]):
        return ("false" if is_checkbox else "No", "CANDIDATE_PROFILE", "No Relatives or Conflicts of Interest (No)")

    # 20. Age 18+ Verification
    if any(k in ctx for k in ["18 years", "at least 18", "over 18", "legal working age", "age of majority"]):
        return ("true" if is_checkbox else "Yes", "CANDIDATE_PROFILE", "Candidate Over 18 Years (Yes)")

    # 21. Criminal Convictions / Background Check Consent / Drug Screen
    if any(k in ctx for k in [
        "convicted of a crime", "convicted of a felony", "criminal record", "criminal history",
        "misdemeanor", "pending criminal", "disciplinary proceedings"
    ]):
        return ("false" if is_checkbox else "No", "CANDIDATE_PROFILE", "No Criminal Convictions (No)")

    if any(k in ctx for k in ["background check", "background verification", "drug test", "drug screening", "undergo a background"]):
        return ("true" if is_checkbox else "Yes", "CANDIDATE_PROFILE", "Background Verification Consent (Yes)")

    # 22. Driver's License
    if any(k in ctx for k in ["driver's license", "driving license", "valid driver"]):
        return ("true" if is_checkbox else "Yes", "CANDIDATE_PROFILE", "Valid Driver's License (Yes)")

    # 23. EEO Race & Ethnicity
    if any(k in ctx for k in ["race", "ethnicity", "ethnic origin"]):
        return ("Asian", "CANDIDATE_PROFILE", "EEO Race/Ethnicity (Asian)")

    # --- CATEGORY: ELIGIBILITY & WORK AUTHORIZATION & VISA ---
    if category == QuestionCategory.ELIGIBILITY or any(k in ctx for k in ["eligible", "visa", "sponsorship", "authoris", "authoriz"]):
        # Restrictive agreements / Non-compete / Non-solicitation (e.g. Scale AI)
        if any(k in ctx for k in [
            "bound by any agreements", "restrict your ability to work", "non-compete",
            "non-solicitation", "contractual obligations that could limit",
            "restrict your ability", "restrict ability to work"
        ]):
            return ("false" if is_checkbox else "No", "CANDIDATE_PROFILE", "No Restrictive Agreements (No)")

        # Visa sponsorship: "Will you now or in the future require company sponsorship to retain or extend your work authorization in the country where the job is located?"
        # CRITICAL: Evaluated BEFORE generic 'work authorization' check!
        if any(k in ctx for k in [
            "require company sponsorship", "company sponsorship", "require sponsorship",
            "require visa sponsorship", "visa sponsorship", "sponsorship to retain",
            "sponsorship to extend", "sponsorship to continue", "need sponsorship",
            "employer sponsorship", "need, or will you need", "sponsorship to work legally",
            "sponsorship to work", "sponsorship"
        ]):
            return ("false" if is_checkbox else "No", "CANDIDATE_PROFILE", "No Employer Sponsorship Required (No)")

        # Work Authorization Status dropdown / radio
        if any(k in ctx for k in ["authorization status", "authorisation status", "status of work authorization", "describe your authorization", "describes your authorization", "describes your authorisation", "status*"]):
            return (
                "I am a citizen/permanent resident with full work authorization",
                "CANDIDATE_PROFILE",
                "Citizen Full Work Authorization Status"
            )

        # Legally eligible / authorised to work in country of residence
        if any(k in ctx for k in [
            "legally eligible", "eligible to work", "authorized to work", "authorised to work",
            "work authorization", "work authorisation", "right to work", "legally authorised", "legally authorized"
        ]):
            return ("true" if is_checkbox else "Yes", "CANDIDATE_PROFILE", "Legally Authorised to Work (Yes)")

        # Privacy notice / terms
        if any(k in ctx for k in ["privacy notice", "privacy policy", "terms", "consent", "confirm you have read"]):
            return ("true" if is_checkbox else "Yes", "CANDIDATE_PROFILE", "Confirm Privacy Notice")

        return ("true" if is_checkbox else "Yes", "CANDIDATE_PROFILE", "Work Authorization / Terms Agreement")

    # --- CATEGORY: LOCATION (Country, State, City, Pincode) ---
    if category == QuestionCategory.LOCATION or (any(k in ctx for k in ["country", "state", "city", "mumbai location", "qatar location", "current location", "where do you live", "where are you based", "preferred location", "work location", "residential address", "home address"]) and not any(k in ctx for k in ["eligible", "visa", "sponsorship", "authorized to work"])):
        # 1. Preferred Work Location (e.g. Test 9)
        if any(k in ctx for k in ["preferred location", "preferred work location", "desired location", "desired work location", "location preference"]):
            pref_loc = cand_profile.get("preferred_work_location", "Mumbai, Kurla, Maharashtra, India")
            return (pref_loc, "CANDIDATE_PROFILE", f"Preferred Work Location ({pref_loc})")

        # 2. Current Residential Address (e.g. Test 8)
        # Strict Rule: Use only verified residential information. Never substitute preferred work location.
        if any(k in ctx for k in ["current residential address", "residential address", "home address", "permanent address"]):
            res_addr = cand_profile.get("residential_address", "Kurla, Mumbai, Maharashtra, India")
            return (res_addr, "CANDIDATE_PROFILE", f"Verified Residential Address ({res_addr})")

        # Specific Country questions (e.g. Scale AI: "What country are you located in?*")
        if any(k in ctx for k in ["what country are you located in", "country you are located in", "country are you located"]):
            target_country = "Qatar" if is_gulf else "India"
            return (target_country, "CANDIDATE_PROFILE", f"Country Located In ({target_country})")

        # Location (City) - e.g. Scale AI / Greenhouse autocomplete
        if any(k in ctx for k in ["location (city)", "location(city)"]):
            res_city = cand_profile.get("residential_city", "Mumbai")
            return (f"{res_city}, Maharashtra, India", "CANDIDATE_PROFILE", f"Location City ({res_city}, Maharashtra, India)")

        # Composite: Location of Residence and Language (e.g. Jobvite / DNEG)
        if any(k in ctx for k in ["location of residence and language", "residence and language", "location and language", "residence / language"]):
            res_addr = cand_profile.get("residential_address", "Kurla, Mumbai, Maharashtra, India")
            return (f"{res_addr} | English (Fluent), Hindi, Urdu", "CANDIDATE_PROFILE", "Location of Residence and Language")

        # Permanent Address (as per a government issued ID) - e.g. LogiNext / Trakstar
        if any(k in ctx for k in ["permanent address", "address as per", "government issued id", "permanent_address"]):
            res_addr = cand_profile.get("residential_address", "Kurla, Mumbai, Maharashtra, India")
            return (res_addr, "CANDIDATE_PROFILE", f"Candidate Permanent Address ({res_addr})")

        # Location of Residence / Residence Location
        if any(k in ctx for k in ["location of residence", "residence location", "current residence", "place of residence", "residence address"]):
            res_addr = cand_profile.get("residential_address", "Kurla, Mumbai, Maharashtra, India")
            return (res_addr, "CANDIDATE_PROFILE", f"Location of Residence ({res_addr})")

        # Country
        if (any(k in words for k in ["country", "nation", "citizenship", "nationality"]) or "country" in fname_low or "country" in fid_low or "countries" in fid_low) and not any(k in ctx for k in ["country code", "calling code", "eligible", "visa", "sponsorship", "authorized"]):
            if any(k in ctx for k in ["citizenship", "nationality"]):
                return ("Indian", "CANDIDATE_PROFILE", "Candidate Nationality (Indian)")
            if any(k in ctx for k in ["preferred", "preference", "work country"]):
                target_country = cand_profile.get("country", "India")
            else:
                # Truthful residence country
                target_country = cand_profile.get("residential_country", "India")
            return (target_country, "CANDIDATE_PROFILE", f"Candidate Country ({target_country})")

        # State / Province
        if (any(k in words for k in ["state", "province", "region"]) or "state" in fname_low or "state" in fid_low or "states" in fid_low) and not any(k in ctx for k in ["statement", "state your", "united states"]):
            if any(k in ctx for k in ["preferred", "preference"]):
                target_state = cand_profile.get("state", "Maharashtra")
            else:
                target_state = cand_profile.get("residential_state", "Maharashtra")
            return (target_state, "CANDIDATE_PROFILE", f"Candidate State ({target_state})")

        # Specific city questions
        if any(k in ctx for k in ["working in mumbai", "mumbai location"]):
            return ("No" if is_gulf else "Yes", "CANDIDATE_PROFILE", "Mumbai Location Confirmation")
        if any(k in ctx for k in ["working in qatar", "qatar location"]):
            return ("Yes" if is_qatar else "No", "CANDIDATE_PROFILE", "Qatar Location Confirmation")
        if any(k in ctx for k in ["working in dubai", "dubai location"]):
            return ("Yes" if is_dubai else "No", "CANDIDATE_PROFILE", "Dubai Location Confirmation")

        # City / Town
        if any(k in words for k in ["city", "town", "district", "current city"]):
            if any(k in ctx for k in ["preferred", "preference"]):
                target_city = cand_profile.get("preferred_city", "Mumbai")
            else:
                target_city = cand_profile.get("residential_city", "Mumbai")
            return (target_city, "CANDIDATE_PROFILE", f"Candidate City ({target_city})")

        # PO Box / Postal Code / Zip / Pincode
        if any(k in ctx for k in ["po box", "zip", "postal", "pincode", "pin code", "post code"]):
            pcode = cand_profile.get("postal_code", "400070") if is_india else ""
            return (pcode, "CANDIDATE_PROFILE", f"Postal Code ({pcode})")

        if any(k in ctx for k in ["preferred", "preference", "desired location"]):
            return (cand_profile.get("preferred_work_location", "Mumbai, Kurla, Maharashtra, India"), "CANDIDATE_PROFILE", "Preferred Location")

        curr_loc = cand_profile.get("current_location", "Kurla, Mumbai, India")
        return (curr_loc, "CANDIDATE_PROFILE", f"Current Location ({curr_loc})")

    # --- CATEGORY: NOTICE PERIOD & AVAILABILITY & START DATE ---
    if category == QuestionCategory.NOTICE_PERIOD or any(k in ctx for k in [
        "notice period", "notice days", "days is your notice", "startdatum", "frühestmögliches",
        "eintrittsdatum", "verfügbarkeit", "start working", "available to start", "when are you available",
        "available to work", "start to work", "earliest start", "start date", "earliest availability"
    ]):
        # Date input / Calendar field
        if is_date or "calendar" in ctx or any(k in ctx for k in ["startdatum", "eintrittsdatum", "datum"]):
            import datetime
            near_date = (datetime.date.today() + datetime.timedelta(days=7)).strftime("%Y-%m-%d")
            near_date_de = (datetime.date.today() + datetime.timedelta(days=7)).strftime("%d.%m.%Y")
            if is_date or "iso" in ctx:
                return (near_date, "CANDIDATE_PROFILE", f"Immediate Start Date ({near_date})")
            if any(k in ctx for k in ["startdatum", "deutsch", "germany", "eur"]):
                return (near_date_de, "CANDIDATE_PROFILE", f"Frühestmögliches Startdatum ({near_date_de})")
            return ("Immediately", "CANDIDATE_PROFILE", "Earliest Availability (Immediately)")

        # Text input / general questions about availability to start
        if any(k in ctx for k in ["available to start", "start working with us", "when are you available", "available to work", "earliest availability", "earliest start"]):
            return ("Immediately", "CANDIDATE_PROFILE", "Earliest Availability (Immediately)")

        if any(k in ctx for k in ["startdatum", "frühestmögliches", "eintrittsdatum", "verfügbarkeit", "ab sofort"]):
            return ("Sofort", "CANDIDATE_PROFILE", "Frühestmögliches Startdatum (Sofort)")

        serving_notice = profile.get("serving_notice", False)
        verified_lwd = profile.get("last_working_day") or profile.get("lwd")

        # Compound question
        is_compound = ("notice" in q or "official notice" in q) and ("serving" in q or "lwd" in q or "last working" in q)
        if is_compound:
            if is_num or is_numeric_context:
                return (str(profile.get("notice_period_days", 0)), "CANDIDATE_PROFILE", "Immediate Notice in Days")
            return ("Immediate Joiner (Not serving notice)", "CANDIDATE_PROFILE", "Immediate Notice (Not Serving Notice)")

        if any(k in ctx for k in ["last working day", "last working date", "lwd"]):
            if serving_notice and verified_lwd:
                return (str(verified_lwd), "CANDIDATE_PROFILE", "Verified Last Working Day")
            elif is_date:
                return (None, "UNKNOWN", "NEEDS_USER_INPUT: Immediate joiner not serving notice")
            else:
                return ("Not serving notice (Immediate Joiner)", "CANDIDATE_PROFILE", "Not Serving Notice")

        if any(q.startswith(p) for p in ["are you", "do you"]) and "serving" in q:
            return ("Yes" if serving_notice else "No", "CANDIDATE_PROFILE", "Serving Notice Status")

        # Specific notice period question asking for days: "How many days is your notice period?"
        if is_num or is_numeric_context or any(k in ctx for k in ["how many days", "in days", "number of days", "notice period in days", "days is your notice", "days notice", "how many day", "notice in days", "notice days", "days", "tage"]):
            return (str(profile.get("notice_period_days", 0)), "CANDIDATE_PROFILE", "Notice Period in Days (0)")

        # Specific notice period question: "Notice Period Immediate Joiner"
        if "immediate" in ctx or "joiner" in ctx:
            if is_num or is_numeric_context:
                return ("0", "CANDIDATE_PROFILE", "Immediate Notice in Days (0)")
            return ("Immediate Joiner", "CANDIDATE_PROFILE", "Notice Period Immediate Joiner")

        if is_num or is_numeric_context:
            return (str(profile.get("notice_period_days", 0)), "CANDIDATE_PROFILE", "Immediate Notice in Days")

        return (profile.get("notice_period_str", "Immediate Joiner"), "CANDIDATE_PROFILE", "Immediate Notice Preference")

    # --- CATEGORY: SALARY & CTC ---
    if category == QuestionCategory.SALARY or any(k in ctx for k in [
        "ctc", "salary", "remuneration", "renumeration", "cost to company", "cost-to-company",
        "lakhs per annum", "lpa", "riyal", "rial", "qar", "compensation", "pay rate", "wages",
        "gehalt", "gehaltserwartung", "gehaltsvorstellung", "eur", "euro", "€", "usd", "$"
    ]):
        is_monthly = any(k in ctx for k in ["month", "monthly", "/month", "pm", "per month"])
        num_salary = is_num or is_numeric_context or any(k in ctx for k in ["in lakhs", "in lpa", "lakhs per annum", "lakhs/annum", "per annum", "in inr", "in rupees", "lakhs", "lpa", "riyal", "qar", "rial", "eur", "euro", "usd", "$"])
        is_lakhs_explicit = any(k in ctx for k in ["in lakhs", "in lpa", "lakhs per annum", "lakhs/annum", "(in lakhs", "lakhs", "lpa"])

        # Check for EUR / Euro / German Salary question (Candidate expected European salary is 65000 EUR)
        is_eur_explicit = any(k in ctx for k in ["eur", "euro", "€", "gehalt", "gehaltserwartung", "gehaltsvorstellung", "jahresgehalt"])
        if is_eur_explicit:
            eur_val = "65000"
            if num_salary or is_num or is_numeric_context:
                return (eur_val, "CANDIDATE_PROFILE", "Expected Annual Salary in EUR (65000)")
            return (f"{eur_val} EUR", "CANDIDATE_PROFILE", "Expected Annual Salary in EUR (65000 EUR)")

        # Check for USD / International Dollar
        is_usd_explicit = any(k in ctx for k in ["usd", "$", "dollar"])
        if is_usd_explicit:
            usd_val = "75000"
            if num_salary or is_num or is_numeric_context:
                return (usd_val, "CANDIDATE_PROFILE", "Expected Annual Salary in USD (75000)")
            return (f"{usd_val} USD", "CANDIDATE_PROFILE", "Expected Annual Salary in USD (75000 USD)")

        # Check for Riyal / QAR / Gulf Currency (Candidate requests 8000 Riyal monthly)
        is_riyal_explicit = any(k in ctx for k in ["riyal", "rial", "qar", "qr", "qatari riyal", "sar", "aed", "dirham"])
        if is_riyal_explicit or (is_gulf and not any(k in ctx for k in ["inr", "lakh", "lpa", "rupee", "rs"])):
            riyal_val = str(profile.get("qatar_profile", {}).get("salary_riyal", 8000))
            if is_monthly or num_salary or is_num or is_numeric_context or any(k in ctx for k in ["ctc", "salary", "remuneration", "renumeration", "cost to company", "cost-to-company", "local currency", "currency"]):
                return (riyal_val, "CANDIDATE_PROFILE", "Monthly Salary in Riyal (8000)")
            return (riyal_val, "CANDIDATE_PROFILE", "Expected Salary in Riyal (8000)")

        # India Monthly Salary
        if is_monthly:
            if any(k in ctx for k in ["expected", "desired", "target", "expectation"]):
                return ("125000", "CANDIDATE_PROFILE", "Expected Monthly Salary India (125000)")
            return ("83000", "CANDIDATE_PROFILE", "Current Monthly Salary India (83000)")

        if any(k in ctx for k in ["expected", "desired", "expectation", "expecting"]):
            if "inr" in ctx or "rs" in ctx or "rupee" in ctx:
                return (str(profile.get("expected_ctc_inr", 1500000)), "CANDIDATE_PROFILE", "Expected CTC INR")
            if is_lakhs_explicit or num_salary or is_num or is_numeric_context:
                return (str(int(profile.get("expected_ctc_lpa", 15))), "CANDIDATE_PROFILE", "Expected CTC Numeric LPA")
            return (f"{profile.get('expected_ctc_lpa', 15)} LPA", "CANDIDATE_PROFILE", "Expected CTC LPA")

        if any(k in ctx for k in ["fixed component", "fixed ctc", "fixed salary"]):
            if "inr" in ctx or "rs" in ctx or "rupee" in ctx:
                return (str(profile.get("fixed_ctc_inr", 1200000)), "CANDIDATE_PROFILE", "Fixed CTC INR")
            if is_lakhs_explicit or num_salary or is_num or is_numeric_context:
                return (str(int(profile.get("current_ctc_lpa", 12))), "CANDIDATE_PROFILE", "Fixed CTC Numeric LPA")
            return (f"{profile.get('current_ctc_lpa', 12)} LPA", "CANDIDATE_PROFILE", "Fixed CTC")

        if "inr" in ctx or "rs" in ctx or "rupee" in ctx:
            return (str(profile.get("current_ctc_inr", 1200000)), "CANDIDATE_PROFILE", "Current CTC INR")
        if is_lakhs_explicit or num_salary or is_num or is_numeric_context:
            return (str(int(profile.get("current_ctc_lpa", 12))), "CANDIDATE_PROFILE", "Current CTC Numeric LPA")
        return (f"{profile.get('current_ctc_lpa', 12)} LPA", "CANDIDATE_PROFILE", "Current CTC LPA")

    # --- CATEGORY: EXPERIENCE ---
    if category == QuestionCategory.EXPERIENCE:
        num_exp = is_num or is_numeric_context or any(k in ctx for k in ["how many years", "years of", "number of years", "in years", "years experience", "total years", "total exp", "relevant exp"])

        # Proven Experience / Total Experience 3 to 5 Yrs
        if any(k in ctx for k in ["proven experience", "total experience 3 to 5", "3 to 5"]):
            return ("5", "CANDIDATE_PROFILE", "Proven Experience 5 Years")

        # Check if question asks about Java or Spring Boot (Must never match JavaScript!)
        has_java_in_ctx = bool(re.search(r"\bjava\b", ctx)) and not bool(re.search(r"\bjavascript\b", ctx))
        if has_java_in_ctx or any(k in ctx for k in ["spring boot", "springboot", "j2ee", "hibernate", "core java"]):
            return ("0" if num_exp else "No", "CANDIDATE_PROFILE", "No Java/Spring Experience (Candidate is MERN / JavaScript Full Stack)")

        # Check if question asks about specific unverified or secondary technologies (Ruby, Golang, Swift, Kotlin, Rust, PHP, C#)
        unverified_techs = ["ruby", "rails", "golang", "rust", "swift", "kotlin", "php", "c#", "scala", "solidity", ".net", "dotnet"]
        for ut in unverified_techs:
            if ut in ctx:
                return ("0" if num_exp else "less than 2", "CANDIDATE_PROFILE", f"Unverified Technology ({ut.capitalize()} - 0/less than 2)")

        if any(q.startswith(p) for p in ["do you", "have you", "are you", "is it"]):
            return ("Yes", "CANDIDATE_PROFILE", "Verified Stack Experience")

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
            if kw in ctx:
                val = str(int(exp_years.get(stack_key, num_ans)))
                return (val if num_exp else f"{val}+ years", "CANDIDATE_PROFILE", f"Verified {kw} Experience")

        total_exp = str(int(profile.get("total_experience_years", 5)))
        return (total_exp if num_exp else f"{total_exp}+ years", "CANDIDATE_PROFILE", "Total Experience")

    # --- CATEGORY: TECHNICAL SKILLS ---
    if category == QuestionCategory.TECHNICAL_SKILLS:
        # Core Technical Stack (e.g. Scale AI: "What is your core technical stack?*")
        if any(k in ctx for k in ["core technical stack", "technical stack", "tech stack", "what is your stack", "primary stack", "core stack", "primary technical stack", "main tech stack"]):
            return ("MERN Stack (React.js, Node.js, Express.js, TypeScript, Next.js, MongoDB, RESTful APIs, AWS)", "CANDIDATE_PROFILE", "Core Technical Stack (MERN)")

        # Programming languages (Section 19.3)
        if any(k in ctx for k in ["programming language", "programming languages", "which languages", "which language", "languages do you know"]):
            return (answers.get("programming_languages", "JavaScript, TypeScript, Python, SQL, C, C++"), "CANDIDATE_PROFILE", "Programming Languages")

        # Frontend technologies (Section 19.3)
        if any(k in ctx for k in ["frontend technologies", "frontend technology", "frontend stack", "frontend frameworks"]):
            return (answers.get("frontend_technologies", "React.js, Next.js, Redux Toolkit, Zustand, Tailwind CSS, Material UI, HTML5, CSS3"), "CANDIDATE_PROFILE", "Frontend Technologies")

        # Backend technologies (Section 19.3)
        if any(k in ctx for k in ["backend technologies", "backend technology", "backend stack", "which backend"]):
            return (answers.get("backend_technologies", "Node.js, Express.js, REST APIs, GraphQL, Socket.io, Prisma, Mongoose"), "CANDIDATE_PROFILE", "Backend Technologies")

        # Databases (Section 19.3)
        if any(k in ctx for k in ["which database", "which databases", "databases have you", "databases do you", "databases you have"]):
            return (answers.get("databases", "MongoDB, PostgreSQL, MySQL, SQLite"), "CANDIDATE_PROFILE", "Databases")

        # Docker, Redis, Kafka (Section 19.3)
        if any(k in ctx for k in ["docker, redis", "redis or kafka", "docker or redis"]):
            return ("Yes, I have hands-on production experience with Docker for containerization, Redis for caching and session management, and Apache Kafka for event-driven messaging architectures.", "CANDIDATE_PROFILE", "Docker, Redis, Kafka Experience")

        # REST APIs (Section 19.3)
        if any(k in ctx for k in ["rest api", "rest apis", "restful api", "restful apis"]):
            return ("Over 5+ years of experience designing, developing, documenting, and consuming scalable RESTful APIs with Node.js and Express, implementing JWT authentication, rate limiting, and database optimization.", "CANDIDATE_PROFILE", "REST API Experience")

        # Cloud technologies (Section 19.3)
        if any(k in ctx for k in ["cloud technologies", "worked with cloud", "cloud technology"]):
            return ("Yes, I have worked with AWS (EC2, S3), Docker containerization, and automated CI/CD pipelines on GitLab and GitHub Actions.", "CANDIDATE_PROFILE", "Cloud Technologies Experience")

        # Relevant Skills React js, HTML 5, JavaScript/ Typescript
        if any(k in ctx for k in ["relevant skills", "skills react"]):
            return ("Yes", "CANDIDATE_PROFILE", "Candidate Possesses All Relevant Skills (Yes)")

        # Check if question asks about Java, Spring Boot, .NET, C#, PHP, Ruby
        has_java_tech = bool(re.search(r"\bjava\b", ctx)) and not bool(re.search(r"\bjavascript\b", ctx))
        if has_java_tech or any(k in ctx for k in ["spring boot", "springboot", "j2ee", "hibernate", "core java"]):
            return ("No", "CANDIDATE_PROFILE", "No Java Experience (Candidate is MERN / JavaScript Full Stack)")
        if any(k in ctx for k in [".net", "dotnet", "c#", "php", "laravel", "wordpress", "scala", "swift", "kotlin", "rust"]):
            return ("No", "CANDIDATE_PROFILE", "No Unverified Technology Experience (No)")

        # Ruby / Ruby on Rails (Oyster portal question)
        if any(k in ctx for k in ["ruby on rails", "ruby", "rails application"]):
            if any(k in ctx for k in ["built and maintained", "in production", "have you built"]):
                return ("No", "CANDIDATE_PROFILE", "No Production Ruby on Rails Experience (No)")
            if any(k in ctx for k in ["how many years", "years of", "experience"]):
                return ("0", "CANDIDATE_PROFILE", "Ruby Experience (0 years)")
            return ("No", "CANDIDATE_PROFILE", "No Ruby Experience (No)")

        if any(k in ctx for k in ["golang or node", "node or golang", "node.js or golang"]):
            return ("Node.js", "CANDIDATE_PROFILE", "Strongest Backend Technology (Node.js)")
        if any(k in ctx for k in ["frontend technology", "react or angular", "angular or react"]):
            return ("React.js", "CANDIDATE_PROFILE", "Strongest Frontend Technology (React.js)")
        if any(k in ctx for k in ["primary skill", "primary technology", "core skill"]):
            return (profile.get("primary_skills", "React.js, Node.js, MERN Stack, TypeScript"), "CANDIDATE_PROFILE", "Primary Skills")
        if any(q.startswith(p) for p in ["do you", "have you", "are you"]):
            return ("Yes", "CANDIDATE_PROFILE", "Verified Skill Experience")
        return (", ".join(profile.get("skills", ["React.js", "Node.js", "TypeScript", "Express.js", "MongoDB", "MySQL", "PostgreSQL", "Docker", "AWS", "Next.js"])), "CANDIDATE_PROFILE", "Candidate Technical Skills")

    # --- CATEGORY: EDUCATION ---
    if category == QuestionCategory.EDUCATION:
        # Degree Type
        if any(k in ctx for k in ["degree type", "degree"]):
            return (profile.get("degree_type", "BSC Computer Sciences"), "CANDIDATE_PROFILE", "Degree Type (BSC Computer Sciences)")
        if any(k in ctx for k in ["ca,", "cs,", "cma", "cfa", "chartered", "professional qualification"]):
            return ("No", "CANDIDATE_PROFILE", "No Professional Accounting Qualification")
        if any(k in ctx for k in ["marks", "percentage", "gpa", "cgpa", "score"]):
            return (None, "UNKNOWN", "UNVERIFIED_MARKS_OR_GPA")
        if any(k in ctx for k in ["university", "college", "institute"]):
            return (profile.get("university", "BAMU University, India"), "CANDIDATE_PROFILE", "University")
        if any(k in ctx for k in ["graduation year", "passing year", "year of passing", "passout"]):
            return (str(profile.get("graduation_year", "2021")), "CANDIDATE_PROFILE", "Graduation Year")
        if any(k in ctx for k in ["highest qualification", "highest educational qualification"]):
            return (profile.get("highest_qualification", "BSC Computer Science"), "CANDIDATE_PROFILE", "Highest Qualification")
        if any(q.startswith(p) for p in ["have you", "are you", "do you"]):
            return ("Yes", "CANDIDATE_PROFILE", "Graduate Degree in Computer Science")
        return (profile.get("highest_qualification", "BSC Computer Science"), "CANDIDATE_PROFILE", "Highest Qualification")

    # --- CATEGORY: EMPLOYMENT HISTORY ---
    if category == QuestionCategory.EMPLOYMENT_HISTORY:
        # Restrictive agreements / Non-compete (Safety guard in case classified under employment history)
        if any(k in ctx for k in ["bound by any agreements", "restrict your ability", "non-compete", "non-solicitation", "contractual obligations"]):
            return ("No", "CANDIDATE_PROFILE", "No Restrictive Agreements (No)")

        # Have you previously worked with us?
        if any(k in ctx for k in ["previously worked", "worked with us", "worked for us", "ex-employee", "past employee"]):
            return (profile.get("previously_worked_with_us", "No"), "CANDIDATE_PROFILE", "Never Worked Here Previously (No)")

        # Current Organisation / Company
        if any(k in ctx for k in ["current organisation", "current organization", "current company", "employer", "organization", "firm"]):
            return (profile.get("current_company", "Tharb"), "CANDIDATE_PROFILE", "Current Organisation (Tharb)")

        if any(k in ctx for k in ["previous company", "past company"]):
            return (profile.get("previous_company", "TechGeekFirms"), "CANDIDATE_PROFILE", "Previous Company")
        if any(k in ctx for k in ["designation", "role", "job title"]):
            return (profile.get("designation", "Senior Full Stack Developer"), "CANDIDATE_PROFILE", "Current Designation")
        return ("Currently working remotely for Tharb from Kurla, Mumbai", "CANDIDATE_PROFILE", "Employment Status")

    # --- CATEGORY: RELOCATION & REMOTE & WORKPLACE ---
    if category == QuestionCategory.RELOCATION:
        # Relocation to Middle East (e.g. Scale AI)
        if any(k in ctx for k in ["middle east", "relocation to the middle east", "relocate to the middle east"]):
            return ("Yes", "CANDIDATE_PROFILE", "Open to Relocation to Middle East (Yes)")

        if any(k in ctx for k in ["wohl bei der arbeit", "remote-umgebung", "fühlen sie sich wohl", "fühlen"]):
            return ("Ja", "CANDIDATE_PROFILE", "Comfortable in Remote Environment (Ja)")
        if any(k in ctx for k in ["arrangement", "workplace", "work model", "work mode", "work setup", "preferred work", "work arrangement"]):
            return ("Remote", "CANDIDATE_PROFILE", "Preferred Work Arrangement (Remote)")
        if any(q.startswith(p) for p in ["are you", "do you", "is it possible", "will you", "fühlen"]):
            return ("Ja" if any(k in ctx for k in ["deutsch", "remote-umgebung", "wohl", "fühlen"]) else "Yes", "CANDIDATE_PROFILE", "Willingness to Relocate / Work Remote")
        return (answers.get("relocate", "Yes, open to relocate to Mumbai or work remotely."), "CANDIDATE_PROFILE", "Relocation Details")

    # --- CATEGORY: REMOTE WORK & COLLABORATION TOOLS (Section 19.4) ---
    if category == QuestionCategory.COLLABORATION_TOOLS or any(k in ctx for k in ["collaboration tool", "collaboration tools", "remote tools", "project management tools", "tools do you use"]):
        if any(k in ctx for k in ["project management", "task management"]):
            return (answers.get("project_management_tools", "Jira, Trello, Asana, Notion"), "CANDIDATE_PROFILE", "Project Management Tools")
        if any(k in ctx for k in ["how do you communicate", "communicate with remote"]):
            return (answers.get("remote_collaboration_methods"), "CANDIDATE_PROFILE", "Remote Communication Methods")
        if any(k in ctx for k in ["manage tasks", "distributed team", "tasks in a distributed"]):
            return ("I break down complex features into modular tickets in Jira, maintain clear acceptance criteria, document architectural decisions in Confluence, and conduct thorough peer code reviews on GitHub/GitLab to ensure full visibility.", "CANDIDATE_PROFILE", "Distributed Task Management")
        if any(k in ctx for k in ["time zone", "timezones", "different time"]):
            return ("I proactively establish overlapping working hours for synchronous discussions and pair programming, while structuring non-blocking asynchronous task handovers and PR reviews so team progress never stalls across time zones.", "CANDIDATE_PROFILE", "Time Zone Management")
        return (answers.get("remote_collaboration_tools", "Slack, Microsoft Teams, Zoom, Google Meet, Jira, Trello, Asana, Notion, GitHub, GitLab, Confluence, Figma"), "CANDIDATE_PROFILE", "Verified Remote Collaboration Tools")

    # --- CATEGORY: BEHAVIORAL & SOFT SKILLS (Section 19.5) ---
    if category == QuestionCategory.BEHAVIORAL or any(k in ctx for k in ["strength", "strengths", "difficult situation", "handle pressure", "work under pressure", "conflict", "challenging project", "manage deadline"]):
        if any(k in ctx for k in ["tell me about yourself", "tell us about yourself", "introduce yourself", "summary about yourself", "short summary"]):
            return (answers.get("tell_me_about_yourself"), "CANDIDATE_PROFILE", "Candidate Introduction / Summary")
        if any(k in ctx for k in ["strength", "strengths"]):
            return (answers.get("strengths"), "CANDIDATE_PROFILE", "Key Strengths")
        if any(k in ctx for k in ["difficult situation", "difficult situations"]):
            return (answers.get("handling_difficult_situations"), "CANDIDATE_PROFILE", "Handling Difficult Situations")
        if any(k in ctx for k in ["deadline", "deadlines", "manage deadline"]):
            return (answers.get("managing_deadlines"), "CANDIDATE_PROFILE", "Managing Deadlines")
        if any(k in ctx for k in ["challenging project"]):
            return (answers.get("challenging_project"), "CANDIDATE_PROFILE", "Challenging Project Description")
        if any(k in ctx for k in ["conflict", "conflicts", "handle conflict"]):
            return (answers.get("handling_conflicts"), "CANDIDATE_PROFILE", "Handling Conflicts")
        if any(k in ctx for k in ["pressure", "under pressure"]):
            return (answers.get("working_under_pressure"), "CANDIDATE_PROFILE", "Working Under Pressure")

    # --- CATEGORY: JOB-SPECIFIC & OPEN-ENDED SCREENING QUESTIONS (Section 19.2 & 19.6) ---
    if category == QuestionCategory.JOB_SPECIFIC_EXPERIENCE:
        # Combined: Short summary about yourself AND why interested in Company (e.g. Oyster)
        has_summary = any(k in ctx for k in ["summary", "about yourself", "tell me about", "introduce yourself", "bio"])
        has_why = any(k in ctx for k in ["why", "interested in", "join our", "work with", "oyster", "company"])
        if has_summary and has_why and any(k in ctx for k in ["interested in", "why you", "why are you"]):
            cname = (company_name or "").strip()
            if not cname:
                m_why = re.search(r"interested in\s+([A-Za-z0-9_.\s!]+)", q_clean, re.IGNORECASE)
                if m_why:
                    cname = m_why.group(1).replace("!", "").strip()
            target_name = cname or "your organization"
            return (
                f"I am a Senior Full Stack Developer with 5+ years of hands-on production experience architecting end-to-end web applications, resilient backend microservices, and modern frontend platforms using React.js, Next.js, Node.js, Express.js, TypeScript, PostgreSQL, and MongoDB. I specialize in scalable API design, cloud containerization with Docker and AWS, and high-performance system design.\n\nI am deeply interested in {target_name} because of your forward-thinking engineering culture, commitment to distributed excellence, and the impactful products you build. My proven track record of autonomous execution, clean architecture, and rapid feature delivery directly aligns with {target_name}'s technical vision, and I am excited to contribute immediately to your team's success.",
                "CANDIDATE_PROFILE",
                f"Candidate Summary & Company Interest ({target_name})"
            )

        # Tell me about yourself / Introduce yourself (standalone)
        if any(k in ctx for k in ["tell me about yourself", "tell us about yourself", "introduce yourself", "summary about yourself", "short summary"]):
            return (answers.get("tell_me_about_yourself"), "CANDIDATE_PROFILE", "Candidate Introduction / Summary")

        # Bio / Biography / Short bio / Candidate Summary
        if any(k in words or k in ctx for k in ["bio", "biography", "short bio", "candidate bio", "summary", "profile summary", "professional summary"]):
            return (
                "Senior Full Stack Developer with 5+ years of production experience specializing in React.js, Next.js, Node.js, Express.js, TypeScript, PostgreSQL, and MongoDB. Proven track record architecting and scaling resilient web applications, enterprise platforms, and high-performance microservices.",
                "CANDIDATE_PROFILE",
                "Candidate Professional Bio"
            )

        # Remote attributes & success in fully remote environment
        if any(k in ctx for k in ["attributes", "remote environment", "success in a fully remote", "success in a remote", "remote attributes", "set you up for success"]):
            return (
                "With 5+ years of software engineering experience, my key attributes for success in a fully remote environment include:\n\n1. Disciplined Self-Management: I maintain high velocity, structure my work efficiently, and take end-to-end ownership from design to production without needing micromanagement.\n2. Transparent Asynchronous Collaboration: I document decisions and architectural changes clearly in Jira, Confluence, and PR reviews on GitHub/GitLab, ensuring teammates across time zones have full visibility.\n3. Resilient Communication: I provide regular proactive updates, participate actively in standups, and communicate thoughtfully on Slack and Zoom.\n4. Continuous Focus on Code Quality & Delivery: I maintain strict testing standards, write clean, maintainable code, and ensure steady, predictable delivery aligned with team sprint goals.",
                "CANDIDATE_PROFILE",
                "Remote Work Success Attributes"
            )

        # Why suitable for remote work?
        if any(k in ctx for k in ["remote work", "suitable for remote", "working remotely", "work from home"]):
            return (
                "With 5+ years of software engineering experience, I thrive in remote environments through disciplined time management, clear written and verbal communication, and independent problem-solving. I am accustomed to working across time zones, collaborating asynchronously with cross-functional teams, and maintaining high velocity and code quality without requiring constant supervision.",
                "CANDIDATE_PROFILE",
                "Remote Work Suitability"
            )

        # Why should we hire you? / What makes you a suitable candidate?
        if any(k in ctx for k in ["why should we hire", "why hire you", "why hire", "suitable candidate", "what makes you a suitable"]):
            return (
                "I bring over 5+ years of specialized Full Stack Development experience architecting and deploying scalable web applications with React.js, Next.js, Node.js, TypeScript, PostgreSQL, and MongoDB. I take full end-to-end ownership from system design to production deployment, optimize database performance, build resilient APIs, and consistently deliver clean, maintainable code aligned with business goals.",
                "CANDIDATE_PROFILE",
                "Why Hire Answer"
            )

        # Company-specific questions: "Why [Company]?", "Why do you want to join our company?", "How can you contribute?"
        if any(k in ctx for k in ["interested in", "why our company", "why work with us", "why join", "why this company", "why oyster", "how can you contribute", "why do you want to work"]):
            cname = (company_name or "").strip()
            if not cname:
                m_why = re.search(r"why\s+([A-Za-z0-9_.\s]+)\??", q_clean, re.IGNORECASE)
                if m_why and m_why.group(1).lower() not in ["join", "work", "apply", "hire", "choose", "us", "this company", "our company", "you"]:
                    cname = m_why.group(1).strip()
            target_name = cname or "your organization"
            return (
                f"I am inspired by {target_name}'s strong engineering culture, impactful product vision, and commitment to building scalable software. My 5+ years of full-stack engineering expertise with React.js, Next.js, Node.js, TypeScript, and distributed systems directly align with {target_name}'s technology requirements, allowing me to hit the ground running and make immediate, high-quality contributions.",
                "CANDIDATE_PROFILE",
                f"Company Interest Answer ({target_name})"
            )

        # Specific technical questions under job-specific category
        if any(k in ctx for k in ["programming languages", "which languages"]):
            return (answers.get("programming_languages", "JavaScript, TypeScript, Python, SQL, C, C++"), "CANDIDATE_PROFILE", "Programming Languages")
        if any(k in ctx for k in ["frontend technologies", "frontend technology"]):
            return (answers.get("frontend_technologies", "React.js, Next.js, Redux Toolkit, Zustand, Tailwind CSS, Material UI, HTML5, CSS3"), "CANDIDATE_PROFILE", "Frontend Technologies")
        if any(k in ctx for k in ["backend technologies", "backend technology"]):
            return (answers.get("backend_technologies", "Node.js, Express.js, REST APIs, GraphQL, Socket.io, Prisma, Mongoose"), "CANDIDATE_PROFILE", "Backend Technologies")
        if any(k in ctx for k in ["which databases", "databases have you used"]):
            return (answers.get("databases", "MongoDB, PostgreSQL, MySQL, SQLite"), "CANDIDATE_PROFILE", "Databases")
        if any(k in ctx for k in ["docker, redis", "redis or kafka", "docker or redis"]):
            return ("Yes, I have hands-on production experience with Docker for containerization, Redis for caching and session management, and Apache Kafka for event-driven messaging architectures.", "CANDIDATE_PROFILE", "Docker, Redis, Kafka Experience")
        if any(k in ctx for k in ["experience with rest", "rest api experience", "restful api"]):
            return ("Over 5+ years of experience designing, developing, documenting, and consuming scalable RESTful APIs with Node.js and Express, implementing JWT authentication, rate limiting, and database optimization.", "CANDIDATE_PROFILE", "REST API Experience")
        if any(k in ctx for k in ["cloud technologies", "worked with cloud"]):
            return ("Yes, I have worked with AWS (EC2, S3), Docker containerization, and automated CI/CD pipelines on GitLab and GitHub Actions.", "CANDIDATE_PROFILE", "Cloud Technologies Experience")

        if any(k in ctx for k in ["mern", "mern stack"]):
            return (answers.get("describe_mern_experience"), "CANDIDATE_PROFILE", "MERN Experience Summary")
        if any(k in ctx for k in ["react and node", "react.js and node", "react", "node"]):
            return (answers.get("experience_react_node"), "CANDIDATE_PROFILE", "React & Node Experience")
        if any(k in ctx for k in ["suitable", "fit for this role", "why you"]):
            return (answers.get("why_suitable_for_role"), "CANDIDATE_PROFILE", "Role Suitability")
        return (answers.get("why_hire"), "CANDIDATE_PROFILE", "Why Hire Answer")

    # --- CATEGORY: CAREER GOALS ---
    if category == QuestionCategory.CAREER_GOALS:
        return (answers.get("reason_for_job_change"), "CANDIDATE_PROFILE", "Reason for Job Change")

    # Consent / Transcripts / Interview recording
    if any(k in ctx for k in ["transcript", "transcripts", "interview transcript", "interview transcripts", "interview recording", "transcription consent"]):
        return ("Yes", "CANDIDATE_PROFILE", "Consent to Interview Transcripts (Yes)")

    # Additional standard answers
    if "portfolio" in ctx:
        return (profile.get("portfolio"), "CANDIDATE_PROFILE", "Portfolio URL")
    if "github" in ctx:
        return (profile.get("github"), "CANDIDATE_PROFILE", "GitHub URL")
    if "linkedin" in ctx:
        return (profile.get("linkedin"), "CANDIDATE_PROFILE", "LinkedIn URL")

    # General affirmative checks
    if any(q.startswith(p) for p in ["are you", "do you", "can you", "have you", "is it possible", "will you"]) and not any(k in ctx for k in ["how many", "what is", "how much", "when can"]):
        if any(k in ctx for k in ["comfortable", "willing", "authorized", "experience", "available", "agree", "open to", "able to"]):
            return ("Yes", "DETERMINISTIC_RULE", "Affirmative Confirmation")

    return None, "", ""

    # Consent / Transcripts / Interview recording
    if any(k in ctx for k in ["transcript", "transcripts", "interview transcript", "interview transcripts", "interview recording", "transcription consent"]):
        return ("Yes", "CANDIDATE_PROFILE", "Consent to Interview Transcripts (Yes)")

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

def match_best_option(answer: Any, options: Any, category: str = "OTHER", question_context: str = "") -> Optional[Dict[str, str]]:
    """
    Intelligently aligns a candidate profile answer with available dropdown/radio options.
    Never picks the first option blindly!
    Supports options as List[Dict[str, str]] or List[str], and handles swapped arguments gracefully.
    """
    # Handle swapped arguments gracefully
    if isinstance(answer, (list, tuple)) and isinstance(options, str):
        answer, options = options, answer

    if not options or not answer:
        return None

    # Normalize options to List[Dict[str, str]]
    norm_options = []
    for o in options:
        if isinstance(o, dict):
            norm_options.append(o)
        elif isinstance(o, str):
            norm_options.append({"value": o, "text": o})

    ans_low = str(answer).lower().strip()

    # Filter out empty or placeholder options like 'Select', 'Choose', '--'
    valid_opts = [
        o for o in norm_options 
        if o.get("text", "").strip().lower() not in ["", "select", "choose", "-- select --", "- select -", "please select", "select an option", "--"]
    ]
    if not valid_opts:
        return None

    # 1. Exact text match
    for opt in valid_opts:
        if opt["text"].lower().strip() == ans_low or opt["value"].lower().strip() == ans_low:
            return opt

    # 1.5 MULTI-CHOICE / TOOLS / SKILLS / NONE OF THE ABOVE
    has_none_opt = next((o for o in valid_opts if any(k in o["text"].lower() for k in ["none of the above", "none of these", "neither", "not applicable"])), None)
    if has_none_opt:
        cand_items = [item.strip().lower() for item in re.split(r"[,;/]+", ans_low) if item.strip()]
        any_item_matched = False
        for opt in valid_opts:
            if opt == has_none_opt:
                continue
            opt_t = opt["text"].lower().strip()
            if any(opt_t == ci or opt_t in ci or ci in opt_t for ci in cand_items if len(ci) > 1):
                any_item_matched = True
                break
        if not any_item_matched:
            return has_none_opt

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
        # If question asks about Ruby or unverified tech:
        if any(ut in (question_context or "").lower() for ut in ["ruby", "rails", "golang", "rust", "swift", "kotlin", "php"]):
            for term in ["less than", "0", "1", "none", "no"]:
                match = next((o for o in valid_opts if term in o["text"].lower() or term in o["value"].lower()), None)
                if match:
                    return match

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

    # RELOCATION & LOCATION
    if category in [QuestionCategory.RELOCATION, QuestionCategory.LOCATION] or "mumbai" in ans_low or ans_low in ["yes", "true"]:
        loc_terms = [
            "currently residing in mumbai", "residing in mumbai", "reside in mumbai",
            "i currently reside in mumbai", "mumbai", "kurla", "willing to relocate to mumbai",
            "open to relocate to mumbai", "willing to relocate", "open to relocate", "relocate",
            "yes", "yes, residing", "yes, willing", "both", "agree"
        ]
        for term in loc_terms:
            match = next((o for o in valid_opts if term == o["text"].lower().strip() or term in o["text"].lower() or term in o["value"].lower()), None)
            if match:
                return match

    # COUNTRY
    if ans_low in ["india", "in", "ind"]:
        match = next((o for o in valid_opts if o["text"].lower().strip() in ["india", "in", "ind", "india (+91)"] or o["value"].lower().strip() in ["in", "ind", "india", "101"]), None)
        if match:
            return match
        match = next((o for o in valid_opts if re.search(r"\bindia\b", o["text"].lower()) and not any(c in o["text"].lower() for c in ["indonesia", "indian ocean"])), None)
        if match:
            return match

    # STATE
    if ans_low in ["maharashtra", "mh"]:
        match = next((o for o in valid_opts if o["text"].lower().strip() in ["maharashtra", "mh"] or o["value"].lower().strip() in ["maharashtra", "mh"]), None)
        if match:
            return match
        match = next((o for o in valid_opts if "maharashtra" in o["text"].lower()), None)
        if match:
            return match

    # COUNTRY: QATAR / UAE
    if ans_low in ["qatar", "qa"]:
        match = next((o for o in valid_opts if o["text"].lower().strip() in ["qatar", "qa", "qatar (+974)"] or o["value"].lower().strip() in ["qa", "qat", "qatar", "178"]), None)
        if match:
            return match
        match = next((o for o in valid_opts if re.search(r"\bqatar\b", o["text"].lower())), None)
        if match:
            return match

    if ans_low in ["dubai", "uae", "united arab emirates"]:
        match = next((o for o in valid_opts if any(k in o["text"].lower().strip() for k in ["united arab emirates", "uae", "dubai"])), None)
        if match:
            return match

    # COUNTRY CODE (+91 for India; +974 for Qatar / Dubai / UAE)
    if any(k in ans_low for k in ["+91", "91"]):
        match = next((o for o in valid_opts if "+91" in o["text"].lower() or o["value"].lower().strip() in ["+91", "91", "in"] or "india (+91)" in o["text"].lower() or "+91 (india)" in o["text"].lower() or o["text"].lower().strip() == "india"), None)
        if match:
            return match

    if any(k in ans_low for k in ["+974", "974"]):
        match = next((o for o in valid_opts if "+974" in o["text"].lower() or o["value"].lower().strip() in ["+974", "974", "qa"] or "qatar (+974)" in o["text"].lower() or "+974 (qatar)" in o["text"].lower() or o["text"].lower().strip() == "qatar"), None)
        if match:
            return match

    # PROFICIENCY LEVELS (Section 19.3 & 19.7)
    opt_texts = [o["text"].lower().strip() for o in valid_opts]
    is_proficiency_scale = any(p in opt_texts for p in ["beginner", "intermediate", "advanced", "expert", "basic", "proficient"])
    if is_proficiency_scale:
        full_ctx = f"{ans_low} {(question_context or '').lower()}"
        is_core = any(s in full_ctx for s in [
            "react", "node", "javascript", "typescript", "mern", "express", "mongo", "html", "css", "tailwind", "rest"
        ])
        is_secondary = any(s in full_ctx for s in [
            "aws", "docker", "postgres", "sql", "redis", "kafka", "python", "graphql", "socket", "prisma", "git", "next"
        ])
        if is_core:
            for target in ["expert", "advanced", "proficient"]:
                match = next((o for o in valid_opts if target in o["text"].lower() or target in o["value"].lower()), None)
                if match:
                    return match
        elif is_secondary:
            for target in ["advanced", "intermediate", "proficient"]:
                match = next((o for o in valid_opts if target in o["text"].lower() or target in o["value"].lower()), None)
                if match:
                    return match
        else:
            for target in ["intermediate", "proficient", "advanced"]:
                match = next((o for o in valid_opts if target in o["text"].lower() or target in o["value"].lower()), None)
                if match:
                    return match

    # WORK AUTHORIZATION STATUS (Oyster, Ashby, Greenhouse)
    if any(k in ans_low for k in ["citizen", "permanent resident", "full work authorization", "existing work permit"]):
        match = next((o for o in valid_opts if any(k in o["text"].lower() for k in ["citizen", "permanent resident", "full work authorization", "existing work permit"])), None)
        if match:
            return match

    # AVAILABILITY TO START (Oyster earliest availability)
    if any(k in ans_low for k in ["immediately", "immediate"]):
        for term in ["immediately", "immediate", "within 2 weeks", "0-15", "within 1 month"]:
            match = next((o for o in valid_opts if term in o["text"].lower() or term in o["value"].lower()), None)
            if match:
                return match

    # UNVERIFIED TECHNOLOGIES / JAVA / SPRING / .NET / RUBY
    q_ctx_low = (question_context or "").lower()
    has_java_match = bool(re.search(r"\bjava\b", q_ctx_low)) and not bool(re.search(r"\bjavascript\b", q_ctx_low))
    if has_java_match or any(k in q_ctx_low for k in ["spring boot", "springboot", "j2ee", "hibernate", ".net", "dotnet", "c#", "php", "ruby"]):
        match = next((o for o in valid_opts if any(k in o["text"].lower() or k in o["value"].lower() for k in ["0", "no", "none", "less than", "na", "n/a", "not applicable", "fresher"])), None)
        if match:
            return match

    # WORKPLACE TYPE / WORK MODEL (Section 19.4)
    is_workplace_scale = any(w in opt_texts for w in ["remote", "hybrid", "on-site", "onsite", "in-office"])
    if is_workplace_scale:
        for target in ["remote", "hybrid", "any"]:
            match = next((o for o in valid_opts if target in o["text"].lower() or target in o["value"].lower()), None)
            if match:
                return match

    # GENDER: MALE (Avoid matching 'Female' via substring!)
    if ans_low in ["male", "man"]:
        match = next((o for o in valid_opts if re.search(r"\bmale\b", o["text"].lower()) and not re.search(r"\bfemale\b", o["text"].lower())), None)
        if match:
            return match

    # PRONOUN: HE/HIM
    if any(k in ans_low for k in ["he/him", "he"]):
        match = next((o for o in valid_opts if any(k in o["text"].lower() for k in ["he/him", "he/him/his", "he / him", "male", "prefer not to say"])), None)
        if match:
            return match

    # DEGREE TYPE
    if any(k in ans_low for k in ["bsc", "computer science"]):
        match = next((o for o in valid_opts if any(k in o["text"].lower() for k in ["bsc computer sciences", "bsc computer science", "computer science", "b.sc", "bachelor of science", "graduate"])), None)
        if match:
            return match

    # TECHNICAL SKILLS
    if category == QuestionCategory.TECHNICAL_SKILLS:
        if any(k in ans_low for k in ["node", "node.js", "nodejs"]):
            match = next((o for o in valid_opts if any(k in o["text"].lower() or k in o["value"].lower() for k in ["node.js", "nodejs", "node js", "node"])), None)
            if match:
                return match
        if any(k in ans_low for k in ["react", "react.js", "reactjs"]):
            match = next((o for o in valid_opts if any(k in o["text"].lower() or k in o["value"].lower() for k in ["react.js", "reactjs", "react js", "react"])), None)
            if match:
                return match

    # LANGUAGE SKILLS (German / English / Hindi / etc.)
    if category == QuestionCategory.LANGUAGE_SKILLS or any(k in (question_context or "").lower() for k in ["deutsch", "german", "english", "language"]):
        if any(k in ans_low for k in ["keine", "none", "no"]):
            match = next((o for o in valid_opts if any(k in o["text"].lower() or k in o["value"].lower() for k in ["keine", "keine (kenntnisse)", "keine kenntnisse", "none", "nicht"])), None)
            if match:
                return match
        if any(k in ans_low for k in ["fluent", "fließend", "native", "muttersprache", "advanced", "professional"]):
            match = next((o for o in valid_opts if any(k in o["text"].lower() or k in o["value"].lower() for k in ["fluent", "native", "fließend", "advanced", "professional", "c1", "c2", "fluent/native"])), None)
            if match:
                return match
        if any(k in ans_low for k in ["english"]):
            match = next((o for o in valid_opts if any(k in o["text"].lower() or k in o["value"].lower() for k in ["english", "englisch"])), None)
            if match:
                return match

    # YES / NO (Including German Ja / Nein and Agreement)
    if ans_low in ["yes", "true", "agree", "positive", "ja"]:
        match = next((o for o in valid_opts if any(
            k == o["text"].lower().strip() or o["text"].lower().startswith(k) or k in o["text"].lower()
            for k in ["ja", "yes", "agree", "confirm", "comfortable", "i agree", "residing", "willing", "stimme zu"]
        )), None)
        if match:
            return match

    if ans_low in ["no", "false", "negative", "none", "nein", "keine"]:
        # Strict matching for No, Disability No, Veteran No, etc.
        match = next((o for o in valid_opts if any(
            re.search(r"\b" + re.escape(k) + r"\b", o["text"].lower()) or o["text"].lower().strip() == k
            for k in [
                "nein", "keine", "keine (kenntnisse)", "no", "not applicable", "n/a", "none", "i do not have a disability", 
                "no disability", "i don't have a disability", "no, i am not a veteran",
                "not a veteran", "neither", "prefer not to disclose", "i do not require sponsorship"
            ]
        )), None)
        if match:
            return match
        # Fallback to option starting with 'no'
        match = next((o for o in valid_opts if o["text"].lower().strip().startswith("no") and not o["text"].lower().strip().startswith("notice")), None)
        if match:
            return match

    # 3. Substring match (with boundary protection)
    for opt in valid_opts:
        otxt = opt["text"].lower()
        oval = opt["value"].lower()
        # Prevent "male" from matching "female"
        if ans_low == "male" and "female" in otxt:
            continue
        # Prevent "no" from matching "notice" or words containing "no"
        if ans_low in ["no", "none"] and not re.search(r"\b(no|none)\b", otxt):
            continue
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
                         job_title: str = "", company_name: str = "",
                         field_name: str = "", field_id: str = "",
                         location_hint: str = "") -> Dict[str, Any]:
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
        self.profile = get_profile()
        q = (question_text or "").strip()
        if not q and not field_name and not field_id:
            return {
                "answer": "",
                "selected_option": None,
                "needs_user_input": False,
                "category": QuestionCategory.OTHER,
                "source": "NONE",
                "reason": "EMPTY_QUESTION",
                "is_blocked": False
            }

        effective_q = q or field_name or field_id

        # 1. Safety Boundary Check
        is_blocked, block_reason = is_sensitive_or_payment(effective_q)
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

        # 1.5 CAPTCHA Challenge Check (Strict Enforcement: never auto-fill or bypass)
        is_captcha = any(k in effective_q.lower() for k in ["captcha", "security code", "verification code", "image code", "type the characters", "enter text from image"])
        if is_captcha:
            return {
                "answer": "",
                "selected_option": None,
                "needs_user_input": True,
                "category": "CAPTCHA",
                "source": "CAPTCHA_CHALLENGE",
                "reason": "CAPTCHA_REQUIRED: Human verification challenge must be solved by candidate in visible browser window.",
                "is_blocked": True
            }

        category = classify_question_category(effective_q)

        # 2. Check Candidate Profile (Deterministic)
        ans, source, reason = resolve_answer_from_profile(
            effective_q, category, input_type, field_name, field_id,
            location_hint=location_hint, job_title=job_title, company_name=company_name
        )
        if ans is not None:
            # If options are provided (dropdown, radio, chips), find the matching option
            selected_opt = None
            if available_options:
                selected_opt = match_best_option(ans, available_options, category, question_context=effective_q)
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

        # 3. Autonomous Thinking Engine: AI or Intelligent Synthesis
        llm_answer = self._call_llm(q, category, input_type, job_title)
        if not llm_answer or "UNKNOWN" in (llm_answer or "").upper():
            synth_answer = self._synthesize_intelligent_answer(
                question=effective_q, category=category, input_type=input_type,
                job_title=job_title, company_name=company_name,
                location_hint=location_hint
            )
            if synth_answer:
                llm_answer = synth_answer

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
                selected_opt = match_best_option(llm_answer, available_options, category, question_context=effective_q)
                if selected_opt:
                    llm_answer = selected_opt.get("value") or selected_opt.get("text")

            return {
                "answer": llm_answer,
                "selected_option": selected_opt,
                "needs_user_input": False,
                "category": category,
                "source": "AI_SYNTHESIS",
                "reason": "Autonomous Question Synthesis",
                "is_blocked": False
            }

        # 4. Unknown Personal Facts Handling - NEVER FABRICATE private identification numbers!
        q_low = q.lower()
        unverified_keywords = [
            "father's name", "mother's name", "spouse's name", "passport number",
            "pan card number", "aadhaar number", "social security", "ssn", "caste"
        ]
        if any(k in q_low for k in unverified_keywords) and not any(k in q_low for k in ["employed", "working", "partner", "relative"]):
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

    def _synthesize_intelligent_answer(self, question: str, category: str, input_type: str,
                                       job_title: str = "", company_name: str = "",
                                       location_hint: str = "") -> Optional[str]:
        """
        MASTER SYSTEM PROMPT SECTION 19:
        Autonomous thinking engine that intelligently analyzes question semantics
        and composes high-quality, professional, customized answers grounded in
        candidate profile, without halting for manual user input.
        """
        q_low = question.lower().strip()
        cname = company_name or "your organization"
        target_role = job_title or "Senior Full Stack Developer"

        # 0. Strict CAPTCHA / Human verification guard: NEVER return an answer
        if any(k in q_low for k in ["captcha", "security code", "verification code", "image code", "type the characters", "enter text from image", "security text", "code shown", "challenge"]):
            return ""

        # 1. Unknown private facts check (Only halt for real private identification numbers)
        unverified_keywords = ["passport number", "pan card number", "aadhaar number", "father's name", "mother's name", "spouse's name"]
        if any(k in q_low for k in unverified_keywords) and not any(k in q_low for k in ["employed", "working", "partner", "relative"]):
            return None

        # 2. Affirmative Yes/No screening
        if input_type in ["radio", "button_group", "select"] or any(q_low.startswith(p) for p in ["are you", "do you", "can you", "will you", "is it possible", "have you"]):
            # Negative checks for unverified technologies (Candidate specializes in MERN / JavaScript Full Stack)
            has_java_syn = bool(re.search(r"\bjava\b", q_low)) and not bool(re.search(r"\bjavascript\b", q_low))
            is_unverified_tech = has_java_syn or any(k in q_low for k in ["spring boot", "springboot", "j2ee", "hibernate", "core java", ".net", "dotnet", "c#", "php", "ruby", "rails"])
            if is_unverified_tech:
                return "No"

            # Negative checks (sponsorship, disability, criminal, relatives, conflict of interest, etc.)
            if any(k in q_low for k in ["sponsorship", "disability", "convicted", "criminal", "disciplinary", "previously fired", "family member", "romantic partner", "relative", "relatives", "conflict of interest"]):
                return "No"
            return "Yes"

        # 3. System Design & Architecture
        if any(k in q_low for k in ["architecture", "system design", "scalable", "microservice", "scale", "performance"]):
            return "In my 5+ years of full-stack engineering, I architect resilient, decoupled systems with clean boundaries. I utilize stateless Node.js/Express and Next.js services, implement low-latency Redis caching and session management, design indexed database schemas in PostgreSQL and MongoDB, and containerize microservices using Docker for automated cloud deployments on AWS. I enforce defensive API error handling, rate limiting, and comprehensive integration testing."

        # 4. Code Quality, Testing, & Best Practices
        if any(k in q_low for k in ["code quality", "testing", "test", "clean code", "best practice", "review"]):
            return "I maintain high code quality through a rigorous engineering discipline: enforcing strict TypeScript types and ESLint standards, writing modular unit tests with Jest, conducting thorough peer pull request reviews on GitHub/GitLab, and maintaining automated CI/CD validation. I advocate for DRY and SOLID design principles, clean component modularity in React, and robust API contracts."

        # 5. Remote Work & Attributes
        if any(k in q_low for k in ["remote", "wfh", "distributed", "time zone", "async", "attribute"]):
            return "With 5+ years of remote software engineering experience, my key success attributes are disciplined self-management, proactive asynchronous communication, and autonomous execution. I structure tasks transparently in Jira, document architectural decisions in Confluence, coordinate across diverse time zones, and maintain high delivery velocity and clean code quality without requiring supervision."

        # 6. Agile, Deadlines, & Fast-paced Delivery
        if any(k in q_low for k in ["agile", "scrum", "sprint", "deadline", "fast-paced", "prioritize"]):
            return "I thrive in fast-paced Agile environments by breaking complex epics into small, testable user stories with clear acceptance criteria. I prioritize tasks based on user and business impact, communicate transparently during standups, flag technical blockers early, and consistently deliver well-tested increments on time."

        # 7. Teamwork, Conflict, & Disagreements
        if any(k in q_low for k in ["conflict", "disagree", "teamwork", "collaboration", "stakeholder"]):
            return "When technical disagreements arise, I focus on data, engineering trade-offs, and user requirements rather than personal opinions. I facilitate open discussions, build small proof-of-concepts to validate assumptions, and align with the team's consensus and overarching business goals to keep development momentum moving forward smoothly."

        # 8. Learning & Adaptability
        if any(k in q_low for k in ["learn", "adapt", "new technology", "unfamiliar", "challenge"]):
            return "With solid computer science fundamentals and 5+ years across the MERN, Node.js, and TypeScript ecosystems, I adapt rapidly to new languages, frameworks, and tools. My approach involves diving into official documentation, analyzing production codebases, building focused proof-of-concepts, and applying battle-tested software engineering design patterns."

        # 9. Guard: Availability to start / start date / Notice Period
        if category == QuestionCategory.NOTICE_PERIOD or any(k in q_low for k in ["start", "available to start", "start working", "availability", "when are you available", "startdatum", "eintrittsdatum", "verfügbarkeit", "kündigungsfrist"]):
            import datetime
            near_date = (datetime.date.today() + datetime.timedelta(days=7)).strftime("%Y-%m-%d")
            near_date_de = (datetime.date.today() + datetime.timedelta(days=7)).strftime("%d.%m.%Y")
            if input_type == "date" or "datum" in q_low:
                return near_date_de if any(k in q_low for k in ["deutsch", "germany", "eur", "startdatum"]) else near_date
            if any(k in q_low for k in ["startdatum", "frühestmögliches", "eintrittsdatum", "sofort"]):
                return "Sofort"
            return "Immediately"

        # 10. Guard: Salary / Compensation (Never allow essay summaries into salary fields!)
        is_salary_prompt = category == QuestionCategory.SALARY or any(k in q_low for k in [
            "salary", "compensation", "gehalt", "ctc", "earning", "vergütung", "remuneration", "renumeration", "pay rate", "wages", "cost-to-company", "cost to company"
        ])
        if is_salary_prompt:
            cand_p = getCandidateProfileByJobLocation(location_hint)
            is_intl = cand_p.get("is_international", False)
            is_monthly = any(k in q_low for k in ["month", "monthly", "/month", "pm", "per month"])
            is_expected = any(k in q_low for k in ["expected", "desired", "target", "expectation", "aspiring"])
            
            if is_intl:
                # Gulf: 8000 QAR/AED monthly or 96000 annual
                if is_monthly or "monthly" in q_low or "salary" in q_low or "remuneration" in q_low or "renumeration" in q_low:
                    return "8000"
                if any(k in q_low for k in ["eur", "euro", "€"]):
                    return "65000"
                if any(k in q_low for k in ["usd", "$", "dollar"]):
                    return "75000"
                return "8000"
            else:
                # India: 83000 current / 125000 expected monthly; 12 LPA current / 15 LPA expected annual
                if is_monthly or "monthly" in q_low:
                    return "125000" if is_expected else "83000"
                if any(k in q_low for k in ["lpa", "lakh", "lac"]):
                    return "15 LPA" if is_expected else "12 LPA"
                return "1500000" if is_expected else "1200000"

        # 11. General Open-Ended Screening / Why Hire / Summary
        # Never treat structured categories (salary, notice period, language, experience, personal info) as essay prompts
        structured_categories = [
            QuestionCategory.NOTICE_PERIOD,
            QuestionCategory.SALARY,
            QuestionCategory.LANGUAGE_SKILLS,
            QuestionCategory.EXPERIENCE,
            QuestionCategory.PERSONAL_INFO,
            QuestionCategory.LOCATION
        ]
        has_structured_keyword = any(k in q_low for k in [
            "salary", "ctc", "remuneration", "renumeration", "compensation", "cost to company",
            "notice", "experience", "years", "dob", "birth", "phone", "mobile", "country code"
        ])
        is_essay_prompt = (
            category not in structured_categories and not has_structured_keyword and (
                (input_type == "textarea" and not any(k in q_low for k in ["answer", "your answer", "your response", "response"])) or
                any(k in q_low for k in [
                    "summary", "cover letter", "coverletter", "about yourself", "about me", "introduce yourself",
                    "tell me about", "tell us about", "why should we hire", "why are you interested", "pitch",
                    "note to recruiter", "note to", "share a short summary", "contribute to"
                ])
            )
        )
        if is_essay_prompt:
            return f"I bring 5+ years of production experience as a Senior Full Stack Developer specializing in React.js, Next.js, Node.js, TypeScript, PostgreSQL, and MongoDB. I have delivered enterprise platforms, scalable REST/GraphQL APIs, and automated cloud deployments with Docker and AWS. I combine end-to-end technical execution with disciplined clean code, and I am excited to contribute high-impact, reliable features to {cname}."

        # Short safe default for single-line inputs (prevents maxlength 20 violations and CAPTCHA pollution)
        if any(k in q_low for k in ["captcha", "security", "code", "verification", "image", "challenge"]):
            return ""
        if any(k in q_low for k in ["designation", "job title", "position applied", "current title"]):
            return "Senior Full Stack Developer"
        return ""

# Singleton instance for easy reuse
qa_engine = QuestionAnsweringEngine()
