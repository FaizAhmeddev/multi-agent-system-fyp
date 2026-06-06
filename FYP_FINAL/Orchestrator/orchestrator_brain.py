"""
ORCHESTRATOR/ORCHESTRATOR_BRAIN.PY
====================================
Central Orchestrator — single routing brain for the Assistant tab.

Pipeline:
  1. LLM request analysis (missing info, agent list, per-agent tasks)
  2. HR Gmail dispatch — inbox / shortlist / approve / follow-up
  3. Parallel specialist invoke (IT, Email, HR, Recruitment, Finance, Documents)
  4. Merge responses; report anything the system cannot do
"""

import os
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from langchain_openai import ChatOpenAI

from config import OPENAI_API_KEY, AGENT_IDS
from message_queue.queue import message_queue


os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY

# ── LLM for intent detection ──────────────────────────────────────────────────

def _get_llm():
    return ChatOpenAI(model="gpt-4o-mini", temperature=0)


def _history_context_block(
    conversation_history: Optional[List[Dict[str, str]]],
    max_turns: int = 6,
) -> str:
    """Prefix prior turns so specialist agents and intent LLM see thread context."""
    lines: list[str] = []
    for h in (conversation_history or [])[-(max_turns * 2) :]:
        content = (h.get("content") or "").strip()[:2000]
        if not content:
            continue
        role = (h.get("role") or "").strip()
        label = "User" if role == "user" else "Assistant"
        lines.append(f"{label}: {content}")
    if not lines:
        return ""
    return "Previous conversation:\n" + "\n".join(lines) + "\n\nCurrent request:\n"


