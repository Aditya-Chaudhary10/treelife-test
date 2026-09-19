"""Landing page. Run: streamlit run streamlit_app.py"""
import _bootstrap  # noqa: F401  (secrets -> env, sys.path)

import streamlit as st

from shared.config import settings

st.set_page_config(page_title="Treelife AI — Technical Assessment", page_icon="🌳", layout="wide", initial_sidebar_state="expanded")

st.markdown(
    """
<style>
  .hero { padding: 2.2rem 0 1.2rem; }
  .hero h1 { font-size: 2.6rem; font-weight: 750; letter-spacing: -0.02em; margin: 0 0 .4rem; }
  .hero p { font-size: 1.15rem; color: #9fb3c8; max-width: 900px; margin: 0; }
  .tag { display:inline-block; padding:.2rem .6rem; border-radius:999px; background:#173b3a; color:#5eead4; font-size:.8rem; font-weight:600; margin-right:.4rem; }
  .fact { border:1px solid #1f2a44; border-radius:12px; padding:.9rem 1rem; background:#111a2e; height:100%; }
  .fact b { display:block; font-size:1.05rem; margin-bottom:.2rem; }
  .fact span { color:#9fb3c8; font-size:.9rem; }
  .foot { color:#6b7a90; font-size:.85rem; margin-top:2.5rem; }
  .foot a { color:#9fb3c8; }
</style>
<div class="hero">
  <span class="tag">Treelife AI</span><span class="tag">Technical assessment</span>
  <h1>Two systems that stay trustworthy when the data is messy</h1>
  <p>A semantic layer that answers plain-English questions over any CRM the way <em>this</em> client actually uses it,
  and a document workspace where 50 files are uploaded once and every follow-up costs a fraction of re-reading them.</p>
</div>
""",
    unsafe_allow_html=True,
)

if not settings.llm_configured:
    st.warning("No LLM key configured. Locally: put `LLM_API_KEY` in `.env`. On Streamlit Cloud: add it under *Settings → Secrets*.", icon="🔑")

left, right = st.columns(2, gap="large")
with left:
    with st.container(border=True):
        st.markdown("### 🔎 Task 1 · Semantic Business Data Translation Layer")
        st.markdown(
            "Connect a CRM or project tool (or the built-in messy demo). The layer **discovers how the client really uses it** — "
            "owners hand-typed in a custom field, lost deals parked in a *Dead Leads* folder, priority hidden in tags — "
            "then answers questions in everyday language **with its reasoning**, or explains honestly why the data can't answer."
        )
        st.markdown("- *“How many open deals does Garima own?”* → **14**, with the evidence chain\n- typos and nicknames resolved · zero results diagnosed · missing concepts flagged\n- Pipedrive · HubSpot · Jira · CSV exports, one 80-line connector each")
        st.page_link("pages/1_Task_1_Semantic_Layer.py", label="Open Task 1", icon="➡️")
with right:
    with st.container(border=True):
        st.markdown("### 📁 Task 2 · Enterprise Document Workspace")
        st.markdown(
            "Upload PDFs, Word and Excel files **once** (duplicates are detected by hash). Ask cross-file questions with citations, "
            "run **SQL over spreadsheets**, **cross-audit** one document against the rest, **edit Word/Excel in place without corruption**, "
            "and generate new documents — every turn shows its token cost against the naive “send everything” baseline."
        )
        st.markdown("- planner sees a 1-line manifest per file, never the files\n- edits are operations applied by code, validated, versioned\n- hidden sheets and formulas are found, kept and protected")
        st.page_link("pages/2_Task_2_Document_Workspace.py", label="Open Task 2", icon="➡️")

st.markdown("#### How it is built")
f1, f2, f3, f4 = st.columns(4)
for col, title, body in (
    (f1, "Any OpenAI-compatible LLM", "Groq gpt-oss by default; swap provider with one variable. Every call is metered and budgeted."),
    (f2, "Local embeddings", "fastembed on CPU — hybrid BM25 + vectors with no embedding bill and no vector database."),
    (f3, "Deterministic where it matters", "Counting, filtering, SQL and file edits are done by code; the model plans, maps and explains."),
    (f4, "Files never corrupted", "Word/Excel edits are validated against the original; originals are kept; risky workbooks are refused."),
):
    col.markdown(f'<div class="fact"><b>{title}</b><span>{body}</span></div>', unsafe_allow_html=True)

st.markdown('<div class="foot">Built by Aditya Chaudhary · <a href="https://github.com/Aditya-Chaudhary10/treelife-test">Source on GitHub</a></div>', unsafe_allow_html=True)
