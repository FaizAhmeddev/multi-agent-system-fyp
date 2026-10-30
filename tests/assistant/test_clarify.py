"""A clarifying answer fills the one detail that was asked for (it is not glued onto the request)."""
from __future__ import annotations

from fakectx import FakeCtx

from agentsmind.assistant.orchestrator import run_turn


def talk(tmp_path, *msgs):
    ctx = FakeCtx(tmp_path, tools={"gmail_read_inbox": lambda a: {"items": [], "simulated": False}})
    pending, out = None, []
    for m in msgs:
        r = run_turn(ctx, m, pending)
        pending = r.pending
        out.append(r.cards)
    return out


def details(card):
    return {d.label: d.value for d in card.approval.details}


def test_department_answer_is_not_added_to_the_ticket(tmp_path):
    first, second = talk(tmp_path, "My laptop keeps disconnecting from the VPN, please raise a ticket", "Operations")
    assert first[-1].kind == "clarify" and "ask" not in first[-1].data  # internal fields never reach the screen
    d = details(second[-1])
    assert d["Department"] == "Operations"
    assert d["Description"] == "My laptop keeps disconnecting from the VPN, please raise a ticket"


def test_meeting_email_uses_the_meeting_as_its_topic(tmp_path):
    first, second = talk(tmp_path, "Schedule a meeting on 1 Nov 2026 at 11am and email to Huzaifa",
                         "huzaifa@company.pk")
    assert [c.agent for c in first] == ["calendar", "email"]
    assert "Huzaifa's email address" in first[-1].body
    d = details(second[-1])
    assert d["To"] == "huzaifa@company.pk" and "1 Nov 2026" in d["Subject"] and d["Message"].startswith("Hi Huzaifa")


def test_email_body_question_is_answered_once(tmp_path):
    a, b, c = talk(tmp_path, "Send an email to Sara Khan", "sara@company.pk", "the report is ready")
    assert b[-1].body == "What should the email say?"
    d = details(c[-1])
    assert d["To"] == "sara@company.pk" and "The report is ready." in d["Message"]
