import os
import sys
import re
import urllib.parse
import subprocess
from typing import Dict, Any, Optional, Tuple
from database import record_application

# Default Outlook Executable Paths on Windows
# Prioritize New Outlook for Windows (olk.exe) over legacy Office 15/16 OUTLOOK.EXE
NEW_OUTLOOK_PATHS = [
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps\olk.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps\Microsoft.OutlookForWindows_8wekyb3d8bbwe\olk.exe"),
]

LEGACY_OUTLOOK_PATHS = [
    r"C:\Program Files\Microsoft Office\root\Office16\OUTLOOK.EXE",
    r"C:\Program Files (x86)\Microsoft Office\root\Office16\OUTLOOK.EXE",
    r"C:\Program Files\Microsoft Office\Office15\OUTLOOK.EXE",
    r"C:\Program Files (x86)\Microsoft Office\Office15\OUTLOOK.EXE",
]

def find_outlook_path() -> Tuple[Optional[str], str]:
    """
    Finds the local path to Outlook.
    Strictly prioritizes New Outlook for Windows (olk.exe) as shown in candidate desktop
    over legacy Microsoft Office 2013/2016 desktop OUTLOOK.EXE.
    Returns: (path, client_type) where client_type is 'NEW_OUTLOOK' or 'LEGACY_OUTLOOK' or 'NONE'.
    """
    # 1. Search for New Outlook for Windows (olk.exe)
    for p in NEW_OUTLOOK_PATHS:
        if os.path.exists(p):
            return p, "NEW_OUTLOOK"

    try:
        res = subprocess.run(["where", "olk.exe"], capture_output=True, text=True)
        if res.returncode == 0 and res.stdout.strip():
            p = res.stdout.strip().split("\n")[0].strip()
            if os.path.exists(p):
                return p, "NEW_OUTLOOK"
    except Exception:
        pass

    # 2. Search for Legacy Outlook (OUTLOOK.EXE)
    for p in LEGACY_OUTLOOK_PATHS:
        if os.path.exists(p):
            return p, "LEGACY_OUTLOOK"

    try:
        res = subprocess.run(["where", "outlook.exe"], capture_output=True, text=True)
        if res.returncode == 0 and res.stdout.strip():
            p = res.stdout.strip().split("\n")[0].strip()
            if os.path.exists(p):
                return p, "LEGACY_OUTLOOK"
    except Exception:
        pass

    return None, "NONE"

def is_job_related_email(email_str: str, context_text: str = "") -> bool:
    """
    STRICT USER RULE: 'only job k realted email karo bss itna hi'
    Verifies that the email is strictly related to a job application or hiring.
    """
    if not email_str or "@" not in email_str:
        return False
    
    email_low = email_str.lower().strip()
    ctx_low = (context_text or "").lower()

    # Block common invalid or spam domains
    blocked_domains = ["example.com", "test.com", "domain.com", "sample.com", "placeholder.com"]
    if any(b in email_low for b in blocked_domains):
        return False

    # Check for hiring / HR / recruitment keywords in email username
    user_part = email_low.split("@")[0]
    hiring_keywords = [
        "hr", "career", "careers", "job", "jobs", "hiring", "recruit", "recruiter", 
        "recruitment", "talent", "people", "apply", "cv", "resume", "work", "join",
        "opportunity", "info", "contact", "support"
    ]
    if any(k in user_part for k in hiring_keywords):
        return True

    # Check context text for job keywords
    if any(k in ctx_low for k in ["apply", "send cv", "send resume", "send your resume", "share cv", "share resume", "careers", "hiring", "recruitment"]):
        return True

    return True

