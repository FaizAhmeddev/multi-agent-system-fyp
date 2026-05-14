"""
AGENTS/FINANCE_AGENT.PY
========================
Finance Agent — Q&A, expense analysis, invoice summary, reports, budget vs actual,
and **multi-format document export** (PDF, XLSX, CSV, TXT, DOCX) with parallel encoding.
All errors are caught and returned as readable messages.
"""

import os


def _get_llm():
    from langchain_openai import ChatOpenAI
    from config import OPENAI_API_KEY
    os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY
    return ChatOpenAI(model="gpt-4o-mini", temperature=0.2)


def _error_msg(action: str, error: Exception, tips: list = None) -> str:
    tips_text = ""
    if tips:
        tips_text = "\n**Tips:**\n" + "\n".join(f"- {t}" for t in tips)
    return f"❌ **{action} Error:** {error}{tips_text}"


def answer_finance_query(question: str, context: str = "", user_name: str = "User") -> str:
    """Answer a finance question, optionally with document context."""
    try:
        llm = _get_llm()
        context_section = f"\n\nContext:\n{context[:3000]}" if context and context.strip() else ""
        prompt = f"""You are a professional Finance Assistant.

User: {user_name}
Question: {question}{context_section}

Provide a clear, accurate, professional answer.
- Show calculations where relevant
- Explain concepts in plain language
- Use bullet points for clarity
- Note if more information is needed"""
        return llm.invoke(prompt).content
    except Exception as e:
        return _error_msg("Finance Q&A", e, tips=["Set OPENAI_API_KEY in your `.env` file (see `.env.example`)."])


def analyze_expenses(expense_text: str, user_name: str = "User") -> str:
    """Analyze expense data — CSV or plain text."""
    try:
        if not expense_text or len(expense_text.strip()) < 10:
            return ("📊 **Please provide expense data.**\n\n"
                    "**Format example:**\n"
                    "```\nDate, Item, Amount, Category\n"
                    "2024-01-05, Office Supplies, 2500, Operations\n"
                    "2024-01-10, AWS Cloud, 15000, IT\n```")
        llm = _get_llm()
        prompt = f"""You are a Finance Analyst.

User {user_name} provided expense data:
{expense_text[:4000]}

Analyze and provide:
**1. Total Expenses** — sum
**2. Category Breakdown** — subtotals per category  
**3. Top 5 Highest Expenses**
**4. Key Observations** — trends, anomalies
**5. Recommendations** — 2-3 practical suggestions"""
        return llm.invoke(prompt).content
    except Exception as e:
        return _error_msg("Expense Analysis", e)


def summarize_invoice(invoice_text: str) -> str:
    """Extract and summarize key fields from invoice text."""
    try:
        if not invoice_text or len(invoice_text.strip()) < 20:
            return ("📄 **Please paste invoice text.**\n\n"
                    "Include: Invoice #, Vendor, Items/Services, Amounts, Total, Due Date.")
        llm = _get_llm()
        prompt = f"""You are a Finance Assistant extracting invoice details.

Invoice:
{invoice_text[:2500]}

Extract and format:
**Invoice Summary**
- Invoice #:
- Vendor/Supplier:
- Issue Date:
- Due Date:
- Line Items: (table)
- Subtotal:
- Tax:
- **Total Due:**
- Payment Terms:
- Status: (Paid/Unpaid/Overdue)

Then: 2-3 sentence summary + any payment recommendations."""
        return llm.invoke(prompt).content
    except Exception as e:
        return _error_msg("Invoice Summary", e)


def generate_finance_report(data: str, report_type: str = "general") -> str:
    """Generate a financial report."""
    try:
        if not data or len(data.strip()) < 10:
            return "📋 **Please provide financial data for the report.**"
        llm = _get_llm()
        report_labels = {
            "general":  "General Financial Report",
            "budget":   "Budget Report",
            "expense":  "Expense Report",
            "invoice":  "Invoice/Receivables Report",
        }
        report_label = report_labels.get(report_type, "Financial Report")
        prompt = f"""You are a Finance Manager generating a {report_label}.

Data provided:
{data[:4000]}

Generate a professional report with:
**Executive Summary** (3-4 sentences)
**Key Financial Metrics** (table format)
**Analysis** (trends, variances, highlights)
**Risks & Concerns** (if any)
**Recommendations** (3-5 actionable items)

Use professional financial language. Include PKR currency where applicable."""
        return llm.invoke(prompt).content
    except Exception as e:
        return _error_msg("Report Generation", e)


def analyze_budget_vs_actual(budget_text: str, actual_text: str) -> str:
    """Compare budget vs actual spending."""
    try:
        if not budget_text or not actual_text:
            return ("📊 **Provide both Budget and Actual data.**\n\n"
                    "**Budget format:** Category, Budgeted Amount\n"
                    "**Actual format:** Category, Actual Amount")
        llm = _get_llm()
        prompt = f"""You are a Finance Analyst doing Budget vs Actual analysis.

**Budget Data:**
{budget_text[:2000]}

**Actual Data:**
{actual_text[:2000]}

Provide:
**Budget vs Actual Comparison Table**
(Category | Budget | Actual | Variance | % Variance)

**Summary:**
- Over-budget items
- Under-budget items
- Total variance

**Analysis:** Key observations
**Recommendations:** Action items"""
        return llm.invoke(prompt).content
    except Exception as e:
        return _error_msg("Budget vs Actual", e)


def extract_financial_insights_from_docs(doc_list: list) -> str:
    """Extract financial insights from a list of documents."""
    try:
        if not doc_list:
            return "📂 No documents provided. Load documents from Google Drive first."
        llm = _get_llm()
        combined = "\n\n---\n\n".join(str(d)[:1000] for d in doc_list[:5])
        prompt = f"""You are a Finance Analyst reviewing documents for financial insights.

Documents:
{combined}

Extract:
1. **Key Financial Figures** (amounts, percentages, dates)
2. **Revenue / Income mentions**
3. **Expense / Cost mentions**
4. **Budget or Target mentions**
5. **Payment Terms / Due Dates**
6. **Financial Risks or Flags**

Summarize insights clearly."""
        return llm.invoke(prompt).content
    except Exception as e:
        return _error_msg("Document Insights", e)
