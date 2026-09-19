"""Step 4 — bind the concept-level query to THIS client's fields and raw values.

Every binding records *why* it was made (note + evidence) so the final explanation is generated from
facts, not from the model's imagination. Anything that cannot be bound is kept as an unresolved
binding with a reason and suggestions — that is what turns a misleading "0" into an honest answer.
"""
from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any

from rapidfuzz import fuzz, process

from . import rules

# generic vocabulary -> canonical category keys. Small on purpose: the map's own keys come first.
_SYNONYMS = {
    "active": "open", "live": "open", "ongoing": "open", "in play": "open", "in progress": "in_progress", "pending": "open",
    "closed won": "won", "closed-won": "won", "success": "won", "signed": "won",
    "dead": "lost", "closed lost": "lost", "closed-lost": "lost", "abandoned": "lost", "churned": "lost", "cancelled": "lost", "canceled": "lost",
    "completed": "done", "complete": "done", "finished": "done", "resolved": "done", "closed": "done",
    "urgent": "high", "critical": "high", "hot": "high", "top": "high", "p1": "high", "highest": "high",
    "normal": "medium", "p2": "medium",
    "minor": "low", "p3": "low", "lowest": "low", "cold": "low",
}


@dataclass
class Binding:
    concept: str
    op: str
    value: Any
    field: str | None = None
    kind: str = "text"
    raw_values: list[str] | None = None      # category/person: raw values that satisfy the filter
    resolved: bool = False
    note: str = ""                            # human-readable reasoning
    evidence: str = ""                        # from the semantic map
    problem: str | None = None
    suggestions: list[str] = dc_field(default_factory=list)
    canonical: str | None = None              # resolved person / category key
    rule: dict[str, Any] | None = None        # boolean rule evaluated by the executor (see rules.py)

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class Plan:
    collection: str
    operation: str
    filters: list[Binding]
    metric_concept: str | None = None
    metric_field: str | None = None
    group_by: Binding | None = None
    sort: dict[str, Any] | None = None
    limit: int = 20
    interpretation: str = ""
    problems: list[str] = dc_field(default_factory=list)
    alias_maps: dict[str, dict[str, str]] = dc_field(default_factory=dict)  # field -> raw alias -> canonical

    @property
    def unresolved(self) -> list[Binding]:
        return [b for b in self.filters if not b.resolved] + ([self.group_by] if self.group_by and not self.group_by.resolved else [])

    @property
    def executable(self) -> bool:
        return not self.unresolved and not self.problems

    def as_dict(self) -> dict[str, Any]:
        return {
            "collection": self.collection, "operation": self.operation, "metric_concept": self.metric_concept,
            "metric_field": self.metric_field, "filters": [b.as_dict() for b in self.filters],
            "group_by": self.group_by.as_dict() if self.group_by else None, "sort": self.sort, "limit": self.limit,
            "interpretation": self.interpretation, "problems": self.problems, "executable": self.executable,
        }


def _norm(s: Any) -> str:
    return " ".join(str(s).strip().lower().split())


def _find_concept(cmap: dict[str, Any], concept: str) -> tuple[str | None, dict[str, Any] | None]:
    concepts = cmap.get("concepts", {})
    if concept in concepts:
        return concept, concepts[concept]
    # tolerate near-misses like "owners", "deal_owner", "assignee"
    aliases = {"assignee": "owner", "assigned to": "owner", "rep": "owner", "salesperson": "owner", "deal owner": "owner", "lead owner": "owner",
               "value": "amount", "revenue": "amount", "deal value": "amount", "size": "amount", "state": "status", "label": "tags", "labels": "tags",
               "organisation": "company", "organization": "company", "account": "company", "customer": "company", "client": "company",
               "created": "created_at", "creation date": "created_at", "due": "close_date", "due date": "close_date", "deadline": "close_date"}
    c2 = aliases.get(concept)
    if c2 and c2 in concepts:
        return c2, concepts[c2]
    match = process.extractOne(concept, list(concepts.keys()), scorer=fuzz.ratio, score_cutoff=85)
    if match:
        return match[0], concepts[match[0]]
    return None, None


