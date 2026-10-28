"""End to end: core gateway -> MCP client -> finance-mcp / it-mcp -> Finance Portal / IT Helpdesk.

Starts the two portals and the two MCP servers as real processes on free localhost ports.
"""
from __future__ import annotations

import os
import socket
import sqlite3
import subprocess
import sys
import time

import httpx
import pytest
from bhelpers import ROOT, auth_header, login
from sqlalchemy import select

PORTAL_KEY = "stack-portal-key-" + "p" * 20
MCP_TOKEN = "stack-mcp-token-" + "t" * 20
PW = "Plenty-Long-Passw0rd"


def _port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _wait(url: str, *, headers=None, ok=(200,), timeout=40.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            if httpx.get(url, headers=headers or {}, timeout=1.0).status_code in ok:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    raise RuntimeError(f"service at {url} did not start")


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("stack")
    ports = {k: _port() for k in ("fin", "it", "fmcp", "imcp")}
    env = dict(os.environ)
    env.update({
        "AGENTSMIND_ENV_FILE": "",
        "FINANCE_PORTAL_API_KEY": PORTAL_KEY, "FINANCE_PORTAL_SECRET_KEY": "f" * 40,
        "FINANCE_PORTAL_ADMIN_EMAIL": "fin.admin@example.com", "FINANCE_PORTAL_ADMIN_PASSWORD": "Fin-Admin-Pass-123",
        "FINANCE_PORTAL_DB_URL": "sqlite:///" + str(tmp / "finance.db").replace("\\", "/"),
        "IT_PORTAL_API_KEY": PORTAL_KEY, "IT_PORTAL_SECRET_KEY": "i" * 40,
        "IT_PORTAL_ADMIN_EMAIL": "it.admin@example.com", "IT_PORTAL_ADMIN_PASSWORD": "It-Admin-Pass-1234",
        "IT_PORTAL_DB_URL": "sqlite:///" + str(tmp / "it.db").replace("\\", "/"),
        "IT_PORTAL_PUBLIC_URL": f"http://127.0.0.1:{ports['it']}", "IT_PORTAL_UPLOAD_DIR": str(tmp / "up"),
        "FINANCE_MCP_TOKEN": MCP_TOKEN, "FINANCE_MCP_PORT": str(ports["fmcp"]),
        "FINANCE_PORTAL_URL": f"http://127.0.0.1:{ports['fin']}",
        "IT_MCP_TOKEN": MCP_TOKEN, "IT_MCP_PORT": str(ports["imcp"]), "IT_PORTAL_URL": f"http://127.0.0.1:{ports['it']}",
        "PYTHONPATH": os.pathsep.join([str(ROOT / "external_systems"), str(ROOT)]),
    })
    logs = {}
    cmds = {
        "fin": [sys.executable, "-m", "uvicorn", "finance_portal.app:create_app", "--factory", "--app-dir",
                str(ROOT / "external_systems"), "--host", "127.0.0.1", "--port", str(ports["fin"])],
        "it": [sys.executable, "-m", "uvicorn", "it_portal.app:create_app", "--factory", "--app-dir",
               str(ROOT / "external_systems"), "--host", "127.0.0.1", "--port", str(ports["it"])],
        "fmcp": [sys.executable, "-m", "mcp_servers.finance_mcp.server"],
        "imcp": [sys.executable, "-m", "mcp_servers.it_mcp.server"],
    }
    procs = {}
    try:
        for name, cmd in cmds.items():
            logs[name] = open(tmp / f"{name}.log", "w")  # noqa: SIM115
            procs[name] = subprocess.Popen(cmd, env=env, cwd=str(ROOT), stdout=logs[name], stderr=subprocess.STDOUT)
        _wait(f"http://127.0.0.1:{ports['fin']}/api/v1/health")
        _wait(f"http://127.0.0.1:{ports['it']}/api/v1/health")
        for p in ("fmcp", "imcp"):  # MCP endpoint answers 401 without a token once it is up
            _wait(f"http://127.0.0.1:{ports[p]}/mcp", ok=(401, 405, 406))
        yield {"ports": ports, "tmp": tmp, "env": env}
    finally:
        for p in procs.values():
            p.kill()
        for p in procs.values():
            p.wait(timeout=10)
        for f in logs.values():
            f.close()


@pytest.fixture
def core(stack, monkeypatch, client):
    """Point the core at the running MCP servers and register the MCP executors."""
    from agentsmind.agents import gateway
    from agentsmind.mcp.client import register_mcp_executors
    from agentsmind.settings import reset_settings_cache

    p = stack["ports"]
    monkeypatch.setenv("FINANCE_MCP_URL", f"http://127.0.0.1:{p['fmcp']}/mcp")
    monkeypatch.setenv("FINANCE_MCP_TOKEN", MCP_TOKEN)
    monkeypatch.setenv("IT_MCP_URL", f"http://127.0.0.1:{p['imcp']}/mcp")
    monkeypatch.setenv("IT_MCP_TOKEN", MCP_TOKEN)
    reset_settings_cache()
    saved = dict(gateway.EXECUTORS)
    names = register_mcp_executors()
    assert len(names) == 13  # 8 finance + 5 IT tools
    yield stack
    gateway.EXECUTORS.clear()
    gateway.EXECUTORS.update(saved)


@pytest.fixture
def people(make_user, client):
    out = {}
    for key, email, roles in (("fin", "sana.malik@example.com", ["finance"]), ("hr", "hira.siddiqui@example.com", ["hr"]),
                              ("emp", "omar.farooq@example.com", ["employee"]), ("it", "bilal.qureshi@example.com", ["it"])):
        u = make_user(email, roles)
        out[key] = {"id": u["id"], "h": auth_header(login(client, email=email, password=PW).json()["access_token"]),
                    "email": email}
    return out


def _fin_db(stack):
    return sqlite3.connect(str(stack["tmp"] / "finance.db"))


# ── MCP server behaviour ─────────────────────────────────────────────────────

def test_mcp_requires_token(stack):
    url = f"http://127.0.0.1:{stack['ports']['fmcp']}/mcp"
    hdr = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    assert httpx.post(url, json={}, headers=hdr).status_code == 401
    assert httpx.post(url, json={}, headers={**hdr, "Authorization": "Bearer wrong-token-xxxxxxxxxxxx"}).status_code == 401


def test_mcp_tools_have_schemas_and_annotations(core):
    from agentsmind.mcp.client import list_tools

    fin = {t["name"]: t for t in list_tools("finance-mcp")}
    assert set(fin) == {"finance_list_people", "finance_get_person", "finance_create_person", "finance_update_person",
                        "finance_delete_person", "finance_search_people", "finance_summary", "finance_list_payments"}
    assert fin["finance_summary"]["read_only"] and not fin["finance_create_person"]["read_only"]
    assert fin["finance_delete_person"]["destructive"]
    assert "idempotency_key" in fin["finance_create_person"]["input_schema"]["required"]
    assert fin["finance_summary"]["output_schema"]["properties"]["source_tool"]
    it = {t["name"] for t in list_tools("it-mcp")}
    assert it == {"it_create_ticket", "it_get_ticket", "it_list_tickets", "it_update_ticket_status", "it_add_comment"}


def test_bad_mcp_token_is_reported_clearly(core, monkeypatch):
    from agentsmind.mcp.client import MCPCallError, call_tool
    from agentsmind.settings import reset_settings_cache

    monkeypatch.setenv("FINANCE_MCP_TOKEN", "definitely-wrong-token-xxxx")
    reset_settings_cache()
    with pytest.raises(MCPCallError) as e:
        call_tool("finance_summary", {})
    assert e.value.code == "unauthorized"


# ── core -> MCP -> portal ────────────────────────────────────────────────────

def test_finance_person_lifecycle_through_approvals(core, client, people, db):
    """Acceptance scenario 3: create needs approval, then appears in the Finance Portal; edit and delete work."""
    from agentsmind.agents.gateway import call_tool
    from agentsmind.db.models import User

    fin_user = db.get(User, people["fin"]["id"])
    args = {"full_name": "Ayesha Khan", "email": "ayesha.khan@example.com", "department": "Finance",
            "job_title": "Accounts Officer", "monthly_salary": "150000", "currency": "PKR", "start_date": "2026-12-01"}
    first = call_tool(db, agent="finance", tool="finance_create_person", args=args, user=fin_user,
                      summary="Add Ayesha Khan, Accounts Officer, 150000 PKR, starts 1 December 2026")
    assert first.status == "approval_required"
    con = _fin_db(core)
    q = "SELECT COUNT(*) FROM people WHERE email='ayesha.khan@example.com'"
    assert con.execute(q).fetchone()[0] == 0  # nothing happened yet
    r = client.post(f"/api/approvals/{first.approval_id}/approve", json={}, headers=people["fin"]["h"])
    assert r.status_code == 200 and r.json()["outcome"]["status"] == "ok", r.text
    row = con.execute("SELECT full_name, salary_minor, created_via FROM people WHERE email='ayesha.khan@example.com'"
                      ).fetchone()
    assert row == ("Ayesha Khan", 15000000, "api")
    pid = r.json()["approval"]["result"]["person"]["id"]

    upd = call_tool(db, agent="finance", tool="finance_update_person", user=fin_user,
                    args={"person_id": pid, "job_title": "Senior Accounts Officer"})
    client.post(f"/api/approvals/{upd.approval_id}/approve", json={}, headers=people["fin"]["h"])
    assert con.execute("SELECT job_title FROM people WHERE id=?", (pid,)).fetchone()[0] == "Senior Accounts Officer"

    dele = call_tool(db, agent="finance", tool="finance_delete_person", user=fin_user, args={"person_id": pid},
                     summary=f"Delete Ayesha Khan (person #{pid})")
    assert client.post(f"/api/approvals/{dele.approval_id}/approve", json={},
                       headers=people["fin"]["h"]).status_code == 400  # destructive needs confirm
    ok = client.post(f"/api/approvals/{dele.approval_id}/approve", json={"confirm": True}, headers=people["fin"]["h"])
    assert ok.json()["approval"]["status"] == "executed"
    assert con.execute(q).fetchone()[0] == 0
    con.close()


def test_retry_with_same_approval_key_creates_no_duplicate(core, db, people):
    """Acceptance scenario 5: replaying the executed tool call through MCP does not duplicate."""
    from agentsmind.mcp.client import call_tool as mcp_call

    args = {"full_name": "Usman Tariq", "email": "usman.t@example.com", "department": "Engineering",
            "job_title": "Frontend Developer", "monthly_salary": "240000", "start_date": "2026-11-15",
            "idempotency_key": "appr-retry-test-0001"}
    a = mcp_call("finance_create_person", args)
    b = mcp_call("finance_create_person", args)  # e.g. the core retried after a timeout
    assert a["created"] is True and b["created"] is False and a["person"]["id"] == b["person"]["id"]
    con = _fin_db(core)
    assert con.execute("SELECT COUNT(*) FROM people WHERE email='usman.t@example.com'").fetchone()[0] == 1
    con.close()


def test_payroll_total_equals_independent_sql(core, client, people):
    from agentsmind.mcp.client import call_tool as mcp_call

    for i, s in enumerate(("100000", "200000.50")):
        mcp_call("finance_create_person", {"full_name": f"Payroll Person {i}", "email": f"pp{i}@example.com",
                                           "department": "Operations", "job_title": "Coordinator",
                                           "monthly_salary": s, "start_date": "2026-01-01",
                                           "idempotency_key": f"payroll-test-{i}-xyz"})
    r = client.get("/api/finance/summary", headers=people["fin"]["h"])
    assert r.status_code == 200 and r.json()["source"] == "finance_summary"
    pkr = next(x for x in r.json()["result"]["payroll_by_currency"] if x["currency"] == "PKR")
    con = _fin_db(core)
    minor = con.execute("SELECT SUM(salary_minor) FROM people WHERE status='active' AND currency='PKR'").fetchone()[0]
    con.close()
    assert pkr["total_monthly_payroll"] == f"{minor // 100}.{minor % 100:02d}"


def test_hr_user_cannot_reach_finance_tools_anywhere(core, client, people, db):
    """Acceptance scenario 2 (backend): 403 on the Finance workspace and a denied, logged tool call."""
    from agentsmind.agents.gateway import call_tool
    from agentsmind.db.models import ToolCall, User

    assert client.get("/api/finance/people", headers=people["hr"]["h"]).status_code == 403
    assert client.get("/api/departments/finance", headers=people["hr"]["h"]).status_code == 403
    hr = db.get(User, people["hr"]["id"])
    out = call_tool(db, agent="hr", tool="finance_list_people", args={}, user=hr)
    assert out.status == "denied"
    out2 = call_tool(db, agent="finance", tool="finance_list_people", args={}, user=hr)
    assert out2.status == "denied" and out2.code == "role_forbidden"
    db.expire_all()
    denied = db.scalars(select(ToolCall).where(ToolCall.status == "denied")).all()
    assert {(c.agent, c.tool) for c in denied} == {("hr", "finance_list_people"), ("finance", "finance_list_people")}


def test_it_complaint_from_core_appears_in_helpdesk_with_confirmation_screen(core, client, people):
    """Acceptance scenario 4 (backend half): ticket via core, confirmation screen on the portal, visible in both."""
    h = {**people["emp"]["h"], "Idempotency-Key": "ui-ticket-1"}
    body = {"department": "Operations", "category": "network", "priority": "medium",
            "summary": "Laptop cannot join office Wi-Fi", "description": "My laptop cannot connect to office wifi."}
    r = client.post("/api/it/tickets", json=body, headers=h)
    assert r.status_code == 201, r.text
    res = r.json()["result"]
    number = res["ticket"]["number"]
    assert res["ticket"]["requester_email"] == "omar.farooq@example.com" and res["ticket"]["source"] == "agentsmind"
    page = httpx.get(res["confirmation_url"])
    assert page.status_code == 200 and "Complaint submitted" in page.text and number in page.text
    # same submit again: no duplicate
    again = client.post("/api/it/tickets", json=body, headers=h)
    assert again.json()["result"]["ticket"]["number"] == number
    # visible in AgentsMind: the requester sees it; IT staff see it in the full list
    mine = client.get("/api/it/tickets", headers=people["emp"]["h"]).json()["result"]
    assert [t["number"] for t in mine["items"]] == [number]
    allt = client.get("/api/it/tickets", headers=people["it"]["h"]).json()["result"]
    assert number in [t["number"] for t in allt["items"]]


def test_non_it_staff_cannot_see_other_peoples_tickets(core, client, people):
    from agentsmind.mcp.client import call_tool as mcp_call

    t = mcp_call("it_create_ticket", {"requester_name": "Someone Else", "requester_email": "else@example.com",
                                      "department": "Sales", "category": "printer", "priority": "low",
                                      "description": "Printer jams on every page.", "idempotency_key": "other-ticket-1"})
    number = t["ticket"]["number"]
    assert client.get(f"/api/it/tickets/{number}", headers=people["emp"]["h"]).status_code == 404
    assert client.post(f"/api/it/tickets/{number}/comments", json={"body": "me too"},
                       headers=people["emp"]["h"]).status_code == 404
    assert client.get(f"/api/it/tickets/{number}", headers=people["it"]["h"]).status_code == 200
    assert client.patch(f"/api/it/tickets/{number}/status", json={"status": "in_progress"},
                        headers=people["emp"]["h"]).status_code == 403


def test_workspace_delete_needs_exact_name(core, client, people):
    h = people["fin"]["h"]
    c = client.post("/api/finance/people", headers={**h, "Idempotency-Key": "ws-create-1"}, json={
        "full_name": "Ahmed Raza", "email": "ahmed.raza@example.com", "department": "Finance",
        "job_title": "Senior Accountant", "monthly_salary": "185000", "start_date": "2023-03-01"})
    assert c.status_code == 201, c.text
    pid = c.json()["result"]["person"]["id"]
    r = client.request("DELETE", f"/api/finance/people/{pid}", headers=h, json={"confirm": True, "confirm_name": "Ahmed"})
    assert r.status_code == 400 and "Ahmed Raza (ahmed.raza@example.com)" in r.json()["detail"]["message"]
    ok = client.request("DELETE", f"/api/finance/people/{pid}", headers=h,
                        json={"confirm": True, "confirm_name": "Ahmed Raza"})
    assert ok.status_code == 200 and ok.json()["result"]["full_name"] == "Ahmed Raza"


def test_admin_mcp_health(core, client, admin_token):
    r = client.get("/api/admin/mcp", headers=auth_header(admin_token)).json()
    by = {s["server"]: s for s in r["servers"]}
    assert by["finance-mcp"]["reachable"] and by["it-mcp"]["reachable"] and by["finance-mcp"]["missing"] == []
    assert by["calendar-mcp"]["reachable"] is False and by["calendar-mcp"]["configured"] is False
