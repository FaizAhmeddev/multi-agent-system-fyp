"""Text extraction for CVs and documents: PDF, Word (.docx), plain text, CSV, Markdown.

Used by the Gmail attachment, Drive and local-folder tools. Everything returned is
untrusted content written by other people.
"""
from __future__ import annotations

import io
import zipfile

MAX_BYTES = 20 * 1024 * 1024
TEXT_TYPES = (".txt", ".md", ".csv", ".json", ".text")
DOC_TYPES = (".pdf", ".docx", *TEXT_TYPES)
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class ExtractError(Exception):
    """A message that is safe to show the user."""


def kind_of(filename: str, mime: str = "") -> str | None:
    name = (filename or "").lower()
    if name.endswith(".pdf") or mime == "application/pdf":
        return "pdf"
    if name.endswith(".docx") or mime == DOCX_MIME:
        return "docx"
    if name.endswith(TEXT_TYPES) or mime.startswith("text/"):
        return "text"
    return None


def pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n".join((p.extract_text() or "") for p in reader.pages[:50])


def docx_text(data: bytes) -> str:
    try:
        from docx import Document
    except ImportError:  # python-docx missing: read the XML directly
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml").decode("utf-8", errors="replace")
        import re

        xml = re.sub(r"</w:p>", "\n", xml)
        return re.sub(r"<[^>]+>", "", xml)
    doc = Document(io.BytesIO(data))
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            parts.append(" | ".join(c.text.strip() for c in row.cells))
    return "\n".join(parts)


def text_of(data: bytes, filename: str, mime: str = "") -> tuple[str, str]:
    """Return (text, how). Raises ExtractError for types AgentsMind cannot read."""
    if len(data) > MAX_BYTES:
        raise ExtractError(f"{filename} is larger than 20 MB.")
    k = kind_of(filename, mime)
    try:
        if k == "pdf":
            return pdf_text(data), "pdf"
        if k == "docx":
            return docx_text(data), "docx"
        if k == "text":
            return data.decode("utf-8", errors="replace"), "text"
    except Exception as exc:  # noqa: BLE001 - corrupt or encrypted files
        raise ExtractError(f"Could not read {filename} ({type(exc).__name__}).") from exc
    raise ExtractError(f"AgentsMind reads PDF, Word (.docx) and text files; {filename} is not one of them.")
