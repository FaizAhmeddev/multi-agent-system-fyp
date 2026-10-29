"""HR records: employees, checklists, letters, attendance, leave, separations, payroll runs, sheets.

All database work for HR goes through here (the assistant, the HR screens and the workflow
engine share it). Amounts, days and balances come from hr.calc; nothing is computed by a model.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..db.base import utcnow
from ..db.hr_models import (
    Attendance,
    Employee,
    HRJob,
    HRLetter,
    HRSettings,
    HRSheet,
    HRTask,
    LeaveRequest,
    PayrollRun,
    Separation,
)
from ..db.models import Candidate, User
from . import calc, letters
from .policy import LEAVE_TYPES, HRError, merged

__all__ = ["HRError"]


# ---------------------------------------------------------------------------- settings

def get_policy(db: Session) -> dict[str, Any]:
    row = db.get(HRSettings, 1)
    return merged(row.data if row else None)


def save_policy(db: Session, data: dict[str, Any], user: User | None = None) -> dict[str, Any]:
    row = db.get(HRSettings, 1)
    if row is None:
        row = HRSettings(id=1, data={})
        db.add(row)
    current = dict(row.data or {})
    for k, v in data.items():
        if isinstance(v, dict) and isinstance(current.get(k), dict):
            current[k] = {**current[k], **v}
        else:
            current[k] = v
    row.data = current
    db.commit()
    if user is not None:
        audit(db, "hr.settings", actor_user_id=user.id, actor_email=user.email, target_type="hr_settings",
              target_id=1, detail={"sections": sorted(data)})
    return merged(row.data)


# ---------------------------------------------------------------------------- employees

def employee_dict(e: Employee) -> dict[str, Any]:
    return {"id": e.id, "code": e.code, "full_name": e.full_name, "email": e.email, "phone": e.phone,
            "job_title": e.job_title, "department": e.department, "manager": e.manager, "location": e.location,
            "employment_type": e.employment_type, "status": e.status,
            "offer_date": _iso(e.offer_date), "joining_date": _iso(e.joining_date),
            "probation_end": _iso(e.probation_end), "last_working_day": _iso(e.last_working_day),
            "monthly_salary": e.monthly_salary, "currency": e.currency, "allowances": e.allowances or {},
            "bank_account_on_file": e.bank_account_on_file, "finance_person_id": e.finance_person_id,
            "candidate_id": e.candidate_id, "notes": e.notes}


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _date(v: Any) -> date | None:
    if v in (None, ""):
        return None
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError as exc:
        raise HRError(f"'{v}' is not a date (use YYYY-MM-DD).") from exc


EMP_FIELDS = ("full_name", "email", "phone", "job_title", "department", "manager", "location", "employment_type",
              "status", "monthly_salary", "currency", "allowances", "bank_account_on_file", "notes", "candidate_id",
              "finance_person_id")
EMP_DATES = ("offer_date", "joining_date", "probation_end", "last_working_day")


def create_employee(db: Session, data: dict[str, Any], user: User | None = None) -> Employee:
    name = " ".join(str(data.get("full_name", "")).split())
    if len(name) < 2:
        raise HRError("The employee's full name is needed.")
    email = str(data.get("email") or "").strip().lower()
    if email:
        clash = db.scalar(select(Employee).where(func.lower(Employee.email) == email,
                                                 Employee.status.notin_(("separated", "withdrawn"))))
        if clash is not None:
            return clash  # same person: never create a duplicate record
    codes = list(db.scalars(select(Employee.code)))
    e = Employee(code=calc.next_code(codes), full_name=name, email=email,
                 created_by_user_id=user.id if user else None)
    _apply(e, data, db)
    if e.joining_date and not e.probation_end:
        months = int(get_policy(db)["payroll"]["probation_months"] or 0)
        e.probation_end = _add_months(e.joining_date, months) if months else None
    db.add(e)
    db.commit()
    if user is not None:
        audit(db, "hr.employee.create", actor_user_id=user.id, actor_email=user.email, target_type="employee",
              target_id=e.id, detail={"code": e.code, "status": e.status})
    return e


def _apply(e: Employee, data: dict[str, Any], db: Session) -> None:
    for k in EMP_FIELDS:
        if k in data and data[k] is not None:
            v = data[k]
            if k == "monthly_salary":
                v = float(v or 0)
            elif k == "email":
                v = str(v).strip().lower()
            elif k == "full_name":
                v = " ".join(str(v).split())
            elif k == "status" and v not in ("offered", "onboarding", "active", "notice", "separated", "withdrawn"):
                raise HRError(f"Unknown status '{v}'.")
            setattr(e, k, v)
    for k in EMP_DATES:
        if k in data:
            setattr(e, k, _date(data[k]))


def update_employee(db: Session, e: Employee, data: dict[str, Any], user: User | None = None) -> Employee:
    before = employee_dict(e)
    _apply(e, data, db)
    db.commit()
    after = employee_dict(e)
    if user is not None:
        audit(db, "hr.employee.update", actor_user_id=user.id, actor_email=user.email, target_type="employee",
              target_id=e.id, detail={k: {"from": before[k], "to": after[k]} for k in after if before[k] != after[k]})
    return e


def _add_months(d: date, months: int) -> date:
    import calendar

    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def find_employees(db: Session, text: str, *, include_separated: bool = True, limit: int = 10) -> list[Employee]:
    t = " ".join(text.split()).strip()
    if not t:
        return []
    m = re.search(r"\bEMP-\d{4,}\b", t, re.I)
    if m:
        e = db.scalar(select(Employee).where(Employee.code == m.group(0).upper()))
        return [e] if e else []
    stmt = select(Employee)
    if "@" in t:
        stmt = stmt.where(func.lower(Employee.email) == t.lower())
    else:
        like = f"%{t.lower()}%"
        stmt = stmt.where(or_(func.lower(Employee.full_name).like(like), func.lower(Employee.email).like(like)))
    if not include_separated:
        stmt = stmt.where(Employee.status.notin_(("separated", "withdrawn")))
    rows = list(db.scalars(stmt.order_by(Employee.full_name).limit(limit)))
    exact = [r for r in rows if r.full_name.lower() == t.lower()]
    return exact or rows


def employee_for_user(db: Session, user: User) -> Employee | None:
    return db.scalar(select(Employee).where(func.lower(Employee.email) == user.email.lower(),
                                            Employee.status.notin_(("separated", "withdrawn"))))


def list_employees(db: Session, *, status: str = "", department: str = "", q: str = "") -> list[Employee]:
    stmt = select(Employee)
    if status:
        stmt = stmt.where(Employee.status.in_(status.split(",")))
    if department:
        stmt = stmt.where(Employee.department == department)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(Employee.full_name).like(like), func.lower(Employee.email).like(like),
                              func.lower(Employee.job_title).like(like), Employee.code == q.upper()))
    return list(db.scalars(stmt.order_by(Employee.full_name)))


# ---------------------------------------------------------------------------- checklists

def task_dict(t: HRTask) -> dict[str, Any]:
    return {"id": t.id, "employee_id": t.employee_id, "process": t.process, "key": t.key, "title": t.title,
            "owner": t.owner, "due_date": _iso(t.due_date), "status": t.status, "automated": t.automated,
            "tool": t.tool, "result": t.result or {}, "notes": t.notes,
            "completed_at": t.completed_at.isoformat() if t.completed_at else None}


def create_checklist(db: Session, e: Employee, process: str, base: date | None) -> list[HRTask]:
    """Create the checklist from the HR template (once per process and employee)."""
    existing = list(db.scalars(select(HRTask).where(HRTask.employee_id == e.id, HRTask.process == process)))
    if existing:
        return existing
    pol = get_policy(db)
    template = pol.get(process, [])
    out = []
    for i, item in enumerate(template):
        due = base + timedelta(days=int(item.get("due", item.get("day", 0)) or 0)) if base else None
        t = HRTask(employee_id=e.id, process=process, key=item["key"], title=item["title"],
                   owner=item.get("owner", "hr"), due_date=due, status="pending",
                   automated=bool(item.get("action")) or process == "induction", tool="", result={}, notes="",
                   sort=i)
        db.add(t)
        out.append(t)
    db.commit()
    return out


def tasks_for(db: Session, employee_id: int, process: str | None = None) -> list[HRTask]:
    stmt = select(HRTask).where(HRTask.employee_id == employee_id)
    if process:
        stmt = stmt.where(HRTask.process == process)
    return list(db.scalars(stmt.order_by(HRTask.process, HRTask.sort, HRTask.id)))


def set_task(db: Session, task: HRTask, status: str, *, result: dict[str, Any] | None = None, notes: str | None = None,
             tool: str | None = None) -> HRTask:
    if status not in ("pending", "in_progress", "done", "skipped", "failed"):
        raise HRError(f"Unknown task status '{status}'.")
    task.status = status
    if result is not None:
        task.result = result
    if notes is not None:
        task.notes = notes[:2000]
    if tool is not None:
        task.tool = tool
    task.completed_at = utcnow() if status == "done" else None
    db.commit()
    return task


def task_by_key(db: Session, employee_id: int, process: str, key: str) -> HRTask | None:
    return db.scalar(select(HRTask).where(HRTask.employee_id == employee_id, HRTask.process == process,
                                          HRTask.key == key))


def progress(db: Session, employee_id: int, process: str) -> dict[str, Any]:
    ts = tasks_for(db, employee_id, process)
    done = sum(1 for t in ts if t.status in ("done", "skipped"))
    today = date.today()
    overdue = [t.title for t in ts if t.status not in ("done", "skipped") and t.due_date and t.due_date < today]
    return {"total": len(ts), "done": done, "percent": round(100 * done / len(ts)) if ts else 0, "overdue": overdue}


# ---------------------------------------------------------------------------- letters

def letter_dict(lt: HRLetter) -> dict[str, Any]:
    return {"id": lt.id, "employee_id": lt.employee_id, "candidate_id": lt.candidate_id, "kind": lt.kind,
            "title": lt.title, "recipient_name": lt.recipient_name, "recipient_email": lt.recipient_email,
            "status": lt.status, "has_docx": bool(lt.docx_path), "has_pdf": bool(lt.pdf_path),
            "docx_path": lt.docx_path, "pdf_path": lt.pdf_path, "drive_file_id": lt.drive_file_id,
            "sent_at": lt.sent_at.isoformat() if lt.sent_at else None, "created_at": lt.created_at.isoformat(),
            "fields": {k: v for k, v in (lt.fields or {}).items() if k not in ("settlement",)}}


def letter_fields(e: Employee | None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    f: dict[str, Any] = {}
    if e is not None:
        f.update(name=e.full_name, email=e.email, job_title=e.job_title, department=e.department, manager=e.manager,
                 location=e.location, employment_type=e.employment_type, joining_date=e.joining_date,
                 last_working_day=e.last_working_day, salary=e.monthly_salary, currency=e.currency,
                 allowances=e.allowances or {}, code=e.code)
    for k, v in (extra or {}).items():
        if v not in (None, ""):
            f[k] = v
    return f


def create_letter(db: Session, kind: str, fields: dict[str, Any], *, employee: Employee | None = None,
                  candidate: Candidate | None = None, user: User | None = None) -> HRLetter:
    """Render a letter to Word and PDF and record it (status draft: nothing has been sent)."""
    pol = get_policy(db)
    f = letter_fields(employee, fields)
    letter = letters.build(kind, f, pol)
    lt = HRLetter(employee_id=employee.id if employee else None, candidate_id=candidate.id if candidate else None,
                  kind=kind, title=f"{letters.KINDS[kind]}: {f.get('name', '')}"[:300],
                  recipient_name=str(f.get("name", ""))[:200], recipient_email=str(f.get("email", ""))[:254],
                  status="draft", fields=_jsonable(f), created_by_user_id=user.id if user else None)
    db.add(lt)
    db.flush()
    folder = f"{employee.code} {employee.full_name}" if employee else f"candidate {f.get('name', lt.id)}"
    ref = f"HR/{kind.upper()[:4]}/{date.today().year}/{lt.id:04d}"
    docx_path, pdf_path = letters.render(letter, pol["company"], folder, lt.id, ref)
    lt.docx_path, lt.pdf_path = str(docx_path), str(pdf_path)
    db.commit()
    if user is not None:
        audit(db, "hr.letter.create", actor_user_id=user.id, actor_email=user.email, target_type="letter",
              target_id=lt.id, detail={"kind": kind, "employee_id": lt.employee_id})
    return lt


def _jsonable(f: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in f.items():
        if isinstance(v, date | datetime):
            out[k] = v.isoformat()
        elif isinstance(v, str | int | float | bool | type(None)):
            out[k] = v
        elif isinstance(v, dict | list):
            out[k] = v
        else:
            out[k] = str(v)
    return out


# ---------------------------------------------------------------------------- attendance

def mark_attendance(db: Session, e: Employee, day: date, status: str, *, check_in: str = "", check_out: str = "",
                    source: str = "manual", note: str = "") -> Attendance:
    if status not in ("present", "absent", "late", "half_day", "leave", "holiday", "wfh"):
        raise HRError(f"Unknown attendance status '{status}'.")
    row = db.scalar(select(Attendance).where(Attendance.employee_id == e.id, Attendance.day == day))
    if row is None:
        row = Attendance(employee_id=e.id, day=day, status=status)
        db.add(row)
    row.status = status
    if check_in:
        row.check_in = check_in[:5]
    if check_out:
        row.check_out = check_out[:5]
    row.source, row.note = source, note[:300]
    db.commit()
    return row


def check_in_out(db: Session, e: Employee, now: datetime) -> tuple[Attendance, str]:
    """Self-service: the first call of the day checks in (late after the policy time), the next checks out."""
    pol = get_policy(db)
    day, hhmm = now.date(), now.strftime("%H:%M")
    row = db.scalar(select(Attendance).where(Attendance.employee_id == e.id, Attendance.day == day))
    if row is None or not row.check_in:
        status = "late" if hhmm > pol["work"]["late_after"] else "present"
        return mark_attendance(db, e, day, status, check_in=hhmm, source="self"), "check_in"
    row.check_out = hhmm
    db.commit()
    return row, "check_out"


def attendance_rows(db: Session, start: date, end: date, employee_id: int | None = None) -> list[dict[str, Any]]:
    stmt = select(Attendance, Employee).join(Employee).where(Attendance.day >= start, Attendance.day <= end)
    if employee_id:
        stmt = stmt.where(Attendance.employee_id == employee_id)
    return [{"day": a.day.isoformat(), "employee_id": e.id, "code": e.code, "name": e.full_name, "status": a.status,
             "check_in": a.check_in, "check_out": a.check_out, "source": a.source, "note": a.note}
            for a, e in db.execute(stmt.order_by(Attendance.day, Employee.full_name))]


def attendance_summary(db: Session, start: date, end: date, employee_id: int | None = None) -> list[dict[str, Any]]:
    """Per employee: present, late, absent, leave, half days and unmarked working days in the period."""
    pol = get_policy(db)
    hol = calc.holidays_of(pol)
    emps = [db.get(Employee, employee_id)] if employee_id else list_employees(db, status="active,notice,onboarding")
    rows = attendance_rows(db, start, end, employee_id)
    leave = approved_leave_days(db, start, end)
    out = []
    for e in [x for x in emps if x]:
        mine = [r for r in rows if r["employee_id"] == e.id]
        s = max(start, e.joining_date or start)
        en = min(end, e.last_working_day or end, date.today())
        wd = calc.working_days(s, en, pol["work"]["weekend"], hol) if en >= s else 0
        counts = {k: sum(1 for r in mine if r["status"] == k) for k in ("present", "late", "absent", "half_day",
                                                                         "leave", "wfh", "holiday")}
        marked = sum(counts.values())
        out.append({"employee_id": e.id, "code": e.code, "name": e.full_name, "department": e.department,
                    "working_days": wd, **counts, "approved_leave_days": leave.get(e.id, {}).get("total", 0.0),
                    "unmarked": max(wd - marked, 0)})
    return out


# ---------------------------------------------------------------------------- leave

def leave_dict(r: LeaveRequest, e: Employee | None = None) -> dict[str, Any]:
    return {"id": r.id, "employee_id": r.employee_id, "name": e.full_name if e else "", "code": e.code if e else "",
            "leave_type": r.leave_type, "start_date": r.start_date.isoformat(), "end_date": r.end_date.isoformat(),
            "days": r.days, "reason": r.reason, "status": r.status,
            "decided_at": r.decided_at.isoformat() if r.decided_at else None}


def request_leave(db: Session, e: Employee, leave_type: str, start: date, end: date, reason: str = "",
                  half_day: bool = False, user: User | None = None) -> LeaveRequest:
    if leave_type not in LEAVE_TYPES:
        raise HRError(f"Leave type must be one of: {', '.join(LEAVE_TYPES)}.")
    if end < start:
        raise HRError("The leave ends before it starts.")
    pol = get_policy(db)
    days = calc.leave_days(start, end, pol, half_day)
    if days <= 0:
        raise HRError("Those dates fall on weekends or holidays only.")
    overlap = db.scalar(select(LeaveRequest).where(LeaveRequest.employee_id == e.id,
                                                   LeaveRequest.status.in_(("pending", "approved")),
                                                   LeaveRequest.start_date <= end, LeaveRequest.end_date >= start))
    if overlap is not None:
        raise HRError(f"{e.full_name} already has {overlap.status} leave from {overlap.start_date} to "
                      f"{overlap.end_date}.")
    if leave_type != "unpaid":
        bal = leave_balances(db, e, start.year)[leave_type]
        if days > bal["remaining"]:
            raise HRError(f"{e.full_name} has {bal['remaining']:g} {leave_type} day(s) left this year; this request "
                          f"needs {days:g}. Use unpaid leave or another type.")
    r = LeaveRequest(employee_id=e.id, leave_type=leave_type, start_date=start, end_date=end, days=days,
                     reason=reason[:500], status="pending")
    db.add(r)
    db.commit()
    if user is not None:
        audit(db, "hr.leave.request", actor_user_id=user.id, actor_email=user.email, target_type="leave",
              target_id=r.id, detail={"employee": e.code, "type": leave_type, "days": days})
    return r


def decide_leave(db: Session, r: LeaveRequest, approve: bool, user: User) -> LeaveRequest:
    if r.status != "pending":
        raise HRError(f"This request is already {r.status}.")
    r.status = "approved" if approve else "rejected"
    r.decided_by_user_id, r.decided_at = user.id, utcnow()
    if approve:
        e = db.get(Employee, r.employee_id)
        d = r.start_date
        pol = get_policy(db)
        while d <= r.end_date:
            if calc.is_working_day(d, pol["work"]["weekend"], calc.holidays_of(pol)):
                mark_attendance(db, e, d, "leave", source="leave", note=f"{r.leave_type} leave #{r.id}")
            d += timedelta(days=1)
    db.commit()
    audit(db, f"hr.leave.{r.status}", actor_user_id=user.id, actor_email=user.email, target_type="leave",
          target_id=r.id, detail={"days": r.days, "type": r.leave_type})
    return r


def leave_taken(db: Session, employee_id: int, year: int) -> dict[str, float]:
    a, b = date(year, 1, 1), date(year, 12, 31)
    out: dict[str, float] = {}
    for r in db.scalars(select(LeaveRequest).where(LeaveRequest.employee_id == employee_id,
                                                   LeaveRequest.status == "approved",
                                                   LeaveRequest.start_date <= b, LeaveRequest.end_date >= a)):
        out[r.leave_type] = out.get(r.leave_type, 0.0) + r.days
    return out


def leave_balances(db: Session, e: Employee, year: int) -> dict[str, dict[str, float]]:
    return calc.leave_balances(get_policy(db), e.joining_date, year, leave_taken(db, e.id, year))


def approved_leave_days(db: Session, start: date, end: date) -> dict[int, dict[str, float]]:
    """Working days of approved leave inside [start, end], per employee and type."""
    pol = get_policy(db)
    hol = calc.holidays_of(pol)
    out: dict[int, dict[str, float]] = {}
    for r in db.scalars(select(LeaveRequest).where(LeaveRequest.status == "approved", LeaveRequest.start_date <= end,
                                                   LeaveRequest.end_date >= start)):
        s, en = max(start, r.start_date), min(end, r.end_date)
        n = calc.working_days(s, en, pol["work"]["weekend"], hol)
        if r.days == 0.5:
            n = 0.5
        d = out.setdefault(r.employee_id, {"total": 0.0})
        d[r.leave_type] = d.get(r.leave_type, 0.0) + n
        d["total"] += n
    return out


def leave_requests(db: Session, *, status: str = "", employee_id: int | None = None) -> list[dict[str, Any]]:
    stmt = select(LeaveRequest, Employee).join(Employee)
    if status:
        stmt = stmt.where(LeaveRequest.status == status)
    if employee_id:
        stmt = stmt.where(LeaveRequest.employee_id == employee_id)
    return [leave_dict(r, e) for r, e in db.execute(stmt.order_by(LeaveRequest.start_date.desc()))]


# ---------------------------------------------------------------------------- separation

def separation_dict(s: Separation, e: Employee | None = None) -> dict[str, Any]:
    return {"id": s.id, "employee_id": s.employee_id, "name": e.full_name if e else "", "code": e.code if e else "",
            "kind": s.kind, "notice_date": _iso(s.notice_date), "last_working_day": s.last_working_day.isoformat(),
            "reason": s.reason, "status": s.status, "settlement": s.settlement or {}}


def start_separation(db: Session, e: Employee, *, kind: str, last_day: date, notice_date: date | None, reason: str,
                     user: User | None = None) -> Separation:
    s = db.scalar(select(Separation).where(Separation.employee_id == e.id, Separation.status != "closed"))
    if s is None:
        s = Separation(employee_id=e.id, kind=kind, notice_date=notice_date, last_working_day=last_day,
                       reason=reason[:500], status="initiated", settlement={})
        db.add(s)
    else:
        s.kind, s.notice_date, s.last_working_day, s.reason = kind, notice_date, last_day, reason[:500]
    e.status = "notice"
    e.last_working_day = last_day
    db.commit()
    create_checklist(db, e, "separation", last_day)
    if user is not None:
        audit(db, "hr.separation.start", actor_user_id=user.id, actor_email=user.email, target_type="employee",
              target_id=e.id, detail={"kind": kind, "last_working_day": last_day.isoformat()})
    return s


def compute_settlement(db: Session, s: Separation, *, other_deductions: float = 0.0,
                       other_additions: float = 0.0) -> dict[str, Any]:
    e = db.get(Employee, s.employee_id)
    pol = get_policy(db)
    bal = leave_balances(db, e, s.last_working_day.year)
    a, _ = calc.month_bounds(s.last_working_day.year, s.last_working_day.month)
    unpaid = approved_leave_days(db, a, s.last_working_day).get(e.id, {}).get("unpaid", 0.0)
    out = calc.final_settlement(employee=employee_dict(e), last_day=s.last_working_day, policy=pol,
                                annual_remaining=bal["annual"]["remaining"], notice_date=s.notice_date,
                                unpaid_leave_days_last_month=unpaid, other_deductions=other_deductions,
                                other_additions=other_additions)
    s.settlement = out
    db.commit()
    return out


def separations(db: Session, start: date | None = None, end: date | None = None) -> list[dict[str, Any]]:
    stmt = select(Separation, Employee).join(Employee)
    if start and end:
        stmt = stmt.where(Separation.last_working_day >= start, Separation.last_working_day <= end)
    return [separation_dict(s, e) for s, e in db.execute(stmt.order_by(Separation.last_working_day.desc()))]


# ---------------------------------------------------------------------------- payroll

def build_payroll(db: Session, month: str, user: User | None = None) -> PayrollRun:
    """Draft (or refresh a draft) payroll for YYYY-MM from employees, attendance and approved leave."""
    y, m = int(month[:4]), int(month[5:7])
    a, b = calc.month_bounds(y, m)
    run = db.scalar(select(PayrollRun).where(PayrollRun.month == month))
    if run is not None and run.status != "draft":
        return run
    pol = get_policy(db)
    leave = approved_leave_days(db, a, b)
    absent = {r["employee_id"]: r["absent"] for r in attendance_summary(db, a, b)}
    lines = []
    for e in db.scalars(select(Employee).where(Employee.status.in_(("active", "notice", "onboarding", "separated")))):
        if e.joining_date and e.joining_date > b:
            continue
        if e.last_working_day and e.last_working_day < a:
            continue
        if e.monthly_salary <= 0:
            continue
        lines.append(calc.payroll_line(employee=employee_dict(e), year=y, month=m, policy=pol,
                                       unpaid_leave_days=leave.get(e.id, {}).get("unpaid", 0.0),
                                       absent_days=absent.get(e.id, 0)))
    totals: dict[str, Any] = {}
    for ln in lines:
        t = totals.setdefault(ln["currency"], {"employees": 0, "gross": 0.0, "deductions": 0.0, "net": 0.0})
        t["employees"] += 1
        t["gross"] = calc.money(t["gross"] + ln["gross"])
        t["deductions"] = calc.money(t["deductions"] + ln["proration"] + ln["leave_deduction"] + ln["eobi"] + ln["tax"])
        t["net"] = calc.money(t["net"] + ln["net"])
    if run is None:
        run = PayrollRun(month=month, status="draft", created_by_user_id=user.id if user else None)
        db.add(run)
    run.lines, run.totals = lines, totals
    db.commit()
    return run


def payroll_dict(r: PayrollRun) -> dict[str, Any]:
    return {"id": r.id, "month": r.month, "status": r.status, "totals": r.totals, "lines": r.lines,
            "updated_at": r.updated_at.isoformat()}


# ---------------------------------------------------------------------------- jobs and sheets

def job_dict(j: HRJob) -> dict[str, Any]:
    return {"id": j.id, "title": j.title, "department": j.department, "location": j.location,
            "employment_type": j.employment_type, "description": j.description, "status": j.status}


def find_job(db: Session, title: str) -> HRJob | None:
    rows = list(db.scalars(select(HRJob).where(HRJob.status == "open")))
    t = title.lower()
    exact = [j for j in rows if j.title.lower() == t]
    if exact:
        return exact[0]
    words = set(re.findall(r"[a-z]+", t))
    scored = sorted(rows, key=lambda j: -len(words & set(re.findall(r"[a-z]+", j.title.lower()))))
    return scored[0] if scored and words & set(re.findall(r"[a-z]+", scored[0].title.lower())) else None


def sheet_dict(s: HRSheet) -> dict[str, Any]:
    return {"id": s.id, "name": s.name, "purpose": s.purpose, "source": s.source, "location": s.location,
            "tab": s.tab, "description": s.description, "headers": s.headers or [], "auto_record": s.auto_record,
            "link": s.location if s.source == "google" and s.location.startswith("http") else
            (f"https://docs.google.com/spreadsheets/d/{s.location}/edit" if s.source == "google" else s.location),
            "last_read_at": s.last_read_at.isoformat() if s.last_read_at else None}


def sheets_for(db: Session, purpose: str | None = None) -> list[HRSheet]:
    stmt = select(HRSheet)
    if purpose:
        stmt = stmt.where(HRSheet.purpose == purpose)
    return list(db.scalars(stmt.order_by(HRSheet.purpose, HRSheet.name)))
