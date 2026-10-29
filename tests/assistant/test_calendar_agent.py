"""Calendar agent end to end through its LangGraph graph, against the sandbox calendar."""
from __future__ import annotations

from fakectx import FakeCtx

from agentsmind.assistant.agents.calendar import CalendarAgent, free_slots
from agentsmind.assistant.base import run_agent

A = CalendarAgent()


def kinds(cards):
    return [c.kind for c in cards]


def test_create_tomorrow_3pm_45min_with_meet(tmp_path):
    ctx = FakeCtx(tmp_path)
    cards = run_agent(A, ctx, "Schedule a design review tomorrow at 3 pm for 45 minutes with a Google Meet link")
    assert kinds(cards) == ["approval"]
    c = cards[0]
    args = ctx.approvals[0]["args"]
    assert ctx.approvals[0]["tool"] == "calendar_create_event"
    assert args["start"] == "2026-10-29T15:00:00+05:00" and args["end"] == "2026-10-29T15:45:00+05:00"
    assert args["add_meet"] is True and args["timezone"] == "Asia/Karachi"
    det = {d.label: d.value for d in c.approval.details}
    assert det["When"] == "Thu 29 Oct 2026, 15:00 to 15:45 (Asia/Karachi)"
    assert '"tomorrow"' in det["Understood from"] and det["Calendar"].startswith("Simulated")
    assert c.simulated and c.warnings == []
    assert ("calendar_check_availability" in [t for t, _ in ctx.reads])  # free/busy before proposing


def test_conflict_warning(tmp_path):
    ctx = FakeCtx(tmp_path)
    ctx.add_event("Weekly team sync", "2026-10-29T15:00:00")
    cards = run_agent(A, ctx, "Book a meeting with Usman tomorrow at 3:30 pm")
    assert kinds(cards) == ["approval"]
    assert "Weekly team sync" in cards[0].warnings[0]
    assert ctx.approvals[0]["args"]["summary"] == "Meeting with Usman"


def test_missing_time_asks_with_free_slots(tmp_path):
    ctx = FakeCtx(tmp_path)
    ctx.add_event("Stand-up", "2026-10-30T12:00:00", 30)
    cards = run_agent(A, ctx, "Set up a meeting Friday afternoon")
    assert kinds(cards) == ["clarify"] and not ctx.approvals
    assert cards[0].options[0] == "at 12:30"


def test_no_day_no_time_asks(tmp_path):
    ctx = FakeCtx(tmp_path)
    cards = run_agent(A, ctx, "Schedule a meeting with the finance team")
    assert kinds(cards) == ["clarify"] and "When should" in cards[0].body


def test_past_time_refused(tmp_path):
    ctx = FakeCtx(tmp_path)
    cards = run_agent(A, ctx, "Schedule a call today at 9 am")
    assert kinds(cards) == ["clarify"] and "already passed" in cards[0].body


def test_move_3pm_to_4pm(tmp_path):
    ctx = FakeCtx(tmp_path)
    ev = ctx.add_event("Budget review", "2026-10-28T15:00:00")
    ctx.add_event("Other", "2026-10-29T15:00:00")
    cards = run_agent(A, ctx, "Move my 3 pm meeting to 4 pm")
    assert kinds(cards) == ["approval"]
    a = ctx.approvals[0]
    assert a["tool"] == "calendar_update_event" and a["args"]["event_id"] == ev.id
    assert a["args"]["start"] == "2026-10-28T16:00:00+05:00" and a["args"]["end"] == "2026-10-28T17:00:00+05:00"


def test_cancel_mondays_review(tmp_path):
    ctx = FakeCtx(tmp_path)
    ev = ctx.add_event("Review meeting", "2026-11-02T11:00:00")
    ctx.add_event("Lunch", "2026-11-02T13:00:00")
    cards = run_agent(A, ctx, "Cancel Monday's review meeting")
    assert kinds(cards) == ["approval"]
    assert cards[0].approval.risk == "destructive" and cards[0].approval.confirm_text == "Review meeting"
    assert ctx.approvals[0]["args"] == {"event_id": ev.id}


def test_cancel_ambiguous_asks(tmp_path):
    ctx = FakeCtx(tmp_path)
    ctx.add_event("Review A", "2026-11-02T11:00:00")
    ctx.add_event("Review B", "2026-11-02T14:00:00")
    cards = run_agent(A, ctx, "Cancel Monday's review")
    assert kinds(cards) == ["clarify"] and len(cards[0].options) == 2


def test_cancel_not_found_is_error_card(tmp_path):
    cards = run_agent(A, FakeCtx(tmp_path), "Cancel Monday's review meeting")
    assert kinds(cards) == ["error"] and "could not find" in cards[0].body


def test_list_and_availability(tmp_path):
    ctx = FakeCtx(tmp_path)
    ctx.add_event("Stand-up", "2026-10-29T10:00:00", 15)
    lst = run_agent(A, ctx, "What's on my calendar tomorrow?")
    assert kinds(lst) == ["result"] and lst[0].data["rows"][0]["title"] == "Stand-up"
    av = run_agent(A, ctx, "Am I free tomorrow morning?")
    assert kinds(av) == ["result"] and "busy" in av[0].body and "Free starts: 09:00" in av[0].body
    av2 = run_agent(A, ctx, "Am I free Friday afternoon?")
    assert av2[0].body.startswith("Yes, you are free")
    assert not ctx.approvals


def test_free_slots_arithmetic():
    from datetime import datetime, timedelta
    a = datetime(2026, 1, 1, 9)
    slots = free_slots((a, a + timedelta(hours=2)), [(a + timedelta(minutes=30), a + timedelta(minutes=60))], 30)
    assert [s.strftime("%H:%M") for s in slots] == ["09:00", "10:00", "10:30"]


def test_graph_steps_emitted(tmp_path):
    ctx = FakeCtx(tmp_path)
    run_agent(A, ctx, "Schedule a sync tomorrow at 11 am")
    assert [e["node"] for e in ctx.events] == ["understand", "gather", "propose"]


def test_titles():
    from agentsmind.assistant.agents.calendar import _title
    assert _title("Schedule a design review tomorrow at 3 pm for 45 minutes with a Google Meet link") == "Design review"
    assert _title("Book a meeting with Usman tomorrow at 3:30 pm") == "Meeting with Usman"
    assert _title('Schedule "Quarterly planning" on Friday at 10') == "Quarterly planning"
    assert _title("Set up a meeting Friday afternoon") == "Meeting"
    assert _title("Schedule a call with the finance team") == "Meeting with the finance team"
    assert _title("Book an interview tomorrow at 11") == "Interview"
