"""
Send one-time passwords by email (Gmail SMTP).
"""

from __future__ import annotations

import os
import random
import string


def generate_otp(length: int = 6) -> str:
    return "".join(random.choices(string.digits, k=length))


def send_email_otp(recipient: str, code: str, purpose: str) -> tuple[bool, str, bool]:
    """
    Send OTP by email. Returns (success, message, dev_fallback_shown).
    """
    recipient = (recipient or "").strip()
    if not recipient:
        return False, "Email address is required.", False

    subject = "Office Automation Pro - verification code"
    if purpose == "reset":
        subject = "Office Automation Pro - password reset code"
    body = (
        f"Your verification code is: {code}\n\n"
        "This code expires in 10 minutes. If you did not request this, "
        "you can ignore this message.\n\n"
        "- Office Automation Agents Pro"
    )

    try:
        from config import DEMO_MODE, is_gmail_configured

        if is_gmail_configured():
            from tools.gmail_send import send_email

            result = send_email(
                {"recipient": recipient, "subject": subject, "body": body}
            )
            status = result.get("send_status") or ""
            if "Email sent" in status or status.startswith("✅") or status.startswith("âœ"):
                return True, "Verification code sent to your email.", False
            return False, status or "Could not send email.", False

        if DEMO_MODE or _otp_dev_fallback_enabled():
            return True, "Email is not configured - use the code shown below (demo mode).", True

        return (
            False,
            "Email delivery is not configured. Set GMAIL_EMAIL and GMAIL_APP_PASSWORD in .env.",
            False,
        )
    except Exception as e:
        return False, f"Email error: {e}", False


def _otp_dev_fallback_enabled() -> bool:
    return os.environ.get("AUTH_OTP_DEV_FALLBACK", "true").lower() in (
        "1",
        "true",
        "yes",
    )
