"""Gmail and Drive backends for workspace-mcp.

Sandbox   sandbox_data/inbox.json and sandbox_data/drive/ (synthetic). Sent mail goes to
          data/workspace_sandbox_outbox.jsonl and is never delivered. simulated=True.
Google    Gmail API v1 (gmail.readonly, gmail.send) and Drive API v3 (drive.readonly),
          sharing one encrypted OAuth token with calendar-mcp.

Email and file text comes from outside the company and is untrusted: every result that
carries such text has untrusted=True, and the core wraps it in delimiters before any
model sees it. Sending mail is idempotent through a local ledger keyed by the
idempotency key (Gmail itself has no idempotency key).
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import mimetypes
import os
import re
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger("workspace_mcp")
REPO_ROOT = Path(__file__).resolve().parents[2]
MAX_TEXT = 100_000  # characters returned by drive_read_file / per email body
SCOPES_GMAIL = ["https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/gmail.send"]
SCOPES_DRIVE = ["https://www.googleapis.com/auth/drive.readonly"]
TIMEOUT_SECONDS = 10
READ_RETRIES = 2


class WorkspaceError(Exception):
    """A message that is safe to show the user."""


@dataclass
class Mail:
    id: str
    thread_id: str
    sender: str
    to: str
    subject: str
    date: str
    snippet: str
    body: str
    unread: bool
    body_truncated: bool = False


@dataclass
class FileInfo:
    id: str
    name: str
    mime_type: str
    modified: str
    size: int | None = None
    path: str = ""
    web_link: str | None = None


@dataclass
class FileText:
    file: FileInfo
    text: str
    truncated: bool
    extracted_from: str


@dataclass
class SentMail:
    message_id: str
    thread_id: str | None
    to: list[str]
    subject: str
    sent: bool
    already_sent: bool
    at: str
    extra: dict[str, Any] = field(default_factory=dict)


class MailBackend(Protocol):
    mode: str

    def inbox(self, max_results: int, unread_only: bool, query: str | None, page_token: str | None
              ) -> tuple[list[Mail], str | None]: ...

    def send(self, *, key: str, to: list[str], subject: str, body: str, cc: list[str], thread_id: str | None,
             in_reply_to: str | None) -> SentMail: ...


class DriveBackend(Protocol):
    mode: str

    def list(self, folder: str | None, page_size: int, page_token: str | None) -> tuple[list[FileInfo], str | None]: ...

    def search(self, query: str, page_size: int) -> list[FileInfo]: ...

    def read(self, file_id: str) -> FileText: ...


def _truncate(text: str) -> tuple[str, bool]:
    return (text[:MAX_TEXT], True) if len(text) > MAX_TEXT else (text, False)


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n".join((p.extract_text() or "") for p in reader.pages[:50])


# ---------------------------------------------------------------------------- send ledger

class SendLedger:
    """idempotency_key -> sent message, so a replayed approval never sends twice."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.lock = threading.Lock()
        with self._c() as c:
            c.execute("CREATE TABLE IF NOT EXISTS sent (key TEXT PRIMARY KEY, result TEXT NOT NULL, at TEXT NOT NULL)")

    def _c(self):
        return sqlite3.connect(self.path, timeout=10)

    def get(self, key: str) -> SentMail | None:
        with self._c() as c:
            r = c.execute("SELECT result FROM sent WHERE key = ?", (key,)).fetchone()
        if not r:
            return None
        d = json.loads(r[0])
        d.update(sent=False, already_sent=True)
        return SentMail(**d)

    def put(self, key: str, s: SentMail) -> None:
        d = {k: v for k, v in s.__dict__.items()}
        with self._c() as c:
            c.execute("INSERT OR IGNORE INTO sent (key, result, at) VALUES (?,?,?)", (key, json.dumps(d), s.at))


def _ledger(name: str) -> SendLedger:
    return SendLedger(Path(os.environ.get("WORKSPACE_DATA_DIR") or REPO_ROOT / "data") / name)


# ---------------------------------------------------------------------------- sandbox

def _sandbox_root() -> Path:
    return Path(os.environ.get("WORKSPACE_SANDBOX_DIR") or REPO_ROOT / "sandbox_data")


