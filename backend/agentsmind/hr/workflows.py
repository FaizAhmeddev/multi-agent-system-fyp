"""HR workflows: one approval runs a whole bundle of HR legwork.

A workflow is a list of steps proposed by the HR agent and shown on ONE approval card, each
step on its own line. After approval the steps run in order:
  core steps   HR records in AgentsMind (create the employee, checklists, letters, leave, separation,
               settlement, payroll run status)
  tool steps   external actions through the tool gateway (email with attachments, IT ticket, payroll
               in the Finance Portal, calendar invites, WhatsApp, a row in an HR sheet). Each one is
               logged, checked against roles and has its own idempotency key derived from the
               workflow's approval, so a replay never repeats an action.
A failed step does not stop the others; its checklist item is marked failed with the reason and
can be retried from the HR screens. Arguments may refer to earlier results with placeholders:
{{employee.email}}, {{employee.finance_person_id}}, {{letter.offer.pdf}}, {{letter.welcome.docx}}.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.hr_models import Employee, HRLetter, HRSheet, LeaveRequest, PayrollRun, Separation
from ..db.models import Candidate, User
from . import service as S

log = logging.getLogger("agentsmind.hr.workflow")
PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+)\.([a-z_]+)(?:\.([a-z_]+))?\s*\}\}")

# ---------------------------------------------------------------------------- sheet rows

HEADER_SYNONYMS: dict[str, tuple[str, ...]] = {
    "code": ("employee id", "emp id", "employee code", "emp code", "id", "code", "staff id"),
    "full_name": ("name", "full name", "employee name", "employee", "candidate", "candidate name", "staff name"),
    "email": ("email", "e-mail", "email address", "mail"),
    "phone": ("phone", "mobile", "contact", "contact number", "cell", "whatsapp"),
    "job_title": ("designation", "job title", "position", "role", "title"),
    "department": ("department", "dept", "team", "function"),
    "manager": ("manager", "reporting to", "line manager", "supervisor"),
    "location": ("location", "city", "office", "branch"),
    "employment_type": ("employment type", "type", "contract type"),
    "joining_date": ("joining date", "date of joining", "doj", "start date", "joined", "joined on"),
    "last_working_day": ("last working day", "lwd", "exit date", "leaving date", "end date", "relieving date"),
    "monthly_salary": ("salary", "gross salary", "monthly salary", "basic salary", "pay", "ctc"),
    "status": ("status", "employee status", "stage"),
    "reason": ("reason", "reason for leaving", "separation reason", "remarks"),
    "recorded_on": ("recorded on", "entry date", "date added", "timestamp", "date"),
}


def _norm(h: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", h.lower()).strip()


def map_headers(headers: list[str]) -> dict[str, str]:
    """header -> employee field, for the headers that clearly mean one."""
    out: dict[str, str] = {}
    used: set[str] = set()
    for h in headers:
        n = _norm(h)
        for field, syns in HEADER_SYNONYMS.items():
            if field in used:
                continue
            if n in syns or n == field.replace("_", " "):
                out[h] = field
                used.add(field)
                break
    return out


def sheet_row(headers: list[str], values: dict[str, Any]) -> list[Any]:
    m = map_headers(headers)
    return [_cell(values.get(m[h], "")) if h in m else "" for h in headers]


def _cell(v: Any) -> Any:
    if isinstance(v, date | datetime):
        return v.isoformat()[:10]
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return "" if v is None else v


def sheet_step(db: Session, purpose: str, values: dict[str, Any], *, title: str, task: tuple[str, str] | None = None
               ) -> dict[str, Any] | None:
    """A sheets_append step for the registered sheet of this purpose (None when no such sheet)."""
    sh = db.scalar(select(HRSheet).where(HRSheet.purpose == purpose, HRSheet.auto_record.is_(True))
                   .order_by(HRSheet.id))
    if sh is None or not sh.headers:
        return None
    row = sheet_row(sh.headers, values)
    if not any(str(c).strip() for c in row):
        return None
    return {"kind": "tool", "tool": "sheets_append", "title": title,
            "summary": f"Add a row to '{sh.name}' ({sh.source}): " + ", ".join(str(c) for c in row if str(c).strip()),
            "args": {"source": sh.source, "location": sh.location, "tab": sh.tab or None, "rows": [row]},
            "task": list(task) if task else None}


# ---------------------------------------------------------------------------- builders

def _when(day: date, hhmm: str, minutes: int, tz: str) -> tuple[str, str]:
    h, m = (int(x) for x in hhmm.split(":"))
    start = datetime.combine(day, time(h, m), ZoneInfo(tz))
    return start.isoformat(), (start + timedelta(minutes=minutes)).isoformat()


def _next_working(d: date, policy: dict[str, Any]) -> date:
    from .calc import holidays_of, is_working_day

    hol = holidays_of(policy)
    while not is_working_day(d, policy["work"]["weekend"], hol):
        d += timedelta(days=1)
    return d


def step(kind: str, title: str, summary: str, **kw: Any) -> dict[str, Any]:
    return {"kind": kind, "title": title, "summary": summary, **kw}


def onboarding_steps(db: Session, emp: dict[str, Any], *, tz: str, options: dict[str, bool],
                     existing_id: int | None, requester: tuple[str, str]) -> list[dict[str, Any]]:
    pol = S.get_policy(db)
    join = S._date(emp.get("joining_date"))
    name = emp.get("full_name", "")
    steps: list[dict[str, Any]] = []
    if existing_id is None:
        steps.append(step("core", "Record the new joiner", f"{name}, {emp.get('job_title', '')}, "
                          f"{emp.get('department', '')}, joining {emp.get('joining_date') or 'date to be confirmed'}",
                          op="create_employee", params={**emp, "status": "onboarding"}))
    else:
        steps.append(step("core", "Mark as onboarding", f"{name}: status onboarding", op="update_employee",
                          params={"status": "onboarding", **{k: v for k, v in emp.items() if k in (
                              "joining_date", "job_title", "department", "manager", "monthly_salary", "phone")}}))
    steps.append(step("core", "Create the onboarding, induction and compliance checklists",
                      f"{len(pol['onboarding'])} onboarding, {len(pol['induction'])} induction and "
                      f"{len(pol['compliance'])} compliance items with due dates", op="checklists",
                      params={"processes": ["onboarding", "compliance", "induction"]}))
    if options.get("contract", True):
        steps.append(step("core", "Generate the employment contract (Word and PDF)",
                          "Contract with salary, probation, notice and leave terms", op="letter",
                          params={"kind": "contract"}, task=["onboarding", "contract"]))
    induction = []
    if join:
        for item in pol["induction"]:
            d = _next_working(join + timedelta(days=int(item.get("day", 0))), pol)
            induction.append({"date": d.isoformat(), "time": item.get("time", ""), "title": item["title"]})
    steps.append(step("core", "Generate the onboarding welcome letter (Word and PDF)",
                      "Welcome letter with first-day instructions" + (" and the induction plan" if induction else ""),
                      op="letter", params={"kind": "welcome", "fields": {"induction": induction}}))
    if options.get("welcome_email", True) and emp.get("email"):
        steps.append(step("tool", "Send the welcome email with the onboarding letter",
                          f"To {emp['email']}, with the welcome letter (PDF) attached", tool="gmail_send_email",
                          args={"to": ["{{employee.email}}"], "subject": f"Welcome to {pol['company']['name'] or 'the team'}",
                                "body": f"Dear {name.split()[0] if name else ''},\n\nWelcome aboard! Your onboarding "
                                        "letter is attached with everything you need for your first day.\n\n"
                                        f"Best regards,\n{pol['company']['signatory_name'] or 'HR'}",
                                "attachments": ["{{letter.welcome.pdf}}"]},
                          task=["onboarding", "welcome"]))
    if options.get("it_ticket", True):
        steps.append(step("tool", "Ask IT to prepare the laptop, email and access", "IT Helpdesk ticket, priority high"
                          + (f", needed by {join.isoformat()}" if join else ""), tool="it_create_ticket", agent="it",
                          args={"requester_name": requester[0], "requester_email": requester[1],
                                "department": "HR", "category": "account", "priority": "high",
                                "summary": f"New joiner setup: {name}"[:150],
                                "description": f"Please prepare a laptop, a company email account and system access for "
                                               f"{name}, {emp.get('job_title', '')} ({emp.get('department', '')}), "
                                               f"joining on {join.isoformat() if join else 'TBC'}. Manager: "
                                               f"{emp.get('manager') or '-'}."},
                          task=["onboarding", "it_setup"]))
    if options.get("payroll", True) and emp.get("email") and float(emp.get("monthly_salary") or 0) > 0 and join:
        steps.append(step("tool", "Add to payroll in the Finance Portal",
                          f"{name}, {emp.get('department')}, {pol['payroll']['currency']} "
                          f"{float(emp['monthly_salary']):,.0f} a month from {join.isoformat()}",
                          tool="payroll_enroll_employee",
                          args={"full_name": name, "email": "{{employee.email}}",
                                "department": portal_department(emp.get("department", "")),
                                "job_title": emp.get("job_title") or "Staff",
                                "monthly_salary": f"{float(emp['monthly_salary']):.2f}", "start_date": join.isoformat(),
                                "employment_type": portal_employment_type(emp.get("employment_type", "")),
                                "currency": emp.get("currency") or "PKR", "notes": "Onboarded by AgentsMind HR"},
                          task=["onboarding", "payroll"], on_ok="save_finance_id"))
    if options.get("induction_events", True) and induction:
        for item, plan in zip(pol["induction"], induction, strict=False):
            d = date.fromisoformat(plan["date"])
            start, end = _when(d, item.get("time", "10:00"), int(item.get("minutes", 60)), tz)
            attendees = [a for a in (emp.get("email"),) if a]
            steps.append(step("tool", f"Induction: {item['title']}", f"{plan['date']} {item.get('time', '')}, "
                              f"{item.get('minutes', 60)} min" + (f", invite {emp['email']}" if attendees else ""),
                              tool="calendar_create_event",
                              args={"summary": f"{item['title']}: {name}", "start": start, "end": end, "timezone": tz,
                                    "attendees": attendees, "description": f"Induction for {name}.",
                                    "add_meet": False, "notify_attendees": True},
                              task=["induction", item["key"]]))
    if options.get("probation_event", True) and join:
        months = int(pol["payroll"]["probation_months"] or 3)
        d = _next_working(S._add_months(join, months) - timedelta(days=5), pol)
        start, end = _when(d, "15:00", 30, tz)
        steps.append(step("tool", "Schedule the probation review", f"{d.isoformat()} 15:00, 30 min",
                          tool="calendar_create_event",
                          args={"summary": f"Probation review: {name}", "start": start, "end": end, "timezone": tz,
                                "attendees": [], "description": f"Probation review for {name} "
                                                                f"({emp.get('job_title', '')}).",
                                "add_meet": False, "notify_attendees": False},
                          task=["onboarding", "probation_review"]))
    if options.get("whatsapp", True) and emp.get("phone"):
        steps.append(step("tool", "Send a WhatsApp welcome", f"To {emp['phone']}", tool="whatsapp_send",
                          args={"to": emp["phone"], "body": f"Welcome to {pol['company']['name'] or 'the team'}, "
                                f"{name.split()[0] if name else ''}! We look forward to seeing you on "
                                f"{join.strftime('%d %B') if join else 'your first day'} at "
                                f"{pol['work']['office_start']}. Your welcome letter has been emailed to you."},
                          task=["onboarding", "whatsapp"]))
    sh = sheet_step(db, "new_joiners", {**emp, "status": "onboarding", "recorded_on": date.today()},
                    title="Record the new joiner in your HR sheet", task=("onboarding", "record"))
    if sh:
        steps.append(sh)
    return steps


def portal_department(d: str) -> str:
    allowed = ("Finance", "HR", "IT", "Operations", "Sales", "Marketing", "Engineering", "Administration")
    for a in allowed:
        if a.lower() == (d or "").strip().lower():
            return a
    low = (d or "").lower()
    if any(w in low for w in ("develop", "software", "tech", "engineer")):
        return "Engineering"
    if "human" in low or "people" in low:
        return "HR"
    if "account" in low:
        return "Finance"
    if "admin" in low:
        return "Administration"
    return "Operations"


def portal_employment_type(t: str) -> str:
    t = (t or "").lower()
    if "part" in t:
        return "part_time"
    if "contract" in t:
        return "contract"
    if "intern" in t:
        return "intern"
    return "full_time"


def letter_steps(db: Session, kind: str, emp: dict[str, Any], *, fields: dict[str, Any], email: bool,
                 existing_id: int | None, create_status: str = "offered") -> list[dict[str, Any]]:
    from .letters import KINDS

    pol = S.get_policy(db)
    name = emp.get("full_name", "")
    steps: list[dict[str, Any]] = []
    if existing_id is None:
        steps.append(step("core", "Record the employee", f"{name}, {emp.get('job_title', '')}, status {create_status}",
                          op="create_employee", params={**emp, "status": create_status,
                                                        "offer_date": date.today().isoformat()
                                                        if kind == "offer" else None}))
    elif kind == "offer":
        steps.append(step("core", "Update the record", "Offer details saved", op="update_employee",
                          params={k: v for k, v in emp.items() if k in ("job_title", "department", "monthly_salary",
                                                                        "joining_date", "manager", "email", "phone")}
                          | {"offer_date": date.today().isoformat()}))
    task = {"offer": ["onboarding", "offer_letter"], "contract": ["onboarding", "contract"],
            "resignation_acceptance": ["separation", "resignation_letter"],
            "final_settlement": ["separation", "final_letter"]}.get(kind)
    steps.append(step("core", f"Generate the {KINDS[kind].lower()} (Word and PDF)", _letter_summary(kind, emp, fields,
                                                                                                    pol),
                      op="letter", params={"kind": kind, "fields": fields}, task=task if not email else None))
    if email and emp.get("email"):
        subj = {"offer": f"Offer of employment: {emp.get('job_title', '')}",
                "contract": "Your employment contract", "welcome": "Welcome aboard",
                "conduct": "Letter from HR", "resignation_acceptance": "Acceptance of your resignation",
                "final_settlement": "Your full and final settlement", "experience": "Your experience certificate"}[kind]
        steps.append(step("tool", "Email the letter", f"To {emp['email']}, PDF attached", tool="gmail_send_email",
                          args={"to": ["{{employee.email}}"], "subject": subj,
                                "body": f"Dear {name.split()[0] if name else ''},\n\nPlease find attached your "
                                        f"{KINDS[kind].lower()}.\n\nBest regards,\n"
                                        f"{pol['company']['signatory_name'] or 'HR'}\n{pol['company']['name']}",
                                "attachments": ["{{letter." + kind + ".pdf}}"]},
                          task=task, on_ok="letter_sent:" + kind))
    return steps


def _letter_summary(kind: str, emp: dict[str, Any], fields: dict[str, Any], pol: dict[str, Any]) -> str:
    from .letters import fmt_date, fmt_money

    cur = emp.get("currency") or pol["payroll"]["currency"]
    if kind == "offer":
        return (f"{emp.get('job_title', '')}, {fmt_money(emp.get('monthly_salary'), cur)} a month, joining "
                f"{fmt_date(emp.get('joining_date'))}, valid until {fmt_date(fields.get('offer_valid_until'))}")
    if kind == "conduct":
        return f"Issue: {fields.get('issue') or '-'}"
    if kind == "final_settlement":
        s = fields.get("settlement") or {}
        return f"Net payable {fmt_money(s.get('net_payable'), s.get('currency', cur))}"
    if kind == "resignation_acceptance":
        return f"Last working day {fmt_date(emp.get('last_working_day'))}"
    return emp.get("full_name", "")


def separation_steps(db: Session, e: Employee, *, kind: str, last_day: date, notice_date: date | None, reason: str,
                     tz: str, email: bool, requester: tuple[str, str]) -> list[dict[str, Any]]:
    name = e.full_name
    steps = [step("core", "Start the separation", f"{name}: {kind}, last working day {last_day.isoformat()}",
                  op="start_separation", params={"kind": kind, "last_working_day": last_day.isoformat(),
                                                 "notice_date": notice_date.isoformat() if notice_date else None,
                                                 "reason": reason})]
    emp = S.employee_dict(e) | {"last_working_day": last_day.isoformat()}
    if kind == "resignation":
        steps += letter_steps(db, "resignation_acceptance", emp, fields={"notice_date": notice_date or date.today(),
                                                                        "last_working_day": last_day},
                              email=email, existing_id=e.id)
    steps.append(step("tool", "Ask IT to collect assets and remove access on the last day",
                      f"IT Helpdesk ticket for {last_day.isoformat()}", tool="it_create_ticket", agent="it",
                      args={"requester_name": requester[0], "requester_email": requester[1],
                            "department": "HR", "category": "account", "priority": "medium",
                            "summary": f"Leaver: {name} ({last_day.isoformat()})"[:150],
                            "description": f"{name} ({e.job_title}, {e.department}) leaves on {last_day.isoformat()}. "
                                           "Please collect the laptop, ID and access cards, and remove email and "
                                           "system access at the end of that day."},
                      task=["separation", "assets"]))
    pol = S.get_policy(db)
    d = _next_working(max(last_day - timedelta(days=2), date.today()), pol)
    start, end = _when(d, "16:00", 30, tz)
    steps.append(step("tool", "Schedule the exit interview", f"{d.isoformat()} 16:00, 30 min",
                      tool="calendar_create_event",
                      args={"summary": f"Exit interview: {name}", "start": start, "end": end, "timezone": tz,
                            "attendees": [e.email] if e.email else [], "description": "Exit interview.",
                            "add_meet": False, "notify_attendees": bool(e.email)},
                      task=["separation", "exit_interview"]))
    sh = sheet_step(db, "separations", emp | {"reason": reason, "status": "notice", "recorded_on": date.today()},
                    title="Record the separation in your HR sheet", task=("separation", "record"))
    if sh:
        steps.append(sh)
    return steps


def settlement_steps(db: Session, e: Employee, s: Separation, *, settlement: dict[str, Any], email: bool
                     ) -> list[dict[str, Any]]:
    emp = S.employee_dict(e)
    steps = [step("core", "Save the final settlement", f"Net payable {settlement['currency']} "
                  f"{settlement['net_payable']:,.2f}", op="settle", params={"settlement": settlement},
                  task=["separation", "settlement"])]
    steps += letter_steps(db, "final_settlement", emp, fields={"settlement": settlement,
                                                              "last_working_day": e.last_working_day},
                          email=email, existing_id=e.id)
    steps += letter_steps(db, "experience", emp, fields={"last_working_day": e.last_working_day}, email=email,
                          existing_id=e.id)
    if e.finance_person_id:
        month = (e.last_working_day or date.today()).strftime("%Y-%m")
        steps.append(step("tool", "Record the final payment in the Finance Portal",
                          f"{settlement['currency']} {settlement['net_payable']:,.2f} for {month}",
                          tool="payroll_record_payment",
                          args={"person_id": int(e.finance_person_id), "month": month,
                                "amount": f"{settlement['net_payable']:.2f}", "status": "pending",
                                "note": "Full and final settlement"}))
        steps.append(step("tool", "Remove from payroll in the Finance Portal", "Status inactive (records are kept)",
                          tool="payroll_end_employment",
                          args={"person_id": int(e.finance_person_id), "note": f"Left on {e.last_working_day}"},
                          task=["separation", "payroll_exit"]))
    steps.append(step("core", "Close the separation", "Employee status separated", op="close_separation", params={}))
    return steps


def payroll_steps(db: Session, run: PayrollRun) -> list[dict[str, Any]]:
    steps = [step("core", "Approve the payroll run", f"{run.month}: {len(run.lines)} employee(s)",
                  op="payroll_status", params={"month": run.month, "status": "approved"})]
    missing = []
    for ln in run.lines:
        e = db.get(Employee, ln["employee_id"])
        if e is None:
            continue
        if not e.finance_person_id:
            missing.append(e.full_name)
            continue
        steps.append(step("tool", f"Pay {e.full_name}", f"{ln['currency']} {ln['net']:,.2f} net for {run.month}",
                          tool="payroll_record_payment",
                          args={"person_id": int(e.finance_person_id), "month": run.month, "amount": f"{ln['net']:.2f}",
                                "status": "pending", "note": f"AgentsMind payroll {run.month}"}))
    steps.append(step("core", "Mark the payroll posted", run.month, op="payroll_status",
                      params={"month": run.month, "status": "posted"}))
    sh_rows = [[ln["code"], ln["name"], ln["department"], run.month, ln["gross"], ln["leave_deduction"] + ln["proration"],
                ln["eobi"], ln["tax"], ln["net"]] for ln in run.lines]
    sh = db.scalar(select(HRSheet).where(HRSheet.purpose == "payroll", HRSheet.auto_record.is_(True)))
    if sh is not None and sh_rows:
        hdr = sh.headers or []
        if hdr:
            rows = [sheet_row(hdr, {"code": r[0], "full_name": r[1], "department": r[2], "recorded_on": r[3],
                                    "monthly_salary": r[8]}) for r in sh_rows]
        else:
            rows = sh_rows
        steps.append(step("tool", f"Record the payroll in '{sh.name}'", f"{len(rows)} row(s)", tool="sheets_append",
                          args={"source": sh.source, "location": sh.location, "tab": sh.tab or None, "rows": rows}))
    if missing:
        steps[0]["summary"] += f". Not in the Finance Portal yet (no payment recorded): {', '.join(missing)}"
    return steps


# ---------------------------------------------------------------------------- execution

def _resolve(v: Any, ctx: dict[str, Any]) -> Any:
    if isinstance(v, str):
        whole = PLACEHOLDER.fullmatch(v.strip())
        if whole:
            return _lookup(ctx, *whole.groups())
        return PLACEHOLDER.sub(lambda m: str(_lookup(ctx, *m.groups()) or ""), v)
    if isinstance(v, list):
        return [_resolve(x, ctx) for x in v]
    if isinstance(v, dict):
        return {k: _resolve(x, ctx) for k, x in v.items()}
    return v


def _lookup(ctx: dict[str, Any], a: str, b: str, c: str | None) -> Any:
    if a == "employee":
        e = ctx.get("employee")
        return getattr(e, b, "") if e is not None else ""
    if a == "letter":
        lt = ctx.get("letters", {}).get(b)
        if lt is None:
            raise LookupError(f"The {b.replace('_', ' ')} letter was not generated.")
        return lt.pdf_path if c in (None, "pdf") else lt.docx_path
    return ""


def _key(base: str, i: int) -> str:
    return hashlib.sha256(f"{base}|{i}".encode()).hexdigest()[:24]


def run(db: Session, args: dict[str, Any], key: str) -> dict[str, Any]:
    """Execute an approved workflow (the hr_run_workflow tool)."""
    from ..agents.gateway import call_tool
    from ..assistant.results import describe

    actor = db.get(User, int(args.get("_actor") or 0))
    if actor is None:
        raise RuntimeError("The approving user no longer exists.")
    ctx: dict[str, Any] = {"letters": {}, "employee": None}
    if args.get("employee_id"):
        ctx["employee"] = db.get(Employee, int(args["employee_id"]))
    if args.get("candidate_id"):
        ctx["candidate"] = db.get(Candidate, int(args["candidate_id"]))
    results = []
    for i, st in enumerate(args.get("steps", [])):
        entry = {"title": st.get("title", ""), "status": "ok", "summary": "", "error": ""}
        task_ref = st.get("task")
        try:
            if st["kind"] == "core":
                entry["summary"] = _core(db, st["op"], _resolve(st.get("params", {}), ctx), ctx, actor, key, i)
            else:
                targs = _resolve(st.get("args", {}), ctx)
                o = call_tool(db, agent=st.get("agent", "hr"), tool=st["tool"], args=targs, user=actor, direct=True,
                              request_key=_key(key, i), summary=st.get("title", ""))
                if o.status != "ok":
                    raise RuntimeError(o.error or o.status)
                entry["summary"] = describe(st["tool"], o.result).get("body", "")[:400]
                _on_ok(db, st.get("on_ok"), o.result, ctx)
                entry["result"] = {k: v for k, v in o.result.items() if k in ("number", "confirmation_url",
                                                                              "html_link", "web_link", "sid")}
        except Exception as exc:  # noqa: BLE001 - one failed step must not stop the rest
            log.warning("workflow step failed", extra={"step": st.get("title"), "error": str(exc)})
            entry.update(status="failed", error=str(exc)[:500])
        _mark_task(db, ctx, task_ref, entry, st)
        results.append(entry)
    e = ctx.get("employee")
    ok = sum(1 for r in results if r["status"] == "ok")
    return {"workflow": args.get("workflow", ""), "title": args.get("title", ""), "employee_id": e.id if e else None,
            "employee_code": e.code if e else "", "steps": results, "ok": ok, "failed": len(results) - ok,
            "letters": {k: {"id": v.id, "title": v.title} for k, v in ctx["letters"].items()}}


def _mark_task(db: Session, ctx: dict[str, Any], task_ref: list[str] | None, entry: dict[str, Any],
               st: dict[str, Any]) -> None:
    e = ctx.get("employee")
    if not task_ref or e is None:
        return
    t = S.task_by_key(db, e.id, task_ref[0], task_ref[1])
    if t is None:
        return
    if entry["status"] == "ok":
        S.set_task(db, t, "done", result={"summary": entry["summary"], **entry.get("result", {})},
                   tool=st.get("tool", st.get("op", "")))
    else:
        S.set_task(db, t, "failed", result={"error": entry["error"], "step": st}, tool=st.get("tool", st.get("op", "")))


def _on_ok(db: Session, what: str | None, result: dict[str, Any], ctx: dict[str, Any]) -> None:
    e = ctx.get("employee")
    if not what or e is None:
        return
    if what == "save_finance_id":
        pid = (result.get("person") or {}).get("id")
        if pid:
            e.finance_person_id = str(pid)
            db.commit()
    elif what.startswith("letter_sent:"):
        lt = ctx["letters"].get(what.split(":", 1)[1])
        if lt is not None:
            from ..db.base import utcnow

            lt.status, lt.sent_at = "sent", utcnow()
            db.commit()


def _core(db: Session, op: str, p: dict[str, Any], ctx: dict[str, Any], actor: User, key: str, i: int) -> str:
    e: Employee | None = ctx.get("employee")
    if op == "create_employee":
        data = {k: v for k, v in p.items() if v is not None}
        if ctx.get("candidate") is not None:
            data.setdefault("candidate_id", ctx["candidate"].id)
        e = S.create_employee(db, data, actor)
        ctx["employee"] = e
        return f"{e.code} {e.full_name} recorded ({e.status})"
    if op == "payroll_status":
        run_ = db.scalar(select(PayrollRun).where(PayrollRun.month == p["month"]))
        if run_ is None:
            raise RuntimeError(f"No payroll run for {p['month']}.")
        run_.status = p["status"]
        db.commit()
        return f"Payroll {run_.month} {run_.status}"
    if op == "attendance_import":
        n = 0
        for r in p.get("rows", []):
            emp = db.get(Employee, int(r["employee_id"]))
            if emp is None:
                continue
            S.mark_attendance(db, emp, S._date(r["day"]), r["status"], check_in=r.get("check_in", ""),
                              check_out=r.get("check_out", ""), source=r.get("source", "sheet"))
            n += 1
        return f"{n} attendance record(s) saved"
    if op == "leave_decision":
        r = db.get(LeaveRequest, int(p["leave_id"]))
        if r is None:
            raise RuntimeError("Leave request not found.")
        S.decide_leave(db, r, bool(p["approve"]), actor)
        return f"Leave #{r.id} {r.status}"
    if e is None:
        raise RuntimeError("No employee for this step.")
    if op == "update_employee":
        S.update_employee(db, e, {k: v for k, v in p.items() if v is not None}, actor)
        return f"{e.code} updated"
    if op == "checklists":
        n = 0
        for proc in p.get("processes", []):
            base = e.joining_date if proc != "separation" else e.last_working_day
            n += len(S.create_checklist(db, e, proc, base))
        return f"{n} checklist item(s)"
    if op == "letter":
        kind = p["kind"]
        wk = f"{key}|{i}"
        prior = next((lt for lt in db.scalars(select(HRLetter).where(HRLetter.employee_id == e.id,
                                                                    HRLetter.kind == kind))
                      if (lt.fields or {}).get("workflow_key") == wk), None)
        if prior is None:
            fields = dict(p.get("fields") or {})
            fields["workflow_key"] = wk
            prior = S.create_letter(db, kind, fields, employee=e, candidate=ctx.get("candidate"), user=actor)
        ctx["letters"][kind] = prior
        return f"{prior.title} (letter #{prior.id})"
    if op == "start_separation":
        s = S.start_separation(db, e, kind=p.get("kind", "resignation"), last_day=S._date(p["last_working_day"]),
                               notice_date=S._date(p.get("notice_date")), reason=p.get("reason", ""), user=actor)
        ctx["separation"] = s
        return f"Separation #{s.id}, last day {s.last_working_day}"
    if op == "settle":
        s = db.scalar(select(Separation).where(Separation.employee_id == e.id, Separation.status != "closed"))
        if s is None:
            raise RuntimeError("No open separation for this employee.")
        s.settlement, s.status = p["settlement"], "settled"
        db.commit()
        return f"Settlement saved: {p['settlement']['currency']} {p['settlement']['net_payable']:,.2f}"
    if op == "close_separation":
        s = db.scalar(select(Separation).where(Separation.employee_id == e.id, Separation.status != "closed"))
        if s is not None:
            s.status = "closed"
        e.status = "separated"
        db.commit()
        return f"{e.full_name} is now separated"
    raise RuntimeError(f"Unknown step '{op}'.")
