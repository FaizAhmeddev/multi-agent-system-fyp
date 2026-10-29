"""Orchestrator: turn one message into a plan of agent steps and run them.

Planning is rule-based and deterministic: the message is split into clauses ("... and
then ...", "; ", "also") and each clause goes to the agent whose vocabulary matches it
best, with a boost for the leading verb. If no agent matches and a language model is
configured, the model may pick an agent (validated against the list); otherwise the
user gets a fallback card listing what AgentsMind can do.

Every step is checked against the user's roles in code before its agent runs.
Clarifying questions are remembered as `pending`, so the next message can answer them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

from .agents.calendar import CalendarAgent
from .agents.documents import DocumentsAgent
from .agents.email import EmailAgent
from .agents.finance import FinanceAgent
from .agents.hr import HRAgent
from .agents.it import ITAgent
from .base import Agent, Ctx, run_agent
from .cards import Card

AGENT_LIST: list[Agent] = [HRAgent(), FinanceAgent(), ITAgent(), CalendarAgent(), EmailAgent(), DocumentsAgent()]
AGENTS: dict[str, Agent] = {a.name: a for a in AGENT_LIST}
DEPARTMENT_OF = {"hr": "HR", "finance": "Finance", "it": "IT", "calendar": "Communications",
                 "email": "Communications", "documents": "Documents"}
VERB_BOOST = [
    (r"^(?:please\s+)?(?:schedule|book|reschedule|move|set up a (?:meeting|call)|am i free|cancel (?:my|the|\w+'s)?\s*"
     r"(?:\w+\s)?(?:meeting|call|event|review|sync))", "calendar"),
    (r"^(?:please\s+)?(?:send|email|reply|respond|draft (?:a |an )?(?:reply|email|response)|check my (?:inbox|email))",
     "email"),
    (r"^(?:please\s+)?(?:raise|report|log|open|file)\b.*\b(?:ticket|complaint|issue|problem)", "it"),
    (r"^(?:please\s+)?(?:summari[sz]e|find (?:the )?(?:file|document)|search (?:drive|files|documents))", "documents"),
    (r"^(?:please\s+)?(?:screen|rank|shortlist)\b", "hr"),
]
SPLIT_RE = re.compile(r"\s*(?:;|\band then\b|\bthen\b|\balso\b|\bafter that\b|\.\s+(?=[A-Z]))\s*", re.I)


@dataclass
class Step:
    agent: str
    text: str
    score: float


@dataclass
class TurnResult:
    cards: list[Card]
    steps: list[Step]
    pending: dict[str, Any] | None = None
    planner: str = "rules"
    meta: dict[str, Any] = field(default_factory=dict)


def score_all(text: str) -> dict[str, float]:
    t = text.strip().lower()
    scores = {a.name: a.score(text) for a in AGENT_LIST}
    for rx, name in VERB_BOOST:
        if re.search(rx, t):
            scores[name] += 1.5
    return scores


def _best(text: str) -> tuple[str | None, float]:
    sc = score_all(text)
    name = max(AGENT_LIST, key=lambda a: sc[a.name]).name  # ties: AGENT_LIST order (most specific first)
    return (name, sc[name]) if sc[name] > 0 else (None, 0.0)


def _clauses(text: str) -> list[str]:
    parts = [p.strip(" ,.") for p in SPLIT_RE.split(text) if p and p.strip(" ,.")]
    out: list[str] = []
    for p in parts:
        # " and " splits only when both halves clearly belong to different agents
        bits = re.split(r"\s+and\s+(?=(?:please\s+)?(?:schedule|book|send|email|reply|raise|report|log|find|"
                        r"screen|cancel|move|check|show|list|create|add|update|delete)\b|summari[sz]e)", p, flags=re.I)
        if len(bits) > 1:
            names = [_best(b)[0] for b in bits]
            if all(names) and len(set(names)) > 1:
                out.extend(b.strip(" ,.") for b in bits)
                continue
        out.append(p)
    return out


def plan(text: str) -> list[Step]:
    steps: list[Step] = []
    for c in _clauses(text):
        name, sc = _best(c)
        if name is None:
            if steps:  # a clause with no signal of its own belongs to the previous step
                steps[-1].text = f"{steps[-1].text}, {c}"
            continue
        steps.append(Step(name, c, sc))
    if len(steps) == 1:
        steps[0].text = text.strip()  # one agent: give it the whole message
    return steps


class RouteOut(BaseModel):
    agent: Literal["hr", "finance", "it", "calendar", "email", "documents", "none"]
    reason: str = Field(default="", max_length=200)


def llm_route(ctx: Ctx, text: str) -> str | None:
    llm = ctx.llm
    if getattr(llm, "simulated", True):
        return None
    menu = "\n".join(f"- {a.name}: {a.title}. Examples: {'; '.join(a.examples[:3])}" for a in AGENT_LIST)
    try:
        out = llm.complete_json(system="Route an office request to one agent, or 'none' if no agent fits.",
                                user=f"Agents:\n{menu}\n\nRequest:\n{text[:2000]}", schema=RouteOut)
    except Exception:  # noqa: BLE001 - routing is best effort; fall back to the capabilities card
        return None
    return out.agent if out and out.agent != "none" else None


def allowed(ctx: Ctx, agent: Agent) -> bool:
    return ctx.user.has(*agent.roles)


def fallback_card(ctx: Ctx) -> Card:
    usable = [a for a in AGENT_LIST if allowed(ctx, a)]
    lines = [f"{a.title}: {'; '.join(a.examples[:2])}" for a in usable]
    return Card(kind="fallback", agent="orchestrator", title="I am not sure which department this is for",
                body="I can help with these. Try one of the examples, or rephrase your request.",
                options=[a.examples[0] for a in usable], data={"capabilities": lines})


def run_turn(ctx: Ctx, text: str, pending: dict[str, Any] | None = None) -> TurnResult:
    text = text.strip()
    planner = "rules"
    if pending and pending.get("agent") in AGENTS:
        other, sc = _best(text)
        if other in (None, pending["agent"]) or sc < 2:
            steps = [Step(pending["agent"], f"{pending['text']} {text}", 0.0)]
            planner = "clarification"
        else:
            steps = plan(text)
    else:
        steps = plan(text)
    if not steps:
        routed = llm_route(ctx, text)
        if routed:
            steps, planner = [Step(routed, text, 0.0)], "llm"
    if not steps:
        ctx.emit({"type": "plan", "steps": []})
        return TurnResult(cards=[fallback_card(ctx)], steps=[], planner="fallback")
    ctx.emit({"type": "plan", "steps": [{"agent": s.agent, "text": s.text} for s in steps]})
    cards: list[Card] = []
    new_pending = None
    for st in steps:
        agent = AGENTS[st.agent]
        if not allowed(ctx, agent):
            note = getattr(ctx, "note_denied", None)
            if note is not None:
                note(agent.name, st.text)
            cards.append(Card(kind="denied", agent=agent.name, title=f"{DEPARTMENT_OF[agent.name]} is not available "
                                                                     "to your role",
                              body=f"Your role cannot use the {agent.title}. Ask an administrator if you need access."))
            continue
        ctx.emit({"type": "agent", "agent": agent.name, "text": st.text})
        out = run_agent(agent, ctx, st.text)
        cards.extend(out)
        if new_pending is None and out and out[-1].kind == "clarify":
            new_pending = {"agent": agent.name, "text": st.text}
    return TurnResult(cards=cards, steps=steps, pending=new_pending, planner=planner)
