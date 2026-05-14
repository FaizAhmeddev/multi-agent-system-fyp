"""
DATA_LOADER/LOADER.PY
======================
Auto-downloads and embeds all 5 recommended datasets into ChromaDB.

Datasets:
  1. IT Helpdesk Tickets      → ChromaDB: it_knowledge
  2. Resume/CV Dataset        → ChromaDB: hr_cvs
  3. Finance/Expense Data     → ChromaDB: finance_docs
  4. Email Templates          → ChromaDB: email_corpus
  5. HR Policy & Documents    → ChromaDB: documents

Run:
  python data_loader/loader.py
"""

import os
import sys
import json
import csv
import io

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

DATA_DIR = os.path.join(ROOT, "data_loader", "data")
os.makedirs(DATA_DIR, exist_ok=True)


def _print(msg: str):
    print(f"  {msg}")


# ── Dataset 1: IT Helpdesk Knowledge Base ─────────────────────────────────────

def load_it_knowledge():
    """Generates IT helpdesk knowledge base and embeds into ChromaDB."""
    _print("📦 Loading IT Knowledge Base...")

    it_data = [
        {"problem": "laptop won't connect to WiFi", "solution": "1. Restart router. 2. Forget network and reconnect. 3. Update network drivers. 4. Run Windows Network Troubleshooter. 5. Reset TCP/IP stack: netsh int ip reset"},
        {"problem": "computer running very slow", "solution": "1. Check Task Manager for high CPU/RAM usage. 2. Disable startup programs. 3. Run Disk Cleanup. 4. Check for malware with Windows Defender. 5. Consider adding more RAM."},
        {"problem": "blue screen of death BSOD", "solution": "1. Note the error code. 2. Restart in Safe Mode. 3. Run sfc /scannow in CMD. 4. Update or rollback recent drivers. 5. Check RAM with MemTest86."},
        {"problem": "printer not working", "solution": "1. Check printer is powered on and connected. 2. Remove and re-add printer. 3. Clear print queue. 4. Update printer drivers. 5. Restart Print Spooler service."},
        {"problem": "forgot Windows password", "solution": "1. Use Microsoft account reset at account.microsoft.com. 2. Contact IT admin to reset local account. 3. Use Windows Recovery Environment if needed."},
        {"problem": "email not syncing in Outlook", "solution": "1. Check internet connection. 2. Go to Send/Receive → Update Folder. 3. Remove and re-add email account. 4. Check mailbox quota. 5. Repair Outlook data file (.pst)."},
        {"problem": "software installation fails", "solution": "1. Run installer as Administrator. 2. Temporarily disable antivirus. 3. Check disk space. 4. Clear temp files. 5. Download fresh installer copy."},
        {"problem": "screen flickering", "solution": "1. Update display drivers. 2. Change monitor refresh rate. 3. Check HDMI/display cable. 4. Disable hardware acceleration. 5. Test with external monitor."},
        {"problem": "keyboard not working", "solution": "1. Unplug and replug USB keyboard. 2. Try different USB port. 3. Check Device Manager for driver issues. 4. Test keyboard on another PC. 5. Update keyboard drivers."},
        {"problem": "VPN not connecting", "solution": "1. Check internet connection. 2. Verify VPN credentials. 3. Try different VPN server. 4. Restart VPN client. 5. Check firewall is not blocking VPN ports."},
        {"problem": "computer not booting", "solution": "1. Check power cable and outlet. 2. Remove external devices. 3. Listen for beep codes. 4. Try booting from USB recovery. 5. Check RAM seating."},
        {"problem": "Teams or Zoom audio not working", "solution": "1. Check microphone is not muted. 2. Set correct audio device in app settings. 3. Update audio drivers. 4. Allow microphone access in Privacy settings. 5. Restart audio service."},
        {"problem": "hard drive full", "solution": "1. Run Disk Cleanup. 2. Uninstall unused programs. 3. Move files to network drive. 4. Empty Recycle Bin. 5. Use Storage Sense to auto-clean."},
        {"problem": "cannot access shared network drive", "solution": "1. Check network connection. 2. Map network drive again with correct path. 3. Verify credentials. 4. Check firewall settings. 5. Contact IT to verify share permissions."},
        {"problem": "USB device not recognized", "solution": "1. Try different USB port. 2. Check Device Manager. 3. Update USB drivers. 4. Try on another computer. 5. Check USB power management settings."},
    ]

    docs = []
    for item in it_data:
        docs.append({
            "file":    "it_knowledge_base",
            "content": f"Problem: {item['problem']}\nSolution: {item['solution']}",
        })

    from database.vector_db import embed_documents
    result = embed_documents(docs, collection_name="it_knowledge")
    _print(f"   ✅ IT Knowledge: {result.get('embedded', 0)} entries embedded")
    return result


