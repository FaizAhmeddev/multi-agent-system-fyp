"""LLM access for agents.

OpenAILLM   used when OPENAI_API_KEY is set. Chat Completions with JSON mode for
            structured output; every structured answer is validated with Pydantic and
            retried once with the validation error, then refused (never passed on).
SandboxLLM  used otherwise. It never calls a network service and every answer it gives
            is labeled Simulated. Structured calls return None, so callers fall back
            to their deterministic rules and mark the result Simulated.

Models never do arithmetic in AgentsMind: totals, scores and dates are computed in code.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from .untrusted import SYSTEM_RULE

log = logging.getLogger("agentsmind.llm")
SIMULATED_LABEL = "Simulated"
M = TypeVar("M", bound=BaseModel)


class LLMError(Exception):
    """The model call failed or returned something unusable. The message is safe to show."""


@dataclass(frozen=True)
class LLMResult:
    text: str
    simulated: bool
    model: str


class LLM(Protocol):
    model: str
    simulated: bool

    def complete(self, prompt: str, *, temperature: float = 0.3, system: str | None = None) -> LLMResult: ...

    def complete_json(self, *, system: str, user: str, schema: type[M], temperature: float = 0.0) -> M | None: ...


class SandboxLLM:
    """Deterministic stand-in. Output says plainly that no model produced it."""

    model = "sandbox"
    simulated = True

    def complete(self, prompt: str, *, temperature: float = 0.3, system: str | None = None) -> LLMResult:
        first = next((ln.strip() for ln in prompt.splitlines() if ln.strip()), "")[:120]
        text = (f"[{SIMULATED_LABEL}] No language model is configured, so this is a placeholder, "
                f"not a real answer. The request was prepared correctly ({len(prompt)} characters; "
                f"starts with: \"{first}\"). Add OPENAI_API_KEY to .env for live answers.")
        return LLMResult(text=text, simulated=True, model=self.model)

    def complete_json(self, *, system: str, user: str, schema: type[M], temperature: float = 0.0) -> M | None:
        return None


class OpenAILLM:
    simulated = False

    def __init__(self, api_key: str, model: str, timeout: float = 30.0):
        from openai import OpenAI

        self.model = model
        self._client = OpenAI(api_key=api_key, timeout=timeout, max_retries=2)

    def _chat(self, messages: list[dict], temperature: float, json_mode: bool) -> str:
        import openai

        kw = {"response_format": {"type": "json_object"}} if json_mode else {}
        try:
            r = self._client.chat.completions.create(model=self.model, messages=messages, temperature=temperature, **kw)
        except openai.AuthenticationError as exc:
            raise LLMError("OpenAI rejected the API key. Check OPENAI_API_KEY in .env.") from exc
        except openai.RateLimitError as exc:
            raise LLMError("OpenAI rate limit or quota reached. Try again later.") from exc
        except openai.APITimeoutError as exc:
            raise LLMError("OpenAI did not answer in time.") from exc
        except openai.APIConnectionError as exc:
            raise LLMError("OpenAI is not reachable from this computer.") from exc
        except openai.APIError as exc:
            raise LLMError(f"OpenAI returned an error ({type(exc).__name__}).") from exc
        choice = r.choices[0]
        if choice.finish_reason == "content_filter":
            raise LLMError("The model refused this request.")
        text = (choice.message.content or "").strip()
        if not text:
            raise LLMError("The model returned an empty answer.")
        return text

    def complete(self, prompt: str, *, temperature: float = 0.3, system: str | None = None) -> LLMResult:
        msgs = [{"role": "system", "content": system or SYSTEM_RULE}, {"role": "user", "content": prompt}]
        return LLMResult(text=self._chat(msgs, temperature, json_mode=False), simulated=False, model=self.model)

    def complete_json(self, *, system: str, user: str, schema: type[M], temperature: float = 0.0) -> M | None:
        shape = json.dumps(schema.model_json_schema(), separators=(",", ":"))
        msgs = [{"role": "system", "content": f"{system}\n\n{SYSTEM_RULE}\n\nAnswer with one JSON object that "
                                              f"matches this JSON schema:\n{shape}"},
                {"role": "user", "content": user}]
        last: ValidationError | json.JSONDecodeError | None = None
        for _ in range(2):
            raw = self._chat(msgs, temperature, json_mode=True)
            try:
                return schema.model_validate_json(raw)
            except ValidationError as exc:
                last = exc
                msgs += [{"role": "assistant", "content": raw},
                         {"role": "user", "content": f"That JSON did not match the schema: {exc.errors()[:3]}. "
                                                     "Send corrected JSON only."}]
        log.warning("llm json invalid twice", extra={"schema": schema.__name__, "error": str(last)[:300]})
        raise LLMError("The model's answer did not have the expected structure, so it was not used.")


def get_llm() -> LLM:
    from ..settings import get_settings

    s = get_settings()
    if s.llm_configured:
        return OpenAILLM(s.openai_api_key.get_secret_value().strip(), s.openai_model)  # type: ignore[union-attr]
    return SandboxLLM()
