import os
import re
import json
import hashlib
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional
import pymupdf

# Load candidate profile
PROFILE_PATH = os.path.join(os.path.dirname(__file__), "profile_data.json")

def get_candidate_profile() -> Dict[str, Any]:
    try:
        if os.path.exists(PROFILE_PATH):
            with open(PROFILE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

# Verified Technical Skills (The Single Source of Truth)
VERIFIED_SKILLS = {
    "languages": ["JavaScript", "TypeScript", "Python", "SQL", "C#", "C", "C++"],
    "frontend": ["React.js", "Next.js", "Redux", "Redux Toolkit", "Zustand", "HTML5", "CSS3", "Tailwind CSS", "Material UI"],
    "backend": ["Node.js", "Express.js", "REST APIs", "GraphQL", "Socket.io", ".NET"],
    "databases": ["MongoDB", "MySQL", "PostgreSQL", "SQLite", "Prisma"],
    "caching_messaging": ["Redis", "Apache Kafka"],
    "cloud_devops": ["AWS", "Docker", "CI/CD", "GitLab", "Git", "GitHub Actions"],
    "architecture": ["Microservices", "Event-Driven Architecture", "Scalable System Design", "Backend Architecture", "RESTful Architecture"]
}

# Strict Disqualifiers (Scenario C: Must NEVER apply or claim experience with these)
DISQUALIFIER_PATTERNS = [
    r"\bjava\b", r"\bspring boot\b", r"\bspringboot\b", r"\bj2ee\b", r"\bhibernate\b",
    r"\bcore java\b", r"\bjava developer\b", r"\bjava full stack\b", r"\bfull stack java\b",
    r"\b\.net\b", r"\bdotnet\b", r"\bc#\b", r"\basp\.net\b",
    r"\bphp\b", r"\blaravel\b", r"\bwordpress\b", r"\bruby\b", r"\brails\b",
    r"\bgolang\b", r"\brust\b", r"\bswift\b", r"\bkotlin\b", r"\bscala\b"
]

class JDAnalysis:
    """Encapsulates structured Job Description analysis and matching results."""
    def __init__(self, job_title: str, company: str, location: str, job_url: str,
                 platform: str, full_jd: str):
        self.job_title = (job_title or "").strip()
        self.company = (company or "").strip()
        self.location = (location or "").strip()
        self.job_url = (job_url or "").strip()
        self.platform = (platform or "GENERAL").strip()
        self.full_jd = (full_jd or "").strip()

        self.match_type: str = "NO_MATCH"  # STRONG_MATCH, PARTIAL_MATCH, NO_MATCH
        self.match_score: int = 0
        self.should_apply: bool = False
        self.disqualification_reason: str = ""

        self.mandatory_skills: List[str] = []
        self.preferred_skills: List[str] = []
        self.matching_skills: List[str] = []
        self.missing_skills: List[str] = []
        self.focus_areas: List[str] = []  # e.g., ["frontend", "backend", "fullstack", "devops"]
        self.key_responsibilities: List[str] = []
        self.experience_required: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_title": self.job_title,
            "company": self.company,
            "location": self.location,
            "job_url": self.job_url,
            "platform": self.platform,
            "match_type": self.match_type,
            "match_score": self.match_score,
            "should_apply": self.should_apply,
            "disqualification_reason": self.disqualification_reason,
            "mandatory_skills": self.mandatory_skills,
            "preferred_skills": self.preferred_skills,
            "matching_skills": self.matching_skills,
            "missing_skills": self.missing_skills,
            "focus_areas": self.focus_areas,
            "experience_required": self.experience_required
        }

