"""Calendar agent: schedule, list, check availability, move and cancel events.

Dates and times are parsed by code (agents/timeparse.py) in the user's time zone, never
by the model. Before any event is created the agent checks free/busy, warns about
conflicts, and shows an approval card with the exact time it understood.
"""
from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ...agents.timeparse import all_times, parse_day, parse_time, parse_when
from ...rbac import STAFF_ROLES
from ..base import Agent, AgentError, Ctx, Proposal, State
from ..cards import Card, Detail
from .common import emails, fmt_dt, fmt_range, has_any, parse_iso, quoted, words

DEFAULT_MINUTES = 30
WORK_START, WORK_END = time(9), time(18)
CAL_WORDS = ("meeting", "meetings", "calendar", "schedule", "reschedule", "book", "appointment", "event", "events",
             "availability", "available", "free", "busy", "invite", "sync", "catch-up", "catch up", "standup",
             "stand-up", "review meeting", "one-to-one", "1:1")


def _intent(text: str) -> str:
    t = text.lower()
    if has_any(t, "cancel", "delete", "remove", "call off"):
        return "cancel"
    if has_any(t, "move", "reschedule", "push", "postpone", "shift", "change the time"):
        return "move"
    if has_any(t, "am i free", "are we free", "free on", "free at", "availability", "available", "busy"):
        return "availability"
    if has_any(t, "what's on", "whats on", "what is on", "show", "list", "agenda", "what meetings", "do i have"):
        return "list"
    return "create"


def _title(text: str) -> str:
    q = quoted(text)
    if q:
        return q[:200]
    m = re.search(r"\b(?:called|titled|named|about|regarding|to discuss)\s+(.+?)(?=\s+(?:on|at|for|with|tomorrow|today|"
                  r"next|this|from|in)\b|[.,;]|$)", text, re.I)
    if m and len(m.group(1).strip()) > 1:
        return m.group(1).strip()[:200].capitalize()
    m = re.search(r"\bwith\s+((?:[A-Z][a-z]+\s?){1,3}|the [a-z]+ team|[a-z]+ team)", text)
    if m:
        return f"Meeting with {m.group(1).strip()}"[:200]
    for kind in ("stand-up", "standup", "review", "interview", "sync", "catch-up", "one-to-one", "demo", "workshop"):
        if kind in text.lower():
            return kind.capitalize() if kind != "one-to-one" else "One-to-one"
    return "Meeting"


def _day_range(day, tz: str) -> tuple[datetime, datetime]:
    z = ZoneInfo(tz)
    a = datetime.combine(day, time(0), z)
    return a, a + timedelta(days=1)


def free_slots(window: tuple[datetime, datetime], busy: list[tuple[datetime, datetime]], minutes: int,
               step: int = 30, limit: int = 4) -> list[datetime]:
    """Start times in `window` with `minutes` free, every `step` minutes. Pure arithmetic in code."""
    out, cur = [], window[0]
    need = timedelta(minutes=minutes)
    while cur + need <= window[1] and len(out) < limit:
        if all(not (cur < b and a < cur + need) for a, b in busy):
            out.append(cur)
        cur += timedelta(minutes=step)
    return out


