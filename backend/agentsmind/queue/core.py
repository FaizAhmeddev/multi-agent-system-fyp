"""Work queue with leases, acknowledgements, retries with backoff and a dead-letter state.

Two interchangeable backends (QUEUE_BACKEND):
  - db:     rows in `queue_tasks`; survives restarts; safe for several workers.
  - memory: in-process; for tests and quick demos only; lost on restart.

Delivery is at-least-once. A task whose worker dies is re-delivered after its lease
expires. Handlers get a stable `idempotency_key` per task so side effects can be
made exactly-once (for example a create call to an external system).
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError

from ..db.base import utcnow
from ..db.models import QueueTask
from ..db.session import SessionLocal

PENDING, LEASED, DONE, DEAD = "pending", "leased", "done", "dead"
STATUSES = (PENDING, LEASED, DONE, DEAD)
MAX_BACKOFF_SECONDS = 300.0


@dataclass
class Task:
    id: int
    queue: str
    kind: str
    payload: dict[str, Any]
    status: str
    attempts: int
    max_attempts: int
    available_at: datetime
    lease_owner: str | None = None
    leased_until: datetime | None = None
    last_error: str = ""
    result: dict[str, Any] | None = None
    idempotency_key: str | None = None
    created_by_user_id: int | None = None
    created_at: datetime = field(default_factory=utcnow)
    finished_at: datetime | None = None

    @property
    def effect_key(self) -> str:
        """Stable key for making this task's side effects idempotent."""
        return self.idempotency_key or f"queue-task-{self.id}"


def backoff_seconds(attempts: int, base: float) -> float:
    """Exponential backoff: base, 2*base, 4*base ... capped at 5 minutes."""
    if attempts <= 0 or base <= 0:
        return 0.0
    return min(base * (2 ** (attempts - 1)), MAX_BACKOFF_SECONDS)


class QueueBackend(Protocol):
    def enqueue(self, kind: str, payload: dict[str, Any], *, queue: str = "default",
                idempotency_key: str | None = None, max_attempts: int | None = None,
                created_by_user_id: int | None = None, delay_seconds: float = 0) -> Task: ...
    def lease(self, worker_id: str, *, queue: str = "default", lease_seconds: int | None = None) -> Task | None: ...
    def extend(self, task_id: int, worker_id: str, lease_seconds: int) -> bool: ...
    def ack(self, task_id: int, worker_id: str, result: dict[str, Any] | None = None) -> bool: ...
    def nack(self, task_id: int, worker_id: str, error: str, *, retry: bool = True) -> str | None: ...
    def get(self, task_id: int) -> Task | None: ...
    def retry_dead(self, task_id: int) -> bool: ...
    def stats(self) -> dict[str, dict[str, int]]: ...
    def list(self, *, status: str | None = None, queue: str | None = None, limit: int = 50,
             offset: int = 0) -> list[Task]: ...


def _view(row: QueueTask) -> Task:
    return Task(id=row.id, queue=row.queue, kind=row.kind, payload=dict(row.payload or {}), status=row.status,
                attempts=row.attempts, max_attempts=row.max_attempts, available_at=row.available_at,
                lease_owner=row.lease_owner, leased_until=row.leased_until, last_error=row.last_error,
                result=row.result, idempotency_key=row.idempotency_key, created_by_user_id=row.created_by_user_id,
                created_at=row.created_at, finished_at=row.finished_at)


