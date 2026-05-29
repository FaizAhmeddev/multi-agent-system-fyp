"""
Send and verify one-time passwords via email (Gmail SMTP) and SMS (Twilio).
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

    subject = "Office Automation Pro — verification code"
    if purpose == "reset":
        subject = "Office Automation Pro — password reset code"
    body = (
        f"Your verification code is: {code}\n\n"
        "This code expires in 10 minutes. If you did not request this, "
        "you can ignore this message.\n\n"
        "— Office Automation Agents Pro"
    )

    try:
        from config import is_gmail_configured, DEMO_MODE

        if is_gmail_configured():
            from tools.gmail_send import send_email

            result = send_email(
                {"recipient": recipient, "subject": subject, "body": body}
            )
            status = result.get("send_status") or ""
            if status.startswith("✅"):
                return True, "Verification code sent to your email.", False
            return False, status or "Could not send email.", False

        if DEMO_MODE or _otp_dev_fallback_enabled():
            return True, "Email is not configured — use the code shown below (demo mode).", True

        return (
            False,
            "Email delivery is not configured. Set GMAIL_EMAIL and GMAIL_APP_PASSWORD in .env.",
            False,
        )
    except Exception as e:
        return False, f"Email error: {e}", False


def send_sms_otp(phone: str, code: str, purpose: str) -> tuple[bool, str, bool]:
    """
    Send OTP by SMS. Returns (success, message, dev_fallback_shown).
    """
    from database.sqlite_db import _normalize_phone

    phone = _normalize_phone(phone)
    if not phone:
        return False, "A valid phone number is required.", False

    try:
        from config import is_twilio_configured, DEMO_MODE

        if is_twilio_configured():
            ok, msg = _twilio_send(phone, code, purpose)
            return ok, msg, False

        if DEMO_MODE or _otp_dev_fallback_enabled():
            return True, "SMS is not configured — use the code shown below (demo mode).", True

        return (
            False,
            "SMS delivery is not configured. Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, "
            "and TWILIO_PHONE_FROM in .env.",
            False,
        )
    except Exception as e:
        return False, f"SMS error: {e}", False


def _otp_dev_fallback_enabled() -> bool:
    return os.environ.get("AUTH_OTP_DEV_FALLBACK", "true").lower() in (
        "1",
        "true",
        "yes",
    )


def _twilio_send(phone: str, code: str, purpose: str) -> tuple[bool, str]:
    import base64

    import requests

    from config import TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_FROM

    label = "verification" if purpose == "signup" else "password reset"
    body = f"Office Automation Pro {label} code: {code}. Valid for 10 minutes."
    url = (
        f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json"
    )
    auth = base64.b64encode(
        f"{TWILIO_ACCOUNT_SID}:{TWILIO_AUTH_TOKEN}".encode()
    ).decode()
    resp = requests.post(
        url,
        data={"From": TWILIO_PHONE_FROM, "To": phone, "Body": body},
        headers={"Authorization": f"Basic {auth}"},
        timeout=30,
    )
    if resp.status_code in (200, 201):
        return True, "Verification code sent to your phone."
    return False, f"SMS failed ({resp.status_code}): {resp.text[:200]}"
