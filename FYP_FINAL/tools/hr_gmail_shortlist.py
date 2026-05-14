"""
HR Gmail shortlist — operational workflow (not chat-only):
  IMAP: scan recent inbox messages → extract PDF/DOCX CVs → parse + JD match → top N
  → draft interview emails → persist to SQLite → send only after explicit approval (UI button or chat **approve and send**).
"""

from __future__ import annotations

import io
import re
import uuid
import imaplib
import email
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.header import decode_header
from typing import Any

from recruitment.agents.cv_parsing_agent import parse_cv_structured
from recruitment.agents.jd_analysis_agent import analyze_job_description
from recruitment.agents.matching_agent import match_candidate_to_jd
from recruitment.agents.email_drafting_agent import draft_interview_invitation
from database.sqlite_db import hr_shortlist_save_batch, hr_shortlist_get_batch, hr_shortlist_update_status, log_agent

HR_GMAIL_BATCH_MARKER_PREFIX = "[[HR_GMAIL_BATCH_ID:"
HR_GMAIL_BATCH_MARKER_SUFFIX = "]]"


def _decode_mime_header(s: str | None) -> str:
    if not s:
        return ""
    parts = decode_header(s)
    out: list[str] = []
    for frag, enc in parts:
        if isinstance(frag, bytes):
            out.append(frag.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(str(frag or ""))
    return "".join(out)


def _extract_text_from_attachment(filename: str, data: bytes) -> str:
    fn = (filename or "").lower()
    if fn.endswith(".pdf"):
        try:
            import pdfplumber

            with pdfplumber.open(io.BytesIO(data)) as pdf:
                return "\n".join((p.extract_text() or "") for p in pdf.pages)
        except Exception:
            try:
                import PyPDF2

                r = PyPDF2.PdfReader(io.BytesIO(data))
                return "\n".join((p.extract_text() or "") for p in r.pages)
            except Exception:
                return ""
    if fn.endswith(".docx"):
        try:
            import docx

            d = docx.Document(io.BytesIO(data))
            return "\n".join(p.text for p in d.paragraphs)
        except Exception:
            return ""
    return ""


def gmail_fetch_cv_attachments(max_messages: int = 50) -> list[dict[str, Any]]:
    """
    Scan the last ``max_messages`` inbox messages (IMAP order) and return one row
    per CV attachment (PDF/DOCX) with extracted plain text.
    """
    from config import GMAIL_EMAIL, GMAIL_APP_PASSWORD

    out: list[dict[str, Any]] = []
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(GMAIL_EMAIL, GMAIL_APP_PASSWORD)
    mail.select("inbox")
    status, data = mail.search(None, "ALL")
    mail_ids = data[0].split()
    if not mail_ids:
        mail.logout()
        return []

    subset = mail_ids[-max_messages:] if len(mail_ids) > max_messages else mail_ids
    for num in reversed(subset):
        try:
            st, msg_data = mail.fetch(num, "(RFC822)")
            if st != "OK" or not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            from_name, from_email = email.utils.parseaddr(msg.get("From", ""))
            subject = _decode_mime_header(msg.get("Subject", ""))
            for part in msg.walk():
                if part.get_content_maintype() == "multipart":
                    continue
                fn = part.get_filename()
                if not fn:
                    continue
                fn_dec = _decode_mime_header(fn)
                low = fn_dec.lower()
                if not (low.endswith(".pdf") or low.endswith(".docx")):
                    continue
                try:
                    data_b = part.get_payload(decode=True) or b""
                except Exception:
                    data_b = b""
                if len(data_b) < 80:
                    continue
                text = _extract_text_from_attachment(fn_dec, data_b)
                if len(text.strip()) < 60:
                    continue
                out.append(
                    {
                        "imap_id": num.decode() if isinstance(num, bytes) else str(num),
                        "from_email": (from_email or "").strip(),
                        "from_name": (from_name or "").strip(),
                        "subject": subject,
                        "filename": fn_dec,
                        "content": text,
                    }
                )
        except Exception:
            continue
    mail.logout()
    return out


def parse_gmail_shortlist_prompt(message: str) -> dict[str, Any] | None:
    """
    Detect natural-language requests like:
    "fetch last 40 emails CVs and select 5 candidates for python and email them"
    """
    m = (message or "").strip()
    if len(m) < 20:
        return None
    low = m.lower()
    has_inbox = any(
        x in low
        for x in ("email", "e-mail", "emails", "inbox", "gmail", "mail message", "messages")
    )
    has_cv = any(x in low for x in ("cv", "resume", "candidat", "applicant"))
    has_fetch = any(
        x in low
        for x in ("fetch", "scan", "pull", "get", "retrieve", "collect", "read last", "last ")
    )
    if not (has_inbox and has_cv and has_fetch):
        return None

    max_messages = 50
    for pat in (
        r"(?:last|past|recent)\s+(\d+)\s+(?:e-?mails?|emails?|messages?)",
        r"(?:fetch|get|scan|pull|collect|retrieve)\s+(\d+)\s+(?:e-?mails?|emails?|messages?)",
        r"(\d+)\s+(?:e-?mails?|emails?|messages?)\s+(?:from|in)\s+(?:my\s+)?(?:inbox|gmail|mail)",
    ):
        mm = re.search(pat, low, re.I)
        if mm:
            max_messages = max(5, min(100, int(mm.group(1))))
            break

    top_n = 5
    for pat in (
        r"select\s+(?:the\s+)?(?:top\s*)?(\d+)\s+candidates?",
        r"(?:pick|choose|take)\s+(\d+)\s+candidates?",
        r"(\d+)\s+best\s+candidates?",
        r"top\s*(\d+)\s+candidates?",
        r"shortlist\s+(\d+)",
    ):
        mm = re.search(pat, low, re.I)
        if mm:
            top_n = max(1, min(25, int(mm.group(1))))
            break

    interview_when = "To be scheduled — confirm by reply."
    im = re.search(
        r"(?i)(interview\s+(?:on\s+|at\s+)?[^.;]{5,140}|"
        r"(?:tomorrow|today|monday|tuesday|wednesday|thursday|friday|saturday|sunday)[^.;\n]{0,100})",
        m,
    )
    if im:
        interview_when = im.group(1).strip()[:220]

    job_criteria = _infer_job_criteria_from_prompt(m)
    company = "Our Company"
    cm = re.search(r"(?i)company\s*[:\-]\s*([^.;,\n]{2,80})", m)
    if cm:
        company = cm.group(1).strip()[:120]

    return {
        "max_messages": max_messages,
        "top_n": top_n,
        "job_criteria": job_criteria,
        "interview_when": interview_when,
        "company": company,
    }


def _infer_job_criteria_from_prompt(message: str) -> str:
    m = re.search(r"(?i)for\s+(.+?)(?:\s+and\s+email|\s*,\s*email|\s+email\s+them|\.|$)", message)
    if m:
        return m.group(1).strip()[:1500]
    tech = re.search(
        r"(?i)\b(python|java|javascript|typescript|react|django|flask|node\.?js|sql|"
        r"data\s+scientist|data\s+entry|devops|aws|ml\b|machine\s+learning)\b[^.;]{0,120}",
        message,
    )
    if tech:
        return f"Hiring focus: {tech.group(0).strip()}. Full request: {message[:700]}"
    return (message or "").strip()[:1500]


def format_hr_gmail_orchestrator_reply(res: dict[str, Any]) -> str:
    if not res.get("ok"):
        return f"**Gmail CV shortlist**\n\n{res.get('error', 'Failed.')}"

    drafts = res.get("drafts") or []
    bid = res.get("batch_id") or ""
    lines = [
        "**Gmail CV shortlist** (IMAP → parse → match → drafts saved)",
        "",
        f"**Batch ID:** `{bid}`",
        f"**Role title (inferred):** {res.get('role_title', '')}",
        f"**CV attachments parsed:** {res.get('attachments_parsed', 0)}",
        "",
        "**Human-in-the-loop:** nothing was sent yet. Use **Approve & send interview emails** below (or on the **HR** tab), "
        "or type **approve and send** in this chat (batch id is taken from this thread or paste the UUID).",
        "",
        "### Shortlist",
    ]
    for d in drafts:
        ok = "yes" if d.get("sendable") else "**missing email**"
        lines.append(f"- **{d.get('candidate_name')}** — match **{d.get('match_score')}** — sendable: {ok}")
    if drafts:
        p0 = drafts[0]
        lines += ["", "### First draft preview", "", f"**Subject:** {p0.get('subject', '')}", "", (p0.get("body") or "")[:1800]]

    marker = f"\n\n{HR_GMAIL_BATCH_MARKER_PREFIX}{bid}{HR_GMAIL_BATCH_MARKER_SUFFIX}"
    return "\n".join(lines) + marker


def run_gmail_shortlist_from_user_prompt(
    *,
    user_message: str,
    user_name: str,
    user_role: str,
) -> dict[str, Any]:
    spec = parse_gmail_shortlist_prompt(user_message)
    if not spec:
        return {"ok": False, "error": "Not recognized as a Gmail inbox CV shortlist request."}
    return run_gmail_shortlist_pipeline(
        job_criteria=spec["job_criteria"],
        interview_when=spec["interview_when"],
        company=spec["company"],
        user_name=user_name,
        user_role=user_role,
        max_messages=int(spec["max_messages"]),
        top_n=int(spec["top_n"]),
    )


def extract_hr_gmail_batch_id(text: str) -> str | None:
    m = re.search(
        re.escape(HR_GMAIL_BATCH_MARKER_PREFIX) + r"([a-f0-9\-]{36})" + re.escape(HR_GMAIL_BATCH_MARKER_SUFFIX),
        text or "",
        re.I,
    )
    return m.group(1) if m else None


def strip_hr_gmail_batch_marker(text: str) -> str:
    return re.sub(
        r"\n*\[\[HR_GMAIL_BATCH_ID:[a-f0-9\-]{36}\]\]\s*",
        "",
        text or "",
        flags=re.I,
    ).strip()


def user_requests_hr_gmail_approve_send(message: str) -> bool:
    """
    Explicit chat opt-in to SMTP-send a pending Gmail shortlist batch.
    Kept narrow so normal \"send an email\" requests are not confused with this path.
    """
    low = (message or "").lower().strip()
    if len(low) < 12:
        return False
    phrases = (
        "approve and send",
        "approve & send",
        "approve send",
        "send the interview emails",
        "send interview emails",
        "send pending interview",
        "send gmail shortlist",
        "send the gmail shortlist",
    )
    return any(p in low for p in phrases)


def resolve_hr_gmail_batch_id_for_send(
    user_message: str,
    conversation_history: list[dict[str, str]] | None,
) -> str | None:
    """
    When ``user_requests_hr_gmail_approve_send`` is true: resolve batch UUID from the
    current message or the most recent assistant reply in this thread (Batch ID line).
    """
    if not user_requests_hr_gmail_approve_send(user_message):
        return None
    msg = user_message or ""
    um = re.search(
        r"\b([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})\b",
        msg,
        re.I,
    )
    if um:
        return um.group(1).lower()
    for entry in reversed(conversation_history or []):
        role = (entry.get("role") or "").strip().lower()
        if role not in ("assistant", "agent"):
            continue
        content = entry.get("content") or ""
        m = extract_hr_gmail_batch_id(content)
        if m:
            return m.lower()
        m2 = re.search(r"\*\*Batch ID:\*\*\s*`([a-f0-9\-]{36})`", content, re.I)
        if m2:
            return m2.group(1).lower()
    return None


def format_hr_gmail_approve_send_reply(sr: dict[str, Any]) -> str:
    if sr.get("ok"):
        n = int(sr.get("emails_sent") or 0)
        tot = int(sr.get("total") or 0)
        lines = [
            "**Gmail CV shortlist — sent**",
            "",
            f"**Delivered:** {n} / {tot} interview email(s) via Gmail SMTP.",
            "",
            "### Per recipient",
        ]
        for row in sr.get("details") or []:
            rec = row.get("recipient", "")
            st = row.get("status", row.get("error", ""))
            ok = row.get("ok")
            mark = "✅" if ok else "❌"
            lines.append(f"- {mark} `{rec}` — {st}")
        return "\n".join(lines)
    err = sr.get("error") or "Send failed."
    lines = ["**Gmail CV shortlist — send failed**", "", str(err)]
    if sr.get("details"):
        lines += ["", "### Details"]
        for row in sr["details"]:
            lines.append(f"- `{row.get('recipient', '')}` — {row.get('status', row.get('error', ''))}")
    return "\n".join(lines)


def _one_match(
    jd_profile: dict[str, Any],
    row: dict[str, Any],
    role_title: str,
) -> dict[str, Any]:
    hint = row.get("from_name") or row.get("filename") or "Candidate"
    parsed = parse_cv_structured(row.get("content") or "", filename=row.get("filename") or "", name_hint=hint)
    match = match_candidate_to_jd(parsed, jd_profile)
    score = int(match.get("match_score") or 0)
    rec_email = (parsed.get("email") or "").strip()
    if not rec_email or "@" not in rec_email:
        rec_email = (row.get("from_email") or "").strip()
    return {
        "parsed": parsed,
        "match": match,
        "match_score": score,
        "recipient": rec_email,
        "from_email": row.get("from_email"),
        "subject_mail": row.get("subject"),
        "filename": row.get("filename"),
        "cv_excerpt": (row.get("content") or "")[:1200],
    }


def run_gmail_shortlist_pipeline(
    *,
    job_criteria: str,
    interview_when: str,
    company: str,
    user_name: str,
    user_role: str,
    max_messages: int = 50,
    top_n: int = 5,
    max_workers: int = 5,
) -> dict[str, Any]:
    """
    Fetch CVs from Gmail, rank vs ``job_criteria``, draft interview emails for top ``top_n``.
    Persists batch with status ``pending_send`` (human must approve send).
    """
    job_criteria = (job_criteria or "").strip()
    if not job_criteria:
        return {"ok": False, "error": "Enter role / job criteria (e.g. Python developer skills)."}

    rows = gmail_fetch_cv_attachments(max_messages=max(5, min(100, int(max_messages))))
    if not rows:
        return {
            "ok": False,
            "error": "No PDF/DOCX CV attachments found in the scanned messages. "
            "Check inbox, labels, and that CVs are attached (not only links in body).",
        }

    jd_profile = analyze_job_description(job_criteria, role_title_hint="")
    role_title = (jd_profile.get("role_title") or "Open role").strip() or "Open role"

    scored: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_one_match, jd_profile, r, role_title): r for r in rows}
        for fut in as_completed(futs):
            row0 = futs[fut]
            try:
                scored.append(fut.result())
            except Exception as e:
                scored.append(
                    {
                        "parsed": {"name": "Candidate", "parse_status": str(e)},
                        "match": {"match_score": 0, "weaknesses": [str(e)]},
                        "match_score": 0,
                        "recipient": row0.get("from_email"),
                        "from_email": row0.get("from_email"),
                        "subject_mail": row0.get("subject"),
                        "filename": row0.get("filename"),
                        "cv_excerpt": "",
                    }
                )

    scored.sort(key=lambda x: -int(x.get("match_score") or 0))
    tn = max(1, min(25, int(top_n)))
    top = scored[:tn]

    drafts_out: list[dict[str, Any]] = []
    for item in top:
        parsed = item.get("parsed") or {}
        match = item.get("match") or {}
        name = (parsed.get("name") or "Candidate").strip()
        strengths = list(match.get("strengths") or [])[:6]
        dr = draft_interview_invitation(
            candidate_name=name,
            role_title=role_title,
            company=company or "Our Company",
            interview_when=interview_when,
            meeting_details="Please reply to confirm; calendar or video link will follow.",
            strengths_hint=strengths,
        )
        rec = (item.get("recipient") or "").strip()
        sendable = bool(rec and "@" in rec)
        drafts_out.append(
            {
                "candidate_name": name,
                "recipient": rec,
                "sendable": sendable,
                "match_score": int(item.get("match_score") or 0),
                "subject": dr.get("subject"),
                "body": dr.get("body"),
                "dimensions": match.get("dimensions") or {},
                "strengths": match.get("strengths") or [],
                "weaknesses": match.get("weaknesses") or [],
                "rationale": match.get("rationale") or "",
                "source_mail_subject": item.get("subject_mail") or "",
                "cv_filename": item.get("filename") or "",
            }
        )

    batch_id = str(uuid.uuid4())
    payload = {
        "top": drafts_out,
        "jd_profile": {k: v for k, v in jd_profile.items() if k != "jd_status"},
        "emails_scanned": int(max_messages),
        "attachments_parsed": len(rows),
    }
    hr_shortlist_save_batch(
        batch_id=batch_id,
        user_name=user_name,
        user_role=user_role,
        criteria=job_criteria,
        interview_when=interview_when,
        company=company,
        payload=payload,
    )
    log_agent(
        "HR Gmail Shortlist",
        "gmail_rank_draft",
        f"batch={batch_id} scanned={max_messages}",
        f"top={len(drafts_out)}",
        True,
        0,
    )
    return {
        "ok": True,
        "batch_id": batch_id,
        "role_title": role_title,
        "drafts": drafts_out,
        "attachments_parsed": len(rows),
    }


