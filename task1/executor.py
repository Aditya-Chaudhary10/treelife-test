"""Step 5 — run the plan. Deterministic Python over the fetched records: the model never does
arithmetic, so the number in the answer is exactly what the filters select."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from dateutil import parser as dateparser

from . import rules
from .planner import Binding, Plan


@dataclass
class ExecResult:
    value: Any
    count: int
    total: int
    matched: list[dict[str, Any]] = field(default_factory=list)
    groups: list[list[Any]] | None = None
    per_filter_counts: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"value": self.value, "count": self.count, "total": self.total, "groups": self.groups,
                "per_filter_counts": self.per_filter_counts, "matched_preview": self.matched[:25]}


def _norm(s: Any) -> str:
    return " ".join(str(s).strip().lower().split())


def _num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _date(v: Any) -> date | None:
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return dateparser.parse(str(v)).date()
    except Exception:
        return None


def _values(rec: dict[str, Any], fld: str) -> list[Any]:
    v = rec.get(fld)
    if isinstance(v, list):
        return [x for x in v if x not in (None, "")]
    return [] if v in (None, "") else [v]


def match(rec: dict[str, Any], b: Binding) -> bool:
    vals = _values(rec, b.field or "")
    op = b.op
    if op == "is_empty":
        return not vals
    if op == "not_empty":
        return bool(vals)
    if b.rule is not None:  # person / category / tags resolved to a boolean rule
        return rules.evaluate(rec, b.rule)
    if b.raw_values is not None:
        allowed = {_norm(r) for r in b.raw_values}
        hit = any(_norm(v) in allowed for v in vals)
        return (not hit) if op == "neq" else hit
    if b.kind == "number":
        nums = [n for n in (_num(v) for v in vals) if n is not None]
        if not nums:
            return False
        target = b.value
        if op == "between" and isinstance(target, list) and len(target) == 2:
            lo, hi = _num(target[0]), _num(target[1])
            return any((lo is None or n >= lo) and (hi is None or n <= hi) for n in nums)
        t = _num(target if not isinstance(target, list) else target[0])
        if t is None:
            return False
        return any({"eq": n == t, "neq": n != t, "gt": n > t, "gte": n >= t, "lt": n < t, "lte": n <= t}.get(op, False) for n in nums)
    if b.kind == "date":
        ds = [d for d in (_date(v) for v in vals) if d]
        if not ds:
            return False
        target = b.value
        if op == "between" and isinstance(target, list) and len(target) == 2:
            lo, hi = _date(target[0]), _date(target[1])
            return any((lo is None or d >= lo) and (hi is None or d <= hi) for d in ds)
        t = _date(target if not isinstance(target, list) else target[0])
        if t is None:
            return False
        return any({"eq": d == t, "neq": d != t, "gt": d > t, "gte": d >= t, "lt": d < t, "lte": d <= t}.get(op, False) for d in ds)
    # text
    wanted = b.value if isinstance(b.value, list) else [b.value]
    wanted = [_norm(w) for w in wanted if w is not None]
    if op == "neq":
        return not any(_norm(v) == w for v in vals for w in wanted)
    if op == "in" or op == "eq":
        if any(_norm(v) == w for v in vals for w in wanted):
            return True
    return any(w in _norm(v) for v in vals for w in wanted)


def filter_records(records: list[dict[str, Any]], bindings: list[Binding]) -> list[dict[str, Any]]:
    return [r for r in records if all(match(r, b) for b in bindings)]


def _group_key(rec: dict[str, Any], gb: Binding, alias_maps: dict[str, dict[str, str]]) -> str:
    vals = _values(rec, gb.field or "")
    if not vals:
        return "(empty)"
    amap = alias_maps.get(gb.field or "", {})
    keys = [amap.get(_norm(v), str(v)) for v in vals]
    return ", ".join(dict.fromkeys(keys))


def execute(plan: Plan, records: list[dict[str, Any]]) -> ExecResult:
    active = [b for b in plan.filters if b.resolved]
    matched = filter_records(records, active)
    per_filter = {b.concept: len(filter_records(records, [b])) for b in active}
    op = plan.operation
    res = ExecResult(value=None, count=len(matched), total=len(records), per_filter_counts=per_filter)

    if op in ("group_count", "group_sum") and plan.group_by and plan.group_by.resolved:
        agg: dict[str, float] = defaultdict(float)
        for r in matched:
            k = _group_key(r, plan.group_by, plan.alias_maps)
            if op == "group_count":
                agg[k] += 1
            else:
                n = _num(r.get(plan.metric_field or ""))
                agg[k] += n or 0.0
        groups = sorted(agg.items(), key=lambda kv: -kv[1])
        res.groups = [[k, int(v) if op == "group_count" else round(v, 2)] for k, v in groups]
        res.value = res.groups
        res.matched = matched[:25]
        return res

    if op == "count":
        res.value = len(matched)
    elif op in ("sum", "avg", "min", "max"):
        nums = [n for n in (_num(r.get(plan.metric_field or "")) for r in matched) if n is not None]
        if not nums:
            res.value = 0 if op == "sum" else None
        else:
            res.value = {"sum": round(sum(nums), 2), "avg": round(sum(nums) / len(nums), 2), "min": min(nums), "max": max(nums)}[op]
    else:  # list
        rows = matched
        if plan.sort and plan.sort.get("field"):
            fld = plan.sort["field"]
            rows = sorted(rows, key=lambda r: (_num(r.get(fld)) is None, _num(r.get(fld)) or 0, str(r.get(fld) or "")), reverse=plan.sort.get("dir") == "desc")
        res.value = len(matched)
        res.matched = rows[: plan.limit]
        return res
    res.matched = matched[:25]
    return res


def breakdown(records: list[dict[str, Any]], fld: str, alias_maps: dict[str, dict[str, str]] | None = None, top: int = 8) -> list[list[Any]]:
    """Distribution of a field over a record set (used for zero-result diagnosis and context)."""
    c: Counter = Counter()
    amap = (alias_maps or {}).get(fld, {})
    for r in records:
        vals = _values(r, fld) or ["(empty)"]
        for v in vals:
            c[amap.get(_norm(v), str(v))] += 1
    return [[k, n] for k, n in c.most_common(top)]
