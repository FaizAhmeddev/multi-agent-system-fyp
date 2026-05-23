"""
TOOLS/GMAIL_READ.PY
====================
Read emails from Gmail inbox via IMAP — list, full body, and attachments.
"""

from __future__ import annotations

import base64
import email
import imaplib
import re
from email.header import decode_header
from email.utils import parsedate_to_datetime, parseaddr
from html import unescape
from typing import Any


def _decode_header_value(raw: str | None) -> str:
    if not raw:
        return ""
    parts: list[str] = []
    for frag, enc in decode_header(raw):
        if isinstance(frag, bytes):
            parts.append(frag.decode(enc or "utf-8", errors="replace"))
        else:
            parts.append(str(frag))
    return "".join(parts).strip()


def _html_to_text(html: str) -> str:
    if not html:
        return ""
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", html)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return unescape(text).strip()


def _decode_part_payload(part: email.message.Message) -> bytes:
    payload = part.get_payload(decode=True)
    if payload is None:
        raw = part.get_payload()
        return (raw or b"").encode("utf-8", errors="ignore") if isinstance(raw, str) else b""
    return payload


def _parse_message(msg: email.message.Message, uid: str) -> dict[str, Any]:
    sender_name, sender_email = parseaddr(_decode_header_value(msg.get("From")))
    subject = _decode_header_value(msg.get("Subject")) or "(No subject)"
    date_raw = msg.get("Date", "")
    try:
        date_str = parsedate_to_datetime(date_raw).strftime("%Y-%m-%d %H:%M") if date_raw else ""
    except Exception:
        date_str = date_raw or ""

    plain_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[dict[str, Any]] = []

    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            disp = (part.get("Content-Disposition") or "").lower()
            ctype = (part.get_content_type() or "").lower()
            filename = part.get_filename()
            if filename:
                filename = _decode_header_value(filename)
            if "attachment" in disp or (filename and ctype not in ("text/plain", "text/html")):
                data = _decode_part_payload(part)
                if not data:
                    continue
                attachments.append({
                    "filename": filename or f"attachment_{len(attachments) + 1}",
                    "content_type": ctype or "application/octet-stream",
                    "size": len(data),
                    "data_b64": base64.b64encode(data).decode("ascii"),
                })
                continue
            if ctype == "text/plain":
                plain_parts.append(_decode_part_payload(part).decode(errors="replace"))
            elif ctype == "text/html":
                html_parts.append(_decode_part_payload(part).decode(errors="replace"))
    else:
        ctype = (msg.get_content_type() or "").lower()
        raw = _decode_part_payload(msg).decode(errors="replace")
        if ctype == "text/html":
            html_parts.append(raw)
        else:
            plain_parts.append(raw)

    body_plain = "\n\n".join(p.strip() for p in plain_parts if p.strip())
    body_html = "\n\n".join(h.strip() for h in html_parts if h.strip())
    body = body_plain or _html_to_text(body_html) or "(No readable body)"

    return {
        "uid": str(uid),
        "from_name": sender_name or sender_email or "Unknown",
        "from_email": sender_email or "",
        "subject": subject,
        "date": date_str,
        "body": body,
        "body_snippet": body[:280] + ("…" if len(body) > 280 else ""),
        "has_html": bool(body_html),
        "attachment_count": len(attachments),
        "attachment_names": [a["filename"] for a in attachments],
        "attachments": attachments,
    }


def _connect_imap():
    from config import gmail_credentials

    email, password = gmail_credentials()
    mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    mail.login(email, password)
    mail.select("INBOX")
    return mail


