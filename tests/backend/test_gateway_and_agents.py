"""Tool gateway (allow-lists, roles, approvals, logging), departments, and agent runs via the queue."""
from __future__ import annotations

import pytest
from bhelpers import auth_header, login
from sqlalchemy import select

PW = "Plenty-Long-Passw0rd"


@pytest.fixture
def users(make_user, client):
    out = {}
    for name, roles in (("hr", ["hr"]), ("fin", ["finance"]), ("it", ["it"]), ("emp", ["employee"])):
        u = make_user(f"{name}.user@example.com", roles)
        out[name] = {"id": u["id"], "token": login(client, email=u["email"], password=PW).json()["access_token"]}
    return out


def _user(db, uid):
    from agentsmind.db.models import User

    db.expire_all()
    return db.get(User, uid)


@pytest.fixture(autouse=True)
def _clean_executors():
    from agentsmind.agents import gateway

    saved = dict(gateway.EXECUTORS)
    yield
    gateway.EXECUTORS.clear()
    gateway.EXECUTORS.update(saved)


# ── gateway ──────────────────────────────────────────────────────────────────

def test_hr_agent_cannot_call_finance_tool_denied_and_logged(db, users):
    """Acceptance scenario 2, tool half: enforced in code, logged in tool_calls and audit_logs."""
    from agentsmind.agents.gateway import call_tool
    from agentsmind.db.models import AuditLog, ToolCall

    hr = _user(db, users["hr"]["id"])
    out = call_tool(db, agent="hr", tool="finance_create_person", args={"full_name": "Ayesha Khan"}, user=hr)
    assert out.status == "denied" and out.code == "not_allowed_for_agent"
    db.expire_all()
    call = db.scalars(select(ToolCall)).one()
    assert (call.agent, call.tool, call.status, call.user_id) == ("hr", "finance_create_person", "denied", hr.id)
    assert db.scalars(select(AuditLog).where(AuditLog.action == "tool.denied")).one().target_id == "finance_create_person"


def test_even_admin_cannot_route_tool_through_wrong_agent(db, client):
    from agentsmind.agents.gateway import call_tool
    from agentsmind.db.models import User

    admin = db.scalars(select(User)).first()
    out = call_tool(db, agent="documents", tool="gmail_send_email", args={}, user=admin)
    assert out.code == "not_allowed_for_agent"


def test_role_check_applies_inside_allowed_agent(db, users):
    from agentsmind.agents.gateway import call_tool

    emp = _user(db, users["emp"]["id"])
    out = call_tool(db, agent="it", tool="it_list_tickets", args={}, user=emp)  # staff-only tool
    assert out.status == "denied" and out.code == "role_forbidden"


def test_unknown_tool_denied(db, users):
    from agentsmind.agents.gateway import call_tool

    out = call_tool(db, agent="it", tool="rm_rf", args={}, user=_user(db, users["it"]["id"]))
    assert out.code == "unknown_tool"


def test_read_tool_runs_without_approval_and_inputs_are_redacted(db, users):
    from agentsmind.agents import gateway
    from agentsmind.db.models import ToolCall

    gateway.register_executor("finance_summary", lambda args, key: {"total_monthly_payroll": 150000})
    fin = _user(db, users["fin"]["id"])
    out = gateway.call_tool(db, agent="finance", tool="finance_summary", args={"api_key": "sk-123"}, user=fin)
    assert out.status == "ok" and out.result == {"total_monthly_payroll": 150000}
    db.expire_all()
    assert db.scalars(select(ToolCall)).one().inputs_redacted == {"api_key": "***"}


def test_write_tool_needs_approval_then_runs_exactly_once(client, db, users):
    from agentsmind.agents import gateway

    calls = []
    gateway.register_executor("finance_create_person",
                              lambda args, key: calls.append((args, key)) or {"id": 7, **args})
    fin = _user(db, users["fin"]["id"])
    args = {"full_name": "Ayesha Khan", "job_title": "Accounts Officer", "monthly_salary": 150000}
    first = gateway.call_tool(db, agent="finance", tool="finance_create_person", args=args, user=fin,
                              summary="Add Ayesha Khan")
    assert first.status == "approval_required" and calls == []
    again = gateway.call_tool(db, agent="finance", tool="finance_create_person", args=args, user=fin)
    assert again.approval_id == first.approval_id  # same request, same approval card

    h = auth_header(users["fin"]["token"])
    pending = client.get("/api/approvals?status=pending", headers=h).json()
    assert pending["total"] == 1 and pending["items"][0]["arguments"] == args
    # another user cannot see or decide it
    other = auth_header(users["hr"]["token"])
    assert client.post(f"/api/approvals/{first.approval_id}/approve", json={}, headers=other).status_code == 404

    r = client.post(f"/api/approvals/{first.approval_id}/approve", json={}, headers=h)
    assert r.status_code == 200 and r.json()["outcome"]["status"] == "ok"
    assert len(calls) == 1 and calls[0][1].startswith("appr-")  # idempotency key passed to the tool
    # approving twice is refused; re-running with the approval returns the stored result, no second call
    assert client.post(f"/api/approvals/{first.approval_id}/approve", json={}, headers=h).status_code == 409
    replay = gateway.call_tool(db, agent="finance", tool="finance_create_person", args=args, user=fin,
                               approval_id=first.approval_id)
    assert replay.status == "ok" and len(calls) == 1


