"""
MESSAGE_QUEUE/QUEUE.PY
======================
Core Message Queue for Agent-to-Agent (A2A) communication.

Architecture:
  ┌─────────────────────────────────────────────────────────┐
  │                   MESSAGE QUEUE (MQ)                     │
  │                                                          │
  │  Orchestrator  ─── publish ──►  Queue  ─── subscribe ── Agent │
  │  Agent A       ─── publish ──►  Queue  ─── subscribe ── Agent B │
  │                                                          │
  └─────────────────────────────────────────────────────────┘

Every message has:
  - msg_id:    unique UUID
  - sender:    who sent it
  - receiver:  intended recipient (agent_id or "broadcast")
  - topic:     what type of message (task, result, status, collab_request)
  - payload:   dict with message content
  - timestamp: when it was created
  - status:    pending | delivered | processed | failed
"""

import uuid
import time
import threading
from collections import defaultdict, deque
from typing import Callable, Optional
from dataclasses import dataclass, field


@dataclass
class A2AMessage:
    """Single message in the A2A protocol."""
    sender:    str
    receiver:  str
    topic:     str
    payload:   dict
    msg_id:    str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: float = field(default_factory=time.time)
    status:    str = "pending"       # pending | delivered | processed | failed
    priority:  int = 1               # 1=normal, 2=high, 3=urgent
    reply_to:  Optional[str] = None  # msg_id this is responding to

    def to_dict(self) -> dict:
        return {
            "msg_id":    self.msg_id,
            "sender":    self.sender,
            "receiver":  self.receiver,
            "topic":     self.topic,
            "payload":   self.payload,
            "timestamp": self.timestamp,
            "status":    self.status,
            "priority":  self.priority,
            "reply_to":  self.reply_to,
        }


class MessageQueue:
    """
    In-memory message queue with pub/sub + direct messaging.
    Thread-safe. Supports agent collaboration via A2A protocol.
    """

    def __init__(self, max_history: int = 500):
        self._lock          = threading.Lock()
        self._queues        = defaultdict(deque)   # agent_id -> deque of messages
        self._subscribers   = defaultdict(list)    # topic -> [callback]
        self._history       = deque(maxlen=max_history)  # all messages ever
        self._agent_stats   = defaultdict(lambda: {"sent": 0, "received": 0, "processed": 0})

    # ── Publish ──────────────────────────────────────────────────────────────

    def publish(self, msg: A2AMessage) -> str:
        """
        Put a message on the queue.
        Returns the msg_id.
        """
        with self._lock:
            if msg.receiver == "broadcast":
                # Fan-out to all known agents
                for agent_id in list(self._queues.keys()):
                    self._queues[agent_id].append(msg)
            else:
                self._queues[msg.receiver].append(msg)

            self._history.append(msg)
            self._agent_stats[msg.sender]["sent"] += 1

        # Fire topic subscribers (outside lock to avoid deadlock)
        for cb in self._subscribers.get(msg.topic, []):
            try:
                cb(msg)
            except Exception:
                pass

        return msg.msg_id

    def send(self, sender: str, receiver: str, topic: str, payload: dict,
             priority: int = 1, reply_to: str = None) -> str:
        """Convenience wrapper — creates and publishes a message."""
        msg = A2AMessage(
            sender=sender, receiver=receiver,
            topic=topic, payload=payload,
            priority=priority, reply_to=reply_to,
        )
        return self.publish(msg)

    # ── Consume ──────────────────────────────────────────────────────────────

    def consume(self, agent_id: str, max_msgs: int = 10) -> list:
        """
        Pop up to max_msgs messages from an agent's queue.
        Marks them as delivered.
        """
        msgs = []
        with self._lock:
            q = self._queues[agent_id]
            for _ in range(min(max_msgs, len(q))):
                msg = q.popleft()
                msg.status = "delivered"
                self._agent_stats[agent_id]["received"] += 1
                msgs.append(msg)
        return msgs

    def peek(self, agent_id: str) -> list:
        """Return messages without consuming them."""
        with self._lock:
            return list(self._queues[agent_id])

    def pending_count(self, agent_id: str) -> int:
        with self._lock:
            return len(self._queues[agent_id])

    # ── Subscribe ────────────────────────────────────────────────────────────

    def subscribe(self, topic: str, callback: Callable):
        """Register a callback that fires whenever a message with this topic is published."""
        with self._lock:
            self._subscribers[topic].append(callback)

    # ── History & Stats ──────────────────────────────────────────────────────

    def get_history(self, limit: int = 100) -> list:
        with self._lock:
            items = list(self._history)[-limit:]
        return [m.to_dict() for m in items]

    def get_stats(self) -> dict:
        with self._lock:
            return dict(self._agent_stats)

    def get_all_messages_for_display(self, limit: int = 50) -> list:
        """Get recent messages formatted for UI display."""
        with self._lock:
            items = list(self._history)[-limit:]
        result = []
        for m in reversed(items):
            result.append({
                "time":     time.strftime("%H:%M:%S", time.localtime(m.timestamp)),
                "msg_id":   m.msg_id,
                "sender":   m.sender,
                "receiver": m.receiver,
                "topic":    m.topic,
                "status":   m.status,
                "priority": m.priority,
                "preview":  str(m.payload)[:120],
            })
        return result


# ── Singleton ────────────────────────────────────────────────────────────────

# One global queue shared by all agents
message_queue = MessageQueue()


def _register_config_agents():
    """Ensure every agent id has a queue so tasks and broadcast fan-out work."""
    try:
        from config import AGENT_IDS
        with message_queue._lock:
            for _role, aid in AGENT_IDS.items():
                message_queue._queues[aid]  # touch: defaultdict creates deque
    except Exception:
        pass


_register_config_agents()
