"""HR reports: new joiners, induction, separations, attendance, leave, compliance, payroll, headcount.

Each report is {title, period, columns, rows, summary}. Every number is counted or summed
in code from the HR records. export_xlsx() writes the same table to data/hr_reports/ so it
can be downloaded or attached to an email.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.hr_models import Employee, HRTask
from ..settings import REPO_ROOT
from . import calc
from . import service as S

REPORTS_DIR = REPO_ROOT / "data" / "hr_reports"
KINDS = {
    "new_joiners": "New joiners",
    "induction": "Induction progress",
    "onboarding": "Onboarding progress",
    "separations": "Separations",
    "attendance": "Attendance",
    "leave": "Leave",
    "compliance": "Compliance checklist",
    "payroll": "Payroll",
    "headcount": "Headcount",
}


def _report(title: str, period: calc.Period | None, columns: list[str], rows: list[dict[str, Any]],
            summary: str) -> dict[str, Any]:
    return {"title": title, "period": period.label if period else "", "start": period.start.isoformat() if period
            else None, "end": period.end.isoformat() if period else None, "columns": columns, "rows": rows,
            "summary": summary}


def build(db: Session, kind: str, period: calc.Period, *, employee_id: int | None = None) -> dict[str, Any]:
    if kind == "new_joiners":
        es = [e for e in S.list_employees(db) if e.joining_date and period.start <= e.joining_date <= period.end]
        rows = []
        for e in es:
            on = S.progress(db, e.id, "onboarding")
            rows.append({"code": e.code, "name": e.full_name, "job_title": e.job_title, "department": e.department,
                         "joining_date": e.joining_date.isoformat(), "status": e.status,
                         "onboarding": f"{on['done']}/{on['total']}", "overdue": len(on["overdue"])})
        by_dept: dict[str, int] = {}
        for e in es:
            by_dept[e.department or "-"] = by_dept.get(e.department or "-", 0) + 1
        dept = ", ".join(f"{k} {v}" for k, v in sorted(by_dept.items()))
        return _report(f"New joiners: {period.label}", period, ["code", "name", "job_title", "department",
                                                                "joining_date", "status", "onboarding", "overdue"],
                       rows, f"{len(rows)} new joiner(s)" + (f" ({dept})" if dept else "") + ".")
    if kind in ("induction", "onboarding"):
        es = [e for e in S.list_employees(db, status="offered,onboarding,active")
              if e.joining_date and e.joining_date >= period.start and e.joining_date <= period.end]
        rows = []
        for e in es:
            pr = S.progress(db, e.id, kind)
            nxt = next((t for t in S.tasks_for(db, e.id, kind) if t.status not in ("done", "skipped")), None)
            rows.append({"code": e.code, "name": e.full_name, "joining_date": e.joining_date.isoformat(),
                         "done": pr["done"], "total": pr["total"], "percent": pr["percent"],
                         "next_item": nxt.title if nxt else "complete", "overdue": "; ".join(pr["overdue"])})
        complete = sum(1 for r in rows if r["total"] and r["done"] == r["total"])
        return _report(f"{KINDS[kind]}: {period.label}", period, ["code", "name", "joining_date", "done", "total",
                                                                 "percent", "next_item", "overdue"], rows,
                       f"{len(rows)} new joiner(s); {complete} completed {kind}; "
                       f"{sum(1 for r in rows if r['overdue'])} with overdue items.")
    if kind == "separations":
        rows = []
        for s in S.separations(db, period.start, period.end):
            pr = S.progress(db, s["employee_id"], "separation")
            rows.append({"code": s["code"], "name": s["name"], "kind": s["kind"], "last_working_day":
                         s["last_working_day"], "status": s["status"], "checklist": f"{pr['done']}/{pr['total']}",
                         "net_settlement": (s["settlement"] or {}).get("net_payable", ""), "reason": s["reason"]})
        return _report(f"Separations: {period.label}", period, ["code", "name", "kind", "last_working_day", "status",
                                                               "checklist", "net_settlement", "reason"], rows,
                       f"{len(rows)} separation(s); {sum(1 for r in rows if r['status'] in ('settled', 'closed'))} "
                       "settled.")
    if kind == "attendance":
        rows = S.attendance_summary(db, period.start, period.end, employee_id)
        cols = ["code", "name", "department", "working_days", "present", "late", "absent", "half_day", "leave", "wfh",
                "unmarked"]
        late = sum(r["late"] for r in rows)
        absent = sum(r["absent"] for r in rows)
        return _report(f"Attendance: {period.label}", period, cols, rows,
                       f"{len(rows)} employee(s); {late} late arrival(s), {absent} absence(s) without leave, "
                       f"{sum(r['unmarked'] for r in rows)} working day(s) not marked.")
    if kind == "leave":
        reqs = [r for r in S.leave_requests(db, employee_id=employee_id)
                if r["start_date"] <= period.end.isoformat() and r["end_date"] >= period.start.isoformat()]
        cols = ["code", "name", "leave_type", "start_date", "end_date", "days", "status", "reason"]
        approved = sum(r["days"] for r in reqs if r["status"] == "approved")
        pending = sum(1 for r in reqs if r["status"] == "pending")
        return _report(f"Leave: {period.label}", period, cols, reqs,
                       f"{len(reqs)} request(s); {approved:g} approved day(s); {pending} waiting for a decision.")
    if kind == "compliance":
        rows = []
        es = [db.get(Employee, employee_id)] if employee_id else S.list_employees(db, status="onboarding,active,notice")
        for e in [x for x in es if x]:
            ts = S.tasks_for(db, e.id, "compliance")
            missing = [t.title for t in ts if t.status not in ("done", "skipped")]
            rows.append({"code": e.code, "name": e.full_name, "done": len(ts) - len(missing), "total": len(ts),
                         "missing": "; ".join(missing) if ts else "checklist not created"})
        return _report("Compliance checklist", None, ["code", "name", "done", "total", "missing"], rows,
                       f"{sum(1 for r in rows if r['total'] and r['done'] == r['total'])} of {len(rows)} employee(s) "
                       "fully compliant.")
    if kind == "payroll":
        month = f"{period.start.year:04d}-{period.start.month:02d}"
        run = S.build_payroll(db, month)
        cols = ["code", "name", "department", "gross", "proration", "unpaid_leave_days", "absent_days",
                "leave_deduction", "eobi", "tax", "net", "currency"]
        tot = "; ".join(f"{c}: {t['employees']} employee(s), net {t['net']:,.2f}" for c, t in run.totals.items())
        return _report(f"Payroll {month} ({run.status})", period, cols, run.lines, tot or "No employees with a "
                                                                                       "salary on record.")
    if kind == "headcount":
        rows: dict[tuple[str, str], int] = {}
        for e in S.list_employees(db, status="onboarding,active,notice"):
            k = (e.department or "-", e.status)
            rows[k] = rows.get(k, 0) + 1
        out = [{"department": d, "status": st, "count": n} for (d, st), n in sorted(rows.items())]
        return _report("Headcount", None, ["department", "status", "count"], out,
                       f"{sum(r['count'] for r in out)} employee(s) on the books.")
    raise S.HRError(f"Unknown report '{kind}'. Reports: {', '.join(KINDS)}.")


def export_xlsx(report: dict[str, Any]) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = re.sub(r"[\[\]:*?/\\]", "", report["title"])[:31] or "Report"
    ws.append([report["title"]])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append([report["summary"]])
    ws.append([])
    ws.append([c.replace("_", " ").capitalize() for c in report["columns"]])
    for cell in ws[4]:
        cell.font = Font(bold=True)
    for r in report["rows"]:
        ws.append([_safe(r.get(c, "")) for c in report["columns"]])
    for i, c in enumerate(report["columns"], start=1):
        width = max([len(str(c))] + [len(str(r.get(c, ""))) for r in report["rows"][:200]]) + 2
        ws.column_dimensions[ws.cell(row=4, column=i).column_letter].width = min(width, 60)
    name = re.sub(r"[^A-Za-z0-9]+", "-", report["title"]).strip("-").lower()[:60]
    path = (REPORTS_DIR / f"{name}-{date.today().isoformat()}.xlsx").resolve()
    wb.save(path)
    return path


def _safe(v: Any) -> Any:
    """Neutralise spreadsheet formula injection in text cells."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@"):
        return "'" + v
    return v


def compliance_formats(db: Session) -> Path:
    """The compliance checklist as a matrix (one row per employee, one column per item) for audits."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    pol = S.get_policy(db)
    items = [c["key"] for c in pol["compliance"]]
    titles = [c["title"] for c in pol["compliance"]]
    wb = Workbook()
    ws = wb.active
    ws.title = "Compliance"
    ws.append(["Code", "Name", "Department", "Joining date", *titles])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for e in S.list_employees(db, status="onboarding,active,notice"):
        status = {t.key: t.status for t in db.scalars(select(HRTask).where(HRTask.employee_id == e.id,
                                                                          HRTask.process == "compliance"))}
        ws.append([e.code, _safe(e.full_name), e.department, e.joining_date.isoformat() if e.joining_date else "",
                   *[{"done": "Yes", "skipped": "N/A"}.get(status.get(k, ""), "No") for k in items]])
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = (REPORTS_DIR / f"compliance-matrix-{date.today().isoformat()}.xlsx").resolve()
    wb.save(path)
    return path
