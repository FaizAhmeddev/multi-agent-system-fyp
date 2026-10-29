"""HR agent: recruitment, offers and letters, onboarding and induction, separation and settlement,
attendance and leave, payroll, compliance, reports, and the HR's own sheets.

Every employee can use the self-service part (check in and out, apply for leave, own leave
balance and policy questions). Everything else needs the HR role; that is checked here in
code before any record is read, in addition to the tool gateway's own role checks.
"""
from __future__ import annotations

import re
from typing import Any

from ....hr.policy import HRError
from ....rbac import STAFF_ROLES
from ...base import Agent, AgentError, Ctx, State
from ...cards import Card
from . import handlers as H
from . import parse as P


class HRAgent(Agent):
    name = "hr"
    title = "HR agent"
    roles = STAFF_ROLES  # self-service for everyone; HR-only intents are checked in understand()
    examples = ("Screen CVs from Gmail for the Python Developer role (Karachi only)",
                "Onboard Sara Khan as Python Developer joining 1 December, salary 150,000, email sara@example.com",
                "Issue an offer letter to Sara Khan", "Ahmed Raza resigned, last working day 30 November",
                "Final settlement for Ahmed Raza", "New joiners report for this month", "Run payroll for October",
                "Apply for casual leave on 5 November", "Check in", "Where do I keep the leave records?")

    def score(self, text: str) -> float:
        t = text.lower()
        s = sum(1.5 for w in P.HR_WORDS if re.search(rf"\b{re.escape(w)}\b", t))
        if re.search(r"\bEMP-\d{4,}\b", text, re.I):
            s += 2.0
        return s

    def understand(self, ctx: Ctx, state: State) -> State:
        text = state["text"]
        slots: dict[str, Any] = dict(state.get("slots") or {})
        if slots.get("intent"):  # a clarification answer: keep the first intent
            intent = slots["intent"]
            _, more, how = P.parse(None, text, ctx.now.date())
            slots.update({k: v for k, v in more.items() if v})
        else:
            intent, parsed, how = P.parse(ctx.llm, text, ctx.now.date())
            slots.update(parsed)
        slots.update(intent=intent, parsed_by=how)
        if intent in P.HR_ONLY and not ctx.user.has("hr"):
            note = getattr(ctx, "note_denied", None)
            if note is not None:
                note(self.name, text)
            slots["denied"] = True
        return {"intent": intent, "slots": slots}

    def gather(self, ctx: Ctx, state: State) -> State:
        s = state["slots"]
        intent = s["intent"]
        text = state["text"]
        if s.get("denied"):
            return {"cards": [Card(kind="denied", agent=self.name, title="HR is not available to your role",
                                   body="This HR action needs the HR role. You can check in, apply for leave, see "
                                        "your leave balance and ask HR policy questions.")]}
        try:
            out = self._dispatch(ctx, intent, text, s)
        except HRError as exc:
            raise AgentError(str(exc)) from exc
        if out.get("question"):
            return {"question": out["question"], "options": out.get("options", [])}
        res: State = {"cards": out.get("cards", [])}
        if out.get("proposals"):
            res["proposals"] = out["proposals"]
        return res

    @staticmethod
    def _dispatch(ctx: Ctx, intent: str, text: str, s: dict[str, Any]) -> dict[str, Any]:
        if intent == "screen":
            return H.h_screen(ctx, text, s)
        if intent == "create_job":
            return H.h_create_job(ctx, text, s)
        if intent in ("job_description", "interview_questions"):
            return H.h_llm_text(ctx, text, s, intent)
        if intent in H.LETTER_INTENT:
            return H.h_letter(ctx, text, s, intent)
        if intent == "onboard":
            return H.h_onboard(ctx, text, s)
        if intent == "induction_plan":
            return H.h_onboard(ctx, text, s, induction_only=True)
        if intent == "separation":
            return H.h_separation(ctx, text, s)
        if intent == "final_settlement":
            return H.h_settlement(ctx, text, s)
        if intent == "check_in":
            return H.h_check_in(ctx, text, s)
        if intent == "attendance_mark":
            return H.h_attendance_mark(ctx, text, s)
        if intent == "attendance_import":
            return H.h_attendance_import(ctx, text, s)
        if intent == "leave_apply":
            return H.h_leave_apply(ctx, text, s)
        if intent == "leave_decide":
            return H.h_leave_decide(ctx, text, s)
        if intent == "leave_balance":
            return H.h_leave_balance(ctx, text, s)
        if intent == "payroll_run":
            return H.h_payroll(ctx, text, s)
        if intent == "compliance":
            return H.h_compliance(ctx, text, s)
        if intent == "task_update":
            return H.h_task_update(ctx, text, s)
        if intent == "report":
            return H.h_report(ctx, text, s)
        if intent == "sheet_where":
            return H.h_sheet_where(ctx, text, s)
        if intent == "sheet_query":
            return H.h_sheet_query(ctx, text, s)
        if intent == "sheet_register":
            return H.h_sheet_register(ctx, text, s)
        if intent == "employee_lookup":
            return H.h_lookup(ctx, text, s)
        return H.h_policy(ctx, text, s)
