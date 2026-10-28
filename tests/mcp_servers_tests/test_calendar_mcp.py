"""calendar-mcp in sandbox mode, as a real process over Streamable HTTP with a bearer token."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx2
import pytest
from mcphelpers import call as _call
from mcphelpers import free_port, start

TOKEN = "calendar-test-token-" + "c" * 20
TZ = ZoneInfo("Asia/Karachi")


@pytest.fixture(scope="module")
def url(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("cal")
    port = free_port()
    p = start("mcp_servers.calendar_mcp.server", {"CALENDAR_MCP_TOKEN": TOKEN, "CALENDAR_MCP_PORT": str(port),
              "CALENDAR_MODE": "sandbox", "CALENDAR_SANDBOX_DB": str(tmp / "cal.db")}, tmp / "cal.log", port)
    yield f"http://127.0.0.1:{port}/mcp"
    p.terminate()
    p.wait(10)


def call(url, tool, args):
    return _call(url, TOKEN, tool, args)


def _at(days, h, m=0):
    base = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    return (base + timedelta(days=days, hours=h, minutes=m)).isoformat()


def test_tools_and_annotations(url):
    tools = {t.name: t for t in call(url, "__list__", None).tools}
    assert set(tools) == {"calendar_list_events", "calendar_check_availability", "calendar_create_event",
                          "calendar_update_event", "calendar_cancel_event"}
    assert tools["calendar_list_events"].annotations.read_only_hint is True
    assert tools["calendar_cancel_event"].annotations.destructive_hint is True
    assert "idempotency_key" in tools["calendar_create_event"].input_schema["required"]


def test_create_is_idempotent_read_back_and_simulated(url):
    args = {"summary": "Design review", "start": _at(5, 15), "end": _at(5, 15, 45),
            "idempotency_key": "test-create-0001", "add_meet": True}
    r1 = call(url, "calendar_create_event", args)
    assert not r1.is_error, r1
    d1 = r1.structured_content
    assert d1["created"] and d1["verified"] and d1["simulated"] and d1["mode"] == "sandbox"
    assert d1["event"]["meet_link"].startswith("https://meet.example.invalid/")
    d2 = call(url, "calendar_create_event", args).structured_content
    assert d2["created"] is False and d2["event"]["id"] == d1["event"]["id"]
    lst = call(url, "calendar_list_events", {"time_min": _at(5, 0), "time_max": _at(6, 0)}).structured_content
    assert [e["summary"] for e in lst["items"]] == ["Design review"]


def test_conflict_detected(url):
    call(url, "calendar_create_event", {"summary": "Team sync", "start": _at(7, 15), "end": _at(7, 16),
                                        "idempotency_key": "test-conflict-01"})
    busy = call(url, "calendar_check_availability", {"start": _at(7, 15, 30), "end": _at(7, 16, 30)}).structured_content
    assert busy["is_free"] is False and busy["conflicts"][0]["summary"] == "Team sync"
    free = call(url, "calendar_check_availability", {"start": _at(7, 17), "end": _at(7, 18)}).structured_content
    assert free["is_free"] is True and free["conflicts"] == []


def test_update_and_cancel(url):
    ev = call(url, "calendar_create_event", {"summary": "Budget chat", "start": _at(9, 10), "end": _at(9, 11),
                                             "idempotency_key": "test-update-001"}).structured_content["event"]
    up = call(url, "calendar_update_event", {"event_id": ev["id"], "idempotency_key": "test-update-002",
                                             "start": _at(9, 12), "end": _at(9, 13)}).structured_content
    assert up["event"]["start"].startswith(_at(9, 12)[:16])
    c1 = call(url, "calendar_cancel_event", {"event_id": ev["id"], "idempotency_key": "test-cancel-001"}).structured_content
    c2 = call(url, "calendar_cancel_event", {"event_id": ev["id"], "idempotency_key": "test-cancel-001"}).structured_content
    assert c1["already_cancelled"] is False and c2["already_cancelled"] is True
    lst = call(url, "calendar_list_events", {"time_min": _at(9, 0), "time_max": _at(10, 0)}).structured_content
    assert lst["items"] == []


def test_validation_errors_reach_client(url):
    r = call(url, "calendar_create_event", {"summary": "x", "start": _at(3, 12), "end": _at(3, 11),
                                            "idempotency_key": "test-bad-0001"})
    assert r.is_error and "end time must be after" in r.content[0].text
    r = call(url, "calendar_list_events", {"time_min": "2026-11-01T10:00:00", "time_max": "2026-11-02T10:00:00+05:00"})
    assert r.is_error  # naive datetimes are refused


def test_no_token_401_and_foreign_host_421(url):
    assert httpx2.post(url, json={}).status_code == 401
    r = httpx2.post(url, json={}, headers={"Authorization": f"Bearer {TOKEN}", "Host": "evil.example:80"})
    assert r.status_code == 421


def test_pagination(url):
    for i in range(3):
        call(url, "calendar_create_event", {"summary": f"Slot {i}", "start": _at(20, 9 + i), "end": _at(20, 9 + i, 30),
                                            "idempotency_key": f"test-page-{i:04d}"})
    p1 = call(url, "calendar_list_events", {"time_min": _at(20, 0), "time_max": _at(21, 0), "max_results": 2}).structured_content
    assert len(p1["items"]) == 2 and p1["next_page_token"]
    p2 = call(url, "calendar_list_events", {"time_min": _at(20, 0), "time_max": _at(21, 0), "max_results": 2,
                                            "page_token": p1["next_page_token"]}).structured_content
    assert [e["summary"] for e in p2["items"]] == ["Slot 2"] and p2["next_page_token"] is None
