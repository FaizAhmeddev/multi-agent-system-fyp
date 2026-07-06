"""Regression routing test for Assistant tab orchestrator (agents_used only)."""

from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from config import get_role_orchestrator_allowlist, load_local_env
from Orchestrator.orchestrator_brain import Orchestrator
from tools.hr_email_intelligence import parse_email_search_prompt
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
        "Please complete the full onboarding process automatically.\n\nTasks to perform:\n\n"
        "1. Send a welcome email to Ahmed with joining instructions.\n"
        "2. Create an employee profile with department, designation, salary, and joining date.\n"
        "3. Generate an employment offer letter.\n"
        "4. Schedule orientation meetings for next Monday.\n"
        "5. Create an IT support ticket for laptop allocation.\n"
        "6. Generate a monthly salary breakdown and payroll entry.\n"
        "7. Store all generated documents.\n"
        "8. Prepare an onboarding summary report.\n"
        "9. Notify the admin dashboard.\n"
        "10. Log all agent activities.",
        {"hr", "email", "it_support", "finance", "documents"},
    ),
    (
        "Send a welcome email to ali@example.com — start Monday as Software Engineer",
        {"email"},
    ),
    (
        "Complete below jobs\n"
        "1. send a email for Huzaifa to welcome to join KIET\n"
        "2. create Huzaifa's joining letter in PDF\n"
        "3. create then again email that joining letter to Huzaifa\n"
        "4. also fetch 2 best python developer from last 10 emails",
        {"email", "documents", "hr_gmail"},
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
    parser_cases = [
        ("fetch last 2 emails from our mailbox", {"max_results": 2, "sender": ""}),
        ("fetch last 2 emails from my inbox", {"max_results": 2, "sender": ""}),
        ("fetch last 2 emails from ali@example.com", {"max_results": 2, "sender": "ali@example.com"}),
        ("show last 2 emails", {"max_results": 2, "sender": ""}),
        ("read the last 2 messages in gmail", {"max_results": 2, "sender": ""}),
    ]

    print("\n=== Parser regressions ===")
    for prompt, expected in parser_cases:
        spec = parse_email_search_prompt(prompt) or {}
        ok = all(spec.get(k) == v for k, v in expected.items())
        status = "OK" if ok else "FAIL"
        if status == "FAIL":
            failures += 1
        print(f"  [{status}] {prompt!r} -> max={spec.get('max_results')} sender={spec.get('sender')!r}")

    followup_prompt = (
        "Complete below jobs\n"
        "1. send a email for Huzaifa to welcome to join KIET\n"
        "2. create Huzaifa's joining letter in PDF\n"
        "3. create then again email that joining letter to Huzaifa\n"
        "4. also fetch 2 best python developer from last 10 emails"
    )

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

        inbox_prompt = "fetch last 2 emails"
        result = orch.route(
            inbox_prompt,
            user_name="TestUser",
            use_llm_intent=True,
            allowed_agents=allow,
            user_role=role,
        )
        used = set(result.get("agents_used") or [])
        ok = used == {"hr_gmail"} or (role == "Assistant" and not used)
        status = "OK" if ok else "FAIL"
        if status == "FAIL":
            failures += 1
        print(f"  [{status}] inbox prompt expected=['hr_gmail'] got={sorted(used)}")

        result = orch.route(
            "huzaifa@example.com",
            user_name="TestUser",
            use_llm_intent=True,
            allowed_agents=allow,
            user_role=role,
            conversation_history=[
                {"role": "user", "content": followup_prompt},
                {"role": "assistant", "content": "Before I can send emails to Huzaifa, please share their email address."},
            ],
        )
        used = set(result.get("agents_used") or [])
        ok = used == {"email"}
        status = "OK" if ok else "FAIL"
        if status == "FAIL":
            failures += 1
        print(f"  [{status}] email-address follow-up expected=['email'] got={sorted(used)}")

    print(f"\nDone. Failures: {failures}")
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
