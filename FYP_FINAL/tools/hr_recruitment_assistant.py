"""
HR Recruitment Assistant — ATS rules: strict skill filter, selective send, session memory.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

# Minimum match % to label "Recommended" (still shown if below, as Not Recommended)
DEFAULT_MIN_RECOMMEND_SCORE = 55

TECH_SKILL_ALIASES: dict[str, list[str]] = {
    "python": ["python", "django", "flask", "fastapi", "pandas", "numpy"],
    "javascript": ["javascript", "js", "typescript", "node", "nodejs", "node.js", "react", "vue", "angular"],
    "react": ["react", "reactjs", "react.js", "next.js", "nextjs"],
    "node": ["node", "nodejs", "node.js", "express"],
    "java": ["java", "spring", "spring boot"],
    "sql": ["sql", "mysql", "postgresql", "postgres", "sqlite", "mssql"],
    "devops": ["devops", "docker", "kubernetes", "k8s", "ci/cd", "jenkins", "terraform", "aws", "azure"],
    "data": ["data science", "data scientist", "machine learning", "ml", "tensorflow", "pytorch"],
    "data entry": ["data entry", "typing", "ms excel", "excel"],
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def extract_required_skills_from_prompt(message: str, jd_profile: dict[str, Any] | None = None) -> list[str]:
    """Derive must-match skills from user prompt + JD analysis."""
    skills: list[str] = []
    jd = jd_profile or {}
    for sk in jd.get("required_skills") or []:
        s = _norm(str(sk))
        if s and s not in skills:
            skills.append(s)
    low = (message or "").lower()
    patterns = [
        (r"\bpython\s+developers?\b", "python"),
        (r"\bselect\s+(?:only\s+)?(?:\d+|one|two|three|four|five)\s+(?:for\s+)?python\b", "python"),
        (r"\bselect\s+(?:only\s+)?(?:\d+|one|two|three|four|five)\s+python\b", "python"),
        (r"\bfor\s+python\b", "python"),
        (r"\breact\s+(?:developers?|engineers?|candidates?)\b", "react"),
        (r"\bnode\.?js\s+(?:developers?|engineers?)\b", "node"),
        (r"\bjavascript\s+(?:developers?|engineers?)\b", "javascript"),
        (r"\bjava\s+(?:developers?|engineers?)\b", "java"),
        (r"\b(?:find|email|shortlist|hire|select|pick|choose)\s+([a-z][a-z0-9.+#\s]{1,30}?)\s+(?:developers?|engineers?|candidates?)\b", None),
        (r"\bfor\s+([a-z][a-z0-9.+#\s]{2,40}?)\s+(?:developers?|role|position)\b", None),
        (r"\bselect\s+(?:only\s+)?(?:\d+|one|two|three|four|five)\s+for\s+([a-z][a-z0-9.+#]{2,24})\b", None),
    ]
    for pat, fixed in patterns:
        m = re.search(pat, low, re.I)
        if not m:
            continue
        if fixed:
            if fixed not in skills:
                skills.append(fixed)
        else:
            chunk = _norm(m.group(1))
            for token in re.split(r"[\s,/&]+", chunk):
                if len(token) >= 2 and token not in skills:
                    skills.append(token)
    for tech in (
        "python", "react", "node", "nodejs", "javascript", "typescript", "java",
        "django", "flask", "fastapi", "sql", "devops", "aws", "data entry",
    ):
        if re.search(rf"\b{re.escape(tech)}\b", low) and tech not in skills:
            skills.append(tech)
    return skills[:12]


def _cv_skill_blob(parsed: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("skills", "technologies", "certifications", "projects"):
        val = parsed.get(key)
        if isinstance(val, list):
            parts.extend(str(x) for x in val)
        elif val:
            parts.append(str(val))
    for key in ("summary", "education", "name"):
        if parsed.get(key):
            parts.append(str(parsed[key]))
    return " ".join(parts).lower()


def candidate_matches_required_skills(
    parsed: dict[str, Any],
    match: dict[str, Any],
    required_skills: list[str],
) -> bool:
    """Strict filter: when skills are specified, candidate must show evidence of at least one."""
    if not required_skills:
        return True
    blob = _cv_skill_blob(parsed)
    match_text = " ".join(
        str(x).lower()
        for x in (match.get("strengths") or []) + (match.get("rationale") or "").split()
    )
    combined = f"{blob} {match_text}"
    for skill in required_skills:
        sk = _norm(skill)
        aliases = TECH_SKILL_ALIASES.get(sk, [sk])
        if any(a in combined for a in aliases):
            return True
        if re.search(rf"\b{re.escape(sk)}\b", combined):
            return True
    dims = match.get("dimensions") or {}
    if int(dims.get("skills_overlap") or 0) >= 65:
        return True
    return False


def recommendation_label(match_score: int, min_score: int = DEFAULT_MIN_RECOMMEND_SCORE) -> str:
    return "Recommended" if int(match_score or 0) >= min_score else "Not Recommended"


def experience_level_label(parsed: dict[str, Any], jd_profile: dict[str, Any]) -> str:
    yrs = parsed.get("experience_years")
    role_level = (jd_profile or {}).get("role_level") or ""
    if yrs is not None:
        try:
            y = float(yrs)
            if y < 1:
                return "Junior / Entry"
            if y < 3:
                return "Junior"
            if y < 6:
                return "Mid-level"
            return "Senior"
        except Exception:
            pass
    if role_level:
        return str(role_level)
    return "Not specified"


def key_skills_display(parsed: dict[str, Any], match: dict[str, Any], limit: int = 6) -> list[str]:
    out: list[str] = []
    for src in (parsed.get("skills") or [], parsed.get("technologies") or [], match.get("strengths") or []):
        for item in src:
            s = str(item).strip()
            if s and s not in out:
                out.append(s)
            if len(out) >= limit:
                return out
    return out


def enrich_candidate_record(
    item: dict[str, Any],
    *,
    min_score: int = DEFAULT_MIN_RECOMMEND_SCORE,
    jd_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parsed = item.get("parsed") or {}
    match = item.get("match") or {}
    score = int(item.get("match_score") or match.get("match_score") or 0)
    name = (parsed.get("name") or item.get("candidate_name") or "Candidate").strip()
    cid = item.get("candidate_id") or str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{name}:{item.get('recipient', '')}"))
    return {
        "candidate_id": cid,
        "candidate_name": name,
        "recipient": (item.get("recipient") or "").strip(),
        "sendable": bool(item.get("sendable")),
        "match_score": score,
        "status": recommendation_label(score, min_score),
        "key_skills": key_skills_display(parsed, match),
        "experience_level": experience_level_label(parsed, jd_profile or {}),
        "strengths": list(match.get("strengths") or [])[:6],
        "weaknesses": list(match.get("weaknesses") or [])[:6],
        "dimensions": match.get("dimensions") or {},
        "rationale": match.get("rationale") or "",
        "subject": item.get("subject"),
        "body": item.get("body"),
        "source_mail_subject": item.get("source_mail_subject") or "",
        "cv_filename": item.get("cv_filename") or "",
        "hr_state": item.get("hr_state") or "pending",  # pending | shortlisted | rejected
    }


def user_explicitly_requests_email_all(message: str) -> bool:
    low = (message or "").lower()
    phrases = (
        "email all",
        "send to all",
        "send to everyone",
        "contact all",
        "email everyone",
        "send everyone",
        "mail all candidates",
        "invite all candidates",
    )
    return any(p in low for p in phrases)


def parse_selective_send_command(
    message: str,
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Resolve who may receive email from a follow-up command.
    Returns: mode (none|all_explicit|names|top_n|recommended|selected_ids), targets, top_n, clarification.
    """
    raw = (message or "").strip()
    low = raw.lower()
    result: dict[str, Any] = {
        "mode": "none",
        "names": [],
        "emails": [],
        "top_n": 0,
        "candidate_ids": [],
        "clarification": "",
    }

    if not candidates:
        result["clarification"] = "No candidates in the current shortlist. Fetch candidates first."
        return result

    if user_explicitly_requests_email_all(low):
        result["mode"] = "all_explicit"
        return result

    # Top N: "invite top 2", "email the top 3 candidates"
    tm = re.search(r"\b(?:top|first|best)\s+(\d+)\b", low)
    if tm:
        result["mode"] = "top_n"
        result["top_n"] = max(1, min(25, int(tm.group(1))))
        return result

    if any(
        x in low
        for x in (
            "recommended only",
            "all recommended",
            "recommended candidates",
            "send to recommended",
            "email recommended",
        )
    ):
        result["mode"] = "recommended"
        return result

    # Named: "send to Faiz", "email Uzair only", "invite Ahmed Khan"
    name_pool = []
    for c in candidates:
        name_pool.append((c.get("candidate_name") or "", c.get("candidate_id") or ""))

    matched_names: list[str] = []
    matched_ids: list[str] = []
    for name, cid in name_pool:
        if not name:
            continue
        parts = name.lower().split()
        first = parts[0] if parts else ""
        if first and len(first) >= 3 and re.search(rf"\b{re.escape(first)}\b", low):
            matched_names.append(name)
            if cid:
                matched_ids.append(cid)
            continue
        if len(name) >= 4 and name.lower() in low:
            matched_names.append(name)
            if cid:
                matched_ids.append(cid)

    if matched_names:
        result["mode"] = "names"
        result["names"] = matched_names
        result["candidate_ids"] = matched_ids
        return result

    # Generic send verbs without target → need clarification (never default to all)
    send_verbs = (
        "approve and send",
        "approve & send",
        "send interview",
        "send email",
        "send the email",
        "send invitation",
        "email them",
    )
    if any(v in low for v in send_verbs):
        names_list = ", ".join(f"**{c.get('candidate_name', '?')}**" for c in candidates[:8])
        result["clarification"] = (
            "Who should receive the interview email? Specify clearly, for example:\n"
            f"- **Send to [name]** (e.g. Send to Faiz)\n"
            f"- **Invite top 2** candidates\n"
            f"- **Email all recommended** candidates\n"
            f"- **Email all** / **Send to everyone** (only if you mean every shortlisted person)\n\n"
            f"Current shortlist: {names_list}"
        )
        return result

    return result