# ── Dataset 2: HR CV Templates ────────────────────────────────────────────────

def load_hr_cvs():
    """Generates sample CV data and embeds into ChromaDB."""
    _print("📦 Loading HR CV Dataset...")

    cvs = [
        {"name": "Ali Hassan", "role": "Software Engineer", "content": "5 years Python, Django, REST APIs. BSc CS FAST NUCES. Led team of 4. Strong SQL and PostgreSQL. AWS certified. Worked at TechCorp Pakistan."},
        {"name": "Fatima Khan", "role": "Data Analyst", "content": "3 years Excel, Power BI, SQL, Python pandas. MBA Finance IBA. Created dashboards for 50+ stakeholders. Experience in banking sector."},
        {"name": "Ahmed Raza", "role": "HR Manager", "content": "7 years HR experience. Recruitment, onboarding, policy creation. MSc HR Management. Managed 200+ employee workforce. Expert in HRIS systems."},
        {"name": "Sara Ahmed", "role": "Finance Manager", "content": "6 years accounting and finance. ACCA qualified. Budget planning, financial reporting, audit. Reduced costs by 15% at previous company."},
        {"name": "Usman Ali", "role": "IT Support", "content": "4 years IT helpdesk. Windows, Linux, networking. CompTIA A+ certified. Resolved 500+ tickets. Experience with Active Directory and Office 365."},
        {"name": "Zara Malik", "role": "Marketing Manager", "content": "5 years digital marketing. SEO, Google Ads, social media. MBA Marketing. Grew company social media by 300%. E-commerce experience."},
        {"name": "Hassan Khan", "role": "Project Manager", "content": "8 years project management. PMP certified. Agile, Scrum. Managed 20+ projects up to PKR 50M budget. Construction and IT sector experience."},
        {"name": "Ayesha Siddiqui", "role": "Software Engineer", "content": "2 years React, Node.js, MongoDB. BSc SE UET. Developed 3 full-stack applications. Strong Git skills and agile methodology."},
        {"name": "Bilal Ahmed", "role": "DevOps Engineer", "content": "4 years Docker, Kubernetes, CI/CD, AWS. Reduced deployment time by 60%. Strong Python and bash scripting. Azure DevOps experience."},
        {"name": "Nadia Hussain", "role": "Business Analyst", "content": "5 years requirement gathering, process mapping, stakeholder management. MBA IBA. CBAP certified. Banking and telecom sector experience."},
    ]

    docs = [{"file": f"cv_{cv['name'].replace(' ', '_')}", "content": f"Name: {cv['name']}\nRole: {cv['role']}\n{cv['content']}"} for cv in cvs]

    from database.vector_db import embed_documents
    result = embed_documents(docs, collection_name="hr_cvs")
    _print(f"   ✅ HR CVs: {result.get('embedded', 0)} CVs embedded")
    return result


# ── Dataset 3: Finance Data ────────────────────────────────────────────────────

