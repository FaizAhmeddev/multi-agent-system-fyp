"""Characterization: the legacy HTTP "MCP" server (not the MCP protocol)."""
import json
import socket
import urllib.error
import urllib.request

import pytest

import mcp_server.server as srv


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="module")
def base_url():
    port = _free_port()
    srv._server_thread = None
    srv.start_mcp_server("127.0.0.1", port)
    yield f"http://127.0.0.1:{port}"
    srv.stop_mcp_server()


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, dict(r.headers), json.loads(r.read())


def _post(url, body, raw=False):
    data = body if raw else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
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


@pytest.mark.legacy_bug
def test_no_auth_and_wildcard_cors(base_url):
    # Any local process, and any web page via CORS "*", can call tools without a token.
    status, headers, _ = _get(base_url + "/health")
    assert status == 200
    assert headers.get("Access-Control-Allow-Origin") == "*"


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


@pytest.mark.legacy_bug
def test_gmail_send_reports_success_even_when_send_failed(monkeypatch):
    import tools.gmail_send as gs

    def fake_send(state):
        state["send_status"] = "Failed to send email. smtp: auth error"
        return state  # legacy send_email never raises on failure

    monkeypatch.setattr(gs, "send_email", fake_send)
    res = srv.call_mcp_tool("gmail_send_email", {"recipient": "a@example.com", "subject": "s", "body": "b"})
    assert res["success"] is True  # wrong: the email was not sent


@pytest.mark.legacy_bug
def test_gmail_read_inbox_ignores_its_parameters(monkeypatch):
    import tools.gmail_read as gr
    captured = {}

    def fake_read(state):
        captured.update(state)
        return {"emails": []}

    monkeypatch.setattr(gr, "read_emails", fake_read)
    srv.call_mcp_tool("gmail_read_inbox", {"max_emails": 2, "unread_only": True})
    assert captured == {}  # max_emails / unread_only are never passed on


def test_call_in_process_unknown_tool():
    assert srv.call_mcp_tool("x", {}) == {"success": False, "error": "Tool 'x' not found"}
