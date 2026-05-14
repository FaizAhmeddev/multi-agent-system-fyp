"""
AUTO REPLY MONITOR
==================
FIX: Uses thread-safe queue instead of st.session_state directly.
st.session_state cannot be accessed from background threads — that was the bug.
"""

import time
import email
import imaplib
import threading
import queue
from email.utils import parseaddr

from config import GMAIL_EMAIL, GMAIL_APP_PASSWORD
from agents.auto_reply_agent import generate_reply
from tools.gmail_send import send_email

_monitor_running = False
_monitor_thread = None

# Thread-safe queue for log messages — UI reads from this each rerun
_log_queue = queue.Queue()


def get_pending_logs() -> list:
    """Drain all pending log messages. Call from the UI (main) thread only."""
    messages = []
    try:
        while True:
            messages.append(_log_queue.get_nowait())
    except queue.Empty:
        pass
    return messages


def _do_monitor():
    global _monitor_running

    _log_queue.put("✅ Auto-reply monitor active. Checking every 30 seconds...")

    while _monitor_running:
        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(GMAIL_EMAIL, GMAIL_APP_PASSWORD)
            mail.select("inbox")

            status, data = mail.search(None, "UNSEEN")
            mail_ids = data[0].split()

            if not mail_ids:
                _log_queue.put("🔍 No new emails found.")
            else:
                _log_queue.put(f"📬 Found {len(mail_ids)} new email(s). Processing...")

            for num in mail_ids:
                if not _monitor_running:
                    break
                try:
                    status, msg_data = mail.fetch(num, "(RFC822)")
                    msg = email.message_from_bytes(msg_data[0][1])

                    sender_name, sender_email = parseaddr(msg.get("From", ""))
                    subject = msg.get("Subject", "No Subject")

                    if not sender_name:
                        sender_name = "Sir/Madam"

                    if sender_email == GMAIL_EMAIL:
                        continue

                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                body = part.get_payload(decode=True).decode(errors="ignore")
                                break
                    else:
                        body = msg.get_payload(decode=True).decode(errors="ignore")

                    if not body.strip():
                        body = subject

                    state = {
                        "email_content": body,
                        "sender_name": sender_name,
                        "sender_email": sender_email,
                        "subject": subject or "",
                    }
                    reply_state = generate_reply(state)
                    reply_state["recipient"] = sender_email
                    reply_state["subject"] = "Re: " + str(subject)

                    send_email(reply_state)

                    msg_text = f"📧 Auto-replied to: {sender_name} ({sender_email})"
                    print(msg_text)
                    _log_queue.put(msg_text)

                except Exception as e:
                    _log_queue.put(f"⚠️ Error processing email: {e}")

            mail.logout()

        except Exception as e:
            _log_queue.put(f"⚠️ Monitor error: {e}")

        for _ in range(30):
            if not _monitor_running:
                break
            time.sleep(1)

    _log_queue.put("🛑 Auto-reply monitor stopped.")


def start_monitor():
    global _monitor_running, _monitor_thread
    if _monitor_running:
        return False
    _monitor_running = True
    _monitor_thread = threading.Thread(target=_do_monitor, daemon=True)
    _monitor_thread.start()
    return True


def stop_monitor():
    global _monitor_running
    _monitor_running = False


def is_running():
    return _monitor_running
