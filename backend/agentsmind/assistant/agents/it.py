"""IT agent: raise complaint tickets, check their status, list them, and (IT staff) move them along."""
from __future__ import annotations

import re
from typing import Any

from ...agents import ported as P
from ...rbac import STAFF_ROLES
from ..base import Agent, Ctx, Proposal, State
from ..cards import Card, Detail
from .common import has_any

TICKET_RE = re.compile(r"\bITK-\d{6}\b", re.I)
CATEGORIES = [
    ("network", ("vpn", "wifi", "wi-fi", "internet", "network", "connection", "connect", "lan", "ethernet")),
    ("printer", ("printer", "print", "printing", "scanner", "toner")),
    ("email", ("email", "outlook", "gmail", "mailbox", "inbox")),
    ("account", ("password", "login", "log in", "sign in", "locked", "account", "access", "permission", "mfa", "2fa")),
    ("hardware", ("laptop", "computer", "pc", "keyboard", "mouse", "monitor", "screen", "battery", "charger",
                  "headset", "webcam", "hardware")),
    ("software", ("install", "software", "app", "application", "excel", "word", "crash", "crashes", "update",
                  "licence", "license", "teams", "zoom", "browser")),
]
DEPARTMENTS = ("Finance", "HR", "IT", "Operations", "Sales", "Marketing", "Engineering", "Administration")
ROLE_DEPT = {"hr": "HR", "finance": "Finance", "it": "IT"}
STATUS_WORDS = {"in progress": "in_progress", "in-progress": "in_progress", "working on": "in_progress",
                "resolved": "resolved", "fixed": "resolved", "closed": "closed", "close": "closed",
                "reopen": "open", "open": "open"}
IT_WORDS = ("ticket", "tickets", "complaint", "it support", "helpdesk", "help desk", "not working", "broken",
            "doesn't work", "does not work", "won't", "cannot connect", "can't connect", "keeps disconnecting",
            "error", "crash", "crashes", "slow", "issue", "problem", "fix")


def category_of(text: str) -> str:
    t = text.lower()
    for cat, kws in CATEGORIES:
        if any(re.search(rf"\b{re.escape(k)}\b", t) for k in kws):
            return cat
    return "other"


def priority_of(text: str) -> str:
    t = text.lower()
    if has_any(t, "urgent", "asap", "emergency", "critical", "immediately"):
        return "urgent"
    if has_any(t, "can't work", "cannot work", "unable to work", "blocked", "down", "nothing works", "high priority"):
        return "high"
    if has_any(t, "low priority", "whenever", "no rush", "not urgent"):
        return "low"
    return "medium"


def _intent(text: str, user) -> str:
    t = text.lower()
    has_no = bool(TICKET_RE.search(text))
    if has_no and user.has("it") and has_any(t, "mark", "set", "move", "change status", "resolve", "close", "reopen",
                                              "start working"):
        return "status_change"
    if has_no and has_any(t, "comment", "add a note", "reply", "tell them", "update them"):
        return "comment"
    if has_no:
        return "get"
    if has_any(t, "my tickets", "my complaints", "list tickets", "show tickets", "open tickets", "ticket list",
               "show my", "tickets"):
        if not has_any(t, "raise", "open a", "create", "log a", "file a", "report"):
            return "list"
    if has_any(t, "how do i", "how can i", "how to", "troubleshoot", "what should i try") and not has_any(
            t, "ticket", "complaint", "raise", "report"):
        return "troubleshoot"
    return "create"


