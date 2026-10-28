"""IT Helpdesk business logic, shared by the REST API, the public form and the staff screens."""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from portal_common.core import EXT_FOR, new_token, safe_filename, sha256_hex, sniff_type, utcnow

from .models import (
    CATEGORIES,
    DEPARTMENTS,
    PRIORITIES,
    STATUSES,
    TRANSITIONS,
    Attachment,
    AuditEvent,
    Comment,
    Ticket,
    parse_ticket_number,
    response_time_text,
    sla_due,
    ticket_number,
)

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
ALLOWED_UPLOAD_TYPES = ("application/pdf", "image/png", "image/jpeg", "text/plain")

Category = Literal["network", "hardware", "software", "account", "email", "printer", "other"]
Priority = Literal["low", "medium", "high", "urgent"]
Status = Literal["open", "in_progress", "resolved", "closed"]
assert set(Category.__args__) == set(CATEGORIES) and set(Priority.__args__) == set(PRIORITIES)


class ServiceError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class TicketIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requester_name: str = Field(min_length=2, max_length=200)
    requester_email: EmailStr
    department: str = Field(min_length=2, max_length=80)
    category: Category
    priority: Priority = "medium"
    summary: str = Field(default="", max_length=200)
    description: str = Field(min_length=10, max_length=5000)

    @field_validator("requester_name", "summary", "description")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @field_validator("department")
    @classmethod
    def _dept(cls, v: str) -> str:
        v = " ".join(v.split())
        for d in DEPARTMENTS:
            if d.lower() == v.lower():
                return d
        raise ValueError(f"must be one of: {', '.join(DEPARTMENTS)}")


class StatusChangeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Status
    comment: str = Field(default="", max_length=5000)


class CommentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=5000)
    internal: bool = False


def _audit(db: Session, actor: str, action: str, target: str, detail: dict[str, Any] | None = None) -> None:
    db.add(AuditEvent(actor=actor, action=action, target=target, detail=detail or {}))


def ticket_out(t: Ticket, *, include_internal: bool = True) -> dict[str, Any]:
    return {
        "number": t.number, "id": t.id, "requester_name": t.requester_name, "requester_email": t.requester_email,
        "department": t.department, "category": t.category, "category_label": CATEGORIES[t.category],
        "priority": t.priority, "summary": t.summary, "description": t.description, "status": t.status,
        "status_label": STATUSES[t.status], "assignee": t.assignee, "source": t.source,
        "sla_due_at": t.sla_due_at.isoformat(), "sla_breached": bool(t.status in ("open", "in_progress")
                                                                       and t.sla_due_at < utcnow()),
        "expected_response": response_time_text(t.priority),
        "created_at": t.created_at.isoformat(), "updated_at": t.updated_at.isoformat(),
        "resolved_at": t.resolved_at.isoformat() if t.resolved_at else None,
        "closed_at": t.closed_at.isoformat() if t.closed_at else None,
        "comments": [{"author": c.author, "body": c.body, "internal": c.internal, "created_at": c.created_at.isoformat()}
                     for c in t.comments if include_internal or not c.internal],
        "attachments": [{"name": a.original_name, "mime_type": a.mime_type, "size_bytes": a.size_bytes}
                        for a in t.attachments],
    }


def get_ticket(db: Session, number: str) -> Ticket:
    tid = parse_ticket_number(number)
    t = db.get(Ticket, tid) if tid else None
    if t is None:
        raise ServiceError(404, "not_found", f"No ticket {number}.")
    return t


def check_tracking(t: Ticket, token: str | None) -> bool:
    return bool(token) and sha256_hex(token) == t.tracking_hash


