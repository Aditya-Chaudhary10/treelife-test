"""Step 2 — build the client's Semantic Map: where each business concept *really* lives.

Input : the statistical profile (discovery.py) — never raw records, so it is cheap and private.
Output: per collection, concept -> {field, kind, confidence, evidence, value_map}. Concepts are open
        (the model adds whatever the data supports) but a few canonical ones are suggested so that
        every client's map speaks the same language ("owner", "status", "priority", ...).

People fields additionally get an alias table (typos, nicknames, initials) built by a deterministic
clustering pass and then refined by a small LLM call. The map is cached per schema fingerprint.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from typing import Any

from rapidfuzz import fuzz
from rapidfuzz.distance import DamerauLevenshtein

from shared import llm
from shared.config import settings

from .adapters.base import Collection
from .discovery import CollectionProfile, profiles_to_text

CANONICAL_CONCEPTS = {
    "owner": "person responsible for the record (owner / rep / assignee)",
    "status": "lifecycle state, e.g. open / won / lost, todo / in_progress / done / abandoned",
    "stage": "pipeline stage or workflow step (finer than status)",
    "priority": "urgency or importance",
    "amount": "monetary value",
    "created_at": "when the record was created",
    "updated_at": "last modified time",
    "close_date": "expected or actual close / due / resolution date",
    "company": "organisation / account the record belongs to",
    "contact": "person at the customer side",
    "title": "the record's name or summary",
    "tags": "free-form labels",
    "source": "where the lead/record came from",
    "type": "record type / category",
}

_SYSTEM = """You are a data analyst who reverse-engineers how a company actually uses its business tool.
You receive a statistical profile of their data (per collection: fields, fill rates, distinct values, signals).
Your job: for each collection, decide where each business CONCEPT really lives, using EVIDENCE from the profile.

Rules that matter:
- A field with signal CONSTANT (one value everywhere) carries no information. Do not map a concept to it; look for a custom field that holds the real thing.
- Declared options that are NEVER USED are a strong hint the team encodes that concept elsewhere (e.g. a 'Dead Leads' stage instead of status=lost).
- Hand-typed fields show 'inconsistent_spelling' — they are often the real owner/assignee.
- Priority / category may hide in tags, labels, stage names or title prefixes.
- Prefer the field that discriminates records (high fill, several distinct values) over the "official" one.
- If a concept is genuinely not tracked anywhere, say so in missing_concepts with the reason (this is important — we must never invent data).
- For kind=category concepts provide value_map: canonical lowercase keys -> definition. A definition is EITHER a list of RAW values of the concept's own field (exactly as they appear), OR — when one field alone cannot express the state — a rule over several fields:
    {"all": [ {"field": "status", "in": ["Open"]}, {"field": "stage", "not_in": ["Dead Leads"]} ]}   or   {"any": [ ... ]}
  Conditions support "in", "not_in", "is_empty": true, "not_empty": true. Rules may nest.
  Cover EVERY raw value that encodes the concept, including slang/emoji ("hot 🔥", "asap" -> high). Use keys like open/won/lost (sales), todo/in_progress/done/abandoned (work), high/medium/low (priority).
- Lifecycle trap: if an option like "Lost" is declared but NEVER USED, the team is parking those records somewhere else — a stage/folder/tag named like "Dead Leads", "Graveyard", "Parked", "Archive", "Won't Do". Fold that into the status value_map with a rule, and make "open" EXCLUDE those records (open = still genuinely in play).
- Include the canonical concepts when they exist, and add extra concepts (e.g. "resolution", "component", "lead_status") when the data clearly supports them.
- Only reference field names that appear in the profile, exactly as written.

