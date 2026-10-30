"""Gmail through IMAP and SMTP with an app password (GMAIL_EMAIL, GMAIL_APP_PASSWORD).

This is how the original FYP read and sent mail, and it needs no Google Cloud project.
  IMAP  imap.gmail.com:993 (SSL). The mailbox is opened read-only and messages are fetched
        with BODY.PEEK, so reading never marks anything as read.
        Searches use Gmail's own search syntax through the X-GM-RAW extension
        (for example "from:hr@company.com has:attachment newer_than:30d").
  SMTP  smtp.gmail.com:465 (SSL). Sending is idempotent through the local send ledger.
Message ids are Gmail's stable X-GM-MSGID values, so the same id works across sessions.
Attachments can only be sent from AgentsMind's own document folders (data/hr_documents,
data/hr_reports), never from anywhere else on the computer.
"""
from __future__ import annotations

import email
import hashlib
import imaplib
import logging
import mimetypes
import os
import re
import smtplib
import ssl
from datetime import UTC, datetime
from email.header import decode_header, make_header
from email.message import EmailMessage, Message
from email.utils import make_msgid, parsedate_to_datetime
from pathlib import Path

from .extract import ExtractError, kind_of, text_of

log = logging.getLogger("workspace_mcp.imap")
IMAP_HOST, IMAP_PORT = "imap.gmail.com", 993
SMTP_HOST, SMTP_PORT = "smtp.gmail.com", 465
TIMEOUT = 30
PREVIEW_BYTES = 60_000  # inbox lists: headers and text, never the attachments
MAX_BODY = 100_000
REPO_ROOT = Path(__file__).resolve().parents[2]


def attachment_roots() -> list[Path]:
    """Folders whose files may be attached to an email: AgentsMind's HR letters and reports, files attached in
    the chat, and the CV folders (so a CV can be forwarded)."""
    data = Path(os.environ.get("WORKSPACE_DATA_DIR") or REPO_ROOT / "data")
    roots = [(data / "hr_documents").resolve(), (data / "hr_reports").resolve(), (data / "chat_uploads").resolve()]
    try:
        from .extras import cv_dirs

        roots += cv_dirs()
    except Exception:  # noqa: BLE001,S110 - CV folders are optional
        pass
    return roots


def safe_attachment(path: str) -> Path:
    p = Path(path).resolve()
    if not any(p.is_relative_to(r) for r in attachment_roots()):
        raise PermissionError("Attachments can only come from AgentsMind's HR documents and reports folders.")
    if not p.is_file():
        raise FileNotFoundError(f"Attachment not found: {p.name}")
    if p.stat().st_size > 20 * 1024 * 1024:
        raise ValueError(f"{p.name} is larger than 20 MB.")
    return p


def _dec(v: str | None) -> str:
    if not v:
        return ""
    try:
        return str(make_header(decode_header(v)))
    except Exception:  # noqa: BLE001 - malformed header: show it raw
        return v


def _body(msg: Message) -> str:
    html = None
    for part in msg.walk() if msg.is_multipart() else [msg]:
        if part.get_content_maintype() == "multipart" or part.get_filename():
            continue
        ct = part.get_content_type()
        payload = part.get_payload(decode=True) or b""
        charset = part.get_content_charset() or "utf-8"
        if ct == "text/plain":
            return payload.decode(charset, errors="replace")
        if ct == "text/html" and html is None:
            html = payload.decode(charset, errors="replace")
    if html:
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()
    return ""


def _attachments(msg: Message) -> list[tuple[int, str, str, bytes]]:
    out = []
    for part in msg.walk():
        fn = part.get_filename()
        if not fn or part.get_content_maintype() == "multipart":
            continue
        out.append((len(out), _dec(fn), part.get_content_type(), part.get_payload(decode=True) or b""))
    return out


