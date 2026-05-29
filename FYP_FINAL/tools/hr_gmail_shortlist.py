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
from tools.hr_recruitment_assistant import (
    DEFAULT_MIN_RECOMMEND_SCORE,
    build_session_memory_from_result,
    candidate_matches_required_skills,
    enrich_candidate_record,
    extract_required_skills_from_prompt,
    filter_drafts_for_send,
    format_ats_ranking,
    parse_selective_send_command,
    user_explicitly_requests_email_all,
)

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


_WORD_TO_INT: dict[str, int] = {
    "a": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

_TECH_ROLE_RE = (
    r"python|java|javascript|typescript|react|django|flask|fastapi|node\.?js|"
    r"sql|devops|aws|ml|machine\s+learning|data\s+scientist|data\s+entry"
)


def _parse_count_token(token: str | None) -> int | None:
    if not token:
        return None
    t = token.strip().lower()
    if t.isdigit():
        return int(t)
    return _WORD_TO_INT.get(t)


def _extract_top_n_from_prompt(low: str) -> int | None:
    """How many candidates to keep, e.g. select 1 python, select two for python."""
    patterns = (
        r"\bselect\s+(?:only\s+)?(?:the\s+)?(?P<n>\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+"
        rf"(?:{_TECH_ROLE_RE}|developer|engineer|candidate|people|person)s?\b",
        rf"\bselect\s+(?:only\s+)?(?P<n>\d+|one|two|three|four|five)\s+for\s+(?:{_TECH_ROLE_RE})\b",
        r"\bselect\s+(?:only\s+)?(?:the\s+)?(?:top\s*)?(?P<n>\d+|one|two|three|four|five)\s+candidates?\b",
        r"\b(?:pick|choose|take|shortlist)\s+(?:only\s+)?(?P<n>\d+|one|two|three|four|five)\s+"
        rf"(?:{_TECH_ROLE_RE}|developer|engineer|candidates?)\b",
        r"\bfetch\s+\d+\s+.*?\bselect\s+(?P<n>\d+|one|two|three|four|five)\b",
        r"\bonly\s+(?P<n>\d+|one|two|three|four|five)\s+"
        rf"(?:{_TECH_ROLE_RE})\s+(?:developer|engineer|candidate|people)?s?\b",
        r"\b(?P<n>\d+|one|two|three|four|five)\s+"
        rf"(?:{_TECH_ROLE_RE})\s+(?:developer|engineer|candidate|people)s?\b",
        r"\btop\s*(?P<n>\d+|one|two|three|four|five)\s+(?:candidates?|developers?|engineers?)\b",
        r"\bshortlist\s+(?P<n>\d+|one|two|three|four|five)\b",
        r"\b(\d+)\s+best\s+candidates?\b",
    )
    for pat in patterns:
        mm = re.search(pat, low, re.I)
        if not mm:
            continue
        tok = mm.groupdict().get("n")
        if not tok and mm.lastindex:
            tok = mm.group(1)
        n = _parse_count_token(tok)
        if n is not None:
            return max(1, min(25, n))
    return None


def extract_max_messages_from_prompt(message: str) -> int:
    """How many recent inbox messages to scan (from natural language)."""
    return _extract_max_messages_from_prompt((message or "").lower())


def _extract_max_messages_from_prompt(low: str) -> int:
    for pat in (
        r"(?:last|past|recent)\s+(\d+)\s+(?:e-?mails?|emails?|messages?)",
        r"(?:fetch|get|scan|pull|collect|retrieve)\s+(?:last\s+)?(\d+)\s+(?:e-?mails?|emails?|messages?)",
        r"(?:fetch|get|scan)\s+(\d+)\b",
        r"(\d+)\s+(?:e-?mails?|emails?|messages?)\s+(?:from|in)\s+(?:my\s+)?(?:inbox|gmail|mail)",
    ):
        mm = re.search(pat, low, re.I)
        if mm:
            return max(5, min(100, int(mm.group(1))))
    return 50


def is_inbox_list_only_request(message: str) -> bool:
    """
    True when the user wants to list/read recent mail — not run the ATS shortlist pipeline.
    e.g. "fetch the latest 10 candidate emails" (applicant mail in inbox, not "shortlist candidates").
    """
    low = (message or "").lower().strip()
    if len(low) < 8:
        return False
    if re.search(r"\b(?:select|shortlist|pick|choose|rank|screen|hire)\b", low):
        if re.search(
            r"\b(?:select|shortlist|pick|choose)\s+(?:\d+|one|two|three|four|five|top)\b",
            low,
        ):
            return False
        if re.search(rf"\b(?:shortlist|select|rank|screen)\b.{0,40}\b(?:{_TECH_ROLE_RE}|developer|engineer)\b", low):
            return False
    if re.search(
        r"\b(?:latest|last|recent)\s+\d+\s+(?:candidate\s+)?e-?mails?\b",
        low,
    ):
        return True
    if re.search(
        r"\b(?:fetch|get|show|list|read)\s+(?:the\s+)?(?:latest|last|recent)\s+\d+\s+"
        r"(?:candidate\s+)?e-?mails?\b",
        low,
    ):
        return True
    if re.search(r"\b(?:fetch|get|show|list|read)\b", low) and re.search(
        r"\b(?:e-?mails?|emails|inbox|gmail|messages?)\b", low
    ):
        if re.search(r"\b(?:cv|resume)s?\b", low) and re.search(
            r"\b(?:shortlist|select|pick|rank|screen)\b", low
        ):
            return False
        if not re.search(r"\b(?:shortlist|select|pick|choose|rank|screen)\b", low):
            return True
    return False


def prompt_has_hiring_focus(message: str) -> bool:
    """Public wrapper — True when the message is about hiring / CV screening."""
    if is_inbox_list_only_request(message):
        return False
    return _prompt_has_hiring_focus((message or "").lower())


def _prompt_has_hiring_focus(low: str) -> bool:
    if any(x in low for x in ("cv", "resume", "curriculum vitae", "applicant", "attachment")):
        return True
    if re.search(r"\bcandidates?\s+(?:for|to\s+hire|matching|with)\b", low):
        return True
    if re.search(
        r"\b(?:shortlist|screen|rank|select|hire)\b.{0,40}\bcandidates?\b",
        low,
    ):
        return True
    if re.search(
        rf"\b(?:{_TECH_ROLE_RE})\b.*\b(?:dev|developer|engineer|candidate|role|position)\b",
        low,
        re.I,
    ):
        return True
    if re.search(
        rf"\b(?:select|shortlist|find|pick|choose|hire)\s+(?:only\s+)?(?:\d+|one|two|three|four|five)\s+"
        rf"(?:for\s+)?(?:{_TECH_ROLE_RE})\b",
        low,
        re.I,
    ):
        return True
    if re.search(rf"\bfor\s+(?:{_TECH_ROLE_RE})\b", low, re.I):
        return True
    if re.search(rf"\b(?:{_TECH_ROLE_RE})\s+(?:dev|developer|engineer)s?\b", low, re.I):
        return True
    if re.search(
        rf"\bfind\s+(?:{_TECH_ROLE_RE})\s+developers?\b",
        low,
        re.I,
    ):
        return True
    return False


def parse_gmail_shortlist_prompt(message: str) -> dict[str, Any] | None:
    """
    Detect natural-language requests like:
    - fetch last 20 emails and select two for python
    - select 1 python developer
    - fetch last 40 emails CVs and select 5 candidates for python
    """
    m = (message or "").strip()
    if len(m) < 12:
        return None
    low = m.lower()

    if is_inbox_list_only_request(m):
        return None

    has_inbox = any(
        x in low
        for x in ("email", "e-mail", "emails", "inbox", "gmail", "mail message", "messages")
    )
    has_fetch = any(
        x in low
        for x in ("fetch", "scan", "pull", "retrieve", "collect", "read last")
    ) or bool(
        re.search(
            r"\b(?:fetch|get|scan|pull|find)\s+(?:the\s+)?(?:last|latest|recent|\d+)",
            low,
        )
    )
    has_select = bool(re.search(r"\b(?:select|shortlist|pick|choose)\b", low))
    has_hiring = _prompt_has_hiring_focus(low)

    is_fetch_flow = has_hiring and (
        (has_fetch and (has_inbox or re.search(r"\bfetch\s+\d+", low)))
        or (has_fetch and has_select)
        or (has_select and has_hiring)
        or (has_fetch and has_inbox and has_hiring)
    )
    if not is_fetch_flow:
        return None

    max_messages = _extract_max_messages_from_prompt(low)
    top_n = _extract_top_n_from_prompt(low)
    if top_n is None:
        top_n = 5

    interview_when = "To be scheduled — confirm by reply."
    im = re.search(
        r"(?i)(interview\s+(?:on\s+|at\s+)?[^.;]{5,140}|"
        r"(?:tomorrow|today|monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
        r"[^.;\n]{0,100}(?:\d{1,2}(?::\d{2})?\s*(?:am|pm)?)?)",
        m,
    )
    if im:
        interview_when = im.group(1).strip()[:220]
    tm = re.search(
        r"(?i)\b(?:tomorrow|today)\b[^.;\n]{0,80}(?:\d{1,2}(?::\d{2})?\s*(?:am|pm)?)",
        m,
    )
    if tm and not im:
        interview_when = tm.group(0).strip()[:220]

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
        "user_message": m,
    }


