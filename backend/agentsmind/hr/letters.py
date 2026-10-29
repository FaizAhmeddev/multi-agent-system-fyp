"""Ready-made HR letters as Word (.docx) and PDF.

Kinds: offer, contract, welcome (onboarding), conduct, resignation_acceptance, final_settlement,
experience. Each letter is built from fields in code (amounts and dates are formatted here,
never written by a model). An optional model-written paragraph (for example the facts of a
conduct issue as HR described them) is inserted as plain text.

Your own formats: put a Word file named <kind>.docx (for example offer.docx) in
data/hr_templates/. Placeholders like {{name}}, {{job_title}}, {{joining_date}},
{{salary}} are replaced and the result is saved as Word; the PDF is rendered from it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]

KINDS = {
    "offer": "Offer letter",
    "contract": "Employment contract",
    "welcome": "Onboarding welcome letter",
    "conduct": "Conduct letter",
    "resignation_acceptance": "Resignation acceptance letter",
    "final_settlement": "Final resignation acceptance and full and final settlement",
    "experience": "Experience certificate",
}
DOCS_DIR = REPO_ROOT / "data" / "hr_documents"
TEMPLATES_DIR = REPO_ROOT / "data" / "hr_templates"


@dataclass
class Letter:
    kind: str
    title: str
    subject: str
    recipient: list[str]
    salutation: str
    paragraphs: list[str]
    table: list[tuple[str, str]] = field(default_factory=list)
    table_title: str = ""
    closing: str = "Yours sincerely,"
    acknowledgement: str = ""
    fields: dict[str, Any] = field(default_factory=dict)


def fmt_date(d: date | str | None) -> str:
    if not d:
        return "to be confirmed"
    if isinstance(d, str):
        try:
            d = date.fromisoformat(d[:10])
        except ValueError:
            return d
    return d.strftime("%d %B %Y").lstrip("0")


def fmt_money(amount: float | int | None, currency: str = "PKR") -> str:
    if amount in (None, ""):
        return "to be confirmed"
    return f"{currency} {float(amount):,.0f}" if float(amount).is_integer() else f"{currency} {float(amount):,.2f}"


def _common(f: dict[str, Any], company: dict[str, Any]) -> dict[str, Any]:
    out = dict(f)
    out.setdefault("company_name", company.get("name") or "the Company")
    out.setdefault("company_city", company.get("city") or "Karachi")
    out.setdefault("signatory_name", company.get("signatory_name") or "")
    out.setdefault("signatory_title", company.get("signatory_title") or "Human Resources")
    out.setdefault("today", date.today())
    return out


def build(kind: str, f: dict[str, Any], policy: dict[str, Any]) -> Letter:
    if kind not in KINDS:
        raise ValueError(f"Unknown letter kind '{kind}'.")
    c = policy["company"]
    f = _common(f, c)
    name = f.get("name", "")
    first = name.split()[0] if name else ""
    cur = f.get("currency") or policy["payroll"]["currency"]
    company = f["company_name"]
    rec = [name] + [x for x in (f.get("address"), f.get("email")) if x]
    pay = policy["payroll"]
    leave = policy["leave"]
    if kind == "offer":
        rows = [("Position", f.get("job_title", "")), ("Department", f.get("department", "") or "-"),
                ("Location", f.get("location") or c.get("city") or "Karachi"),
                ("Employment type", (f.get("employment_type") or "permanent").capitalize()),
                ("Joining date", fmt_date(f.get("joining_date"))),
                ("Monthly gross salary", fmt_money(f.get("salary"), cur))]
        for k, v in (f.get("allowances") or {}).items():
            rows.append((f"{k.replace('_', ' ').capitalize()} allowance", fmt_money(v, cur)))
        rows += [("Probation", f"{f.get('probation_months') or pay['probation_months']} months"),
                 ("Reporting to", f.get("manager") or "-"),
                 ("Working hours", f"{policy['work']['office_start']} to {policy['work']['office_end']}, "
                                   "Monday to Friday")]
        paras = [
            f"We are pleased to offer you the position of {f.get('job_title', '')} at {company}. This letter sets "
            "out the main terms of the offer.",
            "This offer is subject to verification of your educational and experience documents and your CNIC. "
            "A detailed employment contract will be issued on joining.",
            f"Please confirm your acceptance by signing and returning a copy of this letter by "
            f"{fmt_date(f.get('offer_valid_until'))}. After that date the offer lapses.",
            f"We look forward to welcoming you to {company}.",
        ]
        return Letter(kind, KINDS[kind], f"Offer of employment: {f.get('job_title', '')}", rec, f"Dear {first or name},",
                      paras, rows, "Terms of the offer", acknowledgement="I accept this offer on the terms above.",
                      fields=f)
    if kind == "contract":
        rows = [("Employee", name), ("Position", f.get("job_title", "")), ("Department", f.get("department", "") or "-"),
                ("Start date", fmt_date(f.get("joining_date"))), ("Monthly gross salary", fmt_money(f.get("salary"),
                                                                                                  cur)),
                ("Probation", f"{f.get('probation_months') or pay['probation_months']} months"),
                ("Notice period", f"{pay['notice_days']} days by either party (after probation)"),
                ("Annual / casual / sick leave", f"{leave['annual']} / {leave['casual']} / {leave['sick']} days a year")]
        paras = [
            f"This agreement is made between {company} (the Company) and {name} (the Employee).",
            "1. Duties. The Employee will perform the duties of the position above and other reasonable duties "
            "assigned by the Company, and will follow the Company's policies and code of conduct.",
            f"2. Working hours. {policy['work']['office_start']} to {policy['work']['office_end']}, Monday to Friday, "
            "with such additional hours as the role reasonably requires.",
            "3. Pay. Salary is paid monthly in arrears by bank transfer, after statutory deductions.",
            "4. Probation. During probation either party may end employment with 7 days' notice. Confirmation is "
            "in writing.",
            "5. Leave. Leave is granted under the Company's leave policy and applicable law.",
            "6. Confidentiality. The Employee will keep the Company's information confidential during and after "
            "employment, and return all Company property on leaving.",
            "7. Termination. After probation, either party may end employment with the notice period above or "
            "salary in lieu of notice. The Company may end employment without notice for gross misconduct.",
            "8. Governing law. This agreement is governed by the laws of Pakistan and the Province of Sindh.",
        ]
        return Letter(kind, KINDS[kind], f"Employment contract: {f.get('job_title', '')}", rec, "", paras, rows,
                      "Key terms", closing="Signed for and on behalf of the Company,",
                      acknowledgement="I agree to the terms of this contract.", fields=f)
    if kind == "welcome":
        rows = [(fmt_date(x.get("date")) + (f", {x['time']}" if x.get("time") else ""), x["title"])
                for x in f.get("induction", [])]
        paras = [
            f"Welcome to {company}! We are delighted that you are joining us as {f.get('job_title', '')} on "
            f"{fmt_date(f.get('joining_date'))}.",
            f"Please arrive at {policy['work']['office_start']} on your first day"
            + (f" at {f['location']}" if f.get("location") else "") + ". Bring your original CNIC, educational "
            "certificates, experience letters, two photographs and your bank account details.",
            "Your laptop, company email and system access are being prepared, and your first days are planned "
            "below." if rows else "Your laptop, company email and system access are being prepared.",
            f"Your manager is {f['manager']}." if f.get("manager") else "",
            "If you have any questions before you join, simply reply to this email.",
        ]
        return Letter(kind, KINDS[kind], f"Welcome to {company}", rec, f"Dear {first or name},", [p for p in paras if p],
                      rows, "Your induction plan" if rows else "", fields=f)
    if kind == "conduct":
        paras = [
            f"This letter concerns {f.get('issue') or 'a conduct matter'}"
            + (f" on {fmt_date(f.get('incident_date'))}" if f.get("incident_date") else "") + ".",
            f.get("details") or "",
            "This conduct does not meet the standards set out in the Company's code of conduct. You are expected "
            + (f.get("expectation") or "to meet these standards with immediate effect") + ".",
            "Any repetition may lead to further disciplinary action in line with Company policy. You may respond "
            "in writing within 3 working days if you wish to explain your position.",
        ]
        return Letter(kind, KINDS[kind], f"Conduct: {f.get('issue') or 'expected standards'}", rec,
                      f"Dear {first or name},", [p for p in paras if p],
                      acknowledgement="I acknowledge receipt of this letter.", fields=f)
    if kind == "resignation_acceptance":
        paras = [
            f"We acknowledge receipt of your resignation dated {fmt_date(f.get('notice_date'))} from the position of "
            f"{f.get('job_title', '')}.",
            f"Your resignation is accepted. Your last working day will be {fmt_date(f.get('last_working_day'))}.",
            "Before your last day, please complete the handover of your work, return all Company property and "
            "attend an exit interview with HR. Your final settlement will be processed after clearance.",
            f"Thank you for your contribution to {company}. We wish you every success.",
        ]
        return Letter(kind, KINDS[kind], "Acceptance of resignation", rec, f"Dear {first or name},", paras, fields=f)
    if kind == "final_settlement":
        s = f.get("settlement") or {}
        rows = [(x["item"], fmt_money(x["amount"], s.get("currency", cur))) for x in s.get("lines", [])]
        rows.append(("Net amount payable", fmt_money(s.get("net_payable"), s.get("currency", cur))))
        paras = [
            f"Further to your resignation, your employment with {company} as {f.get('job_title', '')} ended on "
            f"{fmt_date(f.get('last_working_day'))}, after clearance of your handover and Company property.",
            "Your full and final settlement is set out below. It will be paid to your bank account on file within "
            "the normal payroll cycle.",
            "With this payment, all dues between you and the Company are settled in full. Please sign and return "
            "a copy to confirm.",
        ]
        return Letter(kind, "Final resignation acceptance and settlement", "Full and final settlement", rec,
                      f"Dear {first or name},", paras, rows, "Settlement", acknowledgement="I confirm receipt of my "
                      "full and final settlement and have no further claims against the Company.", fields=f)
    # experience
    paras = [
        f"This is to certify that {name} was employed with {company} as {f.get('job_title', '')}"
        + (f" in the {f['department']} department" if f.get("department") else "")
        + f" from {fmt_date(f.get('joining_date'))} to {fmt_date(f.get('last_working_day'))}.",
        f.get("remarks") or f"During this period {first or name} carried out their duties diligently.",
        "We wish them success in their future career.",
    ]
    return Letter(kind, KINDS[kind], "To whom it may concern", [], "", paras, fields=f)


# ---------------------------------------------------------------------------- rendering

def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()[:60] or "letter"


def out_paths(letter: Letter, folder_name: str, letter_id: int | str) -> tuple[Path, Path]:
    d = (DOCS_DIR / _slug(folder_name)).resolve()
    d.mkdir(parents=True, exist_ok=True)
    stem = f"{letter.kind}-{date.today().isoformat()}-{letter_id}"
    return d / f"{stem}.docx", d / f"{stem}.pdf"


def _header_lines(company: dict[str, Any]) -> list[str]:
    return [x for x in (company.get("name"), company.get("address"), " | ".join(
        v for v in (company.get("phone"), company.get("email"), company.get("website")) if v)) if x]


def render_docx(letter: Letter, company: dict[str, Any], path: Path, ref: str) -> None:
    from docx import Document
    from docx.shared import Pt

    custom = TEMPLATES_DIR / f"{letter.kind}.docx"
    if custom.is_file():
        _fill_template(custom, path, letter)
        return
    doc = Document()
    st = doc.styles["Normal"]
    st.font.name = "Calibri"
    st.font.size = Pt(11)
    for i, line in enumerate(_header_lines(company)):
        p = doc.add_paragraph()
        r = p.add_run(line)
        r.bold = i == 0
        r.font.size = Pt(14 if i == 0 else 9)
    doc.add_paragraph(f"Ref: {ref}    Date: {fmt_date(letter.fields.get('today'))}")
    for line in letter.recipient:
        doc.add_paragraph(line).paragraph_format.space_after = Pt(0)
    doc.add_paragraph()
    p = doc.add_paragraph()
    p.add_run(f"Subject: {letter.subject}").bold = True
    if letter.salutation:
        doc.add_paragraph(letter.salutation)
    for para in letter.paragraphs:
        doc.add_paragraph(para)
    if letter.table:
        if letter.table_title:
            doc.add_paragraph().add_run(letter.table_title).bold = True
        t = doc.add_table(rows=0, cols=2)
        t.style = "Table Grid"
        for a, b in letter.table:
            cells = t.add_row().cells
            cells[0].text, cells[1].text = str(a), str(b)
    doc.add_paragraph()
    doc.add_paragraph(letter.closing)
    doc.add_paragraph("\n")
    sig = letter.fields.get("signatory_name") or "______________________"
    doc.add_paragraph(sig).paragraph_format.space_after = Pt(0)
    doc.add_paragraph(letter.fields.get("signatory_title", "")).paragraph_format.space_after = Pt(0)
    doc.add_paragraph(letter.fields.get("company_name", ""))
    if letter.acknowledgement:
        doc.add_paragraph()
        doc.add_paragraph(letter.acknowledgement)
        doc.add_paragraph("Signature: ______________________    Date: ______________")
    doc.save(str(path))


def _placeholders(letter: Letter) -> dict[str, str]:
    f = letter.fields
    vals = {k: (fmt_date(v) if isinstance(v, date) or k.endswith("date") or k == "last_working_day" else
                fmt_money(v, f.get("currency", "PKR")) if k == "salary" else str(v))
            for k, v in f.items() if isinstance(v, str | int | float | date)}
    vals.update(subject=letter.subject, body="\n\n".join(letter.paragraphs))
    return vals


def _fill_template(src: Path, dst: Path, letter: Letter) -> None:
    from docx import Document

    vals = _placeholders(letter)
    doc = Document(str(src))

    def fill(paragraphs):
        for p in paragraphs:
            if "{{" not in p.text:
                continue
            text = re.sub(r"\{\{\s*(\w+)\s*\}\}", lambda m: vals.get(m.group(1), m.group(0)), p.text)
            for r in p.runs[1:]:
                r.text = ""
            if p.runs:
                p.runs[0].text = text
    fill(doc.paragraphs)
    for t in doc.tables:
        for row in t.rows:
            for cell in row.cells:
                fill(cell.paragraphs)
    doc.save(str(dst))


def render_pdf(letter: Letter, company: dict[str, Any], path: Path, ref: str, docx_path: Path | None = None) -> None:
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    body = styles["BodyText"]
    body.fontSize, body.leading = 10.5, 14
    story = []
    custom = TEMPLATES_DIR / f"{letter.kind}.docx"
    if custom.is_file() and docx_path is not None and docx_path.is_file():
        from docx import Document

        for p in Document(str(docx_path)).paragraphs:
            story.append(Paragraph(escape(p.text) or "&nbsp;", body))
    else:
        for i, line in enumerate(_header_lines(company)):
            st = styles["Title"] if i == 0 else styles["Normal"]
            story.append(Paragraph(escape(line), st))
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph(f"Ref: {escape(ref)} &nbsp;&nbsp; Date: {fmt_date(letter.fields.get('today'))}", body))
        story.append(Spacer(1, 3 * mm))
        for line in letter.recipient:
            story.append(Paragraph(escape(line), body))
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph(f"<b>Subject: {escape(letter.subject)}</b>", body))
        story.append(Spacer(1, 2 * mm))
        if letter.salutation:
            story.append(Paragraph(escape(letter.salutation), body))
        for para in letter.paragraphs:
            story.append(Paragraph(escape(para), body))
            story.append(Spacer(1, 2 * mm))
        if letter.table:
            if letter.table_title:
                story.append(Paragraph(f"<b>{escape(letter.table_title)}</b>", body))
            t = Table([[Paragraph(escape(str(a)), body), Paragraph(escape(str(b)), body)] for a, b in letter.table],
                      colWidths=[70 * mm, 95 * mm])
            t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            story.append(t)
        story.append(Spacer(1, 8 * mm))
        story.append(Paragraph(escape(letter.closing), body))
        story.append(Spacer(1, 12 * mm))
        for line in (letter.fields.get("signatory_name") or "______________________",
                     letter.fields.get("signatory_title", ""), letter.fields.get("company_name", "")):
            story.append(Paragraph(escape(line), body))
        if letter.acknowledgement:
            story.append(Spacer(1, 10 * mm))
            story.append(Paragraph(escape(letter.acknowledgement), body))
            story.append(Paragraph("Signature: ______________________ &nbsp;&nbsp; Date: ______________", body))
    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm,
                      bottomMargin=18 * mm, title=letter.title).build(story)


def render(letter: Letter, company: dict[str, Any], folder_name: str, letter_id: int, ref: str) -> tuple[Path, Path]:
    docx_path, pdf_path = out_paths(letter, folder_name, letter_id)
    render_docx(letter, company, docx_path, ref)
    render_pdf(letter, company, pdf_path, ref, docx_path)
    return docx_path, pdf_path