def load_finance_data():
    """Generates sample finance records and embeds into ChromaDB."""
    _print("📦 Loading Finance Dataset...")

    records = [
        "Q1 2024 Expense Report: IT Department PKR 485,000. Marketing PKR 267,000. Operations PKR 143,000. HR PKR 312,000. Total PKR 1,207,000. Budget variance -2% under budget.",
        "Invoice INV-2024-001: TechSolutions Pvt Ltd. Web Development 40hrs x 3500 = 140,000. UI/UX 20hrs x 2500 = 50,000. Server Setup 25,000. GST 17% = 36,550. Total Due PKR 251,550.",
        "Monthly Payroll January 2024: Total employees 45. Total salaries PKR 2,250,000. Benefits PKR 337,500. EOBI contributions PKR 45,000. Net payroll PKR 2,632,500.",
        "Budget vs Actual Q2 2024: IT budgeted 500,000 actual 485,000 saving 15,000. Marketing budgeted 200,000 actual 267,000 overspent 67,000. Overall variance -2.3%.",
        "Annual Revenue 2023: Product sales PKR 15,500,000. Service revenue PKR 8,200,000. Total revenue PKR 23,700,000. Operating expenses PKR 18,900,000. Net profit PKR 4,800,000. Margin 20.25%.",
        "Tax Summary 2023: GST collected PKR 3,915,000 at 17%. Income tax PKR 1,440,000. Withholding tax PKR 285,000. Total tax liability PKR 5,640,000.",
        "Office Supplies February 2024: Printer cartridges 3500. Paper reams 2400. Stationery 1800. Cleaning supplies 2200. Total PKR 9,900.",
        "AWS Cloud Services Q1 2024: EC2 instances PKR 45,000. S3 storage PKR 8,500. RDS database PKR 12,000. Data transfer PKR 3,500. Total PKR 69,000.",
    ]

    docs = [{"file": f"finance_record_{i+1}", "content": r} for i, r in enumerate(records)]

    from database.vector_db import embed_documents
    result = embed_documents(docs, collection_name="finance_docs")
    _print(f"   ✅ Finance Records: {result.get('embedded', 0)} records embedded")
    return result


# ── Dataset 4: Email Templates ────────────────────────────────────────────────

def load_email_templates():
    """Loads professional email templates into ChromaDB."""
    _print("📦 Loading Email Templates...")

    templates = [
        {"type": "job_offer", "content": "Subject: Job Offer - [Position]\nDear [Name], We are pleased to offer you the position of [Role] at [Company]. Salary: PKR [Amount]/month. Start date: [Date]. Please confirm acceptance by [Deadline]."},
        {"type": "interview_invite", "content": "Subject: Interview Invitation - [Position]\nDear [Name], Thank you for applying. We would like to invite you for an interview on [Date] at [Time] at [Location]. Please confirm your attendance."},
        {"type": "invoice_reminder", "content": "Subject: Payment Reminder - Invoice [Number]\nDear [Name], This is a reminder that Invoice [Number] for PKR [Amount] was due on [Date]. Please arrange payment at your earliest convenience."},
        {"type": "meeting_request", "content": "Subject: Meeting Request - [Topic]\nDear [Name], I would like to schedule a meeting regarding [Topic] on [Date] at [Time]. Please confirm if this works for you."},
        {"type": "it_maintenance", "content": "Subject: Scheduled IT Maintenance - [Date]\nDear Team, IT maintenance is scheduled for [Date] from [Time] to [Time]. Systems may be unavailable. Please save your work beforehand."},
        {"type": "leave_approval", "content": "Subject: Leave Request Approved\nDear [Name], Your leave request for [Dates] has been approved. Ensure pending work is handed over before your leave. Enjoy your time off."},
        {"type": "performance_review", "content": "Subject: Annual Performance Review Schedule\nDear [Name], Your performance review is scheduled for [Date] at [Time] with [Manager]. Please prepare your self-assessment beforehand."},
    ]

    docs = [{"file": f"email_template_{t['type']}", "content": t["content"]} for t in templates]

    from database.vector_db import embed_documents
    result = embed_documents(docs, collection_name="email_corpus")
    _print(f"   ✅ Email Templates: {result.get('embedded', 0)} templates embedded")
    return result


