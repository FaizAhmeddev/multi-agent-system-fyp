"""Plain-language description of an executed approval, shown under the approval card."""
from __future__ import annotations

from typing import Any


def describe(tool: str, r: dict[str, Any]) -> dict[str, Any]:
    sim = bool(r.get("simulated"))
    links: list[dict[str, str]] = []
    if tool == "it_create_ticket":
        t = r.get("ticket", {})
        if r.get("confirmation_url"):
            links.append({"label": "Open the confirmation page", "url": r["confirmation_url"]})
        if r.get("tracking_url"):
            links.append({"label": "Track this ticket", "url": r["tracking_url"]})
        body = f"Ticket {t.get('number')} was {'created' if r.get('created') else 'already created earlier'}. " \
               f"{t.get('expected_response', '')}".strip()
    elif tool in ("calendar_create_event", "calendar_update_event"):
        e = r.get("event", {})
        verb = "created" if tool == "calendar_create_event" else "updated"
        if tool == "calendar_create_event" and not r.get("created", True):
            verb = "already created earlier"
        body = f"\"{e.get('summary')}\" was {verb}: {e.get('start')} to {e.get('end')}."
        if tool == "calendar_create_event":
            body += " Read back from the calendar: " + ("confirmed." if r.get("verified") else "NOT confirmed.")
        if e.get("meet_link"):
            links.append({"label": "Meet link", "url": e["meet_link"]})
        if e.get("html_link"):
            links.append({"label": "Open in Google Calendar", "url": e["html_link"]})
    elif tool == "calendar_cancel_event":
        body = "The event was already cancelled." if r.get("already_cancelled") else "The event was cancelled."
    elif tool == "gmail_send_email":
        body = (f"Email to {', '.join(r.get('to', []))} " +
                ("was already sent earlier; nothing was sent again." if r.get("already_sent") else "was sent.") +
                (" (Simulated: nothing was delivered.)" if sim else ""))
    elif tool == "finance_create_person":
        p = r.get("person", {})
        body = f"{p.get('full_name')} was {'added' if r.get('created') else 'already added earlier'} (record {p.get('id')})."
    elif tool == "finance_update_person":
        body = f"{r.get('full_name')}'s record was updated."
    elif tool == "finance_delete_person":
        body = f"{r.get('full_name')}'s record and {r.get('payments_deleted', 0)} payment record(s) were deleted."
    elif tool == "it_update_ticket_status":
        body = f"{r.get('number')} is now {str(r.get('status', '')).replace('_', ' ')}."
    elif tool == "it_add_comment":
        body = f"Comment added to {r.get('number')}."
    else:
        body = "Done."
    return {"body": body, "links": links, "simulated": sim}