def _resolve_category(spec: dict[str, Any], binding: Binding, top_values: list[str]) -> None:
    vmap: dict[str, Any] = spec.get("value_map") or {}
    wanted = binding.value if isinstance(binding.value, list) else [binding.value]
    parts: list[dict[str, Any]] = []
    keys_used: list[str] = []
    unknown: list[str] = []
    fld = binding.field or ""
    for w in wanted:
        if w is None:
            continue
        key = _norm(w)
        key_alt = _SYNONYMS.get(key, key).replace(" ", "_")
        hit = None
        for cand in (key, key_alt, key.replace(" ", "_")):
            if cand in vmap:
                hit = cand
                break
        if hit is None and vmap:
            m = process.extractOne(key, list(vmap.keys()), scorer=fuzz.ratio, score_cutoff=80)
            hit = m[0] if m else None
        if hit is not None:
            d = vmap[hit]
            parts.append(d if isinstance(d, dict) else {"field": fld, "in": list(d)})
            keys_used.append(hit)
            continue
        # maybe the user named a raw value directly (e.g. a stage name)
        pool = list({v for d in vmap.values() if isinstance(d, list) for v in d} | set(top_values))
        m = process.extractOne(str(w), pool, scorer=fuzz.WRatio, score_cutoff=88)
        if m:
            parts.append({"field": fld, "in": [m[0]]})
            keys_used.append(f'"{m[0]}"')
        else:
            unknown.append(str(w))
    if unknown and not parts:
        binding.problem = f"'{', '.join(unknown)}' is not a known value for {binding.concept} in field '{fld}'."
        binding.suggestions = list(vmap.keys()) or top_values[:8]
        return
    rule: dict[str, Any] = parts[0] if len(parts) == 1 else {"any": parts}
    if binding.op == "neq":
        rule = {"not": rule}
    binding.rule = rule
    binding.raw_values = sorted({v for p in parts for v in p.get("in", [])}) or None
    binding.canonical = ", ".join(keys_used)
    binding.resolved = True
    neg = "NOT " if binding.op == "neq" else ""
    binding.note = f"'{binding.value}' ⇒ {binding.concept} = {binding.canonical} ⇒ {neg}{rules.describe(parts[0] if len(parts) == 1 else {'any': parts})}"
    if unknown:
        binding.note += f" (ignored unknown: {', '.join(unknown)})"


def _resolve_person(binding: Binding, people: list[dict[str, Any]], top_values: list[str]) -> None:
    wanted = binding.value if isinstance(binding.value, list) else [binding.value]
    raw: list[str] = []
    names: list[str] = []
    for w in wanted:
        if w is None:
            continue
        q = _norm(w)
        scored: list[tuple[float, dict[str, Any]]] = []
        for p in people:
            cands = [p["canonical"], *p.get("aliases", [])]
            best = max(fuzz.WRatio(q, _norm(c)) for c in cands)
            first = _norm(p["canonical"]).split()[0] if p["canonical"] else ""
            if first and (q == first or fuzz.ratio(q, first) >= 88):
                best = max(best, 96)
            scored.append((best, p))
        scored.sort(key=lambda t: -t[0])
        if scored and scored[0][0] >= 85:
            top, p = scored[0]
            if len(scored) > 1 and scored[1][0] >= 85 and scored[1][0] >= top - 3 and scored[1][1]["canonical"] != p["canonical"]:
                binding.problem = f"'{w}' is ambiguous: could be {p['canonical']} or {scored[1][1]['canonical']}."
                binding.suggestions = [p["canonical"], scored[1][1]["canonical"]]
                return
            raw.extend(p.get("aliases", []))
            names.append(p["canonical"])
            continue
        # fallback: substring over raw values of the field
        subs = [v for v in top_values if q and q in _norm(v)]
        if subs:
            raw.extend(subs)
            names.append(str(w))
            continue
        near = [p["canonical"] for s, p in scored[:3] if s >= 60]
        binding.problem = f"No one matching '{w}' appears in field '{binding.field}'."
        binding.suggestions = near or [p["canonical"] for p in people[:5]]
        return
    binding.raw_values = list(dict.fromkeys(raw))
    binding.rule = {"field": binding.field, "in": binding.raw_values}
    if binding.op == "neq":
        binding.rule = {"not": binding.rule}
    binding.canonical = ", ".join(names)
    binding.resolved = True
    spellings = ", ".join(f'"{r}"' for r in binding.raw_values[:8]) + (" …" if len(binding.raw_values) > 8 else "")
    corrected = "" if _norm(binding.value) in (_norm(n) for n in names) or any(_norm(binding.value) == _norm(n).split()[0] for n in names) else f" (interpreted '{binding.value}' as {binding.canonical})"
    neg = "NOT " if binding.op == "neq" else ""
    binding.note = f"{neg}{binding.concept} = {binding.canonical}{corrected}, matched via spellings {spellings} in '{binding.field}'"


