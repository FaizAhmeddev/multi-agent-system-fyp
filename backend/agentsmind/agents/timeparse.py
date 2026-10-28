"""Deterministic date and time parsing for scheduling prompts, in the user's time zone.

Examples (time zone Asia/Karachi):
    "tomorrow at 3 pm for 45 minutes"   -> start tomorrow 15:00, 45 minutes
    "Friday afternoon"                  -> window Friday 12:00-17:00
    "next Monday at 10:30"              -> the next Monday after today, 10:30
    "on 1 December at noon for an hour" -> 1 Dec 12:00, 60 minutes

Rules (shown to the user on the approval card, so they can correct anything):
    - "Monday", "this Monday" and "next Monday" all mean the first Monday after today.
    - A date without a year is the next time that date occurs (today counts).
    - No time given: no start time is returned and the agent asks for one.
This module has no third-party imports, so it is unit tested on its own.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]
MONTH_ALIASES = {m[:3]: i + 1 for i, m in enumerate(MONTHS)} | {m: i + 1 for i, m in enumerate(MONTHS)}
MONTH_ALIASES["sept"] = 9
PARTS_OF_DAY = {"morning": (time(9), time(12)), "afternoon": (time(12), time(17)), "evening": (time(17), time(20))}
WORD_NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "half an": 0.5, "half": 0.5}

_MONTH_RE = "|".join(sorted(MONTH_ALIASES, key=len, reverse=True))
_WD_RE = "|".join(WEEKDAYS)


@dataclass(frozen=True)
class ParsedWhen:
    day: date | None
    start: datetime | None  # tz-aware, set only when a time of day was given
    duration_minutes: int | None
    window: tuple[datetime, datetime] | None  # set for "Friday afternoon" style ranges
    day_phrase: str  # the words that produced `day`, for the approval card
    tz: str

    @property
    def end(self) -> datetime | None:
        if self.start and self.duration_minutes:
            return self.start + timedelta(minutes=self.duration_minutes)
        return None


def _next_weekday(today: date, wd: int) -> date:
    delta = (wd - today.weekday()) % 7
    return today + timedelta(days=delta or 7)


def parse_day(text: str, today: date) -> tuple[date | None, str]:
    t = text.lower()
    if re.search(r"\bday after tomorrow\b", t):
        return today + timedelta(days=2), "day after tomorrow"
    if re.search(r"\btomorrow\b", t):
        return today + timedelta(days=1), "tomorrow"
    if re.search(r"\btoday\b|\btonight\b|\bthis (morning|afternoon|evening)\b", t):
        return today, "today"
    m = re.search(r"\bin (\d{1,2}) days?\b", t)
    if m:
        return today + timedelta(days=int(m.group(1))), m.group(0)
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))), m.group(0)
        except ValueError:
            return None, ""
    m = (re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH_RE})\b\.?(?:\s+(\d{{4}}))?", t)
         or re.search(rf"\b({_MONTH_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(\d{{4}}))?", t))
    if m:
        a, b, y = m.group(1), m.group(2), m.group(3)
        day_s, mon_s = (a, b) if a.isdigit() else (b, a)
        mon, dd = MONTH_ALIASES[mon_s], int(day_s)
        try:
            if y:
                return date(int(y), mon, dd), m.group(0)
            cand = date(today.year, mon, dd)
            if cand < today:
                cand = date(today.year + 1, mon, dd)
            return cand, m.group(0)
        except ValueError:
            return None, ""
    m = re.search(rf"\b(?:(?:this|next|on|coming)\s+)?({_WD_RE})(?:'s)?\b", t)
    if m:
        return _next_weekday(today, WEEKDAYS.index(m.group(1))), m.group(0).strip()
    return None, ""


_TIME_RES = [
    re.compile(r"\b(?:at|from|@)?\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)", re.I),
    re.compile(r"\b(?:at|from)\s+(\d{1,2}):(\d{2})\b", re.I),
    re.compile(r"\b(\d{1,2}):(\d{2})\b"),
]


def parse_time(text: str) -> time | None:
    t = text.lower()
    if re.search(r"\bnoon\b|\bmidday\b", t):
        return time(12)
    for i, rx in enumerate(_TIME_RES):
        m = rx.search(t)
        if not m:
            continue
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        if i == 0:
            ap = m.group(3).replace(".", "")
            if not 1 <= h <= 12:
                continue
            h = (h % 12) + (12 if ap == "pm" else 0)
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return time(h, mi)
    return None


def all_times(text: str) -> list[time]:
    """Every time of day mentioned, in order (used for 'move my 3 pm meeting to 4 pm')."""
    out = []
    for m in re.finditer(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)", text.lower()):
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        if 1 <= h <= 12 and mi < 60:
            out.append(time((h % 12) + (12 if m.group(3).replace(".", "") == "pm" else 0), mi))
    for m in re.finditer(r"\b(?:at|to|from)\s+(\d{1,2}):(\d{2})\b(?!\s*(?:am|pm))", text.lower()):
        h, mi = int(m.group(1)), int(m.group(2))
        if h < 24 and mi < 60:
            out.append(time(h, mi))
    return out


def parse_duration(text: str) -> int | None:
    t = text.lower()
    m = re.search(r"\bfor\s+(\d+(?:\.\d+)?)\s*(minutes?|mins?|m)\b", t)
    if m:
        return int(round(float(m.group(1))))
    m = re.search(r"\bfor\s+(\d+(?:\.\d+)?)\s*(hours?|hrs?|h)\b", t)
    if m:
        return int(round(float(m.group(1)) * 60))
    m = re.search(r"\bfor\s+(half an|an|a|one|two|three|four)\s+hours?\b", t)
    if m:
        return int(WORD_NUM[m.group(1)] * 60)
    if re.search(r"\bfor\s+half an hour\b|\bfor\s+30\b", t):
        return 30
    m = re.search(r"\b(\d+)\s*-?\s*(minute|min)\b", t)
    if m:
        return int(m.group(1))
    return None


def parse_when(text: str, *, tz: str, now: datetime | None = None) -> ParsedWhen:
    zone = ZoneInfo(tz)
    now = (now or datetime.now(zone)).astimezone(zone)
    day, phrase = parse_day(text, now.date())
    tod = parse_time(text)
    dur = parse_duration(text)
    window = None
    lowered = text.lower()
    part = next((p for p in PARTS_OF_DAY if re.search(rf"\b{p}\b", lowered)), None)
    if day is None and tod is not None:
        # "at 3 pm" alone: today if still ahead, otherwise tomorrow
        day = now.date() if datetime.combine(now.date(), tod, zone) > now else now.date() + timedelta(days=1)
        phrase = "today" if day == now.date() else "tomorrow"
    if part and day is not None and tod is None:
        a, b = PARTS_OF_DAY[part]
        window = (datetime.combine(day, a, zone), datetime.combine(day, b, zone))
    start = datetime.combine(day, tod, zone) if (day is not None and tod is not None) else None
    return ParsedWhen(day=day, start=start, duration_minutes=dur, window=window, day_phrase=phrase, tz=tz)
