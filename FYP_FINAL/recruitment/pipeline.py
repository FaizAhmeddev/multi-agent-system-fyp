"""
Recruitment Orchestrator — coordinates specialized agents with parallelism,
persistent workflow state, and human-in-the-loop before any email send.
"""

from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from recruitment.agents.cv_parsing_agent import parse_cv_structured
from recruitment.agents.jd_analysis_agent import analyze_job_description
from recruitment.agents.matching_agent import match_candidate_to_jd
from recruitment.agents.shortlisting_agent import build_shortlist
from recruitment.agents.email_drafting_agent import draft_interview_invitation
from recruitment.agents.email_sending_agent import send_drafts_with_retries
from database.sqlite_db import (
    recruitment_save_workflow,
    recruitment_get_workflow,
    recruitment_log_audit,
    log_candidate,
)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _shrink_for_db(state: dict[str, Any]) -> dict[str, Any]:
    """Reduce large raw blobs in persisted snapshot."""
    import copy

    snap = copy.deepcopy(state)
    for p in snap.get("parsed_cvs") or []:
        if isinstance(p, dict) and "raw_text" in p:
            t = p.get("raw_text") or ""
            p["raw_text"] = t[:2500] + ("..." if len(t) > 2500 else "")
    return snap


def run_recruitment_pipeline(
    *,
    job_description: str,
    cvs: list[dict[str, Any]],
    user_name: str = "Recruiter",
    company: str = "Our Company",
    role_title_hint: str = "",
    interview_when: str = "To be scheduled",
    meeting_details: str = "",
    top_n: int = 5,
    min_match_score: int = 55,
    max_workers: int = 6,
) -> dict[str, Any]:
    """
    Execute full recruitment chain up to email drafts (and persist workflow as ``pending_approval``).

    Actual Gmail delivery happens either from the **Recruitment AI** tab (Approve send) or from the
    **Assistant** when the user explicitly asks to send (handled in ``Orchestrator._run_recruitment_orchestration``).

    ``cvs`` items: ``{{"name": str, "content": str, "file_name"?: str}}``
    """
    wf_id = str(uuid.uuid4())
    t0 = _now_ms()
    errors: list[str] = []

    def audit(step: str, agent: str, ok: bool, ms: int, detail: dict | None = None):
        recruitment_log_audit(wf_id, step, agent, ok, ms, detail)

    if not (job_description or "").strip():
        audit("validate", "Orchestrator", False, 0, {"reason": "empty_jd"})
        return {"ok": False, "error": "Job description is required.", "workflow_id": wf_id}

    if not cvs:
        audit("validate", "Orchestrator", False, 0, {"reason": "no_cvs"})
        return {"ok": False, "error": "At least one CV is required.", "workflow_id": wf_id}

    # --- 1) CV parsing + JD analysis in parallel (independent workloads) ---
    s1 = _now_ms()

    def _parse_one(cv: dict[str, Any]) -> dict[str, Any]:
        name_hint = cv.get("name") or "Candidate"
        raw = cv.get("content") or ""
        fn = cv.get("file_name") or cv.get("name") or ""
        parsed = parse_cv_structured(raw, filename=fn, name_hint=name_hint)
        parsed["raw_text"] = raw[:4000]
        return parsed

    def _analyze_jd_timed() -> tuple[dict[str, Any], int]:
        t_jd = _now_ms()
        prof = analyze_job_description(job_description, role_title_hint=role_title_hint)
        return prof, _now_ms() - t_jd

    parsed_cvs: list[dict[str, Any]] = []
    parse_errors: list[str] = []
    phase_workers = max(2, min(max_workers + 1, len(cvs) + 1))
    with ThreadPoolExecutor(max_workers=phase_workers) as ex:
        jd_fut = ex.submit(_analyze_jd_timed)
        parse_futs = [ex.submit(_parse_one, cv) for cv in cvs]
        for fut in as_completed(parse_futs):
            try:
                parsed_cvs.append(fut.result())
            except Exception as e:
                err = f"parse:{e}"
                parse_errors.append(err)
                errors.append(err)
        try:
            jd_profile, jd_ms = jd_fut.result()
        except Exception as e:
            err = f"jd:{e}"
            errors.append(err)
            jd_profile = {"jd_status": "error", "role_title": "", "error": str(e)}
            jd_ms = 0
    parsed_cvs.sort(key=lambda p: (p.get("name") or "").lower())
    audit(
        "cv_parsing",
        "CVParsingAgent",
        len(parse_errors) == 0,
        _now_ms() - s1,
        {"count": len(parsed_cvs), "parse_errors": len(parse_errors)},
    )
    audit(
        "jd_analysis",
        "JDAnalysisAgent",
        jd_profile.get("jd_status") == "ok",
        jd_ms,
        {"role": jd_profile.get("role_title")},
    )

    role_title = role_title_hint.strip() or jd_profile.get("role_title") or "Open Role"

    # --- 3) Matching (parallel per candidate) ---
    s3 = _now_ms()
    matches: list[dict[str, Any]] = []

    def _match_one(pcv: dict[str, Any]) -> dict[str, Any]:
        # Always attach email from the same parsed CV as this match (LLM candidate
        # strings may not match dict keys in shortlisting, which would drop email).
        m = match_candidate_to_jd(pcv, jd_profile)
        m["email"] = (pcv.get("email") or "").strip()
        if not (m.get("candidate") or "").strip():
            m["candidate"] = (pcv.get("name") or "Candidate").strip()
        return m

    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(parsed_cvs)))) as ex:
        futs = [ex.submit(_match_one, pcv) for pcv in parsed_cvs]
        for fut in as_completed(futs):
            try:
                matches.append(fut.result())
            except Exception as e:
                errors.append(f"match:{e}")
    audit("matching", "CandidateMatchingAgent", True, _now_ms() - s3, {"matches": len(matches)})

    # --- 4) Shortlist ---
    s4 = _now_ms()
    shortlist_result = build_shortlist(matches, parsed_cvs, top_n=top_n, min_score=min_match_score)
    audit("shortlisting", "ShortlistingAgent", True, _now_ms() - s4, {"shortlist": len(shortlist_result.get("shortlisted_candidates") or [])})

    shortlisted = shortlist_result.get("shortlisted_candidates") or []

    # --- 5) Email drafts (parallel) ---
    s5 = _now_ms()
    email_drafts: list[dict[str, Any]] = []

    def _draft_one(row: dict[str, Any]) -> dict[str, Any]:
        name = row.get("name") or "Candidate"
        strengths = row.get("strengths") or []
        d = draft_interview_invitation(
            candidate_name=name,
            role_title=role_title,
            company=company,
            interview_when=interview_when,
            meeting_details=meeting_details,
            strengths_hint=strengths,
        )
        return {
            "recipient": (row.get("email") or "").strip(),
            "candidate_name": name,
            "subject": d.get("subject"),
            "body": d.get("body"),
            "match_score": row.get("match_score"),
            "sendable": bool((row.get("email") or "").strip()),
        }

    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, max(1, len(shortlisted))))) as ex:
        futs = [ex.submit(_draft_one, row) for row in shortlisted]
        for fut in as_completed(futs):
            try:
                email_drafts.append(fut.result())
            except Exception as e:
                errors.append(f"draft:{e}")
    email_drafts.sort(key=lambda x: -(x.get("match_score") or 0))
    audit("email_drafting", "EmailDraftingAgent", True, _now_ms() - s5, {"drafts": len(email_drafts)})

    sendable = [d for d in email_drafts if d.get("sendable")]
    missing = [d["candidate_name"] for d in email_drafts if not d.get("sendable")]

    approval_message = (
        f"{len(shortlisted)} candidate(s) shortlisted. "
        f"{len(sendable)} draft(s) have a valid email and can be sent after approval."
    )
    if missing:
        approval_message += f" Missing email (cannot auto-send): {', '.join(missing)}."

    state: dict[str, Any] = {
        "workflow_id": wf_id,
        "user_name": user_name,
        "company": company,
        "role_title": role_title,
        "interview_when": interview_when,
        "meeting_details": meeting_details,
        "jd_profile": jd_profile,
        "parsed_cvs": parsed_cvs,
        "matches": matches,
        "shortlist": shortlist_result,
        "email_drafts": email_drafts,
        "errors": errors,
        "approval_message": approval_message,
        "human_prompt": (
            f"{approval_message} "
            f"Interview proposal: **{interview_when}**. "
            "Would you like to send the interview invitation emails now?"
        ),
    }

    saved = recruitment_save_workflow(
        workflow_id=wf_id,
        user_name=user_name,
        status="pending_approval",
        role_title=role_title,
        company=company,
        interview_when=interview_when,
        state=_shrink_for_db(state),
    )
    if not saved:
        errors.append("persist:recruitment_save_workflow_failed")

    for row in shortlisted:
        try:
            log_candidate(
                name=row.get("name") or "Candidate",
                job_title=role_title,
                score=int(row.get("match_score") or 0),
                recommendation="Shortlisted (orchestrated pipeline)",
                strengths=list(row.get("strengths") or []),
                weaknesses=list(row.get("weaknesses") or []),
                summary=(row.get("rationale") or "")[:1200],
                cv_filename="recruitment_pipeline",
            )
        except Exception:
            pass

    audit("persist", "Orchestrator", saved, _now_ms() - t0, {"workflow_id": wf_id, "saved": saved})

    return {
        "ok": True,
        "workflow_id": wf_id,
        "workflow_persisted": saved,
        "status": "pending_approval",
        "role_title": role_title,
        "jd_profile": jd_profile,
        "shortlist": shortlist_result,
        "email_drafts": email_drafts,
        "approval_message": approval_message,
        "human_prompt": state["human_prompt"],
        "errors": errors,
        "elapsed_ms": _now_ms() - t0,
    }


