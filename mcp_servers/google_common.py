"""Google OAuth for calendar-mcp and workspace-mcp: one consent, narrow scopes, encrypted token.

The token is stored only as data/google_token.enc, encrypted with a key derived from
GOOGLE_TOKEN_ENCRYPTION_KEY (Fernet: AES-128-CBC with HMAC-SHA256). Plaintext token
files are never written. credentials.json / token.json are gitignored anyway.

Scopes (narrowest that work, see docs/API_VERIFICATION.md):
    calendar.events.owned  create, change and delete events on calendars you own
    calendar.freebusy      your own availability (freebusy.query)
    gmail.readonly         read the inbox
    gmail.send             send a message (only after an approval in AgentsMind)
    drive.readonly         list, search and read files
    drive.file             upload letters and reports (only files AgentsMind created)
    spreadsheets           read and update the HR sheets you register
Gmail scopes are skipped when mail uses an app password (GMAIL_EMAIL, GMAIL_APP_PASSWORD).
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
TOKEN_PATH = Path(os.environ.get("GOOGLE_TOKEN_FILE", str(REPO_ROOT / "data" / "google_token.enc")))
CLIENT_PATH = Path(os.environ.get("GOOGLE_OAUTH_CLIENT_FILE", str(REPO_ROOT / "secrets" / "google_oauth_client.json")))

BASE_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events.owned",
    "https://www.googleapis.com/auth/calendar.freebusy",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/spreadsheets",
]
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/gmail.send"]


def consent_scopes() -> list[str]:
    """Gmail scopes are only requested when mail does not go through an app password (IMAP/SMTP)."""
    app_pw = (os.environ.get("GMAIL_EMAIL") or "").strip() and (os.environ.get("GMAIL_APP_PASSWORD") or "").strip()
    return BASE_SCOPES + ([] if app_pw else GMAIL_SCOPES)


SCOPES = BASE_SCOPES + GMAIL_SCOPES  # everything any tool may ask for
log = logging.getLogger("google")


def _fernet():
    from cryptography.fernet import Fernet

    secret = (os.environ.get("GOOGLE_TOKEN_ENCRYPTION_KEY") or "").strip()
    if len(secret) < 24:
        raise RuntimeError("Set GOOGLE_TOKEN_ENCRYPTION_KEY (24+ characters) to store the Google token encrypted.")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))


def save_token(info: dict[str, Any]) -> None:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_bytes(_fernet().encrypt(json.dumps(info).encode()))


def load_token() -> dict[str, Any] | None:
    if not TOKEN_PATH.is_file():
        return None
    try:
        return json.loads(_fernet().decrypt(TOKEN_PATH.read_bytes()))
    except Exception as exc:  # noqa: BLE001 - wrong key or corrupt file: fall back to sandbox
        log.error("Google token could not be decrypted (%s). Re-run scripts/google_oauth.py.", type(exc).__name__)
        return None


def credentials(required_scopes: list[str]):
    """Return refreshed google.oauth2 Credentials, or None when Google is not set up (sandbox mode)."""
    info = load_token()
    if not info:
        return None
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_info(info)  # the scopes the user actually granted
    missing = set(required_scopes) - set(creds.scopes or info.get("scopes") or [])
    if missing:
        log.warning("Google sign-in lacks %s; sign in to Google again from AgentsMind to add it.",
                    ", ".join(sorted(m.rsplit("/", 1)[1] for m in missing)))
        return None
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        save_token(json.loads(creds.to_json()))
    return creds if creds.valid else None


def run_consent_flow() -> None:
    """Interactive one-time consent (opens a browser on this computer)."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not CLIENT_PATH.is_file():
        raise SystemExit(f"Put your OAuth client file (Desktop app) at {CLIENT_PATH} first.")
    scopes = consent_scopes()
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_PATH), scopes)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline",
                                  success_message="AgentsMind is connected to Google. You can close this tab.")
    save_token(json.loads(creds.to_json()))
    granted = creds.scopes or scopes
    print(f"Google access saved (encrypted) to {TOKEN_PATH}. Scopes: {', '.join(s.rsplit('/', 1)[1] for s in granted)}")


def status() -> dict[str, Any]:
    """What the Google sign-in covers, for the UI and the launcher (no secrets)."""
    info = None
    try:
        info = load_token()
    except RuntimeError:
        info = None
    granted = set((info or {}).get("scopes") or [])
    names = {"calendar": BASE_SCOPES[0], "drive": BASE_SCOPES[2], "drive_upload": BASE_SCOPES[3],
             "sheets": BASE_SCOPES[4], "gmail_api": GMAIL_SCOPES[0]}
    return {"client_file": CLIENT_PATH.is_file(), "signed_in": bool(info),
            "scopes": {k: v in granted for k, v in names.items()},
            "missing": [k for k, v in names.items() if v not in granted and v in consent_scopes()]}
