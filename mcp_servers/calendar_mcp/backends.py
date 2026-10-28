"""Calendar backends for calendar-mcp.

SandboxCalendar  local SQLite file (data/calendar_sandbox.db). Every result says
                 simulated=True and the UI labels it "Simulated". Nothing leaves the computer.
GoogleCalendar   Google Calendar API v3 on the signed-in user's primary calendar.
                 Scopes: calendar.events.owned (create/update/delete own events) and
                 calendar.freebusy (own availability). Verified in docs/API_VERIFICATION.md.

Both backends share the same contract, so the tools and the tests do not care which
one runs. Times are exchanged as ISO 8601 strings with an offset.

Idempotency:
    create  the event id is derived from the idempotency key (sha256 hex is valid
            base32hex, which Google accepts as a client-supplied id). Re-sending a key
            returns the original event with created=False.
    update  applying the same patch twice gives the same event.
    cancel  cancelling an already cancelled event reports already_cancelled=True.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

log = logging.getLogger("calendar_mcp")
REPO_ROOT = Path(__file__).resolve().parents[2]


class CalendarError(Exception):
    """A message that is safe to show the user."""


def event_id_for(key: str) -> str:
    # Google: ids use base32hex characters (a-v, 0-9), length 5-1024. Hex is a subset.
    return hashlib.sha256(key.encode()).hexdigest()[:40]


def _utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise CalendarError("Times must include a time zone offset.")
    return dt.astimezone(UTC).isoformat(timespec="seconds")


def _local(iso_utc: str, tz: str) -> str:
    return datetime.fromisoformat(iso_utc).astimezone(ZoneInfo(tz)).isoformat(timespec="seconds")


@dataclass
class EventData:
    id: str
    summary: str
    start: str
    end: str
    timezone: str
    description: str = ""
    location: str = ""
    attendees: list[str] = field(default_factory=list)
    meet_link: str | None = None
    html_link: str | None = None
    status: str = "confirmed"
    created: str = ""
    updated: str = ""


class Backend(Protocol):
    mode: str

    def list_events(self, time_min: datetime, time_max: datetime, query: str | None, max_results: int,
                    page_token: str | None) -> tuple[list[EventData], str | None]: ...

    def busy(self, time_min: datetime, time_max: datetime) -> list[tuple[str, str]]: ...

    def create(self, *, key: str, summary: str, start: datetime, end: datetime, tz: str, description: str,
               location: str, attendees: list[str], add_meet: bool, notify: bool) -> tuple[EventData, bool]: ...

    def get(self, event_id: str) -> EventData | None: ...

    def update(self, event_id: str, patch: dict[str, Any], notify: bool) -> EventData: ...

    def cancel(self, event_id: str, notify: bool) -> bool: ...


# ---------------------------------------------------------------------------- sandbox

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    summary TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    start_utc TEXT NOT NULL,
    end_utc TEXT NOT NULL,
    timezone TEXT NOT NULL,
    attendees TEXT NOT NULL DEFAULT '[]',
    meet_link TEXT,
    status TEXT NOT NULL DEFAULT 'confirmed',
    created TEXT NOT NULL,
    updated TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events_start ON events (start_utc);
"""


