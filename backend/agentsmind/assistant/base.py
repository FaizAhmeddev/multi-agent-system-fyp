"""Agent contract and the LangGraph graph every agent runs.

Graph (same shape for every agent, built with langgraph.graph.StateGraph):

    START -> understand --error--> fail -> END
                        --question--> clarify -> END
                        --ok--> gather --error--> fail
                                       --question--> clarify
                                       --proposals--> propose --error--> fail
                                                              --ok--> respond -> END
                                       --ok--> respond -> END

understand  parse the request into an intent and slots (rules; no tools)
gather      read tools only (lists, availability, searches) and build result cards
propose     the approval node: every write goes through the gateway, which records a
            pending Approval and returns its id; the card shows exactly what will run
respond     final text card (optional)
error       any exception in a node lands here with a safe message

Agents never call write tools directly. The gateway enforces allow-lists, roles and
approvals in code, and logs every call.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, TypedDict

from ..agents.llm import LLMError
from .cards import ApprovalInfo, Card, Detail

log = logging.getLogger("agentsmind.assistant")


@dataclass(frozen=True)
class UserInfo:
    id: int
    email: str
    name: str
    roles: tuple[str, ...]

    def has(self, *roles: str) -> bool:
        return "admin" in self.roles or any(r in self.roles for r in roles)


@dataclass
class ToolResult:
    status: str  # ok | error | denied | approval_required
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    code: str = ""
    approval_id: int | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


class Ctx(Protocol):
    user: UserInfo
    tz: str
    now: datetime
    llm: Any

    def read(self, agent: str, tool: str, args: dict[str, Any]) -> ToolResult: ...

    def propose(self, agent: str, tool: str, args: dict[str, Any], summary: str) -> ToolResult: ...

    def emit(self, event: dict[str, Any]) -> None: ...


@dataclass
class Proposal:
    tool: str
    args: dict[str, Any]
    summary: str
    details: list[Detail] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    simulated: bool = False
    confirm_text: str = ""


class AgentError(Exception):
    """A message that is safe to show the user."""


class State(TypedDict, total=False):
    text: str
    intent: str
    slots: dict[str, Any]
    question: str
    options: list[str]
    cards: list[Card]
    proposals: list[Proposal]
    reply: str
    error: str


class Agent:
    name = ""
    title = ""
    roles: frozenset[str] = frozenset()  # who may use the agent (admin always)
    examples: tuple[str, ...] = ()

    def score(self, text: str) -> float:
        raise NotImplementedError

    def understand(self, ctx: Ctx, state: State) -> State:
        raise NotImplementedError

    def gather(self, ctx: Ctx, state: State) -> State:
        return {}

    def respond(self, ctx: Ctx, state: State) -> State:
        return {}

    # helpers
    def read_or_raise(self, ctx: Ctx, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        r = ctx.read(self.name, tool, args)
        if r.status == "denied":
            raise AgentError(r.error or f"Not allowed to use {tool}.")
        if not r.ok:
            raise AgentError(r.error or f"{tool} failed.")
        return r.data


def _safe(fn: Callable[[State], State], name: str, agent: str) -> Callable[[State], State]:
    def node(state: State) -> State:
        try:
            return fn(state) or {}
        except (AgentError, LLMError) as exc:
            return {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001 - every failure becomes an error card, never a crash
            log.exception("agent node failed", extra={"agent": agent, "node": name})
            return {"error": f"Something went wrong in the {agent} agent ({type(exc).__name__})."}
    return node


def _jsonable(slots: dict[str, Any]) -> dict[str, Any]:
    """Slots kept with a clarifying question (stored as JSON until the user answers)."""
    import json

    try:
        return json.loads(json.dumps(slots, default=str))
    except (TypeError, ValueError):
        return {}


def build_graph(agent: Agent, ctx: Ctx):
    from langgraph.graph import END, START, StateGraph

    def understand(s: State) -> State:
        ctx.emit({"type": "step", "agent": agent.name, "node": "understand"})
        return agent.understand(ctx, s)

    def gather(s: State) -> State:
        ctx.emit({"type": "step", "agent": agent.name, "node": "gather"})
        return agent.gather(ctx, s)

    def propose(s: State) -> State:
        ctx.emit({"type": "step", "agent": agent.name, "node": "propose"})
        cards = list(s.get("cards", []))
        for p in s.get("proposals", []):
            r = ctx.propose(agent.name, p.tool, p.args, p.summary)
            if r.status == "approval_required" and r.approval_id:
                risk = "destructive" if p.confirm_text else "write"
                cards.append(Card(kind="approval", agent=agent.name, title=p.summary, simulated=p.simulated,
                                  warnings=p.warnings, data={"tool": p.tool, "arguments": p.args},
                                  approval=ApprovalInfo(id=r.approval_id, tool=p.tool, risk=risk, summary=p.summary,
                                                        details=p.details, confirm_text=p.confirm_text)))
            elif r.status == "denied":
                cards.append(Card(kind="denied", agent=agent.name, title="Not allowed", body=r.error))
            else:
                cards.append(Card(kind="error", agent=agent.name, title="Could not prepare the action",
                                  body=r.error or "Unknown error."))
        return {"cards": cards}

    def respond(s: State) -> State:
        out = agent.respond(ctx, s) or {}
        cards = list(out.get("cards", s.get("cards", [])))
        if s.get("reply"):
            cards.insert(0, Card(kind="text", agent=agent.name, title=agent.title, body=s["reply"]))
        return {"cards": cards}

    def clarify(s: State) -> State:
        cards = list(s.get("cards", []))
        cards.append(Card(kind="clarify", agent=agent.name, title="I need one more detail", body=s["question"],
                          options=list(s.get("options", [])),
                          data={"ask": s.get("ask", ""), "slots": _jsonable(s.get("slots") or {})}))
        return {"cards": cards}

    def error(s: State) -> State:
        cards = list(s.get("cards", []))
        cards.append(Card(kind="error", agent=agent.name, title=f"{agent.title}: could not finish", body=s["error"]))
        return {"cards": cards}

    # Node names must differ from state keys (LangGraph rule), so the error node is "fail".
    def after_understand(s: State) -> str:
        return "fail" if s.get("error") else "clarify" if s.get("question") else "gather"

    def after_gather(s: State) -> str:
        if s.get("error"):
            return "fail"
        if s.get("question"):
            return "clarify"
        return "propose" if s.get("proposals") else "respond"

    def after_propose(s: State) -> str:
        return "fail" if s.get("error") else "respond"

    g = StateGraph(State)
    for n, f in (("understand", understand), ("gather", gather), ("propose", propose), ("respond", respond),
                 ("clarify", clarify), ("fail", error)):
        g.add_node(n, _safe(f, n, agent.name) if n not in ("clarify", "fail") else f)
    g.add_edge(START, "understand")
    g.add_conditional_edges("understand", after_understand, {"fail": "fail", "clarify": "clarify", "gather": "gather"})
    g.add_conditional_edges("gather", after_gather,
                            {"fail": "fail", "clarify": "clarify", "propose": "propose", "respond": "respond"})
    g.add_conditional_edges("propose", after_propose, {"fail": "fail", "respond": "respond"})
    for n in ("respond", "clarify", "fail"):
        g.add_edge(n, END)
    return g.compile()


def run_agent(agent: Agent, ctx: Ctx, text: str, slots: dict[str, Any] | None = None) -> list[Card]:
    graph = build_graph(agent, ctx)
    final = graph.invoke({"text": text, "slots": dict(slots or {}), "cards": [], "proposals": []})
    return list(final.get("cards", []))