def filter_drafts_for_send(
    drafts: list[dict[str, Any]],
    send_spec: dict[str, Any],
    *,
    ui_selected_ids: list[str] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Return drafts allowed to send + error/clarification message (empty if ok)."""
    if not drafts:
        return [], "No candidates in batch."

    mode = send_spec.get("mode") or "none"
    if mode == "none":
        clar = send_spec.get("clarification") or ""
        if clar:
            return [], clar
        if ui_selected_ids:
            mode = "selected_ids"
        else:
            return [], (
                "No recipients selected. Choose candidates in the panel below or say e.g. "
                "**Send to Faiz** or **Invite top 2**."
            )

    sendable = [d for d in drafts if d.get("sendable") and d.get("hr_state") != "rejected"]

    if mode == "all_explicit":
        return sendable, ""

    if mode == "selected_ids":
        ids = set(ui_selected_ids or send_spec.get("candidate_ids") or [])
        out = [d for d in sendable if d.get("candidate_id") in ids]
        if not out:
            return [], "No sendable candidates match your selection."
        return out, ""

    if mode == "names":
        names = {_norm(n) for n in send_spec.get("names") or []}
        out = [d for d in sendable if _norm(d.get("candidate_name") or "") in names]
        if not out:
            # partial first-name match
            for d in sendable:
                fn = _norm((d.get("candidate_name") or "").split()[0] if d.get("candidate_name") else "")
                if any(fn and fn in _norm(n) for n in names):
                    out.append(d)
        if not out:
            return [], f"No sendable candidate matched: {', '.join(send_spec.get('names') or [])}"
        return out, ""

    if mode == "top_n":
        n = int(send_spec.get("top_n") or 1)
        ranked = sorted(sendable, key=lambda x: -int(x.get("match_score") or 0))
        return ranked[:n], ""

    if mode == "recommended":
        out = [d for d in sendable if d.get("status") == "Recommended"]
        if not out:
            return [], "No **Recommended** candidates with valid email addresses."
        return out, ""

    return [], send_spec.get("clarification") or "Could not determine recipients."


def format_ats_ranking(drafts: list[dict[str, Any]], *, role_title: str = "", filtered_skills: list[str] | None = None) -> str:
    """Professional ATS-style ranked list for chat/UI."""
    lines = ["### Candidate ranking", ""]
    if role_title:
        lines.append(f"**Role:** {role_title}")
    if filtered_skills:
        lines.append(f"**Required skills filter:** {', '.join(filtered_skills)}")
    lines.append("")
    if not drafts:
        lines.append("_No candidates matched your criteria._")
        return "\n".join(lines)

    for i, d in enumerate(drafts, 1):
        name = d.get("candidate_name") or "Candidate"
        score = int(d.get("match_score") or 0)
        skills = ", ".join(d.get("key_skills") or []) or "—"
        exp = d.get("experience_level") or "—"
        status = d.get("status") or recommendation_label(score)
        lines.append(f"{i}. **{name}** — **{score}%** Match")
        lines.append(f"   - **Skills:** {skills}")
        lines.append(f"   - **Experience:** {exp}")
        lines.append(f"   - **Status:** {status}")
        lines.append("")
    lines.append(
        "_No emails sent. Say **Send to [name]**, **Invite top N**, **Email all recommended**, "
        "or **Email all** only if you want everyone contacted._"
    )
    return "\n".join(lines)


def build_session_memory_from_result(result: dict[str, Any]) -> dict[str, Any]:
    """Structure stored in Streamlit session + batch payload."""
    drafts = result.get("drafts") or []
    return {
        "batch_id": result.get("batch_id"),
        "role_title": result.get("role_title", ""),
        "required_skills": result.get("required_skills") or [],
        "candidates": drafts,
        "filters_applied": result.get("filters_applied") or {},
        "last_fetch_at": result.get("batch_id"),
    }
