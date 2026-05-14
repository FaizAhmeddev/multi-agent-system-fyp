"""Shortlisting Agent — threshold, dedupe by email, stable ranking."""

from __future__ import annotations

from typing import Any


def build_shortlist(
    matches: list[dict[str, Any]],
    parsed_cvs: list[dict[str, Any]],
    top_n: int = 5,
    min_score: int = 55,
) -> dict[str, Any]:
    """Join match scores with parsed CV emails; dedupe; cap top_n."""
    top_n = max(1, min(int(top_n or 5), 50))
    min_score = max(0, min(int(min_score or 0), 100))

    by_name = {p.get("name", "").strip().lower(): p for p in parsed_cvs}

    rows: list[dict[str, Any]] = []
    for m in matches or []:
        name = (m.get("candidate") or "").strip()
        key = name.lower()
        prof = by_name.get(key) or {}
        # Prefer email carried on the match row (same worker as parsed CV).
        raw_email = (m.get("email") or prof.get("email") or "").strip()
        rows.append({
            "name": name or prof.get("name") or "Candidate",
            "email": raw_email,
            "match_score": int(m.get("match_score") or 0),
            "strengths": m.get("strengths") or [],
            "weaknesses": m.get("weaknesses") or [],
            "dimensions": m.get("dimensions") or {},
            "rationale": m.get("rationale") or "",
        })

    rows.sort(key=lambda r: r["match_score"], reverse=True)

    seen_email: set[str] = set()
    seen_name: set[str] = set()
    shortlisted: list[dict[str, Any]] = []
    for r in rows:
        if r["match_score"] < min_score:
            continue
        ek = (r["email"] or "").strip().lower()
        nk = r["name"].strip().lower()
        if ek and ek in seen_email:
            continue
        if nk in seen_name:
            continue
        if ek:
            seen_email.add(ek)
        seen_name.add(nk)
        shortlisted.append(r)
        if len(shortlisted) >= top_n:
            break

    return {
        "shortlisted_candidates": shortlisted,
        "threshold": min_score,
        "top_n": top_n,
        "total_evaluated": len(rows),
    }
