"""Built-in queue task handlers."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .core import Task
from .registry import PermanentError, handler


@handler("agent.run")
def agent_run(task: Task) -> dict[str, Any]:
    from ..agents.runner import execute_run

    run_id = task.payload.get("run_id")
    if not isinstance(run_id, int):
        raise PermanentError("payload.run_id missing")
    return execute_run(run_id)


@handler("demo.append")
def demo_append(task: Task) -> dict[str, Any]:
    """Diagnostic task used by the crash/retry acceptance test.

    Optionally sleeps, then appends the task's effect key to a file, once. If a
    previous attempt already wrote it (crash after the write, before the ack), the
    write is skipped, so a retry never duplicates the effect.
    """
    path = Path(str(task.payload["path"]))
    time.sleep(float(task.payload.get("sleep", 0)))
    key = task.effect_key
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    if key not in existing:
        with path.open("a", encoding="utf-8") as f:
            f.write(key + "\n")
        wrote = True
    else:
        wrote = False
    return {"effect_key": key, "wrote": wrote, "attempt": task.attempts}