class DBQueue:
    def __init__(self, *, lease_seconds: int, backoff_base: float, max_attempts: int):
        self.lease_seconds = lease_seconds
        self.backoff_base = backoff_base
        self.max_attempts = max_attempts

    def enqueue(self, kind, payload, *, queue="default", idempotency_key=None, max_attempts=None,
                created_by_user_id=None, delay_seconds=0):
        with SessionLocal() as db:
            if idempotency_key:
                existing = db.scalar(select(QueueTask).where(QueueTask.idempotency_key == idempotency_key))
                if existing is not None:
                    return _view(existing)
            row = QueueTask(queue=queue, kind=kind, payload=payload, status=PENDING, attempts=0,
                            max_attempts=max_attempts or self.max_attempts,
                            available_at=utcnow() + timedelta(seconds=delay_seconds), last_error="",
                            idempotency_key=idempotency_key, created_by_user_id=created_by_user_id)
            db.add(row)
            try:
                db.commit()
            except IntegrityError:  # lost a race on the same idempotency key
                db.rollback()
                existing = db.scalar(select(QueueTask).where(QueueTask.idempotency_key == idempotency_key))
                assert existing is not None
                return _view(existing)
            return _view(row)

    def lease(self, worker_id, *, queue="default", lease_seconds=None):
        secs = lease_seconds or self.lease_seconds
        with SessionLocal() as db:
            for _ in range(5):  # retry if another worker claimed the candidate first
                now = utcnow()
                cand = db.scalar(
                    select(QueueTask)
                    .where(QueueTask.queue == queue,
                           or_((QueueTask.status == PENDING) & (QueueTask.available_at <= now),
                               (QueueTask.status == LEASED) & (QueueTask.leased_until < now)))
                    .order_by(QueueTask.available_at, QueueTask.id)
                    .limit(1)
                )
                if cand is None:
                    return None
                if cand.attempts >= cand.max_attempts:
                    # Its last allowed attempt was leased and never acknowledged.
                    db.execute(update(QueueTask).where(QueueTask.id == cand.id, QueueTask.status == cand.status)
                               .values(status=DEAD, lease_owner=None, leased_until=None, finished_at=now,
                                       last_error=(cand.last_error or "lease expired on final attempt")))
                    db.commit()
                    continue
                res = db.execute(
                    update(QueueTask)
                    .where(QueueTask.id == cand.id, QueueTask.status == cand.status,
                           QueueTask.attempts == cand.attempts)
                    .values(status=LEASED, lease_owner=worker_id, leased_until=now + timedelta(seconds=secs),
                            attempts=cand.attempts + 1, updated_at=now)
                )
                db.commit()
                if res.rowcount == 1:
                    db.expire_all()
                    row = db.get(QueueTask, cand.id)
                    return _view(row)
            return None

    def extend(self, task_id, worker_id, lease_seconds):
        with SessionLocal() as db:
            res = db.execute(update(QueueTask)
                             .where(QueueTask.id == task_id, QueueTask.lease_owner == worker_id,
                                    QueueTask.status == LEASED)
                             .values(leased_until=utcnow() + timedelta(seconds=lease_seconds)))
            db.commit()
            return res.rowcount == 1

    def ack(self, task_id, worker_id, result=None):
        with SessionLocal() as db:
            now = utcnow()
            res = db.execute(update(QueueTask)
                             .where(QueueTask.id == task_id, QueueTask.lease_owner == worker_id,
                                    QueueTask.status == LEASED)
                             .values(status=DONE, result=result or {}, lease_owner=None, leased_until=None,
                                     finished_at=now, updated_at=now, last_error=""))
            db.commit()
            return res.rowcount == 1

    def nack(self, task_id, worker_id, error, *, retry=True):
        with SessionLocal() as db:
            row = db.get(QueueTask, task_id)
            if row is None or row.lease_owner != worker_id or row.status != LEASED:
                return None
            now = utcnow()
            if not retry or row.attempts >= row.max_attempts:
                new_status, avail, fin = DEAD, row.available_at, now
            else:
                new_status = PENDING
                avail = now + timedelta(seconds=backoff_seconds(row.attempts, self.backoff_base))
                fin = None
            res = db.execute(update(QueueTask)
                             .where(QueueTask.id == task_id, QueueTask.lease_owner == worker_id,
                                    QueueTask.status == LEASED)
                             .values(status=new_status, available_at=avail, lease_owner=None, leased_until=None,
                                     last_error=str(error)[:4000], finished_at=fin, updated_at=now))
            db.commit()
            return new_status if res.rowcount == 1 else None

    def get(self, task_id):
        with SessionLocal() as db:
            row = db.get(QueueTask, task_id)
            return _view(row) if row else None

    def retry_dead(self, task_id):
        with SessionLocal() as db:
            res = db.execute(update(QueueTask).where(QueueTask.id == task_id, QueueTask.status == DEAD)
                             .values(status=PENDING, attempts=0, available_at=utcnow(), finished_at=None))
            db.commit()
            return res.rowcount == 1

    def stats(self):
        out: dict[str, dict[str, int]] = {}
        with SessionLocal() as db:
            for q, status, n in db.execute(select(QueueTask.queue, QueueTask.status, func.count(QueueTask.id))
                                           .group_by(QueueTask.queue, QueueTask.status)):
                out.setdefault(q, dict.fromkeys(STATUSES, 0))[status] = n
        return out

    def list(self, *, status=None, queue=None, limit=50, offset=0):
        with SessionLocal() as db:
            q = select(QueueTask).order_by(QueueTask.id.desc()).limit(limit).offset(offset)
            if status:
                q = q.where(QueueTask.status == status)
            if queue:
                q = q.where(QueueTask.queue == queue)
            return [_view(r) for r in db.scalars(q)]


