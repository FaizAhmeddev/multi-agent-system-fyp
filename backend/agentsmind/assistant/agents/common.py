"""Small helpers shared by the agents (pure Python, unit tested)."""
from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
STOP = {"a", "an", "the", "my", "our", "me", "i", "to", "for", "on", "at", "of", "in", "and", "with", "please", "can",
        "you", "could", "would", "meeting", "meetings", "event", "call", "s", "this", "next", "that", "is", "it", "be"}


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP and len(w) > 1}


def has_any(text: str, *phrases: str) -> bool:
    t = text.lower()
    return any(re.search(rf"\b{p}\b", t) for p in phrases)


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def fmt_dt(dt: datetime, tz: str) -> str:
    d = dt.astimezone(ZoneInfo(tz))
    return d.strftime("%a %d %b %Y, %H:%M")


def fmt_range(a: datetime, b: datetime, tz: str) -> str:
    da, db = a.astimezone(ZoneInfo(tz)), b.astimezone(ZoneInfo(tz))
    end = db.strftime("%H:%M") if da.date() == db.date() else fmt_dt(db, tz)
    return f"{fmt_dt(da, tz)} to {end} ({tz})"


def emails(text: str) -> list[str]:
    seen: list[str] = []
    for e in EMAIL_RE.findall(text):
        e = e.rstrip(".").lower()
        if e not in seen:
            seen.append(e)
    return seen


def quoted(text: str) -> str | None:
    m = re.search(r"[\"“]([^\"”]{2,120})[\"”]", text)
    return m.group(1).strip() if m else None
