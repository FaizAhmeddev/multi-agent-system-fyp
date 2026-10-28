"""Finance Portal database (its own SQLite file; never shared with AgentsMind core)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Date,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from portal_common.core import UTCDateTime, utcnow

EMPLOYMENT_TYPES = ("full_time", "part_time", "contract", "intern")
EMPLOYMENT_LABELS = {"full_time": "Full time", "part_time": "Part time", "contract": "Contract", "intern": "Intern"}
CURRENCIES = ("PKR", "USD", "EUR", "GBP", "AED")
PERSON_STATUSES = ("active", "inactive")
PAYMENT_STATUSES = ("pending", "paid", "failed")
DEPARTMENTS = ("Finance", "HR", "IT", "Operations", "Sales", "Marketing", "Engineering", "Administration")


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


class Person(Base):
    __tablename__ = "people"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(200), index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    department: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    job_title: Mapped[str] = mapped_column(String(150), nullable=False)
    employment_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # Money is stored as integer minor units (paisa, cents) so sums are exact in SQL.
    salary_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    created_via: Mapped[str] = mapped_column(String(20), default="portal", nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False)

    payments: Mapped[list[Payment]] = relationship(back_populates="person", cascade="all, delete-orphan",
                                                   order_by="Payment.month.desc()")


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (UniqueConstraint("person_id", "month", name="uq_payments_person_month"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    month: Mapped[str] = mapped_column(String(7), nullable=False)  # YYYY-MM
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    paid_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    person: Mapped[Person] = relationship(back_populates="payments")


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    actor: Mapped[str] = mapped_column(String(254), nullable=False)  # staff email or "api:<client>"
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    target: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


def to_minor(amount) -> int:
    from decimal import ROUND_HALF_UP, Decimal

    return int((Decimal(str(amount)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def from_minor(minor: int) -> str:
    sign = "-" if minor < 0 else ""
    minor = abs(int(minor))
    return f"{sign}{minor // 100}.{minor % 100:02d}"
