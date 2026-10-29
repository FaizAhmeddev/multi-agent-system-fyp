"""Documents agent: find, read, summarise and answer questions about company files (Drive).

File text is untrusted. It is wrapped before a model sees it, and in sandbox mode the
summary and answers are extractive (sentences copied from the file, labeled Simulated).
"""
from __future__ import annotations

import re
from typing import Any

from ...agents import ported as P
from ...agents.catalog import DOC_ROLES
from ...agents.untrusted import wrap
from ..base import Agent, AgentError, Ctx, State
from ..cards import Card
from .common import STOP, has_any, quoted, words

DOC_WORDS = ("document", "documents", "doc", "docs", "file", "files", "policy", "policies", "guide", "drive",
             "summarize", "summarise", "summary", "pdf", "handbook", "contract", "folder")
EXTRA_STOP = STOP | {"summarize", "summarise", "summary", "find", "file", "files", "document", "documents", "doc", "show",
                     "search", "read", "open", "what", "does", "say", "about", "tell", "give", "list", "drive", "folder",
                     "please", "from", "our", "company", "how", "many", "much", "do", "we", "get", "are"}


def _intent(t: str) -> str:
    if has_any(t, "summarize", "summarise", "summary of", "sum up", "tl;dr", "key points"):
        return "summarize"
    if has_any(t, "list files", "list the files", "what files", "files in", "show files", "show the files"):
        return "list"
    if has_any(t, "find", "search", "look for", "where is", "which file", "which document"):
        return "search"
    return "ask"


def _query(text: str) -> str:
    q = quoted(text)
    if q:
        return q
    ws = [w for w in re.findall(r"[A-Za-z0-9_\-]+", text) if w.lower() not in EXTRA_STOP and len(w) > 2]
    return " ".join(ws[:4])


def extractive_summary(text: str, max_points: int = 6) -> str:
    lines = [ln.strip(" -*•#\t") for ln in text.splitlines() if ln.strip()]
    title = next((ln for ln in lines if len(ln) < 100), "")
    body = [ln for ln in lines[1:] if len(ln) > 15][:max_points]
    return (f"{title}\n\n" if title else "") + "\n".join(f"- {b}" for b in body)


def extractive_answer(text: str, question: str, max_lines: int = 4) -> list[str]:
    want = words(question) - EXTRA_STOP
    scored = []
    for ln in (x.strip(" -*•#\t") for x in text.splitlines()):
        if len(ln) < 10:
            continue
        n = len(want & words(ln))
        if n:
            scored.append((n, ln))
    scored.sort(key=lambda x: -x[0])
    return [ln for _, ln in scored[:max_lines]]


class DocumentsAgent(Agent):
    name = "documents"
    title = "Documents agent"
    roles = DOC_ROLES
    examples = ("Summarize the leave policy", "Find files about VPN", "What does the expense policy say about meals?",
                "List files in Policies")

    def score(self, text: str) -> float:
        t = text.lower()
        return sum(1.0 for w in DOC_WORDS if re.search(rf"\b{re.escape(w)}\b", t))

    def understand(self, ctx: Ctx, state: State) -> State:
        text = state["text"]
        intent = _intent(text.lower())
        slots: dict[str, Any] = dict(state.get("slots") or {}, intent=intent)
        if intent == "list":
            m = re.search(r"\bfiles in (?:the )?([\w/ \-]+?)(?: folder)?(?:[.?]|$)", text, re.I)
            slots["folder"] = m.group(1).strip() if m else None
            return {"intent": intent, "slots": slots}
        slots["query"] = _query(text)
        if not slots["query"]:
            return {"intent": intent, "slots": slots, "question": "Which document do you mean? Give a title or a topic."}
        return {"intent": intent, "slots": slots}

    def _best(self, ctx: Ctx, query: str) -> dict[str, Any]:
        d = self.read_or_raise(ctx, "drive_search", {"query": query, "page_size": 10})
        if not d["items"] and " " in query:
            for w in sorted(query.split(), key=len, reverse=True):
                d = self.read_or_raise(ctx, "drive_search", {"query": w, "page_size": 10})
                if d["items"]:
                    break
        if not d["items"]:
            raise AgentError(f"No file matches '{query}'.")
        q = words(query)
        return max(d["items"], key=lambda f: len(q & words(f["name"].replace("_", " "))))

    def gather(self, ctx: Ctx, state: State) -> State:
        s, text = state["slots"], state["text"]
        intent = s["intent"]
        if intent == "list":
            d = self.read_or_raise(ctx, "drive_list_files", {"folder": s["folder"], "page_size": 50} if s["folder"]
                                   else {"page_size": 50})
            rows = [{"name": f["name"], "path": f.get("path") or "", "modified": f["modified"], "id": f["id"]}
                    for f in d["items"]]
            return {"cards": [Card(kind="result", agent=self.name, title="Files", body=f"{len(rows)} file(s).",
                                   simulated=d["simulated"], data={"columns": ["name", "path", "modified"], "rows": rows})]}
        if intent == "search":
            d = self.read_or_raise(ctx, "drive_search", {"query": s["query"], "page_size": 20})
            rows = [{"name": f["name"], "path": f.get("path") or "", "modified": f["modified"], "id": f["id"],
                     "link": f.get("web_link") or ""} for f in d["items"]]
            return {"cards": [Card(kind="result", agent=self.name, title=f"Files matching '{s['query']}'",
                                   body=f"{len(rows)} file(s).", simulated=d["simulated"],
                                   data={"columns": ["name", "path", "modified"], "rows": rows})]}
        f = self._best(ctx, s["query"])
        doc = self.read_or_raise(ctx, "drive_read_file", {"file_id": f["id"]})
        w = wrap(doc["text"], source=f"file:{f['id']}")
        warnings = (["This file contains text addressed to an AI assistant. It was treated as data and ignored."]
                    if w.injection_suspected else [])
        if doc.get("truncated"):
            warnings.append("The file is long; only the first part was read.")
        llm = ctx.llm
        live = not getattr(llm, "simulated", True)
        if intent == "summarize":
            if live:
                r = llm.complete(P.doc_summarize_prompt(w.text, f["name"], ctx.user.name), temperature=P.Temperature.DOCS)
                body, sim = r.text, False
            else:
                body, sim = "[Simulated] Extract of the main points (no language model configured):\n" + \
                    extractive_summary(doc["text"]), True
            title = f"Summary of {f['name']}"
        else:
            if live:
                r = llm.complete(f"Answer the question using only the document below. If the document does not "
                                 f"answer it, say so.\n\nQuestion: {text}\n\nDocument '{f['name']}':\n{w.text}",
                                 temperature=P.Temperature.DOCS)
                body, sim = r.text, False
            else:
                lines = extractive_answer(doc["text"], text)
                body = ("[Simulated] Lines from the document that match your question:\n" +
                        "\n".join(f"- {ln}" for ln in lines)) if lines else \
                    "[Simulated] I could not find lines in that document that match your question."
                sim = True
            title = f"From {f['name']}"
        return {"cards": [Card(kind="text", agent=self.name, title=title, body=body, simulated=sim or doc["simulated"],
                               untrusted=True, warnings=warnings,
                               data={"file": {"id": f["id"], "name": f["name"], "link": f.get("web_link") or ""}})]}
