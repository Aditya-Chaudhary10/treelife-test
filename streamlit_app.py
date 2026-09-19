"""Entry point. Run: streamlit run streamlit_app.py"""
import _bootstrap  # noqa: F401  (secrets -> env, sys.path)

import streamlit as st

st.set_page_config(page_title="Treelife AI — Technical Assessment", page_icon="🌳", layout="wide", initial_sidebar_state="expanded")

st.markdown(
    """
<style>
  .block-container { padding-top: 2.2rem; }
  .hero h1 { font-size: 2.5rem; font-weight: 750; letter-spacing: -0.02em; margin: 0 0 .4rem; }
  .hero p { font-size: 1.12rem; color: #9fb3c8; max-width: 900px; margin: 0 0 1rem; }
  .tag { display:inline-block; padding:.2rem .6rem; border-radius:999px; background:#173b3a; color:#5eead4; font-size:.8rem; font-weight:600; margin: 0 .4rem .8rem 0; }
  .fact { border:1px solid #1f2a44; border-radius:12px; padding:.9rem 1rem; background:#111a2e; height:100%; }
  .fact b { display:block; font-size:1.02rem; margin-bottom:.2rem; }
  .fact span { color:#9fb3c8; font-size:.9rem; }
  .foot { color:#6b7a90; font-size:.85rem; margin-top:2.5rem; }
  .foot a { color:#9fb3c8; }
  .answer { font-size:1.45rem; font-weight:650; line-height:1.35; margin:.3rem 0 .6rem; }
  div[data-testid="stMetricValue"] { font-size:1.6rem; }
</style>
""",
    unsafe_allow_html=True,
)

pages = [
    st.Page("views/home.py", title="Overview", icon="🌳", default=True),
    st.Page("views/task1.py", title="Task 1 · Semantic Layer", icon="🔎"),
    st.Page("views/task2.py", title="Task 2 · Document Workspace", icon="📁"),
]
st.navigation(pages).run()