def validate_upload(filename: str, data: bytes) -> tuple[str, str]:
    """Return (safe_name, mime). Raises ServiceError on a bad file."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise ServiceError(413, "file_too_large", "The attachment is larger than 5 MB.")
    if not data:
        raise ServiceError(422, "empty_file", "The attachment is empty.")
    mime = sniff_type(data)
    if mime not in ALLOWED_UPLOAD_TYPES:
        raise ServiceError(415, "file_type", "Attach a PDF, PNG, JPEG or plain text file.")
    return safe_filename(filename), mime


def create_ticket(db: Session, data: TicketIn, *, actor: str, source: str = "portal",
                  idempotency_key: str | None = None, attachment: tuple[str, bytes] | None = None,
                  upload_dir: Path | None = None) -> tuple[Ticket, str | None, bool]:
    """Returns (ticket, tracking_token or None on replay, created)."""
    if idempotency_key:
        existing = db.scalar(select(Ticket).where(Ticket.idempotency_key == idempotency_key))
        if existing is not None:
            return existing, None, False
    att = None
    if attachment is not None:
        safe, mime = validate_upload(*attachment)
        att = (safe, mime, attachment[1])
    token = new_token(18)
    now = utcnow()
    summary = data.summary or (data.description.splitlines()[0][:120] if data.description else "")
    t = Ticket(requester_name=data.requester_name, requester_email=str(data.requester_email).lower(),
               department=data.department, category=data.category, priority=data.priority, summary=summary,
               description=data.description, status="open", source=source, tracking_hash=sha256_hex(token),
               idempotency_key=idempotency_key, sla_due_at=sla_due(data.priority, now), created_at=now, updated_at=now)
    db.add(t)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(Ticket).where(Ticket.idempotency_key == idempotency_key))
        if existing is not None:
            return existing, None, False
        raise
    if att is not None and upload_dir is not None:
        safe, mime, raw = att
        upload_dir.mkdir(parents=True, exist_ok=True)
        stored = uuid.uuid4().hex + EXT_FOR[mime]
        (upload_dir / stored).write_bytes(raw)  # random name: the original name never touches the filesystem
        db.add(Attachment(ticket_id=t.id, original_name=safe, stored_name=stored, mime_type=mime,
                          size_bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
    _audit(db, actor, "ticket.create", ticket_number(t.id), {"source": source, "priority": data.priority})
    db.commit()
    return t, token, True


def query_tickets(db: Session, *, status: str = "", priority: str = "", category: str = "", q: str = "",
                  assignee: str = "", requester_email: str = "", sort: str = "created_at", order: str = "desc",
                  page: int = 1, page_size: int = 25) -> tuple[list[Ticket], int]:
    stmt = select(Ticket)
    if status:
        stmt = stmt.where(Ticket.status == status)
    if priority:
        stmt = stmt.where(Ticket.priority == priority)
    if category:
        stmt = stmt.where(Ticket.category == category)
    if assignee:
        stmt = stmt.where(Ticket.assignee == assignee)
    if requester_email:
        stmt = stmt.where(Ticket.requester_email == requester_email.lower())
    if q:
        like = f"%{q.strip().lower()}%"
        tid = parse_ticket_number(q)
        conds = [func.lower(Ticket.summary).like(like), func.lower(Ticket.description).like(like),
                 func.lower(Ticket.requester_name).like(like)]
        if tid:
            conds.append(Ticket.id == tid)
        stmt = stmt.where(or_(*conds))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    col = {"created_at": Ticket.created_at, "sla_due_at": Ticket.sla_due_at, "priority": Ticket.priority,
           "status": Ticket.status, "id": Ticket.id}.get(sort, Ticket.created_at)
    stmt = stmt.order_by(col.desc() if order == "desc" else col.asc(), Ticket.id.desc())
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    return list(db.scalars(stmt)), total


def change_status(db: Session, number: str, change: StatusChangeIn, *, actor: str) -> Ticket:
    t = get_ticket(db, number)
    if change.status == t.status:
        raise ServiceError(409, "no_change", f"{t.number} is already {STATUSES[t.status].lower()}.")
    if change.status not in TRANSITIONS[t.status]:
        allowed = ", ".join(STATUSES[s] for s in sorted(TRANSITIONS[t.status])) or "none (ticket is closed)"
        raise ServiceError(409, "invalid_transition",
                           f"{t.number} cannot go from {STATUSES[t.status]} to {STATUSES[change.status]}. "
                           f"Allowed: {allowed}.")
    old = t.status
    t.status = change.status
    now = utcnow()
    if change.status == "resolved":
        t.resolved_at = now
    if change.status == "closed":
        t.closed_at = now
    if change.status in ("open", "in_progress"):
        t.resolved_at = None
    if change.comment.strip():
        db.add(Comment(ticket_id=t.id, author=actor, body=change.comment.strip(), internal=False))
    _audit(db, actor, "ticket.status", t.number, {"from": old, "to": change.status})
    db.commit()
    db.refresh(t)
    return t


def add_comment(db: Session, number: str, data: CommentIn, *, actor: str) -> Ticket:
    t = get_ticket(db, number)
    if t.status == "closed":
        raise ServiceError(409, "ticket_closed", f"{t.number} is closed. Raise a new complaint instead.")
    db.add(Comment(ticket_id=t.id, author=actor, body=data.body.strip(), internal=data.internal))
    _audit(db, actor, "ticket.comment", t.number, {"internal": data.internal})
    db.commit()
    db.refresh(t)
    return t


def assign(db: Session, number: str, assignee: str, *, actor: str) -> Ticket:
    t = get_ticket(db, number)
    t.assignee = assignee.strip().lower()[:254]
    _audit(db, actor, "ticket.assign", t.number, {"assignee": t.assignee})
    db.commit()
    return t
