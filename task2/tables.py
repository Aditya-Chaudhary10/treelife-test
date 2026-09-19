"""Large tables are queried, not read. The model sees only the schema + 3 sample rows per sheet,
writes DuckDB SQL, and the *database* does the arithmetic. A 50,000-row sheet costs the same
tokens as a 50-row one."""
from __future__ import annotations

import re
from typing import Any

import duckdb
import pandas as pd

from shared import llm
from shared.config import settings

from .ingest import load_frames, load_parsed
from .workspace import Workspace

MAX_RESULT_ROWS = 60


def _alias(file_name: str, sheet: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", f"{file_name.rsplit('.', 1)[0]}_{sheet}".lower()).strip("_")
    return base[:50] or "t"


def collect_tables(ws: Workspace, file_ids: list[str]) -> tuple[str, dict[str, pd.DataFrame]]:
    """Schema text for the prompt + alias -> DataFrame for DuckDB."""
    lines: list[str] = []
    frames: dict[str, pd.DataFrame] = {}
    for fid in file_ids:
        rec = ws.files.get(fid)
        if not rec or rec.kind not in ("xlsx", "csv"):
            continue
        parsed = load_parsed(ws, fid)
        for sheet, df in load_frames(ws, fid).items():
            alias = _alias(rec.name, sheet)
            n = 2
            while alias in frames:
                alias = f"{alias}_{n}"
                n += 1
            frames[alias] = df
            info = parsed.tables.get(sheet, {})
            cols = ", ".join(f'"{c}" {_dtype(df[c])}' for c in df.columns[:40])
            sample = "; ".join(" | ".join(f"{k}={v}" for k, v in r.items() if v not in ("", None)) for r in info.get("sample", [])[:3])
            lines.append(f'TABLE {alias}  (file "{rec.name}", sheet "{sheet}"{", HIDDEN sheet" if info.get("hidden") else ""}, {len(df)} rows)\n  columns: {cols}\n  sample: {sample[:500]}')
    return "\n".join(lines), frames


def _dtype(s: pd.Series) -> str:
    k = str(s.dtype)
    if k.startswith(("int", "float")):
        return "NUMBER"
    if "datetime" in k:
        return "DATE"
    return "TEXT"


_SQL_SYSTEM = """You write DuckDB SQL to answer a question over the tables described. Rules:
- Use only the listed tables/columns; quote identifiers with double quotes when they contain spaces or symbols.
- Return a single SELECT (CTEs allowed). Never modify data. Limit to 60 rows unless aggregating.
- If amounts are stored as text, CAST them (TRY_CAST(x AS DOUBLE)). Be careful with NULLs.
- Prefer aggregates (SUM/COUNT/AVG/GROUP BY) so the result is small and directly answers the question.
Output ONLY JSON: {"sql": "...", "explanation": "one line of what the query computes"}"""


def sql_answer(question: str, ws: Workspace, file_ids: list[str]) -> dict[str, Any]:
    schema, frames = collect_tables(ws, file_ids)
    if not frames:
        return {"error": "no spreadsheet tables among the selected files", "sql": None, "rows": [], "columns": []}
    con = duckdb.connect()
    for alias, df in frames.items():
        con.register(alias, df)
    messages = [{"role": "system", "content": _SQL_SYSTEM}, {"role": "user", "content": f"TABLES:\n{schema}\n\nQUESTION: {question}"}]
    attempts: list[dict[str, Any]] = []
    for attempt in range(3):
        out = llm.chat_json(messages, model=settings.model_strong, reasoning="low", max_tokens=600, step="table:sql")
        sql = (out.get("sql") or "").strip().rstrip(";")
        if not sql:
            attempts.append({"sql": None, "error": "model returned no SQL"})
            continue
        if not re.match(r"^\s*(with|select)\b", sql, re.I):
            attempts.append({"sql": sql, "error": "only SELECT queries are allowed"})
            messages.append({"role": "assistant", "content": str(out)})
            messages.append({"role": "user", "content": "Only a SELECT/CTE query is allowed. Rewrite."})
            continue
        try:
            res = con.execute(sql)
            cols = [d[0] for d in res.description]
            rows = res.fetchmany(MAX_RESULT_ROWS + 1)
            truncated = len(rows) > MAX_RESULT_ROWS
            rows = [[_json_safe(v) for v in r] for r in rows[:MAX_RESULT_ROWS]]
            return {"sql": sql, "explanation": out.get("explanation", ""), "columns": cols, "rows": rows, "truncated": truncated,
                    "tables": list(frames.keys()), "attempts": attempts + [{"sql": sql, "error": None}], "error": None}
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)[:400]}"
            attempts.append({"sql": sql, "error": err})
            messages.append({"role": "assistant", "content": str(out)})
            messages.append({"role": "user", "content": f"That query failed with: {err}\nFix it. Output the JSON again."})
    return {"sql": attempts[-1]["sql"] if attempts else None, "columns": [], "rows": [], "attempts": attempts, "error": attempts[-1]["error"] if attempts else "unknown", "tables": list(frames.keys())}


def _json_safe(v: Any) -> Any:
    if v is None or isinstance(v, (int, float, str, bool)):
        return v
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)


def result_to_text(res: dict[str, Any]) -> str:
    if res.get("error"):
        return f"SQL failed: {res['error']}"
    head = " | ".join(res["columns"])
    body = "\n".join(" | ".join("" if v is None else str(v) for v in r) for r in res["rows"])
    return f"SQL: {res['sql']}\nRESULT ({len(res['rows'])} rows{', truncated' if res.get('truncated') else ''}):\n{head}\n{body}"