class ITAgent(Agent):
    name = "it"
    title = "IT agent"
    roles = STAFF_ROLES
    examples = ("My laptop won't connect to the VPN, please raise a ticket", "What's the status of ITK-000123?",
                "Show my tickets", "Mark ITK-000123 as resolved (IT staff)")

    def score(self, text: str) -> float:
        t = text.lower()
        s = 2.0 if TICKET_RE.search(text) else 0.0
        s += sum(1.0 for w in IT_WORDS if re.search(rf"\b{re.escape(w)}\b", t))
        if category_of(t) != "other":
            s += 1.0
        return s

    def understand(self, ctx: Ctx, state: State) -> State:
        text = state["text"]
        intent = _intent(text, ctx.user)
        slots: dict[str, Any] = dict(state.get("slots") or {})
        slots["intent"] = intent
        m = TICKET_RE.search(text)
        if m:
            slots["number"] = m.group(0).upper()
        if intent == "create":
            dept = next((d for d in DEPARTMENTS if re.search(rf"\b{d}\b", text, re.I)), None) or slots.get("department")
            dept = dept or next((ROLE_DEPT[r] for r in ctx.user.roles if r in ROLE_DEPT), None)
            if len(re.sub(r"\s+", " ", text).strip()) < 15:
                return {"intent": intent, "slots": slots,
                        "question": "What is the problem? A sentence or two helps IT fix it faster."}
            if not dept:
                return {"intent": intent, "slots": slots, "question": "Which department are you in?",
                        "options": list(DEPARTMENTS)}
            slots.update(department=dept, category=category_of(text), priority=priority_of(text))
        if intent == "status_change":
            t = text.lower()
            slots["status"] = next((v for k, v in STATUS_WORDS.items() if re.search(rf"\b{k}\b", t)), None)
            if not slots["status"]:
                return {"intent": intent, "slots": slots, "question": f"Which status should {slots['number']} get?",
                        "options": ["in progress", "resolved", "closed", "reopen"]}
        if intent == "comment":
            m2 = re.search(r"(?:comment|note|reply|tell them|update them)\s*(?:to|on)?\s*(?:ITK-\d{6})?\s*[:,-]?\s*(.+)$",
                           text, re.I | re.S)
            body = (m2.group(1) if m2 else "").strip()
            body = TICKET_RE.sub("", body).strip(" :,-")
            if len(body) < 2:
                return {"intent": intent, "slots": slots, "question": "What should the comment say?"}
            slots["body"] = body[:5000]
        return {"intent": intent, "slots": slots}

    def gather(self, ctx: Ctx, state: State) -> State:
        s, text = state["slots"], state["text"]
        intent = s["intent"]
        if intent == "create":
            description = re.sub(r"\s+", " ", text).strip()
            summary = description[:80] + ("..." if len(description) > 80 else "")
            args = {"requester_name": ctx.user.name, "requester_email": ctx.user.email, "department": s["department"],
                    "category": s["category"], "priority": s["priority"], "summary": summary,
                    "description": description[:5000]}
            return {"proposals": [Proposal(
                tool="it_create_ticket", args=args, summary=f"Raise an IT complaint: {summary}",
                details=[Detail("Requester", f"{ctx.user.name} ({ctx.user.email})"), Detail("Department", s["department"]),
                         Detail("Category", s["category"]), Detail("Priority", s["priority"]),
                         Detail("Description", description[:500])])]}
        if intent == "get":
            t = self.read_or_raise(ctx, "it_get_ticket", {"number": s["number"]})
            body = (f"{t['number']} is {t['status'].replace('_', ' ')} (priority {t['priority']}, category "
                    f"{t['category']}). {t['expected_response']}")
            if t.get("sla_breached"):
                body += " The response target has been missed."
            last = (t.get("comments") or [])[-1:] or []
            if last:
                body += f" Latest comment from {last[0]['author']}: {last[0]['body'][:300]}"
            return {"cards": [Card(kind="result", agent=self.name, title=f"Ticket {t['number']}", body=body,
                                   data={"ticket": t})]}
        if intent == "list":
            st = next((v for k, v in STATUS_WORDS.items() if re.search(rf"\b{k}\b", text.lower())), None)
            args = {"page_size": 25}
            if st:
                args["status"] = st
            d = self.read_or_raise(ctx, "it_list_tickets", args)
            rows = [{"number": t["number"], "summary": t["summary"], "status": t["status"], "priority": t["priority"],
                     "created_at": t["created_at"]} for t in d["items"]]
            who = "" if ctx.user.has("it") else "your "
            return {"cards": [Card(kind="result", agent=self.name, title="IT tickets",
                                   body=f"{d['total']} {who}ticket(s)" + (f" with status {st}." if st else "."),
                                   data={"columns": ["number", "summary", "status", "priority"], "rows": rows})]}
        if intent == "status_change":
            t = self.read_or_raise(ctx, "it_get_ticket", {"number": s["number"]})
            return {"proposals": [Proposal(
                tool="it_update_ticket_status", args={"number": s["number"], "status": s["status"], "actor": ctx.user.email},
                summary=f"Change {s['number']} from {t['status']} to {s['status']}",
                details=[Detail("Ticket", f"{t['number']}: {t['summary']}"), Detail("Requester", t["requester_email"]),
                         Detail("New status", s["status"])])]}
        if intent == "comment":
            return {"proposals": [Proposal(
                tool="it_add_comment", args={"number": s["number"], "body": s["body"], "actor": ctx.user.email},
                summary=f"Add a comment to {s['number']}",
                details=[Detail("Ticket", s["number"]), Detail("Comment", s["body"][:500])])]}
        # troubleshoot: model text only, no tools; the user can then ask to raise a ticket
        r = ctx.llm.complete(P.it_troubleshoot_prompt(text, ctx.user.name), temperature=P.Temperature.IT)
        return {"cards": [Card(kind="text", agent=self.name, title="Troubleshooting steps", body=r.text,
                               simulated=r.simulated, options=["Raise an IT ticket for this"])]}
