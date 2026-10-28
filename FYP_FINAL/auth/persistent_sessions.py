"""Opaque, expiring browser sessions validated against the existing account store.

Only SHA-256 token digests are persisted. Credentials and roles are always loaded
server-side; browser claims are never accepted as identity.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import hmac
import os
import secrets
import time
import uuid

from sqlalchemy import BigInteger, Column, String, delete, select, update
from sqlalchemy.orm import declarative_base, sessionmaker

COOKIE_NAME = "office_session"
GRANT_SECONDS = 45
Base = declarative_base()


class BrowserSession(Base):
    __tablename__ = "auth_browser_sessions"
    id = Column(String(36), primary_key=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    username = Column(String(100), nullable=False, index=True)
    source = Column(String(12), nullable=False)
    credential_fingerprint = Column(String(64), nullable=False)
    created_at = Column(BigInteger, nullable=False)
    expires_at = Column(BigInteger, nullable=False, index=True)
    revoked_at = Column(BigInteger, nullable=True)


class LoginGrant(Base):
    __tablename__ = "auth_login_grants"
    token_hash = Column(String(64), primary_key=True)
    username = Column(String(100), nullable=False)
    source = Column(String(12), nullable=False)
    credential_fingerprint = Column(String(64), nullable=False)
    expires_at = Column(BigInteger, nullable=False, index=True)
    used_at = Column(BigInteger, nullable=True)


@dataclass(frozen=True)
class Account:
    username: str
    role: str
    name: str
    credential_fingerprint: str


@dataclass(frozen=True)
class VerifiedSession:
    id: str
    account: Account
    expires_at: int


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def credential_fingerprint(source: str, username: str, password: str) -> str:
    return digest(source + "\0" + username + "\0" + (password or ""))


def load_account(username: str, source: str) -> Account | None:
    if source == "db":
        from database.sqlite_db import AppUser, get_session
        with get_session() as session:
            row = session.query(AppUser).filter_by(username=username).one_or_none()
            if row is None:
                return None
            return Account(row.username, row.role, row.display_name or row.username,
                           credential_fingerprint(source, row.username, row.password))
    if source == "config":
        from config import USERS
        row = USERS.get(username)
        if row:
            return Account(username, row["role"], row.get("name") or username,
                           credential_fingerprint(source, username, row["password"]))
    return None


def session_seconds() -> int:
    # Absolute expiry is bounded; no option can turn validation/expiry off.
    return max(60, min(int(os.getenv("FYP_AUTH_SESSION_SECONDS", "28800")), 30 * 86400))


class SessionStore:
    def __init__(self, engine, account_loader=load_account, *, ttl_seconds=None):
        Base.metadata.create_all(engine)
        self._sessions = sessionmaker(bind=engine)
        self._load_account = account_loader
        self.ttl_seconds = session_seconds() if ttl_seconds is None else ttl_seconds

    def issue_grant(self, username: str, verified_password: str, *, now=None) -> str | None:
        """Called only after the existing authenticate_user accepts credentials.

        Preserve its DB-then-config resolution order and bind to the accepted
        credential source, so a refresh cannot silently change identity/role.
        """
        now = int(time.time() if now is None else now)
        account = None
        source = ""
        for candidate in ("db", "config"):
            current = self._load_account(username, candidate)
            if current and hmac.compare_digest(current.credential_fingerprint,
                    credential_fingerprint(candidate, username, verified_password)):
                source, account = candidate, current
                break
        if account is None:
            return None
        token = secrets.token_urlsafe(32)
        with self._sessions.begin() as session:
            session.execute(delete(LoginGrant).where(LoginGrant.expires_at < now - 300))
            session.execute(delete(BrowserSession).where(BrowserSession.expires_at < now - 7 * 86400))
            session.add(LoginGrant(token_hash=digest(token), username=account.username,
                source=source, credential_fingerprint=account.credential_fingerprint,
                expires_at=now + GRANT_SECONDS))
        return token

    def exchange(self, grant_token: str, previous_token: str | None = None, *, now=None):
        now = int(time.time() if now is None else now)
        if not grant_token or len(grant_token) > 128:
            return None
        with self._sessions() as reader:
            grant = reader.get(LoginGrant, digest(grant_token))
            if not grant or grant.used_at is not None or grant.expires_at <= now:
                return None
            identity = (grant.username, grant.source, grant.credential_fingerprint)
        account = self._load_account(identity[0], identity[1])
        if not account or not hmac.compare_digest(account.credential_fingerprint, identity[2]):
            return None
        with self._sessions.begin() as session:
            claimed = session.execute(update(LoginGrant).where(
                LoginGrant.token_hash == digest(grant_token), LoginGrant.used_at.is_(None),
                LoginGrant.expires_at > now).values(used_at=now))
            if claimed.rowcount != 1:
                return None
            raw = secrets.token_urlsafe(32)
            record = BrowserSession(id=str(uuid.uuid4()), token_hash=digest(raw),
                username=account.username, source=identity[1],
                credential_fingerprint=account.credential_fingerprint,
                created_at=now, expires_at=now + self.ttl_seconds)
            session.add(record)
            if previous_token:
                session.execute(update(BrowserSession).where(
                    BrowserSession.token_hash == digest(previous_token),
                    BrowserSession.revoked_at.is_(None)).values(revoked_at=now))
            return raw, VerifiedSession(record.id, account, record.expires_at)

    def validate(self, token: str | None, *, now=None) -> VerifiedSession | None:
        if not token or len(token) > 128:
            return None
        now = int(time.time() if now is None else now)
        with self._sessions() as reader:
            row = reader.scalar(select(BrowserSession).where(BrowserSession.token_hash == digest(token)))
            if not row or row.revoked_at is not None:
                return None
            identity = (row.id, row.username, row.source, row.credential_fingerprint, row.expires_at)
        account = self._load_account(identity[1], identity[2])
        if identity[4] <= now or not account or not hmac.compare_digest(
                account.credential_fingerprint, identity[3]):
            self.revoke(token, now=now)
            return None
        return VerifiedSession(identity[0], account, identity[4])

    def revoke(self, token: str | None, *, now=None) -> bool:
        if not token or len(token) > 128:
            return False
        now = int(time.time() if now is None else now)
        with self._sessions.begin() as session:
            result = session.execute(update(BrowserSession).where(
                BrowserSession.token_hash == digest(token), BrowserSession.revoked_at.is_(None)
            ).values(revoked_at=now))
            return result.rowcount == 1


@lru_cache(maxsize=1)
def get_session_store() -> SessionStore:
    from database.sqlite_db import get_engine
    from sqlalchemy import create_engine
    engine = get_engine()
    # Use a separate pool on the same SQLite file: the legacy database uses a
    # StaticPool, which must not share one transaction across HTTP/UI threads.
    if engine.url.get_backend_name() == "sqlite" and engine.url.database not in (None, "", ":memory:"):
        engine = create_engine(engine.url, connect_args={"check_same_thread": False, "timeout": 15})
    return SessionStore(engine)
