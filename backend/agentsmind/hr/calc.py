"""HR arithmetic, done in code (a language model never computes pay, days or balances).

Pure functions with no database or network access, unit tested in tests/hr/test_calc.py.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]
_MON = {m: i + 1 for i, m in enumerate(MONTHS)} | {m[:3]: i + 1 for i, m in enumerate(MONTHS)} | {"sept": 9}
_MON_RE = "|".join(sorted(_MON, key=len, reverse=True))


def money(x: float) -> float:
    return round(float(x) + 1e-9, 2)


# ---------------------------------------------------------------------------- days

def is_working_day(d: date, weekend: list[int], holidays: set[date]) -> bool:
    return d.weekday() not in weekend and d not in holidays


def working_days(start: date, end: date, weekend: list[int], holidays: set[date] | None = None) -> int:
    if end < start:
        return 0
    hol = holidays or set()
    n, d = 0, start
    while d <= end:
        n += is_working_day(d, weekend, hol)
        d += timedelta(days=1)
    return n


def holidays_of(policy: dict[str, Any]) -> set[date]:
    out = set()
    for h in policy.get("work", {}).get("holidays", []):
        try:
            out.add(date.fromisoformat(str(h)[:10]))
        except ValueError:
            continue
    return out


def month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


# ---------------------------------------------------------------------------- periods

@dataclass(frozen=True)
class Period:
    start: date
    end: date
    label: str


def parse_period(text: str, today: date) -> Period | None:
    """'this month', 'last month', 'October', 'Oct 2026', 'this week', 'last 30 days', 'this year', 'today'."""
    t = text.lower()
    if re.search(r"\btoday\b", t):
        return Period(today, today, "today")
    if re.search(r"\byesterday\b", t):
        y = today - timedelta(days=1)
        return Period(y, y, "yesterday")
    m = re.search(r"\b(?:last|past)\s+(\d{1,3})\s+days?\b", t)
    if m:
        return Period(today - timedelta(days=int(m.group(1)) - 1), today, f"last {m.group(1)} days")
    if re.search(r"\bthis week\b", t):
        s = today - timedelta(days=today.weekday())
        return Period(s, s + timedelta(days=6), "this week")
    if re.search(r"\blast week\b", t):
        s = today - timedelta(days=today.weekday() + 7)
        return Period(s, s + timedelta(days=6), "last week")
    if re.search(r"\b(?:this|current) month\b", t):
        a, b = month_bounds(today.year, today.month)
        return Period(a, b, today.strftime("%B %Y"))
    if re.search(r"\b(?:last|previous) month\b", t):
        first = today.replace(day=1) - timedelta(days=1)
        a, b = month_bounds(first.year, first.month)
        return Period(a, b, first.strftime("%B %Y"))
    if re.search(r"\bnext month\b", t):
        nxt = month_bounds(today.year, today.month)[1] + timedelta(days=1)
        a, b = month_bounds(nxt.year, nxt.month)
        return Period(a, b, nxt.strftime("%B %Y"))
    if re.search(r"\b(?:this|current) year\b", t):
        return Period(date(today.year, 1, 1), date(today.year, 12, 31), str(today.year))
    if re.search(r"\blast year\b", t):
        return Period(date(today.year - 1, 1, 1), date(today.year - 1, 12, 31), str(today.year - 1))
    m = re.search(rf"\b({_MON_RE})\b(?:\s*,?\s*(\d{{4}}))?", t)
    if m and not re.search(rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?{m.group(1)}\b|\b{m.group(1)}\s+\d{{1,2}}\b", t):
        mon = _MON[m.group(1)]
        year = int(m.group(2)) if m.group(2) else (today.year if mon <= today.month else today.year - 1)
        a, b = month_bounds(year, mon)
        return Period(a, b, a.strftime("%B %Y"))
    m = re.search(r"\b(\d{4})-(\d{2})\b", t)
    if m and 1 <= int(m.group(2)) <= 12:
        a, b = month_bounds(int(m.group(1)), int(m.group(2)))
        return Period(a, b, a.strftime("%B %Y"))
    return None


def month_key(text: str, today: date) -> str:
    """'October', 'last month', '2026-10' -> 'YYYY-MM'; default: the current month."""
    p = parse_period(text, today)
    d = p.start if p else today
    return f"{d.year:04d}-{d.month:02d}"


# ---------------------------------------------------------------------------- leave

def prorated_entitlement(per_year: float, joining: date | None, year: int) -> float:
    """Full entitlement for staff who joined before this year; otherwise months remaining / 12, to 0.5 day."""
    if not per_year:
        return 0.0
    if joining is None or joining.year < year:
        return float(per_year)
    if joining.year > year:
        return 0.0
    months = 12 - joining.month + (1 if joining.day <= 15 else 0)
    return round(per_year * months / 12 * 2) / 2


def leave_days(start: date, end: date, policy: dict[str, Any], half_day: bool = False) -> float:
    n = working_days(start, end, policy["work"]["weekend"], holidays_of(policy))
    return 0.5 if half_day and n >= 1 and start == end else float(n)


def leave_balances(policy: dict[str, Any], joining: date | None, year: int,
                   taken: dict[str, float]) -> dict[str, dict[str, float]]:
    out = {}
    for lt, per_year in policy["leave"].items():
        if lt in ("carry_forward_annual", "encash_annual_on_exit"):
            continue
        ent = prorated_entitlement(float(per_year), joining, year)
        if lt == "annual":
            ent += float(policy["leave"].get("carry_forward_annual", 0) or 0)
        used = float(taken.get(lt, 0.0))
        out[lt] = {"entitled": ent, "taken": used, "remaining": max(ent - used, 0.0) if lt != "unpaid" else 0.0}
    return out


# ---------------------------------------------------------------------------- pay

def day_rate(gross: float, year: int, month: int, policy: dict[str, Any]) -> float:
    basis = policy["payroll"].get("days_basis", "calendar")
    if basis == "30":
        return gross / 30
    if basis == "working":
        a, b = month_bounds(year, month)
        wd = working_days(a, b, policy["work"]["weekend"], holidays_of(policy)) or 1
        return gross / wd
    return gross / calendar.monthrange(year, month)[1]


def payroll_line(*, employee: dict[str, Any], year: int, month: int, policy: dict[str, Any],
                 unpaid_leave_days: float, absent_days: float) -> dict[str, Any]:
    """One employee's pay for a month. Joiners and leavers are paid for the days they were employed."""
    a, b = month_bounds(year, month)
    basic = float(employee.get("monthly_salary") or 0)
    allowances = {k: float(v or 0) for k, v in (employee.get("allowances") or {}).items()}
    gross = basic + sum(allowances.values())
    rate = day_rate(gross, year, month, policy)
    days_in_month = calendar.monthrange(year, month)[1]
    start = max(a, _d(employee.get("joining_date")) or a)
    end = min(b, _d(employee.get("last_working_day")) or b)
    employed_days = max((end - start).days + 1, 0)
    not_employed = days_in_month - employed_days
    proration = money(not_employed * (gross / days_in_month)) if not_employed else 0.0
    deduct_absent = absent_days if policy["payroll"].get("deduct_absent_without_leave", True) else 0
    leave_deduction = money((unpaid_leave_days + deduct_absent) * rate)
    earned = max(gross - proration - leave_deduction, 0.0)
    eobi = money(float(policy["payroll"].get("eobi_employee_amount") or 0)) if employed_days else 0.0
    tax_pct = float(policy["payroll"].get("tax_withholding_percent") or 0)
    tax = money(earned * tax_pct / 100)
    net = money(earned - eobi - tax)
    return {"employee_id": employee.get("id"), "code": employee.get("code", ""), "name": employee.get("full_name", ""),
            "department": employee.get("department", ""), "basic": money(basic), "allowances": money(sum(
                allowances.values())), "gross": money(gross), "employed_days": employed_days,
            "days_in_month": days_in_month, "proration": proration, "unpaid_leave_days": unpaid_leave_days,
            "absent_days": absent_days if deduct_absent else 0, "leave_deduction": leave_deduction,
            "eobi": eobi, "tax": tax, "net": max(net, 0.0), "currency": employee.get("currency") or "PKR",
            "tax_note": "" if tax_pct else "Income tax not withheld: set the rate in HR > Settings > Payroll."}


