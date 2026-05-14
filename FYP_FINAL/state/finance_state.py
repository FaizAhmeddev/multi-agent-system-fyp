from typing import TypedDict, Any, List

class FinanceState(TypedDict, total=False):
    action:      str    # query | analyze_expenses | summarize_invoice | report | budget_vs_actual | export_documents | insights_from_docs
    question:    str
    context:     str
    data:        str
    report_type: str
    user_name:   str
    output:      str
    export_instruction: str
    export_formats: List[str]
    export_files: List[Any]
