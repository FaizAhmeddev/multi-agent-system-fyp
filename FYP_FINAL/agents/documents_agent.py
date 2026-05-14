"""
AGENTS/DOCUMENTS_AGENT.PY
==========================
Documents Agent — uses ChromaDB RAG for accurate Q&A.
Falls back to direct LLM if ChromaDB empty.
"""
import os

def _get_llm():
    from langchain_openai import ChatOpenAI
    from config import OPENAI_API_KEY
    os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY
    return ChatOpenAI(model="gpt-4o-mini", temperature=0.1)

def search_documents(query, documents, user_name="User"):
    try:
        from database.vector_db import semantic_search
        hits = semantic_search(query, collection_name="documents", top_k=5)
        if hits and hits[0].get("score", 0) > 20:
            parts = [f"**[{h['file']}]** (relevance {h['score']}%)\n{h['text']}" for h in hits]
            context = "\n\n---\n\n".join(parts)
            llm = _get_llm()
            resp = llm.invoke(f'Search results for "{query}":\n\n{context}\n\nSummarize the most relevant results clearly, citing file names.')
            return resp.content
    except Exception:
        pass
    # Fallback to direct search
    if not documents:
        return "📂 No documents loaded. Please load from Google Drive first."
    llm = _get_llm()
    context = "\n\n".join([f"[{d.get('file','')}]: {d.get('content','')[:600]}" for d in documents[:10]])
    resp = llm.invoke(f'Search for: "{query}"\n\nDocuments:\n{context}\n\nFind and cite relevant results.')
    return resp.content

def summarize_document(document_content, file_name="Document", user_name="User"):
    if not document_content or len(document_content.strip()) < 30:
        return f"📄 '{file_name}' is empty or too short to summarize."
    try:
        llm = _get_llm()
        resp = llm.invoke(f"""Summarize "{file_name}" for {user_name}:

{document_content[:4000]}

Format:
**Type:** (Contract/Report/Policy/Invoice/Other)
**Summary:** (3-4 sentences)
**Key Points:** (5-7 bullets)
**Important Dates/Figures:** (if any)
**Action Items:** (if any)""")
        result = resp.content
        try:
            from database.sqlite_db import log_agent
            log_agent("Documents Agent", "summarize", file_name, result[:500])
        except Exception:
            pass
        return result
    except Exception as e:
        return f"❌ Summary error: {e}"

def answer_question_from_documents(question, documents, user_name="User"):
    # Try ChromaDB RAG first
    try:
        from database.vector_db import rag_answer, collection_stats
        stats = collection_stats()
        if stats.get("documents", 0) > 0:
            answer = rag_answer(question, collection_name="documents", top_k=5, user_name=user_name)
            try:
                from database.sqlite_db import log_agent
                log_agent("Documents Agent", "rag_qa", question, answer[:500])
            except Exception:
                pass
            return answer
    except Exception:
        pass

    # Fallback to direct LLM with loaded docs
    if not documents:
        return "📂 No documents loaded. Load from Google Drive first."
    llm = _get_llm()
    context = "\n\n".join([f"[{d.get('file','')}]: {d.get('content','')[:800]}" for d in documents[:12]])
    resp = llm.invoke(f'Question: "{question}"\n\nDocuments:\n{context}\n\nAnswer from documents only. Cite file names.')
    return resp.content

def extract_data_from_document(document_content, extraction_type="all", file_name="Document"):
    if not document_content:
        return "📄 No document content provided."
    try:
        llm = _get_llm()
        tasks = {
            "dates":    "Extract ALL dates and deadlines.",
            "amounts":  "Extract ALL monetary amounts and figures.",
            "parties":  "Extract ALL parties, people, companies with their roles.",
            "clauses":  "Extract KEY clauses, terms, conditions.",
            "contacts": "Extract ALL contact information.",
            "all":      "Extract: dates, amounts, parties, key terms, contacts, action items.",
        }
        resp = llm.invoke(f'File: {file_name}\nTask: {tasks.get(extraction_type, tasks["all"])}\n\n{document_content[:3500]}\n\nPresent in clean organized format.')
        return resp.content
    except Exception as e:
        return f"❌ Extraction error: {e}"

def compare_documents(doc1_content, doc2_content, doc1_name="Doc 1", doc2_name="Doc 2"):
    if not doc1_content or not doc2_content:
        return "📄 Select two documents to compare."
    try:
        llm = _get_llm()
        resp = llm.invoke(f"""Compare these two documents:

**{doc1_name}:**
{doc1_content[:2000]}

**{doc2_name}:**
{doc2_content[:2000]}

Provide:
- Comparison table (Key attributes | {doc1_name} | {doc2_name})
- Similarities
- Key differences
- Recommendation""")
        return resp.content
    except Exception as e:
        return f"❌ Comparison error: {e}"

def batch_analyze_documents(documents, analysis_type="overview"):
    if not documents:
        return "📂 No documents loaded."
    try:
        llm = _get_llm()
        tasks = {
            "overview":   "Catalog and quality overview",
            "financial":  "Extract all financial data, amounts, budgets",
            "contracts":  "Analyze contract terms, parties, obligations, risks",
            "policies":   "Summarize key policies, rules, compliance requirements",
            "compliance": "Check for compliance issues, missing signatures, expired dates",
        }
        summaries = "\n\n---\n\n".join([f"**{d.get('file','')}:**\n{d.get('content','')[:500]}" for d in documents[:10]])
        resp = llm.invoke(f"Task: {tasks.get(analysis_type,'overview')}\n\n{len(documents)} Documents:\n{summaries}\n\nProvide comprehensive batch analysis with key findings and recommendations.")
        return resp.content
    except Exception as e:
        return f"❌ Batch analysis error: {e}"

def list_documents_summary(documents):
    if not documents:
        return "📂 No documents loaded. Load from Google Drive."
    lines = [f"📂 **{len(documents)} Documents Loaded:**\n"]
    for i, doc in enumerate(documents, 1):
        name    = doc.get("file", "Unknown")
        content = doc.get("content", "")
        words   = len(content.split())
        preview = content[:80].replace("\n", " ") + "..." if len(content) > 80 else content
        lines.append(f"**{i}. {name}** — ~{words} words\n_{preview}_\n")
    return "\n".join(lines)
