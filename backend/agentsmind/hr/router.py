"""HR API for the web app: employees, checklists, letters, attendance, leave, separations, payroll,
reports, sheets, jobs and HR settings. Plus Connections (which services are connected, Google sign-in).

Role checks are in code on every endpoint. Self-service endpoints (check in/out, own leave, own
balance) are open to every signed-in staff member and only ever touch the caller's own record.
Actions submitted from a form by HR are that person's own explicit action: external effects
(email, payroll, IT tickets) still go through the tool gateway as direct approvals.
"""
from __future__ import annotations

import re
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..agents.gateway import call_tool
from ..audit import audit
from ..auth.deps import client_ip, get_current_user, require_roles
from ..db.hr_models import Employee, HRJob, HRLetter, HRSheet, HRTask, LeaveRequest, Separation
from ..db.models import User
from ..db.session import get_db
from ..settings import REPO_ROOT, get_settings
from . import calc, letters, reports, workflows
from . import service as S
from .policy import LEAVE_TYPES, SHEET_PURPOSES, company_ready

router = APIRouter(prefix="/api", tags=["hr"])
HR_ONLY = require_roles("hr")
SHEETS_DIR = REPO_ROOT / "data" / "hr_sheets"


def _err(exc: S.HRError, status: int = 400) -> HTTPException:
    return HTTPException(status, detail={"code": "hr_error", "message": str(exc)})


def _emp(db: Session, employee_id: int) -> Employee:
    e = db.get(Employee, employee_id)
    if e is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "Employee not found."})
    return e


def _today() -> date:
    return datetime.now(ZoneInfo(get_settings().timezone)).date()


# ---------------------------------------------------------------------------- overview

@router.get("/hr/overview")
def overview(_: User = Depends(HR_ONLY), db: Session = Depends(get_db)) -> dict:
    t = _today()
    a, b = calc.month_bounds(t.year, t.month)
    es = S.list_employees(db)
    by_status: dict[str, int] = {}
    for e in es:
        by_status[e.status] = by_status.get(e.status, 0) + 1
    joiners = [S.employee_dict(e) for e in es if e.joining_date and a <= e.joining_date <= b]
    upcoming = sorted([S.employee_dict(e) for e in es if e.joining_date and e.joining_date > t
                       and e.status in ("offered", "onboarding")], key=lambda x: x["joining_date"])[:10]
    overdue = 0
    for e in es:
        if e.status in ("onboarding", "notice", "active"):
            for p in ("onboarding", "separation"):
                overdue += len(S.progress(db, e.id, p)["overdue"])
    return {"by_status": by_status, "joiners_this_month": joiners, "upcoming_joiners": upcoming,
            "pending_leave": len(S.leave_requests(db, status="pending")),
            "open_separations": sum(1 for s in S.separations(db) if s["status"] != "closed"),
            "overdue_items": overdue, "sheets": len(S.sheets_for(db)), "jobs_open": len(list(db.scalars(
                select(HRJob).where(HRJob.status == "open")))),
            "company_missing": company_ready(S.get_policy(db))}


# ---------------------------------------------------------------------------- employees

class EmployeeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str = Field(min_length=2, max_length=200)
    email: EmailStr | None = None
    phone: str = Field(default="", max_length=40)
    job_title: str = Field(default="", max_length=200)
    department: str = Field(default="", max_length=100)
    manager: str = Field(default="", max_length=200)
    location: str = Field(default="", max_length=100)
    employment_type: str = Field(default="permanent", max_length=40)
    status: str = Field(default="active", pattern="^(offered|onboarding|active|notice|separated|withdrawn)$")
    joining_date: date | None = None
    offer_date: date | None = None
    probation_end: date | None = None
    last_working_day: date | None = None
    monthly_salary: float = Field(default=0, ge=0, le=100_000_000)
    currency: str = Field(default="PKR", pattern="^[A-Z]{3}$")
    allowances: dict[str, float] = Field(default_factory=dict)
    bank_account_on_file: bool = False
    notes: str = Field(default="", max_length=4000)


class EmployeePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str | None = Field(default=None, min_length=2, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    job_title: str | None = Field(default=None, max_length=200)
    department: str | None = Field(default=None, max_length=100)
    manager: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=100)
    employment_type: str | None = Field(default=None, max_length=40)
    status: str | None = Field(default=None, pattern="^(offered|onboarding|active|notice|separated|withdrawn)$")
    joining_date: date | None = None
    probation_end: date | None = None
    last_working_day: date | None = None
    monthly_salary: float | None = Field(default=None, ge=0, le=100_000_000)
    allowances: dict[str, float] | None = None
    bank_account_on_file: bool | None = None
    notes: str | None = Field(default=None, max_length=4000)


@router.get("/hr/employees")
def employees(status: str = Query("", max_length=100), department: str = Query("", max_length=100),
              q: str = Query("", max_length=100), _: User = Depends(HR_ONLY), db: Session = Depends(get_db)) -> dict:
    items = []
    for e in S.list_employees(db, status=status, department=department, q=q):
        d = S.employee_dict(e)
        d["onboarding"] = S.progress(db, e.id, "onboarding")
        items.append(d)
    return {"items": items}


@router.post("/hr/employees", status_code=201)
def create_employee(body: EmployeeIn, user: User = Depends(HR_ONLY), db: Session = Depends(get_db)) -> dict:
    try:
        e = S.create_employee(db, body.model_dump(), user)
    except S.HRError as exc:
        raise _err(exc) from exc
    return S.employee_dict(e)


@router.get("/hr/employees/{employee_id}")
def employee(employee_id: int, _: User = Depends(HR_ONLY), db: Session = Depends(get_db)) -> dict:
    e = _emp(db, employee_id)
    t = _today()
    a, b = calc.month_bounds(t.year, t.month)
    seps = [s for s in S.separations(db) if s["employee_id"] == e.id]
    return {"employee": S.employee_dict(e), "tasks": [S.task_dict(x) for x in S.tasks_for(db, e.id)],
            "progress": {p: S.progress(db, e.id, p) for p in ("onboarding", "induction", "compliance", "separation")},
            "letters": [S.letter_dict(x) for x in db.scalars(select(HRLetter).where(HRLetter.employee_id == e.id)
                                                              .order_by(HRLetter.id.desc()))],
            "leave": S.leave_requests(db, employee_id=e.id), "balances": S.leave_balances(db, e, t.year),
            "attendance": S.attendance_rows(db, a, b, e.id), "separation": seps[0] if seps else None}


@router.patch("/hr/employees/{employee_id}")
def update_employee(employee_id: int, body: EmployeePatch, user: User = Depends(HR_ONLY),
                    db: Session = Depends(get_db)) -> dict:
    e = _emp(db, employee_id)
    try:
        S.update_employee(db, e, body.model_dump(exclude_unset=True), user)
    except S.HRError as exc:
        raise _err(exc) from exc
    return S.employee_dict(e)


class ChecklistIn(BaseModel):
    process: str = Field(pattern="^(onboarding|induction|compliance|separation)$")


@router.post("/hr/employees/{employee_id}/checklists")
def make_checklist(employee_id: int, body: ChecklistIn, _: User = Depends(HR_ONLY), db: Session = Depends(get_db)
                   ) -> dict:
    e = _emp(db, employee_id)
    base = e.last_working_day if body.process == "separation" else e.joining_date
    return {"items": [S.task_dict(t) for t in S.create_checklist(db, e, body.process, base)]}


class TaskPatch(BaseModel):
    status: str = Field(pattern="^(pending|in_progress|done|skipped|failed)$")
    notes: str | None = Field(default=None, max_length=2000)


@router.patch("/hr/tasks/{task_id}")
def update_task(task_id: int, body: TaskPatch, user: User = Depends(HR_ONLY), db: Session = Depends(get_db)) -> dict:
    t = db.get(HRTask, task_id)
    if t is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "Checklist item not found."})
    S.set_task(db, t, body.status, notes=body.notes)
    audit(db, "hr.task", actor_user_id=user.id, actor_email=user.email, target_type="task", target_id=t.id,
          detail={"status": body.status})
    return S.task_dict(t)


