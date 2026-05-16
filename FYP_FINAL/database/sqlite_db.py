"""
DATABASE/SQLITE_DB.PY
======================
SQLite + SQLAlchemy ORM — All tables for the FYP system.

Tables:
  users, tasks, agent_logs, messages, emails,
  candidates, hr_queries, finance_records,
  documents_meta, it_tickets, notifications, whatsapp_logs,
  recruitment_workflows, recruitment_audit_logs, hr_gmail_shortlist_batches,
  login_history
"""

import os
import sys
import json
import time
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from sqlalchemy import (
    create_engine, Column, Integer, String, Text,
    Float, DateTime, Boolean, ForeignKey, JSON
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.pool import StaticPool

Base = declarative_base()


# ── Models ────────────────────────────────────────────────────────────────────

class TaskLog(Base):
    __tablename__ = "tasks"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    timestamp   = Column(DateTime, default=datetime.utcnow)
    user_name   = Column(String(100))
    user_role   = Column(String(50))
    user_input  = Column(Text)
    agents_used = Column(String(200))
    response    = Column(Text)
    elapsed_ms  = Column(Integer, default=0)
    source      = Column(String(50), default="ui")  # ui | whatsapp | api


class AgentLog(Base):
    __tablename__ = "agent_logs"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    timestamp  = Column(DateTime, default=datetime.utcnow)
    agent_name = Column(String(100))
    action     = Column(String(200))
    input_data = Column(Text)
    output     = Column(Text)
    success    = Column(Boolean, default=True)
    elapsed_ms = Column(Integer, default=0)


class MessageLog(Base):
    __tablename__ = "messages"
    id        = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    msg_id    = Column(String(20))
    sender    = Column(String(100))
    receiver  = Column(String(100))
    topic     = Column(String(50))
    payload   = Column(Text)
    status    = Column(String(20), default="pending")


class EmailLog(Base):
    __tablename__ = "emails"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    timestamp   = Column(DateTime, default=datetime.utcnow)
    direction   = Column(String(10))   # sent | received
    from_addr   = Column(String(200))
    to_addr     = Column(String(200))
    subject     = Column(String(500))
    body        = Column(Text)
    status      = Column(String(20), default="sent")
    auto_reply  = Column(Boolean, default=False)


class Candidate(Base):
    __tablename__ = "candidates"
    id             = Column(Integer, primary_key=True, autoincrement=True)
    timestamp      = Column(DateTime, default=datetime.utcnow)
    name           = Column(String(200))
    job_title      = Column(String(200))
    score          = Column(Integer, default=0)
    recommendation = Column(String(100))
    strengths      = Column(Text)
    weaknesses     = Column(Text)
    summary        = Column(Text)
    cv_filename    = Column(String(200))
    status         = Column(String(50), default="screened")


class HRQuery(Base):
    __tablename__ = "hr_queries"
    id        = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    user_name = Column(String(100))
    action    = Column(String(100))
    question  = Column(Text)
    answer    = Column(Text)


class FinanceRecord(Base):
    __tablename__ = "finance_records"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    timestamp   = Column(DateTime, default=datetime.utcnow)
    user_name   = Column(String(100))
    action      = Column(String(100))
    input_data  = Column(Text)
    result      = Column(Text)
    total_amount= Column(Float, default=0.0)


class DocumentMeta(Base):
    __tablename__ = "documents_meta"
    id           = Column(Integer, primary_key=True, autoincrement=True)
    timestamp    = Column(DateTime, default=datetime.utcnow)
    file_name    = Column(String(500))
    file_id      = Column(String(200))
    source       = Column(String(50), default="drive")
    content_len  = Column(Integer, default=0)
    summary      = Column(Text)
    doc_type     = Column(String(100))
    embedded     = Column(Boolean, default=False)


class ITTicket(Base):
    __tablename__ = "it_tickets"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    timestamp   = Column(DateTime, default=datetime.utcnow)
    ticket_id   = Column(String(20))
    user_name   = Column(String(100))
    problem     = Column(Text)
    solution    = Column(Text)
    status      = Column(String(30), default="resolved")
    priority    = Column(String(20), default="normal")


class Notification(Base):
    __tablename__ = "notifications"
    id        = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    title     = Column(String(200))
    message   = Column(Text)
    level     = Column(String(20), default="info")   # info | warning | error | success
    read      = Column(Boolean, default=False)
    agent     = Column(String(100))


class WhatsAppLog(Base):
    __tablename__ = "whatsapp_logs"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    timestamp   = Column(DateTime, default=datetime.utcnow)
    direction   = Column(String(10))   # inbound | outbound
    from_number = Column(String(50))
    to_number   = Column(String(50))
    message     = Column(Text)
    agents_used = Column(String(200))
    status      = Column(String(20), default="sent")


class RecruitmentWorkflow(Base):
    """Persistent state for multi-agent recruitment runs (HITL before send)."""
    __tablename__ = "recruitment_workflows"
    id            = Column(Integer, primary_key=True, autoincrement=True)
    workflow_id   = Column(String(64), unique=True, index=True)
    timestamp     = Column(DateTime, default=datetime.utcnow)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user_name     = Column(String(100))
    status        = Column(String(40), default="pending_approval")
    # pending_approval | approved_sending | completed | failed | cancelled
    role_title    = Column(String(300))
    company       = Column(String(200))
    interview_when = Column(String(300))
    state_json    = Column(Text)       # JSON snapshot (CV bodies truncated)
    send_results_json = Column(Text)   # JSON after approved send
    error_message = Column(Text)


class RecruitmentAuditLog(Base):
    __tablename__ = "recruitment_audit_logs"
    id           = Column(Integer, primary_key=True, autoincrement=True)
    timestamp    = Column(DateTime, default=datetime.utcnow)
    workflow_id  = Column(String(64), index=True)
    step         = Column(String(80))
    agent        = Column(String(80))
    success      = Column(Boolean, default=True)
    elapsed_ms   = Column(Integer, default=0)
    detail_json  = Column(Text)   # small JSON; avoid full PII dumps


class LoginHistory(Base):
    """User sign-in and sign-out events (audit trail)."""
    __tablename__ = "login_history"
    id           = Column(Integer, primary_key=True, autoincrement=True)
    timestamp    = Column(DateTime, default=datetime.utcnow, index=True)
    username     = Column(String(100), index=True)
    display_name = Column(String(200))
    role         = Column(String(80))
    event        = Column(String(20))   # login | logout
    session_id   = Column(String(64), default="")
    ip_address   = Column(String(64), default="")
    user_agent   = Column(String(500), default="")


class HRGmailShortlistBatch(Base):
    """HR Gmail CV fetch → ranked shortlist; emails sent only after explicit approval."""
    __tablename__ = "hr_gmail_shortlist_batches"
    id              = Column(Integer, primary_key=True, autoincrement=True)
    batch_id        = Column(String(64), unique=True, index=True)
    timestamp       = Column(DateTime, default=datetime.utcnow)
    user_name       = Column(String(100))
    user_role       = Column(String(80))
    status          = Column(String(40), default="pending_send")  # pending_send | sent | cancelled
    criteria        = Column(Text)
    interview_when  = Column(String(400))
    company         = Column(String(200))
    payload_json    = Column(Text)


class AppUser(Base):
    """Application users (synced from config.USERS on init)."""
    __tablename__ = "app_users"
    id           = Column(Integer, primary_key=True, autoincrement=True)
    username     = Column(String(100), unique=True, index=True)
    password     = Column(String(256))
    role         = Column(String(80))
    display_name = Column(String(200))
    created_at   = Column(DateTime, default=datetime.utcnow)


class UserSession(Base):
    """Server-side session row keyed by auth_session_id (Streamlit session)."""
    __tablename__ = "user_sessions"
    id           = Column(Integer, primary_key=True, autoincrement=True)
    session_id   = Column(String(64), unique=True, index=True)
    username     = Column(String(100), index=True)
    display_name = Column(String(200))
    role         = Column(String(80))
    created_at   = Column(DateTime, default=datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.utcnow)
    is_active    = Column(Boolean, default=True)


class Conversation(Base):
    """Persistent chat thread per user + channel."""
    __tablename__ = "conversations"
    id           = Column(Integer, primary_key=True, autoincrement=True)
    session_id   = Column(String(64), index=True, default="")
    username     = Column(String(100), index=True)
    channel      = Column(String(50), default="orchestrator", index=True)
    created_at   = Column(DateTime, default=datetime.utcnow)
    updated_at   = Column(DateTime, default=datetime.utcnow)


class ConversationMessage(Base):
    """Agent / user messages with optional reasoning metadata."""
    __tablename__ = "conversation_messages"
    id               = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id  = Column(Integer, ForeignKey("conversations.id"), index=True)
    role             = Column(String(20))
    content          = Column(Text)
    agents_used      = Column(String(200), default="")
    metadata_json    = Column(Text, default="{}")
    created_at       = Column(DateTime, default=datetime.utcnow)


# ── Engine & Session ──────────────────────────────────────────────────────────

_engine  = None
_Session = None


def get_engine():
    global _engine
    if _engine is None:
        from config import DB_PATH, get_database_url

        url = get_database_url()
        if url.startswith("sqlite"):
            os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
            _engine = create_engine(
                url,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
        else:
            _engine = create_engine(url, pool_pre_ping=True)
        Base.metadata.create_all(_engine)
        seed_app_users_from_config()
    return _engine


def get_session() -> Session:
    global _Session
    if _Session is None:
        _Session = sessionmaker(bind=get_engine())
    return _Session()


def init_db():
    """Initialize DB — creates all tables if not exist."""
    engine = get_engine()
    Base.metadata.create_all(engine)
    return True


# ── Helper Functions ──────────────────────────────────────────────────────────

def log_task(user_name: str, user_role: str, user_input: str,
             agents_used: list, response: str, elapsed_ms: int = 0,
             source: str = "ui"):
    try:
        s = get_session()
        s.add(TaskLog(
            user_name=user_name, user_role=user_role,
            user_input=user_input,
            agents_used=", ".join(agents_used),
            response=response, elapsed_ms=elapsed_ms, source=source,
        ))
        s.commit()
        s.close()
    except Exception:
        pass


def log_agent(agent_name: str, action: str, input_data: str,
              output: str, success: bool = True, elapsed_ms: int = 0):
    try:
        s = get_session()
        s.add(AgentLog(
            agent_name=agent_name, action=action,
            input_data=str(input_data)[:2000],
            output=str(output)[:3000],
            success=success, elapsed_ms=elapsed_ms,
        ))
        s.commit()
        s.close()
    except Exception:
        pass


def log_email(direction: str, from_addr: str, to_addr: str,
              subject: str, body: str, auto_reply: bool = False):
    try:
        s = get_session()
        s.add(EmailLog(
            direction=direction, from_addr=from_addr,
            to_addr=to_addr, subject=subject,
            body=str(body)[:2000], auto_reply=auto_reply,
        ))
        s.commit()
        s.close()
    except Exception:
        pass


def log_candidate(name: str, job_title: str, score: int,
                  recommendation: str, strengths: list,
                  weaknesses: list, summary: str, cv_filename: str = ""):
    try:
        s = get_session()
        s.add(Candidate(
            name=name, job_title=job_title, score=score,
            recommendation=recommendation,
            strengths=", ".join(strengths),
            weaknesses=", ".join(weaknesses),
            summary=summary, cv_filename=cv_filename,
        ))
        s.commit()
        s.close()
    except Exception:
        pass


def log_it_ticket(user_name: str, problem: str, solution: str,
                  priority: str = "normal"):
    try:
        s    = get_session()
        count = s.query(ITTicket).count()
        tid   = f"IT-{datetime.now().strftime('%Y%m%d')}-{count+1:04d}"
        s.add(ITTicket(
            ticket_id=tid, user_name=user_name,
            problem=problem, solution=solution, priority=priority,
        ))
        s.commit()
        s.close()
        return tid
    except Exception:
        return "IT-ERROR"


def log_finance(user_name: str, action: str, input_data: str,
                result: str, total_amount: float = 0.0):
    try:
        s = get_session()
        s.add(FinanceRecord(
            user_name=user_name, action=action,
            input_data=str(input_data)[:2000],
            result=str(result)[:3000],
            total_amount=total_amount,
        ))
        s.commit()
        s.close()
    except Exception:
        pass


def log_whatsapp(direction: str, from_number: str, to_number: str,
                 message: str, agents_used: list = None, status: str = "sent"):
    try:
        s = get_session()
        s.add(WhatsAppLog(
            direction=direction, from_number=from_number,
            to_number=to_number, message=message,
            agents_used=", ".join(agents_used or []),
            status=status,
        ))
        s.commit()
        s.close()
    except Exception:
        pass


def add_notification(title: str, message: str, level: str = "info", agent: str = "System"):
    try:
        s = get_session()
        s.add(Notification(title=title, message=message, level=level, agent=agent))
        s.commit()
        s.close()
    except Exception:
        pass


def get_dashboard_stats() -> dict:
    """Get real stats from DB for dashboard."""
    try:
        s = get_session()
        stats = {
            "total_tasks":       s.query(TaskLog).count(),
            "total_emails":      s.query(EmailLog).count(),
            "total_candidates":  s.query(Candidate).count(),
            "total_it_tickets":  s.query(ITTicket).count(),
            "total_finance":     s.query(FinanceRecord).count(),
            "total_whatsapp":    s.query(WhatsAppLog).count(),
            "unread_notifs":     s.query(Notification).filter_by(read=False).count(),
            "recent_tasks":      [],
            "recent_tickets":    [],
            "agent_usage":       {},
        }
        # Recent tasks
        recent = s.query(TaskLog).order_by(TaskLog.timestamp.desc()).limit(5).all()
        for t in recent:
            stats["recent_tasks"].append({
                "time":    t.timestamp.strftime("%H:%M"),
                "user":    t.user_name,
                "agents":  t.agents_used,
                "input":   t.user_input[:60],
                "elapsed": t.elapsed_ms,
            })
        # Agent usage counts (direct agent logs)
        from sqlalchemy import func
        rows = s.query(AgentLog.agent_name, func.count(AgentLog.id))\
                .group_by(AgentLog.agent_name).all()
        for name, cnt in rows:
            stats["agent_usage"][name] = cnt

        # Orchestrator routes store slugs in TaskLog.agents_used — merge into same display names
        _slug_to_display = {
            "general": "General Assistant",
            "hr_gmail": "Gmail CV shortlist",
            "it_support": "IT Support Agent",
            "email": "Email Agent",
            "hr": "HR Agent",
            "recruitment": "Recruitment Orchestrator",
            "finance": "Finance Agent",
            "documents": "Documents Agent",
            "whatsapp": "WhatsApp Agent",
        }
        for t in s.query(TaskLog).order_by(TaskLog.timestamp.desc()).limit(500).all():
            blob = (t.agents_used or "").lower()
            for part in blob.split(","):
                slug = part.strip().replace(" ", "_")
                disp = _slug_to_display.get(slug)
                if disp:
                    stats["agent_usage"][disp] = stats["agent_usage"].get(disp, 0) + 1

        s.close()
        return stats
    except Exception as e:
        return {"error": str(e), "total_tasks": 0, "total_emails": 0,
                "total_candidates": 0, "total_it_tickets": 0,
                "total_finance": 0, "total_whatsapp": 0,
                "unread_notifs": 0, "recent_tasks": [],
                "recent_tickets": [], "agent_usage": {}}


def log_login_event(
    username: str,
    display_name: str,
    role: str,
    event: str,
    session_id: str = "",
    ip_address: str = "",
    user_agent: str = "",
) -> bool:
    """Record login or logout in login_history table."""
    try:
        s = get_session()
        s.add(LoginHistory(
            username=(username or "")[:100],
            display_name=(display_name or "")[:200],
            role=(role or "")[:80],
            event=(event or "login")[:20],
            session_id=(session_id or "")[:64],
            ip_address=(ip_address or "")[:64],
            user_agent=(user_agent or "")[:500],
        ))
        s.commit()
        s.close()
        return True
    except Exception:
        return False


def get_login_history(limit: int = 100, username: str | None = None) -> list:
    """Return recent login/logout rows, optionally filtered by username."""
    try:
        s = get_session()
        q = s.query(LoginHistory).order_by(LoginHistory.timestamp.desc())
        if username:
            q = q.filter(LoginHistory.username == username)
        rows = q.limit(limit).all()
        result = []
        for r in rows:
            result.append({
                "id": r.id,
                "time": r.timestamp.strftime("%Y-%m-%d %H:%M:%S") if r.timestamp else "",
                "username": r.username or "",
                "display_name": r.display_name or "",
                "role": r.role or "",
                "event": r.event or "",
                "session_id": r.session_id or "",
                "ip_address": r.ip_address or "",
            })
        s.close()
        return result
    except Exception:
        return []


def get_task_history(limit: int = 50) -> list:
    try:
        s = get_session()
        rows = s.query(TaskLog).order_by(TaskLog.timestamp.desc()).limit(limit).all()
        result = []
        for r in rows:
            result.append({
                "id":        r.id,
                "time":      r.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "user":      r.user_name,
                "role":      r.user_role,
                "input":     r.user_input,
                "agents":    r.agents_used,
                "response":  r.response,
                "elapsed":   r.elapsed_ms,
                "source":    r.source,
            })
        s.close()
        return result
    except Exception:
        return []


def get_notifications(unread_only: bool = False) -> list:
    try:
        s = get_session()
        q = s.query(Notification).order_by(Notification.timestamp.desc())
        if unread_only:
            q = q.filter_by(read=False)
        rows = q.limit(20).all()
        result = [{"id": r.id, "time": r.timestamp.strftime("%H:%M"),
                   "title": r.title, "message": r.message,
                   "level": r.level, "agent": r.agent} for r in rows]
        s.close()
        return result
    except Exception:
        return []


def mark_notifications_read():
    try:
        s = get_session()
        s.query(Notification).filter_by(read=False).update({"read": True})
        s.commit()
        s.close()
    except Exception:
        pass


def get_candidates_as_cvs(limit: int = 80) -> list:
    """
    Build pseudo-CV dicts from stored Candidate rows (for re-screening / JD matching).
    Full CV text is not stored; uses summary and metadata.
    """
    try:
        s = get_session()
        rows = (
            s.query(Candidate)
            .order_by(Candidate.timestamp.desc())
            .limit(limit)
            .all()
        )
        out = []
        for r in rows:
            body = (
                f"Candidate: {r.name}\n"
                f"Previously screened for: {r.job_title or 'N/A'}\n"
                f"Historical score: {r.score}\n"
                f"Recommendation: {r.recommendation}\n"
                f"Strengths: {r.strengths or ''}\n"
                f"Weaknesses: {r.weaknesses or ''}\n"
                f"Summary: {r.summary or ''}\n"
                f"CV file ref: {r.cv_filename or 'N/A'}"
            )
            out.append({"name": r.name, "content": body, "source": "database"})
        s.close()
        return out
    except Exception:
        return []


def recruitment_save_workflow(
    workflow_id: str,
    user_name: str,
    status: str,
    role_title: str,
    company: str,
    interview_when: str,
    state: dict,
    send_results: dict | None = None,
    error_message: str | None = None,
) -> bool:
    """Insert or update a recruitment workflow snapshot."""
    try:
        s = get_session()
        row = s.query(RecruitmentWorkflow).filter_by(workflow_id=workflow_id).one_or_none()
        payload = json.dumps(state, ensure_ascii=False)[:490_000]
        send_json = json.dumps(send_results, ensure_ascii=False)[:100_000] if send_results else None
        if row is None:
            s.add(RecruitmentWorkflow(
                workflow_id=workflow_id,
                user_name=user_name or "",
                status=status,
                role_title=role_title or "",
                company=company or "",
                interview_when=interview_when or "",
                state_json=payload,
                send_results_json=send_json,
                error_message=(error_message or "")[:4000],
            ))
        else:
            row.status = status
            row.role_title = role_title or row.role_title
            row.company = company or row.company
            row.interview_when = interview_when or row.interview_when
            row.state_json = payload
            if send_json is not None:
                row.send_results_json = send_json
            if error_message is not None:
                row.error_message = (error_message or "")[:4000]
        s.commit()
        s.close()
        return True
    except Exception:
        return False


def recruitment_get_workflow(workflow_id: str) -> dict | None:
    try:
        s = get_session()
        row = s.query(RecruitmentWorkflow).filter_by(workflow_id=workflow_id).one_or_none()
        if not row:
            s.close()
            return None
        out = {
            "workflow_id": row.workflow_id,
            "user_name": row.user_name,
            "status": row.status,
            "role_title": row.role_title,
            "company": row.company,
            "interview_when": row.interview_when,
            "state": json.loads(row.state_json or "{}"),
            "send_results": json.loads(row.send_results_json or "null") if row.send_results_json else None,
            "error_message": row.error_message or "",
            "timestamp": row.timestamp.isoformat() if row.timestamp else "",
        }
        s.close()
        return out
    except Exception:
        return None


def recruitment_log_audit(
    workflow_id: str,
    step: str,
    agent: str,
    success: bool = True,
    elapsed_ms: int = 0,
    detail: dict | None = None,
):
    try:
        s = get_session()
        s.add(RecruitmentAuditLog(
            workflow_id=workflow_id,
            step=step,
            agent=agent,
            success=success,
            elapsed_ms=elapsed_ms,
            detail_json=json.dumps(detail or {}, ensure_ascii=False)[:8000],
        ))
        s.commit()
        s.close()
    except Exception:
        pass


def hr_shortlist_save_batch(
    batch_id: str,
    user_name: str,
    user_role: str,
    criteria: str,
    interview_when: str,
    company: str,
    payload: dict,
) -> bool:
    try:
        s = get_session()
        s.add(HRGmailShortlistBatch(
            batch_id=batch_id,
            user_name=user_name or "",
            user_role=user_role or "",
            status="pending_send",
            criteria=(criteria or "")[:8000],
            interview_when=(interview_when or "")[:400],
            company=(company or "")[:200],
            payload_json=json.dumps(payload, ensure_ascii=False)[:400_000],
        ))
        s.commit()
        s.close()
        return True
    except Exception:
        return False


def hr_shortlist_get_batch(batch_id: str) -> dict | None:
    try:
        s = get_session()
        row = s.query(HRGmailShortlistBatch).filter_by(batch_id=batch_id).one_or_none()
        if not row:
            s.close()
            return None
        out = {
            "batch_id": row.batch_id,
            "user_name": row.user_name,
            "user_role": row.user_role,
            "status": row.status,
            "criteria": row.criteria or "",
            "interview_when": row.interview_when or "",
            "company": row.company or "",
            "payload": json.loads(row.payload_json or "{}"),
            "timestamp": row.timestamp.isoformat() if row.timestamp else "",
        }
        s.close()
        return out
    except Exception:
        return None


def hr_shortlist_update_status(batch_id: str, status: str) -> bool:
    try:
        s = get_session()
        row = s.query(HRGmailShortlistBatch).filter_by(batch_id=batch_id).one_or_none()
        if row:
            row.status = status[:40]
            s.commit()
        s.close()
        return True
    except Exception:
        return False


# ── Users, sessions, conversation memory ─────────────────────────────────────


def seed_app_users_from_config() -> None:
    """Insert config.USERS into app_users when table is empty."""
    try:
        from config import USERS

        s = get_session()
        if s.query(AppUser).count() > 0:
            s.close()
            return
        for uname, data in USERS.items():
            s.add(
                AppUser(
                    username=uname,
                    password=data.get("password", ""),
                    role=data.get("role", ""),
                    display_name=data.get("name", uname),
                )
            )
        s.commit()
        s.close()
    except Exception:
        pass


def authenticate_user(username: str, password: str) -> dict | None:
    """Return {username, role, name} if credentials match DB or config.USERS."""
    username = (username or "").strip()
    if not username:
        return None
    try:
        s = get_session()
        row = s.query(AppUser).filter_by(username=username).one_or_none()
        s.close()
        if row and row.password == password:
            return {
                "username": row.username,
                "role": row.role,
                "name": row.display_name or row.username,
            }
    except Exception:
        pass
    try:
        from config import USERS

        if username in USERS and USERS[username]["password"] == password:
            return {
                "username": username,
                "role": USERS[username]["role"],
                "name": USERS[username]["name"],
            }
    except Exception:
        pass
    return None


def touch_user_session(
    session_id: str,
    username: str,
    display_name: str,
    role: str,
) -> None:
    try:
        s = get_session()
        row = s.query(UserSession).filter_by(session_id=session_id).one_or_none()
        if row:
            row.username = username
            row.display_name = display_name
            row.role = role
            row.last_seen_at = datetime.utcnow()
            row.is_active = True
        else:
            s.add(
                UserSession(
                    session_id=session_id[:64],
                    username=username[:100],
                    display_name=(display_name or "")[:200],
                    role=(role or "")[:80],
                )
            )
        s.commit()
        s.close()
    except Exception:
        pass


def deactivate_user_session(session_id: str) -> None:
    try:
        s = get_session()
        row = s.query(UserSession).filter_by(session_id=session_id).one_or_none()
        if row:
            row.is_active = False
            s.commit()
        s.close()
    except Exception:
        pass


def get_or_create_conversation(
    session_id: str,
    username: str,
    channel: str = "orchestrator",
) -> int | None:
    """Reuse latest conversation for user+channel; creates one if missing."""
    try:
        s = get_session()
        conv = (
            s.query(Conversation)
            .filter_by(username=username, channel=channel)
            .order_by(Conversation.updated_at.desc())
            .first()
        )
        if conv:
            conv.session_id = (session_id or "")[:64]
            conv.updated_at = datetime.utcnow()
            cid = conv.id
            s.commit()
            s.close()
            return cid
        conv = Conversation(
            session_id=(session_id or "")[:64],
            username=username[:100],
            channel=channel[:50],
        )
        s.add(conv)
        s.commit()
        cid = conv.id
        s.close()
        return cid
    except Exception:
        return None


def append_conversation_message(
    conversation_id: int,
    role: str,
    content: str,
    agents_used: str = "",
    metadata: dict | None = None,
) -> None:
    if not conversation_id:
        return
    try:
        s = get_session()
        s.add(
            ConversationMessage(
                conversation_id=conversation_id,
                role=(role or "user")[:20],
                content=content or "",
                agents_used=(agents_used or "")[:200],
                metadata_json=json.dumps(metadata or {}, ensure_ascii=False)[:50_000],
            )
        )
        conv = s.query(Conversation).filter_by(id=conversation_id).one_or_none()
        if conv:
            conv.updated_at = datetime.utcnow()
        s.commit()
        s.close()
    except Exception:
        pass


def load_conversation_ui_messages(conversation_id: int, limit: int = 100) -> list:
    """Hydrate Streamlit chat lists: [{role, content, agents?}]."""
    if not conversation_id:
        return []
    try:
        s = get_session()
        rows = (
            s.query(ConversationMessage)
            .filter_by(conversation_id=conversation_id)
            .order_by(ConversationMessage.created_at.asc())
            .limit(limit)
            .all()
        )
        out = []
        for r in rows:
            ui_role = "agent" if r.role in ("agent", "assistant") else "user"
            entry = {"role": ui_role, "content": r.content or ""}
            if r.agents_used:
                entry["agents"] = [a.strip() for a in r.agents_used.split(",") if a.strip()]
            out.append(entry)
        s.close()
        return out
    except Exception:
        return []


def load_conversation_openai_history(
    conversation_id: int, limit: int = 20
) -> list[dict[str, str]]:
    """OpenAI-style roles for orchestrator: user | assistant."""
    if not conversation_id:
        return []
    try:
        s = get_session()
        rows = (
            s.query(ConversationMessage)
            .filter_by(conversation_id=conversation_id)
            .order_by(ConversationMessage.created_at.desc())
            .limit(limit)
            .all()
        )
        rows = list(reversed(rows))
        out = []
        for r in rows:
            if r.role in ("agent", "assistant"):
                out.append({"role": "assistant", "content": r.content or ""})
            else:
                out.append({"role": "user", "content": r.content or ""})
        s.close()
        return out
    except Exception:
        return []
