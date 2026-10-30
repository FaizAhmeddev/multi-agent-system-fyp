"""Files attached to an assistant message (paperclip in the chat).

Stored on this computer under data/chat_uploads/u<user id>/, one folder per file with the original
file and a meta.json (name, size, extracted text length). The extracted text is untrusted data: agents
wrap it before a model sees it. Only the user who uploaded a file can use or download it.
Generated outputs (for example a summary exported as PDF) are stored the same way with kind "output".
"""
from __future__ import annotations

import io
import json
import re
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..settings import REPO_ROOT

MAX_BYTES = 15 * 1024 * 1024
MAX_TEXT = 200_000
ALLOWED = (".pdf", ".docx", ".xlsx", ".xlsm", ".csv", ".txt", ".md", ".json", ".tsv", ".log")


class AttachmentError(ValueError):
    pass


def root() -> Path:
    import os

    base = Path(os.environ.get("WORKSPACE_DATA_DIR") or REPO_ROOT / "data")
    return base / "chat_uploads"


def _user_dir(user_id: int) -> Path:
    return root() / f"u{int(user_id)}"


def _safe_name(name: str) -> str:
    n = re.sub(r"[^\w.\- ()]+", "_", Path(name or "file").name).strip(" .") or "file"
    return n[:120]


def extract_text(name: str, data: bytes) -> str:
    low = name.lower()
    if low.endswith(".pdf"):
        from pypdf import PdfReader

        try:
            r = PdfReader(io.BytesIO(data))
            text = "\n".join((p.extract_text() or "") for p in r.pages[:200])
        except Exception as exc:  # noqa: BLE001 - damaged or encrypted PDF
            raise AttachmentError(f"The PDF could not be read ({type(exc).__name__}).") from exc
        if not text.strip():
            raise AttachmentError("The PDF has no text layer (a scan). Attach a text PDF or a Word file.")
        return text
    if low.endswith(".docx"):
        import docx

        d = docx.Document(io.BytesIO(data))
        parts = [p.text for p in d.paragraphs]
        for t in d.tables:
            for row in t.rows:
                parts.append("\t".join(c.text.strip() for c in row.cells))
        return "\n".join(parts)
    if low.endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        out = []
        for ws in wb.worksheets[:10]:
            out.append(f"# Sheet: {ws.title}")
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i >= 2000:
                    out.append("(more rows not shown)")
                    break
                if any(v is not None and str(v).strip() for v in row):
                    out.append("\t".join("" if v is None else str(v) for v in row))
        return "\n".join(out)
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def save(user_id: int, filename: str, data: bytes, *, kind: str = "upload") -> dict[str, Any]:
    name = _safe_name(filename)
    if not name.lower().endswith(ALLOWED):
        raise AttachmentError("Attach a PDF, Word (.docx), Excel (.xlsx), CSV or text file.")
    if not data:
        raise AttachmentError("The file is empty.")
    if len(data) > MAX_BYTES:
        raise AttachmentError("The file is larger than 15 MB.")
    text = extract_text(name, data)[:MAX_TEXT]
    aid = secrets.token_hex(8)
    d = _user_dir(user_id) / aid
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_bytes(data)
    meta = {"id": aid, "name": name, "size": len(data), "chars": len(text), "kind": kind,
            "created_at": datetime.now(UTC).isoformat(timespec="seconds")}
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (d / "text.txt").write_text(text, encoding="utf-8")
    return meta


def load(user_id: int, aid: str) -> dict[str, Any] | None:
    if not re.fullmatch(r"[0-9a-f]{16}", aid or ""):
        return None
    d = _user_dir(user_id) / aid
    try:
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        text = (d / "text.txt").read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None
    return {**meta, "path": str((d / meta["name"]).resolve()), "text": text}


def load_many(user_id: int, ids: list[str]) -> list[dict[str, Any]]:
    out = []
    for i in ids[:5]:
        a = load(user_id, i)
        if a is not None:
            out.append(a)
    return out


def save_pdf(user_id: int, title: str, body: str) -> dict[str, Any]:
    """A generated PDF (e.g. 'export it as PDF'), kept like an attachment so it can be downloaded or emailed."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title=title[:120], leftMargin=50, rightMargin=50, topMargin=50,
                            bottomMargin=50)
    st = getSampleStyleSheet()
    def esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    flow = [Paragraph(esc(title), st["Title"]), Spacer(1, 8)]
    for para in re.split(r"\n\s*\n", body.strip()):
        lines = [esc(x) for x in para.splitlines()]
        flow.append(Paragraph("<br/>".join(lines), st["BodyText"]))
        flow.append(Spacer(1, 6))
    doc.build(flow)
    fname = _safe_name(re.sub(r"\s+", " ", title)[:60]) + ".pdf"
    return save(user_id, fname, buf.getvalue(), kind="output")
