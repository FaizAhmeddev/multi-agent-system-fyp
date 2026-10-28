"""Google backends with a fake API client: request shapes, replay handling, escaping.

No network and no credentials. Skipped where google-api-python-client is not installed.
"""
from __future__ import annotations

import base64
import email
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

errors = pytest.importorskip("googleapiclient.errors")

from mcp_servers.calendar_mcp import backends as cal  # noqa: E402
from mcp_servers.workspace_mcp import backends as ws  # noqa: E402


class Resp(dict):
    def __init__(self, status):
        super().__init__()
        self.status = status
        self.reason = "x"


def http_error(status):
    return errors.HttpError(Resp(status), b"{}")


class Req:
    def __init__(self, fn):
        self.fn = fn

    def execute(self, num_retries=0):
        return self.fn()


class FakeEvents:
    def __init__(self):
        self.store, self.calls = {}, []

    def insert(self, calendarId, body, **kw):
        self.calls.append(("insert", body, kw))

        def run():
            if body["id"] in self.store:
                raise http_error(409)
            ev = dict(body, status="confirmed", htmlLink="https://calendar.google.com/x")
            if "conferenceData" in body:
                ev["conferenceData"] = {"entryPoints": [{"entryPointType": "video", "uri": "https://meet.google.com/abc"}]}
            self.store[body["id"]] = ev
            return ev
        return Req(run)

    def get(self, calendarId, eventId):
        def run():
            if eventId not in self.store:
                raise http_error(404)
            return self.store[eventId]
        return Req(run)

    def delete(self, calendarId, eventId, sendUpdates):
        def run():
            if eventId not in self.store:
                raise http_error(410)
            del self.store[eventId]
            return {}
        return Req(run)


class FakeCal:
    def __init__(self):
        self.ev = FakeEvents()

    def events(self):
        return self.ev


def make_cal():
    g = object.__new__(cal.GoogleCalendar)
    g.svc, g.cal = FakeCal(), "primary"
    return g


def test_calendar_create_with_meet_replay_and_cancel():
    g = make_cal()
    tz = ZoneInfo("Asia/Karachi")
    s = datetime(2026, 10, 29, 15, tzinfo=tz)
    kw = dict(key="appr-abc-123", summary="Design review", start=s, end=s + timedelta(minutes=45), tz="Asia/Karachi",
              description="", location="", attendees=["a@example.com"], add_meet=True, notify=False)
    ev, created = g.create(**kw)
    assert created and ev.meet_link == "https://meet.google.com/abc"
    _, body, extra = g.svc.ev.calls[0]
    assert extra["conferenceDataVersion"] == 1 and extra["sendUpdates"] == "none"
    assert body["conferenceData"]["createRequest"]["conferenceSolutionKey"] == {"type": "hangoutsMeet"}
    assert body["id"] == cal.event_id_for("appr-abc-123") and set(body["id"]) <= set("0123456789abcdef")
    ev2, created2 = g.create(**kw)
    assert created2 is False and ev2.id == ev.id
    assert g.cancel(ev.id, False) is True and g.cancel(ev.id, False) is False


def test_gmail_send_builds_single_message_and_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_DATA_DIR", str(tmp_path))
    sent = []

    class Msgs:
        def send(self, userId, body):
            sent.append(body)
            return Req(lambda: {"id": f"m{len(sent)}", "threadId": "t1"})

    class Users:
        def messages(self):
            return Msgs()

    class Svc:
        def users(self):
            return Users()

    m = object.__new__(ws.GoogleMail)
    m.svc, m.ledger = Svc(), ws._ledger("ledger.db")
    a = m.send(key="appr-mail-1", to=["x@example.com"], subject="Hello", body="Body", cc=[], thread_id=None,
               in_reply_to="<id@example.com>")
    b = m.send(key="appr-mail-1", to=["x@example.com"], subject="Hello", body="Body", cc=[], thread_id=None,
               in_reply_to="<id@example.com>")
    assert len(sent) == 1 and a.sent and b.already_sent and b.message_id == a.message_id
    msg = email.message_from_bytes(base64.urlsafe_b64decode(sent[0]["raw"]))
    assert msg["To"] == "x@example.com" and msg["In-Reply-To"] == "<id@example.com>"


def test_drive_query_escaping():
    assert ws.drive_query_literal("O'Brien \\ CV") == "O\\'Brien \\\\ CV"


def test_plain_body_prefers_text_part():
    enc = base64.urlsafe_b64encode
    payload = {"mimeType": "multipart/alternative", "parts": [
        {"mimeType": "text/html", "body": {"data": enc(b"<p>Hi <b>there</b></p>").decode()}},
        {"mimeType": "text/plain", "body": {"data": enc(b"Hi there").decode()}}]}
    assert ws._plain_body(payload) == "Hi there"
