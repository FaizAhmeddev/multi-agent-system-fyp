"""
Email Sending Agent — Gmail SMTP with retries and logging.

Used after **Recruitment AI → Approve send**, or from the **Assistant** path when the user
explicitly asks to send interview emails (orchestrator auto-send).
"""

from __future__ import annotations

import time
from typing import Any

from tools.gmail_send import send_email
from database.sqlite_db import log_email


def send_drafts_with_retries(
    drafts: list[dict[str, Any]],
    max_attempts: int = 3,
    base_delay_sec: float = 1.5,
) -> dict[str, Any]:
    """
    drafts: list of dicts with keys recipient, subject, body
    """
    results: list[dict[str, Any]] = []
    ok = 0
    for d in drafts:
        recipient = (d.get("recipient") or "").strip()
        subject = d.get("subject") or "Interview invitation"
        body = d.get("body") or ""
        last_status = ""
        for attempt in range(1, max_attempts + 1):
            st = send_email({"recipient": recipient, "subject": subject, "body": body})
            last_status = st.get("send_status", "")
            if "✅" in last_status or "sent" in last_status.lower():
                ok += 1
                try:
                    from config import GMAIL_EMAIL

                    log_email("sent", GMAIL_EMAIL, recipient, subject, body[:1500], auto_reply=False)
                except Exception:
                    pass
                results.append({"recipient": recipient, "status": "success", "attempts": attempt})
                break
            if attempt < max_attempts:
                time.sleep(base_delay_sec * attempt)
        else:
            results.append({"recipient": recipient, "status": "failed", "detail": last_status, "attempts": max_attempts})

    return {
        "status": "success" if ok == len(drafts) and drafts else ("partial" if ok else "failed"),
        "emails_sent": ok,
        "total": len(drafts),
        "details": results,
    }
