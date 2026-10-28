"""Finance and IT workspace APIs for the UI. Every call goes through the tool gateway
(allow-lists, roles, approvals, tool_calls log) and from there through MCP.

Form submissions here are the user's own explicit action, so they are recorded as
direct approvals (approved by that user). Agent-proposed actions use approval cards.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.orm import Session

from ..agents.gateway import ToolOutcome, call_tool
from ..auth.deps import client_ip, get_current_user
from ..db.models import User
from ..db.session import get_db
from ..rbac import can_open_department, department_denial_reason, has_any

router = APIRouter(prefix="/api", tags=["workspaces"])


def _need(user: User, slug: str) -> None:
    if not can_open_department(user.role_names, slug):
        raise HTTPException(403, detail={"code": "forbidden", "message": department_denial_reason(slug)})


def _result(out: ToolOutcome, *, created: bool = False) -> dict[str, Any]:
    if out.status == "ok":
        return {"result": out.result, "tool": out.tool, "approval_id": out.approval_id, "source": out.tool}
    if out.status == "denied":
        raise HTTPException(403, detail={"code": out.code, "message": out.error})
    if out.code in ("tool_unavailable", "unreachable", "not_configured", "unauthorized"):
        raise HTTPException(503, detail={"code": out.code, "message": out.error})
    status = 409 if "already" in out.error.lower() or "cannot go from" in out.error else 400
    if "no person with id" in out.error.lower() or "no ticket" in out.error.lower():
        status = 404
    raise HTTPException(status, detail={"code": out.code or "tool_error", "message": out.error})


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v not in (None, "")}


# ── Finance ──────────────────────────────────────────────────────────────────

Department = Literal["Finance", "HR", "IT", "Operations", "Sales", "Marketing", "Engineering", "Administration"]


class PersonCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    department: Department
    job_title: str = Field(min_length=2, max_length=150)
    employment_type: Literal["full_time", "part_time", "contract", "intern"] = "full_time"
    monthly_salary: str = Field(pattern=r"^\d{1,8}(\.\d{1,2})?$")
    currency: Literal["PKR", "USD", "EUR", "GBP", "AED"] = "PKR"
    status: Literal["active", "inactive"] = "active"
    start_date: date
    notes: str = Field(default="", max_length=2000)


class PersonUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str | None = Field(default=None, min_length=2, max_length=200)
    email: EmailStr | None = None
    department: Department | None = None
    job_title: str | None = Field(default=None, min_length=2, max_length=150)
    employment_type: Literal["full_time", "part_time", "contract", "intern"] | None = None
    monthly_salary: str | None = Field(default=None, pattern=r"^\d{1,8}(\.\d{1,2})?$")
    currency: Literal["PKR", "USD", "EUR", "GBP", "AED"] | None = None
    status: Literal["active", "inactive"] | None = None
    start_date: date | None = None
    notes: str | None = Field(default=None, max_length=2000)


class DeleteConfirm(BaseModel):
    confirm: bool = False
    confirm_name: str = Field(default="", max_length=200)


@router.get("/finance/people")
def finance_people(request: Request, q: str = Query("", max_length=100), department: str = "", status: str = "",
                   employment_type: str = "", sort: str = "full_name", order: str = "asc",
                   page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    _need(user, "finance")
    if q.strip():
        out = call_tool(db, agent="finance", tool="finance_search_people", user=user, ip=client_ip(request),
                        args={"query": q.strip(), "limit": page_size})
    else:
        out = call_tool(db, agent="finance", tool="finance_list_people", user=user, ip=client_ip(request),
                        args=_clean({"page": page, "page_size": page_size, "department": department,
                                     "status": status, "employment_type": employment_type, "sort": sort,
                                     "order": order}))
    return _result(out)


@router.get("/finance/people/{person_id}")
def finance_person(person_id: int, request: Request, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)) -> dict:
    _need(user, "finance")
    return _result(call_tool(db, agent="finance", tool="finance_get_person", args={"person_id": person_id},
                             user=user, ip=client_ip(request)))


@router.get("/finance/summary")
def finance_summary(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    _need(user, "finance")
    return _result(call_tool(db, agent="finance", tool="finance_summary", args={}, user=user, ip=client_ip(request)))


@router.get("/finance/payments")
def finance_payments(request: Request, person_id: int | None = None, month: str = "", status: str = "",
                     page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
                     user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    _need(user, "finance")
    return _result(call_tool(db, agent="finance", tool="finance_list_payments", user=user, ip=client_ip(request),
                             args=_clean({"person_id": person_id, "month": month, "status": status, "page": page,
                                          "page_size": page_size})))


@router.post("/finance/people", status_code=201)
def finance_create(body: PersonCreate, request: Request, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db),
                   idempotency_key: str | None = Header(default=None, max_length=100)) -> dict:
    _need(user, "finance")
    args = body.model_dump(mode="json") | {"actor": user.email}
    return _result(call_tool(db, agent="finance", tool="finance_create_person", args=args, user=user, direct=True,
                             request_key=idempotency_key, ip=client_ip(request),
                             summary=f"Add {body.full_name} ({body.job_title}, {body.department})"))


@router.patch("/finance/people/{person_id}")
def finance_update(person_id: int, body: PersonUpdate, request: Request, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db),
                   idempotency_key: str | None = Header(default=None, max_length=100)) -> dict:
    _need(user, "finance")
    fields = body.model_dump(mode="json", exclude_none=True)
    if not fields:
        raise HTTPException(422, detail={"code": "validation_error", "message": "Change at least one field."})
    args = {"person_id": person_id, **fields, "actor": user.email}
    return _result(call_tool(db, agent="finance", tool="finance_update_person", args=args, user=user, direct=True,
                             request_key=idempotency_key, ip=client_ip(request),
                             summary=f"Update person #{person_id}: {', '.join(sorted(fields))}"))


@router.delete("/finance/people/{person_id}")
def finance_delete(person_id: int, body: DeleteConfirm, request: Request, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db),
                   idempotency_key: str | None = Header(default=None, max_length=100)) -> dict:
    _need(user, "finance")
    current = call_tool(db, agent="finance", tool="finance_get_person", args={"person_id": person_id}, user=user,
                        ip=client_ip(request))
    person = _result(current)["result"]
    if not body.confirm or " ".join(body.confirm_name.split()).lower() != person["full_name"].lower():
        raise HTTPException(400, detail={
            "code": "confirmation_required",
            "message": f"This permanently deletes {person['full_name']} ({person['email']}) and their payments. "
                       f"Send confirm=true and confirm_name='{person['full_name']}' to proceed."})
    return _result(call_tool(db, agent="finance", tool="finance_delete_person", user=user, direct=True,
                             args={"person_id": person_id, "actor": user.email}, request_key=idempotency_key,
                             ip=client_ip(request), summary=f"Delete {person['full_name']} (person #{person_id})"))


# ── IT ───────────────────────────────────────────────────────────────────────

class TicketCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    department: Department
    category: Literal["network", "hardware", "software", "account", "email", "printer", "other"]
    priority: Literal["low", "medium", "high", "urgent"] = "medium"
    summary: str = Field(default="", max_length=200)
    description: str = Field(min_length=10, max_length=5000)


class StatusChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["open", "in_progress", "resolved", "closed"]
    comment: str = Field(default="", max_length=5000)


class CommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=5000)


def _is_it(user: User) -> bool:
    return has_any(user.role_names, frozenset({"it"}))


def _own_ticket(db: Session, user: User, number: str, ip: str) -> dict[str, Any]:
    # The gateway hides other people's tickets from non-IT users (reported as not found).
    return _result(call_tool(db, agent="it", tool="it_get_ticket", args={"number": number}, user=user, ip=ip))["result"]


@router.get("/it/tickets")
def it_tickets(request: Request, status: str = "", priority: str = "", category: str = "",
               q: str = Query("", max_length=100), page: int = Query(1, ge=1),
               page_size: int = Query(25, ge=1, le=100), user: User = Depends(get_current_user),
               db: Session = Depends(get_db)) -> dict:
    args = _clean({"status": status, "priority": priority, "category": category, "query": q, "page": page,
                   "page_size": page_size})
    # Staff outside IT only ever see their own tickets: the gateway enforces this scope.
    return _result(call_tool(db, agent="it", tool="it_list_tickets", args=args, user=user, ip=client_ip(request)))


@router.get("/it/tickets/{number}")
def it_ticket(number: str, request: Request, user: User = Depends(get_current_user),
              db: Session = Depends(get_db)) -> dict:
    return {"result": _own_ticket(db, user, number, client_ip(request)), "tool": "it_get_ticket",
            "source": "it_get_ticket"}


@router.post("/it/tickets", status_code=201)
def it_create(body: TicketCreate, request: Request, user: User = Depends(get_current_user),
              db: Session = Depends(get_db), idempotency_key: str | None = Header(default=None, max_length=100)) -> dict:
    args = {"requester_name": user.full_name, "requester_email": user.email, **body.model_dump()}
    return _result(call_tool(db, agent="it", tool="it_create_ticket", args=args, user=user, direct=True,
                             request_key=idempotency_key, ip=client_ip(request),
                             summary=f"Raise IT complaint: {body.summary or body.description[:80]}"))


@router.patch("/it/tickets/{number}/status")
def it_status(number: str, body: StatusChange, request: Request, user: User = Depends(get_current_user),
              db: Session = Depends(get_db), idempotency_key: str | None = Header(default=None, max_length=100)) -> dict:
    _need(user, "it")
    return _result(call_tool(db, agent="it", tool="it_update_ticket_status", user=user, direct=True,
                             args={"number": number, **body.model_dump(), "actor": user.email},
                             request_key=idempotency_key, ip=client_ip(request),
                             summary=f"Move {number} to {body.status}"))


@router.post("/it/tickets/{number}/comments", status_code=201)
def it_comment(number: str, body: CommentCreate, request: Request, user: User = Depends(get_current_user),
               db: Session = Depends(get_db), idempotency_key: str | None = Header(default=None, max_length=100)) -> dict:
    _own_ticket(db, user, number, client_ip(request))
    return _result(call_tool(db, agent="it", tool="it_add_comment", user=user, direct=True,
                             args={"number": number, "body": body.body, "actor": user.email},
                             request_key=idempotency_key, ip=client_ip(request), summary=f"Comment on {number}"))
