"""Admin: users. (Roles editing, audit viewer and system health screens come later.)"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import service
from ..auth.deps import client_ip, require_roles
from ..auth.router import user_out
from ..auth.schemas import CreateUserIn, MessageOut, UserOut
from ..db.models import OutboundEmail, User
from ..db.session import get_db

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users")
def list_users(page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
               _: User = Depends(require_roles("admin")), db: Session = Depends(get_db)) -> dict:
    total = db.scalar(select(func.count(User.id))) or 0
    rows = db.scalars(select(User).order_by(User.id).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [user_out(u).model_dump(mode="json") for u in rows], "total": total,
            "page": page, "page_size": page_size}


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: CreateUserIn, request: Request, actor: User = Depends(require_roles("admin")),
                db: Session = Depends(get_db)) -> UserOut:
    u = service.create_user(db, email=body.email, full_name=body.full_name, password=body.password,
                            roles=body.roles, actor=actor, ip=client_ip(request))
    return user_out(u)


@router.post("/users/{user_id}/unlock", response_model=MessageOut)
def unlock(user_id: int, request: Request, actor: User = Depends(require_roles("admin")),
           db: Session = Depends(get_db)) -> MessageOut:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "User not found."})
    service.unlock_user(db, target, actor, ip=client_ip(request))
    return MessageOut(message=f"{target.email} unlocked.")


@router.get("/outbox")
def outbox(limit: int = Query(20, ge=1, le=100), _: User = Depends(require_roles("admin")),
           db: Session = Depends(get_db)) -> dict:
    """Sandbox mail outbox. Every item here is Simulated: nothing was sent."""
    rows = db.scalars(select(OutboundEmail).order_by(OutboundEmail.id.desc()).limit(limit)).all()
    return {"items": [{"id": r.id, "to": r.to_address, "subject": r.subject, "body": r.body,
                       "purpose": r.purpose, "simulated": r.simulated, "status": r.status,
                       "created_at": r.created_at.isoformat()} for r in rows]}
