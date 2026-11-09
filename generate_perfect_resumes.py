import asyncio
import os
import pymupdf
from playwright.async_api import async_playwright
from true_icons import TRUE_ICONS

EMAIL_ICON = TRUE_ICONS['email']
PHONE_ICON = TRUE_ICONS['phone']
LINKEDIN_ICON = TRUE_ICONS['linkedin']
GITHUB_ICON = TRUE_ICONS['github']
PORTFOLIO_ICON = TRUE_ICONS['portfolio']

def get_html(is_qatar=False):
    phone_val = "+974 77557982" if is_qatar else "+91 7972694663"
    phone_tel = "tel:+97477557982" if is_qatar else "tel:+917972694663"
    
    # Current Location removed from both; Availability: Immediate Joiner and Open to: Full-Time / Remote / On-site added
    sub_contact = ("Visa Status: Transferable Visa with NOC &nbsp;|&nbsp; Availability: Immediate Joiner &nbsp;|&nbsp; Open to: Full-Time / Remote / On-site" 
                   if is_qatar else 
                   "Availability: Immediate Joiner &nbsp;|&nbsp; Open to: Full-Time / Remote / On-site")
    
    languages_str = "English (Professional Working Proficiency), Arabic (Conversational), Hindi (Native), Urdu (Fluent)" if is_qatar else "English (Professional Working Proficiency), Hindi (Native), Urdu (Fluent)"
    
    qatar_id_block = """
    <table class="section-table" style="margin-top: 15pt;">
      <tr>
        <td class="section-title">Qatar ID Expiry Date</td>
        <td class="section-line-td"><hr class="section-line" /></td>
      </tr>
    </table>
    <div style="font-family: 'Trebuchet MS', Tahoma, sans-serif; font-size: 10pt; font-weight: bold; color: #000000; margin-top: 3pt;">
      3-11-2027
    </div>
    """ if is_qatar else ""

    summary_text = ("Senior Full Stack Developer with 5+ years of production experience engineering web applications, distributed microservices, and enterprise platforms across React.js, Next.js, Node.js, TypeScript, PostgreSQL, and MongoDB. Accelerated database query throughput by 35%, maintained cloud infrastructure on AWS and Docker at 99.9% uptime, and delivering enterprise solutions with immediate availability in Qatar." 
                    if is_qatar else 
                    "Senior Full Stack Developer with 5+ years of production experience engineering web applications, distributed microservices, and enterprise platforms across React.js, Next.js, Node.js, TypeScript, PostgreSQL, and MongoDB. Accelerated database query throughput by 35%, maintained cloud infrastructure on AWS and Docker at 99.9% uptime, and directed end-to-end software delivery from system design to production releases.")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Abdul Razzaque Shaikh - Senior Full Stack Developer</title>