def final_settlement(*, employee: dict[str, Any], last_day: date, policy: dict[str, Any], annual_remaining: float,
                     notice_date: date | None, unpaid_leave_days_last_month: float = 0.0,
                     other_deductions: float = 0.0, other_additions: float = 0.0) -> dict[str, Any]:
    """Final settlement breakdown: last month's salary to the last working day, leave encashment, notice
    shortfall and other items. Every line is shown so HR can check it."""
    basic = float(employee.get("monthly_salary") or 0)
    gross = basic + sum(float(v or 0) for v in (employee.get("allowances") or {}).values())
    y, m = last_day.year, last_day.month
    rate = day_rate(gross, y, m, policy)
    start = max(date(y, m, 1), _d(employee.get("joining_date")) or date(y, m, 1))
    days_worked = max((last_day - start).days + 1, 0)
    salary_due = money(days_worked * (gross / calendar.monthrange(y, m)[1]))
    unpaid = money(unpaid_leave_days_last_month * rate)
    encash = money(annual_remaining * (gross / 30)) if policy["leave"].get("encash_annual_on_exit", True) else 0.0
    notice_days = int(policy["payroll"].get("notice_days") or 0)
    served = (last_day - notice_date).days + 1 if notice_date else notice_days
    shortfall_days = max(notice_days - served, 0)
    shortfall = money(shortfall_days * (gross / 30))
    lines = [
        {"item": f"Salary for {days_worked} day(s) of {last_day.strftime('%B %Y')}", "amount": salary_due},
        {"item": f"Annual leave encashment ({annual_remaining:g} day(s) at gross / 30)", "amount": encash},
        {"item": "Other additions", "amount": money(other_additions)},
        {"item": f"Unpaid leave in the last month ({unpaid_leave_days_last_month:g} day(s))", "amount": -unpaid},
        {"item": f"Notice period shortfall ({shortfall_days} of {notice_days} day(s))", "amount": -shortfall},
        {"item": "Other deductions (advances, loans, unreturned assets)", "amount": -money(other_deductions)},
    ]
    total = money(sum(x["amount"] for x in lines))
    return {"employee": employee.get("full_name", ""), "code": employee.get("code", ""), "last_working_day":
            last_day.isoformat(), "gross_monthly": money(gross), "lines": [x for x in lines if x["amount"]],
            "net_payable": max(total, 0.0), "currency": employee.get("currency") or "PKR",
            "note": "Statutory items (gratuity, provident fund, tax) are not included unless entered as other "
                    "additions or deductions."}