def _evaluate_send_out(workflow_id: str | None, send_out: dict[str, Any]) -> dict[str, Any]:
    """Map send_drafts_with_retries output to a consistent API result (no DB side effects)."""
    sent_ok = int(send_out.get("emails_sent") or 0)
    total = int(send_out.get("total") or 0)
    all_sent = total > 0 and sent_ok == total
    base: dict[str, Any] = {"send_results": send_out}
    if workflow_id:
        base["workflow_id"] = workflow_id
    if total == 0:
        return {**base, "ok": False, "error": "No messages to send."}
    if sent_ok == 0:
        detail = ""
        details = send_out.get("details") or []
        if details and isinstance(details[0], dict):
            detail = (details[0].get("detail") or "")[:2000]
        msg = (
            "No emails were delivered. Use a Gmail **App Password** (Google Account → Security → 2-Step Verification → "
            "App passwords) for the mailbox in GMAIL_EMAIL, or set GMAIL_EMAIL / GMAIL_APP_PASSWORD in the environment. "
            "Some networks block port 465; this build also tries 587 STARTTLS."
        )
        if detail:
            msg += f" SMTP detail: {detail}"
        return {**base, "ok": False, "error": msg}
    if not all_sent:
        return {
            **base,
            "ok": True,
            "partial": True,
            "error": f"Only {sent_ok}/{total} emails succeeded; see send_results.",
        }
    return {**base, "ok": True}


