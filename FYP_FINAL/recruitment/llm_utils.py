"""Shared LLM helpers for recruitment agents."""

from __future__ import annotations

import json
import os
import re
from typing import Any


def get_chat_llm(temperature: float = 0.1):
    from langchain_openai import ChatOpenAI
    from config import OPENAI_API_KEY

    os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY
    return ChatOpenAI(model="gpt-4o-mini", temperature=temperature)


def strip_json_fence(text: str) -> str:
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*```\s*$", "", t)
    return t.strip()


def parse_json_object(text: str) -> dict[str, Any]:
    raw = strip_json_fence(text)
    return json.loads(raw)


def invoke_json(llm, prompt: str, max_retries: int = 2) -> dict[str, Any]:
    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            resp = llm.invoke(prompt)
            return parse_json_object(resp.content)
        except Exception as e:
            last_err = e
            prompt = prompt + "\n\nReturn ONLY one valid JSON object. No markdown."
    raise last_err or ValueError("LLM JSON parse failed")
