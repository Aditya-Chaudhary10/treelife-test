"""Step 1 — discover how the client *actually* uses their tool. Pure statistics, no LLM.

For every field we compute fill rate, cardinality, value shapes and a few tell-tale signals:
  * CONSTANT           -> a field with one value carries no information ("Owner = Treelife Admin" on every deal)
  * inconsistent case  -> hand-typed data (22 raw spellings collapsing to 17 after normalisation)
  * declared-but-unused options -> "Lost" exists as an option but no record ever uses it
  * name_like / repeating -> the field holds people, not free text
The profile is rendered as compact text for the semantic mapper and kept as JSON for the UI.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

from dateutil import parser as dateparser

from .adapters.base import Collection

_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z.'\- ]{0,40}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)
_URL_RE = re.compile(r"^https?://", re.I)
_DATE_HINT = re.compile(r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}")


@dataclass
class FieldProfile:
    name: str
    label: str
    is_custom: bool
    declared_type: str
    inferred_type: str
    fill_rate: float
    nonempty: int
    distinct: int
    distinct_normalised: int
    top_values: list[list[Any]]          # [[value, count], ...]
    looks_like: list[str]
    avg_len: float
    samples: list[str]
    declared_options: list[str] | None = None
    unused_options: list[str] | None = None


@dataclass
class CollectionProfile:
    name: str
    label: str
    record_count: int
    fields: list[FieldProfile]
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _is_empty(v: Any) -> bool:
    return v is None or v == "" or v == [] or (isinstance(v, str) and not v.strip())


def _norm(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v).strip().lower())


def _is_date(s: str) -> bool:
    if not _DATE_HINT.search(s):
        return False
    try:
        dateparser.parse(s)
        return True
    except Exception:
        return False


def profile_field(name: str, label: str, is_custom: bool, declared_type: str, values: list[Any], options: list[str] | None) -> FieldProfile:
    total = len(values)
    nonempty_vals = [v for v in values if not _is_empty(v)]
    nonempty = len(nonempty_vals)
    fill = nonempty / total if total else 0.0

    # explode multi-valued fields for value statistics
    multi = any(isinstance(v, list) for v in nonempty_vals)
    flat: list[Any] = []
    for v in nonempty_vals:
        flat.extend(v if isinstance(v, list) else [v])

    counts = Counter(str(v).strip() for v in flat)
    norm_counts = Counter(_norm(v) for v in flat)
    distinct, distinct_norm = len(counts), len(norm_counts)

    types = Counter()
    for v in flat:
        if isinstance(v, bool):
            types["bool"] += 1
        elif isinstance(v, (int, float)):
            types["number"] += 1
        elif isinstance(v, str):
            s = v.strip()
            if _is_date(s):
                types["date"] += 1
            elif re.fullmatch(r"-?\d+(\.\d+)?", s):
                types["number"] += 1
            else:
                types["text"] += 1
        else:
            types["other"] += 1
    if not flat:
        inferred = "empty"
    else:
        top_type, top_n = types.most_common(1)[0]
        inferred = top_type if top_n / len(flat) >= 0.8 else "mixed"
    if multi:
        inferred = f"list<{inferred}>"

    str_vals = [str(v).strip() for v in flat if isinstance(v, str)]
    avg_len = sum(len(s) for s in str_vals) / len(str_vals) if str_vals else 0.0

    looks: list[str] = []
    if nonempty == 0:
        looks.append("always_empty")
    elif fill < 0.25:
        looks.append("mostly_empty")
    if nonempty >= 3 and distinct_norm == 1:
        looks.append("CONSTANT")
    if multi:
        looks.append("multi_valued")
    if str_vals:
        name_hits = sum(1 for s in str_vals if _NAME_RE.match(s) and len(s.split()) <= 4 and all(len(t) <= 15 for t in s.split()))
        if name_hits / len(str_vals) >= 0.8 and avg_len <= 30:
            looks.append("name_like")
        if sum(1 for s in str_vals if _EMAIL_RE.match(s)) / len(str_vals) >= 0.8:
            looks.append("email")
        if sum(1 for s in str_vals if _URL_RE.match(s)) / len(str_vals) >= 0.8:
            looks.append("url")
        if avg_len > 40 and distinct / max(nonempty, 1) > 0.8:
            looks.append("free_text")
    if flat and distinct <= 20 and nonempty >= 8 and "number" not in inferred and "date" not in inferred:
        looks.append("low_cardinality")
    if flat and nonempty >= 8 and distinct / len(flat) <= 0.6 and "CONSTANT" not in looks and "low_cardinality" not in looks:
        looks.append("repeating_values")
    if distinct_norm < distinct:
        looks.append("inconsistent_spelling")
    if name == "id" or (inferred == "number" and distinct == nonempty and nonempty > 10):
        looks.append("identifier")

    unused = None
    if options:
        used = {_norm(k) for k in counts}
        unused = [o for o in options if _norm(o) not in used]

    return FieldProfile(
        name=name, label=label, is_custom=is_custom, declared_type=declared_type, inferred_type=inferred,
        fill_rate=round(fill, 3), nonempty=nonempty, distinct=distinct, distinct_normalised=distinct_norm,
        top_values=[[v, c] for v, c in counts.most_common(12)], looks_like=looks, avg_len=round(avg_len, 1),
        samples=[s[:60] for s in list(dict.fromkeys(str_vals))[:4]],
        declared_options=options, unused_options=unused or None,
    )


def profile_collection(col: Collection) -> CollectionProfile:
    fields = []
    for fm in col.fields:
        values = [r.get(fm.name) for r in col.records]
        fields.append(profile_field(fm.name, fm.label, fm.is_custom, fm.type, values, fm.options))
    return CollectionProfile(name=col.name, label=col.label, record_count=len(col.records), fields=fields, notes=list(col.notes))


# ----------------------------------------------------------------------------- rendering for the LLM
def _fmt_val(v: Any, n: int = 32) -> str:
    s = str(v).replace("\n", " ")
    return (s[: n - 1] + "…") if len(s) > n else s


def field_line(f: FieldProfile) -> str:
    kind = "CUSTOM" if f.is_custom else "built-in"
    parts = [f"- {f.name} [{f.declared_type}/{f.inferred_type}, {kind}] fill {int(f.fill_rate * 100)}%"]
    if f.nonempty:
        d = f"distinct {f.distinct}"
        if f.distinct_normalised < f.distinct:
            d += f" ({f.distinct_normalised} after case/space normalisation)"
        parts.append(d)
    if f.looks_like:
        parts.append("signals: " + ", ".join(f.looks_like))
    if f.top_values and "identifier" not in f.looks_like and "free_text" not in f.looks_like:
        tv = ", ".join(f'"{_fmt_val(v)}"({c})' for v, c in f.top_values[:8])
        parts.append("top: " + tv)
    elif f.samples:
        parts.append("e.g. " + ", ".join(f'"{_fmt_val(s, 40)}"' for s in f.samples[:3]))
    if f.declared_options:
        parts.append("declared options: " + ", ".join(_fmt_val(o) for o in f.declared_options[:12]))
    if f.unused_options:
        parts.append("NEVER USED: " + ", ".join(_fmt_val(o) for o in f.unused_options[:8]))
    return " | ".join(parts)


def profiles_to_text(profiles: list[CollectionProfile], max_fields: int = 45) -> str:
    out = []
    for p in profiles:
        out.append(f"## Collection `{p.name}` ({p.label}) — {p.record_count} records")
        for n in p.notes:
            out.append(f"note: {n}")
        # interesting fields first: custom, then non-empty, then the rest
        ranked = sorted(p.fields, key=lambda f: (not f.is_custom, "always_empty" in f.looks_like, f.name))
        for f in ranked[:max_fields]:
            out.append(field_line(f))
        if len(p.fields) > max_fields:
            out.append(f"(+{len(p.fields) - max_fields} more fields omitted)")
        out.append("")
    return "\n".join(out)


def schema_fingerprint(collections: list[Collection]) -> str:
    sig = [(c.name, sorted((f.name, f.type, f.is_custom) for f in c.fields), len(c.records)) for c in collections]
    return hashlib.sha1(json.dumps(sig, sort_keys=True, default=str).encode()).hexdigest()[:16]