class GmailIMAP:
    mode = "imap"

    def __init__(self, address: str, app_password: str):
        self.address = address.strip()
        self.password = app_password.replace(" ", "")
        from .backends import _ledger

        self.ledger = _ledger("workspace_imap_sent.db")

    # ------------------------------------------------------------------ connection
    def _imap(self, all_mail: bool = False) -> imaplib.IMAP4_SSL:
        """all_mail: open Gmail's "All Mail" (every label, archived and sent mail too), used to find CVs."""
        from .backends import WorkspaceError

        try:
            c = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, ssl_context=ssl.create_default_context(), timeout=TIMEOUT)
            c.login(self.address, self.password)
        except imaplib.IMAP4.error as exc:
            raise WorkspaceError("Gmail refused the sign-in. Check GMAIL_EMAIL and GMAIL_APP_PASSWORD in .env "
                                 "(an app password from Google Account > Security > App passwords).") from exc
        except OSError as exc:
            raise WorkspaceError(f"Could not reach Gmail ({type(exc).__name__}). Check the internet connection.") from exc
        box = _all_mail_box(c) if all_mail else None
        c.select(box or "INBOX", readonly=True)
        return c

    @staticmethod
    def _search(c: imaplib.IMAP4_SSL, raw: str) -> list[bytes]:
        if raw:
            typ, data = c.uid("SEARCH", "X-GM-RAW", '"' + raw.replace("\\", " ").replace('"', " ") + '"')
        else:
            typ, data = c.uid("SEARCH", "ALL")
        if typ != "OK":
            return []
        return (data[0] or b"").split()

    @staticmethod
    def _fetch(c: imaplib.IMAP4_SSL, uid: bytes) -> tuple[Message, dict[str, str]] | None:
        typ, data = c.uid("FETCH", uid, "(X-GM-MSGID X-GM-THRID FLAGS BODY.PEEK[])")
        if typ != "OK" or not data or not isinstance(data[0], tuple):
            return None
        head = data[0][0].decode(errors="replace")
        meta = {"msgid": (re.search(r"X-GM-MSGID (\d+)", head) or [None, ""])[1],
                "thrid": (re.search(r"X-GM-THRID (\d+)", head) or [None, ""])[1],
                "seen": "\\Seen" in head}
        return email.message_from_bytes(data[0][1]), meta

    @staticmethod
    def _fetch_many(c: imaplib.IMAP4_SSL, uids: list[bytes], limit: int | None = None
                    ) -> list[tuple[Message, dict[str, str]]]:
        """One FETCH for several messages (one round trip instead of one per message). With limit, only the
        first `limit` bytes of each message are downloaded: enough for headers and the text, not attachments."""
        if not uids:
            return []
        part = f"BODY.PEEK[]<0.{limit}>" if limit else "BODY.PEEK[]"
        typ, data = c.uid("FETCH", b",".join(uids), f"(UID X-GM-MSGID X-GM-THRID FLAGS {part})")
        if typ != "OK" or not data:
            return []
        by_uid: dict[bytes, tuple[Message, dict[str, str]]] = {}
        in_order: list[tuple[Message, dict[str, str]]] = []
        for i, item in enumerate(data):
            if not isinstance(item, tuple):
                continue
            head = item[0].decode(errors="replace")
            nxt = data[i + 1] if i + 1 < len(data) else b""
            if isinstance(nxt, bytes):  # some servers send UID/FLAGS after the message text
                head += " " + nxt.decode(errors="replace")
            meta = {"msgid": (re.search(r"X-GM-MSGID (\d+)", head) or [None, ""])[1],
                    "thrid": (re.search(r"X-GM-THRID (\d+)", head) or [None, ""])[1],
                    "seen": "\\Seen" in head}
            got = (email.message_from_bytes(item[1]), meta)
            in_order.append(got)
            uid = (re.search(r"\bUID (\d+)", head) or [None, ""])[1].encode()
            if uid:
                by_uid[uid] = got
        if not by_uid:
            return in_order  # no UID in the answer: keep the server's order
        return [by_uid[u] for u in uids if u in by_uid]

    def _mail(self, msg: Message, meta: dict):
        from .backends import Mail

        body = _body(msg)
        cut = len(body) > MAX_BODY
        try:
            date = parsedate_to_datetime(msg.get("Date")).astimezone(UTC).isoformat(timespec="seconds")
        except Exception:  # noqa: BLE001 - missing or odd Date header
            date = ""
        return Mail(id=meta["msgid"], thread_id=meta["thrid"], sender=_dec(msg.get("From")), to=_dec(msg.get("To")),
                    subject=_dec(msg.get("Subject")) or "(no subject)", date=date,
                    snippet=re.sub(r"\s+", " ", body)[:200], body=body[:MAX_BODY], unread=not meta["seen"],
                    body_truncated=cut)

    # ------------------------------------------------------------------ MailBackend
    def inbox(self, max_results, unread_only, query, page_token):
        raw = " ".join(x for x in ("is:unread" if unread_only else "", query or "") if x)
        c = self._imap()
        try:
            uids = self._search(c, raw)
            uids.reverse()  # newest first
            start = int(page_token or 0)
            page = uids[start:start + max_results]
            out = [self._mail(*got) for got in self._fetch_many(c, page, limit=PREVIEW_BYTES)]
        finally:
            _logout(c)
        nxt = str(start + max_results) if start + max_results < len(uids) else None
        return out, nxt

    def send(self, *, key, to, subject, body, cc, thread_id, in_reply_to, attachments=()):
        from .backends import SentMail, WorkspaceError

        prior = self.ledger.get(key)
        if prior:
            return prior
        msg = EmailMessage()
        msg["From"] = self.address
        msg["To"] = ", ".join(to)
        if cc:
            msg["Cc"] = ", ".join(cc)
        msg["Subject"] = subject
        msg["Message-ID"] = make_msgid(domain=self.address.split("@")[-1])
        msg["X-AgentsMind-Key"] = hashlib.sha256(key.encode()).hexdigest()[:24]
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to
        msg.set_content(body)
        names = []
        for a in attachments:
            p = safe_attachment(a)
            ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            main, sub = ctype.split("/", 1)
            msg.add_attachment(p.read_bytes(), maintype=main, subtype=sub, filename=p.name)
            names.append(p.name)
        try:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ssl.create_default_context(), timeout=TIMEOUT) as s:
                s.login(self.address, self.password)
                s.send_message(msg)
        except smtplib.SMTPAuthenticationError as exc:
            raise WorkspaceError("Gmail refused the sign-in for sending. Check GMAIL_APP_PASSWORD in .env.") from exc
        except (smtplib.SMTPException, OSError) as exc:
            raise WorkspaceError(f"Sending failed ({type(exc).__name__}: {exc}).") from exc
        sent = SentMail(message_id=msg["Message-ID"], thread_id=thread_id, to=to, subject=subject, sent=True,
                        already_sent=False, at=datetime.now(UTC).isoformat(timespec="seconds"),
                        extra={"cc": cc, "attachments": names})
        self.ledger.put(key, sent)
        return sent

    # ------------------------------------------------------------------ attachments (CV gathering)
    def find_attachments(self, query: str, max_messages: int) -> list[dict]:
        raw = " ".join(x for x in ("has:attachment", query) if x)
        c = self._imap(all_mail=True)
        out = []
        try:
            uids = self._search(c, raw)
            uids.reverse()
            self.last_searched = len(uids)
            for msg, meta in self._fetch_many(c, uids[:max_messages]):
                m = self._mail(msg, meta)
                for idx, name, ctype, data in _attachments(msg):
                    if kind_of(name, ctype) is None:
                        continue
                    out.append({"message_id": m.id, "attachment": idx, "filename": name, "mime_type": ctype,
                                "size": len(data), "sender": m.sender, "subject": m.subject, "date": m.date})
        finally:
            _logout(c)
        return out

    def read_attachment(self, message_id: str, attachment: int) -> dict:
        from .backends import WorkspaceError

        if not message_id.isdigit():
            raise WorkspaceError("Unknown message id.")
        c = self._imap(all_mail=True)
        try:
            typ, data = c.uid("SEARCH", "X-GM-MSGID", message_id)
            uids = (data[0] or b"").split() if typ == "OK" else []
            if not uids:
                raise WorkspaceError("That email was not found.")
            got = self._fetch(c, uids[0])
        finally:
            _logout(c)
        if not got:
            raise WorkspaceError("That email could not be read.")
        msg, meta = got
        atts = _attachments(msg)
        if attachment < 0 or attachment >= len(atts):
            raise WorkspaceError("That attachment does not exist.")
        _, name, ctype, blob = atts[attachment]
        try:
            text, how = text_of(blob, name, ctype)
        except ExtractError as exc:
            raise WorkspaceError(str(exc)) from exc
        m = self._mail(msg, meta)
        return {"message_id": m.id, "filename": name, "mime_type": ctype, "text": text[:MAX_BODY],
                "truncated": len(text) > MAX_BODY, "extracted_from": how, "sender": m.sender, "subject": m.subject,
                "date": m.date, "saved_path": _keep_copy(m.id, name, blob)}


