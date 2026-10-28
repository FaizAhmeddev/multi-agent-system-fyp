"""workspace-mcp in sandbox mode: Gmail and Drive tools over a real MCP session."""
from __future__ import annotations

import json

import pytest
from mcphelpers import call, free_port, start

TOKEN = "workspace-test-token-" + "w" * 20


@pytest.fixture(scope="module")
def ws(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("ws")
    port = free_port()
    p = start("mcp_servers.workspace_mcp.server",
              {"WORKSPACE_MCP_TOKEN": TOKEN, "WORKSPACE_MCP_PORT": str(port), "WORKSPACE_MODE": "sandbox",
               "WORKSPACE_DATA_DIR": str(tmp), "CORE_API_URL": f"http://127.0.0.1:{free_port()}"},
              tmp / "ws.log", port)
    yield f"http://127.0.0.1:{port}/mcp", tmp
    p.terminate()
    p.wait(10)


def test_tool_list(ws):
    tools = {t.name: t for t in call(ws[0], TOKEN, "__list__", None).tools}
    assert set(tools) == {"gmail_read_inbox", "gmail_send_email", "drive_list_files", "drive_read_file",
                          "drive_search", "queue_stats", "agent_status"}
    assert tools["gmail_send_email"].annotations.read_only_hint is False
    assert all(tools[t].annotations.read_only_hint for t in tools if t != "gmail_send_email")


def test_inbox_is_untrusted_and_simulated(ws):
    d = call(ws[0], TOKEN, "gmail_read_inbox", {"max_results": 10}).structured_content
    assert d["untrusted"] is True and d["simulated"] is True and len(d["items"]) == 5
    assert d["items"][0]["date"] >= d["items"][-1]["date"]
    unread = call(ws[0], TOKEN, "gmail_read_inbox", {"unread_only": True}).structured_content
    assert len(unread["items"]) == 4
    page = call(ws[0], TOKEN, "gmail_read_inbox", {"max_results": 2}).structured_content
    assert page["next_page_token"] == "2"


def test_send_is_idempotent_and_never_delivered(ws):
    url, tmp = ws
    args = {"to": ["usman.tariq@example.com"], "subject": "Re: Quick catch-up", "body": "Friday 3 pm works.",
            "idempotency_key": "appr-test-send-1"}
    a = call(url, TOKEN, "gmail_send_email", args).structured_content
    b = call(url, TOKEN, "gmail_send_email", args).structured_content
    assert a["sent"] and not a["already_sent"] and a["simulated"]
    assert b["already_sent"] and not b["sent"] and b["message_id"] == a["message_id"]
    lines = (tmp / "workspace_sandbox_outbox.jsonl").read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["simulated"] is True


def test_header_injection_refused(ws):
    r = call(ws[0], TOKEN, "gmail_send_email", {"to": ["a@example.com"], "subject": "Hi\r\nBcc: x@example.net",
                                                "body": "b", "idempotency_key": "appr-test-send-2"})
    assert r.is_error and "single line" in r.content[0].text


def test_drive_list_search_read(ws):
    url = ws[0]
    files = call(url, TOKEN, "drive_list_files", {"folder": "HR/CVs"}).structured_content["items"]
    assert sorted(f["name"] for f in files) == ["CV_Bilal_Ahmed.txt", "CV_Hostile_Candidate.txt", "CV_Sara_Khan.txt"]
    hits = call(url, TOKEN, "drive_search", {"query": "FastAPI"}).structured_content["items"]
    assert {"CV_Sara_Khan.txt", "Job_Description_Python_Developer.txt"} <= {h["name"] for h in hits}
    sara = next(f for f in files if f["name"] == "CV_Sara_Khan.txt")
    doc = call(url, TOKEN, "drive_read_file", {"file_id": sara["id"]}).structured_content
    assert doc["untrusted"] is True and "Sara Khan" in doc["text"] and doc["truncated"] is False
    missing = call(url, TOKEN, "drive_read_file", {"file_id": "sim-doesnotexist"})
    assert missing.is_error and "not found" in missing.content[0].text


def test_system_tools_report_core_unreachable(ws):
    r = call(ws[0], TOKEN, "queue_stats", {})
    assert r.is_error and "not reachable" in r.content[0].text
