"""Core AgentsMind tables.

External systems (Finance Portal, IT Helpdesk) have their own databases and are
never modelled here: the core reaches them only through MCP.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UTCDateTime, utcnow

ROLE_NAMES = ("admin", "hr", "it", "finance", "employee")

user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(200), default="", nullable=False)


class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    password_changed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Karachi", nullable=False)

    roles: Mapped[list[Role]] = relationship(secondary=user_roles, lazy="selectin")

    @property
    def role_names(self) -> list[str]:
        return sorted(r.name for r in self.roles)


class RefreshToken(Base):
    """Opaque refresh tokens, stored as SHA-256 hashes. Rotated on every use."""

    __tablename__ = "refresh_tokens"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    family_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    replaced_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_agent: Mapped[str] = mapped_column(String(300), default="", nullable=False)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class OutboundEmail(Base):
    """Emails produced by the app. In sandbox mode they are stored, not sent."""

    __tablename__ = "outbound_emails"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    to_address: Mapped[str] = mapped_column(String(254), nullable=False)
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    simulated: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="stored", nullable=False)
    purpose: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True, nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_email: Mapped[str] = mapped_column(String(254), default="", nullable=False)
    action: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), default="success", nullable=False)
    ip: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    request_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="New conversation", nullable=False)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user | assistant | system | tool
    content: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    agent: Mapped[str] = mapped_column(String(40), nullable=False)
    action: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    # queued | running | done | failed
    input_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class Approval(TimestampMixin, Base):
    """A pending outward action (write or destructive tool call) awaiting a human."""

    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_run_id: Mapped[int | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"))
    requested_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    decided_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    agent: Mapped[str] = mapped_column(String(40), nullable=False)
    tool: Mapped[str] = mapped_column(String(80), nullable=False)
    risk: Mapped[str] = mapped_column(String(16), default="write", nullable=False)  # write | destructive
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class ToolCall(Base):
    __tablename__ = "tool_calls"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True, nullable=False)
    agent: Mapped[str] = mapped_column(String(40), nullable=False)
    tool: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    server: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    approval_id: Mapped[int | None] = mapped_column(ForeignKey("approvals.id", ondelete="SET NULL"))
    inputs_redacted: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # ok | error | denied | timeout
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Document(TimestampMixin, Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # upload | drive
    external_id: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), default="", index=True, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    text_excerpt: Mapped[str] = mapped_column(Text, default="", nullable=False)


class Candidate(TimestampMixin, Base):
    __tablename__ = "candidates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(254), default="", nullable=False)
    job_title: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    stage: Mapped[str] = mapped_column(String(20), default="new", index=True, nullable=False)
    # new | screened | shortlisted | interview | rejected
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)


class CVRecord(Base):
    __tablename__ = "cv_records"
    __table_args__ = (UniqueConstraint("candidate_id", "document_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    job_description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    rubric_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    keyword_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    matched_skills: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    missing_skills: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    needs_human_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class QueueTask(Base):
    """Persistent work queue (QUEUE_BACKEND=db).

    Lifecycle: pending -> leased -> done | (pending again with backoff) -> dead.
    A lease has an owner token; only the current owner can ack or nack, so a
    worker that was presumed dead cannot overwrite the result of its successor.
    """

    __tablename__ = "queue_tasks"
    __table_args__ = (UniqueConstraint("idempotency_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    queue: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(12), index=True, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    available_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True, nullable=False)
    leased_until: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"),
                                                           nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow,
                                                 nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
