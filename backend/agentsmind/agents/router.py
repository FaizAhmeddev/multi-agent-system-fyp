"""Agents, agent runs and approvals."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..auth.deps import client_ip, get_current_user
from ..db.base import utcnow
from ..db.models import AgentRun, Approval, User
from ..db.session import get_db
from ..rbac import has_any
from .gateway import call_tool
from .registry import AGENTS
from .runner import AgentAccessError, create_run

router = APIRouter(prefix="/api", tags=["agents"])


def _http(exc: AgentAccessError) -> HTTPException:
    return HTTPException(exc.status, detail={"code": exc.code, "message": exc.message})


@router.get("/agents")
def list_agents(user: User = Depends(get_current_user)) -> dict:
    out = []
    for a in AGENTS.values():
        if not has_any(user.role_names, a.roles):
            continue
        out.append({"name": a.name, "title": a.title, "department": a.department,
                    "actions": [{"name": x.name, "title": x.title, "input_schema": x.schema.model_json_schema()}
                                for x in a.actions.values()],
                    "tools": sorted(a.tools)})
    return {"items": out}


class RunIn(BaseModel):
    action: str = Field(min_length=1, max_length=60)
    inputs: dict[str, Any] = Field(default_factory=dict)


def _run_out(r: AgentRun) -> dict:
    return {"id": r.id, "agent": r.agent, "action": r.action, "status": r.status, "output": r.output_text,
            "error": r.error, "simulated": bool((r.meta or {}).get("simulated", False)), "meta": r.meta or {},
            "task_id": r.task_id, "started_at": r.started_at.isoformat(),
            "finished_at": r.finished_at.isoformat() if r.finished_at else None}


@router.post("/agents/{agent}/runs", status_code=202)
def start_run(agent: str, body: RunIn, request: Request, user: User = Depends(get_current_user),
              db: Session = Depends(get_db), idempotency_key: str | None = Header(default=None, max_length=100)
              ) -> dict:
    try:
        run = create_run(db, user=user, agent=agent, action=body.action, inputs=body.inputs,
                         idempotency_key=idempotency_key)
    except AgentAccessError as exc:
        if exc.status == 403:
            audit(db, "access.denied", actor_user_id=user.id, actor_email=user.email, outcome="denied",
                  ip=client_ip(request), target_type="agent", target_id=agent, detail={"action": body.action})
        raise _http(exc) from None
    except ValidationError as exc:
        fields = [{"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()]
        raise HTTPException(422, detail={"code": "validation_error", "message": "Check the highlighted fields.",
                                         "fields": fields}) from None
    return _run_out(run)


@router.get("/agents/runs/{run_id}")
def get_run(run_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    r = db.get(AgentRun, run_id)
    if r is None or (r.user_id != user.id and "admin" not in user.role_names):
        raise HTTPException(404, detail={"code": "not_found", "message": "Run not found."})
    return _run_out(r)


# ── approvals ────────────────────────────────────────────────────────────────

def _appr_out(a: Approval) -> dict:
    return {"id": a.id, "agent": a.agent, "tool": a.tool, "risk": a.risk, "summary": a.summary,
            "arguments": a.arguments, "status": a.status, "result": a.result,
            "created_at": a.created_at.isoformat(), "decided_at": a.decided_at.isoformat() if a.decided_at else None}


@router.get("/approvals")
def list_approvals(status: str | None = Query(None, pattern="^(pending|approved|rejected|executed|failed)$"),
                   page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    q = select(Approval)
    if "admin" not in user.role_names:
        q = q.where(Approval.requested_by_user_id == user.id)
    if status:
        q = q.where(Approval.status == status)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(Approval.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [_appr_out(a) for a in rows], "total": total, "page": page, "page_size": page_size}


class DecisionIn(BaseModel):
    confirm: bool = False
    reason: str = Field(default="", max_length=500)


def _load_for_decision(db: Session, approval_id: int, user: User) -> Approval:
    a = db.get(Approval, approval_id)
    if a is None or (a.requested_by_user_id != user.id and "admin" not in user.role_names):
        raise HTTPException(404, detail={"code": "not_found", "message": "Approval not found."})
    if a.status != "pending":
        raise HTTPException(409, detail={"code": "already_decided", "message": f"This action is already {a.status}."})
    return a


@router.post("/approvals/{approval_id}/approve")
def approve(approval_id: int, body: DecisionIn, request: Request, user: User = Depends(get_current_user),
            db: Session = Depends(get_db)) -> dict:
    a = _load_for_decision(db, approval_id, user)
    if a.risk == "destructive" and not body.confirm:
        raise HTTPException(400, detail={"code": "confirmation_required",
                                         "message": f"This permanently changes data: {a.summary}. "
                                                    "Send confirm=true to proceed."})
    a.status, a.decided_by_user_id, a.decided_at = "approved", user.id, utcnow()
    db.commit()
    audit(db, "approval.approved", actor_user_id=user.id, actor_email=user.email, ip=client_ip(request),
          target_type="approval", target_id=a.id, detail={"tool": a.tool, "arguments": a.arguments})
    requester = db.get(User, a.requested_by_user_id) or user
    outcome = call_tool(db, agent=a.agent, tool=a.tool, args=a.arguments, user=requester, approval_id=a.id,
                        ip=client_ip(request))
    db.refresh(a)
    return {"approval": _appr_out(a), "outcome": {"status": outcome.status, "error": outcome.error,
                                                   "code": outcome.code}}


@router.post("/approvals/{approval_id}/reject")
def reject(approval_id: int, body: DecisionIn, request: Request, user: User = Depends(get_current_user),
           db: Session = Depends(get_db)) -> dict:
    a = _load_for_decision(db, approval_id, user)
    a.status, a.decided_by_user_id, a.decided_at = "rejected", user.id, utcnow()
    a.result = {"reason": body.reason}
    db.commit()
    audit(db, "approval.rejected", actor_user_id=user.id, actor_email=user.email, ip=client_ip(request),
          target_type="approval", target_id=a.id, detail={"tool": a.tool, "reason": body.reason})
    return {"approval": _appr_out(a)}
