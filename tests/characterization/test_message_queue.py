"""Characterization: the in-memory A2A message queue."""
import pytest

from message_queue.queue import A2AMessage, MessageQueue


@pytest.fixture
def mq(monkeypatch):
    q = MessageQueue()
    # Isolate from the shared app DB: persistence is best-effort and swallowed anyway.
    monkeypatch.setattr(q, "_persist_message", lambda msg: None)
    monkeypatch.setattr(q, "_load_persisted_messages", lambda limit=50: [])
    return q


def test_send_and_consume_fifo(mq):
    a = mq.send("orch", "agent-it-001", "task", {"n": 1})
    b = mq.send("orch", "agent-it-001", "task", {"n": 2})
    assert mq.pending_count("agent-it-001") == 2
    got = mq.consume("agent-it-001")
    assert [m.msg_id for m in got] == [a, b]
    assert all(m.status == "delivered" for m in got)
    assert mq.pending_count("agent-it-001") == 0


def test_unacked_message_is_redelivered_and_ack_is_final(mq):
    """Flipped in Phase 1b (was test_consume_is_destructive_no_ack_no_redelivery)."""
    import time

    mid = mq.send("orch", "agent-x", "task", {})
    first = mq.consume("agent-x")
    assert [m.msg_id for m in first] == [mid]
    assert mq.consume("agent-x") == []  # in flight, not visible
    assert mq.requeue_expired(now=time.time() + 31) == 1  # consumer "crashed": no ack
    again = mq.consume("agent-x")
    assert [m.msg_id for m in again] == [mid]
    assert mq.ack(mid) is True and mq.ack(mid) is False
    assert mq.requeue_expired(now=time.time() + 999) == 0


def test_broadcast_fans_out_to_known_queues_only(mq):
    mq.send("orch", "a1", "task", {})
    mq.consume("a1")
    mq._queues["a2"]  # touch
    mq.send("orch", "broadcast", "status", {"x": 1})
    assert mq.pending_count("a1") == 1 and mq.pending_count("a2") == 1
    assert mq.pending_count("never-seen") == 0


def test_subscriber_errors_are_swallowed(mq):
    seen = []
    mq.subscribe("result", lambda m: (_ for _ in ()).throw(RuntimeError("boom")))
    mq.subscribe("result", lambda m: seen.append(m.msg_id))
    mid = mq.send("a", "b", "result", {})
    assert seen == [mid]


def test_stats_and_display(mq):
    mq.send("orch", "b", "task", {"k": "v"})
    mq.consume("b")
    stats = mq.get_stats()
    assert stats["orch"]["sent"] == 1 and stats["b"]["received"] == 1
    disp = mq.get_all_messages_for_display(limit=5)
    assert disp[0]["topic"] == "task" and "'k': 'v'" in disp[0]["preview"]


def test_message_ids_are_8_hex_chars():
    m = A2AMessage(sender="s", receiver="r", topic="t", payload={})
    assert len(m.msg_id) == 8


def test_singleton_registers_config_agent_queues():
    from config import AGENT_IDS
    from message_queue.queue import message_queue
    for aid in AGENT_IDS.values():
        assert aid in message_queue._queues
