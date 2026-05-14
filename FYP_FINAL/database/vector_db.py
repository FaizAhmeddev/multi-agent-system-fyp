"""
DATABASE/VECTOR_DB.PY
======================
ChromaDB Vector Database — persistent semantic search for all agents.

Collections:
  - documents   : Google Drive files (PDFs, XLSX, DOCX)
  - hr_cvs      : CV/Resume data for HR agent
  - finance_docs : Finance documents
  - it_knowledge : IT helpdesk tickets & solutions
  - email_corpus : Email templates & history
"""

import os
import sys
import hashlib
import logging

for _lg in ("transformers", "transformers.models", "sentence_transformers", "torch", "huggingface_hub"):
    logging.getLogger(_lg).setLevel(logging.CRITICAL)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _get_client():
    from config import CHROMA_PATH
    os.makedirs(CHROMA_PATH, exist_ok=True)
    import chromadb
    return chromadb.PersistentClient(path=CHROMA_PATH)


def _get_embedding_fn():
    """
    Prefer Chroma's ONNX MiniLM embedding (onnxruntime only).

    SentenceTransformerEmbeddingFunction pulls PyTorch + transformers, which on Windows
    floods the console with optional ``torchvision`` import errors and can crash with
    ``torch.classes`` during Streamlit startup.
    """
    try:
        from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2

        return ONNXMiniLM_L6_V2()
    except Exception:
        try:
            from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2

            return ONNXMiniLM_L6_V2()
        except Exception:
            pass
    try:
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

        return SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
    except Exception:
        return None


def _chunk_text(text: str, chunk_size: int = 800, overlap: int = 100) -> list:
    """Split text into overlapping chunks for embedding."""
    words  = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunk = " ".join(words[i:i + chunk_size])
        chunks.append(chunk)
        i += chunk_size - overlap
    return chunks if chunks else [text]


def _make_id(text: str, prefix: str = "") -> str:
    return prefix + hashlib.md5(text.encode()).hexdigest()[:16]


# ── Public API ────────────────────────────────────────────────────────────────

def embed_documents(docs: list, collection_name: str = "documents") -> dict:
    """
    Embed a list of {"file": name, "content": text} dicts into ChromaDB.
    Returns {"embedded": N, "skipped": M}
    """
    try:
        client   = _get_client()
        emb_fn   = _get_embedding_fn()
        kwargs   = {"name": collection_name}
        if emb_fn:
            kwargs["embedding_function"] = emb_fn
        col = client.get_or_create_collection(**kwargs)

        embedded = 0
        skipped  = 0
        for doc in docs:
            fname   = doc.get("file", "unknown")
            content = doc.get("content", "").strip()
            if not content:
                skipped += 1
                continue
            chunks = _chunk_text(content)
            ids, texts, metas = [], [], []
            for i, chunk in enumerate(chunks):
                doc_id = _make_id(f"{fname}_{i}")
                ids.append(doc_id)
                texts.append(chunk)
                metas.append({"file": fname, "chunk": i, "total_chunks": len(chunks)})

            # Upsert in batches of 50
            batch = 50
            for b in range(0, len(ids), batch):
                col.upsert(
                    ids=ids[b:b+batch],
                    documents=texts[b:b+batch],
                    metadatas=metas[b:b+batch],
                )
            embedded += 1

        return {"embedded": embedded, "skipped": skipped, "collection": collection_name}
    except Exception as e:
        return {"embedded": 0, "skipped": len(docs), "error": str(e)}


def semantic_search(query: str, collection_name: str = "documents",
                    top_k: int = 5) -> list:
    """
    Search ChromaDB collection semantically.
    Returns list of {"text": ..., "file": ..., "score": ...}
    """
    try:
        client = _get_client()
        emb_fn = _get_embedding_fn()
        kwargs = {"name": collection_name}
        if emb_fn:
            kwargs["embedding_function"] = emb_fn
        col = client.get_or_create_collection(**kwargs)

        count = col.count()
        if count == 0:
            return []

        results = col.query(
            query_texts=[query],
            n_results=min(top_k, count),
        )
        hits = []
        for i, doc in enumerate(results["documents"][0]):
            meta  = results["metadatas"][0][i] if results.get("metadatas") else {}
            dist  = results["distances"][0][i]  if results.get("distances")  else 0
            score = round(max(0, 1 - dist) * 100, 1)
            hits.append({
                "text":  doc,
                "file":  meta.get("file", "unknown"),
                "chunk": meta.get("chunk", 0),
                "score": score,
            })
        return hits
    except Exception as e:
        return [{"text": f"Search error: {e}", "file": "error", "score": 0}]


def rag_answer(question: str, collection_name: str = "documents",
               top_k: int = 5, user_name: str = "User") -> str:
    """
    Full RAG pipeline: semantic search → build context → LLM answer.
    Used by Documents Agent and Finance Agent.
    """
    hits = semantic_search(question, collection_name, top_k)
    if not hits or (len(hits) == 1 and "error" in hits[0]["text"].lower()):
        return (
            "No relevant documents found in the knowledge base. "
            "Load documents from Google Drive or upload files, then embed them into ChromaDB."
        )

    context_parts = []
    for h in hits:
        context_parts.append(
            f"[Source: {h['file']} | Relevance: {h['score']}%]\n{h['text']}"
        )
    context = "\n\n---\n\n".join(context_parts)

    try:
        import os as _os
        from langchain_openai import ChatOpenAI
        from config import OPENAI_API_KEY
        _os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1)

        prompt = f"""You are a precise document Q&A assistant for {user_name}.

Question: "{question}"

Relevant document excerpts (retrieved via semantic search):
{context}

Instructions:
- Answer ONLY from the provided document excerpts
- Always cite which file your answer comes from
- If answer not in documents, say "Not found in loaded documents"
- Be specific, accurate, and concise"""

        return llm.invoke(prompt).content
    except Exception as e:
        # Fallback: return top hit text
        return f"**Top match from {hits[0]['file']}:**\n\n{hits[0]['text']}"


def collection_stats() -> dict:
    """Return count of items in each collection."""
    try:
        client = _get_client()
        cols   = client.list_collections()
        return {c.name: c.count() for c in cols}
    except Exception as e:
        return {"error": str(e)}


def clear_collection(collection_name: str) -> bool:
    """Delete all items from a collection."""
    try:
        client = _get_client()
        client.delete_collection(collection_name)
        return True
    except Exception:
        return False


def is_available() -> bool:
    """Check if ChromaDB is installed and working."""
    try:
        import chromadb
        _get_client()
        return True
    except Exception:
        return False