@router.post("/hr/tasks/{task_id}/retry")
def retry_task(task_id: int, request: Request, user: User = Depends(HR_ONLY), db: Session = Depends(get_db),
               idempotency_key: str | None = Header(default=None, max_length=100)) -> dict:
    """Run the failed automated step of a checklist item again (the HR user's own explicit action)."""
    t = db.get(HRTask, task_id)
    if t is None or not (t.result or {}).get("step"):
        raise HTTPException(409, detail={"code": "not_retryable", "message": "This item has no automated step to retry."})
    step = dict(t.result["step"])
    args = {"workflow": "retry", "title": f"Retry: {t.title}", "steps": [step], "employee_id": t.employee_id,
            "_actor": user.id}
    out = call_tool(db, agent="hr", tool="hr_run_workflow", args=args, user=user, direct=True,
                    request_key=idempotency_key, summary=f"Retry: {t.title}", ip=client_ip(request))
    if out.status != "ok":
        raise HTTPException(400, detail={"code": out.code or "tool_error", "message": out.error})
    db.refresh(t)
    return {"task": S.task_dict(t), "result": out.result}


# ---------------------------------------------------------------------------- letters

class LetterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(pattern="^(offer|contract|welcome|conduct|resignation_acceptance|final_settlement|experience)$")
    employee_id: int
    fields: dict[str, Any] = Field(default_factory=dict)


@router.get("/hr/letters")
def list_letters(_: User = Depends(HR_ONLY), db: Session = Depends(get_db)) -> dict:
    rows = db.scalars(select(HRLetter).order_by(HRLetter.id.desc()).limit(300))
    return {"items": [S.letter_dict(x) for x in rows], "kinds": letters.KINDS}


@router.post("/hr/letters", status_code=201)
def create_letter(body: LetterIn, user: User = Depends(HR_ONLY), db: Session = Depends(get_db)) -> dict:
    e = _emp(db, body.employee_id)
    fields = {k: v for k, v in body.fields.items() if isinstance(v, str | int | float | bool | dict | list)}
    if body.kind == "final_settlement" and "settlement" not in fields:
        sep = db.scalar(select(Separation).where(Separation.employee_id == e.id))
        if sep is None or not sep.settlement:
            raise HTTPException(409, detail={"code": "no_settlement",
                                             "message": "Compute the final settlement first (Separations tab)."})
        fields["settlement"] = sep.settlement
    try:
        lt = S.create_letter(db, body.kind, fields, employee=e, user=user)
    except (S.HRError, ValueError) as exc:
        raise HTTPException(400, detail={"code": "hr_error", "message": str(exc)}) from exc
    return S.letter_dict(lt)


def _letter_file(db: Session, letter_id: int, which: str) -> Path:
    lt = db.get(HRLetter, letter_id)
    if lt is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "Letter not found."})
    p = Path(lt.pdf_path if which == "pdf" else lt.docx_path).resolve()
    if not p.is_file() or not p.is_relative_to(letters.DOCS_DIR.resolve()):
        raise HTTPException(404, detail={"code": "not_found", "message": "The letter file is missing."})
    return p


@router.get("/hr/letters/{letter_id}/pdf")
def letter_pdf(letter_id: int, _: User = Depends(HR_ONLY), db: Session = Depends(get_db)) -> FileResponse:
    p = _letter_file(db, letter_id, "pdf")
    return FileResponse(p, media_type="application/pdf", filename=p.name)


@router.get("/hr/letters/{letter_id}/docx")
def letter_docx(letter_id: int, _: User = Depends(HR_ONLY), db: Session = Depends(get_db)) -> FileResponse:
    p = _letter_file(db, letter_id, "docx")
    return FileResponse(p, filename=p.name,
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


class SendIn(BaseModel):
    to: EmailStr | None = None
    subject: str = Field(default="", max_length=300)
    body: str = Field(default="", max_length=10000)


@router.post("/hr/letters/{letter_id}/send")
def send_letter(letter_id: int, body: SendIn, request: Request, user: User = Depends(HR_ONLY),
                db: Session = Depends(get_db), idempotency_key: str | None = Header(default=None, max_length=100)
                ) -> dict:
    lt = db.get(HRLetter, letter_id)
    if lt is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "Letter not found."})
    to = str(body.to or lt.recipient_email or "")
    if not to:
        raise HTTPException(422, detail={"code": "no_recipient", "message": "No email address for this letter."})
    pdf = _letter_file(db, letter_id, "pdf")
    pol = S.get_policy(db)
    out = call_tool(db, agent="hr", tool="gmail_send_email", user=user, direct=True, request_key=idempotency_key,
                    ip=client_ip(request), summary=f"Send {lt.title}",
                    args={"to": [to], "subject": body.subject or lt.title,
                          "body": body.body or f"Dear {lt.recipient_name.split()[0] if lt.recipient_name else ''},\n\n"
                                               f"Please find attached your {letters.KINDS.get(lt.kind, 'letter').lower()}."
                                               f"\n\nBest regards,\n{pol['company']['signatory_name'] or 'HR'}",
                          "attachments": [str(pdf)]})
    if out.status != "ok":
        raise HTTPException(400 if out.status == "error" else 403, detail={"code": out.code, "message": out.error})
    from ..db.base import utcnow

    lt.status, lt.sent_at = "sent", utcnow()
    db.commit()
    return {"letter": S.letter_dict(lt), "result": out.result}


