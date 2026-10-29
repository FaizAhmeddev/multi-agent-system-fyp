"""Finance agent: payroll summary, people lookup, payments, and approved changes to people records.

Numbers come only from the Finance Portal (finance_summary runs SQL there). The agent
never adds, averages or converts amounts itself and never asks a model to.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from ...agents.timeparse import MONTH_ALIASES
from ..base import Agent, AgentError, Ctx, Proposal, State
from ..cards import Card, Detail
from .common import emails, has_any

DEPARTMENTS = ("Finance", "HR", "IT", "Operations", "Sales", "Marketing", "Engineering", "Administration")
FIN_WORDS = ("payroll", "salary", "salaries", "finance", "headcount", "employees", "employee record", "people record",
             "staff record", "payments", "payment", "paid", "wages", "compensation", "person record", "people",
             "record", "records")


def money(text: str) -> str | None:
    """'150,000' -> '150000.00'; '150k' -> '150000.00'. Exact decimal arithmetic in code."""
    m = re.search(r"(?:pkr|rs\.?|usd|\$)?\s*(\d{1,3}(?:,\d{3})+|\d+)(\.\d{1,2})?\s*(k|thousand|lakh|lac)?\b", text, re.I)
    if not m:
        return None
    try:
        v = Decimal(m.group(1).replace(",", "") + (m.group(2) or ""))
    except InvalidOperation:
        return None
    unit = (m.group(3) or "").lower()
    v *= {"k": 1000, "thousand": 1000, "lakh": 100000, "lac": 100000}.get(unit, 1)
    if v <= 0 or v >= Decimal("100000000"):
        return None
    return f"{v.quantize(Decimal('0.01'))}"


def _intent(t: str) -> str:
    if has_any(t, "delete", "remove", "erase"):
        return "delete"
    if has_any(t, "add a new", "add new", "create a", "new person", "new employee", "onboard", "add .* to payroll"):
        return "create"
    if has_any(t, "update", "change", "set", "raise", "increase", "decrease", "mark .* inactive", "deactivate",
               "promote", "move .* to"):
        return "update"
    if has_any(t, "payment", "payments", "paid", "unpaid", "pending payments"):
        return "payments"
    if has_any(t, "find", "look up", "lookup", "search", "who is", "details of", "show me .* record", "record for"):
        return "search"
    return "summary"


LEAD_VERBS = {"delete", "remove", "erase", "update", "change", "set", "raise", "increase", "decrease", "promote",
              "deactivate", "find", "show", "please", "mark", "move", "who", "what", "search", "look"}


def _name(text: str) -> str | None:
    pats = [r"(?i:delete|remove|erase|update|change|set|raise|increase|decrease|promote|deactivate|find|look up|"
            r"lookup|search for|search|who is|details of|record for|record of)\s+(?i:the\s+)?(?i:record\s+(?:for|of)\s+)?"
            r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})",
            r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})(?:'s|’s)"]
    for p in pats:
        m = re.search(p, text)
        if m:
            name = re.sub(r"(?:'s|’s)$", "", m.group(1)).strip()
            parts = name.split()
            while parts and parts[0].lower() in LEAD_VERBS:
                parts.pop(0)
            name = " ".join(parts)
            if name and name.lower() not in {"the", "my", "finance", "payroll"}:
                return name
    return None


class FinanceAgent(Agent):
    name = "finance"
    title = "Finance agent"
    roles = frozenset({"finance"})
    examples = ("What is the total monthly payroll?", "Find Ahmed Raza", "Show unpaid payments for October",
                "Change Ahmed Raza's salary to 150,000", "Delete the record for Ahmed Raza")

    def score(self, text: str) -> float:
        t = text.lower()
        return sum(1.0 for w in FIN_WORDS if re.search(rf"\b{re.escape(w)}\b", t))

    def understand(self, ctx: Ctx, state: State) -> State:
        text = state["text"]
        t = text.lower()
        intent = _intent(t)
        slots: dict[str, Any] = dict(state.get("slots") or {}, intent=intent)
        if intent in ("delete", "update", "search"):
            slots["name"] = _name(text) or slots.get("name")
            if not slots["name"]:
                return {"intent": intent, "slots": slots, "question": "Whose record do you mean? Give their full name."}
        if intent == "update":
            fields: dict[str, Any] = {}
            if has_any(t, "salary", "pay", "wage"):
                amt = money(re.split(r"\bto\b", text, maxsplit=1)[-1])
                if not amt:
                    return {"intent": intent, "slots": slots, "question": "What should the new monthly salary be?"}
                fields["monthly_salary"] = amt
            dept = re.search(r"\b(?:department|dept)\s+to\s+(\w+)|\bmove .* to (\w+)\b", text, re.I)
            if dept:
                d = next((x for x in DEPARTMENTS if x.lower() == (dept.group(1) or dept.group(2)).lower()), None)
                if d:
                    fields["department"] = d
            jt = re.search(r"\b(?:job title|title|role)\s+to\s+(.+?)(?:[.,;]|$)", text, re.I)
            if jt:
                fields["job_title"] = jt.group(1).strip()[:150]
            if has_any(t, "inactive", "deactivate"):
                fields["status"] = "inactive"
            elif has_any(t, "active again", "reactivate"):
                fields["status"] = "active"
            if not fields:
                return {"intent": intent, "slots": slots,
                        "question": "What should change? For example: salary to 150,000, department to Sales, "
                                    "job title to Senior Accountant, or mark inactive."}
            slots["fields"] = fields
        if intent == "create":
            f = {"email": (emails(text) or [None])[0], "monthly_salary": money(text.split("salary", 1)[-1])
                 if "salary" in t else None,
                 "department": next((x for x in DEPARTMENTS if re.search(rf"\b{x}\b", text)), None)}
            m = re.search(r"\b(?:named|called|person|employee)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})", text)
            f["full_name"] = m.group(1) if m else None
            m = re.search(r"\bas (?:an? )?([A-Za-z ]{2,60}?)(?=\s+(?:in|with|on|from|starting|,)|[.,]|$)", text)
            f["job_title"] = m.group(1).strip().title() if m else None
            m = re.search(r"\b(?:starting|start date|from|joining)\s+(?:on\s+)?(\d{4}-\d{2}-\d{2})", text)
            f["start_date"] = m.group(1) if m else None
            missing = [k.replace("_", " ") for k, v in f.items() if not v]
            slots["fields"] = f
            if missing:
                return {"intent": intent, "slots": slots,
                        "question": "To add a person I still need: " + ", ".join(missing) + ". You can also use "
                                    "the form in Finance > People."}
        if intent == "payments":
            m = re.search(r"\b(\d{4}-\d{2})\b", text)
            month = m.group(1) if m else None
            if not month:
                mm = next((v for k, v in MONTH_ALIASES.items() if re.search(rf"\b{k}\b", t)), None)
                if mm:
                    y = ctx.now.year if mm <= ctx.now.month else ctx.now.year - 1
                    month = f"{y:04d}-{mm:02d}"
            slots["month"] = month
            slots["status"] = "pending" if has_any(t, "unpaid", "pending", "due") else (
                "paid" if has_any(t, "paid") else None)
        return {"intent": intent, "slots": slots}

    def _resolve(self, ctx: Ctx, name: str) -> dict[str, Any] | State:
        d = self.read_or_raise(ctx, "finance_search_people", {"query": name, "limit": 10})
        exact = [p for p in d["items"] if p["full_name"].lower() == name.lower()]
        items = exact or d["items"]
        if not items:
            raise AgentError(f"No person record matches '{name}'.")
        if len(items) > 1:
            return {"question": f"Several records match '{name}'. Which one?",
                    "options": [f"{p['full_name']} ({p['email']}, {p['department']})" for p in items[:5]]}
        return items[0]

    def gather(self, ctx: Ctx, state: State) -> State:
        s = state["slots"]
        intent = s["intent"]
        if intent == "summary":
            d = self.read_or_raise(ctx, "finance_summary", {})
            pay = "; ".join(f"{c['currency']} {c['total_monthly_payroll']} for {c['active_people']} active people"
                            for c in d["payroll_by_currency"]) or "no active payroll"
            body = (f"{d['people_total']} people on record ({d['people_active']} active, {d['people_inactive']} "
                    f"inactive). Total monthly payroll: {pay}.")
            rows = [{"department": x["department"], "currency": x["currency"], "active_people": x["active_people"],
                     "total_monthly_payroll": x["total_monthly_payroll"]} for x in d["payroll_by_department"]]
            return {"cards": [Card(kind="result", agent=self.name, title="Payroll summary", body=body,
                                   data={"columns": ["department", "currency", "active_people", "total_monthly_payroll"],
                                         "rows": rows, "computed_by": d["computed_by"]})]}
        if intent == "payments":
            args = {k: v for k, v in {"month": s["month"], "status": s["status"], "page_size": 50}.items() if v}
            d = self.read_or_raise(ctx, "finance_list_payments", args)
            rows = [{"person": p["person_name"], "month": p["month"], "amount": f"{p['currency']} {p['amount']}",
                     "status": p["status"]} for p in d["items"]]
            label = " ".join(x for x in (s["status"] or "", "payments", f"for {s['month']}" if s["month"] else "") if x)
            return {"cards": [Card(kind="result", agent=self.name, title=label.capitalize(),
                                   body=f"{d['total']} {label}.", data={"columns": ["person", "month", "amount", "status"],
                                                                         "rows": rows})]}
        if intent == "search":
            d = self.read_or_raise(ctx, "finance_search_people", {"query": s["name"], "limit": 10})
            rows = [{"name": p["full_name"], "email": p["email"], "department": p["department"],
                     "job_title": p["job_title"], "salary": f"{p['currency']} {p['monthly_salary']}",
                     "status": p["status"], "id": p["id"]} for p in d["items"]]
            return {"cards": [Card(kind="result", agent=self.name, title=f"People matching '{s['name']}'",
                                   body=f"{d['total']} match(es).",
                                   data={"columns": ["name", "department", "job_title", "salary", "status"],
                                         "rows": rows})]}
        if intent == "create":
            f = dict(s["fields"])
            try:
                date.fromisoformat(f["start_date"])
            except ValueError as exc:
                raise AgentError("The start date must look like 2026-12-01.") from exc
            args = {**f, "actor": ctx.user.email}
            return {"proposals": [Proposal(
                tool="finance_create_person", args=args, summary=f"Add {f['full_name']} to the Finance Portal",
                details=[Detail(k.replace("_", " ").capitalize(), str(v)) for k, v in f.items()])]}
        picked = self._resolve(ctx, s["name"])
        if "question" in picked:
            return picked
        p = picked
        if intent == "update":
            fields = s["fields"]
            changes = [Detail(k.replace("_", " ").capitalize(), f"{p.get(k, '')} -> {v}") for k, v in fields.items()]
            return {"proposals": [Proposal(
                tool="finance_update_person", args={"person_id": p["id"], **fields, "actor": ctx.user.email},
                summary=f"Update {p['full_name']}: " + ", ".join(k.replace("_", " ") for k in fields),
                details=[Detail("Person", f"{p['full_name']} ({p['email']})"), *changes])]}
        return {"proposals": [Proposal(
            tool="finance_delete_person", args={"person_id": p["id"], "actor": ctx.user.email},
            summary=f"Permanently delete {p['full_name']} and their payment records",
            details=[Detail("Person", f"{p['full_name']} ({p['email']})"), Detail("Department", p["department"]),
                     Detail("Job title", p["job_title"])],
            warnings=["This cannot be undone. Payment records for this person are deleted too."],
            confirm_text=p["full_name"])]}