def approve_and_send_shortlist_batch(batch_id: str) -> dict[str, Any]:
    """Send all sendable drafts in the batch; never sends without valid recipient."""
    row = hr_shortlist_get_batch(batch_id)
    if not row:
        return {"ok": False, "error": "Batch not found."}
    if row.get("status") == "sent":
        return {"ok": False, "error": "This batch was already sent."}

    from tools.gmail_send import send_email
    from config import GMAIL_EMAIL
    from database.sqlite_db import log_email

    payload = row.get("payload") or {}
    drafts = payload.get("top") or []
    results: list[dict[str, Any]] = []
    sent = 0
    for d in drafts:
        to = (d.get("recipient") or "").strip()
        if not to or "@" not in to:
            results.append({"recipient": to, "ok": False, "error": "missing recipient"})
            continue
        st = {
            "recipient": to,
            "subject": d.get("subject") or "Interview invitation",
            "body": d.get("body") or "",
        }
        send_email(st)
        status = str(st.get("send_status", ""))
        ok = status.startswith("✅")
        if ok:
            sent += 1
            log_email("sent", GMAIL_EMAIL, to, st["subject"], st["body"][:1500])
        results.append({"recipient": to, "ok": ok, "status": status})

    hr_shortlist_update_status(batch_id, "sent" if sent else "pending_send")
    log_agent("HR Gmail Shortlist", "gmail_approve_send", batch_id, str(results)[:2000], sent > 0, 0)
    return {"ok": sent > 0, "emails_sent": sent, "total": len(drafts), "details": results}