class SandboxCalendar:
    mode = "sandbox"

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or os.environ.get("CALENDAR_SANDBOX_DB") or REPO_ROOT / "data" / "calendar_sandbox.db")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    @staticmethod
    def _row(r: sqlite3.Row) -> EventData:
        tz = r["timezone"]
        return EventData(id=r["id"], summary=r["summary"], description=r["description"], location=r["location"],
                         start=_local(r["start_utc"], tz), end=_local(r["end_utc"], tz), timezone=tz,
                         attendees=json.loads(r["attendees"]), meet_link=r["meet_link"], status=r["status"],
                         created=r["created"], updated=r["updated"])

    def list_events(self, time_min, time_max, query, max_results, page_token):
        offset = int(page_token or 0)
        sql = ("SELECT * FROM events WHERE status != 'cancelled' AND start_utc < ? AND end_utc > ?")
        args: list[Any] = [_utc(time_max), _utc(time_min)]
        if query:
            sql += " AND (summary LIKE ? OR description LIKE ?)"
            args += [f"%{query}%", f"%{query}%"]
        sql += " ORDER BY start_utc LIMIT ? OFFSET ?"
        args += [max_results + 1, offset]
        with self._conn() as c:
            rows = c.execute(sql, args).fetchall()
        nxt = str(offset + max_results) if len(rows) > max_results else None
        return [self._row(r) for r in rows[:max_results]], nxt

    def busy(self, time_min, time_max):
        with self._conn() as c:
            rows = c.execute("SELECT start_utc, end_utc FROM events WHERE status != 'cancelled' "
                             "AND start_utc < ? AND end_utc > ? ORDER BY start_utc",
                             (_utc(time_max), _utc(time_min))).fetchall()
        return [(r[0], r[1]) for r in rows]

    def get(self, event_id):
        with self._conn() as c:
            r = c.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        return self._row(r) if r else None

    def create(self, *, key, summary, start, end, tz, description, location, attendees, add_meet, notify):
        eid = event_id_for(key)
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self._lock, self._conn() as c:
            existing = c.execute("SELECT * FROM events WHERE id = ?", (eid,)).fetchone()
            if existing:
                return self._row(existing), False
            meet = f"https://meet.example.invalid/sim-{eid[:10]}" if add_meet else None
            c.execute("INSERT INTO events (id, summary, description, location, start_utc, end_utc, timezone, "
                      "attendees, meet_link, created, updated) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (eid, summary, description, location, _utc(start), _utc(end), tz, json.dumps(attendees), meet,
                       now, now))
        return self.get(eid), True

    def update(self, event_id, patch, notify):
        cur = self.get(event_id)
        if cur is None or cur.status == "cancelled":
            raise CalendarError(f"Event {event_id} was not found.")
        cols, args = [], []
        for k in ("summary", "description", "location"):
            if k in patch:
                cols.append(f"{k} = ?")
                args.append(patch[k])
        for k in ("start", "end"):
            if k in patch:
                cols.append(f"{k}_utc = ?")
                args.append(_utc(patch[k]))
        if "timezone" in patch:
            cols.append("timezone = ?")
            args.append(patch["timezone"])
        if cols:
            cols.append("updated = ?")
            args.append(datetime.now(UTC).isoformat(timespec="seconds"))
            with self._conn() as c:
                c.execute(f"UPDATE events SET {', '.join(cols)} WHERE id = ?", [*args, event_id])  # noqa: S608
        return self.get(event_id)

    def cancel(self, event_id, notify):
        cur = self.get(event_id)
        if cur is None:
            raise CalendarError(f"Event {event_id} was not found.")
        if cur.status == "cancelled":
            return False
        with self._conn() as c:
            c.execute("UPDATE events SET status = 'cancelled', updated = ? WHERE id = ?",
                      (datetime.now(UTC).isoformat(timespec="seconds"), event_id))
        return True

    def seed(self, tz: str = "Asia/Karachi", today: datetime | None = None) -> int:
        """Synthetic demo events relative to today, so conflict warnings can be shown."""
        zone = ZoneInfo(tz)
        base = (today or datetime.now(zone)).astimezone(zone).replace(hour=0, minute=0, second=0, microsecond=0)
        rows = [
            ("seed-standup", "Daily stand-up", 1, 10, 0, 15),
            ("seed-sync", "Weekly team sync", 1, 15, 0, 60),
            ("seed-review", "Review meeting", 3, 11, 0, 60),
            ("seed-1on1", "One-to-one with HR", 2, 14, 30, 30),
        ]
        n = 0
        for key, title, day, h, m, dur in rows:
            s = base + timedelta(days=day, hours=h, minutes=m)
            _, created = self.create(key=f"{key}-{base.date().isoformat()}", summary=title, start=s,
                                     end=s + timedelta(minutes=dur), tz=tz, description="Synthetic demo event.",
                                     location="", attendees=[], add_meet=False, notify=False)
            n += int(created)
        return n


# ---------------------------------------------------------------------------- google

SCOPES_NEEDED = ["https://www.googleapis.com/auth/calendar.events.owned",
                 "https://www.googleapis.com/auth/calendar.freebusy"]
TIMEOUT_SECONDS = 10
READ_RETRIES = 2