<style>
  @page {{
    size: 8.5in 11in; /* Exact US Letter size 612pt x 792pt */
    margin: 22pt 30pt 18pt 30pt;
  }}
  * {{
    box-sizing: border-box;
    margin: 0;
    padding: 0;
  }}
  body {{
    font-family: Tahoma, Arial, sans-serif;
    color: #000000;
    background: #ffffff;
    -webkit-font-smoothing: antialiased;
  }}
  .page {{
    width: 100%;
    page-break-after: always;
    break-after: page;
  }}
  .page:last-child {{
    page-break-after: avoid;
    break-after: avoid;
  }}

  /* Centered Header as requested */
  .header {{
    text-align: center;
    margin-bottom: 6pt;
  }}
  .name {{
    font-family: "Trebuchet MS", Tahoma, sans-serif;
    font-size: 22.5pt;
    font-weight: bold;
    color: #004e90;
    letter-spacing: 0.5px;
    margin-bottom: 3.5pt;
    text-align: center;
    text-transform: uppercase;
  }}
  .contact-bar {{
    font-size: 8.85pt;
    color: #004e90;
    margin-bottom: 3pt;
    line-height: 1.25;
    text-align: center;
    display: flex;
    justify-content: center;
    align-items: center;
    flex-wrap: wrap;
    gap: 4px 6px;
  }}
  .contact-item {{
    display: inline-flex;
    align-items: center;
    gap: 3.5px;
  }}
  .contact-icon {{
    width: 9.5pt;
    height: 9.5pt;
    object-fit: contain;
    vertical-align: middle;
  }}
  .contact-bar a {{
    color: #004e90;
    text-decoration: none;
  }}
  .contact-bar a:hover {{
    text-decoration: underline;
  }}
  .sub-contact {{
    font-size: 8.5pt;
    color: #222222;
    text-align: center;
    margin-top: 2pt;
  }}

  /* Section Header Table with Horizontal Rule */
  .section-table {{
    width: 100%;
    border-collapse: collapse;
    margin-top: 7pt;
    margin-bottom: 2.5pt;
  }}
  .section-title {{
    font-family: "Trebuchet MS", Tahoma, sans-serif;
    font-size: 11.5pt;
    font-weight: bold;
    color: #004e90;
    white-space: nowrap;
    width: 1%;
    padding-right: 6pt;
    vertical-align: middle;
  }}
  .section-line-td {{
    width: 99%;
    vertical-align: middle;
  }}
  .section-line {{
    border: none;
    border-top: 1px solid #004e90;
    margin: 0;
    width: 100%;
  }}

  /* Typography Page 1 */
  .p1-body {{
    font-size: 8.8pt;
    line-height: 1.28;
  }}
  .p1-bullets li {{
    font-size: 8.75pt;
    line-height: 1.27;
    margin-bottom: 1.8pt;
  }}
  .p1-skills li, .p1-skills .skill-item {{
    font-size: 8.75pt;
    line-height: 1.27;
    margin-bottom: 2pt;
  }}

  /* Typography Page 2 */
  .p2-bullets li {{
    font-size: 9.3pt;
    line-height: 1.35;
    margin-bottom: 3.5pt;
  }}

  /* Paragraphs */
  p.summary {{
    text-align: justify;
    margin-bottom: 2pt;
    color: #000000;
  }}

  /* Job / Project Entry */
  .entry {{
    margin-bottom: 3.5pt;
  }}
  .entry-table {{
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 0.5pt;
  }}
  .company-title {{
    font-family: "Trebuchet MS", Tahoma, sans-serif;
    font-size: 9.7pt;
    font-weight: bold;
    color: #000000;
    text-align: left;
    vertical-align: baseline;
  }}
  .company-title a {{
    color: #004e90;
    text-decoration: none;
  }}
  .company-title a:hover {{
    text-decoration: underline;
  }}
  .date-text {{
    font-family: Tahoma, Arial, sans-serif;
    font-size: 8.9pt;
    color: #000000;
    text-align: right;
    vertical-align: baseline;
    white-space: nowrap;
  }}
  .role-title {{
    font-family: "Trebuchet MS", Tahoma, sans-serif;
    font-size: 9.4pt;
    font-weight: bold;
    color: #000000;
    margin-bottom: 0.5pt;
  }}

  /* Bullets without stacking context for perfect ATS reading order */
  ul.bullets {{
    margin-top: 1pt;
    margin-bottom: 3pt;
    padding-left: 13pt;
  }}
  ul.bullets li {{
    text-align: justify;
    color: #000000;
  }}

  /* Skills */
  .skills-list {{
    margin-top: 1pt;
    margin-bottom: 2.5pt;
    padding-left: 13pt;
  }}
  .skill-item {{
    color: #000000;
  }}
  .skill-label {{
    font-family: "Trebuchet MS", Tahoma, sans-serif;
    font-weight: bold;
    color: #000000;
  }}
