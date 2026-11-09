import re
from typing import Dict, Any, List, Tuple, Optional

# -----------------------------------------------------------------------------
# CANDIDATE TECHNOLOGY PROFILE (Source of Truth)
# -----------------------------------------------------------------------------
# Primary Professional Specialization:
# MERN Stack & JavaScript-based Full Stack Development (5+ years exp)
# Verified primary technologies:
# JavaScript, TypeScript, React.js, Next.js, Node.js, Express.js,
# MongoDB, MySQL, PostgreSQL, REST APIs, Full Stack Development
#
# Additional Technology Experience:
# - .NET / C#: 6 months of actual experience.
# - Python: Additional technical skill & experience documented in CV.
# - Java: Zero experience (Never invent, never claim).
# -----------------------------------------------------------------------------

PRIMARY_MERN_KEYWORDS = [
    "mern", "react", "react.js", "reactjs",
    "node", "node.js", "nodejs",
    "next", "next.js", "nextjs",
    "express", "express.js", "expressjs",
    "javascript", "typescript",
    "mongodb", "postgresql", "mysql", "rest api", "rest apis"
]

FULL_STACK_KEYWORDS = [
    "full stack", "fullstack", "full-stack", "software engineer",
    "software developer", "web developer", "frontend developer",
    "backend developer", "lead developer", "senior developer"
]

def classify_technologies(title: str, desc: str = "") -> Dict[str, Any]:
    """
    Classifies technologies mentioned in a job title and description into:
    1. Primary MERN / JS alignment
    2. Dedicated Specialist indicators (Python, .NET, Java, PHP, Ruby)
    3. Mixed-technology combinations
    """
    title_low = (title or "").lower().strip()
    desc_low = (desc or "").lower().strip()
    full_text = f"{title_low} {desc_low}"

    # 1. MERN / JS Detection
    has_mern_title = any(re.search(rf"\b{re.escape(k)}\b", title_low) for k in PRIMARY_MERN_KEYWORDS)
    has_mern_desc = any(re.search(rf"\b{re.escape(k)}\b", desc_low) for k in PRIMARY_MERN_KEYWORDS)
    has_fullstack_title = any(k in title_low for k in ["full stack", "fullstack", "full-stack"])

    # 2. Python Detection
    has_python_title = bool(re.search(r"\bpython\b", title_low))
    has_python_desc = bool(re.search(r"\bpython\b", desc_low))
    is_python_specialist_title = bool(re.search(
        r"\b(dedicated python|python developer|python backend|python engineer|senior python|python specialist|django developer|fastapi developer|flask developer)\b",
        title_low
    )) or (has_python_title and not (has_mern_title or has_fullstack_title))

    # 3. .NET / C# Detection
    has_dotnet_title = any(k in title_low for k in [".net", "dotnet", "c#", "asp.net"])
    has_dotnet_desc = any(k in desc_low for k in [".net", "dotnet", "c#", "asp.net"])
    is_dotnet_specialist_title = bool(re.search(
        r"\b(dedicated \.net|dedicated c#|\.net developer|dotnet developer|c# developer|asp\.net developer|senior \.net|senior c#|\.net core developer|\.net backend|c# backend)\b",
        title_low
    )) or (has_dotnet_title and not (has_mern_title or has_fullstack_title))

    # 4. Java Detection (Note: \bjava\b regex ensures 'javascript' is NEVER matched as 'java')
    has_java_title = bool(re.search(r"\bjava\b", title_low)) and not bool(re.search(r"\bjavascript\b", title_low))
    has_java_phrases_title = bool(re.search(r"\b(spring boot|springboot|j2ee|hibernate|core java)\b", title_low))
    has_java_desc = bool(re.search(r"\b(core java|spring boot|springboot|j2ee|hibernate|java microservices)\b", desc_low))
    
    is_java_specialist_title = (
        has_java_phrases_title or
        bool(re.search(r"\b(dedicated java|java developer|senior java|lead java|java backend|java engineer|spring boot developer|springboot developer|core java developer|java full stack|full stack java)\b", title_low)) or
        (has_java_title and not (has_mern_title or has_fullstack_title))
    )

    # 5. PHP / Ruby Detection
    is_php_ruby_specialist_title = bool(re.search(
        r"\b(php developer|laravel developer|wordpress developer|ruby developer|rails developer)\b",
        title_low
    )) and not (has_mern_title or has_fullstack_title)

    # 6. Mixed Role Detection
    # Roles that combine primary MERN/Full Stack with additional skills (.NET, Python, or secondary Java)
    is_mixed_role = False
    if (has_mern_title or has_fullstack_title or has_mern_desc):
        if has_python_title or has_python_desc or has_dotnet_title or has_dotnet_desc or (has_java_desc and not is_java_specialist_title):
            is_mixed_role = True

    return {
        "title_low": title_low,
        "has_mern_title": has_mern_title,
        "has_mern_desc": has_mern_desc,
        "has_fullstack_title": has_fullstack_title,
        "has_python_title": has_python_title,
        "has_python_desc": has_python_desc,
        "is_python_specialist_title": is_python_specialist_title,
        "has_dotnet_title": has_dotnet_title,
        "has_dotnet_desc": has_dotnet_desc,
        "is_dotnet_specialist_title": is_dotnet_specialist_title,
        "has_java_title": has_java_title,
        "has_java_desc": has_java_desc,
        "is_java_specialist_title": is_java_specialist_title,
        "is_php_ruby_specialist_title": is_php_ruby_specialist_title,
        "is_mixed_role": is_mixed_role
    }

