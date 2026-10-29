"""Cards are what the assistant returns: text, clarifying questions, approval cards, results, errors.

The UI renders each kind differently. `simulated` is true whenever a sandbox backend or the
sandbox LLM produced the content, and the UI then shows a "Simulated" label.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

KINDS = ("text", "clarify", "approval", "result", "error", "denied", "fallback")


@dataclass
class Detail:
    label: str
    value: str


@dataclass
class ApprovalInfo:
    id: int
    tool: str
    risk: str  # write | destructive
    summary: str
    details: list[Detail] = field(default_factory=list)
    confirm_text: str = ""  # destructive: the user must tick/type this to confirm


@dataclass
class Card:
    kind: str
    agent: str
    title: str
    body: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    simulated: bool = False
    untrusted: bool = False
    warnings: list[str] = field(default_factory=list)
    options: list[str] = field(default_factory=list)
    links: list[dict[str, str]] = field(default_factory=list)
    approval: ApprovalInfo | None = None

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"unknown card kind {self.kind}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