def send_recruitment_email_drafts(email_drafts: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Send interview drafts in the same shape as ``run_recruitment_pipeline`` output.
    Does not read or update the recruitment workflow table — for DB-miss / session-only sends.
    """
    to_send = [
        {"recipient": (d.get("recipient") or "").strip(), "subject": d.get("subject"), "body": d.get("body")}
        for d in email_drafts
        if (d.get("recipient") or "").strip()
    ]
    if not to_send:
        return {
            "ok": False,
            "error": "No drafts with a recipient email address (CVs must include an email the parser can read).",
            "send_results": {"status": "failed", "emails_sent": 0, "total": 0, "details": []},
        }
    send_out = send_drafts_with_retries(to_send)
    return _evaluate_send_out(None, send_out)


def approve_and_send_workflow(workflow_id: str) -> dict[str, Any]:
    """Send emails only after explicit approval (loads persisted drafts)."""
    row = recruitment_get_workflow(workflow_id)
    if not row:
        return {"ok": False, "error": "Workflow not found."}
    if row["status"] not in ("pending_approval", "approved_sending"):
        return {"ok": False, "error": f"Workflow status is '{row['status']}', cannot send."}

    state = row["state"] or {}
    drafts_in = state.get("email_drafts") or []
    to_send = [
        {"recipient": d["recipient"], "subject": d.get("subject"), "body": d.get("body")}
        for d in drafts_in
        if (d.get("recipient") or "").strip()
    ]
    if not to_send:
        recruitment_save_workflow(
            workflow_id=workflow_id,
            user_name=row.get("user_name") or "",
            status="failed",
            role_title=row.get("role_title") or "",
            company=row.get("company") or "",
            interview_when=row.get("interview_when") or "",
            state=state,
            error_message="No sendable drafts (missing recipient emails).",
        )
        return {"ok": False, "error": "No drafts with valid recipient email addresses."}

    recruitment_save_workflow(
        workflow_id=workflow_id,
        user_name=row.get("user_name") or "",
        status="approved_sending",
        role_title=row.get("role_title") or "",
        company=row.get("company") or "",
        interview_when=row.get("interview_when") or "",
        state=state,
    )
    recruitment_log_audit(workflow_id, "send_start", "EmailSendingAgent", True, 0, {"count": len(to_send)})

    send_out = send_drafts_with_retries(to_send)
    final_status = "completed" if send_out.get("emails_sent") == send_out.get("total") else "completed_with_errors"

    recruitment_save_workflow(
        workflow_id=workflow_id,
        user_name=row.get("user_name") or "",
        status=final_status,
        role_title=row.get("role_title") or "",
        company=row.get("company") or "",
        interview_when=row.get("interview_when") or "",
        state=state,
        send_results=send_out,
        error_message="" if final_status == "completed" else "Some sends failed; see send_results.",
    )
    sent_ok = int(send_out.get("emails_sent") or 0)
    total = int(send_out.get("total") or 0)
    all_sent = total > 0 and sent_ok == total
    recruitment_log_audit(
        workflow_id,
        "send_done",
        "EmailSendingAgent",
        all_sent,
        0,
        {"emails_sent": send_out.get("emails_sent"), "total": send_out.get("total")},
    )

    return _evaluate_send_out(workflow_id, send_out)
