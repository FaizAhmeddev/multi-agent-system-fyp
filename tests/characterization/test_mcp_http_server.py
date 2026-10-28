"""Characterization: the legacy HTTP "MCP" server (not the MCP protocol)."""
import json
import socket
import urllib.error
import urllib.request

import os

import pytest

import mcp_server.server as srv

TOKEN = "legacy-mcp-test-token-" + "z" * 10


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="module")
def base_url():
    os.environ["FYP_MCP_TOKEN"] = TOKEN
    port = _free_port()
    srv._server_thread = None
    srv.start_mcp_server("127.0.0.1", port)
    yield f"http://127.0.0.1:{port}"
    srv.stop_mcp_server()


AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _get(url, headers=None):
    req = urllib.request.Request(url, headers=AUTH if headers is None else headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, dict(r.headers), json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), json.loads(e.read())


def _post(url, body, raw=False, headers=None):
    data = body if raw else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json",
                                                          **(AUTH if headers is None else headers)})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


EXPECTED_TOOLS = {
    "drive_list_files", "drive_read_file", "drive_search",
    "gmail_read_inbox", "gmail_send_email", "queue_stats", "agent_status",
}


def test_lists_seven_tools(base_url):
    status, headers, body = _get(base_url + "/tools")
    assert status == 200
    assert {t["name"] for t in body["tools"]} == EXPECTED_TOOLS


def test_token_required_and_no_cors(base_url):
    """Flipped in Phase 2 (was test_no_auth_and_wildcard_cors)."""
    status, headers, _ = _get(base_url + "/health", headers={})
    assert status == 200 and "Access-Control-Allow-Origin" not in headers
    assert _get(base_url + "/tools", headers={})[0] == 401
    assert _post(base_url + "/call", {"name": "gmail_send_email", "params": {}}, headers={})[0] == 401
    bad = {"Authorization": "Bearer wrong"}
    assert _post(base_url + "/call", {"name": "agent_status", "params": {}}, headers=bad)[0] == 401


def test_server_refuses_to_start_without_token(monkeypatch):
    monkeypatch.delenv("FYP_MCP_TOKEN", raising=False)
    saved = srv._server_thread
    srv._server_thread = None
    try:
        srv.start_mcp_server("127.0.0.1", _free_port())
        assert srv._server_thread is None
    finally:
        srv._server_thread = saved


def test_unknown_tool_404(base_url):
    status, body = _post(base_url + "/call", {"name": "nope", "params": {}})
    assert status == 404 and "not found" in body["error"]


def test_invalid_json_400(base_url):
    status, body = _post(base_url + "/call", b"{not json", raw=True)
    assert status == 400


def test_agent_status_tool(base_url):
    _, body = _post(base_url + "/call", {"name": "agent_status", "params": {}})
    assert body["result"]["success"] is True
    assert body["result"]["agents"]["orchestrator"] == "orch-001"


def test_gmail_send_reports_failure_when_send_failed(monkeypatch):
    """Flipped in Phase 2 (was test_gmail_send_reports_success_even_when_send_failed)."""
    import tools.gmail_send as gs

    def fake_send(state):
        state["send_status"] = "Failed to send email. smtp: auth error"
        return state  # legacy send_email never raises on failure

    monkeypatch.setattr(gs, "send_email", fake_send)
    res = srv.call_mcp_tool("gmail_send_email", {"recipient": "a@example.com", "subject": "s", "body": "b"})
    assert res["success"] is False and "auth error" in res["error"]


def test_gmail_read_inbox_passes_its_parameters(monkeypatch):
    """Flipped in Phase 2 (was test_gmail_read_inbox_ignores_its_parameters)."""
    import tools.gmail_read as gr
    captured = {}

    def fake_read(state):
        captured.update(state)
        return {"emails": []}

    monkeypatch.setattr(gr, "read_emails", fake_read)
    srv.call_mcp_tool("gmail_read_inbox", {"max_emails": 2, "unread_only": True})
    assert captured == {"max_emails": 2, "unseen_only": True}


def test_call_in_process_unknown_tool():
    assert srv.call_mcp_tool("x", {}) == {"success": False, "error": "Tool 'x' not found"}