@router.get("/hr/previews/{name}")
def preview(name: str, _: User = Depends(HR_ONLY)) -> FileResponse:
    if not re.fullmatch(r"[0-9a-f]{16}\.pdf", name):
        raise HTTPException(404, detail={"code": "not_found", "message": "Preview not found."})
    p = letters.DOCS_DIR / "_previews" / name
    if not p.is_file():
        raise HTTPException(404, detail={"code": "not_found", "message": "Preview expired; ask again."})
    return FileResponse(p, media_type="application/pdf", filename=f"preview-{name}")


# ---------------------------------------------------------------------------- reports

@router.get("/hr/reports")
def report(kind: str = Query(..., pattern="^(" + "|".join(reports.KINDS) + ")$"),
           period: str = Query("this month", max_length=60), employee_id: int | None = None,
           _: User = Depends(HR_ONLY), db: Session = Depends(get_db)) -> dict:
    t = _today()
    p = calc.parse_period(period, t) or calc.Period(*calc.month_bounds(t.year, t.month), t.strftime("%B %Y"))
    rep = reports.build(db, kind, p, employee_id=employee_id)
    rep["file"] = reports.export_xlsx(rep).name
    return rep


@router.get("/hr/reports/file/{name}")
def report_file(name: str, _: User = Depends(HR_ONLY)) -> FileResponse:
    if not re.fullmatch(r"[a-z0-9\-]+\.xlsx", name):
        raise HTTPException(404, detail={"code": "not_found", "message": "Report not found."})
    p = (reports.REPORTS_DIR / name).resolve()
    if not p.is_file():
        raise HTTPException(404, detail={"code": "not_found", "message": "Report not found."})
    return FileResponse(p, filename=name,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.get("/hr/compliance/matrix")
def compliance_matrix(_: User = Depends(HR_ONLY), db: Session = Depends(get_db)) -> dict:
    return {"file": reports.compliance_formats(db).name}


# ---------------------------------------------------------------------------- attendance

class AttendanceIn(BaseModel):
    employee_id: int
    day: date
    status: str = Field(pattern="^(present|absent|late|half_day|leave|holiday|wfh)$")
    check_in: str = Field(default="", pattern=r"^(\d{2}:\d{2})?$")
    check_out: str = Field(default="", pattern=r"^(\d{2}:\d{2})?$")
    note: str = Field(default="", max_length=300)


@router.get("/hr/attendance")
def attendance(start: date | None = None, end: date | None = None, employee_id: int | None = None,
               _: User = Depends(HR_ONLY), db: Session = Depends(get_db)) -> dict:
    t = _today()
    a, b = calc.month_bounds(t.year, t.month)
    start, end = start or a, end or b
    return {"start": start.isoformat(), "end": end.isoformat(),
            "rows": S.attendance_rows(db, start, end, employee_id),
            "summary": S.attendance_summary(db, start, end, employee_id)}


@router.post("/hr/attendance")
def mark(body: AttendanceIn, user: User = Depends(HR_ONLY), db: Session = Depends(get_db)) -> dict:
    e = _emp(db, body.employee_id)
    a = S.mark_attendance(db, e, body.day, body.status, check_in=body.check_in, check_out=body.check_out,
                          source="manual", note=body.note or f"by {user.email}")
    return {"day": a.day.isoformat(), "status": a.status, "check_in": a.check_in, "check_out": a.check_out}


@router.post("/me/attendance/check")
def self_check(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    e = S.employee_for_user(db, user)
    if e is None:
        raise HTTPException(404, detail={"code": "no_employee_record",
                                         "message": "Your sign-in email is not linked to an employee record."})
    row, what = S.check_in_out(db, e, datetime.now(ZoneInfo(get_settings().timezone)))
    return {"action": what, "day": row.day.isoformat(), "status": row.status, "check_in": row.check_in,
            "check_out": row.check_out}


@router.get("/me/hr")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    e = S.employee_for_user(db, user)
    if e is None:
        return {"employee": None}
    t = _today()
    a, b = calc.month_bounds(t.year, t.month)
    return {"employee": {k: v for k, v in S.employee_dict(e).items() if k not in ("monthly_salary", "allowances",
                                                                                   "finance_person_id", "notes")},
            "balances": S.leave_balances(db, e, t.year), "leave": S.leave_requests(db, employee_id=e.id),
            "attendance": S.attendance_rows(db, a, b, e.id)}


# ---------------------------------------------------------------------------- leave

class LeaveIn(BaseModel):
    leave_type: str = Field(pattern="^(" + "|".join(LEAVE_TYPES) + ")$")
    start_date: date
    end_date: date
    reason: str = Field(default="", max_length=500)
    half_day: bool = False
    employee_id: int | None = Field(default=None, description="HR only: apply for someone else")


@router.get("/hr/leave")
def leave(status: str = Query("", pattern="^(|pending|approved|rejected|cancelled)$"), _: User = Depends(HR_ONLY),
          db: Session = Depends(get_db)) -> dict:
    return {"items": S.leave_requests(db, status=status)}


@router.post("/me/leave", status_code=201)
def apply_leave(body: LeaveIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    if body.employee_id is not None:
        if not ({"hr", "admin"} & set(user.role_names)):
            raise HTTPException(403, detail={"code": "forbidden", "message": "Only HR can apply for someone else."})
        e = _emp(db, body.employee_id)
    else:
        e = S.employee_for_user(db, user)
        if e is None:
            raise HTTPException(404, detail={"code": "no_employee_record",
                                             "message": "Your sign-in email is not linked to an employee record."})
    try:
        r = S.request_leave(db, e, body.leave_type, body.start_date, body.end_date, body.reason, body.half_day, user)
    except S.HRError as exc:
        raise _err(exc, 409) from exc
    return S.leave_dict(r, e)


class DecideIn(BaseModel):
    approve: bool


@router.post("/hr/leave/{leave_id}/decide")
def decide(leave_id: int, body: DecideIn, user: User = Depends(HR_ONLY), db: Session = Depends(get_db)) -> dict:
    r = db.get(LeaveRequest, leave_id)
    if r is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "Leave request not found."})
    try:
        S.decide_leave(db, r, body.approve, user)
    except S.HRError as exc:
        raise _err(exc, 409) from exc
    return S.leave_dict(r, db.get(Employee, r.employee_id))


# ---------------------------------------------------------------------------- separations and payroll

@router.get("/hr/separations")
def list_separations(_: User = Depends(HR_ONLY), db: Session = Depends(get_db)) -> dict:
    return {"items": S.separations(db)}


class SettleIn(BaseModel):
    other_deductions: float = Field(default=0, ge=0, le=100_000_000)
    other_additions: float = Field(default=0, ge=0, le=100_000_000)


@router.post("/hr/separations/{sep_id}/settlement")
def settlement(sep_id: int, body: SettleIn, _: User = Depends(HR_ONLY), db: Session = Depends(get_db)) -> dict:
    s = db.get(Separation, sep_id)
    if s is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "Separation not found."})
    return S.compute_settlement(db, s, other_deductions=body.other_deductions, other_additions=body.other_additions)


