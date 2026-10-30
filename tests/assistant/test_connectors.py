"""Connector hub: any MCP server from connectors.json is discovered, made safe and used by the assistant."""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent


@pytest.fixture
def hub(tmp_path, monkeypatch):
    try:
        import agentsmind.agents.gateway as gateway  # noqa: F401
    except ImportError:  # the cloud workspace has no SQLAlchemy: a stand-in executor registry
        g = types.ModuleType("agentsmind.agents.gateway")
        g.EXECUTORS = {}
        g.register_executor = lambda n, f: g.EXECUTORS.__setitem__(n, f)
        monkeypatch.setitem(sys.modules, "agentsmind.agents.gateway", g)
    cfg = tmp_path / "connectors.json"
    cfg.write_text(json.dumps({"connectors": [
        {"name": "demo", "title": "Demo Chat", "transport": "stdio", "command": sys.executable,
         "args": [str(HERE / "fixtures" / "demo_mcp_server.py")], "keywords": ["demo chat", "channel"],
         "blocked_tools": ["secret_admin"], "roles": ["hr", "employee"], "description": "Team chat"},
        {"name": "needs", "transport": "http", "url": "https://x.example/mcp",
         "headers": {"Authorization": "Bearer ${NEEDS_TOKEN_FOR_TEST}"}},
    ]}))
    monkeypatch.setenv("CONNECTORS_FILE", str(cfg))
    monkeypatch.setenv("AGENTSMIND_ENV_FILE", "")
    from agentsmind.mcp import connectors as C

    C._cache.clear()
    yield C
    for c in ("demo", "needs"):
        C.unregister(c)
        C.POOL.close(c)


def test_discovery_and_risk(hub):
    from agentsmind.agents.catalog import AGENT_TOOLS, TOOLS

    d = {n: x for n, x in hub.discover_all(force=True).items()}
    assert not d["demo"].error
    risks = {t["name"]: t["risk"] for t in d["demo"].tools}
    assert risks == {"list_channels": "read", "get_messages": "read", "post_message": "write",
                     "delete_channel": "destructive"}  # secret_admin is blocked
    assert {"demo.list_channels", "demo.post_message"} <= AGENT_TOOLS["connectors"]
    assert TOOLS["demo.post_message"].roles == frozenset({"hr", "employee"})
    assert "NEEDS_TOKEN_FOR_TEST" in d["needs"].error
    out = hub.call("demo", "post_message", {"channel": "hr", "text": "hi"})
    assert out["text"] == "posted to hr: hi" and out["untrusted"]


class ScriptLLM:
    simulated = False

    def __init__(self, steps):
        self.steps, self.prompts = list(steps), []

    def complete_json(self, *, system, user, schema, temperature=0.0):
        self.prompts.append(user)
        return schema(**self.steps.pop(0))


def _ctx(tmp_path, llm, hub):
    from fakectx import FakeCtx

    tools = {f"demo.{t}": (lambda a, _t=t: hub.call("demo", _t, a)) for t in ("list_channels", "get_messages")}
    return FakeCtx(tmp_path, roles=("hr",), llm=llm, tools=tools)


def test_read_then_answer(hub, tmp_path):
    from agentsmind.assistant.orchestrator import plan, run_turn

    hub.discover_all(force=True)
    assert [s.agent for s in plan("What are the latest messages in the hr channel on Demo Chat?")] == ["connectors"]
    llm = ScriptLLM([{"action": "call", "tool": "get_messages", "arguments": {"channel": "hr"}},
                     {"action": "answer", "text": "The latest message says payroll is ready."}])
    r = run_turn(_ctx(tmp_path, llm, hub), "What are the latest messages in the hr channel on Demo Chat?")
    c = r.cards[0]
    assert c.kind == "text" and "payroll is ready" in c.body and c.untrusted
    assert any("addressed to an AI" in w for w in c.warnings)
    assert "payroll is ready" in llm.prompts[1]  # the tool result went back to the model


def test_write_needs_approval_and_bad_args_are_retried(hub, tmp_path):
    from agentsmind.assistant.orchestrator import run_turn

    hub.discover_all(force=True)
    llm = ScriptLLM([{"action": "call", "tool": "post_message", "arguments": {"channel": "hr"}},
                     {"action": "call", "tool": "post_message", "arguments": {"channel": "hr", "text": "Payroll done"}}])
    ctx = _ctx(tmp_path, llm, hub)
    r = run_turn(ctx, "Post 'Payroll done' in the hr channel on Demo Chat")
    card = r.cards[0]
    assert card.kind == "approval" and card.approval.tool == "demo.post_message"
    assert ctx.approvals[0]["args"] == {"channel": "hr", "text": "Payroll done"}
    assert "rejected" in llm.prompts[1]  # the first call missed 'text' and was sent back


def test_without_a_model_the_tools_are_listed(hub, tmp_path):
    from agentsmind.assistant.orchestrator import run_turn

    hub.discover_all(force=True)
    r = run_turn(_ctx(tmp_path, SimpleNamespace(simulated=True), hub), "Use Demo Chat to list channels")
    assert r.cards[0].kind == "result" and {x["tool"] for x in r.cards[0].data["rows"]} >= {"post_message"}