</style>
</head>
<body>

  <!-- PAGE 1: Header, Summary, Work Experience, Technical Skills, SmartHireX Project -->
  <div class="page">
    <div class="header">
      <div class="name">ABDUL RAZZAQUE SHAIKH</div>
      <div class="contact-bar">
        <span class="contact-item"><img src="{EMAIL_ICON}" class="contact-icon" alt="" /> <a href="mailto:mhaslaiabdur@gmail.com">mhaslaiabdur@gmail.com</a></span> &nbsp;|&nbsp; 
        <span class="contact-item"><img src="{PHONE_ICON}" class="contact-icon" alt="" /> <a href="{phone_tel}">{phone_val}</a></span> &nbsp;|&nbsp; 
        <span class="contact-item"><img src="{LINKEDIN_ICON}" class="contact-icon" alt="" /> <a href="https://www.linkedin.com/in/abdul-razzaque-fullstack/" target="_blank">linkedin.com/in/abdulrazzaque</a></span> &nbsp;|&nbsp; 
        <span class="contact-item"><img src="{GITHUB_ICON}" class="contact-icon" alt="" /> <a href="https://github.com/AbdulRazzaque" target="_blank">github</a></span> &nbsp;|&nbsp; 
        <span class="contact-item"><img src="{PORTFOLIO_ICON}" class="contact-icon" alt="" /> <a href="https://portfolio-website-one-rho-98.vercel.app/" target="_blank">Portfolio</a></span>
      </div>
      <div class="sub-contact">
        {sub_contact}
      </div>
    </div>

    <table class="section-table">
      <tr>
        <td class="section-title">Summary</td>
        <td class="section-line-td"><hr class="section-line" /></td>
      </tr>
    </table>
    <p class="summary p1-body">
      {summary_text}
    </p>

    <table class="section-table">
      <tr>
        <td class="section-title">Work Experience</td>
        <td class="section-line-td"><hr class="section-line" /></td>
      </tr>
    </table>
    
    <div class="entry">
      <table class="entry-table">
        <tr>
          <td class="company-title">Tharb – Doha, Qatar</td>
          <td class="date-text">2021 – Present</td>
        </tr>
      </table>
      <div class="role-title">Senior Full Stack Developer</div>
      <ul class="bullets p1-bullets">
        <li>Spearheaded the development of web and client/server applications using React.js, Next.js, and Node.js, increasing application scalability and overall performance by 30%.</li>
        <li>Architected and deployed secure REST APIs and microservices using Express.js and TypeScript, handling 50,000+ daily requests with 99.9% uptime and centralized error tracking.</li>
        <li>Accelerated customer-facing query throughput and database indexing in MongoDB Atlas and PostgreSQL, decreasing API latency by 35%.</li>
        <li>Mentored 4 junior engineers on TypeScript standards and modular design patterns, shortening feature sprint delivery cycles by 30%.</li>
        <li>Strengthened application security through MongoDB Atlas, JWT authentication, and role-based access control (RBAC), reducing unauthorized access attempts by 40%.</li>
        <li>Orchestrated continuous deployment pipelines via GitLab CI/CD, Docker containerization, and AWS infrastructure (EC2, S3), reducing release cycle turnaround time by 45%.</li>
      </ul>
    </div>

    <div class="entry">
      <table class="entry-table">
        <tr>
          <td class="company-title">TechGeekFirms – Mumbai, India</td>
          <td class="date-text">2020 – 2021</td>
        </tr>
      </table>
      <div class="role-title">Full Stack Developer</div>
      <ul class="bullets p1-bullets">
        <li>Engineered responsive MERN stack web applications using React.js, Node.js, and MongoDB, delivering 8+ client modules with 99.8% crash-free sessions.</li>
        <li>Formulated secure RESTful API endpoints and middleware using Node.js and Express.js, handling 20,000+ daily payload transactions across distributed services.</li>
        <li>Advanced exception handling, debugging, logging, and tracing methodologies, improving application runtime stability and accelerating issue resolution by 25%.</li>
        <li>Eliminated critical production defects via systematic root-cause debugging and Postman testing, reducing recurring issue incidence by 35%.</li>
        <li>Partnered with cross-functional UI/UX designers and QA teams to ship scalable features, boosting overall sprint delivery velocity by 20%.</li>
      </ul>
    </div>

    <table class="section-table">
      <tr>
        <td class="section-title">Technical Skills</td>
        <td class="section-line-td"><hr class="section-line" /></td>
      </tr>
    </table>
    <ul class="skills-list p1-skills">
      <li class="skill-item"><span class="skill-label">Programming Languages:</span> JavaScript (ES6+), TypeScript, Python, C, C++, SQL</li>
      <li class="skill-item"><span class="skill-label">Frontend Technologies:</span> React.js, Next.js, Redux, Redux Toolkit, Zustand, HTML5, CSS3, Tailwind CSS, Responsive Design</li>
      <li class="skill-item"><span class="skill-label">Backend Technologies:</span> Node.js, Express.js, REST APIs, GraphQL, Microservices Architecture</li>
      <li class="skill-item"><span class="skill-label">Database Technologies:</span> MongoDB, PostgreSQL, MySQL, Database Design, Indexing & Query Optimization</li>
      <li class="skill-item"><span class="skill-label">Messaging & Caching:</span> Apache Kafka, Redis (Caching & Session Store)</li>
      <li class="skill-item"><span class="skill-label">AI & LLM Technologies:</span> Google Gemini, OpenAI API (GPT models), ChatGPT, Ollama, Prompt Engineering</li>
      <li class="skill-item"><span class="skill-label">Cloud & DevOps:</span> AWS (EC2, S3), Docker Containerization, CI/CD, GitLab CI/CD, Linux</li>
      <li class="skill-item"><span class="skill-label">Developer Tools:</span> Git, GitHub, Postman, Jest (Unit Testing), Swagger, Vercel</li>
      <li class="skill-item"><span class="skill-label">Architecture & Concepts:</span> Microservices, Event-Driven Architecture, Scalable Systems, Backend Architecture, High Availability</li>
    </ul>

    <table class="section-table">
      <tr>
        <td class="section-title">Projects</td>
        <td class="section-line-td"><hr class="section-line" /></td>
      </tr>
    </table>
    
    <div class="entry">
      <table class="entry-table">
        <tr>
          <td class="company-title"><a href="https://smarhrix-client-hjk4.vercel.app/" target="_blank">SmartHireX Recruitment Automation Platform</a></td>
          <td class="date-text">2026</td>
        </tr>
      </table>
      <ul class="bullets p1-bullets">
        <li>Programmed multi-platform job distribution workflows, expanding candidate reach by 40% across 5+ hiring channels.</li>
        <li>Constructed a centralized CV candidate tracking pipeline, reducing recruitment screening cycle time by 35%.</li>
        <li>Configured granular role-based access control (RBAC) and real-time candidate dashboards, raising recruiter screening productivity by 25%.</li>
        <li>Integrated AI-powered resume parsing and filtering mechanisms, shortening evaluation time by 50% across 1,000+ candidate applications.</li>
        <li>Standardized high-performance RESTful APIs using Node.js and MongoDB Atlas, supporting sub-200ms response times across concurrent user sessions.</li>
        <li>Streamlined backend aggregation pipelines and database indexing, elevating search throughput and system responsiveness by 35%.</li>
      </ul>
    </div>
  </div>

  <!-- PAGE 2: Store Management System, Enterprise E-Commerce, Education, Key Domains, (Qatar ID) -->
  <div class="page">
    <div class="entry" style="margin-top: 6pt;">
      <table class="entry-table">
        <tr>
          <td class="company-title"><a href="https://inventory-management-i8ft.vercel.app/" target="_blank">Store Management System (Qatar) (CRM & POS)</a></td>
          <td class="date-text">2025</td>
        </tr>
      </table>
      <ul class="bullets p2-bullets">
        <li>Designed and deployed an integrated CRM and multi-store POS platform, centralizing billing, procurement, and stock management across 4+ retail locations.</li>
        <li>Established role-based dashboards for administrators, cashiers, and store managers, enabling streamlined access to 10+ operational and reporting modules.</li>
        <li>Systematized real-time inventory monitoring and low-stock alerts, reducing inventory reconciliation overhead by 60%.</li>
        <li>Synthesized sales analytics and real-time revenue dashboards, providing store owners with actionable insights that improved stock turnover by 25%.</li>
        <li>Created fault-tolerant checkout and billing modules with digital invoice generation, eliminating manual invoice discrepancies by 99%.</li>
        <li>Enhanced backend API performance through indexing optimization techniques, decreasing system response time by 35% during peak transactions.</li>
      </ul>
    </div>

    <div class="entry" style="margin-top: 14pt;">
      <table class="entry-table">
        <tr>
          <td class="company-title"><a href="https://alnawayath.com/" target="_blank">Enterprise E-Commerce Platform (MERN)</a></td>
          <td class="date-text">2024</td>
        </tr>
      </table>
      <ul class="bullets p2-bullets">
        <li>Delivered a scalable multi-vendor e-commerce platform supporting 5+ core modules, including dynamic product catalogs, cart, checkout, and inventory tracking.</li>
        <li>Structured high-concurrency Node.js microservices and MongoDB schema models, improving order processing throughput by 40%.</li>
        <li>Secured Stripe and Razorpay payment gateway integrations with real-time webhook listeners, achieving a 99.8% transaction success rate.</li>
        <li>Crafted responsive, mobile-first user interfaces using React.js and Redux Toolkit, decreasing client interaction latency by 30%.</li>
        <li>Administered role-based security configurations for customers, vendors, and admins, safeguarding accounts and operational data.</li>
        <li>Containerized application deployment with Docker and Redis session caching, reducing server load spikes by 45% during peak flash sales.</li>
      </ul>
    </div>

    <table class="section-table" style="margin-top: 16pt;">
      <tr>
        <td class="section-title">Education</td>
        <td class="section-line-td"><hr class="section-line" /></td>
      </tr>
    </table>
    <div class="entry" style="margin-top: 2pt;">
      <table class="entry-table">
        <tr>
          <td class="company-title">Bachelor of Science in Computer Science & Technology</td>
          <td class="date-text">2021</td>
        </tr>
      </table>
      <div style="font-size: 9.3pt; color: #000000; margin-top: 2pt;">
        BAMU University, Aurangabad, India
      </div>
    </div>

    <table class="section-table" style="margin-top: 16pt;">
      <tr>
        <td class="section-title">Key Domains & Strengths</td>
        <td class="section-line-td"><hr class="section-line" /></td>
      </tr>
    </table>
    <div style="font-size: 9.3pt; color: #000000; margin-top: 3pt; line-height: 1.5;">
      • <b>Industry Domains:</b> Enterprise E-Commerce, Retail POS & Inventory ERP, AI Recruitment Tech (HRTech)<br>
      • <b>Languages:</b> {languages_str}
    </div>

    {qatar_id_block}
  </div>