class SandboxMail:
    mode = "sandbox"

    def __init__(self):
        self.root = _sandbox_root()
        self.ledger = _ledger("workspace_sandbox_sent.db")
        self.outbox = Path(os.environ.get("WORKSPACE_DATA_DIR") or REPO_ROOT / "data") / "workspace_sandbox_outbox.jsonl"

    def inbox(self, max_results, unread_only, query, page_token):
        msgs = json.loads((self.root / "inbox.json").read_text(encoding="utf-8"))
        msgs.sort(key=lambda m: m["date"], reverse=True)
        if unread_only:
            msgs = [m for m in msgs if m.get("unread")]
        if query:  # a small subset of Gmail search: from:"name" / from:word, is:unread, plain words
            q = query.lower()
            for who in re.findall(r'from:(?:"([^"]+)"|(\S+))', q):
                w = who[0] or who[1]
                msgs = [m for m in msgs if w in m["from"].lower()]
            if "is:unread" in q:
                msgs = [m for m in msgs if m.get("unread")]
            rest = re.sub(r'from:(?:"[^"]+"|\S+)|is:unread', " ", q).split()
            msgs = [m for m in msgs if all(w in (m["subject"] + m["body"] + m["from"]).lower() for w in rest)]
        off = int(page_token or 0)
        page = msgs[off:off + max_results]
        nxt = str(off + max_results) if off + max_results < len(msgs) else None
        out = []
        for m in page:
            body, cut = _truncate(m["body"])
            out.append(Mail(id=m["id"], thread_id=m["thread_id"], sender=m["from"], to=m["to"], subject=m["subject"],
                            date=m["date"], snippet=m["body"][:160], body=body, unread=m.get("unread", False),
                            body_truncated=cut))
        return out, nxt

    def send(self, *, key, to, subject, body, cc, thread_id, in_reply_to):
        prior = self.ledger.get(key)
        if prior:
            return prior
        mid = "sim-sent-" + hashlib.sha256(key.encode()).hexdigest()[:16]
        s = SentMail(message_id=mid, thread_id=thread_id, to=to, subject=subject, sent=True, already_sent=False,
                     at=datetime.now(UTC).isoformat(timespec="seconds"), extra={"cc": cc})
        self.outbox.parent.mkdir(parents=True, exist_ok=True)
        with self.outbox.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"id": mid, "to": to, "cc": cc, "subject": subject, "body": body, "at": s.at,
                                "simulated": True}) + "\n")
        self.ledger.put(key, s)
        return s