@router.get("/hr/payroll/{month}")
def payroll(month: str, user: User = Depends(HR_ONLY), db: Session = Depends(get_db)) -> dict:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise HTTPException(422, detail={"code": "validation_error", "message": "Month must be YYYY-MM."})
    run = S.build_payroll(db, month, user)
    out = S.payroll_dict(run)
    out["steps"] = [{"title": s["title"], "summary": s["summary"]} for s in workflows.payroll_steps(db, run)]
    return out


# ---------------------------------------------------------------------------- sheets

class SheetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=200)
    purpose: str = Field(pattern="^(" + "|".join(SHEET_PURPOSES) + ")$")
    source: str = Field(pattern="^(google|excel)$")
    location: str = Field(min_length=3, max_length=500)
    tab: str = Field(default="", max_length=100)
    description: str = Field(default="", max_length=2000)
    auto_record: bool = True


@router.get("/hr/sheets")
def sheets(_: User = Depends(HR_ONLY), db: Session = Depends(get_db)) -> dict:
    return {"items": [S.sheet_dict(s) for s in S.sheets_for(db)], "purposes": list(SHEET_PURPOSES)}


def _probe_sheet(db: Session, user: User, s: HRSheet) -> None:
    out = call_tool(db, agent="hr", tool="sheets_read", user=user,
                    args={"source": s.source, "location": s.location, "tab": s.tab or None, "max_rows": 5})
    if out.status != "ok":
        raise HTTPException(400, detail={"code": out.code or "sheet_error", "message": out.error})
    from ..db.base import utcnow

    s.headers = out.result.get("headers", [])
    s.tab = s.tab or out.result.get("tab", "")
    s.last_read_at = utcnow()


