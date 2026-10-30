"""The assistant on top of the database: tool gateway, conversations, agent runs, candidates."""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..agents.gateway import call_tool
from ..agents.llm import get_llm
from ..audit import audit
from ..db.base import utcnow
from ..db.models import AgentRun, Approval, Candidate, Conversation, CVRecord, Document, Message, User
from ..settings import get_settings
from .base import ToolResult, UserInfo
from .cards import Card
from .orchestrator import run_turn

log = logging.getLogger("agentsmind.assistant")


class DBCtx:
    """Context for one assistant turn. Every tool call goes through the gateway."""

    def __init__(self, db: Session, user: User, *, conversation_id: int, ip: str = "",
                 on_event: Callable[[dict[str, Any]], None] | None = None):
        s = get_settings()
        self.db, self.model_user, self.ip = db, user, ip
        self.user = UserInfo(id=user.id, email=user.email, name=user.full_name, roles=tuple(user.role_names))
        self.tz = s.timezone
        self.now = datetime.now(ZoneInfo(self.tz))
        self.llm = get_llm()
        self.conversation_id = conversation_id
        self._on_event = on_event
        self.run: AgentRun | None = None
        self.runs: list[AgentRun] = []
        self.attachments: list[dict[str, Any]] = []

    # ---------------------------------------------------------------- tools
    def _call(self, agent: str, tool: str, args: dict[str, Any], summary: str = "") -> ToolResult:
        o = call_tool(self.db, agent=agent, tool=tool, args=args, user=self.model_user, summary=summary, ip=self.ip)
        if o.approval_id and self.run is not None and o.status == "approval_required":
            a = self.db.get(Approval, o.approval_id)
            if a is not None and a.agent_run_id is None:
                a.agent_run_id = self.run.id
                self.db.commit()
        return ToolResult(status=o.status, data=o.result, error=o.error, code=o.code, approval_id=o.approval_id)

    def read(self, agent: str, tool: str, args: dict[str, Any]) -> ToolResult:
        return self._call(agent, tool, args)

    def save_pdf(self, title: str, body: str) -> dict[str, Any]:
        from .attachments import save_pdf

        return save_pdf(self.user.id, title, body)

    def find_contact(self, name: str) -> str | None:
        """An email address for a first or full name, when exactly one person matches: AgentsMind users, HR
        employee records and screened candidates."""
        from sqlalchemy import func, or_

        from ..db.hr_models import Employee

        n = name.strip().lower()
        if len(n) < 3:
            return None
        found: set[str] = set()
        for model, col in ((User, User.full_name), (Employee, Employee.full_name), (Candidate, Candidate.full_name)):
            rows = self.db.scalars(select(model).where(or_(func.lower(col) == n, func.lower(col).like(f"{n} %"))))
            for r in rows:
                if getattr(r, "email", ""):
                    found.add(r.email.lower())
        return found.pop() if len(found) == 1 else None

    def propose(self, agent: str, tool: str, args: dict[str, Any], summary: str) -> ToolResult:
        return self._call(agent, tool, args, summary)

    # ---------------------------------------------------------------- events and runs
    def emit(self, event: dict[str, Any]) -> None:
        if event.get("type") == "agent":
            self.run = AgentRun(conversation_id=self.conversation_id, user_id=self.user.id, agent=event["agent"],
                                action="assistant", status="running", input_text=event.get("text", "")[:20000],
                                meta={})
            self.db.add(self.run)
            self.db.commit()
            self.runs.append(self.run)
        if self._on_event is not None:
            try:
                self._on_event(event)
            except Exception:  # noqa: BLE001 - a closed stream must not break the turn
                log.debug("event sink failed", exc_info=True)

    def finish_runs(self, cards: list[Card]) -> None:
        for run in self.runs:
            mine = [c for c in cards if c.agent == run.agent]
            run.status = "failed" if any(c.kind == "error" for c in mine) else "done"
            run.finished_at = utcnow()
            run.output_text = "\n\n".join(c.body for c in mine if c.body)[:20000]
            run.error = next((c.body for c in mine if c.kind == "error"), "")
            run.meta = {"cards": [c.kind for c in mine], "simulated": any(c.simulated for c in mine)}
        self.db.commit()

    def note_denied(self, agent: str, text: str) -> None:
        audit(self.db, "access.denied", actor_user_id=self.user.id, actor_email=self.user.email, outcome="denied",
              ip=self.ip, target_type="agent", target_id=agent, detail={"via": "assistant"})

    # ---------------------------------------------------------------- HR candidates board
    def record_screening(self, *, role: str, jd_text: str, jd_file: dict, rows: list[dict]) -> None:
        db = self.db
        for r in rows:
            src = r.get("source", "drive")
            doc_source = "drive" if src == "drive" else src[:20]
            doc = db.scalar(select(Document).where(Document.source == doc_source, Document.external_id == r["file_id"]))
            if doc is None:
                doc = Document(owner_user_id=self.user.id, source=doc_source, external_id=r["file_id"][:200],
                               filename=r["file"][:255], mime_type="", size_bytes=0, sha256="", storage_path="",
                               text_excerpt="")
                db.add(doc)
                db.flush()
            cand = db.scalar(select(Candidate).where(Candidate.source_ref == r["file_id"][:200],
                                                     Candidate.job_title == role[:200]))
            if cand is None:
                cand = Candidate(full_name=r["candidate"][:200], email=r.get("email", "")[:254], job_title=role[:200],
                                 stage="screened", notes="", source_ref=r["file_id"][:200])
                db.add(cand)
                db.flush()
            elif cand.stage == "new":
                cand.stage = "screened"
            cand.source = src[:20]
            cand.location = (r.get("location") or "")[:100]
            if r.get("email") and not cand.email:
                cand.email = r["email"][:254]
            if r.get("phone") and not cand.phone:
                cand.phone = r["phone"][:40]
            rec = db.scalar(select(CVRecord).where(CVRecord.candidate_id == cand.id, CVRecord.document_id == doc.id))
            if rec is None:
                rec = CVRecord(candidate_id=cand.id, document_id=doc.id)
                db.add(rec)
            rec.job_description = jd_text[:20000]
            rec.rubric_score, rec.keyword_score = r["rubric_score"], r["keyword_score"]
            rec.matched_skills, rec.missing_skills = r["matched"], r["missing"]
            rec.needs_human_review = r["needs_human_review"]
            rec.details = {"rubric": r["rubric"], "review_reasons": r["review_reasons"], "flags": r["flags"],
                           "recommendation": r["recommendation"], "simulated": r["simulated"],
                           "job_description_file": jd_file.get("name", "")}
        db.commit()
        audit(db, "hr.screening", actor_user_id=self.user.id, actor_email=self.user.email, ip=self.ip,
              target_type="role", target_id=role[:100], detail={"cvs": len(rows)})


