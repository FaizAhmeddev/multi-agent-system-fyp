"""Check the Gmail connection (app password) and what AgentsMind can see. Writes logs/gmail-check.txt.

    .venv\\Scripts\\python scripts\\check_gmail.py      (or VS Code: "Check Gmail connection")

Read-only: nothing is sent, deleted or marked as read. The report has counts, subjects, senders and
attachment file names, never the password or email bodies.
"""
from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
REPORT = ROOT / "logs" / "gmail-check.txt"
lines: list[str] = []


def out(s: str = "") -> None:
    print(s, flush=True)
    lines.append(s)


def main() -> int:
    from mcp_servers.common import load_env

    load_env()
    import os

    from mcp_servers.workspace_mcp import imap_mail as im

    addr, pw = os.environ.get("GMAIL_EMAIL", ""), os.environ.get("GMAIL_APP_PASSWORD", "")
    out(f"Gmail check {time.strftime('%Y-%m-%d %H:%M:%S')}")
    out(f"GMAIL_EMAIL set: {bool(addr)} ({addr})   GMAIL_APP_PASSWORD set: {bool(pw)} ({len(pw.replace(' ', ''))} chars)")
    if not (addr and pw):
        out("Put GMAIL_EMAIL and GMAIL_APP_PASSWORD in .env and run this again.")
        return 1
    g = im.GmailIMAP(addr, pw)
    t = time.time()
    c = g._imap()
    out(f"Sign-in: OK ({time.time() - t:.1f} s)")
    typ, boxes = c.list()
    names = [b.decode(errors="replace") for b in boxes or []]
    out(f"Mailboxes ({len(names)}):")
    for n in names:
        out(f"  {n}")
    out(f"All Mail box found: {im._all_mail_box(c)}")
    typ, data = c.select("INBOX", readonly=True)
    out(f"INBOX messages: {data[0].decode() if data and data[0] else '?'}")
    uids = g._search(c, "")
    got = g._fetch_many(c, list(reversed(uids))[:5], limit=im.PREVIEW_BYTES)
    out(f"Newest 5 in INBOX (read {len(got)} of {min(5, len(uids))}):")
    for msg, meta in got:
        m = g._mail(msg, meta)
        out(f"  {m.date}  {m.sender[:60]}  |  {m.subject[:80]}  | unread={m.unread}")
    im._logout(c)
    c = g._imap(all_mail=True)
    for q in ("has:attachment", "has:attachment newer_than:365d",
              'has:attachment (cv OR resume OR "curriculum vitae" OR application) newer_than:90d'):
        n = len(g._search(c, q))
        out(f"All Mail search '{q}': {n} email(s)")
    im._logout(c)
    t = time.time()
    found = g.find_attachments("newer_than:365d", 20)
    out(f"Attachments in the newest 20 emails with attachments ({time.time() - t:.1f} s): {len(found)} PDF/Word/text "
        f"file(s) out of {getattr(g, 'last_searched', '?')} matching email(s)")
    for f in found[:20]:
        out(f"  {f['filename'][:60]}  ({f['mime_type']}, {f['size']} bytes)  from {f['sender'][:50]}  | {f['subject'][:60]}")
    if found:
        t = time.time()
        try:
            a = g.read_attachment(found[0]["message_id"], found[0]["attachment"])
            out(f"Read the first attachment: OK, {len(a['text'])} characters of text ({time.time() - t:.1f} s)")
        except Exception as exc:  # noqa: BLE001 - reported
            out(f"Read the first attachment: FAILED {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    try:
        rc = main()
    except Exception as exc:  # noqa: BLE001 - the report is the point
        out(f"FAILED: {type(exc).__name__}: {exc}")
        out(traceback.format_exc())
        rc = 1
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nReport written to {REPORT}")
    sys.exit(rc)
