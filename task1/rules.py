"""Tiny boolean rule language shared by the planner and executor.

rule := {"all": [rule...]} | {"any": [rule...]} | {"not": rule}
      | {"field": f, "in": [...]} | {"field": f, "not_in": [...]} | {"field": f, "is_empty": true} | {"field": f, "not_empty": true}
Values are compared case/whitespace-insensitively; multi-valued fields match if ANY element does.
"""
from __future__ import annotations

from typing import Any


def norm(s: Any) -> str:
    return " ".join(str(s).strip().lower().split())


def field_values(rec: dict[str, Any], fld: str) -> list[Any]:
    v = rec.get(fld)
    if isinstance(v, list):
        return [x for x in v if x not in (None, "")]
    return [] if v in (None, "") else [v]


def evaluate(rec: dict[str, Any], rule: dict[str, Any] | None) -> bool:
    if not rule:
        return False
    if "all" in rule:
        return all(evaluate(rec, r) for r in rule["all"])
    if "any" in rule:
        return any(evaluate(rec, r) for r in rule["any"])
    if "not" in rule:
        return not evaluate(rec, rule["not"])
    fld = rule.get("field")
    vals = field_values(rec, fld or "")
    if rule.get("is_empty"):
        return not vals
    if rule.get("not_empty"):
        return bool(vals)
    if "in" in rule:
        allowed = {norm(x) for x in rule["in"]}
        return any(norm(v) in allowed for v in vals)
    if "not_in" in rule:
        banned = {norm(x) for x in rule["not_in"]}
        return not any(norm(v) in banned for v in vals)
    return False


def describe(rule: dict[str, Any] | None) -> str:
    """Human-readable rendering, e.g. status ∈ {Open} AND stage ∉ {Dead Leads}."""
    if not rule:
        return "(no rule)"
    if "all" in rule:
        return " AND ".join(f"({describe(r)})" if ("any" in r or "all" in r) else describe(r) for r in rule["all"])
    if "any" in rule:
        return " OR ".join(f"({describe(r)})" if ("any" in r or "all" in r) else describe(r) for r in rule["any"])
    if "not" in rule:
        return f"NOT ({describe(rule['not'])})"
    f = rule.get("field")
    if rule.get("is_empty"):
        return f"{f} is empty"
    if rule.get("not_empty"):
        return f"{f} is filled"
    if "in" in rule:
        return f"{f} ∈ {{{', '.join(map(str, rule['in']))}}}"
    if "not_in" in rule:
        return f"{f} ∉ {{{', '.join(map(str, rule['not_in']))}}}"
    return str(rule)


def fields_used(rule: dict[str, Any] | None) -> set[str]:
    if not rule:
        return set()
    if "all" in rule or "any" in rule:
        out: set[str] = set()
        for r in rule.get("all") or rule.get("any") or []:
            out |= fields_used(r)
        return out
    if "not" in rule:
        return fields_used(rule["not"])
    return {rule["field"]} if rule.get("field") else set()
