"""Task 2 — upload once, then ask / audit / edit / generate."""
from pathlib import Path

import pandas as pd
import streamlit as st

from shared.config import settings

EXAMPLES = [
    "What are the payment terms in the Nimbus contract?",
    "Cross-audit the Nimbus Software contract against all other documents and list discrepancies",
    "Total invoiced amount per vendor from the invoice register, and which invoices are still open?",
    "Is there anything in the invoice register that the vendor policy would not allow?",
    "In the Nimbus contract change the payment terms from 30 days to 45 days and the termination notice to 90 days",
    "Generate a Word memo to the CFO summarising the discrepancies found, with a table of items",
    "Create an Excel sheet listing every vendor contract with its annual fee, SLA and notice period",
]
STRATEGY_BADGE = {"qa": ":blue[**Q&A**]", "table_query": ":violet[**SQL over sheet**]", "cross_audit": ":orange[**cross-audit**]",
                  "edit": ":green[**edit**]", "generate": ":rainbow[**generate**]", "summarize": ":gray[**summary**]"}
DEMO_ZIP = Path(__file__).resolve().parent.parent / "samples" / "demo_corpus.zip"


@st.cache_resource(show_spinner=False)
def get_engine():
    from task2.engine import engine

    return engine


@st.cache_resource(show_spinner=False)
def get_store():
    from task2.workspace import store

    return store


def fmt_tok(n: int) -> str:
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def _loc(l: dict) -> str:
    if l.get("page"):
        return f"(p.{l['page']})"
    if l.get("sheet") and l.get("rows"):
        return f"({l['sheet']}!{l['rows'][0]}-{l['rows'][1]})"
    if l.get("sheet"):
        return f"({l['sheet']})"
    if l.get("paragraph") is not None:
        return f"(¶{l['paragraph']}{' ' + l['section'] if l.get('section') else ''})"
    return ""


engine, store = get_engine(), get_store()

# ----------------------------------------------------------------------------- sidebar: workspace + upload
with st.sidebar:
    st.markdown("### Workspace")
    workspaces = store.list()
    options = ["＋ New workspace"] + [w["id"] for w in workspaces]
    labels = {w["id"]: f"{w['name']} ({w['files']} files)" for w in workspaces}
    current = st.session_state.get("t2_ws")
    idx = options.index(current) if current in options else (1 if workspaces else 0)
    choice = st.selectbox("Workspace", options, index=idx, format_func=lambda k: labels.get(k, k))
    if choice == "＋ New workspace":
        name = st.text_input("Name", value="Vendor audit")
        if st.button("Create workspace", type="primary", width="stretch"):
            ws = store.create(name)
            st.session_state["t2_ws"] = ws.id
            st.rerun()
        ws = None
    else:
        st.session_state["t2_ws"] = choice
        ws = store.get(choice)

    if ws is not None:
        st.markdown("### Upload once")
        files = st.file_uploader("PDF · DOCX · XLSX/XLSM · CSV · TXT · MD · ZIP", accept_multiple_files=True,
                                 type=["pdf", "docx", "xlsx", "xlsm", "csv", "txt", "md", "zip"], key=f"t2_up_{ws.id}")
        c1, c2 = st.columns(2)
        if c1.button("Upload & index", type="primary", width="stretch", disabled=not files):
            with st.spinner("Hashing → parsing → indexing (once per file)…"):
                res = engine.upload(ws, [(f.name, f.getvalue()) for f in files])
            msg = f"Added {len(res['added'])} file(s)"
            if res["duplicates"]:
                msg += f" · {len(res['duplicates'])} duplicate(s) skipped"
            if res["errors"]:
                st.error("; ".join(res["errors"]))
            st.toast(msg, icon="✅")
            st.rerun()
        if c2.button("Load demo corpus", width="stretch", disabled=not DEMO_ZIP.exists(), help="16 files with planted discrepancies (samples/demo_corpus.zip)"):
            with st.spinner("Indexing the demo corpus…"):
                res = engine.upload(ws, [("demo_corpus.zip", DEMO_ZIP.read_bytes())])
            st.toast(f"Added {len(res['added'])} file(s) · {len(res['duplicates'])} duplicate(s) skipped", icon="✅")
            st.rerun()

        latest = ws.latest_files()
        st.markdown(f"### Files ({len(latest)})")
        if st.button("↻ Refresh summaries", width="stretch"):
            st.rerun()
        for f in sorted(ws.files.values(), key=lambda f: -f.added_at)[:60]:
            superseded = any(x.parent_id == f.id for x in ws.files.values())
            tags = (f" · v{f.version}" if f.version > 1 else "") + (" · superseded" if superseded else "") + (f" · hidden sheet: {', '.join(f.hidden_sheets)}" if f.hidden_sheets else "")
            with st.expander(f"{f.name}{tags}", expanded=False):
                st.caption(f.summary or f.error or "summarising…")
                st.caption(f"{f.kind} · {fmt_tok(f.tokens_estimate)} tokens · {f.chunks} chunks" + (f" · {f.pages} pages" if f.pages else "") + (f" · sheets: {', '.join(f.sheets)}" if f.sheets else "") + (f" · {f.note}" if f.note else ""))
                try:
                    st.download_button("⬇ download", data=ws.file_path(f.id).read_bytes(), file_name=f.name, key=f"dl_side_{f.id}", width="stretch")
                except OSError:
                    pass

    if not settings.llm_configured:
        st.warning("Set `LLM_API_KEY` (in `.env` locally or Streamlit secrets) to enable chat.", icon="🔑")

