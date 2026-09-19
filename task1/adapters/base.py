"""The only contract the translation layer needs from any tool.

A connector turns *whatever* the source is (CRM, project tracker, spreadsheet export, drive) into
flat collections of records plus light field metadata. Everything downstream — profiling, semantic
mapping, planning, execution — works on this shape and never sees tool-specific concepts.

Adding a new tool = implementing `load()` (typically < 100 lines, see pipedrive.py / jira.py).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FieldMeta:
    name: str                      # key used in the flattened record
    label: str                     # human-readable label as the client sees it in the tool
    type: str = "unknown"          # source's declared type hint: text|number|date|enum|set|user|bool|unknown
    is_custom: bool = False        # created by the client (vs shipped with the tool)
    options: list[str] | None = None  # declared choices for enum/set fields, if the tool exposes them


@dataclass
class Collection:
    name: str                      # e.g. "deals", "issues", "files"
    label: str
    fields: list[FieldMeta]
    records: list[dict[str, Any]]
    notes: list[str] = field(default_factory=list)  # adapter facts worth telling the mapper


class Connector(ABC):
    kind: str = "abstract"

    @abstractmethod
    def load(self, max_records: int = 2000) -> list[Collection]:
        """Fetch schema + records. Called once per connection; results are cached by the engine."""

    def describe(self) -> dict[str, Any]:
        return {"kind": self.kind}


class ConnectorError(RuntimeError):
    pass


def flatten(obj: Any, prefix: str = "", out: dict[str, Any] | None = None) -> dict[str, Any]:
    """Flatten nested dicts to dotted keys. Lists of scalars stay lists; lists of dicts become
    lists of their 'name'/'label'/'value' if present (good enough for tags, components, emails)."""
    if out is None:
        out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, dict):
                flatten(v, f"{prefix}{k}.", out)
            elif isinstance(v, list):
                out[prefix + k] = [_scalarize(x) for x in v]
            else:
                out[prefix + k] = v
    return out


def _scalarize(x: Any) -> Any:
    if isinstance(x, dict):
        for key in ("name", "label", "displayName", "value", "title"):
            if key in x and not isinstance(x[key], (dict, list)):
                return x[key]
        return str(x)
    return x
