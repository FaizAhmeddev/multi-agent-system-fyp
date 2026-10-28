"""Authentication business logic. HTTP-free so it can be unit tested directly."""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..db.models import ROLE_NAMES, PasswordResetToken, RefreshToken, Role, User
from ..mailer import send_system_email
from ..security.passwords import hash_password, needs_rehash, password_problems, verify_password
from ..security.tokens import create_access_token, new_opaque_token, sha256_hex
from ..settings import get_settings

log = logging.getLogger("agentsmind.auth")

ROLE_DESCRIPTIONS = {
    "admin": "Full access, user and system administration",
    "hr": "HR department: candidates, onboarding, policy",
    "it": "IT department: tickets and support",
    "finance": "Finance department: people, payroll, payments",
    "employee": "Assistant and own items only",
}


class AuthError(Exception):
    def __init__(self, code: str, message: str, status: int = 401):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@dataclass
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int
    user: User


def _now() -> datetime:
    return datetime.now(UTC)


def normalise_email(email: str) -> str:
    return (email or "").strip().lower()


# ── Roles and users ──────────────────────────────────────────────────────────

def ensure_roles(db: Session) -> dict[str, Role]:
    existing = {r.name: r for r in db.scalars(select(Role))}
    for name in ROLE_NAMES:
        if name not in existing:
            role = Role(name=name, description=ROLE_DESCRIPTIONS[name])
            db.add(role)
            existing[name] = role
    db.flush()
    return existing


def validate_new_password(password: str, email: str) -> None:
    problems = password_problems(password, email=email, min_length=get_settings().password_min_length)
    if problems:
        raise AuthError("weak_password", " ".join(problems), status=422)


def create_user(db: Session, *, email: str, full_name: str, password: str, roles: list[str],
                actor: User | None = None, ip: str = "") -> User:
    email = normalise_email(email)
    unknown = set(roles) - set(ROLE_NAMES)
    if unknown:
        raise AuthError("unknown_role", f"Unknown role(s): {', '.join(sorted(unknown))}", status=422)
    if not roles:
        raise AuthError("no_role", "A user needs at least one role.", status=422)
    if db.scalar(select(User).where(User.email == email)):
        raise AuthError("email_taken", "A user with this email already exists.", status=409)
    validate_new_password(password, email)
    role_map = ensure_roles(db)
    user = User(email=email, full_name=full_name.strip(), password_hash=hash_password(password),
                roles=[role_map[r] for r in roles], timezone=get_settings().timezone)
    db.add(user)
    db.flush()
    audit(db, "user.create", actor_user_id=actor.id if actor else None,
          actor_email=actor.email if actor else "system", target_type="user", target_id=user.id,
          ip=ip, detail={"email": email, "roles": sorted(roles)}, commit=False)
    db.commit()
    return user


def bootstrap_first_admin(db: Session) -> User | None:
    """Create the first admin from env vars when the users table is empty.

    Returns the created user, or None when users already exist. Raises when the
    table is empty and the env vars are missing, so the operator knows why
    nobody can log in.
    """
    ensure_roles(db)
    db.commit()
    if db.scalar(select(User.id).limit(1)) is not None:
        return None
    s = get_settings()
    if not s.agentsmind_admin_email or not s.agentsmind_admin_password:
        raise RuntimeError(
            "No users exist yet. Set AGENTSMIND_ADMIN_EMAIL and AGENTSMIND_ADMIN_PASSWORD in .env "
            "to create the first admin, then restart."
        )
    user = create_user(db, email=s.agentsmind_admin_email, full_name="Administrator",
                       password=s.agentsmind_admin_password.get_secret_value(), roles=["admin"])
    log.warning("first admin created", extra={"email": user.email})
    return user


# ── Login / tokens ───────────────────────────────────────────────────────────

