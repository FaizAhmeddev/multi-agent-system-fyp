"""Shared OpenAI chat client with clear configuration errors."""

from __future__ import annotations

import os


def get_chat_openai(*, temperature: float = 0.3, model: str = "gpt-4o-mini"):
    from langchain_openai import ChatOpenAI

    from config import OPENAI_API_KEY, is_openai_configured, openai_missing_message

    if not is_openai_configured():
        raise RuntimeError(openai_missing_message("AI assistant"))
    os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY
    return ChatOpenAI(model=model, temperature=temperature)
