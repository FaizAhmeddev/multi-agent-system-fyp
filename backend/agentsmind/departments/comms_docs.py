"""Documents, Communications (inbox and email) and Calendar workspace APIs for the UI.

Like the Finance and IT workspaces, every call goes through the tool gateway and MCP.
Reads run directly. Sends, event creation and cancellation are the user's own explicit
action from a form, so they are recorded as direct approvals made by that user.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import AwareDatetime, BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.orm import Session

from ..agents.gateway import call_tool
from ..agents.llm import LLMError, get_llm
from ..agents.untrusted import wrap
from ..auth.deps import client_ip, get_current_user
from ..db.models import User
from ..db.session import get_db
from ..settings import get_settings
from .workspaces import _need, _result

router = APIRouter(prefix="/api", tags=["workspaces"])


# ── Documents ────────────────────────────────────────────────────────────────

@router.get("/documents/files")
def doc_files(request: Request, folder: str = Query("", max_length=300), page_token: str = Query("", max_length=500),
              user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    _need(user, "documents")
    args: dict[str, Any] = {"page_size": 50}
    if folder:
        args["folder"] = folder
    if page_token:
        args["page_token"] = page_token
    return _result(call_tool(db, agent="documents", tool="drive_list_files", args=args, user=user, ip=client_ip(request)))


@router.get("/documents/search")
def doc_search(request: Request, q: str = Query(..., min_length=2, max_length=200),
               user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    _need(user, "documents")
    return _result(call_tool(db, agent="documents", tool="drive_search", args={"query": q, "page_size": 25}, user=user,
                             ip=client_ip(request)))


@router.get("/documents/files/{file_id}")
def doc_read(file_id: str, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    _need(user, "documents")
    return _result(call_tool(db, agent="documents", tool="drive_read_file", args={"file_id": file_id}, user=user,
                             ip=client_ip(request)))


@router.post("/documents/files/{file_id}/summary")
def doc_summary(file_id: str, request: Request, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)) -> dict:
    """Summarise one file. File text is wrapped as untrusted data before a model sees it."""
    from ..agents import ported as P
    from ..assistant.agents.documents import extractive_summary

    _need(user, "documents")
    doc = _result(call_tool(db, agent="documents", tool="drive_read_file", args={"file_id": file_id}, user=user,
                            ip=client_ip(request)))["result"]
    w = wrap(doc["text"], source=f"file:{file_id}")
    llm = get_llm()
    if llm.simulated:
        text, simulated = extractive_summary(doc["text"]), True
    else:
        try:
            text = llm.complete(P.doc_summarize_prompt(w.text, doc["file"]["name"], user.full_name),
                                temperature=P.Temperature.DOCS).text
        except LLMError as exc:
            raise HTTPException(502, detail={"code": "llm_error", "message": str(exc)}) from None
        simulated = False
    return {"file": doc["file"], "summary": text, "simulated": simulated or bool(doc.get("simulated")),
            "model": llm.model, "injection_suspected": w.injection_suspected, "truncated": doc.get("truncated", False)}


# ── Communications: inbox and email ─────────────────────────────────────────

@router.get("/communications/inbox")
def inbox(request: Request, unread_only: bool = False, q: str = Query("", max_length=200),
          page_token: str = Query("", max_length=500), user: User = Depends(get_current_user),
          db: Session = Depends(get_db)) -> dict:
    from ..agents.untrusted import injection_signals

    _need(user, "communications")
    args: dict[str, Any] = {"max_results": 25, "unread_only": unread_only}
    if q:
        args["query"] = q
    if page_token:
        args["page_token"] = page_token
    out = _result(call_tool(db, agent="email", tool="gmail_read_inbox", args=args, user=user, ip=client_ip(request)))
    for m in out["result"].get("items", []):
        m["suspicious"] = bool(injection_signals(m.get("body", "")))
    return out


class SendIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: list[EmailStr] = Field(min_length=1, max_length=20)
    cc: list[EmailStr] = Field(default_factory=list, max_length=20)
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20000)
    thread_id: str | None = Field(default=None, max_length=200)


@router.post("/communications/send", status_code=201)
def send(body: SendIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db),
         idempotency_key: str | None = Header(default=None, max_length=100)) -> dict:
    _need(user, "communications")
    if "\n" in body.subject or "\r" in body.subject:
        raise HTTPException(422, detail={"code": "validation_error", "message": "The subject must be one line."})
    args = {"to": [str(x) for x in body.to], "subject": body.subject, "body": body.body}
    if body.cc:
        args["cc"] = [str(x) for x in body.cc]
    if body.thread_id:
        args["thread_id"] = body.thread_id
    return _result(call_tool(db, agent="email", tool="gmail_send_email", args=args, user=user, direct=True,
                             request_key=idempotency_key, ip=client_ip(request),
                             summary=f"Send email to {', '.join(args['to'])}: {body.subject}"[:500]))


# ── Calendar ─────────────────────────────────────────────────────────────────

def _tz() -> ZoneInfo:
    return ZoneInfo(get_settings().timezone)


@router.get("/calendar/events")
def events(request: Request, start: AwareDatetime | None = None, days: int = Query(7, ge=1, le=31),
           user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    _need(user, "communications")
    a = start or datetime.now(_tz()).replace(hour=0, minute=0, second=0, microsecond=0)
    b = a + timedelta(days=days)
    return _result(call_tool(db, agent="calendar", tool="calendar_list_events", user=user, ip=client_ip(request),
                             args={"time_min": a.isoformat(), "time_max": b.isoformat(), "max_results": 100}))


@router.get("/calendar/availability")
def availability(request: Request, start: AwareDatetime, end: AwareDatetime, user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)) -> dict:
    _need(user, "communications")
    if end <= start:
        raise HTTPException(422, detail={"code": "validation_error", "message": "The end must be after the start."})
    return _result(call_tool(db, agent="calendar", tool="calendar_check_availability", user=user,
                             ip=client_ip(request), args={"start": start.isoformat(), "end": end.isoformat()}))


class EventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=1, max_length=200)
    start: AwareDatetime
    end: AwareDatetime
    description: str = Field(default="", max_length=5000)
    location: str = Field(default="", max_length=300)
    attendees: list[EmailStr] = Field(default_factory=list, max_length=50)
    add_meet: bool = False


@router.post("/calendar/events", status_code=201)
def create_event(body: EventIn, request: Request, user: User = Depends(get_current_user),
                 db: Session = Depends(get_db), idempotency_key: str | None = Header(default=None, max_length=100)) -> dict:
    _need(user, "communications")
    if body.end <= body.start:
        raise HTTPException(422, detail={"code": "validation_error", "message": "The end must be after the start."})
    if body.start < datetime.now(_tz()):
        raise HTTPException(422, detail={"code": "validation_error", "message": "The start time has already passed."})
    args = {"summary": body.summary, "start": body.start.isoformat(), "end": body.end.isoformat(),
            "timezone": get_settings().timezone, "description": body.description, "location": body.location,
            "attendees": [str(a) for a in body.attendees], "add_meet": body.add_meet}
    return _result(call_tool(db, agent="calendar", tool="calendar_create_event", args=args, user=user, direct=True,
                             request_key=idempotency_key, ip=client_ip(request),
                             summary=f"Create \"{body.summary}\" at {body.start.isoformat()}"))


class CancelIn(BaseModel):
    confirm: bool = False


@router.delete("/calendar/events/{event_id}")
def cancel_event(event_id: str, body: CancelIn, request: Request, user: User = Depends(get_current_user),
                 db: Session = Depends(get_db), idempotency_key: str | None = Header(default=None, max_length=100)) -> dict:
    _need(user, "communications")
    if not body.confirm:
        raise HTTPException(400, detail={"code": "confirmation_required",
                                         "message": "Cancelling removes the event. Send confirm=true to proceed."})
    return _result(call_tool(db, agent="calendar", tool="calendar_cancel_event", args={"event_id": event_id}, user=user,
                             direct=True, request_key=idempotency_key, ip=client_ip(request),
                             summary=f"Cancel event {event_id}"))
