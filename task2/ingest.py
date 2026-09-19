"""Ingest = parse once + index once + one cheap summary line. After this, no step ever re-reads a
file from scratch: questions use the index, spreadsheets use the stored DataFrames, edits use unit ids."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from shared import llm
from shared.config import settings
from shared.llm import approx_tokens

from .index import Index
from .parsers import ParsedDoc, parse_file
from .workspace import FileRecord, Workspace

SUMMARY_INPUT_TOKENS = 900  # keep per-file summary calls tiny: 50 files ≈ 50k tokens once, ever


def heuristic_summary(rec: FileRecord, parsed: ParsedDoc) -> str:
    if parsed.kind in ("xlsx", "csv"):
        parts = [f"{name}: {info['rows']} rows, cols {', '.join(info['columns'][:6])}" for name, info in list(parsed.tables.items())[:4]]
        return "Spreadsheet — " + "; ".join(parts)
    head = " ".join(parsed.text.split()[:40])
    return (("Sections: " + "; ".join(parsed.outline[:5]) + ". ") if parsed.outline else "") + head


def llm_summary(rec: FileRecord, parsed: ParsedDoc) -> str:
    excerpt = llm.truncate_to_budget(parsed.text, SUMMARY_INPUT_TOKENS)
    outline = "; ".join(parsed.outline[:12])
    prompt = (
        f"File: {rec.name}\nOutline: {outline or '(none)'}\nExcerpt:\n{excerpt}\n\n"
        "In ONE sentence (max 35 words) say what this document is and name its key parties, amounts, dates or subjects. "
        "This line is used to decide which files are relevant to a question, so be specific. No preamble."
    )
    text = llm.chat([{"role": "user", "content": prompt}], model=settings.model_fast, reasoning="low", max_tokens=90, step="ingest:summary")
    return text.strip().strip('"')[:300]


def ingest_file(ws: Workspace, rec: FileRecord, index: Index, summarize: bool = True) -> FileRecord:
    path = ws.file_path(rec.id)
    try:
        parsed = parse_file(path)
    except Exception as e:  # keep the workspace usable even if one file is broken
        rec.status, rec.error = "error", f"{type(e).__name__}: {e}"[:300]
        ws.save()
        return rec
    fdir = ws.file_dir(rec.id)
    ws.parsed_path(rec.id).write_text(json.dumps(parsed.as_dict(), ensure_ascii=False), encoding="utf-8")
    if parsed.frames:
        tdir = fdir / "tables"
        tdir.mkdir(exist_ok=True)
        for sheet, df in parsed.frames.items():
            df.to_pickle(tdir / f"{_safe(sheet)}.pkl")
    rec.kind = parsed.kind
    rec.pages = int(parsed.meta.get("pages", 0) or 0)
    rec.sheets = list(parsed.meta.get("sheets", []))
    rec.hidden_sheets = list(parsed.meta.get("hidden_sheets", []))
    rec.outline = parsed.outline[:20]
    rec.tokens_estimate = approx_tokens(parsed.text)
    rec.chunks = index.add_file(rec.id, rec.name, parsed)
    summary = ""
    if summarize and settings.llm_configured:
        try:
            summary = llm_summary(rec, parsed)
        except Exception:
            summary = ""
    rec.summary = summary or heuristic_summary(rec, parsed)
    rec.status, rec.error = "indexed", None
    ws.save()
    return rec


def load_parsed(ws: Workspace, file_id: str) -> ParsedDoc:
    return ParsedDoc.from_dict(json.loads(ws.parsed_path(file_id).read_text(encoding="utf-8")))


def load_frames(ws: Workspace, file_id: str) -> dict[str, pd.DataFrame]:
    tdir = ws.file_dir(file_id) / "tables"
    if not tdir.exists():
        return {}
    parsed = load_parsed(ws, file_id)
    out = {}
    for sheet in parsed.tables:
        p = tdir / f"{_safe(sheet)}.pkl"
        if p.exists():
            out[sheet] = pd.read_pickle(p)
    return out


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:60] or "sheet"
