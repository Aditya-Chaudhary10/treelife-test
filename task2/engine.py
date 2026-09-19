"""Orchestration for the document workspace.

Every chat turn: plan (manifest only) -> run ONE focused strategy -> remember a compact summary.
The cost meter compares what the turn actually consumed with what "send every file" would cost."""
from __future__ import annotations

import json
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from shared import llm
from shared.config import settings
from shared.llm import approx_tokens

from . import audit, tables
from .answer import answer as answer_from_chunks, pack_sources
from .editor import generate as gen
from .editor.docx_edit import EditError, apply_docx_ops
from .editor.validate import preflight_xlsx, validate
from .editor.xlsx_edit import apply_xlsx_ops
from .index import Index
from .ingest import ingest_file, load_parsed
from .planner import plan as make_plan
from .workspace import FileRecord, Workspace, store

_EDIT_DOCX = """You edit a Word document by returning OPERATIONS, never the file. The relevant units are listed as `id | text`.
Allowed ops:
  {"op":"replace_text","unit":"p12","find":"<exact substring copied from the unit>","replace":"<new text>"}
  {"op":"set_paragraph_text","unit":"p12","text":"<full new paragraph text>"}
  {"op":"insert_paragraph_after","unit":"p12","text":"<new paragraph>","style":null}
  {"op":"delete_paragraph","unit":"p12"}
  {"op":"set_table_cell","unit":"t0","row":1,"col":2,"text":"..."}     (row/col are 0-based, row 0 = header)
  {"op":"append_table_row","unit":"t0","values":["..."]}
Rules: change only what the instruction requires; keep all other wording; prefer replace_text with a short exact `find`;
if the instruction cannot be applied to these units, return an empty ops list and explain in "summary".
Output ONLY JSON: {"ops":[...], "summary":"one line describing the change"}"""

_EDIT_XLSX = """You edit a workbook by returning OPERATIONS, never the file. You get sheet schemas (with the header row number),
sample rows and the relevant row blocks (with real sheet row numbers). Allowed ops:
  {"op":"set_cell","sheet":"Invoices","cell":"D3","value":337500}
  {"op":"set_formula","sheet":"Summary","cell":"B9","formula":"=SUM(B2:B8)"}
  {"op":"append_row","sheet":"Invoices","values":[...]}
  {"op":"update_rows","sheet":"Invoices","where":{"column":"Vendor","equals":"Nimbus Software"},"set":{"Status":"Paid"}}
  {"op":"add_sheet","name":"Audit Notes","rows":[["Finding","Detail"],["...","..."]]}
  {"op":"unhide_sheet","sheet":"Adjustments"}
Rules: never overwrite formula cells with values; use real row numbers from the row blocks; keep column order;
if the instruction cannot be applied safely, return an empty ops list and explain in "summary".
Output ONLY JSON: {"ops":[...], "summary":"one line describing the change"}"""

_GENERATE_DOCX = """Produce the CONTENT of a new Word document as JSON (the file is built by code):
{"title":"...","subtitle":"...","sections":[{"heading":"...","paragraphs":["..."],"bullets":["..."],"table":{"columns":["..."],"rows":[["..."]]}}]}
Use only facts from the provided material; cite source file names inline in the text where useful. Be complete but concise."""

_GENERATE_XLSX = """Produce the CONTENT of a new Excel workbook as JSON (the file is built by code):
{"sheets":[{"name":"...","columns":["..."],"rows":[[...]],"total_row":false}]}
Numbers must be plain numbers (no currency symbols or thousands separators). Use only facts from the provided material."""


