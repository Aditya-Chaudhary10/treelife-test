"""Export connector: point at a folder (or one file) of CSV / JSON / XLSX exports.
Each file (or sheet) becomes a collection. This is the escape hatch for any tool without an adapter:
export -> drop the files -> ask questions."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .base import Collection, Connector, ConnectorError, FieldMeta, flatten


class FilesConnector(Connector):
    kind = "files"

    def __init__(self, path: str):
        self.path = Path(path)
        if not self.path.exists():
            raise ConnectorError(f"path not found: {path}")

    def describe(self) -> dict[str, Any]:
        return {"kind": self.kind, "path": str(self.path)}

    def load(self, max_records: int = 2000) -> list[Collection]:
        files = [self.path] if self.path.is_file() else sorted(p for p in self.path.iterdir() if p.suffix.lower() in (".csv", ".json", ".xlsx", ".xlsm"))
        cols: list[Collection] = []
        for f in files:
            for name, records in self._read(f, max_records):
                if not records:
                    continue
                keys = list(dict.fromkeys(k for r in records for k in r))
                metas = [FieldMeta(name=k, label=k, type=_guess(records, k)) for k in keys]
                cols.append(Collection(name=name, label=f"{f.name}", fields=metas, records=records,
                                       notes=["Export file: cannot tell built-in from custom fields; rely on value signals."]))
        if not cols:
            raise ConnectorError("no CSV/JSON/XLSX files found")
        return cols

    @staticmethod
    def _read(f: Path, limit: int):
        suf = f.suffix.lower()
        if suf == ".csv":
            df = pd.read_csv(f, nrows=limit)
            yield f.stem, _df_records(df)
        elif suf in (".xlsx", ".xlsm"):
            for sheet, df in pd.read_excel(f, sheet_name=None, nrows=limit).items():
                yield f"{f.stem}:{sheet}", _df_records(df)
        elif suf == ".json":
            data = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for k in ("data", "results", "items", "records", "issues"):
                    if isinstance(data.get(k), list):
                        data = data[k]
                        break
            if isinstance(data, list):
                yield f.stem, [flatten(r) if isinstance(r, dict) else {"value": r} for r in data[:limit]]


def _df_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    df = df.where(pd.notnull(df), None)
    return [{str(k): (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in row.items()} for row in df.to_dict(orient="records")]


def _guess(records: list[dict], key: str) -> str:
    for r in records:
        v = r.get(key)
        if v in (None, ""):
            continue
        if isinstance(v, bool):
            return "bool"
        if isinstance(v, (int, float)):
            return "number"
        if isinstance(v, list):
            return "set"
        return "text"
    return "unknown"
