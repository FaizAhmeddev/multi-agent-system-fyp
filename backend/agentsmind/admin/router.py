"""Admin: users. (Roles editing, audit viewer and system health screens come later.)"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import service
from ..auth.deps import client_ip, require_roles
from ..auth.router import user_out
from ..auth.schemas import CreateUserIn, MessageOut, UserOut
from ..db.models import OutboundEmail, ToolCall, User
from ..db.session import get_db
from ..queue.core import STATUSES, get_queue

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


@router.get("/queue")
def queue_stats(_: User = Depends(require_roles("admin"))) -> dict:
    from ..settings import get_settings

    return {"backend": get_settings().queue_backend, "queues": get_queue().stats()}


@router.get("/queue/tasks")
def queue_tasks(status: str | None = Query(None), limit: int = Query(50, ge=1, le=200),
                offset: int = Query(0, ge=0), _: User = Depends(require_roles("admin"))) -> dict:
    if status is not None and status not in STATUSES:
        raise HTTPException(422, detail={"code": "validation_error", "message": f"status must be one of {STATUSES}"})
    items = get_queue().list(status=status, limit=limit, offset=offset)
    return {"items": [{"id": t.id, "queue": t.queue, "kind": t.kind, "status": t.status, "attempts": t.attempts,
                       "max_attempts": t.max_attempts, "last_error": t.last_error,
                       "available_at": t.available_at.isoformat(),
                       "finished_at": t.finished_at.isoformat() if t.finished_at else None} for t in items]}


@router.post("/queue/tasks/{task_id}/retry", response_model=MessageOut)
def queue_retry(task_id: int, request: Request, actor: User = Depends(require_roles("admin")),
                db: Session = Depends(get_db)) -> MessageOut:
    if not get_queue().retry_dead(task_id):
        raise HTTPException(409, detail={"code": "not_dead", "message": "Only dead tasks can be retried."})
    from ..audit import audit

    audit(db, "queue.retry", actor_user_id=actor.id, actor_email=actor.email, ip=client_ip(request),
          target_type="queue_task", target_id=task_id)
    return MessageOut(message=f"Task {task_id} queued again.")


@router.get("/tool-calls")
def tool_calls(limit: int = Query(50, ge=1, le=200), status: str | None = Query(None),
               _: User = Depends(require_roles("admin")), db: Session = Depends(get_db)) -> dict:
    q = select(ToolCall).order_by(ToolCall.id.desc()).limit(limit)
    if status:
        q = q.where(ToolCall.status == status)
    return {"items": [{"id": c.id, "at": c.at.isoformat(), "agent": c.agent, "tool": c.tool, "server": c.server,
                       "user_id": c.user_id, "status": c.status, "error": c.error, "latency_ms": c.latency_ms,
                       "inputs": c.inputs_redacted, "approval_id": c.approval_id} for c in db.scalars(q)]}


@router.get("/mcp")
def mcp_health(_: User = Depends(require_roles("admin"))) -> dict:
    """Each MCP server: configured, reachable, tool count and latency."""
    import time

    from ..agents.catalog import TOOLS
    from ..mcp.client import MCPCallError, list_tools, server_configs

    configured = server_configs()
    out = []
    for name in sorted({t.server for t in TOOLS.values()}):
        expected = sorted(t for t, spec in TOOLS.items() if spec.server == name)
        row = {"server": name, "configured": name in configured, "expected_tools": expected}
        if name in configured:
            start = time.perf_counter()
            try:
                tools = list_tools(name)
                row.update(reachable=True, tools=[t["name"] for t in tools],
                           missing=sorted(set(expected) - {t["name"] for t in tools}))
            except MCPCallError as exc:
                row.update(reachable=False, error=str(exc))
            except Exception as exc:  # noqa: BLE001 - shown on the health screen
                row.update(reachable=False, error=f"{type(exc).__name__}: {exc}")
            row["latency_ms"] = int((time.perf_counter() - start) * 1000)
        else:
            row.update(reachable=False, error="Not configured. Set the URL and token in .env.")
        out.append(row)
    return {"servers": out}