class SandboxDrive:
    mode = "sandbox"

    def __init__(self):
        self.root = (_sandbox_root() / "drive").resolve()

    @staticmethod
    def _id(rel: str) -> str:
        return "sim-" + hashlib.sha1(rel.encode(), usedforsecurity=False).hexdigest()[:16]

    def _all(self) -> list[tuple[FileInfo, Path]]:
        out = []
        for p in sorted(self.root.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(self.root).as_posix()
            mime = mimetypes.guess_type(p.name)[0] or ("text/markdown" if p.suffix == ".md" else "text/plain")
            st = p.stat()
            out.append((FileInfo(id=self._id(rel), name=p.name, mime_type=mime, size=st.st_size, path=rel,
                                 modified=datetime.fromtimestamp(st.st_mtime, UTC).isoformat(timespec="seconds")), p))
        return out

    def list(self, folder, page_size, page_token):
        items = [f for f, _ in self._all() if not folder or f.path.lower().startswith(folder.strip("/").lower() + "/")]
        off = int(page_token or 0)
        nxt = str(off + page_size) if off + page_size < len(items) else None
        return items[off:off + page_size], nxt

    def search(self, query, page_size):
        q = query.lower()
        hits = []
        for f, p in self._all():
            if q in f.name.lower() or q in f.path.lower():
                hits.append(f)
                continue
            try:
                if q in p.read_text(encoding="utf-8", errors="ignore").lower():
                    hits.append(f)
            except OSError:
                continue
        return hits[:page_size]

    def read(self, file_id):
        for f, p in self._all():
            if f.id == file_id:
                if p.suffix.lower() == ".pdf":
                    raw, how = _pdf_text(p.read_bytes()), "pdf"
                else:
                    raw, how = p.read_text(encoding="utf-8", errors="replace"), "text"
                text, cut = _truncate(raw)
                return FileText(file=f, text=text, truncated=cut, extracted_from=how)
        raise WorkspaceError(f"File {file_id} was not found.")


# ---------------------------------------------------------------------------- google

def _build(api: str, version: str, creds):
    import google_auth_httplib2
    import httplib2
    from googleapiclient.discovery import build

    http = google_auth_httplib2.AuthorizedHttp(creds, http=httplib2.Http(timeout=TIMEOUT_SECONDS))
    return build(api, version, http=http, cache_discovery=False)


def _exec(req, *, read: bool, what: str):
    from googleapiclient.errors import HttpError

    try:
        return req.execute(num_retries=READ_RETRIES if read else 0)
    except HttpError as exc:
        code = int(getattr(getattr(exc, "resp", None), "status", 0) or 0)
        if code in (401, 403):
            raise WorkspaceError(f"Google refused the {what} request. Re-run scripts/google_oauth.py.") from exc
        if code == 404:
            raise WorkspaceError(f"{what}: not found.") from exc
        raise WorkspaceError(f"{what} returned HTTP {code}.") from exc
    except (TimeoutError, OSError) as exc:
        raise WorkspaceError(f"{what} did not answer within {TIMEOUT_SECONDS} s.") from exc


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _plain_body(payload: dict) -> str:
    """First text/plain part; falls back to text/html with tags stripped."""
    import re

    stack, html = [payload], None
    while stack:
        part = stack.pop(0)
        mt, data = part.get("mimeType", ""), (part.get("body") or {}).get("data")
        if mt == "text/plain" and data:
            return _b64d(data).decode("utf-8", errors="replace")
        if mt == "text/html" and data and html is None:
            html = _b64d(data).decode("utf-8", errors="replace")
        stack.extend(part.get("parts", []) or [])
    if html:
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()
    return ""


class GoogleMail:
    mode = "google"

    def __init__(self, creds):
        self.svc = _build("gmail", "v1", creds)
        self.ledger = _ledger("workspace_gmail_sent.db")

    def inbox(self, max_results, unread_only, query, page_token):
        q = " ".join(x for x in ("is:unread" if unread_only else "", query or "") if x) or None
        d = _exec(self.svc.users().messages().list(userId="me", labelIds=["INBOX"], q=q, maxResults=max_results,
                                                   pageToken=page_token or None), read=True, what="Gmail")
        out = []
        for ref in d.get("messages", []):
            m = _exec(self.svc.users().messages().get(userId="me", id=ref["id"], format="full"), read=True, what="Gmail")
            h = {x["name"].lower(): x["value"] for x in m.get("payload", {}).get("headers", [])}
            body, cut = _truncate(_plain_body(m.get("payload", {})))
            date = datetime.fromtimestamp(int(m.get("internalDate", "0")) / 1000, UTC).isoformat(timespec="seconds")
            out.append(Mail(id=m["id"], thread_id=m.get("threadId", ""), sender=h.get("from", ""), to=h.get("to", ""),
                            subject=h.get("subject", "(no subject)"), date=date, snippet=m.get("snippet", ""),
                            body=body, unread="UNREAD" in m.get("labelIds", []), body_truncated=cut))
        return out, d.get("nextPageToken")

    def send(self, *, key, to, subject, body, cc, thread_id, in_reply_to):
        prior = self.ledger.get(key)
        if prior:
            return prior
        msg = EmailMessage()
        msg["To"] = ", ".join(to)
        if cc:
            msg["Cc"] = ", ".join(cc)
        msg["Subject"] = subject
        msg["X-AgentsMind-Key"] = hashlib.sha256(key.encode()).hexdigest()[:24]
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to
        msg.set_content(body)
        payload: dict[str, Any] = {"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}
        if thread_id:
            payload["threadId"] = thread_id
        d = _exec(self.svc.users().messages().send(userId="me", body=payload), read=False, what="Gmail send")
        s = SentMail(message_id=d["id"], thread_id=d.get("threadId"), to=to, subject=subject, sent=True,
                     already_sent=False, at=datetime.now(UTC).isoformat(timespec="seconds"), extra={"cc": cc})
        self.ledger.put(key, s)
        return s


DRIVE_FIELDS = "nextPageToken, files(id, name, mimeType, modifiedTime, size, webViewLink)"
EXPORTABLE = {"application/vnd.google-apps.document": "text/plain",
              "application/vnd.google-apps.spreadsheet": "text/csv",
              "application/vnd.google-apps.presentation": "text/plain"}


def drive_query_literal(s: str) -> str:
    """Escape a value for a Drive `q` string literal (backslash and single quote)."""
    return s.replace("\\", "\\\\").replace("'", "\\'")


class GoogleDrive:
    mode = "google"

    def __init__(self, creds):
        self.svc = _build("drive", "v3", creds)

    @staticmethod
    def _f(d: dict) -> FileInfo:
        return FileInfo(id=d["id"], name=d.get("name", ""), mime_type=d.get("mimeType", ""),
                        modified=d.get("modifiedTime", ""), size=int(d["size"]) if d.get("size") else None,
                        web_link=d.get("webViewLink"))

    def list(self, folder, page_size, page_token):
        q = "trashed = false"
        if folder:
            q += f" and '{drive_query_literal(folder)}' in parents"
        d = _exec(self.svc.files().list(q=q, pageSize=page_size, pageToken=page_token or None, fields=DRIVE_FIELDS,
                                        orderBy="modifiedTime desc"), read=True, what="Drive")
        return [self._f(x) for x in d.get("files", [])], d.get("nextPageToken")

    def search(self, query, page_size):
        lit = drive_query_literal(query)
        q = f"trashed = false and (name contains '{lit}' or fullText contains '{lit}')"
        d = _exec(self.svc.files().list(q=q, pageSize=page_size, fields=DRIVE_FIELDS), read=True, what="Drive")
        return [self._f(x) for x in d.get("files", [])]

    def read(self, file_id):
        meta = _exec(self.svc.files().get(fileId=file_id, fields="id, name, mimeType, modifiedTime, size, webViewLink"),
                     read=True, what="Drive")
        f = self._f(meta)
        if f.mime_type in EXPORTABLE:
            data, how = _exec(self.svc.files().export(fileId=file_id, mimeType=EXPORTABLE[f.mime_type]), read=True,
                              what="Drive export"), "export"
        elif f.mime_type == "application/pdf" or f.mime_type.startswith("text/") or f.mime_type in (
                "application/json", "text/csv"):
            if f.size and f.size > 20 * 1024 * 1024:
                raise WorkspaceError("That file is larger than 20 MB; open it in Drive instead.")
            data, how = _exec(self.svc.files().get_media(fileId=file_id), read=True, what="Drive download"), "download"
        else:
            raise WorkspaceError(f"AgentsMind can read text, PDF and Google Docs files; this one is {f.mime_type}.")
        if f.mime_type == "application/pdf":
            text, how = _pdf_text(data), "pdf"
        else:
            text = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else str(data)
        text, cut = _truncate(text)
        return FileText(file=f, text=text, truncated=cut, extracted_from=how)


def choose(kind: str):
    """WORKSPACE_MODE = auto (default) | sandbox | google. kind is 'mail' or 'drive'."""
    mode = (os.environ.get("WORKSPACE_MODE") or "auto").strip().lower()
    if mode not in {"auto", "sandbox", "google"}:
        raise SystemExit("WORKSPACE_MODE must be auto, sandbox or google.")
    scopes = SCOPES_GMAIL if kind == "mail" else SCOPES_DRIVE
    if mode != "sandbox":
        from mcp_servers.google_common import credentials

        try:
            creds = credentials(scopes)
        except (ImportError, RuntimeError) as exc:
            if mode == "google":
                raise SystemExit(f"WORKSPACE_MODE=google but Google is not set up: {exc}") from exc
            creds = None
        if creds is not None:
            log.info("%s backend: Google", kind)
            return GoogleMail(creds) if kind == "mail" else GoogleDrive(creds)
        if mode == "google":
            raise SystemExit("WORKSPACE_MODE=google but no Google token. Run scripts/google_oauth.py first.")
    log.info("%s backend: SANDBOX (simulated, sandbox_data/)", kind)
    return SandboxMail() if kind == "mail" else SandboxDrive()

