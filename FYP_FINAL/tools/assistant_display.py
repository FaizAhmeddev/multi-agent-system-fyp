"""
User-facing Assistant chat formatting — no raw markdown walls or internal markers.
"""

from __future__ import annotations

import re
from typing import Any

from tools.hr_gmail_shortlist import strip_hr_gmail_batch_marker


def strip_internal_markers(text: str) -> str:
    t = strip_hr_gmail_batch_marker(text or "")
    t = re.sub(r"\[\[HR_GMAIL_BATCH_ID:[^\]]+\]\]", "", t, flags=re.I)
    return t.strip()


def build_display_text(final_answer: str, ui_payload: dict[str, Any] | None) -> str:
    """Short plain-language line for the chat bubble."""
    if ui_payload:
        t = ui_payload.get("type") or ""
        if t == "hr_shortlist":
            n = len(ui_payload.get("candidates") or [])
            role = ui_payload.get("role_title") or "role"
            skills = ui_payload.get("stats", {}).get("required_skills") or []
            skill_txt = f" ({', '.join(skills)})" if skills else ""
            sent = ui_payload.get("send_result") or {}
            if sent.get("ok"):
                return (
                    f"Shortlisted {n} candidate(s) for {role}{skill_txt} and sent "
                    f"{sent.get('emails_sent', 0)} interview invitation(s)."
                )
            return (
                f"Shortlisted {n} candidate(s) for {role}{skill_txt}. "
                "Say who to invite (e.g. Send to all recommended, Invite top 2)."
            )
        if t == "email_list":
            n = ui_payload.get("count", 0)
            hint = ui_payload.get("filter_hint") or "inbox"
            return f"Found {n} email(s) matching {hint}."
        if t == "email_send":
            if ui_payload.get("ok"):
                return f"Sent {ui_payload.get('emails_sent', 0)} email(s) successfully."
            return ui_payload.get("message") or "Could not send emails."
        if t == "hr_error":
            return ui_payload.get("message") or "Request could not be completed."

    clean = strip_internal_markers(final_answer or "")
    if not clean:
        return "Done."
    # Collapse noisy markdown headers for generic agents
    lines = []
    for line in clean.splitlines():
        s = line.strip()
        if s.startswith("### ") or s.startswith("---"):
            continue
        if s.startswith("**Safety:**") or s.startswith("**Batch ID:**"):
            continue
        lines.append(line)
    short = "\n".join(lines).strip()
    if len(short) > 600:
        return short[:600].rsplit(" ", 1)[0] + "…"
    return short or "Done."


def build_hr_shortlist_ui_payload(res: dict[str, Any], *, send_result: dict | None = None) -> dict[str, Any]:
    drafts = res.get("drafts") or []
    fa = res.get("filters_applied") or {}
    return {
        "type": "hr_shortlist",
        "batch_id": res.get("batch_id"),
        "role_title": res.get("role_title") or "",
        "candidates": [
            {
                "candidate_id": d.get("candidate_id"),
                "candidate_name": d.get("candidate_name"),
                "match_score": d.get("match_score"),
                "status": d.get("status"),
                "key_skills": d.get("key_skills") or [],
                "experience_level": d.get("experience_level"),
                "recipient": d.get("recipient"),
                "sendable": d.get("sendable"),
                "hr_state": d.get("hr_state") or "pending",
            }
            for d in drafts
        ],
        "stats": {
            "emails_scanned": res.get("emails_scanned", 0),
            "attachments_parsed": res.get("attachments_parsed", 0),
            "required_skills": fa.get("required_skills") or res.get("required_skills") or [],
            "matched_after_filter": fa.get("matched_after_filter"),
        },
        "send_result": send_result,
    }


def build_email_list_ui_payload(emails: list[dict], *, filter_hint: str = "") -> dict[str, Any]:
    rows = []
    for em in emails[:40]:
        rows.append(
            {
                "from_name": em.get("from_name") or "",
                "from_email": em.get("from_email") or "",
                "subject": em.get("subject") or "",
                "date": em.get("date") or "",
                "snippet": em.get("body_snippet") or (em.get("body") or "")[:200],
                "attachment_count": em.get("attachment_count", 0),
                "classification": em.get("classification") or "",
            }
        )
    return {
        "type": "email_list",
        "count": len(rows),
        "filter_hint": filter_hint,
        "emails": rows,
    }


def prepare_assistant_chat_entry(orchestrator_result: dict[str, Any]) -> dict[str, Any]:
    ui = orchestrator_result.get("ui_payload")
    final = orchestrator_result.get("final_answer") or ""
    return {
        "role": "agent",
        "content": final,
        "display_content": build_display_text(final, ui),
        "ui_payload": ui,
        "agents": orchestrator_result.get("agents_used") or [],
        "elapsed_ms": orchestrator_result.get("elapsed_ms", 0),
    }


def orchestrator_result_with_ui(
    *,
    final_answer: str,
    agents_used: list[str],
    ui_payload: dict[str, Any] | None,
    hr_gmail_batch_id: str | None = None,
    hr_gmail_pending_cleared: bool = False,
    elapsed_ms: int = 0,
    responses: dict | None = None,
) -> dict[str, Any]:
    display = build_display_text(final_answer, ui_payload)
    return {
        "agents_used": agents_used,
        "responses": responses or {agents_used[0]: display} if agents_used else {},
        "final_answer": final_answer,
        "display_answer": display,
        "ui_payload": ui_payload,
        "hr_gmail_batch_id": hr_gmail_batch_id,
        "hr_gmail_pending_cleared": hr_gmail_pending_cleared,
        "elapsed_ms": elapsed_ms,
    }