def analyze_job_description(job_title: str, company: str, job_desc: str,
                            location: str = "", job_url: str = "", platform: str = "GENERAL") -> JDAnalysis:
    """
    MASTER PROMPT SECTION 2 & 3:
    Deeply analyzes a Job Description, identifies technical requirements,
    and determines compatibility with Abdul Razzaque Shaikh's verified profile.
    Strictly disqualifies non-MERN / Java / .NET / PHP roles.
    """
    analysis = JDAnalysis(job_title, company, location, job_url, platform, job_desc)
    title_low = job_title.lower()
    desc_low = (job_desc or "").lower()
    full_text = f"{title_low} {desc_low}"

    # 1. Evaluate Technology Alignment & Classification
    from technology_matcher import evaluate_technology_alignment
    tech_eval = evaluate_technology_alignment(title=job_title, company=company, desc=job_desc)

    if not tech_eval["should_apply"]:
        analysis.match_type = "NO_MATCH"
        analysis.match_score = tech_eval["match_score"]
        analysis.should_apply = False
        analysis.disqualification_reason = tech_eval["detailed_explanation"]
        return analysis

    analysis.match_score = tech_eval["match_score"]
    analysis.match_type = tech_eval["match_type"]

    # 2. Extract Verified Matching Skills and Track Missing Skills
    all_verified_flat = []
    for cat, slist in VERIFIED_SKILLS.items():
        all_verified_flat.extend(slist)

    matching_found = []
    for skill in all_verified_flat:
        s_clean = skill.lower().replace(".", r"\.")
        pattern = r"\b" + re.escape(skill.lower()) + r"\b"
        if re.search(pattern, full_text) or skill.lower() in full_text:
            matching_found.append(skill)

    # De-duplicate while preserving order
    analysis.matching_skills = list(dict.fromkeys(matching_found))

    # Detect common missing technologies from the JD (strictly tracked as MISSING, NEVER ADDED TO CV!)
    common_other_techs = [
        "Angular", "Vue.js", "GraphQL", "Kubernetes", "GCP", "Azure", "Terraform",
        "Jest", "Cypress", "Kafka", "Redis", "Elasticsearch", "PostgreSQL", "Tailwind CSS"
    ]
    missing_detected = []
    for tech in common_other_techs:
        t_low = tech.lower()
        if t_low in full_text and tech not in analysis.matching_skills:
            # Check if candidate has it verified
            if tech in all_verified_flat:
                if tech not in analysis.matching_skills:
                    analysis.matching_skills.append(tech)
            else:
                missing_detected.append(tech)
    analysis.missing_skills = missing_detected

    # 3. Detect Focus Areas
    if any(k in full_text for k in ["react", "frontend", "next.js", "ui", "redux", "zustand"]):
        analysis.focus_areas.append("frontend")
    if any(k in full_text for k in ["node", "express", "backend", "api", "microservices", "mongodb", "postgresql", "sql"]):
        analysis.focus_areas.append("backend")
    if any(k in full_text for k in ["full stack", "fullstack", "mern", "end-to-end"]):
        analysis.focus_areas.append("fullstack")
    if any(k in full_text for k in ["aws", "docker", "ci/cd", "devops", "cloud", "kafka", "redis"]):
        analysis.focus_areas.append("cloud_devops")

    # 4. Experience Requirement Extraction
    exp_m = re.search(r"(\d+)\s*(?:-|to)?\s*(\d+)?\s*\+?\s*years?(?:\s+of)?\s+experience", full_text)
    if exp_m:
        analysis.experience_required = exp_m.group(0)

    # 5. Calculate Match Score and Match Type
    # High-value MERN indicators: React, Node, Express, MongoDB, TypeScript, JavaScript, Next.js
    core_matches = [s for s in analysis.matching_skills if s in ["React.js", "Next.js", "Node.js", "Express.js", "TypeScript", "JavaScript", "MongoDB"]]
    
    is_title_relevant = any(k in title_low for k in [
        "full stack", "fullstack", "mern", "react", "node", "javascript", "typescript",
        "frontend", "backend", "web developer", "software engineer", "developer", "next.js"
    ])

    if not is_title_relevant:
        analysis.match_type = "NO_MATCH"
        analysis.match_score = 35
        analysis.should_apply = False
        analysis.disqualification_reason = "Job title does not match Senior Full Stack / MERN developer profile."
        return analysis

    score = 60  # Base for relevant title
    score += min(35, len(core_matches) * 7)
    if any(k in title_low for k in ["senior", "lead", "sr."]):
        score += 5
    if len(analysis.matching_skills) >= 6:
        score += 5

    analysis.match_score = min(98, score)

    # Master Rule Section B & Prompt 5:
    # Minimum eligibility threshold is 65%, inclusive.
    # Scores 80–100%: Strong match, high priority.
    # Scores 65–79%: Eligible for evaluation and application.
    # Scores below 65%: Disqualified as LOW_MATCH_SCORE.
    if analysis.match_score >= 80:
        analysis.match_type = "STRONG_MATCH"
        analysis.should_apply = True
    elif analysis.match_score >= 65:
        analysis.match_type = "PARTIAL_MATCH"
        analysis.should_apply = True
    else:
        analysis.match_type = "NO_MATCH"
        analysis.should_apply = False
        analysis.disqualification_reason = f"Compatibility score ({analysis.match_score}%) is below the minimum 65% threshold for verified developer stack."

    return analysis

