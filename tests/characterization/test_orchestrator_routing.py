"""Characterization: deterministic (keyword) routing in Orchestrator/orchestrator_brain.py.

The LLM router (detect_intent_llm / plan_orchestrator_request) is NOT covered here:
it needs a live model. These tests pin the keyword fallback, which is what runs when
"Use LLM for intent routing" is off or the LLM is unavailable.
"""
import pytest

from Orchestrator import orchestrator_brain as ob


@pytest.mark.parametrize(
    "prompt, expected",
    [
        ("My laptop won't connect to WiFi, create an IT ticket", ["it_support"]),
        ("My laptop cannot connect to office wifi, raise a complaint.", ["it_support"]),
        ("Generate interview questions for a senior Python developer", ["hr"]),
        ("Analyze these expenses and highlight the top 5 costs: Travel - 4500", ["finance"]),
        ("Search Google Drive for the onboarding policy PDF", ["documents"]),
        ("Fetch the latest 10 candidate emails", ["hr_gmail"]),
        ("Send a welcome email to ali@example.com - start Monday as Software Engineer", ["email"]),
        ("Add Ayesha Khan, Accounts Officer, salary 150000 PKR, starts 1 December.", ["finance"]),
        ("What can you do?", ["general"]),
        ("hello", ["general"]),
        ("xyzzy", ["general"]),
    ],
)
def test_keyword_routing(prompt, expected):
    assert ob.detect_intent(prompt) == expected


@pytest.mark.legacy_bug
def test_payroll_question_routes_to_hr_not_finance():
    assert ob.detect_intent("What is the total monthly payroll?") == ["hr"]


@pytest.mark.legacy_bug
@pytest.mark.parametrize("prompt", [
    "Schedule a meeting with the HR team tomorrow at 3 pm for 45 minutes",
])
def test_no_calendar_agent_exists(prompt):
    # There is no calendar agent; scheduling prompts fall into HR.
    assert ob.detect_intent(prompt) == ["hr"]


def test_unmatched_requests_fall_back_to_general():
    assert ob.detect_intent("Am I free Friday afternoon?") == ["general"]
    assert ob.detect_intent("Delete Ahmed") == ["general"]


def test_numbered_task_split():
    assert ob._split_numbered_tasks("1. a thing 2. b thing 3. c") == ["a thing", "b thing", "c"]
    assert ob._split_numbered_tasks("just one task") == []


def test_agent_slug_normalization():
    assert ob.normalize_agent_slug("Google Drive") == "documents"
    assert ob.normalize_agent_slug("IT") == "it_support"
    assert ob.normalize_agent_list(["IT", "bogus", "it_support"]) == ["it_support"]
    assert ob.normalize_agent_list([]) == ["general"]


@pytest.mark.legacy_bug
def test_orchestrator_is_a_process_wide_singleton_with_per_request_state():
    # route() writes self._agent_tasks / self._finance_export_files on a shared
    # instance; concurrent Streamlit sessions can overwrite each other's plan.
    assert isinstance(ob.orchestrator, ob.Orchestrator)
    assert hasattr(ob.orchestrator, "_agent_tasks")
