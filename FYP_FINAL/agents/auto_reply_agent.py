"""
AGENTS/AUTO_REPLY_AGENT.PY
===========================
Generates intelligent AI replies to incoming emails.
"""

import os
import re


def _get_llm():
    from langchain_openai import ChatOpenAI
    from config import OPENAI_API_KEY
    os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY
    return ChatOpenAI(model="gpt-4o-mini", temperature=0.3)


def _looks_like_mern_developer_application(subject: str, email_content: str) -> bool:
    """True when the message appears to be about a MERN / full-stack JS developer role."""
    blob = f"{subject or ''}\n{email_content or ''}".lower()
    if re.search(r"\bmern\b", blob):
        return True
    if "mern developer" in blob or "mern stack" in blob:
        return True
    # Common application phrasing + stack hints
    stack_hits = sum(
        1 for k in ("mongodb", "express.js", "expressjs", "react.js", "nodejs", "node.js")
        if k in blob
    )
    if stack_hits >= 2 and ("developer" in blob or "engineer" in blob or "application" in blob):
        return True
    return False


def _mern_interview_selection_reply(sender_name: str) -> str:
    return f"""Dear {sender_name},

Thank you for your application and interest in the MERN Developer position.

We are pleased to inform you that you have been shortlisted. Congratulations: you have been selected to proceed to the interview stage.

We would like to invite you for an interview on Monday at 2:00 PM. Please reply to this email to confirm your attendance; we will share the venue or video meeting details upon confirmation.

We look forward to speaking with you.

Kind regards,
HR Team"""


def generate_reply(state: dict) -> dict:
    """LangGraph node: generate a reply to an email."""
    email_content = state.get("email_content", "")
    sender_name = state.get("sender_name", "Sir/Madam")
    subject = state.get("subject", "")

    if _looks_like_mern_developer_application(subject, email_content):
        state["body"] = _mern_interview_selection_reply(sender_name)
        return state

    try:
        llm = _get_llm()
        prompt = f"""You are a professional email assistant for an office.

You received an email from {sender_name}:
"{email_content}"

Write a polite, professional, and helpful reply.
- Keep it concise (3-5 sentences)
- Address the sender by name
- Acknowledge their message
- Answer any questions if possible
- Close professionally

Your reply:"""

        response = llm.invoke(prompt)
        state["body"] = response.content

    except Exception as e:
        state["body"] = f"Thank you for your email. We will get back to you shortly.\n\n[Auto-reply error: {e}]"

    return state
