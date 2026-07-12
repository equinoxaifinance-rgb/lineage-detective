"""app.py — Lineage Detective web UI (Streamlit).

The demo the judges see: type a symptom, watch the agent walk DataHub lineage and return a ranked
root-cause report with the owner to contact. Run:  streamlit run app.py
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import streamlit as st
from agent import investigate  # noqa: E402

st.set_page_config(page_title="Lineage Detective", page_icon="🕵️", layout="centered")

_CONF = {"high": ("#7f1d1d", "#fca5a5", "HIGH"),
         "medium": ("#78350f", "#fcd34d", "MEDIUM"),
         "low": ("#374151", "#d1d5db", "LOW")}

EXAMPLES = {
    "Revenue dashboard dropped 40% (silent partial load)": (
        "The Revenue Overview dashboard shows a ~40% drop in daily revenue since yesterday, "
        "but nothing in the pipeline reported an error.",
        "urn:li:dataset:(urn:li:dataPlatform:looker,bi.revenue_overview,PROD)"),
    "Customer 360 emails went blank (schema drift)": (
        "The Customer 360 dashboard shows blank/null email for most customers since yesterday, no errors.",
        "urn:li:dataset:(urn:li:dataPlatform:looker,bi.customer_360,PROD)"),
    "Finance USD revenue looks frozen (stale data)": (
        "USD-converted revenue on the Finance dashboard looks frozen — it hasn't changed in days.",
        "urn:li:dataset:(urn:li:dataPlatform:looker,bi.finance_fx,PROD)"),
}

st.title("🕵️ Lineage Detective")
st.caption("Autonomous data-incident root-cause analysis, built with **DataHub**. "
           "Describe the symptom — the agent traces your lineage and finds the cause.")

with st.sidebar:
    st.header("Connection")
    server = st.text_input("DataHub server", value=os.environ.get("DATAHUB_SERVER", "http://localhost:8080"))
    max_hops = st.slider("Max upstream hops", 1, 6, 3)
    st.markdown("---")
    st.markdown("The agent reads **live** lineage + metadata from DataHub. It never invents facts — "
                "the LLM only reasons over what DataHub actually returns.")

ex = st.selectbox("Start from an example incident", list(EXAMPLES.keys()))
symptom = st.text_area("Symptom", value=EXAMPLES[ex][0], height=90)
affected = st.text_input("Affected asset (URN)", value=EXAMPLES[ex][1])

if st.button("🔍 Investigate", type="primary", use_container_width=True):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        st.error("ANTHROPIC_API_KEY not set in the environment running Streamlit.")
        st.stop()
    with st.spinner("Walking DataHub lineage upstream and reasoning over the evidence…"):
        try:
            report = investigate(symptom, affected, server=server, max_hops=max_hops, act=True)
        except Exception as e:
            st.error(f"Investigation failed: {e}")
            st.stop()

    st.success(f"Traced {report.get('_evidence_nodes','?')} upstream entities via DataHub lineage.")
    st.subheader("Summary")
    st.write(report.get("summary", ""))

    st.subheader("Root-cause suspects (ranked)")
    for i, s in enumerate(report.get("suspects", []), 1):
        bg, fg, label = _CONF.get(str(s.get("confidence", "")).lower(), ("#374151", "#d1d5db", "?"))
        name = s.get("urn", "").rsplit("(", 1)[-1].rstrip(")").split(",")
        name = name[-2] if len(name) >= 2 else s.get("urn", "")
        owner = s.get("owner") or "owner unknown"
        st.markdown(
            f"<div style='background:{bg};border-radius:10px;padding:14px;margin:8px 0'>"
            f"<span style='color:{fg};font-weight:800'>#{i} · {label}</span> "
            f"<span style='color:#e5e7eb;font-weight:700'>{name}</span> "
            f"<span style='color:#9ca3af'>→ contact: {owner}</span><br>"
            f"<span style='color:#e5e7eb'><b>Why:</b> {s.get('why','')}</span><br>"
            f"<span style='color:#cbd5e1'><b>Check next:</b> {s.get('check_next','')}</span>"
            f"</div>", unsafe_allow_html=True)

    action = report.get("action")
    if action and action.get("applied"):
        node = action["urn"].rsplit("(", 1)[-1].rstrip(")").split(",")
        node = node[-2] if len(node) >= 2 else action["urn"]
        st.subheader("Autonomous action taken in DataHub")
        st.markdown(f"🔒 Quarantined **{node}** — tagged `QUARANTINE_INCIDENT` so every downstream "
                    f"consumer is warned in the catalog they already use.")
    br = report.get("blast_radius")
    if br and br.get("impacted_count"):
        st.error(f"💥 **Blast radius: {br['impacted_count']} downstream assets contaminated** "
                 f"({br.get('tagged',0)} tagged IMPACTED)")
        cols = st.columns(2)
        with cols[0]:
            st.markdown("**Dashboards affected**\n\n" + ("\n".join(f"- {d}" for d in br.get("dashboards", [])) or "_none_"))
        with cols[1]:
            st.markdown("**Data assets affected**\n\n" + ("\n".join(f"- {a}" for a in br.get("assets", [])) or "_none_"))

    if report.get("missing_evidence"):
        with st.expander("What would confirm it"):
            st.write(report["missing_evidence"])