def build_plan(ir: dict[str, Any], semantic_map: dict[str, Any], profiles: dict[str, Any]) -> Plan:
    cname = ir["collection"]
    cmap = semantic_map["collections"].get(cname, {})
    people_all = semantic_map.get("people", {})
    fields_profile = {f["name"]: f for f in profiles.get(cname, {}).get("fields", [])}

    plan = Plan(collection=cname, operation=ir["operation"], filters=[], metric_concept=ir.get("metric_concept"),
                sort=ir.get("sort"), limit=int(ir.get("limit") or 20), interpretation=ir.get("interpretation", ""))
    if ir.get("unsupported"):
        plan.problems.append(str(ir["unsupported"]))

    def bind(concept: str, op: str, value: Any) -> Binding:
        b = Binding(concept=concept, op=op, value=value)
        name, spec = _find_concept(cmap, concept)
        if not spec:
            missing = cmap.get("missing_concepts") or {}
            why = missing.get(concept) or next((v for k, v in missing.items() if fuzz.ratio(k, concept) > 80), None)
            b.problem = f"This data does not track '{concept}' anywhere." + (f" {why}" if why else "")
            # last resort: a field literally named like the concept
            m = process.extractOne(concept, list(fields_profile.keys()), scorer=fuzz.partial_ratio, score_cutoff=92)
            if m:
                b.suggestions = [f"closest field: '{m[0]}' (not mapped to a concept — ask about it explicitly)"]
            return b
        b.concept = name or concept
        b.field = spec["field"]
        b.kind = spec.get("kind", "text")
        b.evidence = spec.get("evidence", "")
        top_values = [str(v) for v, _ in fields_profile.get(b.field, {}).get("top_values", [])]
        if op in ("is_empty", "not_empty"):
            b.resolved = True
            b.note = f"{b.concept} {'is empty' if op == 'is_empty' else 'is filled'} in field '{b.field}'"
            return b
        if b.kind == "person":
            _resolve_person(b, people_all.get(f"{cname}.{b.field}", []), top_values)
        elif b.kind in ("category", "tags"):
            _resolve_category(spec, b, top_values)
        elif b.kind in ("number", "date"):
            b.resolved = value is not None
            b.note = f"{b.concept} {op} {value} on field '{b.field}'"
            if not b.resolved:
                b.problem = f"No value given for {b.concept}"
        else:
            b.resolved = value is not None
            b.op = "contains" if op == "eq" else op
            b.note = f"{b.concept} {b.op} '{value}' on field '{b.field}'"
        return b

    for f in ir.get("filters", []):
        plan.filters.append(bind(f["concept"], f.get("op", "eq"), f.get("value")))

    if plan.metric_concept:
        name, spec = _find_concept(cmap, plan.metric_concept)
        if spec:
            plan.metric_field = spec["field"]
        else:
            plan.problems.append(f"No numeric field holds '{plan.metric_concept}' in {cname}.")
    elif plan.operation in ("sum", "avg", "min", "max", "group_sum"):
        name, spec = _find_concept(cmap, "amount")
        if spec:
            plan.metric_concept, plan.metric_field = "amount", spec["field"]
        else:
            plan.problems.append(f"'{plan.operation}' needs a numeric concept and none was given.")

    if ir.get("group_by"):
        gb = Binding(concept=ir["group_by"], op="group", value=None)
        name, spec = _find_concept(cmap, ir["group_by"])
        if spec:
            gb.field, gb.kind, gb.resolved = spec["field"], spec.get("kind", "text"), True
            gb.evidence = spec.get("evidence", "")
            gb.note = f"grouped by {name} = field '{gb.field}'"
        else:
            gb.problem = f"Cannot group by '{ir['group_by']}' — not tracked in this data."
        plan.group_by = gb

    # alias maps let the executor print canonical people names in groups
    for key, plist in people_all.items():
        col, fld = key.split(".", 1)
        if col == cname:
            plan.alias_maps[fld] = {_norm(a): p["canonical"] for p in plist for a in p.get("aliases", [])}
    return plan
