"""Central logging setup for FYP_FINAL (console + logs/orchestrator.log)."""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler


_CONFIGURED = False


def configure_logging(log_dir: str | None = None) -> None:
    """Configure root + orchestrator loggers once per process."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    root = log_dir or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
    os.makedirs(root, exist_ok=True)
    log_path = os.path.join(root, "orchestrator.log")

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(fmt)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    if not root_logger.handlers:
        root_logger.addHandler(console)
        root_logger.addHandler(file_handler)

    orch = logging.getLogger("orchestrator")
    orch.setLevel(logging.INFO)

    _CONFIGURED = True
