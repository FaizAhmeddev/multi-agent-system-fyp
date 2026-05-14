from langgraph.graph import StateGraph, END
from state.documents_state import DocumentsState
from agents.documents_agent import (
    search_documents, summarize_document, answer_question_from_documents,
    extract_data_from_document, compare_documents,
    batch_analyze_documents, list_documents_summary,
)


def documents_router(state: DocumentsState) -> DocumentsState:
    action       = state.get("action", "qa")
    documents    = state.get("documents", [])
    user_name    = state.get("user_name", "User")
    doc_content  = state.get("document_content", "")

    if action == "search":
        state["output"] = search_documents(
            query=state.get("query", ""),
            documents=documents,
            user_name=user_name,
        )
    elif action == "summarize":
        fn = state.get("file_names", ["Document"])[0] if state.get("file_names") else "Document"
        state["output"] = summarize_document(
            document_content=doc_content,
            file_name=fn,
            user_name=user_name,
        )
    elif action == "extract":
        fn = state.get("file_names", ["Document"])[0] if state.get("file_names") else "Document"
        state["output"] = extract_data_from_document(
            document_content=doc_content,
            extraction_type=state.get("query", "all"),
            file_name=fn,
        )
    elif action == "compare":
        doc1 = documents[0] if len(documents) > 0 else {}
        doc2 = documents[1] if len(documents) > 1 else {}
        state["output"] = compare_documents(
            doc1_content=doc1.get("content", ""),
            doc2_content=doc2.get("content", ""),
            doc1_name=doc1.get("file", "Document 1"),
            doc2_name=doc2.get("file", "Document 2"),
        )
    elif action == "batch_analyze":
        state["output"] = batch_analyze_documents(
            documents=documents,
            analysis_type=state.get("query", "overview"),
        )
    elif action == "list":
        state["output"] = list_documents_summary(documents=documents)
    else:  # qa
        state["output"] = answer_question_from_documents(
            question=state.get("query", ""),
            documents=documents,
            user_name=user_name,
        )

    return state


_builder = StateGraph(DocumentsState)
_builder.add_node("documents_agent", documents_router)
_builder.set_entry_point("documents_agent")
_builder.add_edge("documents_agent", END)
documents_graph = _builder.compile()
