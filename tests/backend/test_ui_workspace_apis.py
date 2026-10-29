"""Workspace APIs added for the React UI: documents, inbox and email, calendar, audit log, headers."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from bhelpers import auth_header, login
from sandbox_executors import register

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
def h(make_user, client):
    out = {}
    for name, roles in (("hr", ["hr"]), ("emp", ["employee"])):
        u = make_user(f"{name}.ui@example.com", roles)
        out[name] = auth_header(login(client, email=u["email"], password=PW).json()["access_token"])
    return out


def test_documents_list_search_read_summary(client, h):
    files = client.get("/api/documents/files?folder=Policies", headers=h["hr"]).json()["result"]["items"]
    assert [f["name"] for f in files] == ["Leave_Policy.md"]
    hits = client.get("/api/documents/search?q=VPN", headers=h["hr"]).json()["result"]["items"]
    assert any(f["name"] == "VPN_Setup_Guide.md" for f in hits)
    doc = client.get(f"/api/documents/files/{files[0]['id']}", headers=h["hr"]).json()["result"]
    assert "20 working days" in doc["text"] and doc["untrusted"] is True
    s = client.post(f"/api/documents/files/{files[0]['id']}/summary", headers=h["hr"]).json()
    assert s["simulated"] and "20 working days" in s["summary"]
    assert client.get("/api/documents/files", headers=h["emp"]).status_code == 403


def test_inbox_flags_hostile_email(client, h):
    items = client.get("/api/communications/inbox", headers=h["emp"]).json()["result"]["items"]
    sus = [m for m in items if m["suspicious"]]
    assert len(sus) == 1 and "security-alerts" in sus[0]["sender"]


def test_send_with_same_key_sends_once(client, h, tmp_path):
    body = {"to": ["hina.malik@example.com"], "subject": "VPN", "body": "Fixed now."}
    hdr = {**h["emp"], "Idempotency-Key": "ui-send-0001"}
    a = client.post("/api/communications/send", headers=hdr, json=body)
    b = client.post("/api/communications/send", headers=hdr, json=body)
    assert a.status_code == b.status_code == 201
    assert len((tmp_path / "workspace_sandbox_outbox.jsonl").read_text().splitlines()) == 1
    bad = client.post("/api/communications/send", headers=h["emp"], json={**body, "subject": "a\nBcc: x@example.net"})
    assert bad.status_code == 422


def test_calendar_create_list_cancel(client, h):
    tz = ZoneInfo("Asia/Karachi")
    start = (datetime.now(tz) + timedelta(days=2)).replace(hour=10, minute=0, second=0, microsecond=0)
    body = {"summary": "Planning", "start": start.isoformat(), "end": (start + timedelta(minutes=30)).isoformat(),
            "add_meet": True}
    r = client.post("/api/calendar/events", headers={**h["emp"], "Idempotency-Key": "ui-cal-0001"}, json=body)
    assert r.status_code == 201 and r.json()["result"]["verified"]
    ev = r.json()["result"]["event"]
    lst = client.get("/api/calendar/events?days=7", headers=h["emp"]).json()["result"]["items"]
    assert [e["summary"] for e in lst] == ["Planning"]
    av = client.get("/api/calendar/availability", headers=h["emp"],
                    params={"start": start.isoformat(), "end": (start + timedelta(hours=1)).isoformat()}).json()
    assert av["result"]["is_free"] is False
    assert client.request("DELETE", f"/api/calendar/events/{ev['id']}", headers=h["emp"], json={}).status_code == 400
    ok = client.request("DELETE", f"/api/calendar/events/{ev['id']}", headers=h["emp"], json={"confirm": True})
    assert ok.status_code == 200 and ok.json()["result"]["cancelled"]
    past = {**body, "start": (datetime.now(tz) - timedelta(hours=2)).isoformat(),
            "end": (datetime.now(tz) - timedelta(hours=1)).isoformat()}
    assert client.post("/api/calendar/events", headers=h["emp"], json=past).status_code == 422


def test_audit_log_admin_only(client, admin_token, h):
    client.get("/api/departments/finance", headers=h["emp"])  # a denial is audited
    r = client.get("/api/admin/audit?action=access.denied", headers=auth_header(admin_token))
    assert r.status_code == 200 and r.json()["items"][0]["action"] == "access.denied"
    assert client.get("/api/admin/audit", headers=h["emp"]).status_code == 403


def test_security_headers(client):
    r = client.get("/health")
    assert r.headers["X-Frame-Options"] == "DENY" and "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert "Content-Security-Policy" not in client.get("/api/docs").headers