def read_emails(state: dict) -> dict:
    """
    Read the last N emails from Gmail inbox.
    Returns state with 'emails' list (full parse including attachments).
    """
    max_emails = int(state.get("max_emails", 10) or 10)

    try:
        mail = _connect_imap()
        status, data = mail.search(None, "ALL")
        mail_ids = data[0].split() if data and data[0] else []

        emails: list[dict[str, Any]] = []
        for num in mail_ids[-max_emails:]:
            try:
                uid = num.decode() if isinstance(num, bytes) else str(num)
                status, msg_data = mail.fetch(num, "(RFC822)")
                if not msg_data or not msg_data[0]:
                    continue
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)
                emails.append(_parse_message(msg, uid))
            except Exception:
                continue

        mail.logout()
        emails.reverse()
        state["emails"] = emails

    except Exception as e:
        state["emails"] = []
        err = str(e)
        if "not enough arguments" in err.lower():
            from config import GmailNotConfiguredError
            try:
                from config import gmail_credentials
                gmail_credentials()
            except GmailNotConfiguredError as gnc:
                state["email_error"] = str(gnc)
            else:
                state["email_error"] = (
                    "Gmail LOGIN failed. Check GMAIL_EMAIL and GMAIL_APP_PASSWORD "
                    "(use a 16-character App Password, not your normal Gmail password)."
                )
        else:
            state["email_error"] = err

    return state


def search_inbox_messages(
    *,
    max_results: int = 25,
    since_date=None,
    on_date=None,
    sender: str = "",
    subject_contains: str = "",
    body_keyword: str = "",
    candidate_name: str = "",
) -> dict[str, Any]:
    """
    Search inbox with optional date/sender/subject/body filters.
    ``on_date`` restricts to a single calendar day; ``since_date`` is inclusive from that day.
    """
    from datetime import date as date_cls

    max_results = max(1, min(50, int(max_results or 10)))
    try:
        mail = _connect_imap()
        criteria = ["ALL"]
        if since_date:
            d = since_date if isinstance(since_date, date_cls) else since_date
            criteria = ["SINCE", d.strftime("%d-%b-%Y")]
        status, data = mail.search(None, *criteria)
        mail_ids = data[0].split() if data and data[0] else []
        scan = mail_ids[-max(200, max_results * 8) :] if mail_ids else []

        sender_l = (sender or "").lower()
        sub_l = (subject_contains or "").lower()
        kw_l = (body_keyword or "").lower()
        cand_l = (candidate_name or "").lower()

        emails: list[dict[str, Any]] = []
        for num in reversed(scan):
            if len(emails) >= max_results:
                break
            try:
                uid = num.decode() if isinstance(num, bytes) else str(num)
                status, msg_data = mail.fetch(num, "(RFC822)")
                if not msg_data or not msg_data[0]:
                    continue
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)
                parsed = _parse_message(msg, uid)
                date_raw = msg.get("Date", "")
                try:
                    msg_dt = parsedate_to_datetime(date_raw) if date_raw else None
                    msg_date = msg_dt.date() if msg_dt else None
                except Exception:
                    msg_date = None

                if on_date and msg_date and msg_date != on_date:
                    continue
                if since_date and msg_date and msg_date < since_date:
                    continue

                from_blob = f"{parsed.get('from_name', '')} {parsed.get('from_email', '')}".lower()
                if sender_l and sender_l not in from_blob:
                    continue
                if sub_l and sub_l not in (parsed.get("subject") or "").lower():
                    continue
                body_l = (parsed.get("body") or "").lower()
                subj_l = (parsed.get("subject") or "").lower()
                if kw_l and kw_l not in body_l and kw_l not in subj_l:
                    continue
                if cand_l and cand_l not in body_l and cand_l not in subj_l and cand_l not in from_blob:
                    continue

                emails.append(parsed)
            except Exception:
                continue

        mail.logout()
        return {"ok": True, "emails": emails, "count": len(emails)}
    except Exception as e:
        return {"ok": False, "error": str(e), "emails": []}


def get_email_by_uid(uid: str) -> dict[str, Any]:
    """Fetch a single inbox message by IMAP sequence id."""
    try:
        mail = _connect_imap()
        status, msg_data = mail.fetch(uid.encode() if isinstance(uid, str) else uid, "(RFC822)")
        if not msg_data or not msg_data[0]:
            mail.logout()
            return {"ok": False, "error": "Email not found"}
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)
        parsed = _parse_message(msg, uid)
        mail.logout()
        return {"ok": True, "email": parsed}
    except Exception as e:
        return {"ok": False, "error": str(e)}
