"""Task handler registry (kept apart from worker.py so `python -m ...worker` sees the same dict)."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .core import Task

Handler = Callable[[Task], dict[str, Any]]
HANDLERS: dict[str, Handler] = {}


def handler(kind: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        HANDLERS[kind] = fn
        return fn
    return deco


class PermanentError(Exception):
    """Raise from a handler when retrying cannot help (bad input, forbidden). Goes straight to dead."""
