"""HR tables: the AgentsMind HR system of record.

Employees (new joiners to separated staff), their checklists (onboarding, induction,
compliance, separation), generated letters, attendance, leave, separations with final
settlement, payroll runs, job openings, HR settings, and the registry of the HR's own
sheets (Google Sheets and Excel) that the assistant knows about.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Date, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UTCDateTime, utcnow

EMPLOYEE_STATUSES = ("offered", "onboarding", "active", "notice", "separated", "withdrawn")
TASK_PROCESSES = ("onboarding", "induction", "compliance", "separation", "other")
TASK_STATUSES = ("pending", "in_progress", "done", "skipped", "failed")
LEAVE_STATUSES = ("pending", "approved", "rejected", "cancelled")
ATTENDANCE_STATUSES = ("present", "absent", "late", "half_day", "leave", "holiday", "wfh")


class HRSettings(Base):
    __tablename__ = "hr_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False)


class HRJob(TimestampMixin, Base):
    __tablename__ = "hr_jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), index=True, nullable=False)
    department: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    location: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    employment_type: Mapped[str] = mapped_column(String(40), default="permanent", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)  # open | closed
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class Employee(TimestampMixin, Base):
    __tablename__ = "hr_employees"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)  # EMP-0001
    full_name: Mapped[str] = mapped_column(String(200), index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(254), default="", index=True, nullable=False)
    phone: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    job_title: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    department: Mapped[str] = mapped_column(String(100), default="", index=True, nullable=False)
    manager: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    location: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    employment_type: Mapped[str] = mapped_column(String(40), default="permanent", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="offered", index=True, nullable=False)
    offer_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    joining_date: Mapped[date | None] = mapped_column(Date, index=True, nullable=True)
    probation_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_working_day: Mapped[date | None] = mapped_column(Date, nullable=True)
    monthly_salary: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="PKR", nullable=False)
    allowances: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)  # name -> monthly amount
    bank_account_on_file: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    finance_person_id: Mapped[str] = mapped_column(String(40), default="", nullable=False)  # Finance Portal id
    candidate_id: Mapped[int | None] = mapped_column(ForeignKey("candidates.id", ondelete="SET NULL"))
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class HRTask(TimestampMixin, Base):
    """One checklist item: onboarding, induction, compliance or separation."""

    __tablename__ = "hr_tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("hr_employees.id", ondelete="CASCADE"), index=True)
    process: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    key: Mapped[str] = mapped_column(String(60), default="", nullable=False)  # template key, e.g. it_setup
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    owner: Mapped[str] = mapped_column(String(40), default="hr", nullable=False)  # hr | it | finance | manager | employee
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True, nullable=False)
    automated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tool: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    sort: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class HRLetter(Base):
    __tablename__ = "hr_letters"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("hr_employees.id", ondelete="SET NULL"), index=True)
    candidate_id: Mapped[int | None] = mapped_column(ForeignKey("candidates.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    recipient_name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    recipient_email: Mapped[str] = mapped_column(String(254), default="", nullable=False)
    docx_path: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    pdf_path: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)  # draft | issued | sent
    fields: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    drive_file_id: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class Attendance(Base):
    __tablename__ = "hr_attendance"
    __table_args__ = (UniqueConstraint("employee_id", "day"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("hr_employees.id", ondelete="CASCADE"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    check_in: Mapped[str] = mapped_column(String(5), default="", nullable=False)  # HH:MM local
    check_out: Mapped[str] = mapped_column(String(5), default="", nullable=False)
    source: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)  # manual | sheet | excel
    note: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False)


class LeaveRequest(TimestampMixin, Base):
    __tablename__ = "hr_leave_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("hr_employees.id", ondelete="CASCADE"), index=True)
    leave_type: Mapped[str] = mapped_column(String(20), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    days: Mapped[float] = mapped_column(Float, nullable=False)  # working days, computed in code
    reason: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True, nullable=False)
    decided_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class Separation(TimestampMixin, Base):
    __tablename__ = "hr_separations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("hr_employees.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="resignation", nullable=False)
    notice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_working_day: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    reason: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="initiated", nullable=False)
    # initiated | clearance | settled | closed
    settlement: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class PayrollRun(TimestampMixin, Base):
    __tablename__ = "hr_payroll_runs"
    __table_args__ = (UniqueConstraint("month"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    month: Mapped[str] = mapped_column(String(7), nullable=False)  # YYYY-MM
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)  # draft | approved | posted
    totals: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    lines: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class HRSheet(TimestampMixin, Base):
    """One of the HR's own spreadsheets, so the assistant knows where each kind of record is kept."""

    __tablename__ = "hr_sheets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    purpose: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    source: Mapped[str] = mapped_column(String(10), nullable=False)  # google | excel
    location: Mapped[str] = mapped_column(String(500), nullable=False)
    tab: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    headers: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)  # cached from the last read
    auto_record: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_read_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