def _infer_job_criteria_from_prompt(message: str) -> str:
    tech_dev = re.search(
        rf"(?i)\b({_TECH_ROLE_RE})\s+(?:dev|developer|engineer)s?\b",
        message,
    )
    if tech_dev:
        return f"{tech_dev.group(1)} developer. Full request: {message[:700]}"
    for pat in (
        rf"\bselect\s+(?:only\s+)?(?:\d+|one|two|three|four|five)\s+for\s+({_TECH_ROLE_RE}(?:\s+developer)?)",
        rf"\bfor\s+({_TECH_ROLE_RE})(?:\s+developer|\s+engineer|\s+candidate|\s+role|\s+position)?\b",
        r"(?i)find\s+((?:python|java|javascript|react|node)\s+developers?)",
    ):
        m = re.search(pat, message, re.I)
        if m:
            chunk = m.group(1).strip()
            if len(chunk) >= 3:
                return f"{chunk} role. Context: {message[:500]}"
    m = re.search(
        r"(?i)for\s+((?:python|java|javascript|react|node|django|flask)[^.;]{2,80}?)"
        r"(?:\s+and\s+email|\s*,\s*email|\s+email\s+them|\.|$)",
        message,
    )
    if m:
        return m.group(1).strip()[:1500]
    tech = re.search(
        rf"(?i)\b({_TECH_ROLE_RE})\b[^.;]{{0,120}}",
        message,
    )
    if tech:
        return f"Hiring focus: {tech.group(0).strip()}. Full request: {message[:700]}"
    return (message or "").strip()[:1500]


