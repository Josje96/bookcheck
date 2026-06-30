"""Extract text from uploaded manuscript files (.txt, .md, .docx, .pdf)."""

from __future__ import annotations

import os
import re


def extract_text(filename: str, data: bytes) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".pdf":
        return _parse_pdf(data)
    if ext == ".docx":
        return _parse_docx(data)
    return data.decode("utf-8", errors="replace")


def _parse_pdf(data: bytes) -> str:
    try:
        import fitz
    except ImportError:
        raise RuntimeError(
            "PDF support requires PyMuPDF. Install it with: "
            "pip install PyMuPDF")
    doc = fitz.open(stream=data, filetype="pdf")
    pages = []
    for page in doc:
        pages.append(page.get_text())
    doc.close()
    text = "\n\n".join(pages)
    return text.strip() or "(PDF appears to contain no extractable text)"


def _parse_docx(data: bytes) -> str:
    try:
        from docx import Document
    except ImportError:
        raise RuntimeError(
            "DOCX support requires python-docx. Install it with: "
            "pip install python-docx")
    import io
    doc = Document(io.BytesIO(data))
    paras = [p.text for p in doc.paragraphs]
    text = "\n\n".join(paras)
    return text.strip() or "(DOCX appears to contain no text)"
