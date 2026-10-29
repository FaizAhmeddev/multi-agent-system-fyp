"""A fake assistant context: tools run against the real sandbox backends in-process.

Reads go straight to the sandbox calendar / inbox / drive; writes are recorded as
proposals (pending approvals) exactly like the gateway does, and can be "approved"
to run them.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from agentsmind.agents.catalog import AGENT_TOOLS, READ, TOOLS
from agentsmind.agents.llm import SandboxLLM
from agentsmind.assistant.base import ToolResult, UserInfo

TZ = "Asia/Karachi"


class FakeCtx:
    def __init__(self, tmp_path, *, roles=("employee",), now=None, tools: dict[str, Any] | None = None, llm=None):
        self.user = UserInfo(id=7, email="sana.employee@example.com", name="Sana Employee", roles=tuple(roles))
        self.tz = TZ
        self.now = now or datetime(2026, 10, 28, 11, 0, tzinfo=ZoneInfo(TZ))
        self.llm = llm or SandboxLLM()
        self.events: list[dict] = []
        self.approvals: list[dict] = []
        self.reads: list[tuple[str, dict]] = []
        self.denied: list[tuple[str, str]] = []
        self.tools = tools or {}
        self.tmp = tmp_path
        self._cal = None

    @property
    def cal(self):
        if self._cal is None:
            from mcp_servers.calendar_mcp.backends import SandboxCalendar
            self._cal = SandboxCalendar(self.tmp / "cal.db")
        return self._cal

    def _check(self, agent, tool):
        spec = TOOLS.get(tool)
        if spec is None or tool not in AGENT_TOOLS.get(agent, ()):
            self.denied.append((agent, tool))
            return ToolResult(status="denied", code="not_allowed_for_agent",
                              error=f"The {agent} agent is not allowed to use {tool}.")
        if not ("admin" in self.user.roles or set(self.user.roles) & spec.roles):
            self.denied.append((agent, tool))
            return ToolResult(status="denied", code="role_forbidden", error=f"Your role cannot use {tool}.")
        return None

    def read(self, agent, tool, args):
        bad = self._check(agent, tool)
        if bad:
            return bad
        assert TOOLS[tool].risk == READ, f"{tool} is not a read tool"
        self.reads.append((tool, args))
        if tool in self.tools:
            return ToolResult(status="ok", data=self.tools[tool](args))
        if tool.startswith("calendar_"):
            return ToolResult(status="ok", data=self._calendar(tool, args))
        raise AssertionError(f"no fake for {tool}")

    def _calendar(self, tool, a):
        c = self.cal
        if tool == "calendar_list_events":
            items, nxt = c.list_events(datetime.fromisoformat(a["time_min"]), datetime.fromisoformat(a["time_max"]),
                                       a.get("query"), a.get("max_results", 25), None)
            return {"items": [e.__dict__ for e in items], "next_page_token": nxt, "mode": "sandbox", "simulated": True}
        s, e = datetime.fromisoformat(a["start"]), datetime.fromisoformat(a["end"])
        busy = c.busy(s, e)
        conflicts, _ = c.list_events(s, e, None, 20, None)
        return {"is_free": not busy, "busy": [{"start": x, "end": y} for x, y in busy],
                "conflicts": [e.__dict__ for e in conflicts], "mode": "sandbox", "simulated": True}

    def propose(self, agent, tool, args, summary):
        bad = self._check(agent, tool)
        if bad:
            return bad
        assert TOOLS[tool].risk != READ
        self.approvals.append({"id": len(self.approvals) + 1, "agent": agent, "tool": tool, "args": args,
                               "summary": summary})
        return ToolResult(status="approval_required", approval_id=len(self.approvals), code="approval_required")

    def emit(self, event):
        self.events.append(event)

    def add_event(self, title, start, minutes=60):
        from datetime import timedelta
        s = datetime.fromisoformat(start).replace(tzinfo=ZoneInfo(TZ)) if "+" not in start else datetime.fromisoformat(start)
        ev, _ = self.cal.create(key=f"k-{title}-{start}", summary=title, start=s, end=s + timedelta(minutes=minutes), tz=TZ,
                                description="", location="", attendees=[], add_meet=False, notify=False)
        return ev