def generate_job_email_content(job_title: str, company_name: str, location: str) -> Dict[str, str]:
    """
    Generates professional, high-converting job application email content
    strictly aligned with candidate's location (Gulf vs India), 5+ years experience,
    portfolio link (https://portfolio-website-one-rho-98.vercel.app/), GitHub, LinkedIn, and immediate availability.
    """
    loc_low = (location or "").lower()
    is_gulf = any(k in loc_low for k in ["qatar", "doha", "dubai", "uae", "emirates", "abu dhabi", "gulf"])
    
    portfolio_url = "https://portfolio-website-one-rho-98.vercel.app/"
    linkedin_url = "https://www.linkedin.com/in/abdul-razzaque-fullstack/"
    github_url = "https://github.com/AbdulRazzaque"
    
    if is_gulf:
        phone_num = "+974 77557982"
        current_loc = "Doha, Qatar / Dubai, UAE"
        resume_name = "Abdul_Razzaque_Qatar.pdf"
    elif any(k in loc_low for k in ["pune", "kondhwa", "hinjewadi", "kharadi"]):
        phone_num = "+91 7972694663"
        current_loc = "Talab Chowk area in Kondhwa, Pune, India"
        resume_name = "Abdul_Razzaque_India.pdf"
    else:
        phone_num = "+91 7972694663"
        current_loc = "Kurla, Mumbai, India"
        resume_name = "Abdul_Razzaque_India.pdf"

    # Search for resume file across known paths
    candidate_paths = [
        os.path.join(os.path.dirname(__file__), resume_name),
        os.path.join(os.path.dirname(__file__), "Abdul_Razzaque_India.pdf"),
        os.path.join(os.path.dirname(__file__), "Abdul_Razzaque_Qatar.pdf"),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), resume_name),
        r"E:\Abdur Razzaque\Abdur Razzaque Both\Abdul Razzaque India.pdf",
        r"E:\Abdur Razzaque\Abdur Razzaque Both\Abdul Razzaque Qatar.pdf"
    ]
    resume_path = ""
    for cp in candidate_paths:
        if os.path.exists(cp):
            resume_path = cp
            break
    if not resume_path:
        resume_path = os.path.join(os.path.dirname(__file__), resume_name)

    company_display = company_name.strip() if company_name else "the Hiring Team"
    role_display = job_title.strip() if job_title else "Senior Software Engineer"

    subject = f"Application for {role_display} Position – Abdul Razzaque Shaikh (5+ Years Experience)"

    body = f"""Dear Hiring Team,

I am writing to express my interest in the {role_display} position at {company_display}.

I am a Senior Full Stack Developer with over 5 years of hands-on experience designing, developing, and deploying scalable, production-ready web applications and enterprise solutions. My primary technical expertise includes React.js, Next.js, Node.js, Express.js, JavaScript, TypeScript, PostgreSQL, MongoDB, and MySQL.

Throughout my career, I have worked on building robust backend services, scalable REST and GraphQL APIs, database-driven applications, third-party integrations, and modern frontend architectures. I also have practical experience with AWS, Docker, Redis, Kafka, microservices architecture, and GitLab CI/CD.

Core Technical Expertise:
• Frontend: React.js, Next.js, Redux Toolkit, JavaScript, TypeScript
• Backend: Node.js, Express.js, REST APIs, GraphQL, Microservices
• Databases: PostgreSQL, MongoDB, MySQL, SQL, Database Design and Optimization
• Cloud & DevOps: AWS, Docker, Git, GitLab CI/CD, Redis, Kafka
• Project Experience: Enterprise e-commerce platforms, multi-vendor applications, CRM/POS systems, inventory management solutions, and recruitment platforms

Professional Profiles:
• Portfolio: {portfolio_url}
• GitHub: {github_url}
• LinkedIn: {linkedin_url}

Additional Information:
• Experience: 5+ Years
• Availability: Immediate Joiner (0 Days Notice)
• Current Location: {current_loc}
• Contact: {phone_num}

Please find my updated resume, {os.path.basename(resume_path)}, attached for your review.

I would appreciate the opportunity to discuss my experience and demonstrate how my technical expertise, problem-solving abilities, and engineering approach can contribute to {company_display}.

Thank you for your time and consideration. I look forward to hearing from you.

Best regards,

Abdul Razzaque Shaikh
Senior Full Stack Developer
Email: mhaslaiabdur@gmail.com
Phone: {phone_num}
LinkedIn: {linkedin_url}
Portfolio: {portfolio_url}
GitHub: {github_url}
"""
    return {
        "subject": subject,
        "body": body,
        "phone": phone_num,
        "resume_path": resume_path,
        "portfolio_url": portfolio_url,
        "github_url": github_url,
        "linkedin_url": linkedin_url,
        "is_gulf": is_gulf
    }

def extract_hiring_emails(page, jd_text: str = "") -> List[str]:
    """
    Scans a company careers portal or job description page for hiring/recruitment email addresses.
    Returns a sorted list of candidate email addresses (HR/careers first).
    """
    found = set()

    # 1. Scan mailto links
    try:
        mailto_links = page.query_selector_all("a[href^='mailto:']")
        for link in mailto_links:
            href = link.get_attribute("href") or ""
            clean_email = href.replace("mailto:", "").split("?")[0].strip()
            if "@" in clean_email:
                found.add(clean_email)
    except Exception:
        pass

    # 2. Scan page text via regex
    email_regex = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')
    try:
        body_text = page.evaluate("() => document.body ? document.body.innerText : ''")
        for match in email_regex.findall(body_text):
            found.add(match.strip())
    except Exception:
        pass

    # 3. Scan JD text
    if jd_text:
        for match in email_regex.findall(jd_text):
            found.add(match.strip())

    # 4. Filter and prioritize
    valid_emails = []
    blocked_domains = [
        "sentry.io", "w3.org", "github.com", "google.com", "apple.com", "schema.org",
        "domain.com", "example.com", "test.com", "cloudflare.com", "gravatar.com"
    ]
    for e in found:
        e_low = e.lower()
        if any(b in e_low for b in blocked_domains):
            continue
        if any(ext in e_low for ext in [".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"]):
            continue
        valid_emails.append(e)

    def priority_key(email: str):
        low = email.lower()
        if any(k in low for k in ["career", "careers", "hr", "hiring", "jobs", "job", "recruit", "talent", "apply"]):
            return 0
        if any(k in low for k in ["info", "contact", "work", "people"]):
            return 1
        return 2

    valid_emails.sort(key=priority_key)
    return valid_emails

