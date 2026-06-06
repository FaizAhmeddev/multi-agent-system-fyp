"""
EMAIL SEARCH TOOL
=================
Searches through sent/inbox emails to find an email address by person's name.
Used by Coordinator Brain when user says "email Huzaifa" — 
it finds Huzaifa's email from past conversations.
"""

import imaplib
import email
import re
from email.utils import parseaddr
from config import GMAIL_EMAIL, GMAIL_APP_PASSWORD


def _name_matches_query(display_name: str, addr: str, query: str) -> bool:
    """Match full name, first name, or all tokens (e.g. Huzaifa Imran)."""
    q = (query or "").lower().strip()
    if not q:
        return False
    dn = (display_name or "").lower()
    ad = (addr or "").lower()
    if q in dn or q in ad:
        return True
    parts = [p for p in re.split(r"\s+", q) if len(p) > 1]
    if len(parts) >= 2:
        return all(p in dn or p in ad for p in parts)
    return parts[0] in dn if parts else False


def find_email_by_name(name: str) -> list:
    """
    Searches inbox and sent folder for emails from/to a person with given name.
    Returns a list of found email addresses matching that name.
    """
    name_lower = name.lower().strip()
    found = {}  # email_address -> display_name

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_EMAIL, GMAIL_APP_PASSWORD)

        # Search in both INBOX and Sent
        folders = ["INBOX", '"[Gmail]/Sent Mail"']

        for folder in folders:
            try:
                mail.select(folder)
                status, data = mail.search(None, "ALL")
                if status != "OK":
                    continue

                mail_ids = data[0].split()
                recent = mail_ids[-30:] if len(mail_ids) > 30 else mail_ids

                for num in reversed(recent):
                    try:
                        status, msg_data = mail.fetch(num, "(RFC822)")
                        msg = email.message_from_bytes(msg_data[0][1])

                        # Check From field
                        from_name, from_addr = parseaddr(msg.get("From", ""))
                        if _name_matches_query(from_name, from_addr, name_lower):
                            if from_addr and from_addr != GMAIL_EMAIL:
                                found[from_addr] = from_name or from_addr

                        # Check To field
                        to_field = msg.get("To", "")
                        to_name, to_addr = parseaddr(to_field)
                        if _name_matches_query(to_name, to_addr, name_lower):
                            if to_addr and to_addr != GMAIL_EMAIL:
                                found[to_addr] = to_name or to_addr

                    except Exception:
                        continue

            except Exception:
                continue

        mail.logout()

    except Exception as e:
        print(f"Email search error: {e}")

    # Return as list of dicts
    results = [{"name": v, "email": k} for k, v in found.items()]
    return results