class Engine:
    def __init__(self) -> None:
        self._indexes: dict[str, Index] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._glock = threading.Lock()

    # ------------------------------------------------------------------ infra
    def lock(self, ws_id: str) -> threading.Lock:
        with self._glock:
            return self._locks.setdefault(ws_id, threading.Lock())

    def index(self, ws: Workspace) -> Index:
        if ws.id not in self._indexes:
            self._indexes[ws.id] = Index(ws.dir)
        return self._indexes[ws.id]

    # ------------------------------------------------------------------ upload
    def upload(self, ws: Workspace, uploads: list[tuple[str, bytes]]) -> dict[str, Any]:
        added: list[FileRecord] = []
        dupes: list[FileRecord] = []
        errors: list[str] = []
        idx = self.index(ws)
        with self.lock(ws.id):
            for name, data in uploads:
                try:
                    for rec, dup in ws.add_bytes(name, data):
                        (dupes if dup else added).append(rec)
                except Exception as e:
                    errors.append(f"{name}: {e}")
            for rec in added:
                ingest_file(ws, rec, idx, summarize=False)
        if added and settings.llm_configured:
            threading.Thread(target=self._summarize_async, args=(ws.id, [r.id for r in added]), daemon=True).start()
        return {"added": [r.__dict__ for r in added], "duplicates": [r.__dict__ for r in dupes], "errors": errors, "workspace": ws.as_dict()}

    def _summarize_async(self, ws_id: str, file_ids: list[str]) -> None:
        """Batched one-line summaries (≈6 files per call) so 50 files cost a handful of calls, once."""
        try:
            ws = store.get(ws_id)
            batch: list[FileRecord] = []
            for fid in file_ids + [None]:
                rec = ws.files.get(fid) if fid else None
                if rec and rec.status == "indexed":
                    batch.append(rec)
                if (len(batch) >= 6 or fid is None) and batch:
                    self._summarize_batch(ws, batch)
                    batch = []
        except Exception:
            pass

    def _summarize_batch(self, ws: Workspace, recs: list[FileRecord]) -> None:
        items = []
        for r in recs:
            parsed = load_parsed(ws, r.id)
            items.append(f"### {r.id} — {r.name}\noutline: {'; '.join(parsed.outline[:8]) or '(none)'}\nexcerpt: {llm.truncate_to_budget(parsed.text, 320)}")
        prompt = ("For EACH file below write one specific sentence (max 30 words): what it is, key parties, amounts, dates, subjects. "
                  "These lines are used to route questions to the right files. Output ONLY JSON: {\"summaries\": {\"<id>\": \"...\"}}\n\n" + "\n\n".join(items))
        try:
            out = llm.chat_json([{"role": "user", "content": prompt}], model=settings.model_fast, reasoning="low", max_tokens=900, step="ingest:summary")
            summaries = out.get("summaries") or {}
        except Exception:
            return
        with self.lock(ws.id):
            fresh = store.get(ws.id)
            for r in recs:
                s = summaries.get(r.id)
                if s and r.id in fresh.files:
                    fresh.files[r.id].summary = str(s)[:300]
            fresh.save()

    # ------------------------------------------------------------------ chat
    def chat(self, ws: Workspace, message: str) -> dict[str, Any]:
        t0 = time.time()
        idx = self.index(ws)
        with llm.track_usage() as usage:
            p = make_plan(message, ws)
            strategy = p["strategy"]
            try:
                if strategy == "table_query":
                    out = self._table_query(ws, idx, message, p)
                elif strategy == "cross_audit":
                    out = self._cross_audit(ws, idx, message, p)
                elif strategy == "edit":
                    out = self._edit(ws, idx, message, p)
                elif strategy == "generate":
                    out = self._generate(ws, idx, message, p)
                elif strategy == "summarize":
                    out = self._summarize(ws, idx, message, p)
                else:
                    out = self._qa(ws, idx, message, p)
            except EditError as e:
                out = {"answer": f"I could not apply that edit safely: {e}", "sources": [], "error": str(e)}
            except Exception as e:  # never 500 the UI: report what failed and keep the workspace usable
                out = {"answer": f"This step failed and was rolled back: {type(e).__name__}: {e}", "sources": [], "error": str(e)}
        files_used = [ws.files[f].name for f in (p["target_files"] + p["support_files"]) if f in ws.files][:12]
        naive = ws.total_tokens()
        resp = {
            "message": message, "strategy": p["strategy"], "plan": p, **out,
            "files_used": files_used,
            "usage": usage.as_dict(),
            "naive_tokens": naive,
            "saving_pct": round(100 * (1 - usage.prompt_tokens / naive), 1) if naive and usage.prompt_tokens < naive else 0,
            "elapsed_s": round(time.time() - t0, 2),
        }
        if not out.get("error"):  # failed turns are not worth remembering
            with self.lock(ws.id):
                fresh = store.get(ws.id)
                fresh.remember(message, p["strategy"], files_used, _summary_line(out))
        return resp

    # ------------------------------------------------------------------ strategies
    def _scope(self, ws: Workspace, p: dict[str, Any]) -> list[str] | None:
        ids = p["target_files"] + p["support_files"]
        return ids or None  # None = whole workspace

    def _retrieve(self, idx: Index, queries: list[str], file_ids: list[str] | None, k: int = 8) -> list[dict[str, Any]]:
        seen: dict[int, dict[str, Any]] = {}
        for q in queries:
            for c in idx.search(q, file_ids=file_ids, k=k):
                if c["id"] not in seen or c["score"] > seen[c["id"]]["score"]:
                    seen[c["id"]] = c
        return sorted(seen.values(), key=lambda c: -c["score"])

    def _qa(self, ws: Workspace, idx: Index, message: str, p: dict[str, Any]) -> dict[str, Any]:
        scope = self._scope(ws, p)
        chunks = self._retrieve(idx, p["queries"] + [message], scope)
        if p["target_files"]:  # make sure the target document is represented even if its wording differs
            for c in idx.search(message, file_ids=p["target_files"], k=4):
                if all(c["id"] != x["id"] for x in chunks):
                    chunks.insert(0, c)
        res = answer_from_chunks(message, chunks, ws.memory_text())
        return {"answer": res["answer"], "sources": res["cited"], "context_tokens": res["context_tokens"], "candidates": len(chunks)}

    def _table_query(self, ws: Workspace, idx: Index, message: str, p: dict[str, Any]) -> dict[str, Any]:
        ids = [f for f in p["target_files"] + p["support_files"] if ws.files[f].kind in ("xlsx", "csv")]
        if not ids:
            ids = [f.id for f in ws.latest_files() if f.kind in ("xlsx", "csv") and f.status == "indexed"]
        if not ids:
            return self._qa(ws, idx, message, p)
        res = tables.sql_answer(message, ws, ids)
        chunks = self._retrieve(idx, p["queries"], ids, k=3)[:3]
        ans = answer_from_chunks(message, chunks, ws.memory_text(), extra_context=llm.truncate_to_budget(tables.result_to_text(res), 1400))
        return {"answer": ans["answer"], "sources": ans["cited"], "sql": res.get("sql"), "sql_result": {"columns": res.get("columns"), "rows": res.get("rows"), "error": res.get("error"), "attempts": res.get("attempts")},
                "context_tokens": ans["context_tokens"]}

    def _cross_audit(self, ws: Workspace, idx: Index, message: str, p: dict[str, Any]) -> dict[str, Any]:
        if not p["target_files"]:
            return {"answer": "Which document should I audit? Name the target file (e.g. 'audit the Nimbus contract against the rest').", "sources": []}
        target = ws.files[p["target_files"][0]]
        support = p["support_files"] or [f.id for f in ws.latest_files() if f.id != target.id and f.status == "indexed"]
        res = audit.cross_audit(ws, idx, target, support, message)
        return {"answer": res["report"], "sources": res.get("sources", []), "findings": res["findings"], "claims": res["claims"], "claim_evidence": res.get("claim_evidence", []),
                "context_tokens": res.get("target_tokens", 0) + res.get("evidence_tokens", 0)}

    def _summarize(self, ws: Workspace, idx: Index, message: str, p: dict[str, Any]) -> dict[str, Any]:
        ids = p["target_files"] or p["support_files"] or [f.id for f in ws.latest_files()][:3]
        chunks: list[dict[str, Any]] = []
        for fid in ids[:3]:
            chunks.extend(idx.file_chunks(fid))
        if sum(c["n_tokens"] for c in chunks) > settings.context_budget - 800:
            chunks = self._retrieve(idx, p["queries"] + ["summary overview key terms amounts dates"], ids, k=12)
        res = answer_from_chunks(message, chunks, ws.memory_text())
        return {"answer": res["answer"], "sources": res["cited"], "context_tokens": res["context_tokens"]}

    # ------------------------------------------------------------------ edit
    def _edit(self, ws: Workspace, idx: Index, message: str, p: dict[str, Any]) -> dict[str, Any]:
        if not p["target_files"]:
            return {"answer": "Which document should I edit? Name the file.", "sources": []}
        target = ws.files[p["target_files"][0]]
        if target.kind not in ("docx", "xlsx"):
            return {"answer": f"I can edit Word (.docx) and Excel (.xlsx/.xlsm) files in place; '{target.name}' is a {target.kind}. I can generate a new document from it instead.", "sources": []}
        src = ws.file_path(target.id)
        instruction = p.get("edit_instruction") or message
        parsed = load_parsed(ws, target.id)
        budget = settings.context_budget - 900

        # supporting facts from other documents (e.g. "update the fee to what the board approved")
        support_ctx = ""
        if p["support_files"]:
            sup = self._retrieve(idx, p["queries"], p["support_files"], k=3)[:4]
            support_ctx, _ = pack_sources(sup, 900)
            budget -= approx_tokens(support_ctx)

        if target.kind == "docx":
            units = parsed.units
            if sum(approx_tokens(u.text) for u in units) > budget:
                hits = self._retrieve(idx, p["queries"] + [instruction], [target.id], k=10)
                keep = {uid for h in hits for uid in h["unit_ids"]}
                units = [u for u in parsed.units if u.id in keep]
            listing = "\n".join(f"{u.id} | {u.text[:600]}" for u in units)
            system, header_rows = _EDIT_DOCX, {}
        else:
            reasons = preflight_xlsx(src)
            if reasons:
                return {"answer": "Edit blocked to avoid silent corruption: " + "; ".join(reasons) + ". I can instead generate a new workbook with the required changes.", "sources": []}
            schema, _ = tables.collect_tables(ws, [target.id])
            header_rows = {s: int(info.get("header_row", 1)) for s, info in parsed.tables.items()}
            hits = self._retrieve(idx, p["queries"] + [instruction], [target.id], k=6)
            blocks, used = pack_sources([h for h in hits if "rows" in h.get("loc", {})], budget - approx_tokens(schema))
            listing = f"{schema}\nheader rows: {header_rows}\n\nRELEVANT ROW BLOCKS:\n{blocks}"
            system = _EDIT_XLSX
        user = f"DOCUMENT: {target.name}\n\n{listing}\n\n" + (f"SUPPORTING FACTS FROM OTHER DOCUMENTS:\n{support_ctx}\n\n" if support_ctx else "") + f"INSTRUCTION: {instruction}"
        out = llm.chat_json([{"role": "system", "content": system}, {"role": "user", "content": user}], model=settings.model_strong, reasoning="medium", max_tokens=1200, step="edit:ops")
        ops = [o for o in (out.get("ops") or []) if isinstance(o, dict) and o.get("op")]
        if not ops:
            return {"answer": "No safe edit could be derived: " + str(out.get("summary") or "the instruction did not map to any paragraph/cell."), "sources": [], "ops": []}

        tmp = ws.file_dir(target.id) / f"_edit_{int(time.time())}{target.ext}"
        try:
            applied = apply_docx_ops(src, tmp, ops) if target.kind == "docx" else apply_xlsx_ops(src, tmp, ops, header_rows)
            report = validate(tmp, original=src, expect=applied["expect"])
            if not report["ok"]:
                tmp.unlink(missing_ok=True)
                return {"answer": "The edited file failed validation and was discarded: " + "; ".join(report["issues"]), "sources": [], "ops": ops, "validation": report}
            with self.lock(ws.id):
                fresh = store.get(ws.id)
                new_rec = fresh.add_version(target.id, tmp.read_bytes(), note=str(out.get("summary") or instruction)[:200])
                ingest_file(fresh, new_rec, idx, summarize=False)
                fresh.files[new_rec.id].summary = target.summary
                fresh.save()
        finally:
            tmp.unlink(missing_ok=True)
        lines = [f"Edited **{target.name}** → **{new_rec.name}** (original kept). Changes:"] + [f"- {l}" for l in applied["log"]]
        lines.append(f"Validation: OK — {_stats_line(report['stats'])}" + (f"; warnings: {', '.join(report['warnings'])}" if report["warnings"] else ""))
        return {"answer": "\n".join(lines), "sources": [], "ops": ops, "validation": report, "artifacts": [_artifact(ws, new_rec)], "context_tokens": approx_tokens(user)}

    # ------------------------------------------------------------------ generate
    def _generate(self, ws: Workspace, idx: Index, message: str, p: dict[str, Any]) -> dict[str, Any]:
        fmt = (p.get("output_format") or "docx").lower()
        fmt = "xlsx" if fmt in ("xlsx", "excel", "xls", "csv") else "docx"
        scope = self._scope(ws, p)
        chunks = self._retrieve(idx, p["queries"] + [message], scope, k=10)
        material, used = pack_sources(chunks, settings.context_budget - 1500)
        memory = ws.memory_text()
        user = f"MATERIAL:\n{material or '(none)'}\n\nCONVERSATION MEMORY (may contain earlier findings):\n{memory}\n\nREQUEST: {message}"
        spec = llm.chat_json([{"role": "system", "content": _GENERATE_XLSX if fmt == "xlsx" else _GENERATE_DOCX}, {"role": "user", "content": user}],
                             model=settings.model_strong, reasoning="medium", max_tokens=2500, step="generate:spec")
        name = _safe_name(spec.get("title") or (spec.get("sheets") or [{}])[0].get("name") or "Generated document") + f".{fmt}"
        tmp = ws.dir / f"_gen_{int(time.time())}.{fmt}"
        try:
            (gen.build_xlsx if fmt == "xlsx" else gen.build_docx)(spec, tmp)
            report = validate(tmp)
            if not report["ok"]:
                return {"answer": "Generated file failed validation: " + "; ".join(report["issues"]), "sources": used, "validation": report}
            with self.lock(ws.id):
                fresh = store.get(ws.id)
                recs = fresh.add_bytes(name, tmp.read_bytes())
                rec = recs[0][0]
                ingest_file(fresh, rec, idx, summarize=False)
                fresh.files[rec.id].note = "generated by the assistant"
                fresh.save()
        finally:
            tmp.unlink(missing_ok=True)
        n_sections = len(spec.get("sections") or spec.get("sheets") or [])
        return {"answer": f"Created **{rec.name}** ({n_sections} {'sheets' if fmt == 'xlsx' else 'sections'}) from {len(used)} source passages. Validation: OK — {_stats_line(report['stats'])}. It is now part of the workspace and searchable.",
                "sources": used, "artifacts": [_artifact(ws, rec)], "validation": report, "spec": spec, "context_tokens": approx_tokens(user)}


def _artifact(ws: Workspace, rec: FileRecord) -> dict[str, Any]:
    return {"file_id": rec.id, "name": rec.name, "url": f"/api/task2/workspaces/{ws.id}/files/{rec.id}/download", "version": rec.version}


def _stats_line(st: dict[str, Any]) -> str:
    if "sheets" in st:
        return f"{len(st['sheets'])} sheets, {st['formulas']} formulas intact" + (", macros intact" if st.get("has_vba") else "")
    return f"{st.get('paragraphs', 0)} paragraphs, {st.get('tables', 0)} tables, styles intact"


def _summary_line(out: dict[str, Any]) -> str:
    a = str(out.get("answer") or "")
    return " ".join(a.split())[:300]


def _safe_name(s: str) -> str:
    cleaned = "".join(c for c in str(s) if c.isalnum() or c in " -_()")
    return " ".join(cleaned.split())[:60] or "Generated document"


engine = Engine()
