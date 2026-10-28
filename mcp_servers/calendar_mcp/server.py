"""calendar-mcp: calendar tools over Google Calendar, or a labeled sandbox.

Run from the repo root:
    python -m mcp_servers.calendar_mcp.server
Environment: CALENDAR_MCP_TOKEN (required), CALENDAR_MCP_PORT (8103),
CALENDAR_MODE (auto | sandbox | google), CALENDAR_SANDBOX_DB, TIMEZONE.

In sandbox mode every result has simulated=true and mode="sandbox"; the core shows
these as "Simulated". The core never calls a write tool without an approval.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Annotated, Literal

from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import AwareDatetime, BaseModel, EmailStr, Field

from mcp_servers.calendar_mcp.backends import Backend, CalendarError, EventData, choose_backend
from mcp_servers.common import make_server, run

INSTRUCTIONS = (
    "Calendar tools for the signed-in user's own calendar. Always check availability before creating an event "
    "and tell the user about conflicts. Times are ISO 8601 with an offset. When mode is 'sandbox' the calendar "
    "is simulated and nothing reaches Google."
)

server, CFG = make_server(name="calendar-mcp", title="AgentsMind Calendar tools", instructions=INSTRUCTIONS,
                          prefix="CALENDAR", default_port=8103)
_backend: Backend | None = None
DEFAULT_TZ = os.environ.get("TIMEZONE", "Asia/Karachi")
MAX_WINDOW = timedelta(days=62)

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True)
DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True)

Key = Annotated[str, Field(min_length=8, max_length=100, description="Unique key; re-sending it never repeats the change.")]
EventId = Annotated[str, Field(min_length=5, max_length=1024, pattern=r"^[A-Za-z0-9_\-]+$")]
Mode = Literal["sandbox", "google"]


def backend() -> Backend:
    global _backend
    if _backend is None:
        _backend = choose_backend()
    return _backend


class Event(BaseModel):
    id: str
    summary: str
    start: str
    end: str
    timezone: str
    description: str = ""
    location: str = ""
    attendees: list[str] = []
    meet_link: str | None = None
    html_link: str | None = None
    status: str


class EventsPage(BaseModel):
    items: list[Event]
    next_page_token: str | None = None
    mode: Mode
    simulated: bool


class BusySlot(BaseModel):
    start: str
    end: str


class Availability(BaseModel):
    time_min: str
    time_max: str
    is_free: bool = Field(description="True when nothing overlaps the requested time.")
    busy: list[BusySlot]
    conflicts: list[Event] = Field(description="Events that overlap the requested time (titles included).")
    mode: Mode
    simulated: bool


class CreatedEvent(BaseModel):
    created: bool = Field(description="False when the idempotency key was already used; the original event is returned.")
    verified: bool = Field(description="True when the event was read back from the calendar after creating it.")
    event: Event
    mode: Mode
    simulated: bool


class UpdatedEvent(BaseModel):
    event: Event
    mode: Mode
    simulated: bool


class CancelledEvent(BaseModel):
    event_id: str
    cancelled: bool
    already_cancelled: bool
    mode: Mode
    simulated: bool


def _ev(e: EventData) -> Event:
    return Event(**{k: getattr(e, k) for k in Event.model_fields})


def _meta() -> dict:
    m = backend().mode
    return {"mode": m, "simulated": m == "sandbox"}


def _window(a: datetime, b: datetime) -> None:
    if b <= a:
        raise ToolError("The end time must be after the start time.")
    if b - a > MAX_WINDOW:
        raise ToolError("Ask for at most 62 days at a time.")


def _guard(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except CalendarError as exc:
        raise ToolError(str(exc)) from exc


@server.tool(annotations=READ)
def calendar_list_events(
    time_min: AwareDatetime,
    time_max: AwareDatetime,
    query: Annotated[str | None, Field(max_length=100, description="Text to match in title or description")] = None,
    max_results: Annotated[int, Field(ge=1, le=100)] = 25,
    page_token: Annotated[str | None, Field(max_length=500)] = None,
) -> EventsPage:
    """List events between two times, earliest first. Use next_page_token for more."""
    _window(time_min, time_max)
    items, nxt = _guard(backend().list_events, time_min, time_max, query, max_results, page_token)
    return EventsPage(items=[_ev(e) for e in items], next_page_token=nxt, **_meta())


@server.tool(annotations=READ)
def calendar_check_availability(start: AwareDatetime, end: AwareDatetime) -> Availability:
    """Check whether the user is free between start and end (free/busy), and name any conflicting events."""
    _window(start, end)
    b = backend()
    busy = _guard(b.busy, start, end)
    conflicts, _ = _guard(b.list_events, start, end, None, 20, None)
    return Availability(time_min=start.isoformat(), time_max=end.isoformat(), is_free=not busy,
                        busy=[BusySlot(start=s, end=e) for s, e in busy], conflicts=[_ev(e) for e in conflicts],
                        **_meta())


@server.tool(annotations=WRITE)
def calendar_create_event(
    summary: Annotated[str, Field(min_length=1, max_length=200)],
    start: AwareDatetime,
    end: AwareDatetime,
    idempotency_key: Key,
    timezone: Annotated[str, Field(max_length=64, description="IANA time zone, e.g. Asia/Karachi")] = DEFAULT_TZ,
    description: Annotated[str, Field(max_length=5000)] = "",
    location: Annotated[str, Field(max_length=300)] = "",
    attendees: Annotated[list[EmailStr], Field(max_length=50)] = [],  # noqa: B006 - pydantic copies defaults
    add_meet: Annotated[bool, Field(description="Add a Google Meet link")] = False,
    notify_attendees: bool = False,
) -> CreatedEvent:
    """Create an event on the user's calendar, then read it back to confirm it exists."""
    _window(start, end)
    ev, created = _guard(backend().create, key=idempotency_key, summary=summary, start=start, end=end, tz=timezone,
                         description=description, location=location, attendees=[str(a) for a in attendees],
                         add_meet=add_meet, notify=notify_attendees)
    readback = _guard(backend().get, ev.id)
    return CreatedEvent(created=created, verified=readback is not None and readback.status != "cancelled",
                        event=_ev(readback or ev), **_meta())


