"""Focused answering: the model sees only the retrieved passages (budgeted), must cite them,
and must say when the passages don't contain the answer."""
from __future__ import annotations

from typing import Any

from shared import llm
from shared.config import settings
from shared.llm import approx_tokens

_SYSTEM = """You answer questions about business documents using ONLY the numbered sources provided.
- Cite every fact with its source tag like [S2]. Quote exact figures, dates and clause wording where relevant.
- If the sources do not contain the answer, say exactly what is missing instead of guessing.
- When sources disagree, point out the disagreement with both citations.
- Be concise and concrete. Markdown is fine (short bullets, no headings)."""


def pack_sources(chunks: list[dict[str, Any]], budget_tokens: int) -> tuple[str, list[dict[str, Any]]]:
    """Number the chunks and drop the tail that doesn't fit the budget."""
    used: list[dict[str, Any]] = []
    parts: list[str] = []
    total = 0
    for c in chunks:
        t = c.get("n_tokens") or approx_tokens(c["text"])
        if total + t > budget_tokens and used:
            break
        tag = f"S{len(used) + 1}"
        loc = _loc(c.get("loc") or {})
        parts.append(f"[{tag}] {c['file_name']}{loc}\n{c['text']}")
        used.append({"tag": tag, "file_id": c["file_id"], "file_name": c["file_name"], "loc": c.get("loc") or {}, "chunk_id": c.get("id"), "n_tokens": t})
        total += t
    return "\n\n".join(parts), used


def _loc(loc: dict[str, Any]) -> str:
    if "page" in loc:
        return f" (page {loc['page']})"
    if "sheet" in loc and "rows" in loc:
        return f" (sheet {loc['sheet']}, rows {loc['rows'][0]}-{loc['rows'][1]})"
    if "sheet" in loc:
        return f" (sheet {loc['sheet']})"
    if "paragraph" in loc:
        sec = loc.get("section")
        return f" (¶{loc['paragraph']}{', ' + sec if sec else ''})"
    if "table" in loc:
        return f" (table {loc['table']})"
    return ""


def answer(question: str, chunks: list[dict[str, Any]], memory: str = "", extra_context: str = "") -> dict[str, Any]:
    budget = settings.context_budget - 700 - approx_tokens(extra_context)
    sources, used = pack_sources(chunks, max(budget, 800))
    user = ""
    if memory:
        user += f"CONVERSATION SO FAR (for reference resolution only):\n{memory}\n\n"
    if extra_context:
        user += f"COMPUTED DATA:\n{extra_context}\n\n"
    user += f"SOURCES:\n{sources or '(no passages found)'}\n\nQUESTION: {question}"
    text = llm.chat([{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
                    model=settings.model_strong, reasoning="low", max_tokens=900, step="answer")
    cited = [u for u in used if f"[{u['tag']}]" in text or f"{u['tag']}]" in text]
    return {"answer": text, "sources": used, "cited": cited or used[:3], "context_tokens": sum(u["n_tokens"] for u in used)}
