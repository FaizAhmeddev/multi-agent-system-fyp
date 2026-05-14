"""Email Drafting Agent — produces drafts only (no network I/O)."""

from __future__ import annotations

from typing import Any

from recruitment.llm_utils import get_chat_llm, invoke_json


def draft_interview_invitation(
    candidate_name: str,
    role_title: str,
    company: str,
    interview_when: str,
    meeting_details: str,
    strengths_hint: list[str],
) -> dict[str, Any]:
    llm = get_chat_llm(0.35)
    strengths = ", ".join((strengths_hint or [])[:4]) or "your relevant background"
    prompt = f"""Write a professional interview invitation email.

Company: {company}
Role: {role_title}
Candidate name: {candidate_name}
Interview schedule (verbatim from recruiter): {interview_when}
Meeting / logistics note: {meeting_details or "To be confirmed after you reply."}
Fit highlights to personalize lightly: {strengths}

Return ONLY JSON:
{{
  "subject": "clear email subject line",
  "body": "plain-text email body, warm professional tone, no emojis, under 220 words, include greeting with candidate name and sign-off from {company} recruiting team"
}}"""
    try:
        data = invoke_json(llm, prompt)
        return {
            "subject": str(data.get("subject") or f"Interview invitation — {role_title}"),
            "body": str(data.get("body") or ""),
        }
    except Exception as e:
        body = (
            f"Dear {candidate_name},\n\n"
            f"We would like to invite you to interview for the {role_title} position at {company}.\n"
            f"Proposed time: {interview_when}.\n"
            f"{meeting_details or 'We will confirm the meeting link or location after your reply.'}\n\n"
            f"Kind regards,\n{company} Recruiting Team\n"
            f"(Draft fallback: {e})"
        )
        return {"subject": f"Interview invitation — {role_title}", "body": body}