def _issue_refresh(db: Session, user: User, family_id: str | None, user_agent: str) -> tuple[str, RefreshToken]:
    raw = new_opaque_token()
    row = RefreshToken(
        user_id=user.id, token_hash=sha256_hex(raw), family_id=family_id or str(uuid.uuid4()),
        expires_at=_now() + timedelta(days=get_settings().refresh_token_days),
        user_agent=(user_agent or "")[:300],
    )
    db.add(row)
    db.flush()
    return raw, row


def login(db: Session, email: str, password: str, *, ip: str = "", user_agent: str = "") -> TokenPair:
    s = get_settings()
    email_n = normalise_email(email)
    user = db.scalar(select(User).where(User.email == email_n))
    now = _now()

    if user is None:
        verify_password(password, None)  # equalise timing
        audit(db, "auth.login", actor_email=email_n, outcome="failure", ip=ip, detail={"reason": "unknown_email"})
        raise AuthError("invalid_credentials", "Email or password is incorrect.")

    if user.locked_until and user.locked_until > now:
        audit(db, "auth.login", actor_user_id=user.id, actor_email=user.email, outcome="denied", ip=ip,
              detail={"reason": "locked", "locked_until": user.locked_until.isoformat()})
        raise AuthError("account_locked",
                        f"Account locked after repeated failed sign-ins. Try again after "
                        f"{user.locked_until.strftime('%H:%M UTC')} or ask an administrator to unlock it.",
                        status=423)

    if not verify_password(password, user.password_hash):
        user.failed_login_count += 1
        detail = {"reason": "bad_password", "failed_count": user.failed_login_count}
        if user.failed_login_count >= s.lockout_max_attempts:
            user.locked_until = now + timedelta(minutes=s.lockout_minutes)
            user.failed_login_count = 0
            audit(db, "auth.lockout", actor_user_id=user.id, actor_email=user.email, ip=ip,
                  target_type="user", target_id=user.id,
                  detail={"locked_until": user.locked_until.isoformat()}, commit=False)
            audit(db, "auth.login", actor_user_id=user.id, actor_email=user.email, outcome="failure",
                  ip=ip, detail=detail)
            raise AuthError("account_locked",
                            f"Too many failed sign-ins. The account is locked for {s.lockout_minutes} minutes.",
                            status=423)
        audit(db, "auth.login", actor_user_id=user.id, actor_email=user.email, outcome="failure",
              ip=ip, detail=detail)
        raise AuthError("invalid_credentials", "Email or password is incorrect.")

    if not user.is_active:
        audit(db, "auth.login", actor_user_id=user.id, actor_email=user.email, outcome="denied", ip=ip,
              detail={"reason": "inactive"})
        raise AuthError("inactive", "This account is deactivated. Contact an administrator.", status=403)

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    access, ttl = create_access_token(user.id, user.role_names)
    raw_refresh, _ = _issue_refresh(db, user, None, user_agent)
    audit(db, "auth.login", actor_user_id=user.id, actor_email=user.email, ip=ip, commit=False)
    db.commit()
    return TokenPair(access, raw_refresh, ttl, user)


def refresh(db: Session, raw_token: str, *, ip: str = "", user_agent: str = "") -> TokenPair:
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == sha256_hex(raw_token or "")))
    now = _now()
    if row is None:
        raise AuthError("invalid_refresh", "Session expired. Sign in again.")
    if row.revoked_at is not None:
        # Reuse of a rotated token: assume theft, revoke the whole family.
        for t in db.scalars(select(RefreshToken).where(RefreshToken.family_id == row.family_id,
                                                         RefreshToken.revoked_at.is_(None))):
            t.revoked_at = now
        audit(db, "auth.refresh_reuse", actor_user_id=row.user_id, outcome="denied", ip=ip,
              detail={"family_id": row.family_id})
        raise AuthError("invalid_refresh", "Session expired. Sign in again.")
    if row.expires_at <= now:
        raise AuthError("invalid_refresh", "Session expired. Sign in again.")
    user = db.get(User, row.user_id)
    if user is None or not user.is_active or (user.locked_until and user.locked_until > now):
        row.revoked_at = now
        db.commit()
        raise AuthError("invalid_refresh", "Session expired. Sign in again.")
    raw_new, new_row = _issue_refresh(db, user, row.family_id, user_agent)
    row.revoked_at = now
    row.replaced_by_id = new_row.id
    access, ttl = create_access_token(user.id, user.role_names)
    db.commit()
    return TokenPair(access, raw_new, ttl, user)