def test_destructive_tool_requires_explicit_confirmation(client, db, users):
    from agentsmind.agents import gateway

    gateway.register_executor("finance_delete_person", lambda args, key: {"deleted": args["person_id"]})
    fin = _user(db, users["fin"]["id"])
    out = gateway.call_tool(db, agent="finance", tool="finance_delete_person", args={"person_id": 3}, user=fin,
                            summary="Delete Ahmed Raza (person #3)")
    h = auth_header(users["fin"]["token"])
    r = client.post(f"/api/approvals/{out.approval_id}/approve", json={}, headers=h)
    assert r.status_code == 400 and "Delete Ahmed Raza (person #3)" in r.json()["detail"]["message"]
    r = client.post(f"/api/approvals/{out.approval_id}/approve", json={"confirm": True}, headers=h)
    assert r.status_code == 200 and r.json()["approval"]["status"] == "executed"


def test_rejected_approval_never_executes(client, db, users):
    from agentsmind.agents import gateway

    calls = []
    gateway.register_executor("it_create_ticket", lambda args, key: calls.append(1) or {"ticket": "ITK-1"})
    emp = _user(db, users["emp"]["id"])
    out = gateway.call_tool(db, agent="it", tool="it_create_ticket", args={"summary": "wifi"}, user=emp)
    h = auth_header(users["emp"]["token"])
    r = client.post(f"/api/approvals/{out.approval_id}/reject", json={"reason": "duplicate"}, headers=h)
    assert r.status_code == 200 and r.json()["approval"]["status"] == "rejected"
    denied = gateway.call_tool(db, agent="it", tool="it_create_ticket", args={"summary": "wifi"}, user=emp,
                               approval_id=out.approval_id)
    assert denied.status == "denied" and calls == []


def test_missing_executor_reports_unavailable(client, db, users):
    from agentsmind.agents import gateway

    gateway.EXECUTORS.pop("finance_summary", None)
    out = gateway.call_tool(db, agent="finance", tool="finance_summary", args={}, user=_user(db, users["fin"]["id"]))
    assert out.status == "error" and out.code == "tool_unavailable"


def test_every_allow_listed_tool_exists_and_agents_share_no_department_tools():
    from agentsmind.agents.catalog import AGENT_TOOLS, TOOLS

    assert all(t in TOOLS for ts in AGENT_TOOLS.values() for t in ts)
    assert not any(t.startswith("finance_") for t in AGENT_TOOLS["hr"] | AGENT_TOOLS["it"] | AGENT_TOOLS["documents"])
    assert not any(t.startswith("it_") for t in AGENT_TOOLS["hr"] | AGENT_TOOLS["finance"])


# ── departments ──────────────────────────────────────────────────────────────

def test_hr_user_gets_403_on_finance_department(client, users, db):
    """Acceptance scenario 2, page half (backend): direct access to a forbidden department is 403."""
    from agentsmind.db.models import AuditLog

    h = auth_header(users["hr"]["token"])
    assert client.get("/api/departments/hr", headers=h).status_code == 200
    r = client.get("/api/departments/finance", headers=h)
    assert r.status_code == 403 and "finance" in r.json()["detail"]["message"].lower()
    db.expire_all()
    a = db.scalars(select(AuditLog).where(AuditLog.target_type == "department")).one()
    assert (a.action, a.target_id, a.outcome) == ("access.denied", "finance", "denied")


def test_department_list_marks_access_with_reason(client, users):
    items = {d["slug"]: d for d in client.get("/api/departments", headers=auth_header(users["emp"]["token"])).json()["items"]}
    assert items["communications"]["accessible"] is True
    assert items["finance"]["accessible"] is False and items["finance"]["reason"]
    assert set(items) == {"hr", "it", "finance", "documents", "communications"}