class GoogleCalendar:
    mode = "google"

    def __init__(self, creds, calendar_id: str = "primary"):
        import google_auth_httplib2
        import httplib2
        from googleapiclient.discovery import build

        http = google_auth_httplib2.AuthorizedHttp(creds, http=httplib2.Http(timeout=TIMEOUT_SECONDS))
        self.svc = build("calendar", "v3", http=http, cache_discovery=False)
        self.cal = calendar_id

    @staticmethod
    def _status(exc) -> int:
        return int(getattr(getattr(exc, "resp", None), "status", 0) or 0)

    def _exec(self, req, *, read: bool):
        from googleapiclient.errors import HttpError

        try:
            return req.execute(num_retries=READ_RETRIES if read else 0)
        except HttpError as exc:
            code = self._status(exc)
            if code in (401, 403):
                raise CalendarError("Google refused the request. Re-run scripts/google_oauth.py to sign in "
                                    "again.") from exc
            if code == 404:
                raise CalendarError("That event was not found in Google Calendar.") from exc
            raise CalendarError(f"Google Calendar returned HTTP {code}.") from exc
        except (TimeoutError, OSError) as exc:
            raise CalendarError(f"Google Calendar did not answer within {TIMEOUT_SECONDS} s.") from exc

    @staticmethod
    def _event(d: dict, tz_default: str) -> EventData:
        def when(x):
            return x.get("dateTime") or x.get("date") or ""

        meet = None
        for ep in (d.get("conferenceData") or {}).get("entryPoints", []):
            if ep.get("entryPointType") == "video":
                meet = ep.get("uri")
        return EventData(id=d["id"], summary=d.get("summary", "(no title)"), description=d.get("description", ""),
                         location=d.get("location", ""), start=when(d.get("start", {})), end=when(d.get("end", {})),
                         timezone=d.get("start", {}).get("timeZone") or tz_default,
                         attendees=[a["email"] for a in d.get("attendees", []) if a.get("email")], meet_link=meet,
                         html_link=d.get("htmlLink"), status=d.get("status", "confirmed"), created=d.get("created", ""),
                         updated=d.get("updated", ""))

    def list_events(self, time_min, time_max, query, max_results, page_token):
        req = self.svc.events().list(calendarId=self.cal, timeMin=time_min.isoformat(), timeMax=time_max.isoformat(),
                                     q=query or None, maxResults=max_results, pageToken=page_token or None,
                                     singleEvents=True, orderBy="startTime")
        d = self._exec(req, read=True)
        tz = d.get("timeZone", "UTC")
        return [self._event(e, tz) for e in d.get("items", [])], d.get("nextPageToken")

    def busy(self, time_min, time_max):
        body = {"timeMin": time_min.isoformat(), "timeMax": time_max.isoformat(), "items": [{"id": self.cal}]}
        d = self._exec(self.svc.freebusy().query(body=body), read=True)
        cal = next(iter(d.get("calendars", {}).values()), {})
        if cal.get("errors"):
            raise CalendarError("Google could not report availability for this calendar.")
        return [(b["start"], b["end"]) for b in cal.get("busy", [])]

    def get(self, event_id):
        from googleapiclient.errors import HttpError

        try:
            d = self.svc.events().get(calendarId=self.cal, eventId=event_id).execute(num_retries=READ_RETRIES)
        except HttpError as exc:
            if self._status(exc) in (404, 410):
                return None
            raise CalendarError(f"Google Calendar returned HTTP {self._status(exc)}.") from exc
        return self._event(d, "UTC")

    def create(self, *, key, summary, start, end, tz, description, location, attendees, add_meet, notify):
        from googleapiclient.errors import HttpError

        eid = event_id_for(key)
        body: dict[str, Any] = {
            "id": eid, "summary": summary, "description": description, "location": location,
            "start": {"dateTime": start.isoformat(), "timeZone": tz},
            "end": {"dateTime": end.isoformat(), "timeZone": tz},
            "attendees": [{"email": a} for a in attendees],
        }
        kw: dict[str, Any] = {"sendUpdates": "all" if (notify and attendees) else "none"}
        if add_meet:
            body["conferenceData"] = {"createRequest": {"requestId": uuid.uuid5(uuid.NAMESPACE_URL, key).hex,
                                                        "conferenceSolutionKey": {"type": "hangoutsMeet"}}}
            kw["conferenceDataVersion"] = 1
        try:
            self.svc.events().insert(calendarId=self.cal, body=body, **kw).execute(num_retries=0)
            created = True
        except HttpError as exc:
            if self._status(exc) != 409:  # 409: an event with this id exists, i.e. a replay
                raise CalendarError(f"Google Calendar returned HTTP {self._status(exc)}.") from exc
            created = False
        ev = self.get(eid)
        if ev is None:
            raise CalendarError("The event could not be read back from Google Calendar.")
        return ev, created

    def update(self, event_id, patch, notify):
        body: dict[str, Any] = {k: patch[k] for k in ("summary", "description", "location") if k in patch}
        tz = patch.get("timezone")
        for k in ("start", "end"):
            if k in patch:
                body[k] = {"dateTime": patch[k].isoformat(), **({"timeZone": tz} if tz else {})}
        req = self.svc.events().patch(calendarId=self.cal, eventId=event_id, body=body,
                                      sendUpdates="all" if notify else "none")
        return self._event(self._exec(req, read=False), tz or "UTC")

    def cancel(self, event_id, notify):
        from googleapiclient.errors import HttpError

        try:
            self.svc.events().delete(calendarId=self.cal, eventId=event_id,
                                     sendUpdates="all" if notify else "none").execute(num_retries=0)
            return True
        except HttpError as exc:
            if self._status(exc) == 410:  # already deleted
                return False
            if self._status(exc) == 404:
                raise CalendarError(f"Event {event_id} was not found.") from exc
            raise CalendarError(f"Google Calendar returned HTTP {self._status(exc)}.") from exc


def choose_backend() -> Backend:
    """CALENDAR_MODE = auto (default) | sandbox | google."""
    mode = (os.environ.get("CALENDAR_MODE") or "auto").strip().lower()
    if mode not in {"auto", "sandbox", "google"}:
        raise SystemExit("CALENDAR_MODE must be auto, sandbox or google.")
    if mode != "sandbox":
        from mcp_servers.google_common import credentials

        try:
            creds = credentials(SCOPES_NEEDED)
        except (ImportError, RuntimeError) as exc:
            if mode == "google":
                raise SystemExit(f"CALENDAR_MODE=google but Google is not set up: {exc}") from exc
            creds = None
        if creds is not None:
            log.info("calendar backend: Google Calendar (primary)")
            return GoogleCalendar(creds)
        if mode == "google":
            raise SystemExit("CALENDAR_MODE=google but no Google token. Run scripts/google_oauth.py first.")
    log.info("calendar backend: SANDBOX (simulated, data/calendar_sandbox.db)")
    return SandboxCalendar()
