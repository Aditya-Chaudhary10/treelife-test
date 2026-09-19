"""Step 3 — understand what the person means. The question is translated into a small query IR
expressed in CONCEPTS (owner, status, priority...) — never in field names. That keeps the
question-understanding step identical across clients; only the binding (planner.py) is client-specific.
"""
from __future__ import annotations

from typing import Any

from shared import llm
from shared.config import settings

_SYSTEM = """You convert a plain-English business question into a structured query over a client's data.

You are given the client's collections and the CONCEPTS each supports (with allowed values for category concepts and known people for person concepts).
Express the question with those concepts. Never use field names. Do not guess numbers.

Output ONLY JSON:
{
 "collection": "<one of the collections>",
 "operation": "count | list | sum | avg | min | max | group_count | group_sum",
 "metric_concept": "<concept for sum/avg/min/max/group_sum, else null>",
 "filters": [ {"concept": "<concept>", "op": "eq|neq|in|contains|gt|gte|lt|lte|between|is_empty|not_empty", "value": <string | number | [list] | null>} ],
 "group_by": "<concept or null>",
 "sort": {"concept": "<concept>", "dir": "asc|desc"} | null,
 "limit": <int, default 20>,
 "interpretation": "<one sentence restating the question using the concepts>",
 "confidence": <0.0-1.0>,
 "unsupported": null | "<why the question cannot be expressed as a query over this data>"
}

Rules:
- For category concepts use the allowed canonical values exactly (e.g. "open", not "active" or "still in play").
- For person concepts put the name as the user wrote it; the system resolves spelling.
- Dates: convert relative phrases using TODAY into ISO dates; use "between" with [start, end] for ranges, "gte"/"lt" for open ranges.
- If the user asks about a concept that is not listed, still emit it with a descriptive concept name (e.g. "region"); the system will explain that it is missing.
- "how many" -> count; "which/list/show" -> list; "total value/revenue" -> sum of amount; "per owner/by stage" -> group_count or group_sum.
- Pick the collection whose record_nouns match what the user is counting (deals vs leads/persons vs organizations vs issues)."""


def describe_capabilities(semantic_map: dict[str, Any]) -> str:
    lines = []
    people = semantic_map.get("people", {})
    for cname, cmap in semantic_map.get("collections", {}).items():
        lines.append(f"collection `{cname}`: {cmap.get('description','')}")
        lines.append(f"  record_nouns: {', '.join(cmap.get('record_nouns', []))}")
        for concept, spec in cmap.get("concepts", {}).items():
            kind = spec.get("kind", "text")
            extra = ""
            if kind == "category" and spec.get("value_map"):
                extra = " allowed values: " + ", ".join(spec["value_map"].keys())
            elif kind == "person":
                names = [p["canonical"] for p in people.get(f"{cname}.{spec['field']}", [])][:25]
                if names:
                    extra = " known people: " + ", ".join(names)
            lines.append(f"  - {concept} ({kind}){extra}")
        missing = cmap.get("missing_concepts") or {}
        if missing:
            lines.append("  not tracked here: " + ", ".join(missing.keys()))
    return "\n".join(lines)


def parse_intent(question: str, semantic_map: dict[str, Any], today: str) -> dict[str, Any]:
    caps = describe_capabilities(semantic_map)
    user = f"TODAY: {today}\n\nCLIENT DATA CAPABILITIES:\n{caps}\n\nQUESTION: {question}"
    ir = llm.chat_json(
        [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
        model=settings.model_strong, reasoning="low", max_tokens=800, step="intent",
    )
    # normalise
    cols = list(semantic_map.get("collections", {}).keys())
    if ir.get("collection") not in cols and cols:
        ir["collection"] = cols[0]
    ir["operation"] = str(ir.get("operation") or "count").lower()
    ir["filters"] = [f for f in (ir.get("filters") or []) if isinstance(f, dict) and f.get("concept")]
    for f in ir["filters"]:
        f["op"] = str(f.get("op") or "eq").lower()
        f["concept"] = str(f["concept"]).strip().lower()
    ir.setdefault("limit", 20)
    ir.setdefault("interpretation", "")
    ir.setdefault("confidence", 0.7)
    ir.setdefault("unsupported", None)
    if ir.get("group_by"):
        ir["group_by"] = str(ir["group_by"]).strip().lower()
    if ir.get("metric_concept"):
        ir["metric_concept"] = str(ir["metric_concept"]).strip().lower()
    return ir