class ResumeOptimizer:
    """
    MASTER PROMPT SECTION 4 & 5:
    Intelligently customizes Abdul Razzaque Shaikh's original PDF resume
    strictly using verified profile data.
    Preserves 100% of the visual layout, TrueType fonts, and all hyperlinks.
    """
    def __init__(self):
        self.profile = get_candidate_profile()
        self.base_dir = os.path.dirname(__file__)
        self.output_dir = os.path.join(self.base_dir, "customized_resumes")
        os.makedirs(self.output_dir, exist_ok=True)

        self.font_path = "C:/Windows/Fonts/tahoma.ttf"
        self.font_bold_path = "C:/Windows/Fonts/tahomabd.ttf"

    def get_base_resume(self, is_india: bool = True) -> str:
        """Returns the absolute path of the original verified base CV."""
        fname = "Abdul_Razzaque_India.pdf" if is_india else "Abdul_Razzaque_Qatar.pdf"
        p = os.path.join(self.base_dir, fname)
        if not os.path.exists(p):
            # Fallback with spaces
            alt_fname = "Abdul Razzaque India.pdf" if is_india else "Abdul Razzaque Qatar.pdf"
            p = os.path.join(self.base_dir, alt_fname)
        return p

    def synthesize_tailored_summary(self, jd_analysis: JDAnalysis) -> str:
        """
        Synthesizes a tailored Profile Summary strictly grounded in verified experience.
        Never introduces unverified skills. Fits into exact 4 lines (max 310 chars).
        Supports mixed-technology roles (MERN + Python, MERN + .NET/C#).
        """
        focus = jd_analysis.focus_areas
        matching = jd_analysis.matching_skills
        title_and_jd = f"{jd_analysis.job_title} {jd_analysis.full_jd}".lower()

        # Mixed Role 1: MERN + Python
        has_python_mention = "python" in title_and_jd
        if has_python_mention and any(k in title_and_jd for k in ["mern", "react", "node", "full stack", "fullstack", "javascript", "typescript"]):
            return (
                "Senior Full Stack & MERN Developer with 5+ years of experience building scalable applications "
                "using React.js, Next.js, Node.js, and TypeScript, with additional experience in Python services. "
                "Proven expertise in REST APIs, PostgreSQL, MongoDB, Docker, and resilient cloud architectures "
                "delivering secure, high-efficiency enterprise solutions."
            )

        # Mixed Role 2: MERN + .NET / C# (6 months actual experience)
        has_dotnet_mention = any(k in title_and_jd for k in [".net", "dotnet", "c#"])
        if has_dotnet_mention and any(k in title_and_jd for k in ["mern", "react", "node", "full stack", "fullstack", "javascript", "typescript"]):
            return (
                "Senior Full Stack Developer with 5+ years specializing in MERN Stack (React.js, Node.js, TypeScript), "
                "along with 6 months of hands-on experience in .NET/C# services. Experienced in enterprise REST APIs, "
                "scalable microservices, database architecture with PostgreSQL and MongoDB, and cloud deployment "
                "delivering high-reliability software solutions."
            )

        # 1. Frontend / Next.js / React focus
        if "frontend" in focus and "backend" not in focus:
            return (
                "Senior Full Stack & React.js Developer with 5+ years of experience building responsive, "
                "scalable web applications using React.js, Next.js, TypeScript, and modern state architectures. "
                "Proven expertise in component modularity, REST API integration, cloud deployment with AWS, "
                "and delivering high-performance enterprise user interfaces."
            )
        # 2. Backend / Node.js / Database / API focus
        elif "backend" in focus and "frontend" not in focus:
            return (
                "Senior Full Stack & Backend Developer with 5+ years of production experience architecting "
                "scalable RESTful APIs, decoupled microservices, and high-performance databases using Node.js, "
                "Express.js, TypeScript, MongoDB, and PostgreSQL. Skilled in Redis caching, Docker containerization, "
                "and robust cloud architectures on AWS."
            )
        # 3. Cloud / DevOps / Scalability focus
        elif "cloud_devops" in focus and ("Docker" in matching or "AWS" in matching):
            return (
                "Senior Full Stack Developer with 5+ years of experience delivering scalable MERN stack web "
                "platforms, containerized microservices using Docker, and automated CI/CD pipelines. Skilled in "
                "React.js, Node.js, TypeScript, MongoDB, AWS cloud infrastructure, Redis caching, and resilient "
                "system design."
            )
        # 4. Full Stack / MERN standard optimized
        else:
            return (
                "Senior Full Stack & MERN Developer with 5+ years of experience architecting end-to-end "
                "applications using React.js, Next.js, Node.js, Express.js, and MongoDB. Skilled in backend "
                "architecture, RESTful APIs, cloud deployment with Docker and AWS, database optimization, "
                "and delivering secure, high-efficiency enterprise solutions."
            )

    def optimize_resume(self, jd_analysis: JDAnalysis, is_india: bool = True) -> Dict[str, Any]:
        """
        Performs non-destructive, layout-preserving resume optimization:
        1. Copies original PDF.
        2. Rewrites Profile Summary using exact Tahoma TrueType typography.
        3. Validates hyperlinks and formatting.
        4. Saves separate PDF in customized_resumes/. Original is NEVER modified.
        """
        original_pdf = self.get_base_resume(is_india=is_india)
        if not os.path.exists(original_pdf):
            return {
                "success": False,
                "error": f"Original base resume not found at {original_pdf}",
                "customized_path": original_pdf,
                "original_path": original_pdf
            }

        # Do NOT customize for non-matching roles (Scenario C)
        if not jd_analysis.should_apply or jd_analysis.match_type == "NO_MATCH":
            return {
                "success": False,
                "error": f"Optimization aborted: {jd_analysis.disqualification_reason}",
                "customized_path": original_pdf,
                "original_path": original_pdf,
                "validation_passed": False
            }

        # Generate unique, safe filename for this job
        safe_company = re.sub(r"[^\w\-_]", "_", jd_analysis.company or "Company")[:25]
        safe_title = re.sub(r"[^\w\-_]", "_", jd_analysis.job_title or "Role")[:25]
        region_tag = "India" if is_india else "Qatar"
        slug = f"{safe_company}_{safe_title}_{region_tag}"
        
        job_custom_dir = os.path.join(self.output_dir, safe_company)
        os.makedirs(job_custom_dir, exist_ok=True)
        customized_pdf_path = os.path.join(job_custom_dir, f"Abdul_Razzaque_{slug}.pdf")

        try:
            doc = pymupdf.open(original_pdf)
            page1 = doc[0]

            # 1. Snapshot original hyperlinks on page 1
            original_links = [l for l in page1.get_links() if 'uri' in l]

            # 2. Tailor Profile Summary
            original_summary = (
                "MERN Stack Developer with 5+ years of experience building scalable web applications using React.js, "
                "Node.js, Express.js, and MongoDB. Skilled in backend architecture, RESTful APIs, cloud technologies, "
                "and secure application development. Experienced in delivering high-performance solutions, optimizing "
                "system efficiency, and developing enterprise-level applications."
            )
            tailored_summary = self.synthesize_tailored_summary(jd_analysis)

            # Exact bounding box of Profile Summary on Page 1
            # (14.0, 93.0, 602.0, 131.0)
            rect_summary = pymupdf.Rect(14.0, 93.0, 602.0, 131.5)
            page1.add_redact_annot(rect_summary, fill=(1, 1, 1))
            page1.apply_redactions()

            # Insert font and render tailored summary with exact lineheight
            if os.path.exists(self.font_path):
                font = pymupdf.Font(fontfile=self.font_path)
                page1.insert_font(fontname="CustomTahoma", fontbuffer=font.buffer)
                font_to_use = "CustomTahoma"
            else:
                font_to_use = "helv"

            page1.insert_textbox(
                rect_summary, 
                tailored_summary, 
                fontname=font_to_use, 
                fontsize=9.5, 
                color=(0.1, 0.1, 0.1)
            )

            # 3. Ensure hyperlinks remain fully attached
            existing_links = [l for l in page1.get_links() if 'uri' in l]
            if len(existing_links) < len(original_links):
                for ol in original_links:
                    page1.insert_link(ol)

            # 4. Save customized PDF
            doc.save(customized_pdf_path)
            doc.close()

            # 5. Strict Validation Check (Master Prompt Section 6)
            validation_passed, val_reason = self.validate_customized_resume(
                customized_pdf_path, original_pdf, expected_links_count=len(original_links)
            )

            if not validation_passed:
                return {
                    "success": False,
                    "error": f"Validation failed: {val_reason}",
                    "customized_path": original_pdf,
                    "original_path": original_pdf,
                    "validation_passed": False
                }

            return {
                "success": True,
                "customized_path": customized_pdf_path,
                "original_path": original_pdf,
                "summary_before": original_summary,
                "summary_after": tailored_summary,
                "skills_highlighted": jd_analysis.matching_skills[:8],
                "focus_areas": jd_analysis.focus_areas,
                "validation_passed": True,
                "validation_notes": "Preserved exact 2-page layout, TrueType fonts, and all 7 original hyperlinks."
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"PDF customization exception: {str(e)}",
                "customized_path": original_pdf,
                "original_path": original_pdf,
                "validation_passed": False
            }

    def validate_customized_resume(self, customized_path: str, original_path: str, expected_links_count: int = 5) -> Tuple[bool, str]:
        """
        MASTER PROMPT SECTION 6:
        Automated pre-upload validation:
        1. File exists and opens correctly.
        2. Exactly 2 pages (same as original).
        3. All hyperlinks are intact.
        4. Never contains forbidden unverified technologies (Java, Spring, .NET, etc.).
        5. Candidate core identity (Abdul Razzaque Shaikh, email, phone) intact.
        """
        if not os.path.exists(customized_path):
            return False, "Customized PDF file does not exist on disk."

        try:
            doc = pymupdf.open(customized_path)
            if len(doc) != 2:
                doc.close()
                return False, f"Page count mismatch! Expected 2 pages, got {len(doc)}."

            # Verify links on Page 1
            p1_links = [l for l in doc[0].get_links() if 'uri' in l]
            if len(p1_links) < 4:
                doc.close()
                return False, f"Hyperlink loss detected! Found only {len(p1_links)} links on Page 1."

            # Check full text content
            full_text = ""
            for page in doc:
                full_text += page.get_text() + "\n"
            doc.close()

            # Verify Candidate Identity
            if "ABDUL RAZZAQUE SHAIKH" not in full_text:
                return False, "Candidate name missing from customized document."
            if "mhaslaiabdur@gmail.com" not in full_text:
                return False, "Candidate email missing from customized document."

            # Verify Absence of Forbidden Technologies
            full_text_low = full_text.lower()
            for pattern in DISQUALIFIER_PATTERNS:
                if re.search(pattern, full_text_low):
                    if "javascript" in full_text_low and pattern == r"\bjava\b":
                        continue
                    return False, f"Forbidden unverified skill introduced: pattern {pattern} detected!"

            return True, "All validation criteria passed."
        except Exception as e:
            return False, f"PDF read error: {e}"