def logout(db: Session, raw_token: str, *, user: User | None = None, ip: str = "") -> None:
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == sha256_hex(raw_token or "")))
    if row is not None and row.revoked_at is None:
        row.revoked_at = _now()
    audit(db, "auth.logout", actor_user_id=user.id if user else (row.user_id if row else None),
          actor_email=user.email if user else "", ip=ip)


def revoke_all_sessions(db: Session, user_id: int) -> None:
    now = _now()
    for t in db.scalars(select(RefreshToken).where(RefreshToken.user_id == user_id,
                                                     RefreshToken.revoked_at.is_(None))):
        t.revoked_at = now


def change_password(db: Session, user: User, current: str, new: str, *, ip: str = "") -> None:
    if not verify_password(current, user.password_hash):
        audit(db, "auth.password_change", actor_user_id=user.id, actor_email=user.email,
              outcome="failure", ip=ip, detail={"reason": "bad_current"})
        raise AuthError("invalid_credentials", "Current password is incorrect.", status=400)
    validate_new_password(new, user.email)
    user.password_hash = hash_password(new)
    user.password_changed_at = _now()
    revoke_all_sessions(db, user.id)
    audit(db, "auth.password_change", actor_user_id=user.id, actor_email=user.email, ip=ip)


def request_password_reset(db: Session, email: str, *, ip: str = "") -> None:
    """Always succeeds from the caller's point of view (no account enumeration)."""
    email_n = normalise_email(email)
    user = db.scalar(select(User).where(User.email == email_n))
    if user is None or not user.is_active:
        audit(db, "auth.reset_request", actor_email=email_n, outcome="ignored", ip=ip)
        return
    raw = new_opaque_token()
    minutes = get_settings().password_reset_minutes
    db.add(PasswordResetToken(user_id=user.id, token_hash=sha256_hex(raw),
                              expires_at=_now() + timedelta(minutes=minutes)))
    send_system_email(
        db, to=user.email, subject="AgentsMind password reset", purpose="password_reset",
        body=(f"A password reset was requested for your AgentsMind account.\n\n"
              f"Reset code: {raw}\n\nIt expires in {minutes} minutes and can be used once. "
              f"If you did not ask for this, ignore this message."),
    )
    audit(db, "auth.reset_request", actor_user_id=user.id, actor_email=user.email, ip=ip)


def reset_password(db: Session, raw_token: str, new: str, *, ip: str = "") -> None:
    row = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == sha256_hex(raw_token or "")))
    now = _now()
    if row is None or row.used_at is not None or row.expires_at <= now:
        audit(db, "auth.reset", outcome="failure", ip=ip, detail={"reason": "invalid_token"})
        raise AuthError("invalid_reset", "This reset code is invalid or has expired.", status=400)
    user = db.get(User, row.user_id)
    assert user is not None
    validate_new_password(new, user.email)
    user.password_hash = hash_password(new)
    user.password_changed_at = now
    user.failed_login_count = 0
    user.locked_until = None
    row.used_at = now
    revoke_all_sessions(db, user.id)
    audit(db, "auth.reset", actor_user_id=user.id, actor_email=user.email, ip=ip)


def unlock_user(db: Session, target: User, actor: User, *, ip: str = "") -> None:
    target.locked_until = None
    target.failed_login_count = 0
    audit(db, "user.unlock", actor_user_id=actor.id, actor_email=actor.email,
          target_type="user", target_id=target.id, ip=ip)
