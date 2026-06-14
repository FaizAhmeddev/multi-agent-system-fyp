"""Regression routing test for Assistant tab orchestrator (agents_used only)."""

from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from config import get_role_orchestrator_allowlist, load_local_env
from Orchestrator.orchestrator_brain import Orchestrator
from utils.logging_config import configure_logging

load_local_env()
configure_logging()

SAMPLE_EXPENSES = """Analyze these expenses and highlight the top 5 costs:
Travel - 4500
Software licenses - 12000
Office supplies - 800
Consulting - 22000
Training - 3500"""

PROMPTS = [
    (
        "My laptop won't connect to WiFi, create an IT ticket",
        {"it_support"},
    ),
    (
        "Generate interview questions for a senior Python developer",
        {"hr"},
    ),
    (
        SAMPLE_EXPENSES,
        {"finance"},
    ),
    (
        "Search Google Drive for the onboarding policy PDF",
        {"documents"},
    ),
    (
        "Fetch the latest 10 candidate emails",
        {"hr_gmail"},
    ),
    (
        "New employee Ali Khan joining Monday as Software Engineer — complete full onboarding",
        {"hr", "email", "it_support", "finance", "documents"},
    ),
    (
        "Send a welcome email to ali@example.com — start Monday as Software Engineer",
        {"email"},
    ),
    (
        "What can you do?",
        {"general"},
    ),
]

ROLES = ["Admin", "Assistant"]


def _mock_invoke(self, agent_type, *args, **kwargs):
    return f"[mock:{agent_type}]"


def main() -> int:
    Orchestrator._invoke_agent = _mock_invoke  # type: ignore[method-assign]
    orch = Orchestrator()
    failures = 0

    for role in ROLES:
        allow = get_role_orchestrator_allowlist(role)
        print(f"\n=== Role: {role} (allowlist={allow}) ===")
        for prompt, expected in PROMPTS:
            result = orch.route(
                prompt,
                user_name="TestUser",
                use_llm_intent=True,
                allowed_agents=allow,
                user_role=role,
            )
            used = set(result.get("agents_used") or [])
            ok = expected.issubset(used) or (expected == {"general"} and used == {"general"})
            if not ok and role == "Admin":
                ok = bool(used & expected) or (not used and not expected)
            status = "OK" if ok else "FAIL"
            if status == "FAIL":
                failures += 1
            print(f"  [{status}] expected>={sorted(expected)} got={sorted(used)}")
            if status == "FAIL":
                preview = (result.get("final_answer") or "")[:120].replace("\n", " ")
                print(f"         answer: {preview}...")

    print(f"\nDone. Failures: {failures}")
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
