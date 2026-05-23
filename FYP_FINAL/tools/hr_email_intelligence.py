"""
HR email intelligence — natural-language inbox search, CV shortlist, send, schedule.
Used by the unified Assistant (no separate Recruitment tab).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from tools.assistant_display import (
    build_email_list_ui_payload,
    build_hr_shortlist_ui_payload,
    build_display_text,
    orchestrator_result_with_ui,
)
from tools.hr_gmail_shortlist import (
    HR_GMAIL_BATCH_MARKER_PREFIX,
    HR_GMAIL_BATCH_MARKER_SUFFIX,
    approve_and_send_shortlist_batch,
    format_hr_gmail_approve_send_reply,
    handle_hr_recruitment_follow_up,
    parse_gmail_shortlist_prompt,
    run_gmail_shortlist_from_user_prompt,
    user_requests_hr_gmail_approve_send,
    user_requests_hr_recruitment_follow_up,
)


def _batch_marker(batch_id: str) -> str:
    return f"\n\n{HR_GMAIL_BATCH_MARKER_PREFIX}{batch_id}{HR_GMAIL_BATCH_MARKER_SUFFIX}"


def wants_auto_send_after_fetch(message: str) -> bool:
    low = (message or "").lower()
    cues = (
        "and send",
        "and email",
        "email them",
        "email him",
        "email her",
        "send invitation",
        "send interview",
        "invite them",
        "mail them",
        "send to shortlisted",
        "send invitations",
    )
    return any(c in low for c in cues)


def parse_email_search_prompt(message: str) -> dict[str, Any] | None:
    """Detect inbox browse / search commands (not CV shortlist pipeline)."""
    m = (message or "").strip()
    if len(m) < 10:
        return None
    low = m.lower()

    is_list = any(
        x in low
        for x in (
            "show email",
            "list email",
            "fetch email",
            "fetch the latest",
            "latest email",
            "read email",
            "inbox",
            "received on",
            "emails from",
            "email from",
            "search email",
            "find email",
            "candidate email",
            "summarize email",
            "classify email",
        )
    )
    if not is_list:
        return None
    if parse_gmail_shortlist_prompt(message):
        return None

    max_results = 10
    for pat in (
        r"(?:latest|last|recent)\s+(\d+)\s+(?:candidate\s+)?e-?mails?",
        r"(?:fetch|get|show|list)\s+(?:the\s+)?(?:latest\s+)?(\d+)\s+(?:candidate\s+)?e-?mails?",
        r"\b(\d+)\s+(?:candidate\s+)?e-?mails?\b",
    ):
        mm = re.search(pat, low, re.I)
        if mm:
            max_results = max(1, min(50, int(mm.group(1))))
            break

    on_date = None
    dm = re.search(
        r"(?:on|dated?|received\s+on)\s+(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{4})",
        low,
        re.I,
    )
    if dm:
        try:
            on_date = datetime.strptime(
                f"{dm.group(1)} {dm.group(2)[:3]} {dm.group(3)}", "%d %b %Y"
            ).date()
        except Exception:
            pass

    since_date = None
    sm = re.search(r"(?:since|after|from)\s+(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{4})", low, re.I)
    if sm:
        try:
            since_date = datetime.strptime(
                f"{sm.group(1)} {sm.group(2)[:3]} {sm.group(3)}", "%d %b %Y"
            ).date()
        except Exception:
            pass

    sender = ""
    sem = re.search(r"(?:from|sender)\s+([a-z0-9._@\s-]{3,80})", low, re.I)
    if sem:
        sender = sem.group(1).strip()

    subject = ""
    subm = re.search(r"subject\s+(?:contains?|like|is)\s+['\"]?([^'\".;,\n]{2,80})", m, re.I)
    if subm:
        subject = subm.group(1).strip()

    candidate = ""
    cnm = re.search(
        r"(?:candidate|applicant|named?)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
        message,
    )
    if cnm:
        candidate = cnm.group(1).strip()

    keywords = ""
    kwm = re.search(r"(?:keyword|containing|about|mentioning)\s+['\"]?([^'\".;,\n]{2,60})", m, re.I)
    if kwm:
        keywords = kwm.group(1).strip()
    elif re.search(r"\bpython\b", low):
        keywords = "python"

    classify = any(x in low for x in ("classify", "classification", "summarize", "summary", "categorize"))

    return {
        "max_results": max_results,
        "on_date": on_date,
        "since_date": since_date,
        "sender": sender,
        "subject_contains": subject,
        "candidate_name": candidate,
        "body_keyword": keywords,
        "classify": classify,
    }


def _classify_email_row(em: dict[str, Any]) -> str:
    sub = (em.get("subject") or "").lower()
    body = (em.get("body") or "").lower()[:2000]
    blob = f"{sub} {body}"
    if any(x in blob for x in ("cv", "resume", "curriculum vitae", "application for")):
        return "Candidate / CV"
    if any(x in blob for x in ("interview", "schedule", "availability")):
        return "Interview"
    if any(x in blob for x in ("offer", "joining", "onboarding")):
        return "Offer / Onboarding"
    if any(x in blob for x in ("follow up", "follow-up", "reminder", "checking in")):
        return "Follow-up"
    return "General"


def run_email_search(spec: dict[str, Any]) -> dict[str, Any]:
    from tools.gmail_read import search_inbox_messages

    res = search_inbox_messages(
        max_results=int(spec.get("max_results") or 10),
        on_date=spec.get("on_date"),
        since_date=spec.get("since_date"),
        sender=spec.get("sender") or "",
        subject_contains=spec.get("subject_contains") or "",
        body_keyword=spec.get("body_keyword") or "",
        candidate_name=spec.get("candidate_name") or "",
    )
    if not res.get("ok"):
        return {"ok": False, "error": res.get("error", "Inbox search failed.")}

    emails = res.get("emails") or []
    if spec.get("classify"):
        for em in emails:
            em["classification"] = _classify_email_row(em)

    parts = []
    if spec.get("on_date"):
        parts.append(f"date {spec['on_date']}")
    if spec.get("sender"):
        parts.append(f"sender “{spec['sender']}”")
    if spec.get("subject_contains"):
        parts.append(f"subject “{spec['subject_contains']}”")
    if spec.get("candidate_name"):
        parts.append(f"candidate “{spec['candidate_name']}”")
    if spec.get("body_keyword"):
        parts.append(f"keyword “{spec['body_keyword']}”")
    filter_hint = ", ".join(parts) if parts else "your criteria"

    return {"ok": True, "emails": emails, "filter_hint": filter_hint}


def try_hr_email_assistant_command(
    *,
    user_message: str,
    conversation_history: list[dict[str, str]] | None,
    user_name: str,
    user_role: str,
    start_time: float,
) -> dict[str, Any] | None:
    """
    Handle HR email / recruitment NL commands. Returns full orchestrator result dict or None.
    """
    import time

    msg = (user_message or "").strip()
    if not msg:
        return None

    elapsed = lambda: round((time.time() - start_time) * 1000)

    # 1) CV shortlist fetch (priority over generic email list)
    gspec = parse_gmail_shortlist_prompt(msg)
    if gspec:
        res = run_gmail_shortlist_from_user_prompt(
            user_message=msg,
            user_name=user_name,
            user_role=user_role,
        )
        if not res.get("ok"):
            ui = {"type": "hr_error", "message": res.get("error", "Could not run shortlist.")}
            return {
                **orchestrator_result_with_ui(
                    final_answer=res.get("error", "Failed."),
                    agents_used=["hr_gmail"],
                    ui_payload=ui,
                    elapsed_ms=elapsed(),
                ),
                "mq_messages": [],
                "finance_export_files": None,
                "task_ids": {},
            }

        send_result = None
        internal_lines = [
            f"Shortlisted {len(res.get('drafts') or [])} candidate(s) for {res.get('role_title', 'role')}.",
        ]
        bid = res.get("batch_id") or ""

        if wants_auto_send_after_fetch(msg) and bid:
            sr = approve_and_send_shortlist_batch(bid, user_message=msg)
            send_result = {
                "ok": bool(sr.get("ok")),
                "emails_sent": sr.get("emails_sent", 0),
                "error": sr.get("error"),
            }
            if sr.get("ok"):
                internal_lines.append(
                    f"Sent {sr.get('emails_sent', 0)} interview invitation(s) via Gmail."
                )
            else:
                internal_lines.append(sr.get("error") or "Send step needs clarification.")

        ui = build_hr_shortlist_ui_payload(res, send_result=send_result)
        final = "\n".join(internal_lines) + _batch_marker(bid)
        return {
            **orchestrator_result_with_ui(
                final_answer=final,
                agents_used=["hr_gmail"],
                ui_payload=ui,
                hr_gmail_batch_id=None if send_result and send_result.get("ok") else bid,
                hr_gmail_pending_cleared=bool(send_result and send_result.get("ok")),
                elapsed_ms=elapsed(),
                responses={"hr_gmail": build_display_text(final, ui)},
            ),
            "mq_messages": [],
            "finance_export_files": None,
            "task_ids": {},
        }

    # 2) Follow-up send / shortlist on existing batch
    if user_requests_hr_recruitment_follow_up(msg) or user_requests_hr_gmail_approve_send(msg):
        fu = handle_hr_recruitment_follow_up(
            user_message=msg,
            conversation_history=conversation_history,
            user_name=user_name,
            user_role=user_role,
        )
        if fu:
            ui = None
            bid = fu.get("hr_gmail_batch_id")
            if "sent" in (fu.get("final_answer") or "").lower() and fu.get("ok"):
                ui = {
                    "type": "email_send",
                    "ok": True,
                    "emails_sent": 1,
                    "message": build_display_text(fu.get("final_answer", ""), None),
                }
            elif not fu.get("ok") and "No shortlist batch" in (fu.get("final_answer") or ""):
                ui = {"type": "hr_error", "message": "Run a fetch first, e.g. Fetch the latest 10 candidate emails and find Python developers."}

            return {
                **orchestrator_result_with_ui(
                    final_answer=fu.get("final_answer", ""),
                    agents_used=fu.get("agents_used") or ["hr_gmail"],
                    ui_payload=ui,
                    hr_gmail_batch_id=bid,
                    hr_gmail_pending_cleared=bool(fu.get("hr_gmail_pending_cleared")),
                    elapsed_ms=elapsed(),
                ),
                "mq_messages": [],
                "finance_export_files": None,
                "task_ids": {},
            }

    # 3) Inbox search / summarize / classify
    espec = parse_email_search_prompt(msg)
    if espec:
        sr = run_email_search(espec)
        if not sr.get("ok"):
            ui = {"type": "hr_error", "message": sr.get("error")}
            return {
                **orchestrator_result_with_ui(
                    final_answer=sr.get("error", "Search failed."),
                    agents_used=["hr_gmail"],
                    ui_payload=ui,
                    elapsed_ms=elapsed(),
                ),
                "mq_messages": [],
                "finance_export_files": None,
                "task_ids": {},
            }
        emails = sr.get("emails") or []
        ui = build_email_list_ui_payload(emails, filter_hint=sr.get("filter_hint", ""))
        final = f"Listed {len(emails)} email(s) for {sr.get('filter_hint', 'inbox')}."
        return {
            **orchestrator_result_with_ui(
                final_answer=final,
                agents_used=["hr_gmail"],
                ui_payload=ui,
                elapsed_ms=elapsed(),
                responses={"hr_gmail": build_display_text(final, ui)},
            ),
            "mq_messages": [],
            "finance_export_files": None,
            "task_ids": {},
        }

    return None
