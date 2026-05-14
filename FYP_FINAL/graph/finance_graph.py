from langgraph.graph import StateGraph, END
from state.finance_state import FinanceState
from agents.finance_agent import (
    answer_finance_query, analyze_expenses, summarize_invoice,
    generate_finance_report, analyze_budget_vs_actual,
    extract_financial_insights_from_docs,
)


def finance_router(state: FinanceState) -> FinanceState:
    action = state.get("action", "query")

    if action == "analyze_expenses":
        state["output"] = analyze_expenses(
            expense_text=state.get("data", ""),
            user_name=state.get("user_name", "User"),
        )
    elif action == "summarize_invoice":
        state["output"] = summarize_invoice(invoice_text=state.get("data", ""))

    elif action == "report":
        state["output"] = generate_finance_report(
            data=state.get("data", ""),
            report_type=state.get("report_type", "general"),
        )
    elif action == "budget_vs_actual":
        parts  = state.get("data", "|||").split("|||", 1)
        budget = parts[0].strip() if len(parts) > 0 else ""
        actual = parts[1].strip() if len(parts) > 1 else ""
        state["output"] = analyze_budget_vs_actual(budget, actual)

    elif action == "insights_from_docs":
        docs = state.get("data", "")
        doc_list = docs.split("---DOC---") if docs else []
        state["output"] = extract_financial_insights_from_docs(doc_list)

    elif action == "export_documents":
        from tools.finance_document_export import run_finance_document_export

        user_request = (state.get("export_instruction") or state.get("question") or "").strip()
        parts: list[str] = []
        d = (state.get("data") or "").strip()
        c = (state.get("context") or "").strip()
        if d:
            parts.append(d)
        if c and c != d:
            parts.append(c)
        source_data = "\n\n".join(parts)
        fmts = state.get("export_formats")
        fmt_list = fmts if isinstance(fmts, list) else None
        res = run_finance_document_export(
            user_request=user_request or source_data or "Finance export",
            source_data=source_data,
            user_name=state.get("user_name", "User"),
            export_formats=fmt_list,
        )
        state["output"] = res.get("output", "")
        state["export_files"] = res.get("export_files") or []

    else:  # query
        state["output"] = answer_finance_query(
            question=state.get("question", ""),
            context=state.get("context", ""),
            user_name=state.get("user_name", "User"),
        )

    return state


_builder = StateGraph(FinanceState)
_builder.add_node("finance_agent", finance_router)
_builder.set_entry_point("finance_agent")
_builder.add_edge("finance_agent", END)
finance_graph = _builder.compile()
