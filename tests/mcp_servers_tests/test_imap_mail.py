"""Gmail by app password: the inbox is read with one batched FETCH and attachments are found (no network)."""
from __future__ import annotations

from email.message import EmailMessage

from mcp_servers.workspace_mcp import imap_mail


def _raw(subject: str, body: str, attach: bool = False) -> bytes:
    m = EmailMessage()
    m["From"] = "Sara <sara@gmail.com>"
    m["To"] = "hr@company.pk"
    m["Subject"] = subject
    m["Date"] = "Wed, 28 Oct 2026 10:00:00 +0500"
    m.set_content(body)
    if attach:
        m.add_attachment(b"%PDF-1.4 cv", maintype="application", subtype="pdf", filename="Sara CV.pdf")
    return m.as_bytes()


class FakeIMAP:
    def __init__(self, msgs: dict[bytes, bytes]):
        self.msgs, self.fetches = msgs, []

    def uid(self, cmd, *args):
        if cmd == "SEARCH":
            return "OK", [b" ".join(self.msgs)]
        self.fetches.append(args)
        out = []
        for u in args[0].split(b","):
            out += [(b"%s (UID %s X-GM-MSGID 9%s X-GM-THRID 7%s FLAGS (\\Seen) BODY[] {10}" % (u, u, u, u),
                     self.msgs[u]), b")"]
        return "OK", out

    def logout(self):
        pass


def test_inbox_uses_one_fetch_and_newest_first(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKSPACE_DATA_DIR", str(tmp_path))
    fake = FakeIMAP({b"1": _raw("Old", "first"), b"2": _raw("New", "second"), b"3": _raw("CV", "cv", True)})
    g = imap_mail.GmailIMAP("hr@gmail.com", "abcd efgh ijkl mnop")
    monkeypatch.setattr(g, "_imap", lambda all_mail=False: fake)
    mails, nxt = g.inbox(2, False, "", None)
    assert [m.subject for m in mails] == ["CV", "New"] and nxt == "2"
    assert len(fake.fetches) == 1 and "<0." in fake.fetches[0][1]  # partial bodies, one round trip
    assert mails[1].id == "92" and not mails[1].unread
    found = g.find_attachments("", 10)
    assert [(f["filename"], f["message_id"]) for f in found] == [("Sara CV.pdf", "93")]