class MemoryQueue:
    """Same semantics as DBQueue, in process memory. Not durable."""

    def __init__(self, *, lease_seconds: int, backoff_base: float, max_attempts: int):
        self.lease_seconds = lease_seconds
        self.backoff_base = backoff_base
        self.max_attempts = max_attempts
        self._lock = threading.Lock()
        self._tasks: dict[int, Task] = {}
        self._next = 1

    def enqueue(self, kind, payload, *, queue="default", idempotency_key=None, max_attempts=None,
                created_by_user_id=None, delay_seconds=0):
        with self._lock:
            if idempotency_key:
                for t in self._tasks.values():
                    if t.idempotency_key == idempotency_key:
                        return t
            t = Task(id=self._next, queue=queue, kind=kind, payload=dict(payload), status=PENDING, attempts=0,
                     max_attempts=max_attempts or self.max_attempts,
                     available_at=utcnow() + timedelta(seconds=delay_seconds),
                     idempotency_key=idempotency_key, created_by_user_id=created_by_user_id)
            self._tasks[t.id] = t
            self._next += 1
            return t

    def lease(self, worker_id, *, queue="default", lease_seconds=None):
        secs = lease_seconds or self.lease_seconds
        with self._lock:
            now = utcnow()
            for t in sorted(self._tasks.values(), key=lambda x: (x.available_at, x.id)):
                if t.queue != queue:
                    continue
                ready = (t.status == PENDING and t.available_at <= now) or (
                    t.status == LEASED and t.leased_until is not None and t.leased_until < now)
                if not ready:
                    continue
                if t.attempts >= t.max_attempts:
                    t.status, t.lease_owner, t.leased_until, t.finished_at = DEAD, None, None, now
                    t.last_error = t.last_error or "lease expired on final attempt"
                    continue
                t.status, t.lease_owner = LEASED, worker_id
                t.leased_until, t.attempts = now + timedelta(seconds=secs), t.attempts + 1
                return t
            return None

    def extend(self, task_id, worker_id, lease_seconds):
        with self._lock:
            t = self._tasks.get(task_id)
            if t and t.status == LEASED and t.lease_owner == worker_id:
                t.leased_until = utcnow() + timedelta(seconds=lease_seconds)
                return True
            return False

    def ack(self, task_id, worker_id, result=None):
        with self._lock:
            t = self._tasks.get(task_id)
            if not t or t.status != LEASED or t.lease_owner != worker_id:
                return False
            t.status, t.result, t.lease_owner, t.leased_until = DONE, result or {}, None, None
            t.finished_at, t.last_error = utcnow(), ""
            return True

    def nack(self, task_id, worker_id, error, *, retry=True):
        with self._lock:
            t = self._tasks.get(task_id)
            if not t or t.status != LEASED or t.lease_owner != worker_id:
                return None
            now = utcnow()
            t.lease_owner, t.leased_until, t.last_error = None, None, str(error)[:4000]
            if not retry or t.attempts >= t.max_attempts:
                t.status, t.finished_at = DEAD, now
            else:
                t.status = PENDING
                t.available_at = now + timedelta(seconds=backoff_seconds(t.attempts, self.backoff_base))
            return t.status

    def get(self, task_id):
        return self._tasks.get(task_id)

    def retry_dead(self, task_id):
        with self._lock:
            t = self._tasks.get(task_id)
            if not t or t.status != DEAD:
                return False
            t.status, t.attempts, t.available_at, t.finished_at = PENDING, 0, utcnow(), None
            return True

    def stats(self):
        out: dict[str, dict[str, int]] = {}
        for t in self._tasks.values():
            out.setdefault(t.queue, dict.fromkeys(STATUSES, 0))[t.status] += 1
        return out

    def list(self, *, status=None, queue=None, limit=50, offset=0):
        items = [t for t in sorted(self._tasks.values(), key=lambda x: -x.id)
                 if (not status or t.status == status) and (not queue or t.queue == queue)]
        return items[offset:offset + limit]


_queue: QueueBackend | None = None
_queue_lock = threading.Lock()


def get_queue() -> QueueBackend:
    global _queue
    with _queue_lock:
        if _queue is None:
            from ..settings import get_settings

            s = get_settings()
            kw = dict(lease_seconds=s.queue_lease_seconds, backoff_base=s.queue_backoff_seconds,
                      max_attempts=s.queue_max_attempts)
            _queue = DBQueue(**kw) if s.queue_backend == "db" else MemoryQueue(**kw)
        return _queue


def reset_queue() -> None:
    global _queue
    with _queue_lock:
        _queue = None


def new_worker_id() -> str:
    return f"worker-{uuid.uuid4().hex[:12]}"
