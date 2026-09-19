"""Step 6 — explain the answer, and explain *nothing* properly.

Everything in `steps` is generated from the plan's bindings and the executor's counts, so the
explanation cannot drift from what was actually computed. The LLM is only used to phrase the
one-line answer, and its output is checked to contain the computed number.
"""
from __future__ import annotations

import re
from typing import Any

from shared import llm
from shared.config import settings

from . import rules
from .executor import ExecResult, breakdown, filter_records
from .planner import Binding, Plan


def _noun(cmap: dict[str, Any], n: int) -> str:
    nouns = cmap.get("record_nouns") or ["record"]
    base = nouns[0]
    return base if n == 1 else (base + "s" if not base.endswith("s") else base)


def _binding_step(b: Binding) -> str:
    s = b.note or f"{b.concept} {b.op} {b.value}"
    if b.evidence:
        s += f" — why this field: {b.evidence}"
    return s


def zero_diagnosis(plan: Plan, result: ExecResult, records: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Explain why nothing matched: which filter kills it, and what the data holds instead."""
    active = [b for b in plan.filters if b.resolved]
    if result.count > 0 or not active:
        return None
    killers = [b for b in active if result.per_filter_counts.get(b.concept, 0) == 0]
    if killers:
        b = killers[0]
        others = [x for x in active if x is not b]
        pool = filter_records(records, others) if others else records
        fld = b.field or ""
        return {
            "kind": "no_such_value",
            "message": f"No record satisfies '{b.note}' at all — not just for this combination.",
            "field": fld,
            "distribution": breakdown(records, fld, plan.alias_maps),
            "pool_size": len(pool),
        }
    # every filter matches something on its own; the combination is empty -> show what the other filters' records look like
    best = None
    for b in active:
        others = [x for x in active if x is not b]
        pool = filter_records(records, others)
        if best is None or len(pool) > best[1]:
            best = (b, len(pool), pool)
    b, n, pool = best
    fld = b.field or ""
    return {
        "kind": "combination_empty",
        "message": f"{n} record(s) match the other filter(s) but none of them satisfies '{b.note}'. Here is how those {n} break down on '{fld}':",
        "field": fld,
        "distribution": breakdown(pool, fld, plan.alias_maps),
        "pool_size": n,
    }


def context_breakdowns(plan: Plan, result: ExecResult, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """For non-zero counts: show the wider picture (e.g. Garima's 21 deals by stage)."""
    out = []
    active = [b for b in plan.filters if b.resolved]
    if len(active) < 2 or result.count == 0:
        return out
    for b in active:
        if b.kind not in ("category", "tags"):
            continue
        others = [x for x in active if x is not b]
        pool = filter_records(records, others)
        flds = sorted(rules.fields_used(b.rule)) if b.rule else [b.field]
        for fld in flds[:2]:
            out.append({"title": f"All {len(pool)} records matching the other filters, by '{fld}'", "distribution": breakdown(pool, fld, plan.alias_maps)})
    return out[:2]


def _fmt(v: Any) -> str:
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, float):
        return f"{v:,.2f}"
    return str(v)


def phrase_answer(question: str, plan: Plan, result: ExecResult, cmap: dict[str, Any], facts: list[str]) -> str:
    """One natural sentence. The number must appear verbatim or we fall back to a template."""
    noun = _noun(cmap, result.count if plan.operation in ("count", "list") else 2)
    corrections = [f"the user wrote '{b.value}', the person is {b.canonical}" for b in plan.filters if b.resolved and b.kind == "person" and b.canonical and str(b.value).strip().lower() not in str(b.canonical).lower()]
    if plan.operation == "count":
        template = f"{result.value} {noun} match."
        must = str(result.value)
    elif plan.operation in ("sum", "avg", "min", "max"):
        template = f"{plan.operation} of {plan.metric_concept} across {result.count} {noun}: {_fmt(result.value)}."
        must = str(result.value)
    elif plan.operation in ("group_count", "group_sum"):
        top = ", ".join(f"{k}: {_fmt(v)}" for k, v in (result.groups or [])[:6])
        template = f"By {plan.group_by.concept if plan.group_by else 'group'} — {top}."
        must = str((result.groups or [["", ""]])[0][1])
    else:
        template = f"{result.count} {noun} match; showing {len(result.matched)}."
        must = str(result.count)
    if not settings.llm_configured:
        return template
    try:
        payload = {
            "question": question, "interpretation": plan.interpretation, "operation": plan.operation,
            "result": result.value if plan.operation != "list" else {"count": result.count, "showing": len(result.matched)},
            "record_noun": noun, "facts": facts[:6], "name_corrections": corrections,
        }
        text = llm.chat(
            [
                {"role": "system", "content": "Write ONE short, natural sentence answering the user's question using EXACTLY the numbers given. "
                                              "Phrase it the way a colleague would (e.g. 'Garima owns 14 open deals.', '3 tickets were abandoned.', 'No deals match.'), using the client's own vocabulary from the facts. If name_corrections is non-empty, use the corrected person name. No preamble, no markdown, no extra numbers."},
                {"role": "user", "content": str(payload)},
            ],
            model=settings.model_fast, reasoning="low", max_tokens=120, step="phrase",
        ).strip().strip('"')
        if must and must not in text.replace(",", "") and _fmt(result.value) not in text:
            return template
        # never echo a misspelling back: swap the user's spelling for the resolved canonical name
        for b in plan.filters:
            if b.resolved and b.kind == "person" and b.canonical and b.value and str(b.value).strip().lower() not in str(b.canonical).lower():
                text = re.sub(re.escape(str(b.value)), b.canonical, text, flags=re.I)
        return text
    except Exception:
        return template


def build_explanation(question: str, plan: Plan, result: ExecResult | None, semantic_map: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    cmap = semantic_map["collections"].get(plan.collection, {})
    steps: list[str] = []
    if plan.interpretation:
        steps.append(f"Understood the question as: {plan.interpretation}")
    desc = cmap.get("description", "")
    steps.append(f"Looked in collection `{plan.collection}`" + (f" — {desc}" if desc else ""))
    for b in plan.filters:
        if b.resolved:
            steps.append(_binding_step(b))
    if plan.group_by and plan.group_by.resolved:
        steps.append(_binding_step(plan.group_by))
    notes = [n for n in cmap.get("notes", []) if any((b.field or "") and b.field in n for b in plan.filters)]
    steps.extend(f"Note: {n}" for n in notes[:2])

    if not plan.executable:
        binding_problems = [f"{b.problem} " + (f"Did you mean: {', '.join(b.suggestions)}?" if b.suggestions else "") for b in plan.unresolved]
        problems = binding_problems or plan.problems
        return {
            "answer_type": "unanswerable",
            "answer": "I can't answer this from the data as it is set up — " + " ".join(p.strip() for p in problems),
            "steps": steps,
            "problems": [p.strip() for p in problems],
            "zero_diagnosis": None,
            "context": [],
            "confidence": 0.0,
        }

    assert result is not None
    noun = _noun(cmap, result.count)
    steps.append(f"Applied the filters to {result.total} records → {result.count} {noun} matched" + (f"; per-filter counts: {result.per_filter_counts}" if len(result.per_filter_counts) > 1 else ""))
    conf = float(plan.confidence) if hasattr(plan, "confidence") else 0.8
    for b in plan.filters:
        conf = min(conf, float(cmap.get("concepts", {}).get(b.concept, {}).get("confidence", 0.8)))

    if result.count == 0:
        zd = zero_diagnosis(plan, result, records)
        answer = f"None — 0 {noun} match. " + (zd["message"] if zd else "")
        return {"answer_type": "empty_with_reason", "answer": answer, "steps": steps, "problems": [], "zero_diagnosis": zd, "context": [], "confidence": round(conf, 2)}

    facts = [b.note for b in plan.filters if b.resolved and b.note]
    answer = phrase_answer(question, plan, result, cmap, facts)
    return {
        "answer_type": "answer",
        "answer": answer,
        "steps": steps,
        "problems": [],
        "zero_diagnosis": None,
        "context": context_breakdowns(plan, result, records),
        "confidence": round(conf, 2),
    }
