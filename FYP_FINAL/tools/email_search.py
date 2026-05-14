"""
EMAIL SEARCH TOOL
=================
Searches through sent/inbox emails to find an email address by person's name.
Used by Coordinator Brain when user says "email Huzaifa" — 
it finds Huzaifa's email from past conversations.
"""

import imaplib
import email
from email.utils import parseaddr
from config import GMAIL_EMAIL, GMAIL_APP_PASSWORD


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
                # Check last 100 emails only for speed
                recent = mail_ids[-100:] if len(mail_ids) > 100 else mail_ids

                for num in recent:
                    try:
                        status, msg_data = mail.fetch(num, "(RFC822)")
                        msg = email.message_from_bytes(msg_data[0][1])

                        # Check From field
                        from_name, from_addr = parseaddr(msg.get("From", ""))
                        if name_lower in from_name.lower() or name_lower in from_addr.lower():
                            if from_addr and from_addr != GMAIL_EMAIL:
                                found[from_addr] = from_name or from_addr

                        # Check To field
                        to_field = msg.get("To", "")
                        to_name, to_addr = parseaddr(to_field)
                        if name_lower in to_name.lower() or name_lower in to_addr.lower():
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
