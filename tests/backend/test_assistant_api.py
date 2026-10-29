"""Assistant API end to end: orchestrator -> agents -> gateway -> approvals -> executors (sandbox)."""
from __future__ import annotations

import json

import pytest
from bhelpers import auth_header, login
from sandbox_executors import register
from sqlalchemy import select

PW = "Plenty-Long-Passw0rd"


@pytest.fixture(autouse=True)
def _executors(tmp_path, monkeypatch):
    from agentsmind.agents import gateway

    saved = dict(gateway.EXECUTORS)
    register(tmp_path, monkeypatch)
    yield
    gateway.EXECUTORS.clear()
    gateway.EXECUTORS.update(saved)


@pytest.fixture
def users(make_user, client):
    out = {}
    for name, roles in (("hr", ["hr"]), ("fin", ["finance", "hr"]), ("emp", ["employee"])):
        u = make_user(f"{name}.a@example.com", roles)
        out[name] = {"id": u["id"], "h": auth_header(login(client, email=u["email"], password=PW).json()["access_token"])}
    return out


def say(client, h, text, conv=None):
    r = client.post("/api/assistant/messages", headers=h, json={"text": text, "conversation_id": conv})
    assert r.status_code == 200, r.text
    return r.json()


def test_calendar_prompt_to_event_with_read_back(client, users):
    """Acceptance: calendar by prompt, approval card first, read back after creating, labeled Simulated."""
    h = users["emp"]["h"]
    out = say(client, h, "Schedule a design review tomorrow at 3 pm for 45 minutes with a Google Meet link")
    card = out["cards"][0]
    assert card["kind"] == "approval" and card["simulated"] and out["simulated"]
    appr_id = card["approval"]["id"]
    pend = client.get("/api/approvals?status=pending", headers=h).json()["items"]
    assert [a["id"] for a in pend] == [appr_id] and pend[0]["tool"] == "calendar_create_event"
    r = client.post(f"/api/approvals/{appr_id}/approve", headers=h, json={}).json()
    assert r["outcome"]["status"] == "ok" and "confirmed" in r["outcome"]["result"]["body"]
    assert r["outcome"]["result"]["links"][0]["label"] == "Meet link"
    lst = say(client, h, "What's on my calendar tomorrow?", out["conversation_id"])
    assert lst["cards"][0]["data"]["rows"][0]["title"] == "Design review"
    # replaying the approval does not create a second event
    assert client.post(f"/api/approvals/{appr_id}/approve", headers=h, json={}).status_code == 409


def test_clarification_round_trip_uses_conversation(client, users):
    h = users["emp"]["h"]
    a = say(client, h, "Set up a meeting with the finance team")
    assert a["cards"][0]["kind"] == "clarify" and a["pending"]
    b = say(client, h, "tomorrow at 11 am", a["conversation_id"])
    assert b["cards"][0]["kind"] == "approval" and b["planner"] == "clarification"
    conv = client.get(f"/api/assistant/conversations/{a['conversation_id']}", headers=h).json()
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant", "user", "assistant"]
    other = users["hr"]["h"]
    assert client.get(f"/api/assistant/conversations/{a['conversation_id']}", headers=other).status_code == 404


def test_employee_denied_payroll_and_audited(client, users, db):
    from agentsmind.db.models import AuditLog, ToolCall

    out = say(client, users["emp"]["h"], "What is the total monthly payroll?")
    assert out["cards"][0]["kind"] == "denied"
    db.expire_all()
    assert db.scalars(select(AuditLog).where(AuditLog.action == "access.denied",
                                             AuditLog.target_id == "finance")).first() is not None
    assert not db.scalars(select(ToolCall).where(ToolCall.tool.like("finance_%"))).all()


def test_hostile_email_only_produces_reply_drafts(client, users, db):
    """Acceptance: hostile email. Nothing but approval-gated reply drafts; no finance tool is touched."""
    from agentsmind.db.models import Approval, ToolCall

    out = say(client, users["fin"]["h"], "Draft replies to my unread emails")
    approvals = [c for c in out["cards"] if c["kind"] == "approval"]
    assert approvals and {c["approval"]["tool"] for c in approvals} == {"gmail_send_email"}
    db.expire_all()
    assert {a.tool for a in db.scalars(select(Approval))} == {"gmail_send_email"}
    assert all(a.status == "pending" for a in db.scalars(select(Approval)))
    assert not db.scalars(select(ToolCall).where(ToolCall.tool.like("finance_%"))).all()
    hostile = next(c for c in approvals if "security-alerts" in c["approval"]["summary"])
    assert hostile["data"]["arguments"]["to"] == ["it-support@security-alerts.example.net"]
    assert any("addressed to an AI" in w for w in hostile["warnings"])