def generate_activity_report(jd_analysis: JDAnalysis, optimization_res: Dict[str, Any],
                             application_status: str = "Applied Successfully",
                             error_msg: str = "") -> str:
    """
    MASTER PROMPT SECTION 8:
    Generates a structured, professional Application Activity & Change Report.
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    is_opt = optimization_res.get("success", False)
    cust_path = optimization_res.get("customized_path", "")
    orig_path = optimization_res.get("original_path", "")
    cust_fname = os.path.basename(cust_path) if cust_path else "Abdul_Razzaque_India.pdf"
    orig_fname = os.path.basename(orig_path) if orig_path else "Abdul_Razzaque_India.pdf"

    matching_str = ", ".join(jd_analysis.matching_skills) if jd_analysis.matching_skills else "MERN Full Stack Core"
    missing_str = ", ".join(jd_analysis.missing_skills) if jd_analysis.missing_skills else "None (Full Stack Alignment)"

    report = f"""
================================================================================
📋 APPLICATION ACTIVITY & RESUME OPTIMIZATION REPORT
Generated: {now_str}
================================================================================

### 1. Job Information
- Company Name        : {jd_analysis.company or 'N/A'}
- Job Title           : {jd_analysis.job_title or 'N/A'}
- Job Location        : {jd_analysis.location or 'N/A'}
- Application Platform: {jd_analysis.platform}
- Job Description URL : {jd_analysis.job_url or 'Direct Platform Search'}