def evaluate_technology_alignment(title: str, company: str = "", desc: str = "") -> Dict[str, Any]:
    """
    Evaluates technology stack alignment per Candidate Technology Profile & Flexible Job Matching rules:
    - APPLY for relevant mixed-technology roles (MERN + Python, MERN + .NET/C#, etc.)
    - SKIP dedicated specialist roles (Dedicated Python, Dedicated .NET, Dedicated Java)
    - If React.js, Node.js and MERN are central, evaluate positively even when Python, .NET or secondary Java are present.
    - If Python, Java or .NET is the central specialization, do NOT apply simply because JS is mentioned.
    """
    c = classify_technologies(title, desc)
    title_low = c["title_low"]

    # RULE 1: Dedicated Java Specialist -> SKIP
    if c["is_java_specialist_title"]:
        # Verify if MERN is actually primary and Java is only secondary
        if not (c["has_mern_title"] and not c["has_java_title"]):
            return {
                "should_apply": False,
                "match_score": 20,
                "match_type": "NO_MATCH",
                "reason_code": "PRIMARY_SPECIALIZATION_MISMATCH",
                "detailed_explanation": "Dedicated Java / Spring Boot specialist role. Candidate specializes strictly in MERN Stack and has no Java experience.",
                "is_mixed_technology": False,
                "additional_tech_noted": ["Java"]
            }

    # RULE 2: Dedicated .NET / C# Specialist -> SKIP
    if c["is_dotnet_specialist_title"]:
        # Verify if it's a mixed role where MERN/React/Node is primary
        if not (c["has_mern_title"] or (c["has_fullstack_title"] and c["has_mern_desc"])):
            return {
                "should_apply": False,
                "match_score": 30,
                "match_type": "NO_MATCH",
                "reason_code": "PRIMARY_SPECIALIZATION_MISMATCH",
                "detailed_explanation": "Dedicated .NET / C# specialist role. Candidate has 6 months of .NET experience, but primary specialization is MERN Stack / JavaScript Full Stack.",
                "is_mixed_technology": False,
                "additional_tech_noted": [".NET / C#"]
            }

    # RULE 3: Dedicated Python Specialist -> SKIP
    if c["is_python_specialist_title"]:
        # Verify if it's a mixed role where MERN/React/Node is primary
        if not (c["has_mern_title"] or (c["has_fullstack_title"] and c["has_mern_desc"])):
            return {
                "should_apply": False,
                "match_score": 35,
                "match_type": "NO_MATCH",
                "reason_code": "PRIMARY_SPECIALIZATION_MISMATCH",
                "detailed_explanation": "Dedicated Python specialist role. Candidate has additional Python experience, but primary specialization is MERN Stack / JavaScript Full Stack.",
                "is_mixed_technology": False,
                "additional_tech_noted": ["Python"]
            }

    # RULE 4: Dedicated PHP / Ruby Specialist -> SKIP
    if c["is_php_ruby_specialist_title"]:
        return {
            "should_apply": False,
            "match_score": 25,
            "match_type": "NO_MATCH",
            "reason_code": "PRIMARY_SPECIALIZATION_MISMATCH",
            "detailed_explanation": "Dedicated PHP / Ruby role. Candidate's primary specialization is MERN Stack / JavaScript Full Stack.",
            "is_mixed_technology": False,
            "additional_tech_noted": []
        }

    # RULE 5: Pure Java backend requirement in description with NO MERN alignment
    if c["has_java_desc"] and not (c["has_mern_title"] or c["has_mern_desc"]):
        return {
            "should_apply": False,
            "match_score": 20,
            "match_type": "NO_MATCH",
            "reason_code": "PRIMARY_SPECIALIZATION_MISMATCH",
            "detailed_explanation": "Job description requires pure Java/Spring Boot backend with no MERN/JavaScript alignment.",
            "is_mixed_technology": False,
            "additional_tech_noted": ["Java"]
        }

    # RULE 6: Mixed-Technology Roles (APPLY!)
    # Examples: MERN + Python, MERN + .NET / C#, React + Node.js + Python, React + Node.js + C#
    if c["is_mixed_role"]:
        additional_notes = []
        if c["has_python_title"] or c["has_python_desc"]:
            additional_notes.append("Python")
        if c["has_dotnet_title"] or c["has_dotnet_desc"]:
            additional_notes.append(".NET / C# (6 months exp)")
        if c["has_java_desc"] and not c["is_java_specialist_title"]:
            additional_notes.append("Java (secondary/preferred)")

        score = 88 if ("Python" in additional_notes or not additional_notes) else 82
        return {
            "should_apply": True,
            "match_score": score,
            "match_type": "STRONG_MATCH",
            "reason_code": "",
            "detailed_explanation": f"Relevant mixed-technology Full Stack role combining candidate's primary MERN Stack with additional technologies: {', '.join(additional_notes)}.",
            "is_mixed_technology": True,
            "additional_tech_noted": additional_notes
        }

    # RULE 7: Primary MERN / JavaScript Full Stack Roles (APPLY!)
    is_general_software = any(k in title_low for k in FULL_STACK_KEYWORDS)
    if c["has_mern_title"] or c["has_mern_desc"] or is_general_software:
        return {
            "should_apply": True,
            "match_score": 90 if c["has_mern_title"] else 85,
            "match_type": "STRONG_MATCH",
            "reason_code": "",
            "detailed_explanation": "Direct match with candidate's primary MERN Stack & JavaScript Full Stack specialization.",
            "is_mixed_technology": False,
            "additional_tech_noted": []
        }

    # Fallback: Non-software role or unclear keywords
    return {
        "should_apply": False,
        "match_score": 40,
        "match_type": "MODERATE_MATCH",
        "reason_code": "LOW_MATCH_SCORE",
        "detailed_explanation": "Role keywords do not sufficiently align with candidate's MERN / Full Stack specialization.",
        "is_mixed_technology": False,
        "additional_tech_noted": []
    }

