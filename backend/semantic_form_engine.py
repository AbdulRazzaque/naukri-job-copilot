"""
Intelligent Form Understanding & Semantic Autofill Engine
=========================================================
A robust, context-aware form understanding and autofill engine for all job application
platforms (LinkedIn, Naukri, NaukriGulf, Oracle Cloud HCM, Workday, Greenhouse, Lever, Ashby, etc.).

Key Capabilities:
1. Understand Before Filling:
   Deep multi-signal DOM inspection (labels, headings, help text, descriptions, placeholders,
   input types, HTML attributes, character constraints).
2. Semantic Field Classification:
   Accurate classification into standard categories with confidence scoring.
3. Strict Candidate Data Mapping:
   Single source of truth. Prevents cross-contamination (e.g., never putting essay summaries in
   salary fields, never putting skills in experience fields, never putting +971 in phone fields).
4. Currency & Period Intelligence:
   Differentiates Monthly Salary vs Annual CTC, local currency vs INR vs USD/EUR.
5. Pre-Submission Semantic Integrity Audit:
   Validates populated fields before submit, detects and cleans pollution, and guarantees conformance.
"""

import os
import re
import json
import logging
from typing import Dict, Any, Tuple, Optional, List
from candidate_manager import getCandidateProfileByJobLocation

logger = logging.getLogger("semantic_form_engine")

class SemanticFieldCategory:
    # Salary & Compensation
    CURRENT_MONTHLY_SALARY = "CURRENT_MONTHLY_SALARY"
    EXPECTED_MONTHLY_SALARY = "EXPECTED_MONTHLY_SALARY"
    CURRENT_ANNUAL_CTC = "CURRENT_ANNUAL_CTC"
    EXPECTED_ANNUAL_CTC = "EXPECTED_ANNUAL_CTC"
    GENERIC_SALARY = "GENERIC_SALARY"
    
    # Experience & Career
    TOTAL_EXPERIENCE = "TOTAL_EXPERIENCE"
    RELEVANT_EXPERIENCE = "RELEVANT_EXPERIENCE"
    NOTICE_PERIOD = "NOTICE_PERIOD"
    CURRENT_COMPANY = "CURRENT_COMPANY"
    PREVIOUS_COMPANY = "PREVIOUS_COMPANY"
    CURRENT_DESIGNATION = "CURRENT_DESIGNATION"
    
    # Skills & Links
    PRIMARY_SKILLS = "PRIMARY_SKILLS"
    ALL_SKILLS = "ALL_SKILLS"
    LINKEDIN_URL = "LINKEDIN_URL"
    GITHUB_URL = "GITHUB_URL"
    PORTFOLIO_URL = "PORTFOLIO_URL"
    
    # Contact & Identity
    EMAIL_ADDRESS = "EMAIL_ADDRESS"
    PHONE_NUMBER = "PHONE_NUMBER"
    PHONE_COUNTRY_CODE = "PHONE_COUNTRY_CODE"
    DATE_OF_BIRTH = "DATE_OF_BIRTH"
    CAPTCHA = "CAPTCHA"
    FULL_NAME = "FULL_NAME"
    FIRST_NAME = "FIRST_NAME"
    LAST_NAME = "LAST_NAME"
    AGE = "AGE"
    MARITAL_STATUS = "MARITAL_STATUS"
    NATIONALITY = "NATIONALITY"
    
    # Locations
    RESIDENTIAL_LOCATION = "RESIDENTIAL_LOCATION"
    PREFERRED_WORK_LOCATION = "PREFERRED_WORK_LOCATION"
    RESIDENTIAL_CITY = "RESIDENTIAL_CITY"
    RESIDENTIAL_STATE = "RESIDENTIAL_STATE"
    RESIDENTIAL_COUNTRY = "RESIDENTIAL_COUNTRY"
    
    # Text / Essays
    COVER_LETTER = "COVER_LETTER"
    PROFESSIONAL_SUMMARY = "PROFESSIONAL_SUMMARY"
    
    # Demographics & Compliance
    GENDER = "GENDER"
    DISABILITY = "DISABILITY"
    VETERAN_STATUS = "VETERAN_STATUS"
    VISA_SPONSORSHIP = "VISA_SPONSORSHIP"
    WORK_AUTHORIZATION = "WORK_AUTHORIZATION"
    TERMS_ACCEPTANCE = "TERMS_ACCEPTANCE"
    RESUME_UPLOAD = "RESUME_UPLOAD"
    
    # Fallback
    UNKNOWN_MANDATORY = "UNKNOWN_MANDATORY"
    OTHER = "OTHER"

