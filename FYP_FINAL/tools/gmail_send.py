"""
TOOLS/GMAIL_SEND.PY
====================
Send email via Gmail SMTP (SSL :465, with STARTTLS :587 fallback).
Credentials: set `GMAIL_EMAIL` and `GMAIL_APP_PASSWORD` in `.env` (see `.env.example`),
or set the same names as OS environment variables.
"""

from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage


def _smtp_credentials() -> tuple[str, str]:
    """Resolve (user, app_password) from env first, then config."""
    try:
        from config import GMAIL_EMAIL, GMAIL_APP_PASSWORD
    except Exception:
        GMAIL_EMAIL = ""
        GMAIL_APP_PASSWORD = ""

    mail_user = (os.environ.get("GMAIL_EMAIL") or GMAIL_EMAIL or "").strip()
    raw_pass = os.environ.get("GMAIL_APP_PASSWORD") or GMAIL_APP_PASSWORD or ""
    # App passwords are 16 characters; Google often displays them as 4×4 with spaces.
    mail_pass = raw_pass.replace(" ", "").strip()
    return mail_user, mail_pass


def _build_message(mail_user: str, recipient: str, subject: str, body: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = mail_user
    msg["To"] = recipient
    msg.set_content(body or "", subtype="plain", charset="utf-8")
    return msg


def _send_ssl(msg: EmailMessage, mail_user: str, mail_pass: str) -> None:
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as server:
        server.login(mail_user, mail_pass)
        server.send_message(msg)


def _send_starttls(msg: EmailMessage, mail_user: str, mail_pass: str) -> None:
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=60) as server:
        server.ehlo()
        server.starttls(context=ssl.create_default_context())
        server.ehlo()
        server.login(mail_user, mail_pass)
        server.send_message(msg)


def send_email(state: dict) -> dict:
    """
    Send an email.
    state must contain: recipient, subject, body
    """
    recipient = (state.get("recipient") or "").strip()
    subject = state.get("subject", "No Subject")
    body = state.get("body", "")

    if not recipient:
        state["send_status"] = "❌ No recipient specified."
        return state

    mail_user, mail_pass = _smtp_credentials()
    if not mail_user or not mail_pass:
        state["send_status"] = (
            "❌ Gmail not configured: set GMAIL_EMAIL and GMAIL_APP_PASSWORD "
            "in `.env` or environment variables."
        )
        return state

    msg = _build_message(mail_user, recipient, subject, body)
    attempts: list[str] = []

    for label, sender in (
        ("smtp.gmail.com:465 (SSL)", _send_ssl),
        ("smtp.gmail.com:587 (STARTTLS)", _send_starttls),
    ):
        try:
            sender(msg, mail_user, mail_pass)
            state["send_status"] = f"✅ Email sent to {recipient} via {label.split()[0]}"
            return state
        except Exception as e:
            attempts.append(f"{label}: {e}")

    state["send_status"] = "❌ Failed to send email. " + " | ".join(attempts)
    return state
