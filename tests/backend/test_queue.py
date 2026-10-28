"""Persistent queue: leases, acks, retries with backoff, dead-letter, idempotency, crash recovery."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import timedelta

import pytest
from bhelpers import ROOT


@pytest.fixture(params=["db", "memory"])
def q(request, db_url):
    from agentsmind.queue.core import DBQueue, MemoryQueue

    kw = dict(lease_seconds=30, backoff_base=0.0, max_attempts=3)
    return DBQueue(**kw) if request.param == "db" else MemoryQueue(**kw)


def test_enqueue_lease_ack(q):
    t = q.enqueue("demo.append", {"x": 1})
    assert t.status == "pending" and t.attempts == 0
    got = q.lease("w1")
    assert got.id == t.id and got.status == "leased" and got.attempts == 1 and got.lease_owner == "w1"
    assert q.lease("w2") is None  # leased tasks are invisible to others
    assert q.ack(t.id, "w1", {"ok": True}) is True
    done = q.get(t.id)
    assert done.status == "done" and done.result == {"ok": True} and done.finished_at is not None


def test_only_lease_owner_can_ack_or_nack(q):
    t = q.enqueue("k", {})
    q.lease("w1")
    assert q.ack(t.id, "intruder", {}) is False
    assert q.nack(t.id, "intruder", "x") is None
    assert q.get(t.id).status == "leased"


def test_nack_retries_then_dead_letters(q):
    t = q.enqueue("k", {}, max_attempts=2)
    q.lease("w")
    assert q.nack(t.id, "w", "boom 1") == "pending"
    q.lease("w")
    assert q.nack(t.id, "w", "boom 2") == "dead"
    d = q.get(t.id)
    assert d.status == "dead" and d.attempts == 2 and "boom 2" in d.last_error
    assert q.lease("w") is None
    assert q.retry_dead(t.id) is True and q.get(t.id).status == "pending"


def test_permanent_failure_goes_straight_to_dead(q):
    t = q.enqueue("k", {}, max_attempts=5)
    q.lease("w")
    assert q.nack(t.id, "w", "bad input", retry=False) == "dead"


def test_backoff_delays_redelivery(db_url):
    from agentsmind.queue.core import DBQueue, backoff_seconds

    assert [backoff_seconds(n, 2) for n in (1, 2, 3, 4)] == [2, 4, 8, 16]
    assert backoff_seconds(20, 2) == 300
    qq = DBQueue(lease_seconds=30, backoff_base=5.0, max_attempts=3)
    t = qq.enqueue("k", {})
    qq.lease("w")
    qq.nack(t.id, "w", "transient")
    assert qq.lease("w") is None  # not yet: waiting ~5 seconds
    assert qq.get(t.id).available_at > t.available_at + timedelta(seconds=4)


def test_expired_lease_is_redelivered(q):
    t = q.enqueue("k", {})
    q.lease("w1", lease_seconds=2)
    time.sleep(2.2)
    again = q.lease("w2")
    assert again.id == t.id and again.attempts == 2 and again.lease_owner == "w2"
    assert q.ack(t.id, "w1", {"late": True}) is False  # the presumed-dead worker cannot win
    assert q.ack(t.id, "w2", {"ok": True}) is True
    assert q.get(t.id).result == {"ok": True}


def test_expired_final_attempt_becomes_dead(q):
    t = q.enqueue("k", {}, max_attempts=1)
    q.lease("w1", lease_seconds=2)
    time.sleep(2.2)
    assert q.lease("w2") is None
    assert q.get(t.id).status == "dead"


def test_idempotency_key_returns_same_task(q):
    a = q.enqueue("k", {"n": 1}, idempotency_key="abc")
    b = q.enqueue("k", {"n": 2}, idempotency_key="abc")
    assert a.id == b.id and b.payload == {"n": 1}


def test_stats(q):
    q.enqueue("k", {})
    t = q.enqueue("k", {})
    q.lease("w")
    stats = q.stats()["default"]
    assert stats["pending"] + stats["leased"] == 2 and t.id


def test_worker_run_once_dispatches_and_acks(db_url, tmp_path):
    from agentsmind.queue import handlers  # noqa: F401
    from agentsmind.queue.core import DBQueue
    from agentsmind.queue.worker import Worker

    qq = DBQueue(lease_seconds=30, backoff_base=0.0, max_attempts=3)
    out = tmp_path / "effects.txt"
    t = qq.enqueue("demo.append", {"path": str(out)})
    done = Worker(qq).run_once()
    assert done.status == "done" and done.result["wrote"] is True
    assert out.read_text().splitlines() == [t.effect_key]


def test_worker_unknown_kind_is_dead(db_url):
    from agentsmind.queue.core import DBQueue
    from agentsmind.queue.worker import Worker

    qq = DBQueue(lease_seconds=30, backoff_base=0.0, max_attempts=3)
    qq.enqueue("no.such.kind", {})
    assert Worker(qq).run_once().status == "dead"


def _spawn_worker(db_url: str, worker_id: str, lease: int):
    env = dict(os.environ, DATABASE_URL=db_url, PYTHONPATH=str(ROOT / "backend"), QUEUE_BACKEND="db",
               LOG_JSON="true")
    return subprocess.Popen([sys.executable, "-m", "agentsmind.queue.worker", "--once", "--lease", str(lease),
                             "--worker-id", worker_id], env=env, cwd=str(ROOT),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def test_killed_worker_task_is_retried_once_without_duplicate_effect(db_url, tmp_path):
    """Acceptance scenario 8: kill the worker mid-task, restart, the task runs again once."""
    from agentsmind.queue.core import DBQueue

    qq = DBQueue(lease_seconds=3, backoff_base=0.0, max_attempts=3)
    out = tmp_path / "effects.txt"
    t = qq.enqueue("demo.append", {"path": str(out), "sleep": 6})

    first = _spawn_worker(db_url, "worker-A", lease=3)
    deadline = time.time() + 20
    while qq.get(t.id).status != "leased" and time.time() < deadline:
        time.sleep(0.2)
    assert qq.get(t.id).lease_owner == "worker-A"
    first.kill()  # mid-task: it is sleeping inside the handler and never acks
    first.wait(timeout=10)
    assert not out.exists()

    time.sleep(3.5)  # let worker-A's lease (3 s, no heartbeat any more) expire
    proc = _spawn_worker(db_url, "worker-B", lease=10)
    logs = proc.communicate(timeout=60)[0].decode(errors="replace")
    assert proc.returncode == 0, logs
    final = qq.get(t.id)
    assert final.status == "done", logs
    assert final.attempts == 2
    assert final.result["attempt"] == 2 and final.result["wrote"] is True
    assert out.read_text().splitlines() == [t.effect_key]  # exactly one effect