GENERIC_PLACEHOLDERS = {
    "your answer", "type answer", "enter answer", "enter here", "type here",
    "write your response", "write your answer", "please enter", "please specify",
    "answer", "response", "your response", "input", "text", "comments",
    "details", "optional", "n/a", "placeholder"
}

class SemanticFormEngine:
    """
    Centralized contextual form inspector and answer generator.
    """

    @staticmethod
    def clean_text(text: str) -> str:
        if not text:
            return ""
        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def is_generic_label(cls, label: str) -> bool:
        """Determines if a label is merely a placeholder like 'Your answer'."""
        if not label:
            return True
        norm = re.sub(r"[*?:_#()\-]+", "", label).strip().lower()
        return norm in GENERIC_PLACEHOLDERS or len(norm) < 2

    @classmethod
    def classify_field(cls, 
                       label: str = "", 
                       heading: str = "", 
                       help_text: str = "", 
                       placeholder: str = "", 
                       input_type: str = "text",
                       name: str = "",
                       field_id: str = "",
                       max_length: Optional[int] = None) -> Tuple[str, float, str]:
        """
        Classifies a field into a SemanticFieldCategory with a confidence score.
        Returns: (category, confidence, explanation)
        """
        # Determine effective label
        effective_label = label
        if cls.is_generic_label(label) and heading:
            effective_label = heading

        combined = f"{effective_label} {heading} {help_text} {placeholder} {name} {field_id}".lower()
        combined_clean = re.sub(r"[*?:_#()\-]+", " ", combined).strip()
        tokens = set(combined_clean.split())

        # -------------------------------------------------------------
        # 0. CAPTCHA & SECURITY CHALLENGES (Strict Safety Boundary)
        # -------------------------------------------------------------
        if any(k in combined_clean for k in ["captcha", "security code", "verification code", "enter text from image", "type the characters", "image code"]):
            return SemanticFieldCategory.CAPTCHA, 0.99, "CAPTCHA Security Challenge (Requires Candidate Input)"

        # -------------------------------------------------------------
        # 1. SALARY & COMPENSATION
        # -------------------------------------------------------------
        is_salary_context = any(k in combined_clean for k in [
            "salary", "remuneration", "renumeration", "compensation", "ctc", "earning", "pay rate", "wages"
        ])

        if is_salary_context:
            is_monthly = any(k in combined_clean for k in ["monthly", "per month", "month", "/month", "pm"])
            is_annual = any(k in combined_clean for k in ["annual", "per annum", "annum", "yearly", "p.a", "lpa", "lakhs", "/year"])
            is_current = any(k in combined_clean for k in ["current", "present", "existing", "drawing", "now"])
            is_expected = any(k in combined_clean for k in ["expected", "desired", "target", "looking for", "expectation", "aspiring"])

            if is_monthly and is_current:
                return SemanticFieldCategory.CURRENT_MONTHLY_SALARY, 0.98, "Current Monthly Salary (Explicit label & period)"
            if is_monthly and is_expected:
                return SemanticFieldCategory.EXPECTED_MONTHLY_SALARY, 0.98, "Expected Monthly Salary (Explicit label & period)"
            if is_annual and is_current:
                return SemanticFieldCategory.CURRENT_ANNUAL_CTC, 0.98, "Current Annual CTC (Explicit annual period)"
            if is_annual and is_expected:
                return SemanticFieldCategory.EXPECTED_ANNUAL_CTC, 0.98, "Expected Annual CTC (Explicit annual period)"
            
            # If not explicitly monthly or annual
            if is_current:
                return SemanticFieldCategory.CURRENT_MONTHLY_SALARY if is_monthly else SemanticFieldCategory.CURRENT_ANNUAL_CTC, 0.85, "Current Salary"
            if is_expected:
                return SemanticFieldCategory.EXPECTED_MONTHLY_SALARY if is_monthly else SemanticFieldCategory.EXPECTED_ANNUAL_CTC, 0.85, "Expected Salary"
            
            return SemanticFieldCategory.GENERIC_SALARY, 0.75, "Generic Salary Context"

        # -------------------------------------------------------------
        # 2. EXPERIENCE & TENURE
        # -------------------------------------------------------------
        if any(k in combined_clean for k in ["notice period", "notice", "availability to join", "how soon can you join", "days notice"]):
            return SemanticFieldCategory.NOTICE_PERIOD, 0.95, "Notice Period / Joining Availability"

        if any(k in combined_clean for k in ["relevant experience", "experience in react", "experience in node", "years of relevant"]):
            return SemanticFieldCategory.RELEVANT_EXPERIENCE, 0.92, "Relevant Technical Experience"

        if any(k in combined_clean for k in ["total experience", "overall experience", "total years", "years of experience", "work experience"]):
            return SemanticFieldCategory.TOTAL_EXPERIENCE, 0.95, "Total Professional Experience"

        # -------------------------------------------------------------
        # 3. COMPANY & DESIGNATION
        # -------------------------------------------------------------
        if any(k in combined_clean for k in ["current company", "current employer", "present employer", "organization currently", "current organization"]):
            return SemanticFieldCategory.CURRENT_COMPANY, 0.95, "Current Company"

        if any(k in combined_clean for k in ["previous company", "past employer", "last company", "prior organization"]):
            return SemanticFieldCategory.PREVIOUS_COMPANY, 0.95, "Previous Company"

        if any(k in combined_clean for k in ["current designation", "current role", "current title", "present designation", "present role"]):
            return SemanticFieldCategory.CURRENT_DESIGNATION, 0.95, "Current Designation"

        # -------------------------------------------------------------
        # 4. CONTACT & IDENTITY
        # -------------------------------------------------------------
        if any(k in combined_clean for k in ["date of birth", "dob", "birth date", "birthdate", "birthday"]) and not any(k in combined_clean for k in ["place of birth", "country of birth"]):
            return SemanticFieldCategory.DATE_OF_BIRTH, 0.98, "Candidate Date of Birth (19-11-1999)"

        if any(k in combined_clean for k in ["country code", "dial code", "calling code", "phone code", "country codes"]):
            return SemanticFieldCategory.PHONE_COUNTRY_CODE, 0.98, "Phone Country Code / Dial Code"

        if any(k in combined_clean for k in ["phone", "mobile", "contact number", "cell number", "telephone"]) and not any(k in combined_clean for k in ["country code", "dial code"]):
            return SemanticFieldCategory.PHONE_NUMBER, 0.95, "Phone / Mobile Number"

        if any(k in combined_clean for k in ["email", "e mail", "email address"]):
            return SemanticFieldCategory.EMAIL_ADDRESS, 0.98, "Email Address"

        if any(k in combined_clean for k in ["full name", "fullname", "candidate name", "complete name", "your name"]) or (("name" in tokens or "name" in combined_clean) and not any(k in combined_clean for k in ["first name", "last name", "surname", "company", "college", "school", "user", "file", "org"])):
            return SemanticFieldCategory.FULL_NAME, 0.98, "Candidate Full Name"

        if any(k in combined_clean for k in ["first name", "given name"]):
            return SemanticFieldCategory.FIRST_NAME, 0.98, "First Name"

        if any(k in combined_clean for k in ["last name", "surname", "family name"]):
            return SemanticFieldCategory.LAST_NAME, 0.98, "Last Name"

        if input_type == "file" or any(k in combined_clean for k in [
            "resume", "cv", "curriculum vitae", "upload cv", "upload resume", "attach resume",
            "attach cv", "attach document", "drop document", "attach your resume", "upload your resume",
            "upload your cv", "drag & drop", "drag and drop"
        ]):
            return SemanticFieldCategory.RESUME_UPLOAD, 0.98, "Candidate Resume / CV File Upload"

        if any(k in combined_clean for k in ["agree with the storage", "storage and handling", "handling of your data", "data processing", "by using this form you agree", "privacy policy", "terms of service", "accept terms", "terms &", "terms and"]):
            return SemanticFieldCategory.TERMS_ACCEPTANCE, 0.98, "Data Storage and Handling Agreement"

        # -------------------------------------------------------------
        # 5. ONLINE PROFILES & LINKS
        # -------------------------------------------------------------
        if "linkedin" in combined_clean:
            return SemanticFieldCategory.LINKEDIN_URL, 0.98, "LinkedIn Profile URL"

        if "github" in combined_clean:
            return SemanticFieldCategory.GITHUB_URL, 0.98, "GitHub URL"

        if any(k in combined_clean for k in ["portfolio", "website", "personal site", "blog url"]):
            return SemanticFieldCategory.PORTFOLIO_URL, 0.95, "Portfolio URL"

        # -------------------------------------------------------------
        # 6. LOCATION INTELLIGENCE
        # -------------------------------------------------------------
        if any(k in combined_clean for k in ["what country are you located in", "country you are located in", "country are you located", "current country", "residential country"]) or (any(k in combined_clean for k in ["country", "nation"]) and not any(k in combined_clean for k in ["country code", "dial code", "calling code", "phone code"])):
            return SemanticFieldCategory.RESIDENTIAL_COUNTRY, 0.95, "Candidate Residential Country"

        if any(k in combined_clean for k in [
            "location (city)", "location(city)", "current location", "current city", "current address", 
            "where do you reside", "home address", "living in", "city", "town",
            "permanent address", "address as per", "government issued id", "location of residence", 
            "residence location", "place of residence", "location of residence and language"
        ]):
            return SemanticFieldCategory.RESIDENTIAL_LOCATION, 0.95, "Current Residence Location"

        if any(k in combined_clean for k in ["preferred location", "desired location", "preferred work location", "open to relocate", "preference for location"]):
            return SemanticFieldCategory.PREFERRED_WORK_LOCATION, 0.95, "Preferred Work Location"

        # -------------------------------------------------------------
        # 7. ESSAY / OPEN-ENDED PROMPTS
        # -------------------------------------------------------------
        if any(k in combined_clean for k in ["cover letter", "coverletter", "why do you want to work", "why join", "interest in this role", "pitch"]):
            return SemanticFieldCategory.COVER_LETTER, 0.90, "Cover Letter / Motivation Prompt"

        if any(k in combined_clean for k in ["professional summary", "profile summary", "about yourself", "tell us about yourself", "brief bio", "short summary", "bio", "biography", "short bio", "candidate bio"]):
            return SemanticFieldCategory.PROFESSIONAL_SUMMARY, 0.90, "Professional Profile Summary / Bio"

        # -------------------------------------------------------------
        # 8. DEMOGRAPHICS & CANDIDATE IDENTITY
        # -------------------------------------------------------------
        if re.search(r"\b(age|candidate[-_ ]?age|your[-_ ]?age)\b", combined_clean, re.I) and not any(k in combined_clean for k in ["language", "percentage", "coverage", "manage", "package", "average"]):
            return SemanticFieldCategory.AGE, 0.95, "Candidate Age"

        if any(k in combined_clean for k in ["marital status", "civil status", "marital"]):
            return SemanticFieldCategory.MARITAL_STATUS, 0.95, "Candidate Marital Status"

        if any(k in combined_clean for k in ["current nationality", "what is your current nationality", "nationality"]) and not any(k in combined_clean for k in ["sponsorship", "visa"]):
            return SemanticFieldCategory.NATIONALITY, 0.95, "Candidate Nationality"

        # Fallback / Unknown
        return SemanticFieldCategory.OTHER, 0.30, "Unclassified General Field"

    @classmethod
    def get_candidate_value(cls, 
                            category: str, 
                            location_hint: str = "", 
                            input_type: str = "text",
                            max_length: Optional[int] = None,
                            currency_hint: str = "") -> Tuple[str, str]:
        """
        Retrieves the exact, verified candidate value mapped to the category.
        Ensures strict data integrity, preventing any essay pollution into structured fields.
        Returns: (value, description)
        """
        cand_p = getCandidateProfileByJobLocation(location_hint)
        is_international = cand_p["is_international"]
        detected_country = cand_p.get("detected_country", "")

        is_numeric_input = input_type in ["number", "numeric"] or "number" in input_type
        # Local currency detection
        local_curr = "QAR" if "qatar" in detected_country.lower() else ("AED" if "emirates" in detected_country.lower() else "INR")
        if currency_hint:
            if "aed" in currency_hint.lower(): local_curr = "AED"
            elif "qar" in currency_hint.lower() or "riyal" in currency_hint.lower(): local_curr = "QAR"
            elif "inr" in currency_hint.lower() or "rs" in currency_hint.lower(): local_curr = "INR"

        # 1. CURRENT MONTHLY SALARY
        if category == SemanticFieldCategory.CURRENT_MONTHLY_SALARY:
            if is_international:
                # 8000 Riyal / AED monthly
                if is_numeric_input or (max_length and max_length <= 15):
                    return "8000", "Current Monthly Salary (Numeric Gulf)"
                return f"8000 {local_curr}", "Current Monthly Salary (Formatted Gulf)"
            else:
                # India: 83,000 INR monthly
                if is_numeric_input or (max_length and max_length <= 15):
                    return "83000", "Current Monthly Salary (Numeric India)"
                return "83,000 INR", "Current Monthly Salary (Formatted India)"

        # 2. EXPECTED MONTHLY SALARY
        if category == SemanticFieldCategory.EXPECTED_MONTHLY_SALARY:
            if is_international:
                if is_numeric_input or (max_length and max_length <= 15):
                    return "8000", "Expected Monthly Salary (Numeric Gulf)"
                return f"8000 {local_curr}", "Expected Monthly Salary (Formatted Gulf)"
            else:
                if is_numeric_input or (max_length and max_length <= 15):
                    return "125000", "Expected Monthly Salary (Numeric India)"
                return "1,25,000 INR", "Expected Monthly Salary (Formatted India)"

        # 3. CURRENT ANNUAL CTC
        if category == SemanticFieldCategory.CURRENT_ANNUAL_CTC:
            if is_international:
                if is_numeric_input or (max_length and max_length <= 15):
                    return "96000", "Current Annual CTC (Numeric Gulf)"
                return f"96,000 {local_curr}", "Current Annual CTC (Formatted Gulf)"
            else:
                if is_numeric_input or (max_length and max_length <= 15):
                    return "1200000", "Current Annual CTC (Numeric India)"
                return "12 LPA", "Current Annual CTC (LPA India)"

        # 4. EXPECTED ANNUAL CTC
        if category == SemanticFieldCategory.EXPECTED_ANNUAL_CTC:
            if is_international:
                if is_numeric_input or (max_length and max_length <= 15):
                    return "96000", "Expected Annual CTC (Numeric Gulf)"
                return f"96,000 {local_curr}", "Expected Annual CTC (Formatted Gulf)"
            else:
                if is_numeric_input or (max_length and max_length <= 15):
                    return "1500000", "Expected Annual CTC (Numeric India)"
                return "15 LPA", "Expected Annual CTC (LPA India)"

        # 5. GENERIC SALARY
        if category == SemanticFieldCategory.GENERIC_SALARY:
            if is_international:
                return "8000", "Standard Gulf Monthly Salary (8000)"
            return "15 LPA", "Standard India Annual CTC (15 LPA)"

        # 6. TOTAL & RELEVANT EXPERIENCE
        if category == SemanticFieldCategory.TOTAL_EXPERIENCE:
            if is_numeric_input or (max_length and max_length <= 5):
                return "5", "Total Experience (5 Years Numeric)"
            return "5+ Years", "Total Experience (5+ Years)"

        if category == SemanticFieldCategory.RELEVANT_EXPERIENCE:
            if is_numeric_input or (max_length and max_length <= 5):
                return "5", "Relevant Experience (5 Years Numeric)"
            return "5 Years", "Relevant Experience (5 Years)"

        # 7. NOTICE PERIOD
        if category == SemanticFieldCategory.NOTICE_PERIOD:
            if is_numeric_input or (max_length and max_length <= 5):
                return "0", "Notice Period (0 Days - Immediate)"
            return "Immediate (Serving Notice)", "Notice Period (Immediate)"

        # 8. CURRENT & PREVIOUS COMPANY
        if category == SemanticFieldCategory.CURRENT_COMPANY:
            return "Freelance / Self-Employed (Senior Full Stack Developer)", "Current Employer"

        if category == SemanticFieldCategory.PREVIOUS_COMPANY:
            return "Technovert Solutions", "Previous Employer"

        if category == SemanticFieldCategory.CURRENT_DESIGNATION:
            return "Senior Full Stack Developer", "Current Designation"

        # 9. CONTACT & IDENTITY
        if category == SemanticFieldCategory.CAPTCHA:
            return "", "CAPTCHA Security Challenge - Must not auto-populate (Requires candidate manual solution)"

        if category == SemanticFieldCategory.DATE_OF_BIRTH:
            if input_type in ["date", "datetime-local"]:
                return cand_p.get("dob_iso", "1999-11-19"), "Date of Birth (ISO YYYY-MM-DD)"
            return cand_p.get("dob_formatted", "19-11-1999"), "Date of Birth (DD-MM-YYYY)"

        if category == SemanticFieldCategory.PHONE_COUNTRY_CODE:
            # Strict rule: International -> +974 (Qatar); India -> +91
            # Candidate does NOT have a UAE number. NEVER return +971 (UAE)!
            target_cc = "+974" if is_international else "+91"
            return target_cc, f"Phone Country Code ({target_cc})"

        if category == SemanticFieldCategory.PHONE_NUMBER:
            return cand_p["mobile_number"], f"National Mobile Number ({cand_p['mobile_number']})"

        if category == SemanticFieldCategory.EMAIL_ADDRESS:
            return "mhaslaiabdur@gmail.com", "Verified Candidate Email"

        if category == SemanticFieldCategory.FULL_NAME:
            return cand_p.get("name", "Abdul Razzaque Shaikh"), "Verified Candidate Full Name"

        if category == SemanticFieldCategory.FIRST_NAME:
            return "Abdul Razzaque", "Candidate First Name"

        if category == SemanticFieldCategory.LAST_NAME:
            return "Shaikh", "Candidate Last Name"

        if category == SemanticFieldCategory.TERMS_ACCEPTANCE:
            return "true", "Candidate Agrees to Data Handling and Terms"

        if category == SemanticFieldCategory.RESUME_UPLOAD:
            target_res = cand_p.get("resume_filename", "Abdul_Razzaque_Qatar.pdf" if is_international else "Abdul_Razzaque_India.pdf")
            cand_p_file = os.path.join(os.path.dirname(__file__), target_res)
            return cand_p_file if os.path.exists(cand_p_file) else cand_p.get("resume_path", ""), "Candidate Tailored Resume Path"

        # 10. PROFILES & LINKS
        if category == SemanticFieldCategory.LINKEDIN_URL:
            return "https://www.linkedin.com/in/abdul-razzaque-fullstack/", "LinkedIn URL"

        if category == SemanticFieldCategory.GITHUB_URL:
            return "https://github.com/AbdulRazzaque", "GitHub URL"

        if category == SemanticFieldCategory.PORTFOLIO_URL:
            return "https://portfolio-website-one-rho-98.vercel.app/", "Portfolio URL"

        # 11. LOCATIONS & COUNTRY
        if category == SemanticFieldCategory.RESIDENTIAL_COUNTRY:
            return cand_p.get("country", "Qatar" if is_international else "India"), "Candidate Residential Country"

        if category == SemanticFieldCategory.RESIDENTIAL_LOCATION:
            res_val = cand_p.get("residential_address", "Kurla, Mumbai, Maharashtra, India")
            return res_val, "Verified Residential Address"

        if category == SemanticFieldCategory.PREFERRED_WORK_LOCATION:
            return "Qatar / Dubai / Remote" if is_international else cand_p.get("preferred_work_location", "Mumbai, India"), "Preferred Location"

        # 12. ESSAYS & SUMMARIES (Guaranteed length compliance)
        if category == SemanticFieldCategory.PROFESSIONAL_SUMMARY:
            full_summary = "Senior Full Stack Developer with 5+ years of production experience specializing in React.js, Next.js, Node.js, Express.js, TypeScript, PostgreSQL, and MongoDB. Proven track record architecting and scaling resilient web applications, enterprise platforms, and high-performance microservices."
            if max_length and max_length < len(full_summary):
                return full_summary[:max_length].rstrip(), f"Profile Summary (Trimmed to {max_length} chars)"
            return full_summary, "Professional Summary"

        if category == SemanticFieldCategory.COVER_LETTER:
            full_cover = "I am excited to bring 5+ years of full-stack engineering expertise with React.js, Next.js, Node.js, TypeScript, and cloud technologies to your engineering team. I deliver clean architecture, robust APIs, and scalable user interfaces that drive immediate business impact."
            if max_length and max_length < len(full_cover):
                return full_cover[:max_length].rstrip(), f"Cover Letter (Trimmed to {max_length} chars)"
            return full_cover, "Cover Letter"

        if category == SemanticFieldCategory.AGE:
            return "27", "Candidate Verified Age"

        if category == SemanticFieldCategory.MARITAL_STATUS:
            return "Single", "Candidate Verified Marital Status"

        if category == SemanticFieldCategory.NATIONALITY:
            return "Indian", "Candidate Verified Nationality"

        return "", "Unresolved Category"

    @classmethod
    def sanitize_and_validate_field(cls, 
                                     category: str, 
                                     current_value: str = None, 
                                     location_hint: str = "",
                                     max_length: Optional[int] = None,
                                     value: str = None) -> Tuple[bool, str, str]:
        """
        Validates if a populated field is semantically valid or contains data pollution.
        Returns: (is_valid, corrected_value, audit_reason)
        """
        val = ((current_value if current_value is not None else value) or "").strip()
        val_low = val.lower()

        # 1. SALARY FIELDS: Never allow essay summaries or skill paragraphs!
        if category in [
            SemanticFieldCategory.CURRENT_MONTHLY_SALARY, 
            SemanticFieldCategory.EXPECTED_MONTHLY_SALARY,
            SemanticFieldCategory.CURRENT_ANNUAL_CTC,
            SemanticFieldCategory.EXPECTED_ANNUAL_CTC,
            SemanticFieldCategory.GENERIC_SALARY
        ]:
            has_essay_words = any(w in val_low for w in ["developer", "react", "production experience", "node", "specializing", "bring 5+", "architecting"])
            is_too_long = len(val) > 30
            if has_essay_words or is_too_long:
                correct_val, _ = cls.get_candidate_value(category, location_hint=location_hint, max_length=max_length)
                return False, correct_val, f"DATA POLLUTION DETECTED: Professional summary found in salary field. Cleaned to '{correct_val}'."

        # 2. EXPERIENCE FIELDS: Never allow phone numbers or essays!
        if category in [SemanticFieldCategory.TOTAL_EXPERIENCE, SemanticFieldCategory.RELEVANT_EXPERIENCE]:
            if "@" in val or "77557982" in val or "7972694663" in val or len(val) > 20:
                correct_val, _ = cls.get_candidate_value(category, location_hint=location_hint, max_length=max_length)
                return False, correct_val, f"DATA POLLUTION DETECTED: Invalid content in experience field. Cleaned to '{correct_val}'."

        # 3. PHONE COUNTRY CODE: Never allow +971 for Qatar/International profile!
        if category == SemanticFieldCategory.PHONE_COUNTRY_CODE:
            cand_p = getCandidateProfileByJobLocation(location_hint)
            if cand_p["is_international"] and ("+971" in val or "971" in val):
                return False, "+974", "COUNTRY CODE ERROR: +971 detected in phone country code. Corrected to +974 (Qatar)."

        # 3.2 PHONE NUMBER: Ensure no leading country code prefix or cross-country contamination
        if category == SemanticFieldCategory.PHONE_NUMBER:
            cand_p = getCandidateProfileByJobLocation(location_hint)
            if cand_p["is_international"]:
                if "+91" in val or "7972694663" in val or "+974" in val or val.startswith("974"):
                    return False, cand_p["mobile_number"], f"PHONE NUMBER CORRECTION: Set to Qatar national number '{cand_p['mobile_number']}'"
            else:
                if val.startswith("+91") or val.startswith("91 "):
                    clean_phone = val.replace("+91", "").strip()
                    return False, clean_phone, f"PHONE NUMBER CORRECTION: Removed redundant +91 prefix -> '{clean_phone}'"

        # 3.5 CAPTCHA: Field must remain empty for manual user solution
        if category == SemanticFieldCategory.CAPTCHA:
            if val:
                return False, "", "CAPTCHA POLLUTION: Text found in CAPTCHA field. Field cleared for manual candidate verification."

        # 3.8 DATE OF BIRTH: Ensure DOB is populated with verified date
        if category == SemanticFieldCategory.DATE_OF_BIRTH:
            if not val or val in ["0", "none"]:
                dob_val, _ = cls.get_candidate_value(category, location_hint=location_hint)
                return False, dob_val, f"MISSING DOB: Populated with verified Date of Birth '{dob_val}'."

        # 4. MAX LENGTH COMPLIANCE:
        if max_length and len(val) > max_length:
            trimmed = val[:max_length].rstrip()
            return False, trimmed, f"MAXLENGTH VIOLATION: Value exceeded {max_length} chars. Trimmed."

        return True, val, "Field semantically valid."

    # Backward-compatibility alias
    validate_field_value = sanitize_and_validate_field

# Singleton instance
semantic_engine = SemanticFormEngine()