@router.post("/hr/sheets", status_code=201)
def add_sheet(body: SheetIn, user: User = Depends(HR_ONLY), db: Session = Depends(get_db)) -> dict:
    s = HRSheet(**body.model_dump(), headers=[])
    _probe_sheet(db, user, s)
    db.add(s)
    db.commit()
    audit(db, "hr.sheet.add", actor_user_id=user.id, actor_email=user.email, target_type="sheet", target_id=s.id,
          detail={"purpose": s.purpose, "source": s.source})
    return S.sheet_dict(s)


class SheetPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=2, max_length=200)
    purpose: str | None = Field(default=None, pattern="^(" + "|".join(SHEET_PURPOSES) + ")$")
    tab: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    auto_record: bool | None = None


@router.patch("/hr/sheets/{sheet_id}")
def edit_sheet(sheet_id: int, body: SheetPatch, user: User = Depends(HR_ONLY), db: Session = Depends(get_db)) -> dict:
    s = db.get(HRSheet, sheet_id)
    if s is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "Sheet not found."})
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(s, k, v)
    if "tab" in body.model_fields_set:
        _probe_sheet(db, user, s)
    db.commit()
    return S.sheet_dict(s)


@router.post("/hr/sheets/{sheet_id}/refresh")
def refresh_sheet(sheet_id: int, user: User = Depends(HR_ONLY), db: Session = Depends(get_db)) -> dict:
    s = db.get(HRSheet, sheet_id)
    if s is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "Sheet not found."})
    _probe_sheet(db, user, s)
    db.commit()
    return S.sheet_dict(s)


@router.delete("/hr/sheets/{sheet_id}")
def remove_sheet(sheet_id: int, user: User = Depends(HR_ONLY), db: Session = Depends(get_db)) -> dict:
    s = db.get(HRSheet, sheet_id)
    if s is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "Sheet not found."})
    db.delete(s)
    db.commit()
    audit(db, "hr.sheet.remove", actor_user_id=user.id, actor_email=user.email, target_type="sheet",
          target_id=sheet_id, detail={})
    return {"removed": sheet_id, "note": "Only the registration was removed; the sheet itself is unchanged."}


@router.post("/hr/sheets/upload", status_code=201)
async def upload_sheet(file: UploadFile = File(...), _: User = Depends(HR_ONLY)) -> dict:
    name = Path(file.filename or "").name
    if not re.fullmatch(r"[\w\- .()]{1,120}\.(xlsx|xlsm)", name, re.I):
        raise HTTPException(422, detail={"code": "bad_file", "message": "Upload an .xlsx or .xlsm file."})
    data = await file.read(25 * 1024 * 1024 + 1)
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(413, detail={"code": "too_large", "message": "Files up to 25 MB."})
    if data[:2] != b"PK":
        raise HTTPException(422, detail={"code": "bad_file", "message": "That is not an Excel workbook."})
    SHEETS_DIR.mkdir(parents=True, exist_ok=True)
    dest = SHEETS_DIR / name
    if dest.exists():
        dest = SHEETS_DIR / f"{dest.stem}-{datetime.now().strftime('%Y%m%d%H%M%S')}{dest.suffix}"
    dest.write_bytes(data)
    return {"location": dest.name, "path": str(dest)}


# ---------------------------------------------------------------------------- jobs and settings

class JobIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=2, max_length=200)
    department: str = Field(default="", max_length=100)
    location: str = Field(default="Karachi", max_length=100)
    employment_type: str = Field(default="permanent", max_length=40)
    description: str = Field(default="", max_length=20000)
    status: str = Field(default="open", pattern="^(open|closed)$")