</body>
</html>
"""

async def build_and_validate():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp('http://127.0.0.1:9222')
        context = browser.contexts[0]
        page = await context.new_page()

        # India PDF
        india_html = get_html(is_qatar=False)
        await page.set_content(india_html, wait_until='networkidle')
        india_pdf = await page.pdf(
            format='Letter',
            print_background=True,
            prefer_css_page_size=True,
            margin={'top': '0', 'right': '0', 'bottom': '0', 'left': '0'}
        )
        india_path = os.path.abspath('backend/Abdul_Razzaque_India.pdf')
        with open(india_path, 'wb') as f:
            f.write(india_pdf)
        print("Generated India PDF:", india_path)

        # Qatar PDF
        qatar_html = get_html(is_qatar=True)
        await page.set_content(qatar_html, wait_until='networkidle')
        qatar_pdf = await page.pdf(
            format='Letter',
            print_background=True,
            prefer_css_page_size=True,
            margin={'top': '0', 'right': '0', 'bottom': '0', 'left': '0'}
        )
        qatar_path = os.path.abspath('backend/Abdul_Razzaque_Qatar.pdf')
        with open(qatar_path, 'wb') as f:
            f.write(qatar_pdf)
        print("Generated Qatar PDF:", qatar_path)

        await page.close()

    # Validation
    for name, path in [("India", india_path), ("Qatar", qatar_path)]:
        doc = pymupdf.open(path)
        print(f"\n================ {name} Validation ================")
        print(f"Total Pages: {len(doc)} (Target: EXACTLY 2)")
        for i, p_doc in enumerate(doc):
            links = [l for l in p_doc.get_links() if 'uri' in l]
            print(f"Page {i+1} Links count: {len(links)}")
            images = p_doc.get_images()
            print(f"Page {i+1} Images count: {len(images)}")
            blocks = p_doc.get_text('blocks')
            print(f"Page {i+1} first block (y0={blocks[0][1]:.1f}): {blocks[0][4][:50].strip()}")
            print(f"Page {i+1} last block (y1={blocks[-1][3]:.1f}): {blocks[-1][4][:50].strip()}")
        assert len(doc) == 2, f"Failed: expected 2 pages, got {len(doc)}"
        doc.close()
    print("\nALL VALIDATIONS SUCCESSFUL!")

if __name__ == '__main__':
    asyncio.run(build_and_validate())
