"""Prompts ported verbatim from the legacy FYP_FINAL agents.

Behaviour is pinned by tests/characterization/test_ported_prompts.py, which renders
the legacy function and the port with the same inputs and asserts identical prompts.

Deliberate differences from legacy (and why):
  - no database writes, ChromaDB lookups or environment changes as side effects
  - early-return messages are plain text (no emoji)
Prompt wording is NOT improved here; that happens in Phase 3 with delimited
untrusted input and schema-validated outputs.
"""
from __future__ import annotations

from dataclasses import dataclass

# ── HR (legacy agents/hr_agent.py) ───────────────────────────────────────────


def hr_interview_questions_prompt(job_description: str, candidate_name: str, cv_content: str) -> str:
    return f"""You are a senior HR interviewer.

Job Description:
{job_description}

Candidate: {candidate_name}
CV Summary: {cv_content[:1000]}

Generate 8 tailored interview questions. Mix of: technical, behavioral, situational, role-specific.
For each question, include a brief note on what it assesses.
Format as numbered list."""


def hr_onboarding_missing(job_title: str, department: str) -> str | None:
    missing = []
    if not (job_title or "").strip():
        missing.append("job title")
    if not (department or "").strip():
        missing.append("department")
    if not missing:
        return None
    if len(missing) == 1:
        return f"Please provide the employee's {missing[0]} so I can generate the onboarding checklist."
    return "Please provide the employee's job title and department so I can generate the onboarding checklist."


def hr_onboarding_checklist_prompt(job_title: str, department: str) -> str:
    return f"""You are an HR specialist.
Create a detailed onboarding checklist for a new {job_title} in the {department} department.

Include:
- Day 1 tasks
- Week 1 tasks
- Month 1 milestones
- Required documents
- System access to setup
- Key people to meet

Format as a clear checklist using [ ] for each item."""


def hr_policy_answer_prompt(question: str, user_name: str = "Employee", policy_context: str = "") -> str:
    context_section = ""
    if policy_context:
        context_section = f"\nRelevant HR Policy:\n{policy_context[:2000]}\n"
    return f"""You are a professional HR assistant executing tasks assigned by the office orchestrator.

User context: {user_name}
Task / question:
{question}
{context_section}
If the user is only asking what the system can do (capabilities, features, which tasks you support), reply briefly that the Assistant chat handles that — do NOT invent sample employees (e.g. John Doe), offer letters, or placeholder profiles.
Complete every HR item in the request (profiles, offer letters, orientation schedules, summaries) only when the user asked for real HR work.
Output the deliverables directly in your reply — do not say you saved files to disk.
If employee facts (salary, email, department, name) appear anywhere in the request or prior thread context, use them — do not ask again and never substitute fictional names.
Only mention missing facts when they are truly absent from the entire context.
Keep answers structured and actionable."""  # noqa: E501


def hr_job_description_prompt(role: str, department: str, requirements: str = "") -> str:
    return f"""You are an HR specialist. Write a professional job description for:

Role: {role}
Department: {department}
Key Requirements: {requirements or 'standard for this role'}

Include:
- Role overview (2-3 sentences)
- Key responsibilities (6-8 bullet points)
- Required qualifications
- Preferred qualifications
- What we offer

Professional tone, clear and attractive."""


# ── IT (legacy agents/it_support_agent.py, prompt only) ─────────────────────

IT_KEYWORDS = [
    "computer", "laptop", "pc", "mac", "macbook", "iphone", "android", "phone", "tablet", "ipad",
    "wifi", "wi-fi", "internet", "password", "login", "software", "app", "application",
    "install", "error", "crash", "slow", "printer", "network", "screen", "keyboard",
    "mouse", "virus", "update", "windows", "system", "restart", "freeze", "blue screen", "bsod",
    "not working", "broken", "connection", "vpn", "access", "reset", "boot", "driver",
    "device", "hardware", "monitor", "usb", "teams", "zoom", "outlook", "email", "browser",
    "chrome", "edge", "firefox", "website", "loading", "stuck", "frozen", "sound", "audio",
    "microphone", "camera", "battery", "charger", "black screen", "blank", "file", "folder",
    "onedrive", "sharepoint", "microsoft", "google", "account", "sync", "backup", "disk",
]


def detect_it_issue(text: str) -> tuple[bool, list[str]]:
    t = text.lower()
    matched = [kw for kw in IT_KEYWORDS if kw in t]
    return len(matched) > 0, matched


def it_troubleshoot_prompt(problem: str, user_name: str = "User", kb_context: str = "") -> str:
    is_it, matched = detect_it_issue(problem)
    low_signal = not is_it
    kb_sec = f"\n\nKnowledge Base Reference:\n{kb_context}" if kb_context else ""
    hint = (
        "Optional context: wording matched few built-in IT keywords — still treat as IT/tech if it involves "
        "devices, software, accounts, or workplace tools. If it is clearly only HR/finance/recruiting with no "
        "technology angle, reply briefly and suggest the matching tab."
        if low_signal
        else ""
    )
    return f"""You are a professional IT Support Agent executing a task from the office orchestrator.

Requester: {user_name}
Task: "{problem}"
Detected keywords: {', '.join(matched) if matched else '(none — infer from full text)'}{kb_sec}
{hint}

If the task is to create a provisioning / support ticket (new hire laptop, email setup, software):
- State the ticket summary clearly
- List setup steps and priority
- Do not reference saving files to disk

Otherwise provide:
1. Diagnosis (1-2 sentences)
2. Step-by-step solution (numbered)
3. Prevention tip (1 sentence)

Be friendly, professional, concise."""


# ── Documents (legacy agents/documents_agent.py) ────────────────────────────

def doc_summarize_prompt(document_content: str, file_name: str = "Document", user_name: str = "User") -> str:
    return f"""Summarize "{file_name}" for {user_name}:

{document_content[:4000]}

Format:
**Type:** (Contract/Report/Policy/Invoice/Other)
**Summary:** (3-4 sentences)
**Key Points:** (5-7 bullets)
**Important Dates/Figures:** (if any)
**Action Items:** (if any)"""


EXTRACTION_TASKS = {
    "dates": "Extract ALL dates and deadlines.",
    "amounts": "Extract ALL monetary amounts and figures.",
    "parties": "Extract ALL parties, people, companies with their roles.",
    "clauses": "Extract KEY clauses, terms, conditions.",
    "contacts": "Extract ALL contact information.",
    "all": "Extract: dates, amounts, parties, key terms, contacts, action items.",
}


def doc_extract_prompt(document_content: str, extraction_type: str = "all", file_name: str = "Document") -> str:
    task = EXTRACTION_TASKS.get(extraction_type, EXTRACTION_TASKS["all"])
    return f"File: {file_name}\nTask: {task}\n\n{document_content[:3500]}\n\nPresent in clean organized format."


def doc_compare_prompt(doc1_content: str, doc2_content: str, doc1_name: str = "Doc 1",
                       doc2_name: str = "Doc 2") -> str:
    return f"""Compare these two documents:

**{doc1_name}:**
{doc1_content[:2000]}

**{doc2_name}:**
{doc2_content[:2000]}

Provide:
- Comparison table (Key attributes | {doc1_name} | {doc2_name})
- Similarities
- Key differences
- Recommendation"""


@dataclass(frozen=True)
class Temperature:
    """Legacy temperatures, kept for parity."""

    HR = 0.3
    HR_JD = 0.4
    IT = 0.3
    DOCS = 0.1
