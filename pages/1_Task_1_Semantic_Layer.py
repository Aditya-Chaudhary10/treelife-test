"""Task 1 UI — connect a source, see what the layer learned, ask questions."""
import _bootstrap  # noqa: F401

import json

import pandas as pd
import streamlit as st

from shared.config import settings
from task1.adapters.base import ConnectorError
from task1.adapters.registry import SOURCES

st.set_page_config(page_title="Task 1 · Semantic Layer", page_icon="🔎", layout="wide")

EXAMPLES = {
    "mock_crm": ["How many open deals does Garima own?", "Which deals are lost?", "Total value of open deals per owner",
                 "How many high priority deals does Ishan have?", "Leads assigned to Ishan", "How many deals in the London region?",
                 "Deals owned by Garmia in negotiation", "How many deals were created after June 2026?"],
    "mock_jira": ["How many tickets are assigned to Ishan?", "How many completed tickets does Garima have?", "Which tickets were abandoned?",
                  "Open high priority bugs", "Tickets per assignee"],
}
DEFAULT_EXAMPLES = ["How many open deals does Garima own?", "Which records are high priority?", "Records per owner"]


@st.cache_resource(show_spinner=False)
def get_engine():
    from task1.engine import engine

    return engine


def rule_text(d, fld) -> str:
    if isinstance(d, list):
        return f"{fld} ∈ {{{', '.join(d)}}}"
    if "all" in d:
        return " AND ".join(rule_text(x, fld) for x in d["all"])
    if "any" in d:
        return "(" + " OR ".join(rule_text(x, fld) for x in d["any"]) + ")"
    if "not" in d:
        return "NOT " + rule_text(d["not"], fld)
    if d.get("field"):
        if "in" in d:
            return f"{d['field']} ∈ {{{', '.join(d['in'])}}}"
        if "not_in" in d:
            return f"{d['field']} ∉ {{{', '.join(d['not_in'])}}}"
        if d.get("is_empty"):
            return f"{d['field']} is empty"
        if d.get("not_empty"):
            return f"{d['field']} is filled"
    return json.dumps(d)


# ----------------------------------------------------------------------------- sidebar: connect
with st.sidebar:
    st.markdown("### 1 · Connect a tool")
    source = st.selectbox("Source", list(SOURCES), format_func=lambda k: SOURCES[k]["label"])
    st.caption(SOURCES[source]["description"])
    cfg = {}
    for f in SOURCES[source]["fields"]:
        cfg[f["name"]] = st.text_input(f["label"], value=f.get("default", ""), type="password" if f.get("secret") else "default", key=f"t1cfg_{source}_{f['name']}")
    force = st.checkbox("Force re-map (ignore cached map)", value=False)
    if st.button("Connect & discover", type="primary", width="stretch", disabled=not settings.llm_configured):
        try:
            with st.spinner("Fetching schema + records → profiling → building the semantic map…"):
                conn = get_engine().connect(source, cfg, force_remap=force)
            st.session_state["t1_conn"] = conn.id
            st.session_state["t1_history"] = []
            st.session_state["t1_just_connected"] = True
        except ConnectorError as e:
            st.error(str(e))
        except Exception as e:  # noqa: BLE001
            st.error(f"{type(e).__name__}: {e}")
    if not settings.llm_configured:
        st.warning("Set `LLM_API_KEY` (in `.env` locally or Streamlit secrets) to enable the layer.", icon="🔑")

engine = get_engine()
conn = None
if st.session_state.get("t1_conn"):
    try:
        conn = engine.get(st.session_state["t1_conn"])
    except KeyError:
        st.session_state.pop("t1_conn", None)

st.title("🔎 Semantic Business Data Translation Layer")

if conn is None:
    st.markdown(
        "Pick a source in the sidebar and click **Connect & discover**. The layer will fetch the schema and records, "
        "profile how every field is really used, and build a *semantic map* of where each business concept lives for this client. "
        "Then ask anything in plain English."
    )
    c1, c2, c3 = st.columns(3)
    c1.info("**Discover** — fill rates, constant fields, unused options, hand-typed spellings", icon="1️⃣")
    c2.info("**Map** — concept → field with evidence, cross-field rules (`open = status∈{Open} AND stage∉{Dead Leads}`)", icon="2️⃣")
    c3.info("**Answer** — deterministic execution, explained; zero results diagnosed, missing concepts flagged", icon="3️⃣")
    st.stop()

# ----------------------------------------------------------------------------- what it learned
summary = conn.summary()
m1, m2, m3, m4 = st.columns(4)
m1.metric("Source", SOURCES[conn.source]["kind"])
m2.metric("Collections", len(summary["collections"]))
m3.metric("Records", sum(c["records"] for c in summary["collections"]))
m4.metric("Map built with", "cache" if summary["map_from_cache"] else f"{summary['discovery_usage'].get('total_tokens', 0):,} tokens")

