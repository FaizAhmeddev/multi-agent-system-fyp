"""Assistant API: send a message (JSON or Server-Sent Events), list conversations, HR candidates board."""
from __future__ import annotations

import json
import queue
import threading
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..auth.deps import client_ip, get_current_user, require_roles
from ..db.models import Candidate, Conversation, CVRecord, Message, User
from ..db.session import SessionLocal, get_db
from .service import handle_message

router = APIRouter(prefix="/api", tags=["assistant"])


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    conversation_id: int | None = None


@router.post("/assistant/messages")
def send_message(body: MessageIn, request: Request, user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)) -> dict:
    try:
        return handle_message(db, user, body.text, conversation_id=body.conversation_id, ip=client_ip(request))
    except LookupError as exc:
        raise HTTPException(404, detail={"code": "not_found", "message": str(exc)}) from None


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.post("/assistant/messages/stream")
def stream_message(body: MessageIn, request: Request, user: User = Depends(get_current_user)) -> StreamingResponse:
    """Server-Sent Events: `plan`, `agent` and `step` events while agents work, then one `result` event."""
    q: queue.Queue = queue.Queue()
    ip, user_id = client_ip(request), user.id

    def work() -> None:
        with SessionLocal() as db:
            u = db.get(User, user_id)
            try:
                res = handle_message(db, u, body.text, conversation_id=body.conversation_id, ip=ip,
                                     on_event=lambda e: q.put(("progress", e)))
                q.put(("result", res))
            except LookupError as exc:
                q.put(("error", {"code": "not_found", "message": str(exc)}))
            except Exception as exc:  # noqa: BLE001 - reported to the client, logged by the handler
                q.put(("error", {"code": "internal", "message": f"The assistant failed ({type(exc).__name__})."}))
            finally:
                q.put(None)

    threading.Thread(target=work, daemon=True).start()

    def gen() -> Iterator[str]:
        yield ": connected\n\n"
        while True:
            try:
                item = q.get(timeout=15)
            except queue.Empty:
                yield ": keep-alive\n\n"
                continue
            if item is None:
                return
            kind, data = item
            yield _sse(data.get("type", kind) if kind == "progress" else kind, data)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/assistant/conversations")
def conversations(page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    q = select(Conversation).where(Conversation.user_id == user.id)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(Conversation.updated_at.desc()).offset((page - 1) * page_size).limit(page_size))
    return {"items": [{"id": c.id, "title": c.title, "updated_at": c.updated_at.isoformat()} for c in rows],
            "total": total, "page": page, "page_size": page_size}


@router.get("/assistant/conversations/{conversation_id}")
def conversation(conversation_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    c = db.get(Conversation, conversation_id)
    if c is None or c.user_id != user.id:
        raise HTTPException(404, detail={"code": "not_found", "message": "Conversation not found."})
    msgs = db.scalars(select(Message).where(Message.conversation_id == c.id).order_by(Message.id)).all()
    return {"id": c.id, "title": c.title,
            "messages": [{"id": m.id, "role": m.role, "content": m.content, "cards": (m.meta or {}).get("cards", []),
                          "created_at": m.created_at.isoformat()} for m in msgs]}


# ---------------------------------------------------------------- HR candidates board

STAGES = ("new", "screened", "shortlisted", "interview", "rejected")


def _latest_cv(db: Session, cand_id: int) -> CVRecord | None:
    return db.scalar(select(CVRecord).where(CVRecord.candidate_id == cand_id).order_by(CVRecord.id.desc()).limit(1))


def _cand_out(c: Candidate, rec: CVRecord | None, full: bool = False) -> dict:
    out = {"id": c.id, "name": c.full_name, "job_title": c.job_title, "stage": c.stage, "notes": c.notes,
           "updated_at": c.updated_at.isoformat(), "rubric_score": rec.rubric_score if rec else None,
           "keyword_score": rec.keyword_score if rec else None,
           "needs_human_review": rec.needs_human_review if rec else False,
           "recommendation": (rec.details or {}).get("recommendation") if rec else None,
           "simulated": bool((rec.details or {}).get("simulated")) if rec else False,
           "email": c.email, "phone": c.phone, "location": c.location, "source": c.source}
    if full and rec is not None:
        out.update(matched=rec.matched_skills, missing=rec.missing_skills, details=rec.details)
    return out


@router.get("/hr/candidates")
def list_candidates(stage: str | None = Query(None), job_title: str | None = Query(None, max_length=200),
                    _: User = Depends(require_roles("hr")), db: Session = Depends(get_db)) -> dict:
    if stage is not None and stage not in STAGES:
        raise HTTPException(422, detail={"code": "validation_error", "message": f"stage must be one of {STAGES}"})
    q = select(Candidate).order_by(Candidate.updated_at.desc())
    if stage:
        q = q.where(Candidate.stage == stage)
    if job_title:
        q = q.where(Candidate.job_title == job_title)
    items = [_cand_out(c, _latest_cv(db, c.id)) for c in db.scalars(q.limit(200))]
    return {"items": items, "stages": list(STAGES)}


@router.get("/hr/candidates/{candidate_id}")
def get_candidate(candidate_id: int, _: User = Depends(require_roles("hr")), db: Session = Depends(get_db)) -> dict:
    c = db.get(Candidate, candidate_id)
    if c is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "Candidate not found."})
    return _cand_out(c, _latest_cv(db, c.id), full=True)


class StageIn(BaseModel):
    stage: str = Field(pattern="^(new|screened|shortlisted|interview|rejected)$")
    notes: str | None = Field(default=None, max_length=4000)


@router.patch("/hr/candidates/{candidate_id}")
def move_candidate(candidate_id: int, body: StageIn, request: Request, actor: User = Depends(require_roles("hr")),
                   db: Session = Depends(get_db)) -> dict:
    """A person moves candidates between stages; the screening never does."""
    c = db.get(Candidate, candidate_id)
    if c is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "Candidate not found."})
    old = c.stage
    c.stage = body.stage
    if body.notes is not None:
        c.notes = body.notes
    db.commit()
    audit(db, "hr.candidate.stage", actor_user_id=actor.id, actor_email=actor.email, ip=client_ip(request),
          target_type="candidate", target_id=c.id, detail={"from": old, "to": body.stage})
    return _cand_out(c, _latest_cv(db, c.id))