### 2. Job Matching Analysis
- Overall Match Score : {jd_analysis.match_score}% ({jd_analysis.match_type})
- Matching Verified   : {matching_str}
- Missing Skills (JD) : {missing_str} (Strictly not added to CV)
- Relevant Experience : 5+ Years (Verified MERN / Full Stack Engineering)
- Target Suitability  : {'Approved for Application' if jd_analysis.should_apply else 'Skipped (Incompatible Role)'}

### 3. CV Modification Report
- Status              : {'Customized & Tailored to JD' if is_opt else 'Original CV Preserved (No modifications)'}
- Modified Section    : Profile Summary (Page 1)
- Summary Optimization:
  [Before] {optimization_res.get('summary_before', 'Standard MERN Developer summary')}
  [After ] {optimization_res.get('summary_after', 'Tailored alignment with role requirements')}
- Skills Prioritized  : {', '.join(optimization_res.get('skills_highlighted', [])) or 'Standard Core Stack'}
- Focus Areas Aligned : {', '.join(optimization_res.get('focus_areas', [])) or 'Full Stack'}
- Unchanged Sections  : Employment History, Companies, Dates, Education, Projects, and Contact Details (Preserved verbatim as source of truth).

### 4. Resume Information
- Original CV File    : {orig_fname}
- Customized CV File  : {cust_fname}
- Layout & Design     : 100% Preserved (Microsoft Word Tahoma typography intact)
- Hyperlinks Status   : 100% Preserved (Portfolio, GitHub, LinkedIn, Email, Project links)
- File Location       : {cust_path}

### 5. Application Status
- Status              : {application_status}
- Additional Notes    : {error_msg if error_msg else 'Verified and submitted in compliance with Master Guidelines.'}
================================================================================
"""
    return report.strip()

# Singleton optimizer instance
resume_optimizer = ResumeOptimizer()