@router.get("/hr/jobs")
def jobs(_: User = Depends(HR_ONLY), db: Session = Depends(get_db)) -> dict:
    return {"items": [S.job_dict(j) for j in db.scalars(select(HRJob).order_by(HRJob.id.desc()))]}


@router.post("/hr/jobs", status_code=201)
def add_job(body: JobIn, user: User = Depends(HR_ONLY), db: Session = Depends(get_db)) -> dict:
    j = HRJob(**body.model_dump(), created_by_user_id=user.id)
    db.add(j)
    db.commit()
    return S.job_dict(j)


@router.put("/hr/jobs/{job_id}")
def edit_job(job_id: int, body: JobIn, _: User = Depends(HR_ONLY), db: Session = Depends(get_db)) -> dict:
    j = db.get(HRJob, job_id)
    if j is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "Job not found."})
    for k, v in body.model_dump().items():
        setattr(j, k, v)
    db.commit()
    return S.job_dict(j)


@router.get("/hr/settings")
def get_hr_settings(_: User = Depends(HR_ONLY), db: Session = Depends(get_db)) -> dict:
    return S.get_policy(db)


@router.put("/hr/settings")
def put_hr_settings(body: dict[str, Any], user: User = Depends(HR_ONLY), db: Session = Depends(get_db)) -> dict:
    allowed = {"company", "recruitment", "work", "leave", "payroll", "onboarding", "induction", "compliance",
               "separation"}
    bad = set(body) - allowed
    if bad:
        raise HTTPException(422, detail={"code": "validation_error", "message": f"Unknown sections: {sorted(bad)}"})
    return S.save_policy(db, body, user)


# ---------------------------------------------------------------------------- connections

_signin: dict[str, Any] = {"running": False, "error": "", "done": False}


@router.get("/connections")
def connections(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    s = get_settings()
    out = call_tool(db, agent="orchestrator", tool="connections_status", args={}, user=user)
    return {"openai": s.llm_configured, "model": s.openai_model if s.llm_configured else None,
            "workspace": out.result if out.status == "ok" else {"error": out.error},
            "google_signin": dict(_signin)}


class AutoReplyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: str | None = Field(default=None, pattern="^(off|draft|send)$")
    interval_minutes: int | None = Field(default=None, ge=1, le=240)
    instructions: str | None = Field(default=None, max_length=1000)
    max_per_run: int | None = Field(default=None, ge=1, le=200)
    max_per_day: int | None = Field(default=None, ge=1, le=200)


@router.get("/settings/auto-reply")
def auto_reply_get(user: User = Depends(require_roles("admin", "hr")), db: Session = Depends(get_db)) -> dict:
    from ..assistant import autoreply

    return autoreply.get_config(db)


@router.put("/settings/auto-reply")
def auto_reply_put(body: AutoReplyIn, user: User = Depends(require_roles("admin", "hr")),
                   db: Session = Depends(get_db)) -> dict:
    from ..assistant import autoreply

    return autoreply.save_config(db, user, body.model_dump(exclude_none=True))


@router.post("/settings/auto-reply/run")
def auto_reply_run(user: User = Depends(require_roles("admin", "hr")), db: Session = Depends(get_db)) -> dict:
    """Check the inbox now (uses the saved mode; with auto-reply off nothing is done)."""
    from ..assistant import autoreply

    return autoreply.run_once(db) | {"config": autoreply.get_config(db)}


@router.post("/connections/google")
def google_signin(user: User = Depends(require_roles("admin", "hr"))) -> dict:
    """Open the one-time Google consent in a browser on THIS computer (the one running AgentsMind)."""
    if _signin["running"]:
        return dict(_signin)

    def work():
        import sys

        _signin.update(running=True, error="", done=False)
        try:
            sys.path.insert(0, str(REPO_ROOT))
            from mcp_servers.common import load_env
            from mcp_servers.google_common import run_consent_flow

            load_env()
            run_consent_flow()
            _signin["done"] = True
        except BaseException as exc:  # noqa: BLE001 - shown in the UI
            _signin["error"] = str(exc)[:500]
        finally:
            _signin["running"] = False

    threading.Thread(target=work, daemon=True).start()
    return {"running": True, "message": "A Google sign-in page is opening in the browser on this computer."}
