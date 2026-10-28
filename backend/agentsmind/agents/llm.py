"""LLM access for agents.

Phase 1b ships only the sandbox client: it never calls a network service and every
answer it gives is labeled Simulated. The live OpenAI client arrives in Phase 3,
after the API is verified against the official docs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

SIMULATED_LABEL = "Simulated"


@dataclass(frozen=True)
class LLMResult:
    text: str
    simulated: bool
    model: str


class LLM(Protocol):
    def complete(self, prompt: str, *, temperature: float = 0.3) -> LLMResult: ...


class SandboxLLM:
    """Deterministic stand-in. Output says plainly that no model produced it."""

    model = "sandbox"

    def complete(self, prompt: str, *, temperature: float = 0.3) -> LLMResult:
        first = next((ln.strip() for ln in prompt.splitlines() if ln.strip()), "")[:120]
        text = (f"[{SIMULATED_LABEL}] No language model is configured, so this is a placeholder, "
                f"not a real answer. The request was prepared correctly ({len(prompt)} characters; "
                f"starts with: \"{first}\"). Live model output is enabled in Phase 3.")
        return LLMResult(text=text, simulated=True, model=self.model)


def get_llm() -> LLM:
    return SandboxLLM()
