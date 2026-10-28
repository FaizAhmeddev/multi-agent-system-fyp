"""IT Helpdesk database (its own SQLite file; never shared with AgentsMind core)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, MetaData, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from portal_common.core import UTCDateTime, utcnow

CATEGORIES = {"network": "Network or Wi-Fi", "hardware": "Laptop or hardware", "software": "Software",
              "account": "Account or password", "email": "Email", "printer": "Printer", "other": "Other"}
PRIORITIES = {"low": "Low", "medium": "Medium", "high": "High", "urgent": "Urgent"}
STATUSES = {"open": "Open", "in_progress": "In progress", "resolved": "Resolved", "closed": "Closed"}
DEPARTMENTS = ("Finance", "HR", "IT", "Operations", "Sales", "Marketing", "Engineering", "Administration")

# First response targets (calendar hours) shown to the requester and used for the SLA due time.
SLA_HOURS = {"urgent": 4, "high": 8, "medium": 24, "low": 72}

# Allowed status changes. Closed is final; resolved can be reopened.
TRANSITIONS = {
    "open": {"in_progress", "resolved", "closed"},
    "in_progress": {"open", "resolved"},
    "resolved": {"closed", "in_progress"},
    "closed": set(),
}


def ticket_number(ticket_id: int) -> str:
    return f"ITK-{ticket_id:06d}"


def parse_ticket_number(number: str) -> int | None:
    n = (number or "").strip().upper()
    if n.startswith("ITK-") and n[4:].isdigit() and len(n) == 10:
        return int(n[4:])
    return None


def sla_due(priority: str, created: datetime) -> datetime:
    return created + timedelta(hours=SLA_HOURS[priority])


def response_time_text(priority: str) -> str:
    h = SLA_HOURS[priority]
    return f"within {h} hours" if h < 48 else f"within {h // 24} days"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention={
        "ix": "ix_%(column_0_label)s", "uq": "uq_%(table_name)s_%(column_0_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s", "pk": "pk_%(table_name)s",
    })


class StaffUser(Base):
    __tablename__ = "staff_users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class Ticket(Base):
    __tablename__ = "tickets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    requester_name: Mapped[str] = mapped_column(String(200), nullable=False)
    requester_email: Mapped[str] = mapped_column(String(254), index=True, nullable=False)
    department: Mapped[str] = mapped_column(String(80), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    priority: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    summary: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(12), index=True, default="open", nullable=False)
    assignee: Mapped[str] = mapped_column(String(254), default="", nullable=False)
    source: Mapped[str] = mapped_column(String(20), default="portal", nullable=False)  # portal | agentsmind
    tracking_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    sla_due_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    comments: Mapped[list[Comment]] = relationship(back_populates="ticket", cascade="all, delete-orphan",
                                                   order_by="Comment.id")
    attachments: Mapped[list[Attachment]] = relationship(back_populates="ticket", cascade="all, delete-orphan")

    @property
    def number(self) -> str:
        return ticket_number(self.id)


class Comment(Base):
    __tablename__ = "comments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    author: Mapped[str] = mapped_column(String(254), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    internal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    ticket: Mapped[Ticket] = relationship(back_populates="comments")


class Attachment(Base):
    __tablename__ = "attachments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    original_name: Mapped[str] = mapped_column(String(160), nullable=False)
    stored_name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(60), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    ticket: Mapped[Ticket] = relationship(back_populates="attachments")


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    actor: Mapped[str] = mapped_column(String(254), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    target: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