def _summary_text(cards: list[Card]) -> str:
    parts = []
    for c in cards:
        if c.kind == "approval":
            parts.append(f"Needs your approval: {c.title}")
        elif c.body:
            parts.append(c.body if c.kind != "clarify" else f"Question: {c.body}")
    return "\n\n".join(parts)[:20000] or "Done."


def get_conversation(db: Session, user: User, conversation_id: int | None, first_text: str) -> Conversation:
    if conversation_id is not None:
        conv = db.get(Conversation, conversation_id)
        if conv is None or conv.user_id != user.id:
            raise LookupError("Conversation not found.")
        return conv
    conv = Conversation(user_id=user.id, title=(first_text.strip().splitlines() or ["New conversation"])[0][:120])
    db.add(conv)
    db.commit()
    return conv


def handle_message(db: Session, user: User, text: str, *, conversation_id: int | None = None, ip: str = "",
                   on_event: Callable[[dict[str, Any]], None] | None = None,
                   attachments: list[str] | None = None) -> dict[str, Any]:
    from .attachments import load_many

    conv = get_conversation(db, user, conversation_id, text)
    last = db.scalar(select(Message).where(Message.conversation_id == conv.id, Message.role == "assistant")
                     .order_by(Message.id.desc()).limit(1))
    pending = (last.meta or {}).get("pending") if last is not None else None
    files = load_many(user.id, list(attachments or []))
    if not files:  # "email it to Huzaifa" after attaching a file earlier in the same conversation
        prev = db.scalar(select(Message).where(Message.conversation_id == conv.id, Message.role == "user")
                         .order_by(Message.id.desc()).limit(1))
        files = load_many(user.id, list((prev.meta or {}).get("attachments") or [])) if prev is not None else []
    db.add(Message(conversation_id=conv.id, role="user", content=text[:20000],
                   meta={"attachments": [f["id"] for f in files], "attachment_names": [f["name"] for f in files]}))
    db.commit()
    ctx = DBCtx(db, user, conversation_id=conv.id, ip=ip, on_event=on_event)
    ctx.attachments = files
    result = run_turn(ctx, text, pending=pending)
    ctx.finish_runs(result.cards)
    cards = [c.to_dict() for c in result.cards]
    msg = Message(conversation_id=conv.id, role="assistant", content=_summary_text(result.cards),
                  meta={"cards": cards, "pending": result.pending, "planner": result.planner,
                        "steps": [{"agent": s.agent, "text": s.text} for s in result.steps],
                        "runs": [r.id for r in ctx.runs]})
    db.add(msg)
    conv.updated_at = utcnow()
    db.commit()
    return {"conversation_id": conv.id, "message_id": msg.id, "cards": cards, "planner": result.planner,
            "steps": msg.meta["steps"], "pending": result.pending is not None,
            "simulated": any(c["simulated"] for c in cards), "llm": "sandbox" if ctx.llm.simulated else ctx.llm.model}