def test_admin_opens_every_department(client, admin_token):
    for slug in ("hr", "it", "finance", "documents", "communications"):
        assert client.get(f"/api/departments/{slug}", headers=auth_header(admin_token)).status_code == 200
    assert client.get("/api/departments/payroll", headers=auth_header(admin_token)).status_code == 404


# ── agent runs (through the queue) ───────────────────────────────────────────

def _drain():
    from agentsmind.queue import handlers  # noqa: F401
    from agentsmind.queue.core import get_queue
    from agentsmind.queue.worker import Worker

    w = Worker(get_queue())
    while w.run_once() is not None:
        pass


@pytest.fixture(autouse=True)
def _fresh_queue():
    from agentsmind.queue.core import reset_queue

    reset_queue()
    yield
    reset_queue()


def test_agent_run_goes_through_queue_and_is_labeled_simulated(client, users):
    h = auth_header(users["hr"]["token"])
    r = client.post("/api/agents/hr/runs", headers=h, json={
        "action": "job_description", "inputs": {"role": "Accounts Officer", "department": "Finance"}})
    assert r.status_code == 202 and r.json()["status"] == "queued"
    run_id = r.json()["id"]
    _drain()
    done = client.get(f"/api/agents/runs/{run_id}", headers=h).json()
    assert done["status"] == "done" and done["simulated"] is True
    assert done["output"].startswith("[Simulated]")


def test_hr_user_cannot_run_finance_agent(client, users):
    r = client.post("/api/agents/finance/runs", headers=auth_header(users["hr"]["token"]),
                    json={"action": "anything", "inputs": {}})
    assert r.status_code == 403


def test_any_staff_member_can_use_it_agent(client, users):
    r = client.post("/api/agents/it/runs", headers=auth_header(users["emp"]["token"]),
                    json={"action": "troubleshoot", "inputs": {"problem": "My laptop cannot connect to office wifi"}})
    assert r.status_code == 202


def test_agent_inputs_are_validated(client, users):
    r = client.post("/api/agents/it/runs", headers=auth_header(users["emp"]["token"]),
                    json={"action": "troubleshoot", "inputs": {"problem": "x"}})
    assert r.status_code == 422 and r.json()["detail"]["fields"][0]["field"] == "problem"


def test_runs_are_private_to_their_owner(client, users):
    r = client.post("/api/agents/it/runs", headers=auth_header(users["emp"]["token"]),
                    json={"action": "troubleshoot", "inputs": {"problem": "Printer shows offline"}})
    rid = r.json()["id"]
    assert client.get(f"/api/agents/runs/{rid}", headers=auth_header(users["it"]["token"])).status_code == 404


def test_idempotency_key_prevents_duplicate_runs(client, users):
    h = {**auth_header(users["emp"]["token"]), "Idempotency-Key": "req-123"}
    body = {"action": "troubleshoot", "inputs": {"problem": "VPN keeps disconnecting"}}
    a = client.post("/api/agents/it/runs", headers=h, json=body).json()
    b = client.post("/api/agents/it/runs", headers=h, json=body).json()
    assert a["id"] == b["id"] and a["task_id"] == b["task_id"]


def test_onboarding_missing_fields_answered_without_llm(client, users):
    h = auth_header(users["hr"]["token"])
    rid = client.post("/api/agents/hr/runs", headers=h,
                      json={"action": "onboarding_checklist", "inputs": {"job_title": "Accounts Officer"}}).json()["id"]
    _drain()
    out = client.get(f"/api/agents/runs/{rid}", headers=h).json()
    assert out["output"] == "Please provide the employee's department so I can generate the onboarding checklist."
    assert out["simulated"] is False


def test_agent_list_only_shows_permitted_agents(client, users):
    names = {a["name"] for a in client.get("/api/agents", headers=auth_header(users["emp"]["token"])).json()["items"]}
    assert names == {"it", "email", "calendar"}


def test_admin_queue_endpoints(client, admin_token, users):
    client.post("/api/agents/it/runs", headers=auth_header(users["emp"]["token"]),
                json={"action": "troubleshoot", "inputs": {"problem": "Monitor flickers"}})
    h = auth_header(admin_token)
    stats = client.get("/api/admin/queue", headers=h).json()
    assert stats["backend"] == "db" and stats["queues"]["default"]["pending"] == 1
    assert client.get("/api/admin/queue", headers=auth_header(users["it"]["token"])).status_code == 403
    tasks = client.get("/api/admin/queue/tasks?status=pending", headers=h).json()["items"]
    assert tasks[0]["kind"] == "agent.run"
    assert client.post(f"/api/admin/queue/tasks/{tasks[0]['id']}/retry", headers=h).status_code == 409
