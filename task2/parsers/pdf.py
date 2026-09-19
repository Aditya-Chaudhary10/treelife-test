"""PDF -> page units (PyMuPDF). Long pages are split into ~1800-char blocks so a chunk never
mixes unrelated sections; headings are guessed from short bold-ish lines for the outline."""
from __future__ import annotations

import re
from pathlib import Path

try:
    import pymupdf as fitz  # PyMuPDF >= 1.24
except ImportError:  # pragma: no cover
    import fitz

from . import ParsedDoc, Unit

_HEADING = re.compile(r"^(?:\d+(?:\.\d+)*\s+)?[A-Z][A-Za-z0-9 ,&/\-]{3,60}$")


def parse_pdf(path: Path) -> ParsedDoc:
    doc = fitz.open(str(path))
    units: list[Unit] = []
    outline: list[str] = []
    for pno, page in enumerate(doc, start=1):
        text = page.get_text("text").strip()
        if not text:
            continue
        for line in text.splitlines()[:40]:
            line = line.strip()
            if _HEADING.match(line) and len(outline) < 40 and line not in outline:
                outline.append(line)
        blocks = _split(text, 1200)
        for bi, block in enumerate(blocks):
            uid = f"pg{pno}" if len(blocks) == 1 else f"pg{pno}.{bi + 1}"
            units.append(Unit(id=uid, kind="page", text=block, loc={"page": pno, "block": bi + 1}))
    toc = [t[1] for t in doc.get_toc()] if doc.get_toc() else []
    if toc:
        outline = toc[:40]
    return ParsedDoc(kind="pdf", units=units, outline=outline, meta={"pages": doc.page_count})


def _split(text: str, size: int) -> list[str]:
    if len(text) <= size:
        return [text]
    paras = re.split(r"\n\s*\n", text)
    if len(paras) <= 2:  # PDFs rarely carry blank lines between paragraphs; fall back to numbered/heading lines
        paras = re.split(r"\n(?=(?:\d+(?:\.\d+)*[.)]?\s+[A-Z])|(?:[A-Z][A-Za-z &/-]{2,40}$))", text, flags=re.M)
    out: list[str] = []
    cur = ""
    for p in paras:
        if len(cur) + len(p) + 2 > size and cur:
            out.append(cur.strip())
            cur = ""
        cur += p + "\n\n"
    if cur.strip():
        out.append(cur.strip())
    return out