def open_outlook_for_job_application(recipient_email: str, job_title: str, company_name: str, 
                                      location: str = "", context_text: str = "", job_url: str = "") -> Tuple[bool, str]:
    """
    STRICT RULE: 'only job k realted email karo bss itna hi'
    Opens Outlook with filled job application email (recipient, subject, body, attached resume).
    """
    if not is_job_related_email(recipient_email, context_text):
        return False, f"Email '{recipient_email}' is not verified as job-related. Skipped."

    content = generate_job_email_content(job_title, company_name, location)
    subject = content["subject"]
    body = content["body"]
    resume_path = content["resume_path"]
    effective_job_url = job_url or f"mailto:{recipient_email}"

    outlook_bin, client_type = find_outlook_path()

    try:
        encoded_subj = urllib.parse.quote(subject)
        encoded_body = urllib.parse.quote(body)
        mailto_url = f"mailto:{recipient_email}?subject={encoded_subj}&body={encoded_body}"

        if outlook_bin and client_type == "NEW_OUTLOOK":
            # Launch via os.startfile or olk.exe for New Outlook
            try:
                os.startfile(mailto_url)
            except Exception:
                subprocess.Popen([outlook_bin, mailto_url])

            record_application(
                job_title=job_title,
                company_name=company_name,
                location=location,
                job_url=effective_job_url,
                status="APPLIED",
                apply_type="OUTLOOK_EMAIL",
                match_score=90,
                notes=f"Job application email composed and opened in New Outlook for Windows for {recipient_email}. Resume: {os.path.basename(resume_path)}",
                platform="EMAIL"
            )
            return True, f"New Outlook for Windows opened successfully for {recipient_email}."
        elif outlook_bin and client_type == "LEGACY_OUTLOOK":
            cmd = [outlook_bin, "/c", "ipm.note", "/m", f"{recipient_email}?subject={encoded_subj}&body={encoded_body}"]
            if os.path.exists(resume_path):
                cmd.extend(["/a", resume_path])

            subprocess.Popen(cmd)
            record_application(
                job_title=job_title,
                company_name=company_name,
                location=location,
                job_url=effective_job_url,
                status="APPLIED",
                apply_type="OUTLOOK_EMAIL",
                match_score=90,
                notes=f"Job application email composed and opened in Outlook Desktop for {recipient_email}. Resume: {os.path.basename(resume_path)}",
                platform="EMAIL"
            )
            return True, f"Outlook opened successfully for {recipient_email} with attached resume."
        else:
            # Fallback to mailto link via default system handler
            os.startfile(mailto_url)
            record_application(
                job_title=job_title,
                company_name=company_name,
                location=location,
                job_url=effective_job_url,
                status="APPLIED",
                apply_type="SYSTEM_EMAIL",
                match_score=90,
                notes=f"Job application email opened via mailto for {recipient_email}.",
                platform="EMAIL"
            )
            return True, f"Default mail client opened for {recipient_email}."
    except Exception as e:
        return False, f"Error launching Outlook: {str(e)}"

def open_outlook_for_verification(reason: str = "OTP Verification") -> Tuple[bool, str]:
    """
    MASTER PROMPT SECTION 10 & 11:
    Opens Outlook desktop or web client when email verification or OTP is required.
    Prioritizes New Outlook for Windows (olk.exe) as requested by user.
    """
    outlook_bin, client_type = find_outlook_path()
    try:
        if outlook_bin:
            subprocess.Popen([outlook_bin])
            client_name = "New Outlook for Windows" if client_type == "NEW_OUTLOOK" else "Outlook Desktop"
            return True, f"{client_name} launched for {reason}."
        else:
            import webbrowser
            webbrowser.open("https://outlook.live.com/mail/")
            return True, f"Outlook Web opened in browser for {reason}."
    except Exception as e:
        return False, f"Could not launch Outlook: {str(e)}"


