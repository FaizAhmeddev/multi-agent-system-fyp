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
    elif tool == "hr_run_workflow":
        steps = r.get("steps", [])
        failed = [s for s in steps if s.get("status") != "ok"]
        body = (f"{r.get('title') or 'HR workflow'}: {r.get('ok', 0)} of {len(steps)} step(s) done."
                + (" Failed: " + "; ".join(f"{s['title']} ({s.get('error', '')})" for s in failed) if failed else ""))
        if r.get("employee_id"):
            links.append({"label": f"Open {r.get('employee_code') or 'the employee'} in HR",
                          "url": f"/hr/employees/{r['employee_id']}"})
        for lt in (r.get("letters") or {}).values():
            links.append({"label": f"{lt['title']} (PDF)", "url": f"/api/hr/letters/{lt['id']}/pdf"})
    elif tool == "payroll_enroll_employee":
        p = r.get("person", {})
        body = f"{p.get('full_name')} was {'added to' if r.get('created') else 'already on'} payroll (record {p.get('id')})."
    elif tool == "payroll_end_employment":
        body = f"{r.get('full_name')} is now inactive in payroll."
    elif tool == "payroll_record_payment":
        pm = r.get("payment") or {}
        body = (f"Payment of {pm.get('currency', '')} {pm.get('amount', '')} for {pm.get('month', '')} recorded."
                if r.get("recorded") else r.get("message") or "Payment was already recorded.")
    elif tool == "whatsapp_send":
        body = ("WhatsApp message was already sent earlier." if r.get("already_sent")
                else f"WhatsApp message to {r.get('to', '')} {r.get('status', 'queued')}.")
    elif tool == "sheets_append":
        body = ("Those rows were already added earlier." if r.get("already_done")
                else f"{r.get('appended', 0)} row(s) added to {r.get('tab', 'the sheet')}.")
    elif tool == "sheets_update_row":
        body = f"Row {r.get('updated_row')} updated."
    elif tool == "drive_upload_file":
        body = f"{r.get('name')} uploaded to Google Drive."
        if r.get("web_link"):
            links.append({"label": "Open in Drive", "url": r["web_link"]})
    else:
        body = "Done."
    return {"body": body, "links": links, "simulated": sim}
