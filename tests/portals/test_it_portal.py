"""IT Helpdesk: public complaint form, confirmation screen, tracking, uploads, workflow and REST API."""
from __future__ import annotations

import re

from phelpers import H, csrf_of, web_login

COMPLAINT = {"requester_name": "Omar Farooq", "requester_email": "omar.farooq@example.com", "department": "Operations",
             "category": "network", "priority": "medium", "summary": "Laptop cannot join office Wi-Fi",
             "description": "My laptop cannot connect to office wifi since this morning."}


def _submit(it, files=None, **over):
    page = it.get("/")
    data = {**COMPLAINT, **over, "csrf": csrf_of(page.text),
            "form_key": re.search(r'name="form_key" value="([^"]+)"', page.text).group(1)}
    return it.post("/complaint", data=data, files=files, follow_redirects=False)


def test_public_form_creates_ticket_and_shows_confirmation(it):
    r = _submit(it)
    assert r.status_code == 303 and r.headers["location"].startswith("/complaint/submitted/ITK-000001?t=")
    page = it.get(r.headers["location"])
    assert page.status_code == 200
    text = page.text
    assert "Complaint submitted" in text and "ITK-000001" in text and "Laptop cannot join office Wi-Fi" in text
    assert "within 24 hours" in text and "Track this ticket" in text
    track = re.search(r'href="(/track/ITK-000001\?t=[^"]+)"', text).group(1)
    t = it.get(track.replace("&amp;", "&"))
    assert t.status_code == 200 and "Open" in t.text


def test_confirmation_and_tracking_need_the_token(it):
    _submit(it)
    assert it.get("/complaint/submitted/ITK-000001").status_code == 404
    assert it.get("/track/ITK-000001?t=guess").status_code == 404


def test_form_validation_inline(it):
    r = _submit(it, requester_email="bad", description="short", category="")
    assert r.status_code == 422 and 'aria-invalid="true"' in r.text


def test_upload_checks(it):
    big = ("big.pdf", b"%PDF-" + b"0" * (5 * 1024 * 1024), "application/pdf")
    assert _submit(it, files={"attachment": big}).status_code == 413
    exe = ("invoice.pdf", b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 64, "application/pdf")
    r = _submit(it, files={"attachment": exe})
    assert r.status_code == 415 and "PDF, PNG, JPEG" in r.text
    good = ("../../etc/screen shot (1).png", b"\x89PNG\r\n\x1a\n" + b"x" * 100, "image/png")
    assert _submit(it, files={"attachment": good}).status_code == 303
    web_login(it, "/staff/login")
    page = it.get("/staff/tickets/ITK-000001").text
    assert "screen shot _1_.png" in page and "../" not in page


def test_double_submit_does_not_duplicate(it):
    page = it.get("/")
    data = {**COMPLAINT, "csrf": csrf_of(page.text), "form_key": "same-key-123"}
    assert it.post("/complaint", data=data, follow_redirects=False).status_code == 303
    assert it.post("/complaint", data=data, follow_redirects=False).status_code == 409
    assert it.get("/api/v1/tickets", headers=H).json()["total"] == 1


def test_api_create_is_idempotent_and_returns_confirmation_link(it):
    """Acceptance scenario 5 (ticket half)."""
    body = {k: v for k, v in COMPLAINT.items()}
    hk = {**H, "Idempotency-Key": "appr-ticket-001"}
    a = it.post("/api/v1/tickets", json=body, headers=hk)
    b = it.post("/api/v1/tickets", json=body, headers=hk)
    assert a.status_code == 201 and b.status_code == 200
    assert a.json()["ticket"]["number"] == b.json()["ticket"]["number"] == "ITK-000001"
    assert a.json()["ticket"]["source"] == "agentsmind"
    link = a.json()["confirmation_url"]
    assert link.startswith("http://testserver/complaint/submitted/ITK-000001?t=")
    assert "Complaint submitted" in it.get(link.replace("http://testserver", "")).text
    assert "confirmation_url" not in b.json()  # the token is never re-issued
    assert it.get("/api/v1/tickets", headers=H).json()["total"] == 1


def test_ticket_created_on_portal_is_visible_through_api(it):
    _submit(it)
    lst = it.get("/api/v1/tickets?requester_email=omar.farooq@example.com", headers=H).json()
    assert lst["items"][0]["number"] == "ITK-000001" and lst["items"][0]["source"] == "portal"


def test_status_workflow(it):
    it.post("/api/v1/tickets", json=COMPLAINT, headers=H)
    ok = it.patch("/api/v1/tickets/ITK-000001/status", json={"status": "in_progress", "comment": "On it"}, headers=H)
    assert ok.status_code == 200 and ok.json()["status"] == "in_progress"
    assert it.patch("/api/v1/tickets/ITK-000001/status", json={"status": "resolved"}, headers=H).status_code == 200
    assert it.patch("/api/v1/tickets/ITK-000001/status", json={"status": "closed"}, headers=H).status_code == 200
    bad = it.patch("/api/v1/tickets/ITK-000001/status", json={"status": "open"}, headers=H)
    assert bad.status_code == 409 and "cannot go from Closed" in bad.json()["detail"]["message"]
    c = it.post("/api/v1/tickets/ITK-000001/comments", json={"body": "hello"}, headers=H)
    assert c.status_code == 409


def test_sla_due_time_follows_priority(it):
    from datetime import datetime

    t = it.post("/api/v1/tickets", json={**COMPLAINT, "priority": "urgent"}, headers=H).json()["ticket"]
    hours = (datetime.fromisoformat(t["sla_due_at"]) - datetime.fromisoformat(t["created_at"])).total_seconds() / 3600
    assert hours == 4 and t["expected_response"] == "within 4 hours"


def test_staff_screens(it):
    _submit(it)
    assert it.get("/staff/tickets", follow_redirects=False).status_code == 303
    web_login(it, "/staff/login")
    lst = it.get("/staff/tickets?status=open")
    assert "ITK-000001" in lst.text
    page = it.get("/staff/tickets/ITK-000001")
    csrf = csrf_of(page.text)
    r = it.post("/staff/tickets/ITK-000001/assign", data={"assignee": "portal.admin@example.com", "csrf": csrf})
    assert r.status_code == 200 and "Assigned to portal.admin@example.com" in r.text
    r = it.post("/staff/tickets/ITK-000001/status", data={"status": "in_progress", "comment": "Checking", "csrf": csrf})
    assert "Status changed to In progress" in r.text
    r = it.post("/staff/tickets/ITK-000001/comment", data={"body": "Internal note", "internal": "1", "csrf": csrf})
    assert "Comment added" in r.text
    # internal notes stay hidden from the requester
    view = it.get("/api/v1/tickets/ITK-000001", headers=H).json()
    assert any(c["internal"] for c in view["comments"])


def test_api_key_required(it):
    assert it.post("/api/v1/tickets", json=COMPLAINT).status_code == 401
