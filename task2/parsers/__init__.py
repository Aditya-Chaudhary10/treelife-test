"""Parse once, address forever. Every file becomes a list of small addressable *units*
(paragraph / page / table / row-block) plus an outline; spreadsheets also yield DataFrames.

Unit ids are stable for a given file so that later edits can target them precisely
("replace text in paragraph p12", "set Summary!B4")."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass
class Unit:
    id: str
    kind: str                 # heading | paragraph | table | page | rows | sheet
    text: str
    loc: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedDoc:
    kind: str
    units: list[Unit]
    outline: list[str] = field(default_factory=list)
    tables: dict[str, dict[str, Any]] = field(default_factory=dict)   # sheet -> info (columns, rows, hidden, formulas, sample)
    frames: dict[str, pd.DataFrame] = field(default_factory=dict)     # sheet -> DataFrame (not serialised to JSON)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n".join(u.text for u in self.units)

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "units": [asdict(u) for u in self.units], "outline": self.outline, "tables": self.tables, "meta": self.meta}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ParsedDoc":
        return cls(kind=d["kind"], units=[Unit(**u) for u in d["units"]], outline=d.get("outline", []), tables=d.get("tables", {}), meta=d.get("meta", {}))


def parse_file(path: Path) -> ParsedDoc:
    ext = path.suffix.lower()
    if ext == ".pdf":
        from .pdf import parse_pdf
        return parse_pdf(path)
    if ext == ".docx":
        from .docx import parse_docx
        return parse_docx(path)
    if ext in (".xlsx", ".xlsm"):
        from .xlsx import parse_xlsx
        return parse_xlsx(path)
    if ext == ".csv":
        from .xlsx import parse_csv
        return parse_csv(path)
    from .text import parse_text
    return parse_text(path)