def test_send_email_after_approval_is_idempotent(client, users, tmp_path):
    h = users["emp"]["h"]
    out = say(client, h, "Send an email to hina.malik@example.com about the VPN fix saying it is resolved now")
    aid = out["cards"][0]["approval"]["id"]
    r = client.post(f"/api/approvals/{aid}/approve", headers=h, json={}).json()
    assert r["outcome"]["status"] == "ok" and "Simulated" in r["outcome"]["result"]["body"]
    lines = (tmp_path / "workspace_sandbox_outbox.jsonl").read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["to"] == ["hina.malik@example.com"]


def test_hr_screening_fills_candidates_board(client, users, db):
    h = users["hr"]["h"]
    out = say(client, h, "Screen the CVs for the Python Developer role")
    assert out["cards"][0]["kind"] == "result"
    board = client.get("/api/hr/candidates", headers=h).json()["items"]
    names = {c["name"]: c for c in board}
    assert set(names) == {"Sara Khan", "Bilal Ahmed", "Alex Example"}
    assert names["Alex Example"]["needs_human_review"] and names["Sara Khan"]["stage"] == "screened"
    detail = client.get(f"/api/hr/candidates/{names['Alex Example']['id']}", headers=h).json()
    assert detail["details"]["flags"] and detail["simulated"]
    r = client.patch(f"/api/hr/candidates/{names['Sara Khan']['id']}", headers=h, json={"stage": "shortlisted"})
    assert r.status_code == 200 and r.json()["stage"] == "shortlisted"
    say(client, h, "Screen the CVs for the Python Developer role")  # re-screening keeps people's decisions
    again = {c["name"]: c for c in client.get("/api/hr/candidates", headers=h).json()["items"]}
    assert len(again) == 3 and again["Sara Khan"]["stage"] == "shortlisted"
    assert client.get("/api/hr/candidates", headers=users["emp"]["h"]).status_code == 403


def test_stream_emits_progress_then_result(client, users):
    with client.stream("POST", "/api/assistant/messages/stream", headers=users["emp"]["h"],
                       json={"text": "Am I free tomorrow afternoon?"}) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    events = [ln.split(": ", 1)[1] for ln in body.splitlines() if ln.startswith("event: ")]
    assert events[0] == "plan" and "step" in events and events[-1] == "result"
    result = json.loads(body.strip().split("data: ")[-1])
    assert result["cards"][0]["kind"] == "result"


def test_agent_runs_recorded(client, users, db):
    from agentsmind.db.models import AgentRun

    say(client, users["emp"]["h"], "Raise a ticket because my printer is broken and then schedule a call with IT "
                                   "tomorrow at 2 pm")
    db.expire_all()
    runs = db.scalars(select(AgentRun).order_by(AgentRun.id)).all()
    assert [r.agent for r in runs] == ["it", "calendar"] and all(r.status == "done" for r in runs)


def test_internal_status_requires_workspace_token(client, monkeypatch):
    from agentsmind.settings import reset_settings_cache

    assert client.get("/api/internal/status").status_code == 401
    monkeypatch.setenv("WORKSPACE_MCP_TOKEN", "w" * 30)
    reset_settings_cache()
    try:
        assert client.get("/api/internal/status", headers={"Authorization": "Bearer nope"}).status_code == 401
        r = client.get("/api/internal/status", headers={"Authorization": "Bearer " + "w" * 30})
        assert r.status_code == 200 and "queue" in r.json() and r.json()["agents"]["llm_mode"].startswith("sandbox")
    finally:
        reset_settings_cache()


def test_llm_failure_is_an_error_card_not_a_crash(client, users, monkeypatch):
    """Legacy flip: the old client returned provider errors as if they were answers."""
    from agentsmind.agents import llm as L

    class Failing(L.SandboxLLM):
        simulated = False
        model = "broken"

        def complete(self, prompt, **kw):
            raise L.LLMError("OpenAI rejected the API key. Check OPENAI_API_KEY in .env.")

    monkeypatch.setattr("agentsmind.assistant.service.get_llm", lambda: Failing())
    out = say(client, users["hr"]["h"], "Summarize the leave policy")
    c = out["cards"][0]
    assert c["kind"] == "error" and "OpenAI rejected the API key" in c["body"]
