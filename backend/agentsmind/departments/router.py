"""Department access. A user sees every department, with access and a reason when denied."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..audit import audit
from ..auth.deps import client_ip, get_current_user
from ..db.models import User
from ..db.session import get_db
from ..rbac import DEPARTMENTS, can_open_department, department_denial_reason

router = APIRouter(prefix="/api/departments", tags=["departments"])


@router.get("")
def list_departments(user: User = Depends(get_current_user)) -> dict:
    items = []
    for d in DEPARTMENTS.values():
        ok = can_open_department(user.role_names, d.slug)
        items.append({"slug": d.slug, "name": d.name, "description": d.description, "accessible": ok,
                      "reason": "" if ok else department_denial_reason(d.slug)})
    return {"items": items}


@router.get("/{slug}")
def open_department(slug: str, request: Request, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)) -> dict:
    d = DEPARTMENTS.get(slug)
    if d is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "There is no such department."})
    if not can_open_department(user.role_names, slug):
        audit(db, "access.denied", actor_user_id=user.id, actor_email=user.email, outcome="denied",
              ip=client_ip(request), target_type="department", target_id=slug, detail={"has": user.role_names})
        raise HTTPException(403, detail={"code": "forbidden", "message": department_denial_reason(slug)})
    # Live figures for the hub tiles are added as each department's data source lands (Phases 2-4).
    return {"slug": d.slug, "name": d.name, "description": d.description, "figures": []}
