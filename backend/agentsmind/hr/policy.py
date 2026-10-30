"""HR settings with defaults: company profile, leave policy, payroll rules and checklist templates.

Everything here is editable in HR > Settings and stored in the hr_settings table. The
defaults follow common practice in Karachi (Sindh, Pakistan). Statutory amounts that change
every year (income tax slabs, EOBI and SESSI rates) are NOT computed by AgentsMind: the
rates below default to 0 and HR sets them, so no figure is invented.
"""
from __future__ import annotations

import copy
from typing import Any


class HRError(Exception):
    """A message that is safe to show the user."""

DEFAULTS: dict[str, Any] = {
    "company": {
        "name": "",
        "address": "",
        "city": "Karachi",
        "phone": "",
        "email": "",
        "website": "",
        "signatory_name": "",
        "signatory_title": "Head of Human Resources",
    },
    "recruitment": {
        "candidate_city": "Karachi",
        "city_aliases": ["karachi", "khi"],
        # Karachi areas, so a CV that names only the area still counts as Karachi
        "areas": ["gulshan", "gulistan-e-johar", "gulistan e johar", "johar", "clifton", "dha", "defence", "saddar",
                  "nazimabad", "north nazimabad", "north karachi", "korangi", "malir", "landhi", "pechs", "bahadurabad",
                  "federal b area", "fb area", "gulberg", "orangi", "lyari", "kemari", "shah faisal", "surjani",
                  "scheme 33", "bahria town karachi", "tariq road", "garden", "lines area", "jamshed road",
                  "model colony", "malir cantt", "saadi town", "buffer zone", "new karachi", "baldia", "site area"],
        "include_unknown_location": True,  # CVs without a city are screened and marked "not stated"
        "gmail_query": "(cv OR resume OR \"curriculum vitae\" OR application) newer_than:90d",
    },
    "work": {
        "weekend": [5, 6],  # Monday=0 ... Saturday=5, Sunday=6
        "office_start": "09:00",
        "late_after": "09:15",
        "office_end": "18:00",
        "holidays": [],  # ISO dates
    },
    "leave": {
        # days per calendar year; pro-rated for joiners during the year
        "annual": 14,
        "casual": 10,
        "sick": 8,
        "unpaid": 0,  # no limit; always deducted
        "maternity": 90,
        "paternity": 3,
        "carry_forward_annual": 0,
        "encash_annual_on_exit": True,
    },
    "payroll": {
        "currency": "PKR",
        "pay_day": 1,  # day of the next month
        "days_basis": "calendar",  # calendar | 30 | working: per-day rate for deductions
        "deduct_absent_without_leave": True,
        "eobi_employee_amount": 0,  # fixed monthly amount set by HR (rates change yearly)
        "tax_withholding_percent": 0,  # set by HR from the current FBR slabs; 0 = not computed
        "probation_months": 3,
        "notice_days": 30,
    },
    "onboarding": [
        # key, title, owner, due (days relative to joining), automated action
        {"key": "offer_letter", "title": "Offer letter issued", "owner": "hr", "due": -14, "action": "offer_letter"},
        {"key": "offer_accepted", "title": "Signed offer received", "owner": "employee", "due": -7},
        {"key": "contract", "title": "Employment contract generated and signed", "owner": "hr", "due": 0,
         "action": "contract"},
        {"key": "documents", "title": "Documents collected: CNIC copy, degrees, experience letters, photographs",
         "owner": "employee", "due": 0},
        {"key": "bank_details", "title": "Bank account details for salary received", "owner": "employee", "due": 0},
        {"key": "it_setup", "title": "IT: laptop, company email and system access ready", "owner": "it", "due": -2,
         "action": "it_ticket"},
        {"key": "payroll", "title": "Added to payroll (Finance Portal)", "owner": "hr", "due": 0,
         "action": "payroll_enroll"},
        {"key": "welcome", "title": "Welcome email with onboarding letter sent", "owner": "hr", "due": -3,
         "action": "welcome_email"},
        {"key": "whatsapp", "title": "WhatsApp welcome message sent", "owner": "hr", "due": -1,
         "action": "whatsapp"},
        {"key": "record", "title": "New joiner recorded in the HR sheet", "owner": "hr", "due": 0,
         "action": "sheet_record"},
        {"key": "buddy", "title": "Buddy assigned", "owner": "manager", "due": 0},
        {"key": "probation_review", "title": "Probation review meeting scheduled", "owner": "hr", "due": 85,
         "action": "probation_event"},
    ],
    "induction": [
        {"key": "orientation", "title": "Day 1: welcome and orientation", "day": 0, "time": "10:00", "minutes": 60},
        {"key": "policies", "title": "HR policies and code of conduct session", "day": 0, "time": "12:00",
         "minutes": 45},
        {"key": "it_induction", "title": "IT systems induction", "day": 0, "time": "15:00", "minutes": 45},
        {"key": "department", "title": "Department introduction with the manager", "day": 1, "time": "11:00",
         "minutes": 60},
        {"key": "week1_checkin", "title": "Week 1 check-in with HR", "day": 4, "time": "16:00", "minutes": 30},
    ],
    "compliance": [
        {"key": "contract_signed", "title": "Employment contract signed", "due": 0},
        {"key": "cnic_copy", "title": "CNIC copy on file (verified with the original)", "due": 0},
        {"key": "education_verified", "title": "Educational documents verified", "due": 30},
        {"key": "experience_verified", "title": "Previous experience letters verified", "due": 30},
        {"key": "eobi", "title": "EOBI registration", "due": 30},
        {"key": "sessi", "title": "SESSI (Sindh Employees' Social Security) registration", "due": 30},
        {"key": "tax", "title": "Income tax details (NTN or CNIC) recorded for withholding", "due": 30},
        {"key": "nda", "title": "Confidentiality agreement signed", "due": 0},
        {"key": "policy_ack", "title": "HR policy handbook and code of conduct acknowledged", "due": 7},
        {"key": "emergency_contact", "title": "Emergency contact recorded", "due": 7},
        {"key": "medical", "title": "Medical / group insurance enrolment", "due": 30},
    ],
    "separation": [
        {"key": "resignation_letter", "title": "Resignation acceptance letter issued", "owner": "hr", "due": -25,
         "action": "resignation_acceptance"},
        {"key": "handover", "title": "Work handover completed", "owner": "manager", "due": -1},
        {"key": "assets", "title": "Company assets returned (laptop, ID card, access card)", "owner": "it", "due": 0,
         "action": "it_offboarding"},
        {"key": "access", "title": "Email and system access removed", "owner": "it", "due": 0},
        {"key": "exit_interview", "title": "Exit interview", "owner": "hr", "due": -2, "action": "exit_interview"},
        {"key": "settlement", "title": "Final settlement calculated and approved", "owner": "hr", "due": 5},
        {"key": "payroll_exit", "title": "Removed from payroll (Finance Portal)", "owner": "hr", "due": 5,
         "action": "payroll_exit"},
        {"key": "final_letter", "title": "Final settlement letter and experience certificate issued", "owner": "hr",
         "due": 7, "action": "final_letters"},
        {"key": "record", "title": "Separation recorded in the HR sheet", "owner": "hr", "due": 0,
         "action": "sheet_record"},
    ],
}

LEAVE_TYPES = ("annual", "casual", "sick", "unpaid", "maternity", "paternity")
SHEET_PURPOSES = ("employees", "new_joiners", "attendance", "leave", "payroll", "separations", "compliance",
                  "candidates", "other")


def merged(stored: dict[str, Any] | None) -> dict[str, Any]:
    """Defaults overlaid with what HR saved (one level deep for dict sections)."""
    out = copy.deepcopy(DEFAULTS)
    for k, v in (stored or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        elif v is not None:
            out[k] = v
    return out


def company_ready(s: dict[str, Any]) -> list[str]:
    """Company details still missing for letters."""
    c = s["company"]
    return [label for key, label in (("name", "company name"), ("address", "company address"),
                                     ("signatory_name", "HR signatory name")) if not str(c.get(key, "")).strip()]