def _d(v: Any) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


# ---------------------------------------------------------------------------- recruitment

def location_match(cv_text: str, rec: dict[str, Any]) -> tuple[bool | None, str]:
    """True when the CV places the candidate in the target city, False when it names another
    Pakistani city as home, None when no location is found."""
    low = cv_text.lower()
    names = [a.lower() for a in rec.get("city_aliases", [])] + [rec.get("candidate_city", "").lower()]
    for n in [x for x in names if x]:
        m = re.search(rf"\b{re.escape(n)}\b", low)
        if m:
            return True, cv_text[max(m.start() - 30, 0):m.end() + 30].replace("\n", " ").strip()
    for a in rec.get("areas", []):
        m = re.search(rf"\b{re.escape(a.lower())}\b", low)
        if m:
            return True, cv_text[max(m.start() - 30, 0):m.end() + 30].replace("\n", " ").strip()
    others = ("lahore", "islamabad", "rawalpindi", "faisalabad", "multan", "peshawar", "quetta", "hyderabad",
              "sukkur", "sialkot", "gujranwala", "abbottabad", "bahawalpur", "sargodha", "larkana")
    head = "\n".join(cv_text.splitlines()[:15]).lower()  # contact block at the top of a CV
    for o in others:
        if re.search(rf"\b{o}\b", head):
            return False, o.title()
    return None, ""


def next_code(existing: list[str]) -> str:
    nums = [int(m.group(1)) for c in existing if (m := re.match(r"EMP-(\d+)$", c or ""))]
    return f"EMP-{(max(nums) + 1) if nums else 1:04d}"
