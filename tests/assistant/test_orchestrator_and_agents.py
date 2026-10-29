"""Orchestrator routing, multi-step plans, clarifications, RBAC and the other agents."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fakectx import FakeCtx

from agentsmind.assistant.orchestrator import plan, run_turn

ROOT = Path(__file__).resolve().parents[2]
SANDBOX = ROOT / "sandbox_data"


def kinds(cards):
    return [c.kind for c in cards]


# ---------------------------------------------------------------- routing

@pytest.mark.parametrize("text,agent", [
    ("My laptop won't connect to the VPN, please raise a ticket", "it"),
    ("What's the status of ITK-000123?", "it"),
    ("Schedule a design review tomorrow at 3 pm for 45 minutes", "calendar"),
    ("Am I free Friday afternoon?", "calendar"),
    ("Cancel Monday's review meeting", "calendar"),
    ("What is the total monthly payroll?", "finance"),
    ("Change Ahmed Raza's salary to 150,000", "finance"),
    ("Show my unread emails", "email"),
    ("Reply to Usman saying Friday 3 pm works", "email"),
    ("Summarize the leave policy", "documents"),
    ("Screen the CVs for the Python Developer role", "hr"),
])
def test_routing(text, agent):
    steps = plan(text)
    assert [s.agent for s in steps] == [agent]


def test_multi_step_plan():
    steps = plan("Raise a ticket because my printer is broken and then schedule a call with IT tomorrow at 2 pm")
    assert [s.agent for s in steps] == ["it", "calendar"]
    steps = plan("Check my inbox and summarize the expense policy")
    assert [s.agent for s in steps] == ["email", "documents"]


def test_no_match_gives_fallback(tmp_path):
    r = run_turn(FakeCtx(tmp_path), "What is the weather like on Mars?")
    assert kinds(r.cards) == ["fallback"] and r.planner == "fallback"
    assert all("Finance" not in line for line in r.cards[0].data["capabilities"])  # employee: no finance offered


# ---------------------------------------------------------------- RBAC

def test_employee_denied_finance_and_hr(tmp_path):
    ctx = FakeCtx(tmp_path, roles=("employee",))
    r = run_turn(ctx, "What is the total monthly payroll?")
    assert kinds(r.cards) == ["denied"] and not ctx.reads
    r = run_turn(ctx, "Screen the CVs for the Python Developer role")
    assert kinds(r.cards) == ["denied"]


def test_hr_agent_cannot_call_finance_tool_even_if_asked(tmp_path):
    from agentsmind.assistant.base import Agent, run_agent

    class Rogue(Agent):
        name, title = "hr", "HR agent"

        def understand(self, ctx, state):
            return {"slots": {}}

        def gather(self, ctx, state):
            self.read_or_raise(ctx, "finance_summary", {})
            return {}

    ctx = FakeCtx(tmp_path, roles=("hr", "finance"))
    cards = run_agent(Rogue(), ctx, "anything")
    assert kinds(cards) == ["error"] and "not allowed to use finance_summary" in cards[0].body
    assert ctx.denied == [("hr", "finance_summary")]


# ---------------------------------------------------------------- clarification round trip

def test_clarification_then_answer(tmp_path):
    ctx = FakeCtx(tmp_path)
    r1 = run_turn(ctx, "Schedule a meeting with the finance team")
    assert kinds(r1.cards) == ["clarify"] and r1.pending["agent"] == "calendar"
    r2 = run_turn(ctx, "tomorrow at 11 am", pending=r1.pending)
    assert kinds(r2.cards) == ["approval"] and r2.planner == "clarification"
    assert ctx.approvals[0]["args"]["start"] == "2026-10-29T11:00:00+05:00"


# ---------------------------------------------------------------- IT

def fake_ticket(number="ITK-000123", requester="sana.employee@example.com", status="open"):
    return {"number": number, "requester_name": "Sana", "requester_email": requester, "department": "Sales",
            "category": "network", "priority": "medium", "summary": "VPN drops", "description": "VPN drops often",
            "status": status, "assignee": "", "source": "agent", "sla_due_at": "2026-10-28T19:00:00+05:00",
            "sla_breached": False, "expected_response": "IT will respond within 8 hours.",
            "created_at": "2026-10-28T11:00:00+05:00", "updated_at": "2026-10-28T11:00:00+05:00", "comments": []}


def test_it_ticket_create_asks_department_for_employee_then_proposes(tmp_path):
    ctx = FakeCtx(tmp_path)
    r = run_turn(ctx, "My laptop keeps disconnecting from the VPN, please raise a ticket")
    assert kinds(r.cards) == ["clarify"] and "department" in r.cards[0].body
    r = run_turn(ctx, "Sales", pending=r.pending)
    assert kinds(r.cards) == ["approval"]
    a = ctx.approvals[0]["args"]
    assert a["category"] == "network" and a["department"] == "Sales" and a["requester_email"] == ctx.user.email


def test_it_role_department_and_urgent_priority(tmp_path):
    ctx = FakeCtx(tmp_path, roles=("hr",))
    run_turn(ctx, "Urgent: the printer on floor 2 is broken, raise a complaint")
    a = ctx.approvals[0]["args"]
    assert a["department"] == "HR" and a["category"] == "printer" and a["priority"] == "urgent"


def test_it_status_and_staff_status_change(tmp_path):
    ctx = FakeCtx(tmp_path, tools={"it_get_ticket": lambda a: fake_ticket(a["number"])})
    r = run_turn(ctx, "What's the status of ITK-000123?")
    assert kinds(r.cards) == ["result"] and "open" in r.cards[0].body
    staff = FakeCtx(tmp_path, roles=("it",), tools={"it_get_ticket": lambda a: fake_ticket(a["number"])})
    r = run_turn(staff, "Mark ITK-000123 as resolved")
    assert kinds(r.cards) == ["approval"] and staff.approvals[0]["args"]["status"] == "resolved"
    # an employee saying the same thing only gets the status, never a status change
    r = run_turn(ctx, "Mark ITK-000123 as resolved")
    assert kinds(r.cards) == ["result"] and not ctx.approvals


# ---------------------------------------------------------------- Finance

PEOPLE = [{"id": 3, "full_name": "Ahmed Raza", "email": "ahmed.raza@example.com", "department": "Finance",
           "job_title": "Accountant", "employment_type": "full_time", "monthly_salary": "120000.00", "currency": "PKR",
           "status": "active"}]


def fin_tools():
    return {
        "finance_search_people": lambda a: {"items": [p for p in PEOPLE if a["query"].lower() in p["full_name"].lower()],
                                            "total": 1, "page": 1, "page_size": 10, "pages": 1},
        "finance_summary": lambda a: {"people_total": 14, "people_active": 12, "people_inactive": 2,
                                      "payroll_by_currency": [{"currency": "PKR", "active_people": 12,
                                                               "total_monthly_payroll": "1830000.00"}],
                                      "payroll_by_department": [], "payments_by_status": [],
                                      "computed_by": "SQL in the Finance Portal"},
    }


def test_finance_summary_numbers_come_from_tool(tmp_path):
    ctx = FakeCtx(tmp_path, roles=("finance",), tools=fin_tools())
    r = run_turn(ctx, "What is the total monthly payroll?")
    assert "PKR 1830000.00 for 12 active people" in r.cards[0].body


def test_finance_update_salary_and_delete_needs_confirm(tmp_path):
    ctx = FakeCtx(tmp_path, roles=("finance",), tools=fin_tools())
    r = run_turn(ctx, "Change Ahmed Raza's salary to 150,000")
    assert kinds(r.cards) == ["approval"]
    assert ctx.approvals[0]["args"] == {"person_id": 3, "monthly_salary": "150000.00", "actor": ctx.user.email}
    r = run_turn(ctx, "Delete the record for Ahmed Raza")
    assert r.cards[0].approval.risk == "destructive" and r.cards[0].approval.confirm_text == "Ahmed Raza"


def test_money_parsing():
    from agentsmind.assistant.agents.finance import money
    assert money("150,000") == "150000.00" and money("150k") == "150000.00" and money("1.5 lakh") == "150000.00"
    assert money("PKR 99.5") == "99.50" and money("nothing") is None


# ---------------------------------------------------------------- Email (sandbox inbox)

def inbox_tool(tmp_path, monkeypatch):
    from mcp_servers.workspace_mcp.backends import SandboxMail
    monkeypatch.setenv("WORKSPACE_DATA_DIR", str(tmp_path))
    mail = SandboxMail()

    def read(a):
        items, nxt = mail.inbox(a.get("max_results", 10), a.get("unread_only", False), a.get("query"), None)
        return {"items": [i.__dict__ for i in items], "next_page_token": nxt, "untrusted": True, "mode": "sandbox",
                "simulated": True}
    return {"gmail_read_inbox": read}


def test_email_read_flags_hostile_message(tmp_path, monkeypatch):
    ctx = FakeCtx(tmp_path, tools=inbox_tool(tmp_path, monkeypatch))
    r = run_turn(ctx, "Show my unread emails")
    c = r.cards[0]
    assert c.kind == "result" and c.untrusted and len(c.data["rows"]) == 4
    assert any(row["suspicious"] for row in c.data["rows"]) and "ACTION REQUIRED" in c.warnings[0]


def test_email_reply_recipient_from_header(tmp_path, monkeypatch):
    ctx = FakeCtx(tmp_path, tools=inbox_tool(tmp_path, monkeypatch))
    r = run_turn(ctx, "Reply to Usman saying Friday at 3 pm works for me")
    assert kinds(r.cards) == ["approval"]
    a = ctx.approvals[0]["args"]
    assert a["to"] == ["usman.tariq@example.com"] and a["subject"] == "Re: Quick catch-up this week?"
    assert "Friday at 3 pm works for me." in a["body"] and a["body"].startswith("Hi Usman,")


def test_hostile_email_cannot_trigger_actions(tmp_path, monkeypatch):
    """Acceptance: the hostile email asks for payroll export, a delete and passwords. Only reply drafts result."""
    ctx = FakeCtx(tmp_path, roles=("finance", "hr"), tools={**inbox_tool(tmp_path, monkeypatch), **fin_tools()})
    r = run_turn(ctx, "Draft replies to my unread emails")
    tools = {a["tool"] for a in ctx.approvals}
    assert tools == {"gmail_send_email"}
    hostile = [a for a in ctx.approvals if "security-alerts" in a["args"]["to"][0]]
    assert len(hostile) == 1
    assert hostile[0]["args"]["to"] == ["it-support@security-alerts.example.net"]  # the sender, not the payroll address
    assert "password" not in hostile[0]["args"]["body"].lower() and "payroll" not in hostile[0]["args"]["body"].lower()
    card = next(c for c in r.cards if c.kind == "approval" and "security-alerts" in c.approval.summary)
    assert any("addressed to an AI" in w for w in card.warnings)
    assert not [t for t, _ in ctx.reads if t.startswith("finance_")]


def test_send_needs_explicit_address(tmp_path, monkeypatch):
    ctx = FakeCtx(tmp_path, tools=inbox_tool(tmp_path, monkeypatch))
    r = run_turn(ctx, "Send an email to Hina about the VPN fix saying it is resolved")
    assert kinds(r.cards) == ["clarify"]
    r = run_turn(ctx, "Send an email to hina.malik@example.com about the VPN fix saying it is resolved now")
    assert kinds(r.cards) == ["approval"] and ctx.approvals[0]["args"]["to"] == ["hina.malik@example.com"]


# ---------------------------------------------------------------- Documents and HR (sandbox drive)

def drive_tools():
    from mcp_servers.workspace_mcp.backends import SandboxDrive
    d = SandboxDrive()

    def lst(a):
        items, nxt = d.list(a.get("folder"), a.get("page_size", 25), None)
        return {"items": [i.__dict__ for i in items], "next_page_token": nxt, "mode": "sandbox", "simulated": True}

    def search(a):
        return {"items": [i.__dict__ for i in d.search(a["query"], a.get("page_size", 10))], "mode": "sandbox",
                "simulated": True}

    def read(a):
        t = d.read(a["file_id"])
        return {"file": t.file.__dict__, "text": t.text, "truncated": t.truncated, "extracted_from": t.extracted_from,
                "untrusted": True, "mode": "sandbox", "simulated": True}
    return {"drive_list_files": lst, "drive_search": search, "drive_read_file": read}


def test_documents_summary_and_question(tmp_path):
    ctx = FakeCtx(tmp_path, roles=("hr",), tools=drive_tools())
    r = run_turn(ctx, "Summarize the leave policy")
    c = r.cards[0]
    assert c.kind == "text" and c.simulated and c.untrusted and "20 working days" in c.body
    r = run_turn(ctx, "What does the expense policy say about meals?")
    assert "PKR 3,000.00" in r.cards[0].body


def test_documents_denied_for_employee(tmp_path):
    r = run_turn(FakeCtx(tmp_path, tools=drive_tools()), "Summarize the leave policy")
    assert kinds(r.cards) == ["denied"]


def test_hr_screening_ranks_and_flags_hostile_cv(tmp_path):
    recorded = {}
    ctx = FakeCtx(tmp_path, roles=("hr",), tools=drive_tools())
    ctx.record_screening = lambda **kw: recorded.update(kw)
    r = run_turn(ctx, "Screen the CVs for the Python Developer role")
    c = r.cards[0]
    assert c.kind == "result" and c.simulated
    rows = {x["candidate"]: x for x in c.data["rows"]}
    assert set(rows) == {"Sara Khan", "Bilal Ahmed", "Alex Example"}
    assert rows["Sara Khan"]["recommendation"] == "strong match"
    assert rows["Alex Example"]["needs_human_review"] and rows["Alex Example"]["rubric_score"] == 0
    assert not ctx.approvals  # screening never emails, shortlists or rejects anyone
    assert recorded["role"] == "Python Developer" and len(recorded["rows"]) == 3
    assert json.dumps(c.data)  # serialisable for the API