smap, profiles = conn.semantic_map, conn.profiles_dict()
with st.expander("2 · What the system learned about this client", expanded=st.session_state.pop("t1_just_connected", False)):
    for cname, cm in smap["collections"].items():
        fields = {f["name"]: f for f in profiles.get(cname, {}).get("fields", [])}
        st.markdown(f"**`{cname}`** — {cm.get('description', '')}")
        rows = []
        for concept, spec in cm.get("concepts", {}).items():
            f = fields.get(spec["field"], {})
            usage = ""
            if spec.get("value_map"):
                usage = "; ".join(f"{k} = {rule_text(d, spec['field'])}" for k, d in spec["value_map"].items())
            rows.append({
                "concept": concept, "lives in": spec["field"], "field type": "custom" if f.get("is_custom") else "built-in",
                "kind": spec.get("kind", ""), "confidence": float(spec.get("confidence", 0)), "how values are read": usage, "evidence": spec.get("evidence", ""),
            })
        if rows:
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True,
                         column_config={"confidence": st.column_config.ProgressColumn("confidence", min_value=0, max_value=1, format="%.2f")})
        missing = cm.get("missing_concepts") or {}
        if missing:
            st.caption("Not tracked here: " + "; ".join(f"**{k}** ({v})" for k, v in missing.items()))
        for n in cm.get("notes", []):
            st.caption("• " + n)
    people = {k: v for k, v in (smap.get("people") or {}).items() if any(len(p["aliases"]) > 1 for p in v)}
    if people:
        st.markdown("**People and how they are spelled**")
        for key, plist in people.items():
            st.caption(f"`{key}`")
            for p in plist:
                if len(p["aliases"]) > 1:
                    st.markdown(f"- **{p['canonical']}** ({p['records']} records) ← " + ", ".join(f'"{a}"' for a in p["aliases"]))
    with st.expander("raw semantic map (JSON)"):
        st.json(smap, expanded=False)

# ----------------------------------------------------------------------------- ask
st.markdown("### 3 · Ask in plain English")
examples = EXAMPLES.get(conn.source, DEFAULT_EXAMPLES)
picked = st.pills("Try one", examples, selection_mode="single", key=f"t1_pills_{conn.id}")
question = st.text_input("Question", value=picked or "", placeholder="How many open deals does Garima own?", key=f"t1_q_{conn.id}", label_visibility="collapsed")
ask = st.button("Ask", type="primary")

if ask and question.strip():
    try:
        with st.spinner("Understanding intent → binding to this client's fields → executing → explaining…"):
            resp = engine.ask(conn.id, question.strip())
        st.session_state.setdefault("t1_history", []).insert(0, resp)
    except Exception as e:  # noqa: BLE001
        st.error(f"{type(e).__name__}: {e}")

BADGE = {"answer": ":green[**answered from data**]", "empty_with_reason": ":orange[**nothing matched — here's why**]", "unanswerable": ":red[**can't be answered from this data**]"}


def render(a: dict) -> None:
    with st.container(border=True):
        st.caption(f"Q: {a['question']}")
        st.markdown(f"{BADGE.get(a['answer_type'], a['answer_type'])} · confidence {int(a.get('confidence', 0) * 100)}% · "
                    f"{a['usage']['total_tokens']:,} tokens · {a['usage']['llm_calls']} LLM calls · {a['elapsed_s']}s")
        st.markdown(f"### {a['answer']}")
        res = a.get("result") or {}
        if res.get("groups"):
            st.dataframe(pd.DataFrame(res["groups"], columns=["group", "value"]), hide_index=True, width="stretch")
        st.markdown("**How I got this**")
        for i, s in enumerate(a.get("steps", []), start=1):
            st.markdown(f"{i}. {s}")
        for p in a.get("problems", []):
            st.error(p)
        zd = a.get("zero_diagnosis")
        if zd:
            st.warning("**Why zero:** " + zd["message"])
            if zd.get("distribution"):
                st.dataframe(pd.DataFrame(zd["distribution"], columns=[zd.get("field", "value"), "records"]), hide_index=True)
        for c in a.get("context", []):
            with st.expander(c["title"]):
                st.dataframe(pd.DataFrame(c["distribution"], columns=["value", "records"]), hide_index=True)
        rows = res.get("matched_preview") or []
        if rows:
            with st.expander(f"matched records (showing {len(rows)} of {res.get('count', len(rows))})"):
                df = pd.DataFrame(rows)
                drop = [c for c in df.columns if c in ("id", "update_time", "pipeline", "currency", "probability", "won_time", "lost_time")]
                st.dataframe(df.drop(columns=drop), width="stretch", hide_index=True)
        with st.expander("plan & intent (JSON)"):
            st.json({"intent": a.get("intent"), "plan": a.get("plan"), "usage": a.get("usage")}, expanded=False)


for a in st.session_state.get("t1_history", []):
    render(a)
