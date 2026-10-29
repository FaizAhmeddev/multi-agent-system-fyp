"""In-process tools (catalog server "core"): HR workflows run inside AgentsMind, not behind MCP."""
from __future__ import annotations

from typing import Any


def _run_workflow(args: dict[str, Any], key: str) -> dict[str, Any]:
    from ..db.session import SessionLocal
    from .workflows import run

    with SessionLocal() as db:
        return run(db, args, key or "no-key")


def register_core_executors() -> list[str]:
    from ..agents.gateway import register_executor

    register_executor("hr_run_workflow", _run_workflow)
    return ["hr_run_workflow"]
