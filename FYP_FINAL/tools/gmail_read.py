"""
TOOLS/GMAIL_READ.PY
====================
Read emails from Gmail inbox via IMAP.
"""

import imaplib
import email
from email.utils import parseaddr


def read_emails(state: dict) -> dict:
    """
    Read the last N emails from Gmail inbox.
    Returns state with 'emails' list.
    """
    from config import GMAIL_EMAIL, GMAIL_APP_PASSWORD

    max_emails = state.get("max_emails", 5)

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_EMAIL, GMAIL_APP_PASSWORD)
        mail.select("inbox")

        status, data = mail.search(None, "ALL")
        mail_ids     = data[0].split()

        emails = []
        for num in mail_ids[-max_emails:]:
            try:
                status, msg_data = mail.fetch(num, "(RFC822)")
                msg              = email.message_from_bytes(msg_data[0][1])

                sender_name, sender_email = parseaddr(msg.get("From", ""))
                subject                   = msg.get("Subject", "No Subject")

                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            body = part.get_payload(decode=True).decode(errors="ignore")
                            break
                else:
                    body = msg.get_payload(decode=True).decode(errors="ignore")

                emails.append({
                    "from_name":  sender_name,
                    "from_email": sender_email,
                    "subject":    subject,
                    "body":       body[:500],
                })
            except Exception:
                continue

        mail.logout()
        state["emails"] = emails

    except Exception as e:
        state["emails"]       = []
        state["email_error"]  = str(e)

    return state
