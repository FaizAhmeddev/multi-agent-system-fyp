"""Register in-process executors for calendar, Gmail and Drive tools, backed by the sandbox backends.

They return the same shapes as calendar-mcp and workspace-mcp, so API tests exercise the
real gateway, approvals and assistant without starting MCP servers.
"""
from __future__ import annotations

from datetime import datetime

from bhelpers import ROOT


def register(tmp_path, monkeypatch) -> None:
    import sys

    sys.path.insert(0, str(ROOT))
    monkeypatch.setenv("WORKSPACE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("WORKSPACE_SANDBOX_DIR", str(ROOT / "sandbox_data"))
    from agentsmind.agents.gateway import register_executor
    from mcp_servers.calendar_mcp.backends import SandboxCalendar
    from mcp_servers.workspace_mcp.backends import SandboxDrive, SandboxMail

    cal, mail, drive = SandboxCalendar(tmp_path / "cal.db"), SandboxMail(), SandboxDrive()
    meta = {"mode": "sandbox", "simulated": True}
    dt = datetime.fromisoformat

    def ev(e):
        return {k: getattr(e, k) for k in ("id", "summary", "start", "end", "timezone", "description", "location",
                                            "attendees", "meet_link", "html_link", "status")}

    def list_events(a, _k):
        items, nxt = cal.list_events(dt(a["time_min"]), dt(a["time_max"]), a.get("query"), a.get("max_results", 25), None)
        return {"items": [ev(e) for e in items], "next_page_token": nxt, **meta}

    def availability(a, _k):
        s, e = dt(a["start"]), dt(a["end"])
        busy = cal.busy(s, e)
        conflicts, _ = cal.list_events(s, e, None, 20, None)
        return {"time_min": a["start"], "time_max": a["end"], "is_free": not busy,
                "busy": [{"start": x, "end": y} for x, y in busy], "conflicts": [ev(c) for c in conflicts], **meta}

    def create(a, key):
        assert key, "write tools must receive the approval's idempotency key"
        e, created = cal.create(key=key, summary=a["summary"], start=dt(a["start"]), end=dt(a["end"]),
                                tz=a.get("timezone", "Asia/Karachi"), description=a.get("description", ""),
                                location=a.get("location", ""), attendees=a.get("attendees", []),
                                add_meet=a.get("add_meet", False), notify=False)
        back = cal.get(e.id)
        return {"created": created, "verified": back is not None, "event": ev(back), **meta}

    def update(a, key):
        patch = {k: (dt(v) if k in ("start", "end") else v) for k, v in a.items() if k != "event_id"}
        return {"event": ev(cal.update(a["event_id"], patch, False)), **meta}

    def cancel(a, key):
        done = cal.cancel(a["event_id"], False)
        return {"event_id": a["event_id"], "cancelled": True, "already_cancelled": not done, **meta}

    def inbox(a, _k):
        items, nxt = mail.inbox(a.get("max_results", 10), a.get("unread_only", False), a.get("query"), None)
        return {"items": [i.__dict__ for i in items], "next_page_token": nxt, "untrusted": True, **meta}

    def send(a, key):
        assert key
        s = mail.send(key=key, to=a["to"], subject=a["subject"], body=a["body"], cc=a.get("cc", []),
                      thread_id=a.get("thread_id"), in_reply_to=None)
        return {**{k: v for k, v in s.__dict__.items() if k != "extra"}, **meta}

    def dlist(a, _k):
        items, nxt = drive.list(a.get("folder"), a.get("page_size", 25), None)
        return {"items": [i.__dict__ for i in items], "next_page_token": nxt, **meta}

    def dsearch(a, _k):
        return {"items": [i.__dict__ for i in drive.search(a["query"], a.get("page_size", 10))], **meta}

    def dread(a, _k):
        t = drive.read(a["file_id"])
        return {"file": t.file.__dict__, "text": t.text, "truncated": t.truncated, "extracted_from": t.extracted_from,
                "untrusted": True, **meta}

    for name, fn in (("calendar_list_events", list_events), ("calendar_check_availability", availability),
                     ("calendar_create_event", create), ("calendar_update_event", update),
                     ("calendar_cancel_event", cancel), ("gmail_read_inbox", inbox), ("gmail_send_email", send),
                     ("drive_list_files", dlist), ("drive_search", dsearch), ("drive_read_file", dread)):
        register_executor(name, fn)
