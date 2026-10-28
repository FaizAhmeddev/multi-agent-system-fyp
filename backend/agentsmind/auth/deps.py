"""FastAPI dependencies: current user and role checks.

Every protected endpoint declares its roles with `require_roles(...)`. Checks
happen on the server; the UI hiding things is only a convenience.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from ..audit import audit
from ..db.models import User
from ..db.session import get_db
from ..security.tokens import TokenError, decode_access_token

_bearer = HTTPBearer(auto_error=False)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "not_authenticated", "message": "Sign in to continue."},
        headers={"WWW-Authenticate": "Bearer"},
    )
    if creds is None or creds.scheme.lower() != "bearer":
        raise unauthorized
    try:
        claims = decode_access_token(creds.credentials)
    except TokenError:
        raise unauthorized from None
    user = db.get(User, claims.user_id)
    if user is None or not user.is_active:
        raise unauthorized
    if user.locked_until and user.locked_until > datetime.now(UTC):
        raise unauthorized
    # Tokens issued before a password change are no longer valid.
    if user.password_changed_at and claims.iat < int(user.password_changed_at.timestamp()):
        raise unauthorized
    request.state.user = user
    return user


def require_roles(*roles: str) -> Callable[..., User]:
    allowed = set(roles)

    def _dep(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        if "admin" in user.role_names or allowed & set(user.role_names):
            return user
        audit(db, "access.denied", actor_user_id=user.id, actor_email=user.email, outcome="denied",
              ip=client_ip(request), target_type="endpoint", target_id=request.url.path,
              detail={"required": sorted(allowed), "has": user.role_names})
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "forbidden",
                    "message": "You do not have access to this area. Ask an administrator if you need it."},
        )

    return _dep
