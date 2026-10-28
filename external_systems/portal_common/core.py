"""Shared building blocks for the two external portals.

The portals are separate systems: they never import AgentsMind core code and each
has its own database. This module only holds helpers both portals need.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import DateTime, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.types import TypeDecorator

COMMON_DIR = Path(__file__).resolve().parent
log = logging.getLogger("portal")


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime")
        return value.astimezone(UTC)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def make_sqlite_engine(url: str) -> Engine:
    if url.startswith("sqlite:///") and ":memory:" not in url:
        Path(url[len("sqlite:///"):]).parent.mkdir(parents=True, exist_ok=True)
    eng = create_engine(url, connect_args={"check_same_thread": False, "timeout": 5})

    @event.listens_for(eng, "connect")
    def _pragmas(dbapi_conn, _rec):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

    return eng


def env(name: str, default: str | None = None, *, required: bool = False, min_len: int = 0) -> str:
    v = os.environ.get(name, "")
    v = v.strip() if v else ""
    if not v:
        if required:
            raise RuntimeError(f"Set {name} in the environment or .env before starting this service.")
        return default or ""
    if min_len and len(v) < min_len:
        raise RuntimeError(f"{name} must be at least {min_len} characters.")
    return v


def load_dotenv_file(path: Path) -> None:
    """Minimal .env reader (KEY=VALUE lines). Existing environment variables win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


# ── passwords and keys ───────────────────────────────────────────────────────

_hasher = PasswordHasher()
_DUMMY = _hasher.hash("portal-timing-equaliser")


def hash_password(p: str) -> str:
    return _hasher.hash(p)


def verify_password(p: str, h: str | None) -> bool:
    try:
        return _hasher.verify(h or _DUMMY, p) and h is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def keys_match(given: str | None, expected: str) -> bool:
    return bool(given) and hmac.compare_digest(given.encode(), expected.encode())


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def new_token(n: int = 24) -> str:
    return secrets.token_urlsafe(n)


# ── CSRF for server-rendered forms ───────────────────────────────────────────

def csrf_token(request: Request) -> str:
    tok = request.session.get("csrf")
    if not tok:
        tok = new_token(16)
        request.session["csrf"] = tok
    return tok


def csrf_ok(request: Request, submitted: str | None) -> bool:
    expected = request.session.get("csrf")
    return bool(expected and submitted) and hmac.compare_digest(str(expected), str(submitted))


def flash(request: Request, message: str, kind: str = "info") -> None:
    request.session.setdefault("flash", []).append({"kind": kind, "message": message})


def pop_flashes(request: Request) -> list[dict[str, str]]:
    return request.session.pop("flash", [])


# ── templates ────────────────────────────────────────────────────────────────

def make_templates(app_template_dir: Path, *, portal_name: str, short_name: str) -> Jinja2Templates:
    t = Jinja2Templates(directory=[str(app_template_dir), str(COMMON_DIR / "templates")])
    t.env.globals.update(portal_name=portal_name, short_name=short_name, csrf_token=csrf_token,
                         pop_flashes=pop_flashes)
    t.env.filters["dt"] = lambda d: d.strftime("%d %b %Y, %H:%M UTC") if d else ""
    t.env.filters["date"] = lambda d: d.strftime("%d %b %Y") if d else ""
    t.env.filters["money"] = lambda v: f"{v:,.2f}"
    return t


def page_meta(total: int, page: int, page_size: int) -> dict[str, Any]:
    pages = max(1, (total + page_size - 1) // page_size)
    return {"total": total, "page": page, "page_size": page_size, "pages": pages,
            "has_prev": page > 1, "has_next": page < pages}


# ── uploads ──────────────────────────────────────────────────────────────────

MAGIC = {
    "application/pdf": [b"%PDF-"],
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/jpeg": [b"\xff\xd8\xff"],
}
EXT_FOR = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg", "text/plain": ".txt"}


def sniff_type(data: bytes) -> str | None:
    """Detect the file type from its first bytes. Plain text must be valid UTF-8 without NUL bytes."""
    for mime, sigs in MAGIC.items():
        if any(data.startswith(s) for s in sigs):
            return mime
    if data and b"\x00" not in data[:4096]:
        try:
            data[:4096].decode("utf-8")
            return "text/plain"
        except UnicodeDecodeError:
            return None
    return None


def safe_filename(name: str, max_len: int = 120) -> str:
    """Strip paths, control and special characters. Never returns an empty or dotted name."""
    name = unicodedata.normalize("NFKC", name or "")
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip(" .")
    name = re.sub(r"\.{2,}", ".", name)
    if not name:
        name = "file"
    stem, dot, ext = name.rpartition(".")
    if dot and len(ext) <= 8:
        return (stem[: max_len - len(ext) - 1] or "file") + "." + ext
    return name[:max_len]
