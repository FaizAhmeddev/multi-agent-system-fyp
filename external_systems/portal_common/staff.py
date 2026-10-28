"""Staff sign-in shared by both portals (each portal has its own staff table)."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .core import hash_password, utcnow, verify_password

MAX_ATTEMPTS = 5
LOCK_MINUTES = 15


def attempt_login(db: Session, model: Any, email: str, password: str) -> tuple[Any | None, str]:
    email = (email or "").strip().lower()
    user = db.scalar(select(model).where(model.email == email))
    now = utcnow()
    if user is None:
        verify_password(password, None)
        return None, "Email or password is incorrect."
    if user.locked_until and user.locked_until > now:
        return None, "Account locked after repeated failed sign-ins. Try again in 15 minutes."
    if not verify_password(password, user.password_hash):
        user.failed_count += 1
        if user.failed_count >= MAX_ATTEMPTS:
            user.locked_until, user.failed_count = now + timedelta(minutes=LOCK_MINUTES), 0
            db.commit()
            return None, "Too many failed sign-ins. The account is locked for 15 minutes."
        db.commit()
        return None, "Email or password is incorrect."
    user.failed_count, user.locked_until = 0, None
    db.commit()
    return user, ""


def bootstrap_staff(db: Session, model: Any, email: str, password: str, full_name: str) -> Any | None:
    """Create the first staff account from env vars when none exist."""
    if db.scalar(select(model.id).limit(1)) is not None:
        return None
    if not email or not password:
        raise RuntimeError("No staff accounts exist. Set the portal's *_ADMIN_EMAIL and *_ADMIN_PASSWORD.")
    if len(password) < 12:
        raise RuntimeError("Portal admin password must be at least 12 characters.")
    u = model(email=email.strip().lower(), full_name=full_name, password_hash=hash_password(password),
              failed_count=0)
    db.add(u)
    db.commit()
    return u
