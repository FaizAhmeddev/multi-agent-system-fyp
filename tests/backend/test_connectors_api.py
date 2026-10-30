"""Settings > Connectors: an admin adds an MCP server; its tools go through the gateway like built-in tools."""
from __future__ import annotations

import sys

from bhelpers import ROOT, auth_header, login

PW = "Plenty-Long-Passw0rd"
SERVER = ROOT / "tests" / "assistant" / "fixtures" / "demo_mcp_server.py"


def test_add_use_and_remove_a_connector(client, admin_token, make_user, tmp_path, monkeypatch):
    monkeypatch.setenv("CONNECTORS_FILE", str(tmp_path / "connectors.json"))
    env = tmp_path / ".env"
    env.write_text("EXISTING=1\n")
    monkeypatch.setenv("AGENTSMIND_ENV_FILE", str(env))
    h = auth_header(admin_token)
    r = client.post("/api/connectors", headers=h, json={
        "name": "demo", "title": "Demo Chat", "transport": "stdio", "command": sys.executable, "args": [str(SERVER)],
        "env": {"DEMO_TOKEN": "${DEMO_CHAT_TOKEN}"}, "keywords": ["demo chat"], "roles": ["hr"],
        "blocked_tools": ["secret_admin"], "secrets": {"DEMO_CHAT_TOKEN": "s3cret"}})
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["state"] == "connected" and {t["name"] for t in c["tools"]} == {"list_channels", "get_messages",
                                                                             "post_message", "delete_channel"}
    assert "DEMO_CHAT_TOKEN=s3cret" in env.read_text() and "s3cret" not in (tmp_path / "connectors.json").read_text()
    assert c["env"] == {"DEMO_TOKEN": "${DEMO_CHAT_TOKEN}"}

    from agentsmind.agents.gateway import call_tool
    from agentsmind.db.models import User
    from agentsmind.db.session import SessionLocal

    hr = make_user("hira@company.pk", ["hr"])
    emp = make_user("omar@company.pk", ["employee"])
    with SessionLocal() as db:
        u = db.get(User, hr["id"])
        ok = call_tool(db, agent="connectors", tool="demo.list_channels", args={}, user=u)
        assert ok.status == "ok" and "general" in ok.result["text"]
        w = call_tool(db, agent="connectors", tool="demo.post_message", args={"channel": "hr", "text": "hi"}, user=u)
        assert w.status == "approval_required"
        no = call_tool(db, agent="connectors", tool="demo.list_channels", args={}, user=db.get(User, emp["id"]))
        assert no.status == "denied"
        assert call_tool(db, agent="hr", tool="demo.list_channels", args={}, user=u).status == "denied"
        appr = w.approval_id
    hh = auth_header(login(client, email=hr["email"], password=PW).json()["access_token"])
    done = client.post(f"/api/approvals/{appr}/approve", headers=hh, json={})
    assert done.status_code == 200, done.text
    assert done.json()["outcome"]["status"] == "ok" and "posted to hr: hi" in str(done.json())
    eh = auth_header(login(client, email=emp["email"], password=PW).json()["access_token"])
    assert client.get("/api/connectors", headers=eh).status_code == 403
    assert client.delete("/api/connectors/demo", headers=h).status_code == 204
    assert client.get("/api/connectors", headers=h).json()["items"] == []