@server.tool(annotations=WRITE)
def calendar_update_event(
    event_id: EventId,
    idempotency_key: Key,
    summary: Annotated[str | None, Field(min_length=1, max_length=200)] = None,
    start: AwareDatetime | None = None,
    end: AwareDatetime | None = None,
    timezone: Annotated[str | None, Field(max_length=64)] = None,
    description: Annotated[str | None, Field(max_length=5000)] = None,
    location: Annotated[str | None, Field(max_length=300)] = None,
    notify_attendees: bool = False,
) -> UpdatedEvent:
    """Move or edit an event. Give both start and end when moving it."""
    if (start is None) != (end is None):
        raise ToolError("Give both start and end when moving an event.")
    if start and end:
        _window(start, end)
    patch = {k: v for k, v in {"summary": summary, "start": start, "end": end, "timezone": timezone,
                               "description": description, "location": location}.items() if v is not None}
    if not patch:
        raise ToolError("Nothing to change.")
    ev = _guard(backend().update, event_id, patch, notify_attendees)
    return UpdatedEvent(event=_ev(ev), **_meta())


@server.tool(annotations=DESTRUCTIVE)
def calendar_cancel_event(event_id: EventId, idempotency_key: Key, notify_attendees: bool = False) -> CancelledEvent:
    """Cancel (delete) an event. Cancelling twice is safe."""
    done = _guard(backend().cancel, event_id, notify_attendees)
    return CancelledEvent(event_id=event_id, cancelled=True, already_cancelled=not done, **_meta())


if __name__ == "__main__":
    backend()  # fail fast on a bad CALENDAR_MODE
    run(server, CFG)
