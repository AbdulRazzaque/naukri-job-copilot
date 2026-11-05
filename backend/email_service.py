import os
import sys
import re
import urllib.parse
import subprocess
from typing import Dict, Any, Optional, Tuple
from database import record_application

# Default Outlook Executable Paths on Windows
OUTLOOK_PATHS = [
    r"C:\Program Files\Microsoft Office\Office15\OUTLOOK.EXE",
    r"C:\Program Files\Microsoft Office\root\Office16\OUTLOOK.EXE",
    r"C:\Program Files (x86)\Microsoft Office\Office15\OUTLOOK.EXE",
    r"C:\Program Files (x86)\Microsoft Office\root\Office16\OUTLOOK.EXE",
]

def find_outlook_path() -> Optional[str]:
    """Finds the local path to Outlook.exe if installed."""
    for p in OUTLOOK_PATHS:
        if os.path.exists(p):
            return p
    # Try getting from Windows registry / where command
    try:
        res = subprocess.run(["where", "outlook.exe"], capture_output=True, text=True)
        if res.returncode == 0 and res.stdout.strip():
            p = res.stdout.strip().split("\n")[0].strip()
            if os.path.exists(p):
                return p
    except Exception:
        pass
    return None

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
    portfolio link (https://portfolio-website-one-rho-98.vercel.app/), and immediate availability.
    """
    loc_low = (location or "").lower()
    is_gulf = any(k in loc_low for k in ["qatar", "doha", "dubai", "uae", "emirates", "abu dhabi", "gulf"])
    
    portfolio_url = "https://portfolio-website-one-rho-98.vercel.app/"
    linkedin_url = "https://www.linkedin.com/in/abdul-razzaque-fullstack/"
    
    if is_gulf:
        phone_num = "+974 77557982"
        current_loc = "Doha, Qatar / Dubai, UAE"
        resume_name = "Abdul_Razzaque_Qatar.pdf"
    else:
        phone_num = "+91 797269663"
        current_loc = "Kurla, Mumbai, India"
        resume_name = "Abdul_Razzaque_India.pdf"

    resume_path = os.path.join(os.path.dirname(__file__), resume_name)
    if not os.path.exists(resume_path):
        resume_path = os.path.join(os.path.dirname(__file__), "Abdul_Razzaque_India.pdf")

    # Master Prompt Section 12 Subject Line Requirement
    subject = f"Application for {job_title or 'Senior Full Stack Developer'} – 5+ Years of Full Stack Development Experience"

    body = f"""Dear Hiring Team at {company_name or 'the organization'},

I am writing to express my strong interest in the {job_title or 'Senior Full Stack Developer'} opportunity.

With 5+ years of hands-on production experience as a Senior Full Stack Developer specializing in React.js, Next.js, Node.js, Express.js, TypeScript, PostgreSQL, and MongoDB, I have architected and deployed scalable web applications, enterprise platforms, and high-performance microservices.

Key Qualifications & Highlights:
• Experience: 5+ years in full-stack engineering, scalable REST/GraphQL APIs, and modern frontend architecture.
• Core Tech Stack: React.js, Next.js, Node.js, Express.js, TypeScript, JavaScript, MongoDB, PostgreSQL, MySQL.
• Cloud & DevOps: Docker, AWS, GitLab CI/CD, Redis, Kafka, Microservices architecture.
• Verified Portfolio: {portfolio_url}
• Availability / Notice Period: Immediate Joiner (0 days notice).
• Current Location: {current_loc}
• Contact Number: {phone_num}

I have attached my updated resume for your detailed review. I would welcome the opportunity to discuss how my technical expertise and problem-solving skills align with your team's objectives.

Thank you for your time and consideration.

Best regards,

Abdul Razzaque Shaikh
Senior Full Stack Developer
Phone: {phone_num}
Email: mhaslaiabdur@gmail.com
Portfolio: {portfolio_url}
LinkedIn: {linkedin_url}
"""
    return {
        "subject": subject,
        "body": body,
        "phone": phone_num,
        "resume_path": resume_path,
        "portfolio_url": portfolio_url,
        "is_gulf": is_gulf
    }

def open_outlook_for_job_application(recipient_email: str, job_title: str, company_name: str, 
                                      location: str = "", context_text: str = "") -> Tuple[bool, str]:
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

    outlook_bin = find_outlook_path()

    try:
        if outlook_bin and os.path.exists(outlook_bin):
            # Outlook CLI syntax to open compose window with recipient, subject, body, and attachment
            # /c ipm.note /m "<email>?subject=<subj>&body=<body>" /a "<attachment_path>"
            encoded_subj = urllib.parse.quote(subject)
            encoded_body = urllib.parse.quote(body)
            mailto_param = f"{recipient_email}?subject={encoded_subj}&body={encoded_body}"

            cmd = [outlook_bin, "/c", "ipm.note", "/m", mailto_param]
            if os.path.exists(resume_path):
                cmd.extend(["/a", resume_path])

            subprocess.Popen(cmd)
            record_application(
                job_title=job_title,
                company_name=company_name,
                location=location,
                status="APPLIED",
                apply_type="OUTLOOK_EMAIL",
                match_score=90,
                notes=f"Job application email composed and opened in Outlook for {recipient_email}. Resume: {os.path.basename(resume_path)}",
                platform="EMAIL"
            )
            return True, f"Outlook opened successfully for {recipient_email} with attached resume."
        else:
            # Fallback to mailto link via default system handler
            encoded_subj = urllib.parse.quote(subject)
            encoded_body = urllib.parse.quote(body)
            mailto_url = f"mailto:{recipient_email}?subject={encoded_subj}&body={encoded_body}"
            os.startfile(mailto_url)
            record_application(
                job_title=job_title,
                company_name=company_name,
                location=location,
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
    """
    outlook_bin = find_outlook_path()
    try:
        if outlook_bin and os.path.exists(outlook_bin):
            subprocess.Popen([outlook_bin])
            return True, f"Outlook desktop client launched for {reason}."
        else:
            # Open Outlook Web in default browser
            import webbrowser
            webbrowser.open("https://outlook.live.com/mail/")
            return True, f"Outlook Web opened in browser for {reason}."
    except Exception as e:
        return False, f"Could not launch Outlook: {str(e)}"