def format_hr_gmail_orchestrator_reply(res: dict[str, Any]) -> str:
    """Internal thread text (batch marker for follow-ups). UI uses assistant_display cards."""
    if not res.get("ok"):
        return res.get("error", "Failed.")

    drafts = res.get("drafts") or []
    bid = res.get("batch_id") or ""
    fa = res.get("filters_applied") or {}
    skills = ", ".join(fa.get("required_skills") or []) or "—"
    summary = (
        f"Shortlisted {len(drafts)} candidate(s) for {res.get('role_title', 'role')}. "
        f"Scanned {res.get('emails_scanned', 0)} emails, {res.get('attachments_parsed', 0)} CVs. "
        f"Skill filter: {skills}."
    )
    marker = f"\n\n{HR_GMAIL_BATCH_MARKER_PREFIX}{bid}{HR_GMAIL_BATCH_MARKER_SUFFIX}"
    return summary + marker


def build_shortlist_spec_from_message(message: str) -> dict[str, Any] | None:
    """
    Relaxed shortlist spec when the user clearly wants recruitment from Gmail
    but phrasing does not match the strict ``parse_gmail_shortlist_prompt`` rules.
    """
    m = (message or "").strip()
    if len(m) < 12:
        return None
    low = m.lower()
    if is_inbox_list_only_request(m):
        return None
    if not _prompt_has_hiring_focus(low):
        return None
    has_action = bool(
        re.search(
            r"\b(?:select|shortlist|pick|choose|rank|screen|hire|find|fetch|scan|pull)\b",
            low,
        )
    )
    if not has_action:
        return None

    max_messages = _extract_max_messages_from_prompt(low)
    top_n = _extract_top_n_from_prompt(low)
    if top_n is None:
        top_n = 5

    interview_when = "To be scheduled — confirm by reply."
    im = re.search(
        r"(?i)(interview\s+(?:on\s+|at\s+)?[^.;]{5,140}|"
        r"(?:tomorrow|today|monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
        r"[^.;\n]{0,100}(?:\d{1,2}(?::\d{2})?\s*(?:am|pm)?)?)",
        m,
    )
    if im:
        interview_when = im.group(1).strip()[:220]

    company = "Our Company"
    cm = re.search(r"(?i)company\s*[:\-]\s*([^.;,\n]{2,80})", m)
    if cm:
        company = cm.group(1).strip()[:120]

    return {
        "max_messages": max_messages,
        "top_n": top_n,
        "job_criteria": _infer_job_criteria_from_prompt(m),
        "interview_when": interview_when,
        "company": company,
        "user_message": m,
    }


