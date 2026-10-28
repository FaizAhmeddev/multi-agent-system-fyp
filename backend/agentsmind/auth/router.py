from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from ..db.models import User
from ..db.session import get_db
from . import service
from .deps import client_ip, get_current_user
from .schemas import (
    ChangePasswordIn,
    ForgotIn,
    LoginIn,
    MessageOut,
    RefreshIn,
    ResetIn,
    TokenOut,
    UserOut,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def user_out(u: User) -> UserOut:
    locked = bool(u.locked_until and u.locked_until > datetime.now(UTC))
    return UserOut(id=u.id, email=u.email, full_name=u.full_name, roles=u.role_names,
                   is_active=u.is_active, timezone=u.timezone, last_login_at=u.last_login_at, locked=locked)


def _tokens(pair: service.TokenPair) -> TokenOut:
    return TokenOut(access_token=pair.access_token, refresh_token=pair.refresh_token,
                    expires_in=pair.expires_in, user=user_out(pair.user))


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)) -> TokenOut:
    pair = service.login(db, body.email, body.password, ip=client_ip(request),
                         user_agent=request.headers.get("user-agent", ""))
    return _tokens(pair)


@router.post("/refresh", response_model=TokenOut)
def refresh(body: RefreshIn, request: Request, db: Session = Depends(get_db)) -> TokenOut:
    pair = service.refresh(db, body.refresh_token, ip=client_ip(request),
                           user_agent=request.headers.get("user-agent", ""))
    return _tokens(pair)


@router.post("/logout", response_model=MessageOut)
def logout(body: RefreshIn, request: Request, db: Session = Depends(get_db)) -> MessageOut:
    service.logout(db, body.refresh_token, ip=client_ip(request))
    return MessageOut(message="Signed out.")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return user_out(user)


@router.post("/password/change", response_model=MessageOut)
def change_password(body: ChangePasswordIn, request: Request, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)) -> MessageOut:
    service.change_password(db, user, body.current_password, body.new_password, ip=client_ip(request))
    return MessageOut(message="Password changed. Other sessions were signed out.")


@router.post("/password/forgot", response_model=MessageOut, status_code=status.HTTP_202_ACCEPTED)
def forgot(body: ForgotIn, request: Request, db: Session = Depends(get_db)) -> MessageOut:
    service.request_password_reset(db, body.email, ip=client_ip(request))
    return MessageOut(message="If an account exists for this email, a reset code has been sent.")


@router.post("/password/reset", response_model=MessageOut)
def reset(body: ResetIn, request: Request, db: Session = Depends(get_db)) -> MessageOut:
    service.reset_password(db, body.token, body.new_password, ip=client_ip(request))
    return MessageOut(message="Password updated. Sign in with your new password.")