# ----------------------------------------------------------------------------- main
st.title("📁 Enterprise Document Workspace")
if ws is None:
    st.markdown("Create a workspace in the sidebar, upload your files **once** (or load the demo corpus), then ask, audit, edit or generate.")
    c1, c2, c3, c4 = st.columns(4)
    c1.info("**Upload once** — SHA-256 dedupe, ZIPs expanded, parsed & indexed a single time", icon="1️⃣")
    c2.info("**Ask** — the planner sees a one-line manifest per file, never the files", icon="2️⃣")
    c3.info("**Audit / query** — claims vs evidence with citations; SQL over sheets", icon="3️⃣")
    c4.info("**Edit / generate** — operations applied by code, validated, versioned", icon="4️⃣")
    st.stop()

stats = engine.index(ws).stats()
latest = ws.latest_files()
m1, m2, m3, m4 = st.columns(4)
m1.metric("Files", len(latest))
m2.metric("Chunks indexed", stats["chunks"])
m3.metric("Tokens if sent whole", fmt_tok(ws.total_tokens()))
m4.metric("Turns remembered", len(ws.chat))

ready = any(f.status == "indexed" for f in latest)
if not ready:
    st.info("Upload files or load the demo corpus from the sidebar to start.", icon="⬅️")
    st.stop()

history_key, queue_key, pill_key = f"t2_chat_{ws.id}", f"t2_queue_{ws.id}", f"t2_pills_{ws.id}"
history = st.session_state.setdefault(history_key, [])


def render_reply(j: dict, i: int) -> None:
    st.markdown(f"{STRATEGY_BADGE.get(j['strategy'], j['strategy'])} · {j.get('plan', {}).get('reason', '')}")
    st.markdown(j.get("answer") or "")
    for a in j.get("artifacts") or []:
        p = ws.file_path(a["file_id"]) if a["file_id"] in ws.files else None
        if p and p.exists():
            st.download_button(f"⬇ {a['name']}", data=p.read_bytes(), file_name=a["name"], key=f"dl_{i}_{a['file_id']}")
    if j.get("sql"):
        with st.expander(f"SQL executed over the sheet ({len((j.get('sql_result') or {}).get('rows') or [])} rows)"):
            st.code(j["sql"], language="sql")
            sr = j.get("sql_result") or {}
            if sr.get("columns"):
                st.dataframe(pd.DataFrame(sr["rows"], columns=sr["columns"]), hide_index=True, width="stretch")
            if sr.get("error"):
                st.error(sr["error"])
    if j.get("findings"):
        with st.expander(f"findings ({len(j['findings'])})", expanded=True):
            st.dataframe(pd.DataFrame(j["findings"])[["claim", "status", "severity", "evidence"]], hide_index=True, width="stretch")
    if j.get("ops"):
        with st.expander(f"edit operations applied ({len(j['ops'])})"):
            st.json(j["ops"], expanded=False)
    if j.get("validation"):
        with st.expander("file validation"):
            st.json(j["validation"], expanded=False)
    if j.get("sources"):
        st.caption("Sources: " + " · ".join(f"[{s['tag']}] {s['file_name']} {_loc(s.get('loc') or {})}" for s in j["sources"][:8]))
    used, naive = j["usage"]["prompt_tokens"], j.get("naive_tokens") or 0
    pct = min(1.0, used / naive) if naive else 0.0
    st.progress(pct, text=f"context used: {fmt_tok(used)} of {fmt_tok(naive)} tokens if every file were sent ({j.get('saving_pct', 0)}% saved) · "
                          f"{j['usage']['total_tokens']:,} tokens · {j['usage']['llm_calls']} calls · {j['elapsed_s']}s · files: {', '.join(j.get('files_used') or []) or 'whole workspace'}")
    with st.expander("plan & usage (JSON)"):
        st.json({"plan": j.get("plan"), "usage": j.get("usage")}, expanded=False)


# previous turns persisted with the workspace (shown compactly when this browser session is new)
if not history and ws.chat:
    for t in ws.chat:
        with st.chat_message("user"):
            st.markdown(t["q"])
        with st.chat_message("assistant"):
            st.markdown(f"{STRATEGY_BADGE.get(t['strategy'], t['strategy'])} · {t['summary']}")
for i, turn in enumerate(history):
    with st.chat_message("user"):
        st.markdown(turn["q"])
    with st.chat_message("assistant"):
        render_reply(turn["resp"], i)


def _queue_example() -> None:
    v = st.session_state.get(pill_key)
    if v:
        st.session_state[queue_key] = v


st.pills("Try one", EXAMPLES, selection_mode="single", key=pill_key, on_change=_queue_example)
prompt = st.chat_input("Ask, cross-audit, edit or generate…", disabled=not settings.llm_configured)
message = prompt or st.session_state.pop(queue_key, None)
if message:
    with st.chat_message("user"):
        st.markdown(message)
    with st.chat_message("assistant"):
        with st.spinner("Planning from the manifest → running one focused strategy…"):
            try:
                resp = engine.chat(ws, message)
            except Exception as e:  # noqa: BLE001
                resp = {"strategy": "qa", "answer": f"Failed: {type(e).__name__}: {e}", "usage": {"prompt_tokens": 0, "total_tokens": 0, "llm_calls": 0}, "elapsed_s": 0, "plan": {}}
        render_reply(resp, len(history))
    history.append({"q": message, "resp": resp})
    if resp.get("artifacts"):
        st.rerun()