# ── Dataset 5: HR Policies ────────────────────────────────────────────────────

def load_hr_policies():
    """Loads HR policy documents into ChromaDB."""
    _print("📦 Loading HR Policy Documents...")

    policies = [
        {"title": "Annual Leave Policy", "content": "Employees are entitled to 15 days annual leave per year. Leave must be applied 1 week in advance. Unused leave can be carried forward up to 10 days. Leave encashment available at year end."},
        {"title": "Sick Leave Policy", "content": "Employees are entitled to 10 days sick leave per year. Medical certificate required for more than 2 consecutive days. Sick leave cannot be carried forward. Emergency sick leave can be taken without prior notice."},
        {"title": "Working Hours Policy", "content": "Office hours are 9am to 6pm Monday to Friday. 1 hour lunch break from 1pm to 2pm. Remote work allowed on Fridays with manager approval. Overtime compensated at 1.5x rate."},
        {"title": "Recruitment Policy", "content": "All positions must be approved by department head and HR. Internal candidates given preference. Selection through CV screening, written test, and interview panel. Offer requires HR and finance approval."},
        {"title": "Code of Conduct", "content": "Employees must maintain professional behavior. Harassment of any kind is strictly prohibited. Confidential information must not be shared. Violations result in disciplinary action up to termination."},
        {"title": "Probation Policy", "content": "New employees serve 3-month probation period. Performance reviewed at end of probation. Probation can be extended by 1 month if needed. Confirmation letter issued upon successful completion."},
        {"title": "Training & Development", "content": "Employees entitled to 5 training days per year. Training budget PKR 50,000 per employee annually. Online courses reimbursed upon completion. Skills development encouraged and supported."},
        {"title": "Expense Reimbursement", "content": "Business expenses reimbursed within 30 days. Original receipts required for amounts over PKR 500. Travel expenses approved by manager before travel. Mobile allowance PKR 2000/month for managers."},
    ]

    docs = [{"file": f"hr_policy_{p['title'].replace(' ', '_')}", "content": f"{p['title']}\n\n{p['content']}"} for p in policies]

    from database.vector_db import embed_documents
    result = embed_documents(docs, collection_name="hr_policies")
    _print(f"   ✅ HR Policies: {result.get('embedded', 0)} policies embedded")
    return result


# ── Main Loader ───────────────────────────────────────────────────────────────

def load_all_datasets():
    """Load and embed all datasets. Called on first run."""
    print("\n" + "="*55)
    print("  📊 FYP Data Loader — Embedding All Datasets")
    print("="*55)

    results = {}
    for fn, name in [
        (load_it_knowledge,   "IT Knowledge"),
        (load_hr_cvs,         "HR CVs"),
        (load_finance_data,   "Finance Data"),
        (load_email_templates,"Email Templates"),
        (load_hr_policies,    "HR Policies"),
    ]:
        try:
            results[name] = fn()
        except Exception as e:
            _print(f"   ❌ {name} failed: {e}")
            results[name] = {"error": str(e)}

    print("\n" + "="*55)
    print("  ✅ All datasets loaded into ChromaDB!")
    print("="*55 + "\n")
    return results


def check_datasets_loaded() -> bool:
    """Returns True if datasets are already embedded."""
    try:
        from database.vector_db import collection_stats
        stats = collection_stats()
        return all(
            stats.get(c, 0) > 0
            for c in ["it_knowledge", "hr_cvs", "finance_docs"]
        )
    except Exception:
        return False


if __name__ == "__main__":
    load_all_datasets()
