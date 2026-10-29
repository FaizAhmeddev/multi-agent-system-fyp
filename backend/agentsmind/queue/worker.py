"""Queue worker.

    python -m agentsmind.queue.worker            # run until Ctrl+C
    python -m agentsmind.queue.worker --once     # process at most one task, then exit

Run from the repo root with backend on the path, for example:
    .venv\\Scripts\\python -m agentsmind.queue.worker   (with PYTHONPATH=backend)
"""
from __future__ import annotations

import argparse
import logging
import signal
import threading
import time

from .core import QueueBackend, Task, get_queue, new_worker_id
from .registry import HANDLERS, PermanentError

log = logging.getLogger("agentsmind.worker")

class Worker:
    def __init__(self, q: QueueBackend | None = None, *, queue: str = "default", worker_id: str | None = None,
                 lease_seconds: int | None = None, poll_seconds: float = 1.0):
        self.q = q or get_queue()
        self.queue = queue
        self.worker_id = worker_id or new_worker_id()
        self.lease_seconds = lease_seconds or getattr(self.q, "lease_seconds", 60)
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()

    def stop(self, *_a) -> None:
        self._stop.set()

    def _heartbeat(self, task: Task, done: threading.Event) -> None:
        interval = max(1.0, self.lease_seconds / 3)
        while not done.wait(interval):
            if not self.q.extend(task.id, self.worker_id, self.lease_seconds):
                log.warning("lease lost", extra={"task_id": task.id, "worker": self.worker_id})
                return

    def run_once(self) -> Task | None:
        task = self.q.lease(self.worker_id, queue=self.queue, lease_seconds=self.lease_seconds)
        if task is None:
            return None
        fn = HANDLERS.get(task.kind)
        log.info("task leased", extra={"task_id": task.id, "kind": task.kind, "attempt": task.attempts,
                                       "worker": self.worker_id})
        if fn is None:
            self.q.nack(task.id, self.worker_id, f"no handler for kind '{task.kind}'", retry=False)
            return self.q.get(task.id)
        done = threading.Event()
        hb = threading.Thread(target=self._heartbeat, args=(task, done), daemon=True)
        hb.start()
        start = time.perf_counter()
        try:
            result = fn(task) or {}
        except PermanentError as exc:
            done.set()
            self.q.nack(task.id, self.worker_id, f"PermanentError: {exc}", retry=False)
            log.warning("task failed permanently", extra={"task_id": task.id, "error": str(exc)})
        except Exception as exc:  # noqa: BLE001 - any handler failure is retried with backoff
            done.set()
            status = self.q.nack(task.id, self.worker_id, f"{type(exc).__name__}: {exc}")
            log.warning("task failed", extra={"task_id": task.id, "error": str(exc), "next": status})
        else:
            done.set()
            ok = self.q.ack(task.id, self.worker_id, result)
            ms = int((time.perf_counter() - start) * 1000)
            log.info("task done" if ok else "late ack ignored (lease lost)",
                     extra={"task_id": task.id, "latency_ms": ms, "acked": ok})
        return self.q.get(task.id)

    def run_forever(self) -> None:
        log.info("worker started", extra={"worker": self.worker_id, "queue": self.queue})
        while not self._stop.is_set():
            if self.run_once() is None:
                self._stop.wait(self.poll_seconds)
        log.info("worker stopped", extra={"worker": self.worker_id})


def main(argv: list[str] | None = None) -> int:
    from ..log_config import configure_logging
    from ..settings import get_settings
    from . import handlers  # noqa: F401  (register built-in handlers)

    p = argparse.ArgumentParser(description="AgentsMind queue worker")
    p.add_argument("--queue", default="default")
    p.add_argument("--once", action="store_true")
    p.add_argument("--lease", type=int, default=None, help="lease seconds (default from settings)")
    p.add_argument("--worker-id", default=None)
    a = p.parse_args(argv)
    s = get_settings()
    configure_logging(s.log_level, s.log_json)
    if s.queue_backend != "db":
        log.warning("QUEUE_BACKEND=memory: a separate worker process cannot see API tasks; use db")
    from ..hr.tools import register_core_executors
    from ..mcp.client import register_mcp_executors

    register_mcp_executors()
    register_core_executors()
    w = Worker(queue=a.queue, worker_id=a.worker_id, lease_seconds=a.lease)
    signal.signal(signal.SIGINT, w.stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, w.stop)
    if a.once:
        w.run_once()
    else:
        w.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