Return ONLY JSON:
{
 "collections": {
   "<collection name>": {
     "description": "one line: what these records are and how this team uses them",
     "record_nouns": ["deal", "opportunity"],
     "concepts": {
        "<concept>": {"field": "<exact field name>", "kind": "person|category|number|date|text|tags",
                      "confidence": 0.0-1.0, "evidence": "short, cites the profile numbers",
                      "value_map": {"open": ["raw", ...]}   (category kind only),
                      "caveats": "optional"}
     },
     "missing_concepts": {"<concept>": "why it is not available"},
     "notes": ["other quirks worth remembering"]
   }
 }
}"""


def build_semantic_map(profiles: list[CollectionProfile], source_kind: str) -> dict[str, Any]:
    profile_text = profiles_to_text(profiles)
    profile_text = llm.truncate_to_budget(profile_text, settings.context_budget - 900)
    concepts = "\n".join(f"- {k}: {v}" for k, v in CANONICAL_CONCEPTS.items())
    user = (
        f"Tool type: {source_kind}\n\nCanonical concepts to look for:\n{concepts}\n\n"
        f"DATA PROFILE:\n{profile_text}\n\nBuild the semantic map."
    )
    result = llm.chat_json(
        [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
        model=settings.model_strong, reasoning="medium", max_tokens=3000, step="semantic_map",
    )
    cols = result.get("collections") or {}
    # defensive normalisation
    known = {p.name: {f.name for f in p.fields} for p in profiles}
    for cname, cmap in list(cols.items()):
        if cname not in known:
            cols.pop(cname)
            continue
        concepts_map = cmap.get("concepts") or {}
        for concept, spec in list(concepts_map.items()):
            if not isinstance(spec, dict) or spec.get("field") not in known[cname]:
                concepts_map.pop(concept)
                continue
            spec.setdefault("kind", "text")
            spec.setdefault("confidence", 0.5)
            spec.setdefault("evidence", "")
            if spec.get("value_map"):
                spec["value_map"] = {str(k).strip().lower(): _norm_definition(vals, spec["field"], known[cname]) for k, vals in spec["value_map"].items()}
                spec["value_map"] = {k: v for k, v in spec["value_map"].items() if v}
        cmap["concepts"] = concepts_map
        cmap.setdefault("record_nouns", [cname.rstrip("s")])
        cmap.setdefault("missing_concepts", {})
        cmap.setdefault("notes", [])
    return {"collections": cols, "source_kind": source_kind}


def _norm_definition(d: Any, own_field: str, fields: set[str]) -> Any:
    """value_map entry -> either list[str] (raw values of own_field) or a rule dict; drops unknown fields."""
    if isinstance(d, list):
        if all(isinstance(x, (str, int, float)) for x in d):
            return [str(x) for x in d]
        parts = [_norm_definition(x, own_field, fields) for x in d]
        parts = [p for p in parts if p]
        return {"any": [p if isinstance(p, dict) else {"field": own_field, "in": p} for p in parts]} if parts else None
    if isinstance(d, dict):
        if "all" in d or "any" in d:
            key = "all" if "all" in d else "any"
            parts = [_norm_definition(x, own_field, fields) for x in (d.get(key) or [])]
            parts = [p if isinstance(p, dict) else {"field": own_field, "in": p} for p in parts if p]
            return {key: parts} if parts else None
        if d.get("field") in fields:
            cond = {"field": d["field"]}
            for k in ("in", "not_in"):
                if isinstance(d.get(k), list):
                    cond[k] = [str(x) for x in d[k]]
            for k in ("is_empty", "not_empty"):
                if d.get(k):
                    cond[k] = True
            return cond if len(cond) > 1 else None
    if isinstance(d, (str, int, float)):
        return [str(d)]
    return None


# ----------------------------------------------------------------------------- people alias clustering
def _norm_name(s: str) -> str:
    return re.sub(r"[^a-z ]", " ", s.lower()).strip()


def _tokens(s: str) -> list[str]:
    return [t for t in _norm_name(s).split() if t]


def cluster_names(values: list[str]) -> list[list[str]]:
    """Deterministic union-find over raw spellings: same first name (fuzzy), abbreviation, or initials."""
    vals = [v for v in dict.fromkeys(v.strip() for v in values if v and v.strip())]
    parent = list(range(len(vals)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    toks = [_tokens(v) for v in vals]
    for i in range(len(vals)):
        for j in range(i + 1, len(vals)):
            ti, tj = toks[i], toks[j]
            if not ti or not tj:
                continue
            same = False
            if _norm_name(vals[i]) == _norm_name(vals[j]):
                same = True
            elif _same_token(ti[0], tj[0]):  # garima ~ garmia ~ ishaan
                # if both have surnames they must agree too
                if len(ti) > 1 and len(tj) > 1 and not (ti[-1].startswith(tj[-1][0]) or tj[-1].startswith(ti[-1][0])):
                    same = False
                else:
                    same = True
            else:
                # initials: "g sharma" vs "garima sharma", "ik" vs "ishan kapoor"
                for a, b in ((ti, tj), (tj, ti)):
                    if len(a) == 1 and len(a[0]) <= 3 and len(b) >= 2 and "".join(t[0] for t in b) == a[0]:
                        same = True
                    if len(a) >= 2 and len(b) >= 2 and len(a[0]) == 1 and a[0] == b[0][0] and a[-1] == b[-1]:
                        same = True
            if same:
                union(i, j)
    groups: dict[int, list[str]] = defaultdict(list)
    for i, v in enumerate(vals):
        groups[find(i)].append(v)
    return sorted(groups.values(), key=lambda g: -len(g))


def _same_token(a: str, b: str) -> bool:
    """First-name equality tolerant to typos: transpositions count as one edit (Damerau)."""
    if len(a) <= 2 or len(b) <= 2:
        return a == b
    if a == b or (len(a) >= 4 and (a.startswith(b) or b.startswith(a))):
        return True
    return DamerauLevenshtein.normalized_similarity(a, b) >= 0.8


def _pick_canonical(group: list[str], freq: Counter) -> str:
    # prefer the longest well-formed full name, tie-break by frequency
    def score(v):
        t = _tokens(v)
        full = len(t) >= 2 and all(len(x) > 1 for x in t)
        return (full, len(_norm_name(v)), freq[v])
    best = max(group, key=score)
    return " ".join(w.capitalize() for w in _norm_name(best).split())


def build_people_aliases(field_values: list[str], use_llm: bool = True) -> list[dict[str, Any]]:
    freq = Counter(v.strip() for v in field_values if v and str(v).strip())
    if not freq:
        return []
    raw = [v for v, _ in freq.most_common(80)]
    groups = cluster_names(raw)
    people = [{"canonical": _pick_canonical(g, freq), "aliases": g, "records": sum(freq[v] for v in g)} for g in groups]
    if not use_llm or not settings.llm_configured:
        return people
    try:
        prompt = (
            "These are raw, hand-typed spellings of people's names from one CRM field, pre-grouped by a heuristic. "
            "Fix the grouping if the heuristic is wrong (merge typos/nicknames/initials of the same person, split different people). "
            "Keep every raw spelling exactly once. Return ONLY JSON: {\"people\": [{\"canonical\": \"Full Name\", \"aliases\": [\"raw\", ...]}]}\n\n"
            + json.dumps([{"canonical": p["canonical"], "aliases": p["aliases"]} for p in people], ensure_ascii=False)
        )
        res = llm.chat_json([{"role": "user", "content": prompt}], model=settings.model_fast, reasoning="low", max_tokens=1500, step="people_aliases")
        fixed = res.get("people") or []
        seen: set[str] = set()
        out = []
        for p in fixed:
            aliases = [a for a in (p.get("aliases") or []) if a in freq and a not in seen]
            if not aliases:
                continue
            seen.update(aliases)
            out.append({"canonical": str(p.get("canonical") or aliases[0]).strip(), "aliases": aliases, "records": sum(freq[a] for a in aliases)})
        leftovers = [v for v in raw if v not in seen]
        for v in leftovers:
            out.append({"canonical": _pick_canonical([v], freq), "aliases": [v], "records": freq[v]})
        return sorted(out, key=lambda p: -p["records"])
    except Exception:
        return people


def attach_people(semantic_map: dict[str, Any], collections: list[Collection]) -> dict[str, Any]:
    """For every concept of kind=person, compute alias clusters over that field's values."""
    by_name = {c.name: c for c in collections}
    people: dict[str, list[dict[str, Any]]] = {}
    for cname, cmap in semantic_map.get("collections", {}).items():
        col = by_name.get(cname)
        if not col:
            continue
        for concept, spec in cmap.get("concepts", {}).items():
            if spec.get("kind") != "person":
                continue
            key = f"{cname}.{spec['field']}"
            if key in people:
                continue
            vals: list[str] = []
            for r in col.records:
                v = r.get(spec["field"])
                if isinstance(v, list):
                    vals.extend(str(x) for x in v if x)
                elif v not in (None, ""):
                    vals.append(str(v))
            people[key] = build_people_aliases(vals)
    semantic_map["people"] = people
    return semantic_map