def _thread_blob(
    user_message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> str:
    """Concatenate recent thread text for pattern matching."""
    parts: list[str] = []
    for h in conversation_history or []:
        c = (h.get("content") or "").strip()
        if c:
            parts.append(c)
    if (user_message or "").strip():
        parts.append(user_message.strip())
    return "\n".join(parts)


def _is_onboarding_workflow(
    user_message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> bool:
    from tools.hr_gmail_shortlist import _is_employee_onboarding_context

    return _is_employee_onboarding_context(_thread_blob(user_message, conversation_history).lower())


def _should_skip_gmail_shortcircuit(
    user_message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> bool:
    """Onboarding threads and direct SMTP sends must not hijack the Gmail inbox pipeline."""
    if _is_onboarding_workflow(user_message, conversation_history):
        return True
    if _is_compose_to_person_request(user_message, conversation_history):
        return True
    return False


def _is_compose_to_person_request(
    user_message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> bool:
    """True when the user wants to compose/send to a named person (not inbox fetch/shortlist)."""
    from tools.hr_gmail_shortlist import is_compose_email_to_person

    msg = (user_message or "").strip()
    if not msg or _is_onboarding_workflow(msg, conversation_history):
        return False
    if is_compose_email_to_person(msg) or _looks_like_one_off_email_request(msg):
        return True
    if _compose_request_active(msg, conversation_history):
        low = msg.lower()
        if re.search(r"\b(?:fetch|shortlist|inbox|batch|approve\s+and\s+send)\b", low):
            return False
        return True
    return False


def _extract_onboarding_facts(
    user_message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> dict[str, str]:
    """Pull employee facts from the full thread (current message + prior turns)."""
    blob = _thread_blob(user_message, conversation_history)
    facts: dict[str, str] = {}

    emails = re.findall(r"[\w.+-]+@[\w.-]+\.\w+", blob)
    if emails:
        facts["email"] = emails[-1]

    for pat, key in (
        (r"salary\s*:?\s*(\d+(?:\.\d+)?)", "salary"),
        (r"department\s*:?\s*([A-Za-z][A-Za-z0-9\s&/-]{0,40})", "department"),
        (r"designation\s*:?\s*([A-Za-z][A-Za-z0-9\s/-]{2,50})", "designation"),
    ):
        m = re.search(pat, blob, re.I)
        if m:
            val = m.group(1).strip().rstrip(".,;")
            if key == "department":
                val = val.split("\n")[0].split(" email")[0].strip()
            facts[key] = val

    for pat in (
        r"(?:new employee|employee named?|joining(?: the company)?(?: as)?)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)",
        r"\b([A-Z][a-z]+\s+[A-Z][a-z]+)\s+is joining",
        r"named?\s+([A-Z][a-z]+\s+[A-Z][a-z]+)",
    ):
        m = re.search(pat, blob)
        if m:
            facts["name"] = m.group(1).strip()
            break

    role_m = re.search(
        r"(?:as (?:a|an)\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s*(?:!|\.|,|\s+on|\s+joining|\s+starting)",
        blob,
    )
    if role_m and "name" not in facts.get("designation", ""):
        title = role_m.group(1).strip()
        if title.lower() not in ("monday", "tuesday", "wednesday", "thursday", "friday"):
            facts.setdefault("designation", title)

    if re.search(r"\bmonday\b", blob, re.I):
        facts["joining_day"] = "Monday"
    date_m = re.search(r"joining date\s*:?\s*([^\n,;]{4,40})", blob, re.I)
    if date_m:
        facts["joining_date"] = date_m.group(1).strip()

    return facts


def _onboarding_agent_set() -> list[str]:
    return ["hr", "email", "it_support", "finance", "documents"]


def _facts_context_block(facts: dict[str, str]) -> str:
    if not facts:
        return ""
    lines = [f"- {k.replace('_', ' ').title()}: {v}" for k, v in facts.items()]
    return "Known employee facts from this thread (use these — do not ask again):\n" + "\n".join(lines) + "\n\n"


def _parse_compose_recipient_name(message: str) -> str:
    """Extract a person name from 'email to …' / interview-invite phrasing."""
    m = (message or "").strip()
    if not m:
        return ""
    patterns = (
        r"\b(?:email|mail|send|write|invite)\s+(?:an?\s+)?(?:e-?mail\s+)?to\s+"
        r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})",
        r"\b(?:interview|invite|notify)\b.*\bto\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})",
        r"\bto\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b.*\b(?:interview|invite)\b",
    )
    for pat in patterns:
        hit = re.search(pat, m, re.I)
        if hit:
            name = hit.group(1).strip()
            if name.lower() not in ("the", "all", "everyone", "recommended"):
                return name
    loose = re.search(
        r"\b(?:email|mail|send|write|compose)\s+(?:an?\s+)?(?:e-?mail\s+)?(?:to\s+)?"
        r"([a-z][a-z.'-]*(?:\s+[a-z][a-z.'-]*){0,3})\b",
        m,
        re.I,
    )
    if loose:
        name = loose.group(1).strip()
        bad = {
            "email", "mail", "message", "reply", "interview", "invite", "invitation",
            "the", "all", "everyone", "recommended", "client", "candidate",
        }
        if name.lower() not in bad and "@" not in name:
            return " ".join(part.capitalize() for part in name.split())
    return ""


def _emails_in_user_text_only(
    user_message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> list[str]:
    """Email addresses the user typed — never from assistant drafts."""
    found: list[str] = []
    for h in conversation_history or []:
        if (h.get("role") or "").strip() != "user":
            continue
        found.extend(re.findall(r"[\w.+-]+@[\w.-]+\.\w+", h.get("content") or ""))
    found.extend(re.findall(r"[\w.+-]+@[\w.-]+\.\w+", user_message or ""))
    return found


def _interview_schedule_needs_clarification(message: str) -> bool:
    """True when interview time is missing or commonly ambiguous (e.g. 12 am vs noon)."""
    low = (message or "").lower()
    if not re.search(r"\b(?:interview|invite|schedule|meeting)\b", low):
        return False
    if re.search(r"\b12\s*(?::00)?\s*am\b", low):
        return True
    if re.search(
        r"\b(?:tomorrow|today|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        low,
    ) and re.search(r"\bat\s+\d{1,2}(?::\d{2})?\b", low):
        if not re.search(r"\b(?:am|pm|a\.m\.|p\.m\.)\b", low):
            return True
    if re.search(r"\bat\s+\d{1,2}\s*(?:o'?clock)?\s*(?:for|to)\b", low):
        if not re.search(r"\b(?:am|pm|a\.m\.|p\.m\.)\b", low):
            return True
    return False


def _compose_request_active(
    user_message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> bool:
    """True for compose-to-person now or a send/confirm follow-up on that thread."""
    from tools.hr_gmail_shortlist import is_compose_email_to_person

    msg = (user_message or "").strip()
    if is_compose_email_to_person(msg):
        return True
    blob = _thread_blob(msg, conversation_history)
    if is_compose_email_to_person(blob):
        if _user_confirmed_compose_send(msg, conversation_history) or _emails_in_user_text_only(
            msg, conversation_history
        ):
            return True
    return False


def validate_compose_email_request(
    user_message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> dict[str, Any]:
    """
    Pre-flight for one-off SMTP compose (not inbox shortlist).
    Returns ok, clarify_message, recipient_email, recipient_name, draft_only.
    """
    msg = (user_message or "").strip()
    if not _compose_request_active(msg, conversation_history):
        return {"ok": True, "clarify_message": "", "recipient_email": "", "recipient_name": "", "draft_only": False}

    if _is_onboarding_workflow(msg, conversation_history):
        return {"ok": True, "clarify_message": "", "recipient_email": "", "recipient_name": "", "draft_only": False}

    user_emails = _emails_in_user_text_only(msg, conversation_history)
    explicit = user_emails[-1] if user_emails else ""
    name = _parse_compose_recipient_name(msg) or _parse_compose_recipient_name(
        _thread_blob(msg, conversation_history)
    )
    confirmed = _user_confirmed_compose_send(msg, conversation_history)
    questions: list[str] = []

    schedule_blob = _thread_blob(msg, conversation_history)
    if _interview_schedule_needs_clarification(schedule_blob) and not re.search(
        r"\b(?:am|pm|a\.m\.|p\.m\.|noon|midnight)\b",
        msg,
        re.I,
    ):
        questions.append(
            "Please confirm the interview time (e.g. **12:00 PM noon** vs **12:00 AM midnight** tomorrow)."
        )

    recipient_email = explicit
    if not recipient_email and name:
        from config import is_gmail_configured

        if is_gmail_configured():
            try:
                from tools.email_search import find_email_by_name

                matches = find_email_by_name(name)
            except Exception:
                matches = []
            if not matches:
                questions.append(
                    f"I could not find an email address for **{name}** in your Gmail inbox/sent mail. "
                    "Please provide their email address."
                )
            elif len(matches) == 1:
                recipient_email = matches[0].get("email") or ""
                display = matches[0].get("name") or name
                if not explicit and not confirmed:
                    questions.append(
                        f"I found **{display}** at `{recipient_email}`. "
                        "Reply **send** (or include their email if this is wrong) to deliver the message."
                    )
            else:
                if not explicit:
                    opts = "\n".join(
                        f"- **{c.get('name', name)}** — `{c.get('email', '')}`" for c in matches[:8]
                    )
                    extra = f"\n- …and {len(matches) - 8} more" if len(matches) > 8 else ""
                    questions.append(
                        f"I found multiple contacts matching **{name}**. Which recipient should I use?\n{opts}{extra}"
                    )
                recipient_email = explicit
        else:
            questions.append(
                f"Please provide the email address for **{name}** "
                "(Gmail is not configured for automatic contact lookup)."
            )

    elif not recipient_email and not name and not confirmed:
        questions.append(
            "Who should receive this email? Please provide the recipient's **full name** or **email address**."
        )

    if questions and not (confirmed and recipient_email and not _interview_schedule_needs_clarification(schedule_blob)):
        return {
            "ok": False,
            "clarify_message": "Before I send anything, I need to confirm:\n\n"
            + "\n".join(f"{i + 1}. {q}" for i, q in enumerate(questions)),
            "recipient_email": recipient_email,
            "recipient_name": name,
            "draft_only": True,
        }

    ready = bool(recipient_email) and (
        explicit or confirmed or not name
    )
    return {
        "ok": ready,
        "clarify_message": "",
        "recipient_email": recipient_email,
        "recipient_name": name,
        "draft_only": not ready,
    }


def _user_confirmed_compose_send(
    user_message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> bool:
    """User explicitly opted in to send after a prior draft/clarification."""
    low = (user_message or "").lower().strip()
    if re.search(r"[\w.+-]+@[\w.-]+\.\w+", user_message or ""):
        if re.search(r"\b(?:send|yes|confirm|go ahead|deliver|dispatch)\b", low):
            return True
    confirm_only = (
        r"^(?:yes|yep|yeah|confirm|confirmed|send(?:\s+it)?|go ahead|"
        r"please send|ok send|looks good)\.?$"
    )
    if re.match(confirm_only, low):
        return True
    return False


def _parse_composed_email(drafted: str) -> dict[str, str]:
    """Extract To / Subject / body from a composed email block."""
    lines = (drafted or "").splitlines()
    to_addr = ""
    subject = ""
    body_lines: list[str] = []
    in_body = False
    for line in lines:
        low = line.strip().lower()
        if not in_body and low.startswith("to:"):
            to_addr = line.split(":", 1)[1].strip()
            continue
        if not in_body and low.startswith("subject:"):
            subject = line.split(":", 1)[1].strip()
            continue
        if not in_body and subject and not line.strip():
            in_body = True
            continue
        if in_body or subject:
            body_lines.append(line)
    body = "\n".join(body_lines).strip()
    if not body and subject:
        body = drafted
    return {"to": to_addr, "subject": subject or "Welcome to the Team", "body": body or drafted}


def _smtp_send_office_email(recipient: str, subject: str, body: str) -> str:
    from tools.gmail_send import send_email

    state = send_email({"recipient": recipient, "subject": subject, "body": body})
    return (state.get("send_status") or "Send attempted.").strip()


def _should_send_onboarding_email(
    user_message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> bool:
    from tools.hr_gmail_shortlist import is_direct_email_send_to_address

    blob = _thread_blob(user_message, conversation_history).lower()
    if is_direct_email_send_to_address(user_message):
        return True
    auto_cues = (
        "automatically",
        "auto complete",
        "complete the full onboarding",
        "send welcome email",
        "send a welcome",
        "notify the admin",
        "tasks to perform",
    )
    if any(c in blob for c in auto_cues):
        return True
    low = (user_message or "").lower()
    return bool(re.search(r"\b(?:send|deliver|dispatch|mail)\b", low) and "email" in low)


def _enrich_onboarding_context(
    user_message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> str:
    facts = _extract_onboarding_facts(user_message, conversation_history)
    block = _facts_context_block(facts)
    if not block:
        return user_message
    return block + user_message


def _is_capabilities_or_meta_question(message: str) -> bool:
    """
    User is asking what the Assistant can do — not requesting HR/IT/finance work.
    Must route to general only (never run specialist agents with invented demos).
    """
    msg = (message or "").lower().strip()
    if not msg or len(msg) > 600:
        return False
    if _has_operational_work_request(msg):
        return False
    capability_patterns = (
        r"what can you do",
        r"what (?:tasks?|things?) (?:can|do) you",
        r"which tasks? can you",
        r"let me know which task",
        r"what (?:are your|is your) capabilit",
        r"what (?:services|features) do you offer",
        r"list (?:your )?(?:tasks|capabilities|features|functions)",
        r"how can you help(?: me)?",
        r"what do you support",
        r"which (?:agents?|modules?|specialists?) can you",
        r"tell me what you can",
        r"what are you able to",
        r"describe your (?:role|functions|capabilities)",
        r"what kind of (?:work|tasks?) can you",
        r"what does (?:this |the )?(?:project|app|system|platform) do",
        r"what is this (?:project|app|system|platform)",
        r"explain (?:the )?(?:whole |entire )?(?:project|system|platform)",
        r"what (?:is|are) (?:the )?(?:whole |entire )?project",
        r"show (?:me )?(?:all )?(?:prompt|task)s? (?:i can|you can|to use)",
        r"prompt (?:guide|examples?|catalog)",
        r"assistant (?:tab|guide|help)",
        r"what can i (?:do|ask) (?:here|in assistant)",
    )
    if any(re.search(p, msg) for p in capability_patterns):
        return True
    if re.search(r"\b(?:which|what)\s+tasks?\b", msg) and re.search(
        r"\b(?:can you|do you|you perform|you handle|are you able)\b", msg
    ):
        return True
    return False


def _has_operational_work_request(msg: str) -> bool:
    """True when the user wants real work done, not a meta/capabilities question."""
    return bool(
        re.search(
            r"\b(?:onboard|new employee|welcome email|offer letter|shortlist|fetch\s+last|"
            r"inbox|create (?:a |an )?ticket|payroll entry|generate pdf|export pdf|"
            r"screen (?:these )?cv|hire |joining (?:on|date)|complete the full onboarding|"
            r"tasks to perform|send (?:a )?welcome|approve and send)\b",
            msg,
        )
    )


# Agent task catalog — same slugs as intent routing / _CANONICAL (capabilities answers only).
_AGENT_TASK_CATALOG: dict[str, dict] = {
    "hr_gmail": {
        "title": "Gmail / recruitment inbox",
        "desc": (
            "Fetch or filter inbox, parse CV attachments, shortlist by skills, draft interview invites, "
            "approve and send from a batch."
        ),
        "examples": [
            "Fetch the latest 10 candidate emails",
            "Fetch 20 emails and shortlist two Python developers",
            "Show emails received on 15 May 2026",
            "Send interview invitations for Monday at 3 PM",
            "Approve and send to all recommended candidates",
        ],
    },
    "email": {
        "title": "Email compose & send",
        "desc": "Welcome letters, replies, notifications — drafted and sent via Gmail when you provide a recipient.",
        "examples": [
            "Send a welcome email to newhire@company.com — start Monday as Software Engineer",
            "Draft a reply thanking the vendor and ask for revised invoice",
        ],
    },
    "hr": {
        "title": "HR",
        "desc": (
            "Onboarding checklists, offer letters, orientation, policies, interview questions "
            "(for a **named** new hire — facts you provide, not invented examples)."
        ),
        "examples": [
            "New employee [Name] joining Monday as [Role] — complete full onboarding automatically",
            "Generate interview questions for a senior Python developer",
            "Draft an offer letter for Ali, start date 1 June",
        ],
    },
    "recruitment": {
        "title": "Recruitment (attachments)",
        "desc": "Upload CVs + job description in chat → parse, rank, shortlist, draft interview emails.",
        "examples": [
            "Screen attached CVs for the JD in my message and rank top 3",
            "Shortlist the best candidate and draft an invite email",
        ],
    },
    "it_support": {
        "title": "IT support",
        "desc": "Troubleshooting guidance and IT tickets (laptop, software, access, VPN, etc.).",
        "examples": [
            "My laptop is slow — create an IT ticket",
            "WiFi connects but no internet on VPN",
        ],
    },
    "finance": {
        "title": "Finance",
        "desc": "Expenses, budgets, invoices, payroll breakdowns — **PDF / Excel downloads** when you ask to generate or export.",
        "examples": [
            "Analyze these expenses and highlight top 5 costs",
            "Generate quarterly expense PDF and Excel",
        ],
    },
    "documents": {
        "title": "Documents",
        "desc": "Google Drive search and summaries when Drive is connected; compare or extract from document text.",
        "examples": [
            "Search Google Drive for onboarding policy PDF",
            "Summarize the security policy document",
        ],
    },
}


def build_platform_capabilities_answer(user_name: str = "User", user_role: str = "") -> str:
    """Deterministic capability list from orchestrator agent catalog — no invented deliverables."""
    from config import get_role_orchestrator_allowlist, is_gmail_configured, is_google_drive_configured

    all_slugs = tuple(_AGENT_TASK_CATALOG.keys())
    allow = get_role_orchestrator_allowlist(user_role) if user_role else None
    if allow is None:
        allowed = list(all_slugs)
    else:
        allowed = [s for s in all_slugs if s in allow]

    lines = [
        f"Hi {user_name} — **Office Automation Agents Pro** (Assistant / Orchestrator).",
        "",
        "Type any office task in plain language. I detect intent, route to the right specialist(s), "
        "and run them **in parallel** when needed. Results appear as cards below your message.",
        "",
        "**Specialists you can invoke from this chat:**",
        "",
    ]
    for slug in all_slugs:
        if slug not in allowed:
            continue
        block = _AGENT_TASK_CATALOG[slug]
        lines.append(f"- **{block['title']}**: {block['desc']}")
        lines.append("  Example prompts:")
        for ex in block["examples"]:
            lines.append(f'  - "{ex}"')
        lines.append("")

    blocked = [s for s in all_slugs if s not in allowed]
    if blocked:
        titles = [_AGENT_TASK_CATALOG[s]["title"] for s in blocked]
        lines.append("**Not available for your role:** " + ", ".join(titles) + ".")
        lines.append("")

    lines += [
        "**How routing works (this orchestrator):**",
        "- Keyword + LLM intent → agent list (IT, HR, Finance, Documents, Email, hr_gmail, recruitment)",
        "- Gmail hiring requests short-circuit to inbox shortlist when the message matches inbox ops",
        "- Multi-step jobs (e.g. onboard + email) expand to several agents in one turn",
        "",
    ]
    if not is_gmail_configured():
        lines.append("Note: Gmail needs `GMAIL_EMAIL` and `GMAIL_APP_PASSWORD` in `.env`.")
    if not is_google_drive_configured():
        lines.append("Note: Google Drive is optional for document search.")
    lines.append("")
    lines.append(
        "Send your next **real** task when ready — I route and execute specialists; "
        "I do not run them for this capabilities question."
    )
    return "\n".join(lines)


def _looks_like_one_off_email_request(message: str) -> bool:
    """Broad SMTP compose/send detection, including lowercase names."""
    low = (message or "").lower().strip()
    if not low:
        return False
    if re.search(r"\b(?:fetch|list|read|show|search)\b.*\b(?:inbox|emails?|gmail)\b", low):
        return False
    return bool(
        re.search(
            r"\b(?:send|compose|write|draft|mail|email)\b.{0,80}\b(?:to|for)\b",
            low,
        )
        or re.search(r"\bemail\s+to\s+[a-z0-9_.+-]+", low)
        or re.search(r"\b(?:send|email|mail)\s+(?:him|her|them)\b", low)
    )


def _looks_like_dashboard_request(message: str) -> bool:
    low = (message or "").lower()
    return bool(
        re.search(r"\b(?:make|create|build|show|generate|prepare)\b.{0,60}\bdashboards?\b", low)
        or re.search(r"\bdashboards?\b", low)
    )


def _dashboard_guidance(message: str) -> str:
    low = (message or "").lower()
    if any(k in low for k in ("finance", "expense", "budget", "invoice", "revenue", "sales", "profit", "cost")):
        return (
            "Dashboard creation is available in the **Finance** tab. "
            "Open **Finance**, upload or paste your finance data, then use the dashboard/report controls there. "
            "From Assistant I can still answer finance questions, analyze data, or generate PDF/Excel reports."
        )
    return (
        "Dashboard building is not executed directly inside the Assistant chat. "
        "For finance dashboards, go to the **Finance** tab and create the dashboard from there. "
        "For other dashboards, tell me the domain and data source, and I can route analysis or explain which tab to use."
    )


def _looks_like_export_request(message: str) -> bool:
    low = (message or "").lower()
    return bool(
        re.search(r"\b(?:generate|create|make|export|download|prepare|build)\b.{0,80}\b(?:pdf|excel|xlsx|csv|docx|word|report|summary)\b", low)
        or re.search(r"\b(?:pdf|excel|xlsx|csv|docx)\b.{0,60}\b(?:report|summary|invoice|budget|expense|finance|payroll)\b", low)
    )


def _has_substantive_export_data(message: str, attachments: Optional[List[Dict[str, Any]]] = None) -> bool:
    if attachments:
        return any((a.get("content") or "").strip() for a in attachments)
    text = (message or "").strip()
    if "|" in text and "\n" in text:
        return True
    if re.search(r"\b\d+(?:,\d{3})*(?:\.\d+)?\b", text) and len(text.split()) >= 10:
        return True
    return bool(re.search(r"\b(?:invoice|expense|budget|payroll|salary|revenue|sales|profit|loss)\b", text, re.I))


def _assistant_preflight_result(
    user_message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    attachments: Optional[List[Dict[str, Any]]] = None,
) -> Optional[dict]:
    """
    Deterministic guardrail before LLM planning.
    Returns a route-result-like dict with proceed/message/agents/agent_tasks when it can decide.
    """
    msg = (user_message or "").strip()
    low = msg.lower()
    if not msg:
        return {
            "proceed": False,
            "message": "Please type the task you want me to perform.",
            "agents": [],
            "agent_tasks": {},
            "limitations": [],
        }

    if _looks_like_dashboard_request(msg):
        return {
            "proceed": False,
            "message": _dashboard_guidance(msg),
            "agents": [],
            "agent_tasks": {},
            "limitations": [],
        }

    if _is_compose_to_person_request(msg, conversation_history):
        compose_check = validate_compose_email_request(msg, conversation_history)
        task = msg
        resolved = (compose_check.get("recipient_email") or "").strip()
        if resolved:
            task = f"{msg}\n\n[Resolved recipient for send: {resolved}]"
        out = {
            "proceed": True,
            "message": "",
            "agents": ["email"],
            "agent_tasks": {"email": task},
            "limitations": [],
        }
        if not compose_check.get("ok") and compose_check.get("clarify_message"):
            out["clarify_prefix"] = compose_check["clarify_message"]
        return out

    if _looks_like_export_request(msg):
        if not _has_substantive_export_data(msg, attachments):
            return {
                "proceed": False,
                "message": (
                    "I can generate the PDF/Excel/report from Assistant, but I need the source data first. "
                    "Please paste the invoice, expense, budget, payroll, or sales data, or attach a file."
                ),
                "agents": [],
                "agent_tasks": {},
                "limitations": [],
            }
        agent = "finance" if re.search(
            r"\b(?:finance|financial|invoice|expense|budget|payroll|salary|revenue|sales|profit|loss|tax|pkr|usd)\b",
            low,
        ) else "documents"
        return {
            "proceed": True,
            "message": "",
            "agents": [agent],
            "agent_tasks": {agent: msg},
            "limitations": [],
        }

    return None


def run_general_assistant(
    user_message: str,
    user_name: str = "User",
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> str:
    """
    Conversational layer: greetings, date/time (server clock), follow-ups, light Q&A.
    Uses thread history so the next turn can refer to the previous reply (real multi-turn).
    """
    from datetime import datetime

    msg_low = (user_message or "").strip().lower()
    if any(k in msg_low for k in ("load dataset", "seed database", "populate collection", "load all datasets")):
        try:
            from data_loader.loader import load_all_datasets
            results = load_all_datasets()
            formatted = []
            for name, r in results.items():
                if "error" in r:
                    formatted.append(f"- {name}: Failed ({r['error']})")
                else:
                    formatted.append(f"- {name}: Successfully embedded {r.get('embedded', 0)} entries.")
            return "Database Seeding Status\n\n" + "\n".join(formatted)
        except Exception as e:
            return f"Database seeding failed: {e}"

    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    now = datetime.now().strftime("%A, %B %d, %Y — %I:%M %p (local time on this machine)")
    system = (
        f"You are a helpful office assistant speaking with **{user_name}** inside an enterprise "
        "multi-agent automation platform (IT, Email, HR, Finance, Documents).\n"
        f"When the user asks what day it is, the date, or the time, answer using this exact real-world clock: **{now}**.\n"
        "Continue the conversation naturally: refer back to earlier turns when they say \"that\", \"it\", "
        "\"continue\", or ask a follow-up.\n"
        "If they need operational work (send Gmail from the system, screen CVs, IT tickets, Drive search), "
        "say clearly that those are handled by specialist agents in this same chat — keep your reply short "
        "and do not pretend you already executed those integrations yourself.\n"
        "Be concise unless they ask for detail."
    )
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.35)
    msgs = [SystemMessage(content=system)]
    for h in (conversation_history or [])[-10:]:
        role = (h.get("role") or "").strip()
        text = (h.get("content") or "").strip()[:4000]
        if not text:
            continue
        if role == "user":
            msgs.append(HumanMessage(content=text))
        elif role == "assistant":
            msgs.append(AIMessage(content=text))
    msgs.append(HumanMessage(content=(user_message or "").strip()[:8000]))
    if _is_capabilities_or_meta_question(user_message):
        return build_platform_capabilities_answer(user_name)
    try:
        out = llm.invoke(msgs)
        # Sanitize LLM output to ASCII for Windows console
        content = (out.content or "").strip()
        clean = content.encode('ascii', errors='ignore').decode()
        return clean or "I'm here if you need anything else."
    except Exception as e:
        return f"I couldn't reach the language model ({e}). Current local time: {now}."


# ── Intent detection ──────────────────────────────────────────────────────────

EMAIL_KEYWORDS = [
    "email", "mail", "send", "reply", "inbox", "message", "gmail",
    "smtp", "imap", "subject", "recipient", "forward", "compose",
    "write to", "contact", "notify"
]

IT_KEYWORDS = [
    "computer", "laptop", "wifi", "internet", "password", "login",
    "software", "install", "error", "crash", "slow", "printer",
    "network", "screen", "keyboard", "virus", "update", "windows",
    "restart", "freeze", "not working", "broken", "connection",
    "vpn", "access", "reset", "boot", "driver", "it support", "technical",
    "device", "hardware", "monitor", "cable", "usb", "mouse",
    "blue screen", "bsod", "cannot connect", "won't turn on",
]

HR_KEYWORDS = [
    "hr", "hire", "recruit", "cv", "resume", "candidate", "interview",
    "onboard", "onboarding", "employee", "salary", "leave", "policy",
    "payroll", "job description", "staff", "screening", "shortlist",
    "performance", "appraisal", "human resources", "vacancy", "position"
]

RECRUITMENT_KEYWORDS = [
    "orchestration", "multi-agent recruitment", "shortlist and email",
    "interview invitation", "uploaded 10", "uploaded ten", "parallel agents",
    "candidate matching", "jd match", "rank candidates", "workflow",
]

FINANCE_KEYWORDS = [
    "finance", "financial", "expense", "budget", "invoice", "payment",
    "revenue", "cost", "profit", "loss", "tax", "account", "balance",
    "ledger", "cash flow", "report", "spending", "pkr", "usd", "money",
    "salary", "payable", "receivable", "quarterly", "fiscal", "audit",
    "generate pdf", "generate excel", "generate xlsx", "export pdf", "export excel",
]

DOCS_KEYWORDS = [
    "document", "file", "pdf", "drive", "google drive", "folder",
    "search document", "find file", "summarize", "contract", "policy",
    "manual", "report", "doc", "read file", "extract", "compare doc"
]


def _keyword_score(msg: str, keywords: list, weight: int = 1) -> int:
    """Score how strongly a message matches a keyword set (phrase-aware)."""
    score = 0
    for kw in keywords:
        k = kw.lower().strip()
        if not k:
            continue
        if " " in k:
            if k in msg:
                score += weight * 2
        elif re.search(rf"\b{re.escape(k)}\b", msg):
            score += weight
    return score


def _pre_route_intent(
    user_message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> list | None:
    """Fast, deterministic routing for common phrasing before LLM/keywords."""
    from tools.hr_email_intelligence import classify_hr_email_intent
    from tools.hr_gmail_shortlist import (
        is_compose_email_to_person,
        parse_gmail_shortlist_prompt,
        user_requests_hr_gmail_approve_send,
        user_requests_hr_recruitment_follow_up,
    )

    if _is_compose_to_person_request(user_message, conversation_history):
        return ["email"]

    hr_mail_intent = classify_hr_email_intent(user_message)
    if hr_mail_intent in ("inbox_browse", "cv_inventory", "cv_shortlist"):
        return ["hr_gmail"]
    if parse_gmail_shortlist_prompt(user_message):
        return ["hr_gmail"]

    msg = (user_message or "").lower().strip()
    if not msg:
        return ["general"]

    if user_requests_hr_gmail_approve_send(user_message) or user_requests_hr_recruitment_follow_up(
        user_message
    ):
        return ["hr_gmail"]

    if re.search(r"\b(what\s+day|what\s+date|what\s+time|today'?s\s+date|current\s+time)\b", msg):
        return ["general"]
    if re.search(r"^(hi|hello|hey|thanks|thank you|good\s+(morning|afternoon|evening))\b", msg):
        return ["general"]
    if _is_capabilities_or_meta_question(user_message):
        return ["general"]
    if _looks_like_dashboard_request(user_message):
        return ["general"]

    fin_doc = re.search(
        r"\b(generate|export|create|download)\b.*\b(pdf|xlsx|excel|csv|word|docx|report)\b",
        msg,
    ) or re.search(r"\b(pdf|xlsx|excel)\b.*\b(expense|invoice|budget|finance|financial)\b", msg)
    if fin_doc:
        return ["finance"]

    if re.search(r"\b(google\s+drive|drive\s+folder|search\s+(the\s+)?document)\b", msg):
        return ["documents"]

    return None


def detect_intent(user_message: str) -> list:
    """
    Detect which agents should handle the message (keyword scoring).
    Returns list of agent types.
    """
    early = _pre_route_intent(user_message)
    if early is not None:
        return early

    msg = user_message.lower()

    scores = {
        "email": _keyword_score(msg, EMAIL_KEYWORDS),
        "it_support": _keyword_score(msg, IT_KEYWORDS),
        "hr": _keyword_score(msg, HR_KEYWORDS),
        "recruitment": _keyword_score(msg, RECRUITMENT_KEYWORDS, weight=2),
        "finance": _keyword_score(msg, FINANCE_KEYWORDS),
        "documents": _keyword_score(msg, DOCS_KEYWORDS),
    }

    # Disambiguate shared terms
    if "salary" in msg or "payroll" in msg:
        if scores["finance"] >= scores["hr"]:
            scores["hr"] = max(0, scores["hr"] - 1)
        else:
            scores["finance"] = max(0, scores["finance"] - 1)

    if "resume" in msg or "cv" in msg:
        if any(w in msg for w in ("upload", "attached", "shortlist", "rank", "screen")):
            scores["recruitment"] += 3
            scores["email"] = max(0, scores["email"] - 1)

    threshold = 1
    matches = [agent for agent, sc in scores.items() if sc >= threshold]
    matches.sort(key=lambda a: scores[a], reverse=True)

    if not matches:
        return ["general"]

    return normalize_agent_list(matches)


# Canonical agent keys used by AGENT_IDS, graphs, and logging
_CANONICAL = ("general", "hr_gmail", "it_support", "email", "hr", "recruitment", "finance", "documents")

_AGENT_ALIASES = {
    "general": "general",
    "conversation": "general",
    "chitchat": "general",
    "small_talk": "general",
    "assistant_general": "general",
    "hr_gmail": "hr_gmail",
    "gmail_cv_shortlist": "hr_gmail",
    "onboarding": "hr",
    "employee_onboarding": "hr",
    "new_hire": "hr",
    "inbox_cv_fetch": "hr_gmail",
    "it_support": "it_support",
    "it": "it_support",
    "it_support_agent": "it_support",
    "support": "it_support",
    "tech": "it_support",
    "email": "email",
    "mail": "email",
    "gmail": "email",
    "hr": "hr",
    "human_resources": "hr",
    "hiring": "hr",
    "recruitment": "recruitment",
    "recruiting": "recruitment",
    "talent_acquisition": "recruitment",
    "recruitment_pipeline": "recruitment",
    "finance": "finance",
    "financial": "finance",
    "accounting": "finance",
    "documents": "documents",
    "document": "documents",
    "docs": "documents",
    "drive": "documents",
    "google_drive": "documents",
}


def normalize_agent_slug(raw: str) -> Optional[str]:
    """Map LLM / user output to a canonical agent type."""
    if not raw or not isinstance(raw, str):
        return None
    s = raw.strip().lower().replace("-", "_").replace(" ", "_")
    s = re.sub(r"[^a-z0-9_]", "", s)
    if s in _CANONICAL:
        return s
    return _AGENT_ALIASES.get(s)


def normalize_agent_list(agents: list) -> list:
    seen = set()
    out = []
    for a in agents or []:
        c = normalize_agent_slug(str(a))
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out if out else ["general"]


def _cv_attachment_count(attachments: Optional[List[Dict[str, Any]]]) -> int:
    """Count non–job-description file attachments with extractable text (treated as CVs)."""
    if not attachments:
        return 0
    n = 0
    for a in attachments:
        name = (a.get("name") or a.get("filename") or "").lower()
        if any(k in name for k in ("jd", "job_desc", "job-description", "requisition", "specification")):
            continue
        if (a.get("content") or "").strip():
            n += 1
    return n


def coerce_agents_for_cv_hiring(
    user_message: str,
    attachments: Optional[List[Dict[str, Any]]],
    agents: List[str],
) -> List[str]:
    """
    If the user attached resume/CV files and the text is about hiring or interviews,
    run **recruitment only** so the Email auto-reply agent does not answer in parallel.
    """
    if _cv_attachment_count(attachments) < 1:
        return agents
    msg = (user_message or "").lower()
    hiring = any(
        w in msg
        for w in (
            "candidate", "cv", "resume", "shortlist", "hire", "interview",
            "recruit", "data entry", "job", "role", "position", "jd",
            "select", "best ", "email them", "mail them", "invite", "invitation",
        )
    )
    if not hiring:
        return agents
    return ["recruitment"]


def recruitment_user_requests_email_send(message: str) -> bool:
    """True when the user explicitly wants messages delivered (not drafts-only)."""
    m = (message or "").lower()
    if any(
        x in m
        for x in (
            "don't send",
            "do not send",
            "draft only",
            "no email",
            "without sending",
            "do not email",
            "don't email",
        )
    ):
        return False
    if any(
        h in m
        for h in (
            "email them",
            "email him",
            "email her",
            "send email",
            "send the email",
            "send an email",
            "send interview",
            "email invitation",
            "email invite",
            "notify them",
            "invite them",
            "mail them",
        )
    ):
        return True
    if ("email" in m or "send" in m) and ("interview" in m or "invite" in m or "invitation" in m):
        return True
    return False


def recruitment_user_wants_top_one_only(message: str) -> bool:
    """Prefer emailing a single top-scoring candidate (e.g. 'best candidate')."""
    m = (message or "").lower()
    return any(
        k in m
        for k in (
            "best candidate",
            "top candidate",
            "one candidate",
            "single candidate",
            "select one",
            "pick one",
            "top one",
            "best one",
            "the best ",
            "a best ",
            "highest match",
            "top match",
        )
    )


def build_context_with_attachments(user_message: str, attachments: Optional[List[Dict[str, Any]]]) -> str:
    """Append extracted attachment text so every routed agent sees the same context."""
    if not attachments:
        return user_message
    parts = [user_message.rstrip(), "", "### Attached files (shared context)", ""]
    for att in attachments:
        name = att.get("name") or att.get("filename") or "file"
        text = (att.get("content") or "").strip()
        if not text:
            continue
        cap = 12000
        if len(text) > cap:
            text = text[:cap] + "\n...[truncated]"
        parts.append(f"#### {name}\n{text}\n")
    return "\n".join(parts).strip()


def apply_routing_corrections(
    user_message: str,
    agents: List[str],
    conversation_history: Optional[List[Dict[str, str]]] = None,
    attachments: Optional[List[Dict[str, Any]]] = None,
) -> List[str]:
    """
    Deterministic routing fixes after LLM planning.
    Prevents compose-to-person prompts from being sent to hr_gmail inbox pipeline.
    """
    from tools.hr_gmail_shortlist import is_compose_email_to_person
    from tools.hr_email_intelligence import message_looks_like_gmail_ops

    msg = (user_message or "").strip()
    if not msg:
        return agents

    if _is_compose_to_person_request(msg, conversation_history):
        return ["email"]

    if _should_skip_gmail_shortcircuit(msg, conversation_history):
        cleaned = [a for a in agents if a != "hr_gmail"]
        return normalize_agent_list(cleaned) if cleaned else agents

    low = msg.lower()
    if message_looks_like_gmail_ops(msg) and re.search(
        r"\b(?:fetch|shortlist|inbox|last\s+\d+\s+(?:e-?mails?|emails?))\b", low
    ):
        cleaned = [a for a in agents if a not in ("email", "hr")]
        if "hr_gmail" not in cleaned:
            cleaned.append("hr_gmail")
        return normalize_agent_list(cleaned) if cleaned else ["hr_gmail"]

    if _cv_attachment_count(attachments) >= 1:
        return coerce_agents_for_cv_hiring(msg, attachments, agents)

    return agents


def _finalize_agent_routing(
    user_message: str,
    agents: List[str],
    conversation_history: Optional[List[Dict[str, str]]] = None,
    attachments: Optional[List[Dict[str, Any]]] = None,
) -> List[str]:
    """Last routing pass before parallel execution — prevents hr_gmail + email double-runs."""
    agents = apply_routing_corrections(user_message, agents, conversation_history, attachments)
    agents = coerce_agents_for_cv_hiring(user_message, attachments, agents)
    if _is_compose_to_person_request(user_message, conversation_history):
        return ["email"]
    return normalize_agent_list(agents)


def expand_agents_for_multi_task(
    message: str,
    agents: list,
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> list:
    """Include every specialist domain referenced in a multi-step user request."""
    if _is_capabilities_or_meta_question(message):
        return ["general"]
    if _is_onboarding_workflow(message, conversation_history):
        return normalize_agent_list(list(set(agents + _onboarding_agent_set())))

    if _is_compose_to_person_request(message, conversation_history):
        return ["email"]

    low = (message or "").lower()
    numbered = len(re.findall(r"(?m)^\s*\d+\.\s", message or ""))
    multi = numbered >= 3 or "tasks to perform" in low or "complete the following" in low
    if not multi and len(agents) > 1:
        return agents
    if not multi:
        return agents

    extra = set(agents)
    if any(k in low for k in ("fetch", "inbox", "last 10", "last 20", "shortlist", "python developer", "gmail")):
        extra.add("hr_gmail")
    if any(k in low for k in ("welcome email", "send email", "send a welcome", "email to", "notify", "compose")):
        extra.add("email")
    if any(
        k in low
        for k in (
            "employee profile",
            "offer letter",
            "orientation",
            "onboarding",
            "new employee",
            "joining",
            "employment",
        )
    ):
        extra.add("hr")
    if any(k in low for k in ("it support", "laptop", "software installation", "it ticket", "provisioning")):
        extra.add("it_support")
    if any(k in low for k in ("payroll", "salary breakdown", "payroll entry", "monthly salary")):
        extra.add("finance")
    if any(k in low for k in ("google drive", "pdf", "document", "offer letter")):
        extra.add("documents")

    out = normalize_agent_list(list(extra))
    if "hr_gmail" in out and any(k in low for k in ("fetch", "inbox", "shortlist", "last 10", "last 20")):
        # Inbox recruitment is hr_gmail; new-hire welcome email stays on email agent
        pass
    return out if out else agents


def plan_orchestrator_request(
    user_message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> dict:
    """
    Analyze the full request: agents to run in parallel, focused sub-tasks, gaps, limitations.
    Returns dict with keys: proceed, message, agents, agent_tasks, limitations.
    """
    import json

    from config import (
        is_gmail_configured,
        is_google_drive_configured,
        is_openai_configured,
        openai_missing_message,
    )

    if not is_openai_configured():
        return {
            "proceed": False,
            "message": openai_missing_message("The Assistant orchestrator"),
            "agents": [],
            "agent_tasks": {},
            "limitations": [],
        }

    if _is_capabilities_or_meta_question(user_message):
        return {
            "proceed": True,
            "message": "",
            "agents": ["general"],
            "agent_tasks": {},
            "limitations": [],
        }

    preflight = _assistant_preflight_result(user_message, conversation_history)
    if preflight is not None:
        return preflight

    from tools.hr_gmail_shortlist import is_compose_email_to_person

    if _is_compose_to_person_request(user_message, conversation_history):
        compose_check = validate_compose_email_request(user_message, conversation_history)
        task = (user_message or "").strip()
        resolved = (compose_check.get("recipient_email") or "").strip()
        if resolved:
            task = f"{task}\n\n[Resolved recipient for send: {resolved}]"
        out = {
            "proceed": True,
            "message": "",
            "agents": ["email"],
            "agent_tasks": {"email": task},
            "limitations": [],
        }
        if not compose_check.get("ok") and compose_check.get("clarify_message"):
            out["clarify_prefix"] = compose_check["clarify_message"]
        return out

    hist = _history_context_block(conversation_history, max_turns=10)
    facts = _extract_onboarding_facts(user_message, conversation_history)
    facts_block = _facts_context_block(facts)
    onboarding = _is_onboarding_workflow(user_message, conversation_history)
    caps = []
    if not is_gmail_configured():
        caps.append("Gmail fetch/send is not configured (set GMAIL_EMAIL and GMAIL_APP_PASSWORD in .env).")
    if not is_google_drive_configured():
        caps.append("Google Drive storage is not configured; deliver documents in chat instead of saving to Drive.")

    cap_block = "\n".join(f"- {c}" for c in caps) if caps else "- All core integrations available."

    prompt = f"""You are the orchestrator brain for an office automation platform.
Analyze the user's request using the conversation thread. Decide which specialist agents to run IN PARALLEL.

{facts_block}{hist if hist else "(No prior turns.)"}

Current user message:
\"\"\"{(user_message or "")[:12000]}\"\"\"

System capabilities:
{cap_block}

Available agent slugs:
- hr_gmail: Gmail inbox — fetch/list emails, count CVs, shortlist candidates, send interview invites from inbox
- email: Compose and send welcome/onboarding emails via Gmail SMTP when recipient is known
- hr: Employee profiles, offer letters, orientation schedules, HR policy, onboarding content
- it_support: IT tickets, laptop/software provisioning requests
- finance: Payroll breakdowns, expenses, invoices, budget reports, export PDF/Excel in parallel
- documents: Offer letters, onboarding summaries, Google Drive when configured
- recruitment: When CV files are attached + hiring workflow
- general: Greetings, date/time, small talk only

Return ONLY valid JSON:
{{
  "proceed": true or false,
  "message": "If proceed is false: ask the user naturally for ONLY the missing required facts. No example formats. No invented defaults.",
  "agents": ["slug", ...],
  "agent_tasks": {{"slug": "focused instruction for that agent only"}},
  "limitations": ["tasks the system cannot complete and why"]
}}

Rules:
1. Multiple agents IN PARALLEL when the user lists multiple tasks (full new-hire onboarding → hr, email, it_support, finance, documents).
2. "fetch last N emails" or "shortlist python developers from inbox" → hr_gmail only (never mix with new-hire onboarding).
2b. "Email to [Person Name] for interview" or schedule interview invite to a named person → email agent ONLY (not hr_gmail). hr_gmail is for inbox fetch/shortlist, not one-off SMTP compose.
2c. For one-off compose/send to a named person: proceed false if recipient email is unknown, multiple Gmail matches exist, interview time is ambiguous (e.g. "12 am" or "tomorrow at 12" without AM/PM), or the user has not confirmed send. Ask naturally — never invent or guess an email address.
3. Use salary, email, department, name, and dates already present anywhere in the thread — do NOT ask again if they appear above.
4. For full onboarding requests: proceed true immediately; run all relevant agents even if some details are still missing (note gaps in limitations, not in message).
5. Do not plan to save employee files to a local folder; output content and downloadable PDFs via finance/documents agents.
6. If an integration is unavailable, add to limitations and still proceed for other tasks when possible.
7. If the request is impossible or unrelated, proceed false with a clear explanation.
8. "What can you do?", "which tasks can you perform?", capabilities, or how you can help → agents: ["general"] ONLY. Never run hr/email/finance to demo fake John Doe data.

JSON only:"""

    try:
        llm = _get_llm()
        raw = llm.invoke(prompt).content.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
        raw = re.sub(r"\s*```\s*$", "", raw)
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("plan not an object")
        agents = normalize_agent_list(data.get("agents") or [])
        agent_tasks = data.get("agent_tasks") if isinstance(data.get("agent_tasks"), dict) else {}
        limitations = data.get("limitations") if isinstance(data.get("limitations"), list) else []
        proceed = bool(data.get("proceed", True))
        message = (data.get("message") or "").strip()
        if proceed and not agents:
            proceed = False
            message = message or "I could not determine which specialist agents should handle this request."
        if not proceed and not message:
            message = "I need more information before I can run this request."
        if _is_capabilities_or_meta_question(user_message):
            return {
                "proceed": True,
                "message": "",
                "agents": ["general"],
                "agent_tasks": {},
                "limitations": [],
            }
        if onboarding:
            agents = normalize_agent_list(list(set(agents + _onboarding_agent_set())))
            if facts:
                proceed = True
                message = ""
            elif not proceed:
                proceed = True
                message = ""
                if not limitations:
                    limitations = [
                        "Some employee details were not in the thread; agents will use placeholders where needed."
                    ]
            default_tasks = {
                "hr": "Create employee profile, offer letter text, orientation schedule, onboarding summary.",
                "email": "Compose and send welcome email with joining instructions to the employee.",
                "it_support": "Create IT ticket for laptop, official email, and software setup.",
                "finance": "Generate monthly salary breakdown and initial payroll entry; export PDF.",
                "documents": "Prepare offer letter and onboarding summary documents.",
            }
            for slug, task in default_tasks.items():
                agent_tasks.setdefault(slug, task)
        agents = apply_routing_corrections(
            user_message, agents, conversation_history, attachments=None
        )
        clarify_prefix = ""
        if _is_compose_to_person_request(user_message, conversation_history):
            proceed = True
            message = ""
            agents = ["email"]
            compose_check = validate_compose_email_request(user_message, conversation_history)
            agent_tasks.setdefault("email", (user_message or "").strip())
            resolved = (compose_check.get("recipient_email") or "").strip()
            if resolved:
                agent_tasks["email"] = (
                    f"{user_message.strip()}\n\n"
                    f"[Resolved recipient for send: {resolved}]"
                )
            if not compose_check.get("ok") and compose_check.get("clarify_message"):
                clarify_prefix = compose_check["clarify_message"]
        return {
            "proceed": proceed,
            "message": message,
            "agents": agents,
            "agent_tasks": {k: str(v) for k, v in agent_tasks.items() if normalize_agent_slug(k)},
            "limitations": [str(x) for x in limitations],
            "clarify_prefix": clarify_prefix,
        }
    except Exception:
        agents = detect_intent_llm(user_message, conversation_history)
        agents = expand_agents_for_multi_task(user_message, agents, conversation_history)
        agents = _finalize_agent_routing(user_message, agents, conversation_history)
        return {
            "proceed": True,
            "message": "",
            "agents": agents,
            "agent_tasks": {},
            "limitations": caps,
        }


def detect_intent_llm(
    user_message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> list:
    """
    LLM-powered intent detection for complex/ambiguous messages.
    Falls back gracefully.
    """
    early = _pre_route_intent(user_message, conversation_history)
    if early is not None:
        return early

    try:
        llm = _get_llm()
        hist = _history_context_block(conversation_history, max_turns=8)
        context_block = (
            f"\nRecent conversation:\n{hist}\n" if hist else "\n(No prior turns in this thread.)\n"
        )
        prompt = f"""You are an intent detector for an office automation system.
Use the conversation thread to resolve follow-ups ("that", "them", "approve", "send it", "the shortlist").
{context_block}
User message: "{user_message}"

Available agents (return canonical slugs only):
- general: greetings, thanks, date/time, small talk, clarifying questions, follow-ups that do NOT require running Gmail/IT/HR/Finance/Drive tools
- hr_gmail: Gmail inbox for HR — list/search emails by date, count CVs by skill, OR fetch inbox CVs + rank/shortlist + draft interview emails. Follow-up "approve and send" after a shortlist → hr_gmail. Use hr_gmail for "fetch last 10 emails", "emails on 20 May", "how many Python CVs", and recruitment shortlist — NOT for unrelated chitchat.
- it_support: computer, laptop, wifi, printer, software install, errors, VPN, passwords (IT hardware/software)
- email: compose/send/reply to a specific person (NOT inbox listing or CV shortlist — use hr_gmail for Gmail inbox operations)
- hr: HR policies, employee profiles, offer letters, orientation plans (NOT Gmail inbox — use hr_gmail for inbox)
- recruitment: user attached CV/resume files AND wants screen/rank/shortlist/interview email workflow
- finance: expenses, invoices, budgets, revenue, tax, payroll reports, export PDF/Excel/CSV financial documents
- documents: Google Drive search, summarize files, contracts, manuals

Rules:
0. "What can you do?", "which tasks can you perform?", capabilities, how you can help → ["general"] ONLY.
1. Use multiple agents when the user clearly asks for several domains in one message (e.g. new hire onboarding with welcome email + IT ticket + payroll → hr, email, it_support, finance).
2. Gmail inbox list/search/count CVs OR CV shortlist OR "fetch and email python developers" → hr_gmail only (not email+hr).
3. CV attachments uploaded in chat + hiring language → recruitment only (not hr_gmail).
4. "Salary" in a budget/expense/invoice context → finance; in hiring/employee context → hr or finance if payroll.
5. Follow-up approval to send interview emails after hr_gmail shortlist → hr_gmail.

Respond with ONLY a JSON array of agent slugs.
Examples:
  "what day is it today?" → ["general"]
  "fetch last 10 emails" → ["hr_gmail"]
  "fetch last 40 emails with CVs and select 5 Python developers and email them" → ["hr_gmail"]
  "new employee Ahmed joining Monday as Software Engineer — complete full onboarding (welcome email, profile, offer, IT ticket, payroll)" → ["hr", "email", "it_support", "finance"]
  "approve and send" (after shortlist in thread) → ["hr_gmail"]
  "what is our leave policy?" → ["hr"]
  "thanks" → ["general"]
  "my laptop is very slow" → ["it_support"]
  "draft a reply to the client email" → ["email"]
  "what is our leave policy?" → ["hr"]
  "rank these CVs and email top candidate" (with attachments) → ["recruitment"]
  "generate quarterly expense PDF and Excel" → ["finance"]
  "find the contract PDF on Google Drive" → ["documents"]
  "thanks, that helped" → ["general"]

JSON array only:"""

        resp = llm.invoke(prompt)
        text = resp.content.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```\s*$", "", text)
        text = text.strip()
        import json

        agents = json.loads(text)
        if isinstance(agents, list) and agents:
            return apply_routing_corrections(
                user_message,
                normalize_agent_list(agents),
                conversation_history,
            )
    except Exception:
        pass

    return apply_routing_corrections(
        user_message,
        detect_intent(user_message),
        conversation_history,
    )


# ── Orchestrator Core ─────────────────────────────────────────────────────────

class Orchestrator:
    """
    Central orchestrator that:
    1. Receives user requests
    2. Detects intent (which agents needed)
    3. Publishes tasks to Message Queue (A2A)
    4. Collects responses from agents
    5. Merges and returns final answer
    """

    def __init__(self):
        self.agent_id = AGENT_IDS["orchestrator"]
        self.mq = message_queue
        self._lock = threading.Lock()
        self._responses = {}
        self._finance_export_files: Optional[List[Dict[str, Any]]] = None
        self._agent_tasks: Dict[str, str] = {}

    def _scoped_route_result(
        self,
        *,
        start_time: float,
        agents_used: List[str],
        final_answer: str,
        responses: Optional[Dict[str, str]] = None,
        hr_gmail_batch_id: Optional[str] = None,
        hr_gmail_pending_cleared: bool = False,
        ui_payload: Optional[dict] = None,
        finance_export_files: Optional[list] = None,
    ) -> dict:
        """Standard orchestrator response envelope."""
        from config import orchestrator_mq_enabled
        from tools.assistant_display import build_display_text

        elapsed = round((time.time() - start_time) * 1000)
        resp = responses if responses is not None else (
            {agents_used[0]: final_answer} if agents_used else {}
        )
        out = {
            "agents_used": agents_used,
            "responses": resp,
            "final_answer": final_answer,
            "task_ids": {},
            "elapsed_ms": elapsed,
            "mq_messages": (
                self.mq.get_all_messages_for_display(limit=30) if orchestrator_mq_enabled() else []
            ),
            "hr_gmail_batch_id": hr_gmail_batch_id,
            "finance_export_files": finance_export_files,
        }
        if hr_gmail_pending_cleared:
            out["hr_gmail_pending_cleared"] = True
        if ui_payload:
            out["ui_payload"] = ui_payload
            out["display_answer"] = build_display_text(final_answer, ui_payload)
        return out

    def _route_hr_gmail(
        self,
        *,
        user_message: str,
        user_name: str,
        user_role: str,
        conversation_history: Optional[List[Dict[str, str]]],
        allowed_agents: Optional[List[str]],
        start_time: float,
    ) -> Optional[dict]:
        from tools.hr_email_intelligence import (
            dispatch_hr_gmail_for_orchestrator,
            message_looks_like_gmail_ops,
        )
        from tools.hr_gmail_shortlist import (
            parse_gmail_shortlist_prompt,
            user_requests_hr_gmail_approve_send,
            user_requests_hr_recruitment_follow_up,
        )

        allow = set(normalize_agent_list(allowed_agents)) if allowed_agents else None
        needs_gmail = (
            user_requests_hr_gmail_approve_send(user_message)
            or user_requests_hr_recruitment_follow_up(user_message)
        )
        if allow is not None and "hr_gmail" not in allow and needs_gmail:
            return self._scoped_route_result(
                start_time=start_time,
                agents_used=[],
                final_answer=(
                    "**Gmail CV shortlist blocked** — your role cannot use inbox shortlist / approve-send."
                ),
            )

        if allow is not None and "hr_gmail" not in allow and "hr" not in allow and "recruitment" not in allow:
            return None

        gmail_relevant = message_looks_like_gmail_ops(user_message)
        if not gmail_relevant:
            return None

        return dispatch_hr_gmail_for_orchestrator(
            user_message=user_message,
            conversation_history=conversation_history,
            user_name=user_name,
            user_role=user_role,
            start_time=start_time,
        )

    def _resolve_agents(
        self,
        *,
        user_message: str,
        attachments: Optional[List[Dict[str, Any]]],
        conversation_history: Optional[List[Dict[str, str]]],
        use_llm_intent: bool,
    ) -> list:
        if use_llm_intent:
            agents = detect_intent_llm(user_message, conversation_history)
        else:
            agents = normalize_agent_list(detect_intent(user_message))
        return coerce_agents_for_cv_hiring(user_message, attachments, agents)

    def route(self, user_message: str, user_name: str = "User",
              use_llm_intent: bool = True,
              attachments: Optional[List[Dict[str, Any]]] = None,
              allowed_agents: Optional[List[str]] = None,
              conversation_history: Optional[List[Dict[str, str]]] = None,
              user_role: str = "") -> dict:
        """
        Main entry point.
        Returns:
          {
            "agents_used":  ["it_support", ...],
            "responses":    {"it_support": "...", ...},
            "final_answer": "merged response",
            "task_ids":     {"it_support": "msg-id", ...},
            "mq_messages":  [list of all queue messages],
          }
        """
        start_time = time.time()
        self._finance_export_files = None
        self._agent_tasks = {}
        forced_agents: Optional[List[str]] = None
        clarify_prefix = ""

        if _is_capabilities_or_meta_question(user_message):
            cap_answer = build_platform_capabilities_answer(user_name, user_role)
            return self._scoped_route_result(
                start_time=start_time,
                agents_used=["general"],
                final_answer=cap_answer,
                responses={"general": cap_answer},
            )

        preflight = _assistant_preflight_result(user_message, conversation_history, attachments)
        if preflight is not None:
            if not preflight.get("proceed"):
                return self._scoped_route_result(
                    start_time=start_time,
                    agents_used=[],
                    final_answer=preflight.get("message") or "I need more information to proceed.",
                    responses={},
                )
            self._agent_tasks = preflight.get("agent_tasks") or {}
            forced_agents = normalize_agent_list(preflight.get("agents") or [])
            clarify_prefix = (preflight.get("clarify_prefix") or "").strip()
            if forced_agents and forced_agents != ["general"]:
                forced_agents = coerce_agents_for_cv_hiring(user_message, attachments, forced_agents)
                use_llm_intent = False

        full_message = build_context_with_attachments(
            _enrich_onboarding_context(user_message, conversation_history),
            attachments,
        )

        from tools.hr_email_intelligence import message_looks_like_gmail_ops

        if not use_llm_intent and not _should_skip_gmail_shortcircuit(user_message, conversation_history):
            if message_looks_like_gmail_ops(user_message):
                hr_gmail = self._route_hr_gmail(
                    user_message=user_message,
                    user_name=user_name,
                    user_role=user_role,
                    conversation_history=conversation_history,
                    allowed_agents=allowed_agents,
                    start_time=start_time,
                )
                if hr_gmail is not None:
                    return hr_gmail

        plan_limitations: list[str] = []
        if forced_agents:
            agents = forced_agents
        elif use_llm_intent:
            plan = plan_orchestrator_request(user_message, conversation_history)
            plan_limitations = plan.get("limitations") or []
            if not plan.get("proceed"):
                return self._scoped_route_result(
                    start_time=start_time,
                    agents_used=[],
                    final_answer=plan.get("message") or "I need more information to proceed.",
                )
            agents = expand_agents_for_multi_task(
                user_message, plan.get("agents") or [], conversation_history
            )
            self._agent_tasks = plan.get("agent_tasks") or {}
            if not clarify_prefix:
                clarify_prefix = (plan.get("clarify_prefix") or "").strip()
            if not self._agent_tasks.get("email") and agents == ["email"]:
                self._agent_tasks["email"] = user_message.strip()
        else:
            agents = self._resolve_agents(
                user_message=user_message,
                attachments=attachments,
                conversation_history=conversation_history,
                use_llm_intent=False,
            )
            agents = expand_agents_for_multi_task(user_message, agents, conversation_history)

        agents = _finalize_agent_routing(
            user_message, agents, conversation_history, attachments
        )
        if not self._agent_tasks.get("email") and agents == ["email"]:
            self._agent_tasks.setdefault("email", user_message.strip())

        if allowed_agents:
            allow = set(normalize_agent_list(allowed_agents))
            allow.add("general")
            blocked = [a for a in agents if a not in allow]
            agents = [a for a in agents if a in allow]
            if not agents:
                if "general" in allow:
                    agents = ["general"]
                else:
                    elapsed = round((time.time() - start_time) * 1000)
                    allowed_txt = ", ".join(sorted(allow - {"general"})) or "none"
                    return {
                        "agents_used": [],
                        "responses": {},
                        "final_answer": (
                            "**Outside your department scope**\n\n"
                            f"This request matched: **{', '.join(blocked) or 'restricted agents'}**, but your role may use: "
                            f"**{allowed_txt}** (plus general chat).\n\n"
                            "Try rephrasing for your department tab, or ask an **Administrator** for broader access."
                        ),
                        "task_ids": {},
                        "elapsed_ms": elapsed,
                        "mq_messages": self.mq.get_all_messages_for_display(limit=30),
                        "hr_gmail_batch_id": None,
                        "finance_export_files": None,
                    }

        result = {
            "agents_used":  agents,
            "responses":    {},
            "final_answer": "",
            "task_ids":     {},
            "elapsed_ms":   0,
            "mq_messages":  [],
            "hr_gmail_batch_id": None,
            "finance_export_files": None,
        }

        # 2. Optional A2A message queue (off by default — faster orchestration)
        from config import orchestrator_mq_enabled

        task_ids = {}
        if orchestrator_mq_enabled():
            for agent_type in agents:
                agent_receiver = AGENT_IDS.get(agent_type, f"agent-{agent_type}-001")
                msg_id = self.mq.send(
                    sender=self.agent_id,
                    receiver=agent_receiver,
                    topic="task",
                    payload={
                        "user_message": full_message,
                        "user_name":    user_name,
                        "agent_type":   agent_type,
                        "has_attachments": bool(attachments),
                    },
                    priority=2,
                )
                task_ids[agent_type] = msg_id

        result["task_ids"] = task_ids

        # 3. Execute agents in parallel (same context for each)
        responses: Dict[str, str] = {}

        def _run_one(agent_type: str) -> tuple:
            try:
                task_msg = self._agent_tasks.get(agent_type)
                agent_input = build_context_with_attachments(task_msg, attachments) if task_msg else full_message
                resp = self._invoke_agent(
                    agent_type,
                    agent_input,
                    user_name,
                    user_message_raw=task_msg or user_message,
                    attachments=attachments,
                    conversation_history=conversation_history,
                    user_role=user_role,
                )
                return agent_type, resp, None
            except Exception as e:
                return agent_type, f"Agent error: {e}", e

        max_workers = max(1, min(len(agents), 8))
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(_run_one, at): at for at in agents}
            for fut in as_completed(futures):
                agent_type, resp, err = fut.result()
                responses[agent_type] = resp
                if orchestrator_mq_enabled():
                    payload_resp = resp.get("final_answer", "") if isinstance(resp, dict) else resp
                    self.mq.send(
                        sender=AGENT_IDS.get(agent_type, agent_type),
                        receiver=self.agent_id,
                        topic="result",
                        payload={"response": payload_resp, "agent_type": agent_type, "error": str(err) if err else None},
                        reply_to=task_ids.get(agent_type),
                    )

        # Collect structured fields and flatten responses
        responses_flat = {}
        finance_export_files = []
        ui_payload = None
        bid = None
        hr_gmail_pending_cleared = False

        for at in agents:
            if at in responses:
                val = responses[at]
                if isinstance(val, dict):
                    responses_flat[at] = val.get("final_answer", "")
                    if val.get("ui_payload"):
                        ui_payload = val["ui_payload"]
                    if val.get("hr_gmail_batch_id"):
                        bid = val["hr_gmail_batch_id"]
                    if val.get("hr_gmail_pending_cleared"):
                        hr_gmail_pending_cleared = True
                    if val.get("finance_export_files"):
                        finance_export_files.extend(val["finance_export_files"])
                else:
                    responses_flat[at] = val

        result["responses"] = responses_flat

        from tools.hr_gmail_shortlist import extract_hr_gmail_batch_id, strip_hr_gmail_batch_marker

        if not bid:
            for _at, txt in responses_flat.items():
                b = extract_hr_gmail_batch_id(txt or "")
                if b:
                    bid = b
                    break
        if bid:
            result["hr_gmail_batch_id"] = bid
        if hr_gmail_pending_cleared:
            result["hr_gmail_pending_cleared"] = True

        for k in list(responses_flat.keys()):
            responses_flat[k] = strip_hr_gmail_batch_marker(responses_flat[k] or "")

        from tools.assistant_display import build_display_text, build_hr_shortlist_ui_payload
        from database.sqlite_db import hr_shortlist_get_batch

        if bid and not ui_payload:
            try:
                row = hr_shortlist_get_batch(bid)
                if row:
                    pl = row.get("payload") or {}
                    ui_payload = build_hr_shortlist_ui_payload(
                        {
                            "ok": True,
                            "batch_id": bid,
                            "drafts": pl.get("top") or [],
                            "role_title": (row.get("criteria") or "")[:120],
                            "emails_scanned": pl.get("emails_scanned", 0),
                            "attachments_parsed": pl.get("attachments_parsed", 0),
                            "filters_applied": (pl.get("session_memory") or {}).get("filters_applied") or {},
                        }
                    )
            except Exception:
                pass
        if ui_payload:
            result["ui_payload"] = ui_payload

        # 4. Merge responses (stable order matching original agent list)
        ordered = [(at, responses_flat[at]) for at in agents if at in responses_flat]
        if len(ordered) == 1:
            result["final_answer"] = ordered[0][1]
        else:
            parts = []
            agent_labels = {
                "general":      "Assistant",
                "hr_gmail":     "Gmail CV shortlist",
                "it_support":   "IT Support",
                "email":        "Email",
                "hr":           "HR",
                "recruitment":  "Recruitment Orchestrator",
                "finance":      "Finance",
                "documents":    "Documents",
            }
            for agent_type, resp in ordered:
                label = agent_labels.get(agent_type, agent_type.upper())
                parts.append(f"{label}:\n{resp}")
            result["final_answer"] = "\n\n---\n\n".join(parts)
        from tools.assistant_display import build_display_text, strip_markdown

        result["final_answer"] = strip_markdown(result.get("final_answer", ""))
        if clarify_prefix:
            result["final_answer"] = (
                clarify_prefix + "\n\n---\n\n" + (result.get("final_answer") or "")
            ).strip()
        if plan_limitations:
            lim = "\n".join(f"- {x}" for x in plan_limitations)
            result["final_answer"] = (
                result["final_answer"] + "\n\nUnable to complete:\n" + lim
            ).strip()
        result["display_answer"] = build_display_text(result.get("final_answer", ""), result.get("ui_payload"))

        if len(agents) > 1:
            try:
                from database.sqlite_db import add_notification

                add_notification(
                    "Multi-agent task completed",
                    f"Agents: {', '.join(agents)}",
                    "success",
                    "Orchestrator",
                )
            except Exception:
                pass

        result["elapsed_ms"]  = round((time.time() - start_time) * 1000)
        result["mq_messages"] = (
            self.mq.get_all_messages_for_display(limit=30)
            if orchestrator_mq_enabled()
            else []
        )
        result["finance_export_files"] = finance_export_files if finance_export_files else None

        return result

    def _invoke_agent(
        self,
        agent_type: str,
        user_message: str,
        user_name: str,
        user_message_raw: str = "",
        attachments: Optional[List[Dict[str, Any]]] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        user_role: str = "",
    ) -> str:
        """
        Invoke the correct LangGraph agent or recruitment pipeline.
        This is the A2A execution layer.
        """
        raw = (user_message_raw or user_message or "").strip()
        hist_prefix = _history_context_block(conversation_history)
        contextual = (hist_prefix + user_message) if hist_prefix else user_message

        if agent_type == "general":
            return run_general_assistant(raw, user_name, conversation_history)

        if agent_type == "hr_gmail":
            from tools.hr_gmail_shortlist import is_compose_email_to_person
            from tools.hr_email_intelligence import dispatch_hr_gmail_for_orchestrator, execute_hr_gmail_agent

            if is_compose_email_to_person(raw) and not _is_onboarding_workflow(
                raw, conversation_history
            ):
                return self._invoke_agent(
                    "email",
                    contextual,
                    user_name,
                    user_message_raw=raw,
                    attachments=attachments,
                    conversation_history=conversation_history,
                    user_role=user_role,
                )

            res = dispatch_hr_gmail_for_orchestrator(
                user_message=raw,
                conversation_history=conversation_history,
                user_name=user_name,
                user_role=user_role or "User",
                start_time=time.time(),
            )
            if res is not None:
                return res
            return execute_hr_gmail_agent(
                user_message=raw,
                conversation_history=conversation_history,
                user_name=user_name,
                user_role=user_role or "User",
            )

        if agent_type == "it_support":
            from graph.it_graph import it_graph
            state  = {"user_name": user_name, "it_problem": contextual}
            result = it_graph.invoke(state)
            return result.get("it_solution", "No solution returned.")

        elif agent_type == "email":
            from agents.auto_reply_agent import compose_office_email, generate_reply

            raw_task = (user_message_raw or user_message or "").strip()
            from tools.hr_gmail_shortlist import is_compose_email_to_person

            low = raw_task.lower()
            if (
                is_compose_email_to_person(raw_task)
                or any(
                    x in low
                    for x in (
                        "welcome email",
                        "draft",
                        "compose",
                        "write an email",
                        "send a welcome",
                        "send email to",
                        "email to ",
                        "send this email",
                        "interview",
                        "invitation",
                    )
                )
                or _is_onboarding_workflow(raw_task, conversation_history)
            ):
                drafted = compose_office_email(contextual, user_name)
                parsed = _parse_composed_email(drafted)
                compose_preflight = validate_compose_email_request(
                    raw_task, conversation_history
                )
                is_compose = is_compose_email_to_person(raw_task) and not _is_onboarding_workflow(
                    raw_task, conversation_history
                )
                may_send = _should_send_onboarding_email(raw_task, conversation_history)
                if is_compose:
                    may_send = (
                        compose_preflight.get("ok")
                        and not compose_preflight.get("draft_only")
                        and (
                            _user_confirmed_compose_send(raw_task, conversation_history)
                            or bool(_emails_in_user_text_only(raw_task, conversation_history))
                        )
                    )
                elif re.search(r"\b(?:email|send|mail|invite)\b", low):
                    may_send = may_send or bool(
                        _emails_in_user_text_only(raw_task, conversation_history)
                    )

                if may_send:
                    user_emails = _emails_in_user_text_only(raw_task, conversation_history)
                    resolved = (compose_preflight.get("recipient_email") or "").strip()
                    resolved_m = re.search(
                        r"\[Resolved recipient for send:\s*([^\]]+)\]",
                        contextual or "",
                    )
                    if resolved_m:
                        resolved = resolved_m.group(1).strip()
                    recipient = ""
                    if user_emails:
                        recipient = user_emails[-1]
                    elif resolved:
                        recipient = resolved
                    elif not is_compose:
                        facts = _extract_onboarding_facts(raw_task, conversation_history)
                        recipient = facts.get("email") or ""
                    if recipient:
                        status = _smtp_send_office_email(
                            recipient,
                            parsed.get("subject") or "Welcome to the Team",
                            parsed.get("body") or drafted,
                        )
                        drafted = (
                            f"{drafted}\n\n---\nEmail delivery (Gmail SMTP)\n{status}\n"
                            f"Recipient: {recipient}"
                        )
                    else:
                        drafted += (
                            "\n\n---\nEmail not sent: no verified recipient address. "
                            "Provide the recipient email or reply **send** after confirming the match above."
                        )
                elif is_compose:
                    drafted += (
                        "\n\n---\n**Draft only — not sent yet.** "
                        "Confirm the recipient and interview time, then reply **send** "
                        "(or include the correct email address)."
                    )
                return drafted
            state = {"email_content": contextual, "sender_name": user_name, "sender_email": ""}
            result = generate_reply(state)
            return result.get("body", "No reply generated.")

        elif agent_type == "hr":
            from graph.hr_graph import hr_graph

            state = {"action": "hr_query", "query": contextual, "user_name": user_name}
            result = hr_graph.invoke(state)
            return result.get("output", "No HR response.")

        elif agent_type == "recruitment":
            return self._run_recruitment_orchestration(raw, user_message, user_name, attachments)

        elif agent_type == "finance":
            from graph.finance_graph import finance_graph
            from tools.finance_document_export import detect_finance_export_intent

            attach_blob = ""
            if attachments:
                attach_blob = "\n\n".join(
                    f"### {a.get('name', 'file')}\n{(a.get('content') or '')[:12000]}"
                    for a in attachments
                )
            combined = f"{raw}\n{attach_blob}".strip()
            onboarding = _is_onboarding_workflow(raw, conversation_history)
            wants_export = detect_finance_export_intent(combined) or onboarding
            if wants_export:
                export_instruction = raw
                if onboarding:
                    facts = _extract_onboarding_facts(raw, conversation_history)
                    export_instruction = (
                        f"Generate payroll and salary breakdown PDF for new employee onboarding. "
                        f"Include offer letter summary if applicable. Facts: {facts}"
                    )
                fin_state: dict[str, Any] = {
                    "action": "export_documents",
                    "question": export_instruction,
                    "export_instruction": export_instruction,
                    "context": attach_blob or combined,
                    "data": attach_blob or combined,
                    "user_name": user_name,
                    "export_formats": ["pdf", "xlsx"] if onboarding else None,
                }
                fin_result = finance_graph.invoke(fin_state)
                files = fin_result.get("export_files") or []
                out = fin_result.get("output") or ""
                if files:
                    out += (
                        "\n\nDownloads: use the Finance document downloads section below this chat "
                        "(same browser session)."
                    )
                return {"final_answer": out, "finance_export_files": files}
            state = {"action": "query", "question": contextual, "context": attach_blob, "user_name": user_name}
            fin_result = finance_graph.invoke(state)
            return fin_result.get("output", "No finance response.")

        elif agent_type == "documents":
            from graph.documents_graph import documents_graph
            from tools.finance_document_export import run_finance_document_export

            msg_low = raw.lower()
            if any(k in msg_low for k in ("load drive", "sync google drive", "load files from drive", "import drive")):
                from tools.mcp_drive_client import DriveClient
                from database.vector_db import embed_documents
                from database.sqlite_db import get_session, DocumentMeta
                try:
                    client = DriveClient()
                    docs = client.load_documents(max_results=50)
                    if docs:
                        res = embed_documents(docs, "documents")
                        try:
                            s = get_session()
                            for d in docs:
                                s.add(DocumentMeta(
                                    file_name=d.get("file", ""),
                                    content_len=len(d.get("content", "")),
                                    source="drive",
                                    embedded=True
                                ))
                            s.commit()
                            s.close()
                        except Exception:
                            pass
                        return f"✅ Successfully synced and loaded {len(docs)} documents from Google Drive and embedded them in ChromaDB."
                    else:
                        return "📂 Google Drive synced, but no files were found or credentials are not configured."
                except Exception as e:
                    return f"❌ Google Drive sync failed: {e}"

            if _is_onboarding_workflow(raw, conversation_history):
                facts = _extract_onboarding_facts(raw, conversation_history)
                doc_req = (
                    f"Employment offer letter and onboarding summary for new hire. Facts: {facts}. "
                    f"Full request context:\n{contextual[:8000]}"
                )
                res = run_finance_document_export(
                    user_request=doc_req,
                    source_data=contextual[:12000],
                    user_name=user_name,
                    export_formats=["pdf", "docx"],
                )
                files = res.get("export_files") or []
                out = res.get("output") or ""
                if files:
                    out += (
                        "\n\nDownloads: use the Finance document downloads section below this chat."
                    )
                return {"final_answer": out, "finance_export_files": files}
            state = {"action": "qa", "query": contextual, "user_name": user_name, "documents": []}
            result = documents_graph.invoke(state)
            return result.get("output", "No documents response.")

        else:
            return f"Unknown agent type: {agent_type}"

    def _run_recruitment_orchestration(
        self,
        raw_msg: str,
        full_ctx: str,
        user_name: str,
        attachments: Optional[List[Dict[str, Any]]],
    ) -> str:
        """
        Multi-agent recruitment: parse → JD → match → shortlist → draft.
        If the user explicitly asks to **send** / **email** interview invitations,
        sends via Gmail (top sendable draft, or all sendable, from the shortlist).
        """
        import re

        from recruitment.pipeline import run_recruitment_pipeline, send_recruitment_email_drafts
        from database.sqlite_db import recruitment_get_workflow, recruitment_save_workflow, recruitment_log_audit

        cvs: List[Dict[str, Any]] = []
        jd_chunks: List[str] = [(raw_msg or "").strip()]
        for a in attachments or []:
            text = (a.get("content") or "").strip()
            if not text:
                continue
            name_l = (a.get("name") or "").lower()
            if any(k in name_l for k in ("jd", "job_desc", "job-description", "requisition", "specification")):
                jd_chunks.insert(0, text)
            else:
                cvs.append({
                    "name": a.get("name") or "Candidate",
                    "content": text,
                    "file_name": a.get("name") or "",
                })

        jd = "\n\n---\n\n".join(x for x in jd_chunks if x).strip()
        if not cvs:
            return (
                "**Recruitment** needs resume/CV file attachments. "
                "Put the job description in your message (or name a file with **JD** in the filename) "
                "and attach CVs as PDF/DOCX."
            )

        interview_hint = "As stated in your request — confirm after reply."
        m = re.search(
            r"(tomorrow|today|monday|tuesday|wednesday|thursday|friday|sat|sun)[^.\n]{0,100}("
            r"\d{1,2}:\d{2}\s*(a\.?m\.?|p\.?m\.?|am|pm)?|\d{1,2}\s*(a\.?m\.?|p\.?m\.?|am|pm))",
            raw_msg,
            re.I,
        )
        if m:
            interview_hint = m.group(0).strip()[:220]

        jd_len = len(jd or "")
        min_score = 45 if jd_len < 300 else 52

        res = run_recruitment_pipeline(
            job_description=jd or raw_msg,
            cvs=cvs,
            user_name=user_name,
            company="Our Company",
            role_title_hint="",
            interview_when=interview_hint,
            meeting_details="Confirm attendance by reply; calendar invite or link to follow.",
            top_n=5,
            min_match_score=min_score,
        )
        if not res.get("ok"):
            return f"**Recruitment Orchestrator:** {res.get('error', 'Run failed')}"

        drafts = res.get("email_drafts") or []
        wf_id = res.get("workflow_id") or ""
        auto_send = recruitment_user_requests_email_send(raw_msg)
        want_one = recruitment_user_wants_top_one_only(raw_msg)
        send_report = ""

        if auto_send and drafts:
            sendable_sorted = sorted(
                [d for d in drafts if d.get("sendable") and (d.get("recipient") or "").strip()],
                key=lambda x: -(x.get("match_score") or 0),
            )
            to_send = sendable_sorted[:1] if want_one else sendable_sorted[: min(10, len(sendable_sorted))]
            if not to_send:
                send_report = (
                    "\n\n### Email send\n**Not sent:** no draft had a **recipient email** parsed from the CV. "
                    "Put a clear `email: you@domain.com` line on each resume."
                )
            else:
                try:
                    send_r = send_recruitment_email_drafts(to_send)
                    sr = send_r.get("send_results") or {}
                    n = int(sr.get("emails_sent") or 0)
                    tot = int(sr.get("total") or 0)
                    if send_r.get("ok"):
                        send_report = f"\n\n### Email send (Gmail SMTP)\n**Delivered:** {n}/{tot} message(s)."
                        if send_r.get("partial"):
                            send_report += f"\n**Partial:** {send_r.get('error', '')}"
                    else:
                        send_report = f"\n\n### Email send\n**Failed:** {send_r.get('error', 'Unknown error')}"

                    wf_row = recruitment_get_workflow(wf_id) if wf_id else None
                    if wf_row and wf_id:
                        new_status = "completed"
                        if not send_r.get("ok"):
                            new_status = "pending_approval"
                        elif send_r.get("partial"):
                            new_status = "completed_with_errors"
                        recruitment_save_workflow(
                            workflow_id=wf_id,
                            user_name=wf_row.get("user_name") or user_name,
                            status=new_status,
                            role_title=wf_row.get("role_title") or res.get("role_title") or "",
                            company=wf_row.get("company") or "",
                            interview_when=wf_row.get("interview_when") or "",
                            state=wf_row.get("state") or {},
                            send_results=sr,
                            error_message=((send_r.get("error") or "")[:4000]) if not send_r.get("ok") else "",
                        )
                    if wf_id:
                        recruitment_log_audit(
                            wf_id,
                            "assistant_auto_send",
                            "EmailSendingAgent",
                            bool(send_r.get("ok")),
                            0,
                            {"recipients": [x.get("recipient") for x in to_send], "want_one": want_one},
                        )
                except Exception as ex:
                    send_report = f"\n\n### Email send\n**Error:** {ex}"
        elif auto_send and not drafts:
            send_report = (
                "\n\n### Email send\n**Not sent:** nobody reached the shortlist "
                f"(min score **{min_score}**). Try lowering expectations in the JD or attach clearer CVs."
            )

        header = "**Recruitment Orchestrator** (CV parse → JD → match → shortlist → drafts"
        if auto_send and "Delivered:" in send_report:
            header += " → **Gmail send**"
        header += ")"

        lines = [
            header,
            "",
            f"**Workflow ID:** `{wf_id}`",
            "",
            res.get("human_prompt", ""),
            "",
            "### Shortlist",
        ]
        for d in drafts:
            ok = "yes" if d.get("sendable") else "**missing email in CV**"
            lines.append(
                f"- **{d.get('candidate_name')}** — match **{d.get('match_score')}** — sendable: {ok}"
            )
        if drafts:
            preview = next((d for d in drafts if d.get("sendable")), drafts[0])
            lines += [
                "",
                "### First draft preview",
                "",
                f"**Subject:** {preview.get('subject', '')}",
                "",
                (preview.get("body") or "")[:2000],
            ]

        lines.append(send_report)

        if not auto_send:
            lines += [
                "",
                "To **send** interview emails from here, say e.g. **email them** or **send interview invitation** "
                "in the same request. Otherwise use **Assistant** to review candidates and approve send.",
            ]

        return "\n".join(lines)

    def get_queue_status(self) -> dict:
        return {
            "stats":    self.mq.get_stats(),
            "messages": self.mq.get_all_messages_for_display(limit=50),
        }

    def broadcast(self, message: str, sender_name: str = "Orchestrator"):
        """Broadcast a message to all agents."""
        self.mq.send(
            sender=self.agent_id,
            receiver="broadcast",
            topic="broadcast",
            payload={"message": message, "from": sender_name},
        )


# ── Singleton ─────────────────────────────────────────────────────────────────

orchestrator = Orchestrator()


def dispatch_user_prompt(
    user_message: str,
    user_name: str = "User",
    *,
    use_llm_intent: bool = True,
    attachments: Optional[List[Dict[str, Any]]] = None,
    allowed_agents: Optional[List[str]] = None,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    user_role: str = "",
) -> dict:
    """
    Public entry point: one user prompt → orchestrator → sub-agents → merged result.
    Same as ``orchestrator.route``; use whichever reads clearer in your integration.
    """
    return orchestrator.route(
        user_message,
        user_name,
        use_llm_intent=use_llm_intent,
        attachments=attachments,
        allowed_agents=allowed_agents,
        conversation_history=conversation_history,
        user_role=user_role,
    )


# ── Legacy helper (backward compat) ──────────────────────────────────────────

def route_to_agent(user_message: str, user_name: str = "User") -> dict:
    """Legacy wrapper kept for backward compatibility."""
    result = orchestrator.route(user_message, user_name, attachments=None)
    return {
        "user_message": user_message,
        "agent_used":   ", ".join(result["agents_used"]),
        "response":     result["final_answer"],
        "agents_used":  result["agents_used"],
        "responses":    result["responses"],
    }