def run_gmail_shortlist_from_user_prompt(
    *,
    user_message: str,
    user_name: str,
    user_role: str,
) -> dict[str, Any]:
    spec = parse_gmail_shortlist_prompt(user_message) or build_shortlist_spec_from_message(user_message)
    if not spec:
        return {
            "ok": False,
            "error": (
                "I could not tell which role or CV action you want. "
                "Try: “Fetch the last 20 emails and shortlist 2 Python developers” or "
                "“How many Python CVs are in the last 30 emails?”"
            ),
        }
    return run_gmail_shortlist_pipeline(
        job_criteria=spec["job_criteria"],
        interview_when=spec["interview_when"],
        company=spec["company"],
        user_name=user_name,
        user_role=user_role,
        max_messages=int(spec["max_messages"]),
        top_n=int(spec["top_n"]),
        user_prompt=spec.get("user_message") or user_message,
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
    Chat opt-in to SMTP-send — includes selective targets (Send to Faiz, top 2, etc.).
    """
    if parse_gmail_shortlist_prompt(message):
        return False
    low = (message or "").lower().strip()
    if len(low) < 8:
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
        "send to all",
        "email all",
        "send to everyone",
        "send invitations",
        "send invitation",
        "top 1",
        "top 2",
        "top 3",
        "top 4",
        "top 5",
        "recommended candidates",
        "recommended only",
    )
    if any(p in low for p in phrases):
        return True
    if re.search(r"\bsend\s+to\s+(?:all|everyone|recommended|top\s+\d+)\b", low):
        return True
    if re.search(r"\b(?:email|invite|mail)\s+(?:all|them|him|her|top\s+\d+)\b", low):
        return True
    if re.search(r"\b(?:send|email|invite)\s+(?:to\s+)?[a-z]{3,}", low):
        return True
    return False


def user_requests_hr_recruitment_follow_up(message: str) -> bool:
    """Follow-up on a prior shortlist without re-fetching inbox."""
    low = (message or "").lower().strip()
    if len(low) < 6:
        return False
    if parse_gmail_shortlist_prompt(message):
        return False
    cues = (
        "send to",
        "invite ",
        "approve",
        "top 1",
        "top 2",
        "top 3",
        "top 4",
        "top 5",
        "recommended",
        "email all",
        "send to all",
        "send to everyone",
        "reject ",
        "decline ",
    )
    if any(c in low for c in cues):
        return True
    if re.search(r"\b(?:send|email|invite)\s+(?:to\s+)?[a-z]{3,}", low):
        return True
    return False


def resolve_hr_gmail_batch_id_for_send(
    user_message: str,
    conversation_history: list[dict[str, str]] | None,
    *,
    require_send_phrase: bool = True,
) -> str | None:
    """
    Resolve batch UUID from the message or the most recent assistant reply in this thread.
    """
    if require_send_phrase and not user_requests_hr_gmail_approve_send(user_message):
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
    user_prompt: str = "",
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

    skill_source = f"{job_criteria}\n{user_prompt or ''}".strip()
    jd_profile = analyze_job_description(job_criteria, role_title_hint="")
    role_title = (jd_profile.get("role_title") or "Open role").strip() or "Open role"
    required_skills = extract_required_skills_from_prompt(skill_source, jd_profile)
    min_score = DEFAULT_MIN_RECOMMEND_SCORE

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

    skill_filtered: list[dict[str, Any]] = []
    for item in scored:
        parsed = item.get("parsed") or {}
        match = item.get("match") or {}
        if int(item.get("match_score") or 0) < min_score:
            continue
        if not candidate_matches_required_skills(parsed, match, required_skills):
            continue
        skill_filtered.append(item)

    tn = max(1, min(25, int(top_n)))
    top = skill_filtered[:tn]

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
        raw = {
            "parsed": parsed,
            "match": match,
            "candidate_name": name,
            "recipient": rec,
            "sendable": sendable,
            "match_score": int(item.get("match_score") or 0),
            "subject": dr.get("subject"),
            "body": dr.get("body"),
            "source_mail_subject": item.get("subject_mail") or "",
            "cv_filename": item.get("filename") or "",
        }
        drafts_out.append(enrich_candidate_record(raw, min_score=min_score, jd_profile=jd_profile))

    batch_id = str(uuid.uuid4())
    payload = {
        "top": drafts_out,
        "jd_profile": {k: v for k, v in jd_profile.items() if k != "jd_status"},
        "emails_scanned": int(max_messages),
        "attachments_parsed": len(rows),
        "required_skills": required_skills,
        "session_memory": build_session_memory_from_result({
            "batch_id": batch_id,
            "role_title": role_title,
            "drafts": drafts_out,
            "required_skills": required_skills,
            "filters_applied": {
                "required_skills": required_skills,
                "min_score": min_score,
                "matched_after_filter": len(skill_filtered),
                "total_scored": len(scored),
            },
        }),
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
        "emails_scanned": int(max_messages),
        "required_skills": required_skills,
        "filters_applied": payload.get("session_memory", {}).get("filters_applied") or {},
        "session_memory": payload.get("session_memory"),
    }


def approve_and_send_shortlist_batch(
    batch_id: str,
    *,
    user_message: str = "",
    ui_selected_ids: list[str] | None = None,
) -> dict[str, Any]:
    """
    Send only explicitly targeted candidates. Never emails everyone unless user says email all / send to everyone.
    """
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
    send_spec = parse_selective_send_command(user_message, drafts)
    if user_explicitly_requests_email_all(user_message):
        send_spec["mode"] = "all_explicit"

    to_send, err = filter_drafts_for_send(drafts, send_spec, ui_selected_ids=ui_selected_ids)
    if err:
        return {"ok": False, "error": err, "needs_clarification": True, "candidates": drafts}

    if not to_send:
        return {
            "ok": False,
            "error": "No recipients to send. Select candidates or specify who to email.",
            "needs_clarification": True,
        }

    results: list[dict[str, Any]] = []
    sent = 0
    for d in to_send:
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
    return {
        "ok": sent > 0,
        "emails_sent": sent,
        "total": len(to_send),
        "total_in_batch": len(drafts),
        "details": results,
        "recipients": [d.get("candidate_name") for d in to_send],
    }


def handle_hr_recruitment_follow_up(
    *,
    user_message: str,
    conversation_history: list[dict[str, str]] | None,
    user_name: str,
    user_role: str,
) -> dict[str, Any] | None:
    """
    Process follow-up send/shortlist commands against the last batch in thread.
    Returns orchestrator-style dict or None if not a follow-up.
    """
    if not user_requests_hr_recruitment_follow_up(user_message):
        return None

    bid = resolve_hr_gmail_batch_id_for_send(
        user_message, conversation_history, require_send_phrase=False
    )
    if not bid and conversation_history:
        for entry in reversed(conversation_history or []):
            if (entry.get("role") or "").lower() in ("assistant", "agent"):
                bid = extract_hr_gmail_batch_id(entry.get("content") or "")
                if bid:
                    break

    if not bid:
        return {
            "ok": False,
            "final_answer": (
                "**HR Recruitment Assistant**\n\n"
                "No shortlist batch found in this thread. Run a fetch first, e.g. "
                "*Fetch last 20 emails and find Python developers*."
            ),
            "agents_used": ["hr_gmail"],
        }

    row = hr_shortlist_get_batch(bid)
    if not row:
        return {"ok": False, "final_answer": "Batch not found.", "agents_used": ["hr_gmail"]}

    drafts = (row.get("payload") or {}).get("top") or []
    low = (user_message or "").lower()

    if any(x in low for x in ("reject ", "decline ", "not recommended")):
        for d in drafts:
            name = (d.get("candidate_name") or "").lower()
            if name and name.split()[0] in low:
                d["hr_state"] = "rejected"
        return {
            "ok": True,
            "final_answer": f"Marked matching candidate(s) as **rejected** in batch `{bid}`. They will not be emailed.",
            "agents_used": ["hr_gmail"],
            "hr_gmail_batch_id": bid,
        }

    if "shortlist" in low and not user_requests_hr_gmail_approve_send(user_message):
        return {
            "ok": True,
            "final_answer": format_ats_ranking(drafts, role_title=row.get("criteria", "")[:80]),
            "agents_used": ["hr_gmail"],
            "hr_gmail_batch_id": bid,
        }

    if user_requests_hr_gmail_approve_send(user_message) or any(
        v in low for v in ("send to", "email ", "invite ", "mail ")
    ):
        sr = approve_and_send_shortlist_batch(bid, user_message=user_message)
        if sr.get("needs_clarification"):
            return {
                "ok": False,
                "final_answer": f"**HR Recruitment Assistant**\n\n{sr.get('error', '')}",
                "agents_used": ["hr_gmail"],
                "hr_gmail_batch_id": bid,
            }
        body = format_hr_gmail_approve_send_reply(sr)
        out = {
            "ok": bool(sr.get("ok")),
            "final_answer": body,
            "agents_used": ["hr_gmail"],
            "hr_gmail_batch_id": None if sr.get("ok") else bid,
        }
        if sr.get("ok"):
            out["hr_gmail_pending_cleared"] = True
        return out

    return None
