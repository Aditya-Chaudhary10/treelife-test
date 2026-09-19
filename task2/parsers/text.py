"""TXT / Markdown -> paragraph units; markdown headings feed the outline."""
from __future__ import annotations

import re
from pathlib import Path

from . import ParsedDoc, Unit


def parse_text(path: Path) -> ParsedDoc:
    raw = path.read_text(encoding="utf-8", errors="replace")
    units: list[Unit] = []
    outline: list[str] = []
    section = ""
    for i, para in enumerate(re.split(r"\n\s*\n", raw)):
        p = para.strip()
        if not p:
            continue
        m = re.match(r"^#{1,6}\s+(.*)$", p.splitlines()[0])
        if m:
            section = m.group(1).strip()
            outline.append(section)
            units.append(Unit(id=f"p{i}", kind="heading", text=section, loc={"paragraph": i, "section": section}))
            rest = "\n".join(p.splitlines()[1:]).strip()
            if rest:
                units.append(Unit(id=f"p{i}b", kind="paragraph", text=rest, loc={"paragraph": i, "section": section}))
            continue
        units.append(Unit(id=f"p{i}", kind="paragraph", text=p, loc={"paragraph": i, "section": section}))
    return ParsedDoc(kind="text", units=units, outline=outline[:40], meta={"chars": len(raw)})