class CalendarAgent(Agent):
    name = "calendar"
    title = "Calendar agent"
    roles = STAFF_ROLES
    examples = ("Schedule a design review tomorrow at 3 pm for 45 minutes with a Meet link",
                "Am I free Friday afternoon?", "Move my 3 pm meeting to 4 pm", "Cancel Monday's review meeting",
                "What's on my calendar tomorrow?")

    def score(self, text: str) -> float:
        t = text.lower()
        s = sum(1.0 for w in CAL_WORDS if re.search(rf"\b{re.escape(w)}\b", t))
        if s and (parse_time(t) or parse_day(t, datetime.now().date())[0]):
            s += 1.0
        return s

    # ---------------------------------------------------------------- understand
    def understand(self, ctx: Ctx, state: State) -> State:
        text = state["text"]
        intent = _intent(text)
        pw = parse_when(text, tz=ctx.tz, now=ctx.now)
        slots: dict[str, Any] = dict(state.get("slots") or {})
        slots.update(intent=intent, day=pw.day.isoformat() if pw.day else None, day_phrase=pw.day_phrase,
                     start=pw.start.isoformat() if pw.start else None, duration=pw.duration_minutes,
                     window=[w.isoformat() for w in pw.window] if pw.window else None)
        if intent == "create":
            slots.update(title=_title(text), attendees=emails(text),
                         add_meet=has_any(text, "meet link", "google meet", "video call", "video link", "online",
                                          "meet"))
            if not pw.day and not pw.start:
                return {"intent": intent, "slots": slots,
                        "question": "When should the meeting be? For example: tomorrow at 3 pm for 30 minutes."}
            if pw.start and pw.start < ctx.now:
                return {"intent": intent, "slots": slots,
                        "question": f"{fmt_dt(pw.start, ctx.tz)} has already passed. Which day and time do you mean?"}
        return {"intent": intent, "slots": slots}

    # ---------------------------------------------------------------- gather
    def gather(self, ctx: Ctx, state: State) -> State:
        s = state["slots"]
        return getattr(self, f"_g_{s['intent']}")(ctx, state, s)

    def _availability(self, ctx: Ctx, a: datetime, b: datetime) -> dict[str, Any]:
        return self.read_or_raise(ctx, "calendar_check_availability", {"start": a.isoformat(), "end": b.isoformat()})

    def _g_create(self, ctx: Ctx, state: State, s: dict[str, Any]) -> State:
        minutes = s["duration"] or DEFAULT_MINUTES
        if not s["start"]:
            z = ZoneInfo(ctx.tz)
            day = datetime.fromisoformat(s["day"]).date() if s["day"] else ctx.now.date()
            win = ([parse_iso(w) for w in s["window"]] if s["window"]
                   else [datetime.combine(day, WORK_START, z), datetime.combine(day, WORK_END, z)])
            win[0] = max(win[0], ctx.now.replace(second=0, microsecond=0))
            if win[0] >= win[1]:
                return {"question": "That time has already passed. Which day and time do you mean?"}
            av = self._availability(ctx, win[0], win[1])
            busy = [(parse_iso(x["start"]), parse_iso(x["end"])) for x in av["busy"]]
            slots = free_slots((win[0], win[1]), busy, minutes)
            label = s["day_phrase"] or fmt_dt(win[0], ctx.tz)[:15]
            if not slots:
                return {"question": f"You have no free {minutes}-minute slot {label} between "
                                    f"{win[0].astimezone(z):%H:%M} and {win[1].astimezone(z):%H:%M}. "
                                    "Which other day or time should I try?"}
            return {"question": f"What time {label}? These {minutes}-minute slots are free:",
                    "options": [f"at {x.astimezone(z):%H:%M}" for x in slots]}
        start = parse_iso(s["start"])
        end = start + timedelta(minutes=minutes)
        av = self._availability(ctx, start, end)
        warnings = []
        if not av["is_free"]:
            names = ", ".join(f"{c['summary']} ({fmt_range(parse_iso(c['start']), parse_iso(c['end']), ctx.tz)})"
                              for c in av["conflicts"][:3]) or "another event"
            warnings.append(f"Conflict: this overlaps {names}.")
        args = {"summary": s["title"], "start": start.isoformat(), "end": end.isoformat(), "timezone": ctx.tz,
                "attendees": s["attendees"], "add_meet": bool(s["add_meet"]),
                "description": f"Created by AgentsMind for {ctx.user.name}."}
        details = [Detail("Title", s["title"]), Detail("When", fmt_range(start, end, ctx.tz)),
                   Detail("Understood from", f'"{s["day_phrase"] or "today"}" with time zone {ctx.tz}'),
                   Detail("Duration", f"{minutes} minutes" + ("" if s["duration"] else " (default)")),
                   Detail("Attendees", ", ".join(s["attendees"]) or "None"),
                   Detail("Google Meet link", "Yes" if s["add_meet"] else "No"),
                   Detail("Calendar", "Simulated sandbox calendar" if av["simulated"] else "Your Google Calendar")]
        return {"proposals": [Proposal(tool="calendar_create_event", args=args, simulated=av["simulated"],
                                       summary=f"Create \"{s['title']}\" on {fmt_dt(start, ctx.tz)}",
                                       details=details, warnings=warnings)]}

    def _range(self, ctx: Ctx, s: dict[str, Any], default_days: int = 1) -> tuple[datetime, datetime, str]:
        if s["window"]:
            a, b = (parse_iso(w) for w in s["window"])
            return a, b, s["day_phrase"]
        if s["start"]:
            a = parse_iso(s["start"])
            return a, a + timedelta(minutes=s["duration"] or DEFAULT_MINUTES), fmt_dt(a, ctx.tz)
        if s["day"]:
            a, b = _day_range(datetime.fromisoformat(s["day"]).date(), ctx.tz)
            return a, b, s["day_phrase"]
        a, _ = _day_range(ctx.now.date(), ctx.tz)
        return a, a + timedelta(days=default_days), "today" if default_days == 1 else f"the next {default_days} days"

    def _g_list(self, ctx: Ctx, state: State, s: dict[str, Any]) -> State:
        days = 7 if has_any(state["text"], "this week", "week", "next few days") else 1
        a, b, label = self._range(ctx, s, days)
        d = self.read_or_raise(ctx, "calendar_list_events", {"time_min": a.isoformat(), "time_max": b.isoformat(),
                                                             "max_results": 50})
        rows = [{"title": e["summary"], "when": fmt_range(parse_iso(e["start"]), parse_iso(e["end"]), ctx.tz),
                 "meet_link": e.get("meet_link") or "", "id": e["id"]} for e in d["items"]]
        body = f"{len(rows)} event{'s' if len(rows) != 1 else ''} {label}." if rows else f"Nothing on your calendar {label}."
        return {"cards": [Card(kind="result", agent=self.name, title=f"Calendar, {label}", body=body,
                               data={"columns": ["title", "when"], "rows": rows}, simulated=d["simulated"])]}

    def _g_availability(self, ctx: Ctx, state: State, s: dict[str, Any]) -> State:
        a, b, label = self._range(ctx, s)
        av = self._availability(ctx, a, b)
        z = ZoneInfo(ctx.tz)
        if av["is_free"]:
            body = f"Yes, you are free {label} ({a.astimezone(z):%H:%M} to {b.astimezone(z):%H:%M})."
        else:
            busy = "; ".join(f"{c['summary']} {fmt_range(parse_iso(c['start']), parse_iso(c['end']), ctx.tz)}"
                             for c in av["conflicts"][:5])
            free = free_slots((a, b), [(parse_iso(x["start"]), parse_iso(x["end"])) for x in av["busy"]],
                              s["duration"] or DEFAULT_MINUTES)
            body = f"You have {len(av['busy'])} busy period(s) {label}: {busy}."
            if free:
                body += " Free starts: " + ", ".join(f"{x.astimezone(z):%H:%M}" for x in free) + "."
        return {"cards": [Card(kind="result", agent=self.name, title="Availability", body=body, simulated=av["simulated"],
                               data={"busy": av["busy"], "is_free": av["is_free"]})]}

    def _find(self, ctx: Ctx, state: State, s: dict[str, Any], at: time | None) -> tuple[list[dict], bool]:
        if s["day"]:
            a, b = _day_range(datetime.fromisoformat(s["day"]).date(), ctx.tz)
        else:
            a, _ = _day_range(ctx.now.date(), ctx.tz)
            b = a + timedelta(days=8)
        d = self.read_or_raise(ctx, "calendar_list_events", {"time_min": a.isoformat(), "time_max": b.isoformat(),
                                                             "max_results": 100})
        items = d["items"]
        if at is not None:
            items = [e for e in items if parse_iso(e["start"]).astimezone(ZoneInfo(ctx.tz)).time() == at]
        want = words(state["text"]) - {"cancel", "move", "reschedule", "delete", "remove", "postpone", "push", "today",
                                       "tomorrow", "pm", "am", "monday", "tuesday", "wednesday", "thursday",
                                       "friday", "saturday", "sunday", "mondays", "tuesdays", "wednesdays",
                                       "thursdays", "fridays", "later", "earlier", "hour", "minutes"}
        want = {w for w in want if not w.isdigit()}
        if not s["day"]:  # no day named: the first upcoming day that has a match
            items = [e for e in items if parse_iso(e["end"]) > ctx.now]
        if want:
            scored = [(len(want & words(e["summary"])), e) for e in items]
            best = max((n for n, _ in scored), default=0)
            if best:
                items = [e for n, e in scored if n == best]
        if not s["day"] and items:
            first = parse_iso(items[0]["start"]).astimezone(ZoneInfo(ctx.tz)).date()
            items = [e for e in items if parse_iso(e["start"]).astimezone(ZoneInfo(ctx.tz)).date() == first]
        return items, d["simulated"]

    def _pick(self, ctx: Ctx, items: list[dict], verb: str) -> dict | State:
        if not items:
            raise AgentError(f"I could not find that event to {verb}. Try naming the day and time, "
                             "for example: cancel tomorrow's 3 pm meeting.")
        if len(items) > 1:
            return {"question": f"Which event should I {verb}?",
                    "options": [f"{e['summary']} at {fmt_dt(parse_iso(e['start']), ctx.tz)}" for e in items[:5]]}
        return items[0]

    def _g_move(self, ctx: Ctx, state: State, s: dict[str, Any]) -> State:
        text = state["text"]
        times = all_times(text)
        m = re.search(r"\b(?:to|until|till)\b", text)
        head, tail = (text[:m.start()], text[m.end():]) if m else (text, "")
        old_t = all_times(head)[0] if all_times(head) else (times[0] if len(times) > 1 else None)
        new_t = (all_times(tail) or [None])[-1] if tail else None
        new_day = parse_day(tail, ctx.now.date())[0] if tail else None
        if new_t is None and new_day is None:
            return {"question": "What new day or time should the event move to?"}
        hs = dict(s)
        hd, _ = parse_day(head, ctx.now.date())
        hs["day"] = hd.isoformat() if hd else None
        items, _sim = self._find(ctx, {"text": head}, hs, old_t)
        picked = self._pick(ctx, items, "move")
        if "question" in picked:
            return picked
        ev = picked
        z = ZoneInfo(ctx.tz)
        old_start, old_end = parse_iso(ev["start"]).astimezone(z), parse_iso(ev["end"]).astimezone(z)
        day = new_day or old_start.date()
        start = datetime.combine(day, new_t or old_start.time(), z)
        end = start + (old_end - old_start)
        if start < ctx.now:
            return {"question": f"{fmt_dt(start, ctx.tz)} has already passed. Which day and time do you mean?"}
        av = self._availability(ctx, start, end)
        others = [c for c in av["conflicts"] if c["id"] != ev["id"]]
        warnings = [f"Conflict: the new time overlaps {', '.join(c['summary'] for c in others[:3])}."] if others else []
        return {"proposals": [Proposal(
            tool="calendar_update_event", simulated=av["simulated"], warnings=warnings,
            args={"event_id": ev["id"], "start": start.isoformat(), "end": end.isoformat(), "timezone": ctx.tz},
            summary=f"Move \"{ev['summary']}\" to {fmt_dt(start, ctx.tz)}",
            details=[Detail("Event", ev["summary"]), Detail("From", fmt_range(old_start, old_end, ctx.tz)),
                     Detail("To", fmt_range(start, end, ctx.tz))])]}

    def _g_cancel(self, ctx: Ctx, state: State, s: dict[str, Any]) -> State:
        at = parse_time(state["text"])
        items, sim = self._find(ctx, state, s, at)
        picked = self._pick(ctx, items, "cancel")
        if "question" in picked:
            return picked
        ev = picked
        when = fmt_range(parse_iso(ev["start"]), parse_iso(ev["end"]), ctx.tz)
        return {"proposals": [Proposal(
            tool="calendar_cancel_event", simulated=sim, args={"event_id": ev["id"]},
            summary=f"Cancel \"{ev['summary']}\" on {fmt_dt(parse_iso(ev['start']), ctx.tz)}",
            details=[Detail("Event", ev["summary"]), Detail("When", when),
                     Detail("Attendees", ", ".join(ev.get("attendees") or []) or "None")],
            warnings=["This removes the event from the calendar."], confirm_text=ev["summary"])]}
