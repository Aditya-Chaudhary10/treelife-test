"""Turn a chat message into a focused plan: which strategy, which files, which search queries.

The planner sees only the manifest (1–2 lines per file) and the compact conversation memory —
never document contents — so this step costs ~1.5k tokens even with 50 files in the workspace."""
from __future__ import annotations

from typing import Any

from shared import llm
from shared.config import settings

from .workspace import Workspace

STRATEGIES = ("qa", "table_query", "cross_audit", "edit", "generate", "summarize")

_SYSTEM = """You are the planner of a document workspace. Choose HOW to answer and WHICH files to touch.

Strategies:
- qa           : question answerable from passages of one or a few documents (search then read only those passages)
- table_query  : numeric / aggregation / filtering question over a spreadsheet or CSV (SQL over the sheet, never read all rows)
- cross_audit  : the user asks to audit / verify / reconcile / cross-check ONE specific document's contents against others (claims of the target are checked one by one). Not for spreadsheets as target.
                 For "does X comply with the policy / is anything not allowed / compare A and B on topic T" questions prefer qa with both files as targets.
- edit         : the user wants an existing DOCX/XLSX changed (replace text, update a value/clause, add a row/paragraph)
- generate     : the user wants a NEW document produced (report, memo, summary sheet) as DOCX or XLSX
- summarize    : summarise one or more documents

Rules:
- target_files: the document(s) the question is ABOUT (the one to edit / audit / summarise / answer from). Use the ids from the manifest exactly.
- support_files: other documents needed as context. Use "all" when the user says "against the rest / all documents / everything"; otherwise list the relevant ids, or [].
- queries: 2-4 short search queries (keywords, not sentences) that would find the relevant passages. For table_query put the natural-language question.
- Prefer few files. Never choose files that are clearly unrelated.
- Use the conversation memory to resolve references like "that document", "the same file", "now change it".
- output_format: "docx" or "xlsx" for generate, else null. edit_instruction: for edit, restate precisely what to change.

Output ONLY JSON:
{"strategy": "...", "target_files": ["id"], "support_files": ["id"] | "all" | [], "queries": ["..."], "reason": "one line", "output_format": null, "edit_instruction": null}"""


def plan(question: str, ws: Workspace) -> dict[str, Any]:
    manifest = ws.manifest_text()
    memory = ws.memory_text()
    user = f"MANIFEST (id, name, summary):\n{manifest}\n\nCONVERSATION MEMORY:\n{memory}\n\nMESSAGE: {question}"
    p = llm.chat_json([{"role": "system", "content": _SYSTEM}, {"role": "user", "content": llm.truncate_to_budget(user, settings.context_budget)}],
                      model=settings.model_strong, reasoning="low", max_tokens=500, step="plan")
    return normalise(p, ws, question)


def normalise(p: dict[str, Any], ws: Workspace, question: str) -> dict[str, Any]:
    latest = {f.id: f for f in ws.latest_files() if f.status == "indexed"}
    strategy = str(p.get("strategy") or "qa").lower()
    if strategy not in STRATEGIES:
        strategy = "qa"

    def resolve(ids: Any) -> list[str]:
        out: list[str] = []
        for x in ids if isinstance(ids, list) else []:
            rec = ws.find(str(x))
            if rec and rec.id in latest and rec.id not in out:
                out.append(rec.id)
        return out

    targets = resolve(p.get("target_files"))
    support_raw = p.get("support_files")
    if isinstance(support_raw, str) and support_raw.lower() == "all":
        support = [fid for fid in latest if fid not in targets]
        support_all = True
    else:
        support = [fid for fid in resolve(support_raw) if fid not in targets]
        support_all = False
    # name mentions in the question beat the model when it forgot a target
    if not targets:
        ql = question.lower()
        for f in latest.values():
            stem = f.name.rsplit(".", 1)[0].lower()
            if len(stem) > 4 and stem in ql:
                targets.append(f.id)
    if strategy == "cross_audit" and not support and not support_all:
        support = [fid for fid in latest if fid not in targets]
        support_all = True
    queries = [str(q) for q in (p.get("queries") or []) if str(q).strip()][:4] or [question]
    return {
        "strategy": strategy, "target_files": targets, "support_files": support, "support_all": support_all,
        "queries": queries, "reason": str(p.get("reason") or ""), "output_format": p.get("output_format"),
        "edit_instruction": p.get("edit_instruction") or question,
    }