def _keep_copy(message_id: str, name: str, blob: bytes) -> str:
    """A local copy of a CV read from Gmail (data/hr_documents/cvs), so it can be forwarded by email."""
    data = Path(os.environ.get("WORKSPACE_DATA_DIR") or REPO_ROOT / "data")
    d = data / "hr_documents" / "cvs"
    try:
        d.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w.\- ()]+", "_", Path(name).name).strip(" .") or "attachment"
        p = d / f"{message_id}_{safe[:100]}"
        if not p.exists():
            p.write_bytes(blob)
        return str(p.resolve())
    except OSError:
        return ""


def _all_mail_box(c: imaplib.IMAP4_SSL) -> str | None:
    """The quoted name of the mailbox flagged \\All ("[Gmail]/All Mail", localized in some accounts)."""
    try:
        typ, data = c.list()
    except imaplib.IMAP4.error:
        return None
    for line in data or []:
        t = line.decode(errors="replace") if isinstance(line, bytes) else str(line)
        if "\\All" in t:
            m = re.search(r'"((?:[^"\\]|\\.)*)"\s*$', t) or re.search(r"(\S+)\s*$", t)
            if m:
                return '"' + m.group(1) + '"'
    return None


def _logout(c: imaplib.IMAP4_SSL) -> None:
    try:
        c.logout()
    except Exception:  # noqa: BLE001 - connection already gone
        log.debug("IMAP logout failed", exc_info=True)
