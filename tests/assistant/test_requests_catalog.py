"""The request catalogue from the FYP demo: each prompt reaches the right agent and does the right thing."""
from __future__ import annotations

import pytest
from fakectx import FakeCtx

from agentsmind.assistant.orchestrator import plan, run_turn

CV = ("Uzair Ahmed\nKarachi, Pakistan\nuzair.ahmed@gmail.com 0300-1112223\nSoftware Engineer, 4 years\n"
      "Skills: Python, Django, Git, Agile/Scrum, REST APIs\nBS Computer Science, NED University")


@pytest.mark.parametrize("text,agents", [
    ("Find Uzair's CV, summarize it, and email that CV to Huzaifa", ["hr", "email"]),
    ("Select 6 software developers with good understanding of agile methodologies and git experience", ["hr"]),
    ("Fetch the latest 10 candidate emails", ["hr"]),
    ("Shortlist 3 Python developers from the last 20 emails", ["hr"]),
    ("Email the top 2 candidates for the Python developer role", ["hr"]),
    ("Summarize the attached CV", ["documents"]),
    ("Analyze the attached campaign report and prepare a management summary", ["documents"]),
    ("Compare the two attached documents and highlight differences", ["documents"]),
    ("Find the attached CV, summarize it, and email it to Huzaifa", ["documents", "email"]),
    ("Read the attached report, summarize it, and send the summary to Huzaifa", ["documents", "email"]),
    ("Analyze these expenses and highlight the top 5 costs", ["documents"]),
    ("Prepare a budget vs actual analysis", ["documents"]),
    ("My laptop won't connect to WiFi, create an IT ticket", ["it"]),
    ("VPN not connecting, raise a support ticket", ["it"]),
    ("New employee Ali Khan joining Monday as Software Engineer - complete full onboarding", ["hr"]),
    ("Create employee profile, welcome email, offer letter, IT ticket, and payroll entry for Ahmed", ["hr"]),
])
def test_routing(text, agents):
    assert [s.agent for s in plan(text)] == agents


def test_hr_intents():
    from datetime import date

    from agentsmind.assistant.agents.hr import handlers as H
    from agentsmind.assistant.agents.hr.parse import parse

    t = "Select 6 software developers with good understanding of agile methodologies and git experience"
    assert parse(None, t, date(2026, 10, 30))[0] == "screen"
    assert (H._role_only(t), H._criteria(t), H._top_count(t)) == ("Software Developer", ["Agile methodologies", "Git"], 6)
    assert parse(None, "Find Uzair's CV, summarize it", date(2026, 10, 30))[0] == "cv_find"
    assert parse(None, "Fetch the latest 10 candidate emails", date(2026, 10, 30))[0] == "candidate_emails"
    assert parse(None, "Email the top 2 candidates for the Python developer role", date(2026, 10, 30))[0] == \
        "email_candidates"
    _, s, _ = parse(None, "New employee Ali Khan joining Monday as Software Engineer - complete full onboarding",
                    date(2026, 10, 30))
    assert s["job_title"] == "Software Engineer"


def _ctx(tmp_path, files=()):
    c = FakeCtx(tmp_path, roles=("hr",), tools={
        "gmail_read_inbox": lambda a: {"items": [], "simulated": False},
        "gmail_find_attachments": lambda a: {"items": [{"message_id": "77", "attachment": 0,
                                                        "filename": "Uzair_Ahmed_CV.pdf", "mime_type": "application/pdf",
                                                        "size": 9, "sender": "Uzair <uzair.ahmed@gmail.com>",
                                                        "subject": "Application", "date": "2026-10-29"}],
                                             "searched": 1, "simulated": False},
        "gmail_read_attachment": lambda a: {"text": CV, "saved_path": str(tmp_path / "77_Uzair_Ahmed_CV.pdf")},
    })
    c.attachments = list(files)
    return c


def _talk(ctx, *msgs):
    pending, out = None, []
    for m in msgs:
        r = run_turn(ctx, m, pending)
        pending = r.pending
        out.append(r.cards)
    return out


def test_find_cv_summarize_and_email_it(tmp_path):
    (first, second) = _talk(_ctx(tmp_path), "Find Uzair's CV, summarize it, and email that CV to Huzaifa",
                            "huzaifa@company.pk")
    assert first[0].agent == "hr" and "Uzair" in first[0].title and "Found in Gmail" in first[0].body
    assert first[-1].kind == "clarify" and "Huzaifa" in first[-1].body
    appr = second[-1]
    assert appr.kind == "approval" and appr.data["arguments"]["to"] == ["huzaifa@company.pk"]
    assert appr.data["arguments"]["attachments"] == [str(tmp_path / "77_Uzair_Ahmed_CV.pdf")]
    assert "Python" in appr.data["arguments"]["body"]


def test_attached_report_summary_sent_without_the_file(tmp_path):
    f = {"id": "0123456789abcdef", "name": "Q3 campaign.pdf", "path": str(tmp_path / "Q3 campaign.pdf"),
         "text": "Q3 campaign report\nReach grew 40% to 1.2 million.\nCost per lead fell to PKR 310.\nNext: TikTok test.",
         "kind": "upload"}
    (cards,) = _talk(_ctx(tmp_path, [f]), "Read the attached report, summarize it, and send the summary to "
                                         "huzaifa@company.pk")
    assert cards[0].agent == "documents" and cards[0].title.startswith("Summary of Q3 campaign.pdf")
    args = cards[-1].data["arguments"]
    assert "attachments" not in args and "Reach grew 40%" in args["body"]


def test_attached_cv_is_emailed_with_the_file(tmp_path):
    f = {"id": "0123456789abcdef", "name": "Ali CV.docx", "path": str(tmp_path / "Ali CV.docx"), "text": CV,
         "kind": "upload"}
    (cards,) = _talk(_ctx(tmp_path, [f]), "Find the attached CV, summarize it, and email it to huzaifa@company.pk")
    assert cards[-1].data["arguments"]["attachments"] == [f["path"]]


def test_attachment_needed(tmp_path):
    (cards,) = _talk(_ctx(tmp_path), "Analyze these expenses and highlight the top 5 costs")
    assert cards[-1].kind == "clarify" and "paperclip" in cards[-1].body
