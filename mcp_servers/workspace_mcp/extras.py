"""Local CV folders, WhatsApp (Twilio) and Drive upload for workspace-mcp.

Local folders
    HR_CV_DIRS (semicolon separated) plus data/cvs. Files outside these folders are never
    listed or read. Supported: PDF, Word (.docx), text.
WhatsApp
    Twilio Messages API (POST /2010-04-01/Accounts/{sid}/Messages.json, HTTP basic auth
    with the account SID and auth token). WhatsApp numbers are written "whatsapp:+92...".
    A Content template (TWILIO_CONTENT_SID) is used when no free text is allowed, for
    example outside the 24-hour WhatsApp session window.
    Sending is idempotent through the same local ledger as email.
Drive upload
    files.create with the drive.file scope: AgentsMind can only see and change files it
    created itself. Only files from data/hr_documents and data/hr_reports can be uploaded.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .extract import DOC_TYPES, ExtractError, text_of
from .imap_mail import safe_attachment

REPO_ROOT = Path(__file__).resolve().parents[2]
SCOPES_DRIVE_FILE = ["https://www.googleapis.com/auth/drive.file"]
TWILIO_API = "https://api.twilio.com/2010-04-01"
WA_NUMBER = re.compile(r"^whatsapp:\+[1-9]\d{7,14}$")


class ExtraError(Exception):
    """A message that is safe to show the user."""


# ---------------------------------------------------------------------------- local folders

def cv_dirs() -> list[Path]:
    data = Path(os.environ.get("WORKSPACE_DATA_DIR") or REPO_ROOT / "data")
    (data / "cvs").mkdir(parents=True, exist_ok=True)
    dirs = [data / "cvs"] + [Path(p.strip()).expanduser() for p in (os.environ.get("HR_CV_DIRS") or "").split(";")
                             if p.strip()]
    return [d.resolve() for d in dirs if d.is_dir()]


def _file_id(p: Path) -> str:
    return "loc-" + hashlib.sha256(str(p).encode()).hexdigest()[:24]


def local_list(max_files: int = 200) -> list[dict[str, Any]]:
    out = []
    for root in cv_dirs():
        for p in sorted(root.rglob("*")):
            if p.is_file() and p.suffix.lower() in DOC_TYPES and not p.name.startswith("~$"):
                st = p.stat()
                out.append({"id": _file_id(p), "name": p.name, "folder": str(root), "path": str(p), "size": st.st_size,
                            "modified": datetime.fromtimestamp(st.st_mtime, UTC).isoformat(timespec="seconds")})
                if len(out) >= max_files:
                    return out
    return out


def local_read(file_id: str) -> dict[str, Any]:
    for root in cv_dirs():
        for p in root.rglob("*"):
            if p.is_file() and _file_id(p) == file_id:
                try:
                    text, how = text_of(p.read_bytes(), p.name)
                except ExtractError as exc:
                    raise ExtraError(str(exc)) from exc
                return {"id": file_id, "name": p.name, "folder": str(root), "text": text[:100_000],
                        "truncated": len(text) > 100_000, "extracted_from": how}
    raise ExtraError("That file is not in the CV folders any more.")


# ---------------------------------------------------------------------------- WhatsApp

def wa_number(raw: str) -> str:
    s = re.sub(r"[\s\-()]", "", raw.strip())
    if s.startswith("whatsapp:"):
        s = s[len("whatsapp:"):]
    if s.startswith("00"):
        s = "+" + s[2:]
    if s.startswith("03") and len(s) == 11:  # Pakistani mobile written locally, e.g. 03001234567
        s = "+92" + s[1:]
    if not s.startswith("+"):
        s = "+" + s
    out = "whatsapp:" + s
    if not WA_NUMBER.match(out):
        raise ExtraError(f"'{raw}' is not a valid phone number. Use international format, e.g. +923001234567.")
    return out


class WhatsApp:
    def __init__(self):
        self.sid = (os.environ.get("TWILIO_ACCOUNT_SID") or "").strip()
        self.token = (os.environ.get("TWILIO_AUTH_TOKEN") or "").strip()
        self.sender = (os.environ.get("TWILIO_WHATSAPP_FROM") or "").strip()
        self.default_to = (os.environ.get("TWILIO_WHATSAPP_TO") or "").strip()
        self.content_sid = (os.environ.get("TWILIO_CONTENT_SID") or "").strip()
        from .backends import _ledger

        self.ledger = _ledger("workspace_whatsapp_sent.db")

    @property
    def configured(self) -> bool:
        return bool(self.sid and self.token and self.sender)

    def send(self, *, key: str, to: str | None, body: str, use_template: bool,
             template_variables: dict[str, str] | None) -> dict[str, Any]:
        import httpx2

        if not self.configured:
            raise ExtraError("WhatsApp is not connected. Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and "
                             "TWILIO_WHATSAPP_FROM in .env.")
        prior = self.ledger.get(key)
        if prior:
            return {"sid": prior.message_id, "to": prior.to[0], "status": "already_sent", "already_sent": True,
                    "at": prior.at}
        dest = wa_number(to or self.default_to or "")
        form: dict[str, str] = {"From": wa_number(self.sender), "To": dest}
        if use_template:
            if not self.content_sid:
                raise ExtraError("No WhatsApp template configured (TWILIO_CONTENT_SID).")
            form["ContentSid"] = self.content_sid
            if template_variables:
                form["ContentVariables"] = json.dumps(template_variables)
        else:
            form["Body"] = body
        try:
            r = httpx2.post(f"{TWILIO_API}/Accounts/{self.sid}/Messages.json", data=form, auth=(self.sid, self.token),
                            timeout=httpx2.Timeout(20.0, connect=5.0))
        except httpx2.HTTPError as exc:
            raise ExtraError(f"Twilio is not reachable ({type(exc).__name__}).") from exc
        try:
            d = r.json()
        except ValueError:
            d = {}
        if r.status_code >= 400:
            raise ExtraError(f"Twilio refused the message: {d.get('message') or r.status_code} "
                             f"(code {d.get('code', '-')}).")
        from .backends import SentMail

        at = datetime.now(UTC).isoformat(timespec="seconds")
        self.ledger.put(key, SentMail(message_id=d.get("sid", ""), thread_id=None, to=[dest], subject="whatsapp",
                                      sent=True, already_sent=False, at=at))
        return {"sid": d.get("sid", ""), "to": dest, "status": d.get("status", "queued"), "already_sent": False,
                "at": at}


# ---------------------------------------------------------------------------- Drive upload

def drive_upload(creds, path: str, folder_id: str | None, convert: bool) -> dict[str, Any]:
    from googleapiclient.http import MediaFileUpload

    from .backends import _build, _exec

    p = safe_attachment(path)
    svc = _build("drive", "v3", creds)
    import mimetypes

    mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    meta: dict[str, Any] = {"name": p.name}
    if folder_id:
        meta["parents"] = [folder_id]
    if convert and p.suffix.lower() == ".docx":
        meta["mimeType"] = "application/vnd.google-apps.document"
    media = MediaFileUpload(str(p), mimetype=mime, resumable=False)
    d = _exec(svc.files().create(body=meta, media_body=media, fields="id, name, webViewLink"), read=False,
              what="Drive upload")
    return {"id": d["id"], "name": d.get("name", p.name), "web_link": d.get("webViewLink")}
