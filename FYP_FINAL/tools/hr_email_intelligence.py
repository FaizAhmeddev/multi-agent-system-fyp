"""
HR email intelligence — natural-language inbox search, CV shortlist, send, schedule.
Used by the unified Assistant (no separate Recruitment tab).
"""

from __future__ import annotations

import re
import time
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
    extract_max_messages_from_prompt,
    approve_and_send_shortlist_batch,
    format_hr_gmail_approve_send_reply,
    handle_hr_recruitment_follow_up,
    parse_gmail_shortlist_prompt,
    prompt_has_hiring_focus,
    run_gmail_shortlist_from_user_prompt,
    build_shortlist_spec_from_message,
    is_inbox_list_only_request,
    message_is_new_shortlist_workflow,
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
        "send interview invitation",
        "interview invitation",
        "invite them",
        "mail them",
        "send to shortlisted",
        "send invitations",
    )
    return any(c in low for c in cues)


_MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"


def _parse_date_from_prompt(low: str) -> tuple[Any, Any]:
    """Return (on_date, since_date) from natural-language date phrases."""
    on_date = None
    since_date = None

    dm = re.search(
        rf"(?:on|dated?|received\s+on|emails?\s+on|email\s+on)\s+(\d{{1,2}})\s+{_MONTH}\s+(\d{{4}})",
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

    if not on_date:
        dm2 = re.search(rf"\b(\d{{1,2}})\s+{_MONTH}\s+(\d{{4}})\b", low, re.I)
        if dm2:
            try:
                on_date = datetime.strptime(
                    f"{dm2.group(1)} {dm2.group(2)[:3]} {dm2.group(3)}", "%d %b %Y"
                ).date()
            except Exception:
                pass

    if not on_date:
        dm3 = re.search(rf"\b({_MONTH})\s+(\d{{1,2}}),?\s+(\d{{4}})\b", low, re.I)
        if dm3:
            try:
                on_date = datetime.strptime(
                    f"{dm3.group(2)} {dm3.group(1)[:3]} {dm3.group(3)}", "%d %b %Y"
                ).date()
            except Exception:
                pass

    iso = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", low)
    if iso and not on_date:
        try:
            on_date = datetime(int(iso.group(1)), int(iso.group(2)), int(iso.group(3))).date()
        except Exception:
            pass

    dmy = re.search(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b", low)
    if dmy and not on_date:
        try:
            on_date = datetime(int(dmy.group(3)), int(dmy.group(2)), int(dmy.group(1))).date()
        except Exception:
            pass

    sm = re.search(
        rf"(?:since|after|from)\s+(\d{{1,2}})\s+{_MONTH}\s+(\d{{4}})",
        low,
        re.I,
    )
    if sm:
        try:
            since_date = datetime.strptime(
                f"{sm.group(1)} {sm.group(2)[:3]} {sm.group(3)}", "%d %b %Y"
            ).date()
        except Exception:
            pass

    return on_date, since_date


def _looks_like_inbox_browse(low: str) -> bool:
    """True when the user wants to list/read/search inbox mail (not CV shortlist)."""
    if re.search(
        r"\b(?:show|list|fetch|get|read|display|see|view|check|open)\b.{0,50}"
        r"\b(?:email|e-?mail|emails|inbox|gmail|mailbox|messages?)\b",
        low,
    ):
        return True
    if re.search(
        r"\b(?:email|e-?mail|emails|inbox|gmail|messages?)\b.{0,40}"
        r"\b(?:show|list|fetch|get|read|display|see|view)\b",
        low,
    ):
        return True
    if re.search(r"\b(?:last|latest|recent)\s+\d+\s+(?:candidate\s+)?(?:e-?mails?|emails?|messages?)\b", low):
        return True
    if re.search(
        r"\b(?:fetch|get|show|list|read)\s+(?:the\s+)?(?:latest|last|recent)\s+\d+\s+"
        r"(?:candidate\s+)?(?:e-?mails?|emails?)\b",
        low,
    ):
        return True
    if re.search(r"\b(?:fetch|get)\s+(?:the\s+)?(?:last|latest)\s+\d+\b", low):
        return True
    if re.search(r"\b(?:received\s+on|emails?\s+on|email\s+on|dated?)\b", low):
        return True
    if "inbox" in low and re.search(r"\b(?:show|list|fetch|get|read|check)\b", low):
        return True
    if re.search(r"\b(?:check|open|read)\s+(?:my\s+)?(?:inbox|mailbox)\b", low):
        return True
    if re.search(r"\b(?:latest|recent|new)\s+(?:e-?mails?|emails?|messages?)\b", low):
        return True
    if re.search(r"\bfetch\s+(?:e-?mails?|emails?|inbox|gmail)\b", low):
        return True
    if re.search(r"\b(?:show|get|list)\s+(?:me\s+)?(?:my\s+)?(?:e-?mails?|emails?|inbox)\b", low):
        return True
    return False


def message_looks_like_gmail_ops(message: str) -> bool:
    """True when the user wants Gmail inbox / CV shortlist (not generic 'email someone')."""
    m = (message or "").strip()
    if len(m) < 4:
        return False
    low = m.lower()

    has_gmail_verb = bool(
        re.search(
            r"\b(?:fetch|get|show|list|read|check|open|scan|shortlist|screen|rank|"
            r"inbox|gmail|mailbox|approve\s+and\s+send)\b",
            low,
        )
    )

    if re.search(
        r"\b(?:department|dept|salary|designation|joining|compensation)\s*:",
        low,
    ) and not has_gmail_verb:
        return False

    from tools.hr_gmail_shortlist import is_compose_email_to_person, is_direct_email_send_to_address

    if is_compose_email_to_person(m) or is_direct_email_send_to_address(m):
        return False

    if user_requests_hr_gmail_approve_send(m) or user_requests_hr_recruitment_follow_up(m):
        return True
    if parse_gmail_shortlist_prompt(m) or build_shortlist_spec_from_message(m):
        return True
    if classify_hr_email_intent(m) != "none":
        return True
    if _looks_like_inbox_browse(low):
        return True
    if has_gmail_verb and re.search(r"\b(?:e-?mails?|emails?|inbox|gmail|mailbox|messages?|cv|cvs)\b", low):
        return True
    if re.search(r"\b(?:shortlist|screen|rank)\b.{0,40}\b(?:cv|cvs|resume|candidate|python|developer)\b", low):
        return True
    return False


def classify_hr_email_intent(message: str) -> str:
    """
    Classify HR Gmail-related requests for routing.
    Returns: none | inbox_browse | cv_inventory | cv_shortlist
    """
    m = (message or "").strip()
    if len(m) < 6:
        return "none"
    low = m.lower()

    from tools.hr_gmail_shortlist import (
        _is_employee_onboarding_context,
        is_compose_email_to_person,
    )

    if is_compose_email_to_person(m):
        return "none"

    if _is_employee_onboarding_context(low):
        return "none"

    hiring = prompt_has_hiring_focus(m)
    shortlist_verbs = bool(
        re.search(r"\b(?:select|shortlist|pick|choose|rank|screen|hire)\b", low)
    )

    if hiring and re.search(
        r"\b(?:how many|how much|count|number of|total)\b.{0,50}\b(?:cv|cvs|resume|resumes|candidate)",
        low,
    ):
        return "cv_inventory"
    if hiring and re.search(
        r"\b(?:cv|cvs|resume|resumes)\b.{0,50}\b(?:how many|count|number)\b",
        low,
    ):
        return "cv_inventory"

    if is_inbox_list_only_request(m):
        return "inbox_browse"

    if parse_gmail_shortlist_prompt(m) or build_shortlist_spec_from_message(m):
        return "cv_shortlist"

    if _looks_like_inbox_browse(low):
        if hiring and shortlist_verbs:
            return "cv_shortlist"
        return "inbox_browse"

    if hiring and shortlist_verbs and re.search(
        r"\b(?:fetch|scan|pull|get|find)\b", low
    ):
        return "cv_shortlist"

    return "none"


def parse_email_search_prompt(message: str) -> dict[str, Any] | None:
    """Detect inbox browse / search commands (not CV shortlist pipeline)."""
    m = (message or "").strip()
    if len(m) < 6:
        return None
    low = m.lower()

    if classify_hr_email_intent(m) == "cv_shortlist":
        return None
    if not _looks_like_inbox_browse(low) and classify_hr_email_intent(m) != "inbox_browse":
        if not re.search(r"\b(?:email|e-?mail|emails|inbox|gmail)\b", low):
            return None

    max_results = 10
    for pat in (
        r"(?:latest|last|recent)\s+(\d+)\s+(?:candidate\s+)?e-?mails?",
        r"(?:fetch|get|show|list|read)\s+(?:the\s+)?(?:last|latest|recent)?\s*(\d+)\s+(?:e-?mails?|emails?|messages?)",
        r"(?:fetch|get)\s+(?:the\s+)?(?:last|latest)\s+(\d+)\b",
        r"\b(\d+)\s+(?:candidate\s+)?e-?mails?\b",
        r"\blast\s+(\d+)\s+(?:e-?mails?|emails?|messages?)\b",
    ):
        mm = re.search(pat, low, re.I)
        if mm:
            max_results = max(1, min(50, int(mm.group(1))))
            break

    on_date, since_date = _parse_date_from_prompt(low)

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
    else:
        for skill in ("python", "java", "javascript", "react", "django", "node"):
            if re.search(rf"\b{skill}\b", low):
                keywords = skill
                break

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


def parse_cv_inventory_prompt(message: str) -> dict[str, Any] | None:
    """Count CV attachments in recent inbox matching optional skill filters."""
    m = (message or "").strip()
    if classify_hr_email_intent(m) != "cv_inventory":
        return None
    low = m.lower()
    max_messages = extract_max_messages_from_prompt(m)
    skills: list[str] = []
    for skill in (
        "python",
        "java",
        "javascript",
        "typescript",
        "react",
        "django",
        "flask",
        "node",
        "sql",
        "devops",
        "aws",
        "machine learning",
        "data scientist",
    ):
        if re.search(rf"\b{re.escape(skill)}\b", low):
            skills.append(skill)
    return {"max_messages": max_messages, "skills": skills, "user_message": m}


def run_cv_inventory(spec: dict[str, Any]) -> dict[str, Any]:
    from tools.hr_gmail_shortlist import gmail_fetch_cv_attachments

    max_messages = int(spec.get("max_messages") or 50)
    skills = [s.lower() for s in (spec.get("skills") or [])]
    rows = gmail_fetch_cv_attachments(max_messages=max_messages)
    if not rows:
        return {
            "ok": True,
            "total_cvs": 0,
            "matched_cvs": 0,
            "skills": skills,
            "message": f"No CV attachments (PDF/DOCX) found in the last {max_messages} inbox messages.",
        }

    if not skills:
        return {
            "ok": True,
            "total_cvs": len(rows),
            "matched_cvs": len(rows),
            "skills": [],
            "message": f"Found {len(rows)} CV attachment(s) in the last {max_messages} inbox messages scanned.",
        }

    matched = []
    for row in rows:
        blob = f"{row.get('filename', '')} {row.get('content', '')}".lower()
        if all(s in blob for s in skills):
            matched.append(row)

    skill_txt = ", ".join(skills)
    return {
        "ok": True,
        "total_cvs": len(rows),
        "matched_cvs": len(matched),
        "skills": skills,
        "message": (
            f"Scanned {max_messages} recent messages: {len(rows)} CV attachment(s) total; "
            f"{len(matched)} mention **{skill_txt}**."
        ),
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


def _orchestrator_hr_result(
    *,
    final_answer: str,
    ui_payload: dict[str, Any] | None,
    elapsed_ms: int,
    hr_gmail_batch_id: str | None = None,
    hr_gmail_pending_cleared: bool = False,
) -> dict[str, Any]:
    return {
        **orchestrator_result_with_ui(
            final_answer=final_answer,
            agents_used=["hr_gmail"],
            ui_payload=ui_payload,
            hr_gmail_batch_id=hr_gmail_batch_id,
            hr_gmail_pending_cleared=hr_gmail_pending_cleared,
            elapsed_ms=elapsed_ms,
            responses={"hr_gmail": build_display_text(final_answer, ui_payload)},
        ),
        "mq_messages": [],
        "finance_export_files": None,
        "task_ids": {},
    }


def _handle_hr_shortlist_command(
    msg: str,
    *,
    user_name: str,
    user_role: str,
    elapsed_ms: int,
) -> dict[str, Any]:
    res = run_gmail_shortlist_from_user_prompt(
        user_message=msg,
        user_name=user_name,
        user_role=user_role,
    )
    if not res.get("ok"):
        return _orchestrator_hr_result(
            final_answer=res.get("error", "Failed."),
            ui_payload={"type": "hr_error", "message": res.get("error", "Could not run shortlist.")},
            elapsed_ms=elapsed_ms,
        )

    internal_lines = [
        f"Shortlisted {len(res.get('drafts') or [])} candidate(s) for {res.get('role_title', 'role')}.",
    ]
    bid = res.get("batch_id") or ""
    send_result = None

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
    return _orchestrator_hr_result(
        final_answer=final,
        ui_payload=ui,
        elapsed_ms=elapsed_ms,
        hr_gmail_batch_id=None if send_result and send_result.get("ok") else bid,
        hr_gmail_pending_cleared=bool(send_result and send_result.get("ok")),
    )


def execute_hr_gmail_agent(
    *,
    user_message: str,
    conversation_history: list[dict[str, str]] | None,
    user_name: str,
    user_role: str,
) -> str:
    """
    Single entry for orchestrator ``hr_gmail`` agent — inbox list, CV counts, or shortlist.
    Returns user-facing text (UI cards are built separately when using try_hr_email_assistant_command).
    """
    msg = (user_message or "").strip()
    intent = classify_hr_email_intent(msg)

    if (
        intent == "cv_shortlist"
        or parse_gmail_shortlist_prompt(msg)
        or build_shortlist_spec_from_message(msg)
        or message_is_new_shortlist_workflow(msg)
    ):
        res = run_gmail_shortlist_from_user_prompt(
            user_message=msg, user_name=user_name, user_role=user_role
        )
        if res.get("ok"):
            lines = [
                f"Shortlisted {len(res.get('drafts') or [])} candidate(s) for {res.get('role_title', 'role')}."
            ]
            bid = res.get("batch_id") or ""
            if wants_auto_send_after_fetch(msg) and bid:
                sr = approve_and_send_shortlist_batch(bid, user_message=msg)
                if sr.get("ok"):
                    lines.append(f"Sent {sr.get('emails_sent', 0)} interview invitation(s).")
                else:
                    lines.append(sr.get("error") or "Send needs clarification.")
            return "\n".join(lines) + _batch_marker(bid)
        return res.get("error", "Shortlist failed.")

    if user_requests_hr_recruitment_follow_up(msg) or user_requests_hr_gmail_approve_send(msg):
        fu = handle_hr_recruitment_follow_up(
            user_message=msg,
            conversation_history=conversation_history,
            user_name=user_name,
            user_role=user_role,
        )
        if fu:
            return fu.get("final_answer") or "Done."

    if intent == "cv_inventory":
        inv = parse_cv_inventory_prompt(msg)
        if inv:
            return run_cv_inventory(inv).get("message", "Done.")

    if intent == "inbox_browse":
        espec = parse_email_search_prompt(msg) or {
            "max_results": 10,
            "on_date": None,
            "since_date": None,
            "sender": "",
            "subject_contains": "",
            "candidate_name": "",
            "body_keyword": "",
            "classify": False,
        }
        sr = run_email_search(espec)
        if not sr.get("ok"):
            return sr.get("error", "Inbox search failed.")
        n = len(sr.get("emails") or [])
        hint = sr.get("filter_hint", "inbox")
        if n == 0:
            return (
                f"No emails found for {hint}. "
                "Try a different date, widen the search, or check Gmail credentials."
            )
        return f"Listed {n} email(s) for {hint}."

    if intent == "cv_shortlist":
        from tools.hr_gmail_shortlist import format_hr_gmail_orchestrator_reply

        res = run_gmail_shortlist_from_user_prompt(
            user_message=msg,
            user_name=user_name,
            user_role=user_role,
        )
        return format_hr_gmail_orchestrator_reply(res)

    espec = parse_email_search_prompt(msg)
    if espec:
        sr = run_email_search(espec)
        if sr.get("ok"):
            n = len(sr.get("emails") or [])
            return f"Listed {n} email(s) for {sr.get('filter_hint', 'inbox')}."
        return sr.get("error", "Inbox search failed.")

    return (
        "Tell me what you need with Gmail — for example:\n"
        "• “Fetch the last 10 emails”\n"
        "• “Show emails received on 20 May 2026”\n"
        "• “How many Python CVs are in the last 30 emails?”\n"
        "• “Fetch last 20 emails and shortlist 2 Python developers”"
    )


def dispatch_hr_gmail_for_orchestrator(
    *,
    user_message: str,
    conversation_history: list[dict[str, str]] | None,
    user_name: str,
    user_role: str,
    start_time: float,
) -> dict[str, Any] | None:
    """
    Single HR-Gmail entry for the orchestrator (inbox, shortlist, approve, follow-up).
    Replaces duplicate handlers in orchestrator_brain.
    """
    msg = (user_message or "").strip()
    if not msg:
        return None

    result = try_hr_email_assistant_command(
        user_message=msg,
        conversation_history=conversation_history,
        user_name=user_name,
        user_role=user_role,
        start_time=start_time,
    )
    if result is not None:
        return result

    intent = classify_hr_email_intent(msg)
    elapsed = round((time.time() - start_time) * 1000)

    if intent == "cv_shortlist" or parse_gmail_shortlist_prompt(msg):
        return _handle_hr_shortlist_command(
            msg, user_name=user_name, user_role=user_role, elapsed_ms=elapsed
        )

    if intent == "inbox_browse":
        espec = parse_email_search_prompt(msg) or {
            "max_results": 10,
            "on_date": None,
            "since_date": None,
            "sender": "",
            "subject_contains": "",
            "candidate_name": "",
            "body_keyword": "",
            "classify": False,
        }
        sr = run_email_search(espec)
        if not sr.get("ok"):
            return _orchestrator_hr_result(
                final_answer=sr.get("error", "Search failed."),
                ui_payload={"type": "hr_error", "message": sr.get("error")},
                elapsed_ms=elapsed,
            )
        emails = sr.get("emails") or []
        ui = build_email_list_ui_payload(emails, filter_hint=sr.get("filter_hint", ""))
        final = build_display_text(
            f"Listed {len(emails)} email(s) for {sr.get('filter_hint', 'inbox')}.",
            ui,
        )
        return _orchestrator_hr_result(final_answer=final, ui_payload=ui, elapsed_ms=elapsed)

    if intent == "cv_inventory":
        inv = parse_cv_inventory_prompt(msg)
        if inv:
            inv_res = run_cv_inventory(inv)
            ui = {
                "type": "hr_inventory",
                "total_cvs": inv_res.get("total_cvs", 0),
                "matched_cvs": inv_res.get("matched_cvs", 0),
                "skills": inv_res.get("skills") or [],
                "message": inv_res.get("message", ""),
            }
            return _orchestrator_hr_result(
                final_answer=inv_res.get("message", "Done."),
                ui_payload=ui,
                elapsed_ms=elapsed,
            )

    return None


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
    msg = (user_message or "").strip()
    if not msg:
        return None

    from tools.hr_gmail_shortlist import (
        _is_employee_onboarding_context,
        is_compose_email_to_person,
        is_direct_email_send_to_address,
    )

    thread_low = msg.lower()
    for entry in conversation_history or []:
        thread_low += "\n" + (entry.get("content") or "").lower()
    if _is_employee_onboarding_context(thread_low):
        return None
    if is_compose_email_to_person(msg) or is_direct_email_send_to_address(msg):
        return None

    intent = classify_hr_email_intent(msg)
    if intent == "none" and not (
        user_requests_hr_recruitment_follow_up(msg) or user_requests_hr_gmail_approve_send(msg)
    ):
        return None

    elapsed = lambda: round((time.time() - start_time) * 1000)

    # 1) New fetch + shortlist (+ optional send in same message) — before send-only follow-up
    if (
        classify_hr_email_intent(msg) == "cv_shortlist"
        or parse_gmail_shortlist_prompt(msg)
        or build_shortlist_spec_from_message(msg)
        or message_is_new_shortlist_workflow(msg)
    ):
        return _handle_hr_shortlist_command(
            msg, user_name=user_name, user_role=user_role, elapsed_ms=elapsed()
        )

    # 2) Follow-up on an existing shortlist batch (no new fetch in this message)
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
                ui = {
                    "type": "hr_error",
                    "message": (
                        "No CV shortlist batch in this thread. "
                        "For inbox hiring, try: fetch the last 20 emails and shortlist Python developers. "
                        "To email one person directly, say: Email to [name] at address@company.com — interview tomorrow at 3 PM."
                    ),
                }
            return _orchestrator_hr_result(
                final_answer=fu.get("final_answer", ""),
                ui_payload=ui,
                elapsed_ms=elapsed(),
                hr_gmail_batch_id=bid,
                hr_gmail_pending_cleared=bool(fu.get("hr_gmail_pending_cleared")),
            )

    # 3) Plain inbox browse (no recruitment shortlist)
    if intent == "inbox_browse":
        espec = parse_email_search_prompt(msg) or {
            "max_results": 10,
            "on_date": None,
            "since_date": None,
            "sender": "",
            "subject_contains": "",
            "candidate_name": "",
            "body_keyword": "",
            "classify": "classify" in msg.lower() or "summarize" in msg.lower(),
        }
        sr = run_email_search(espec)
        if not sr.get("ok"):
            return _orchestrator_hr_result(
                final_answer=sr.get("error", "Search failed."),
                ui_payload={"type": "hr_error", "message": sr.get("error")},
                elapsed_ms=elapsed(),
            )
        emails = sr.get("emails") or []
        ui = build_email_list_ui_payload(emails, filter_hint=sr.get("filter_hint", ""))
        final = build_display_text(
            f"Listed {len(emails)} email(s) for {sr.get('filter_hint', 'inbox')}.",
            ui,
        )
        return _orchestrator_hr_result(final_answer=final, ui_payload=ui, elapsed_ms=elapsed())

    # 4) CV count / inventory (recruitment-related, not full shortlist)
    if intent == "cv_inventory":
        inv = parse_cv_inventory_prompt(msg)
        if inv:
            result = run_cv_inventory(inv)
            ui = {
                "type": "hr_inventory",
                "total_cvs": result.get("total_cvs", 0),
                "matched_cvs": result.get("matched_cvs", 0),
                "skills": result.get("skills") or [],
                "message": result.get("message", ""),
            }
            return _orchestrator_hr_result(
                final_answer=result.get("message", "Done."),
                ui_payload=ui,
                elapsed_ms=elapsed(),
            )

    # 5) CV shortlist (intent-only fallback)
    if intent == "cv_shortlist":
        return _handle_hr_shortlist_command(
            msg, user_name=user_name, user_role=user_role, elapsed_ms=elapsed()
        )

    return None
