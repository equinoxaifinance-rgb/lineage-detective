"""Lineage Detective's Streamlit judge surface.

The UI makes the control boundary visible: investigation and catalog containment are one flow;
repair is a separate proposal -> human approval -> sandbox-only verification flow.  Nothing here
can apply a production change.
"""
import base64
import html
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import streamlit as st
from agent import investigate  # noqa: E402
from repair import execute_sandbox_trial, receipt_for_display  # noqa: E402
from setup_vocab import ensure_incident_vocabulary  # noqa: E402


@st.cache_resource(show_spinner=False)
def _vocab_ready(server_url: str, token: str | None) -> str:
    """Create the two incident tags once when containment is requested."""
    try:
        ensure_incident_vocabulary(server_url, token=token or None)
        return "ok"
    except Exception as exc:
        return f"skipped ({type(exc).__name__})"


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

MASCOT = Path(__file__).with_name("assets") / "lineage-detective-mascot.png"


@st.cache_data(show_spinner=False)
def _mascot_data_uri() -> str | None:
    """Keep the judge UI resilient if an asset is absent from a local checkout."""
    try:
        return "data:image/png;base64," + base64.b64encode(MASCOT.read_bytes()).decode("ascii")
    except OSError:
        return None


_STAGE_COPY = {
    "ready": ("Live catalog investigator", "Start with a symptom. The detective will only use DataHub evidence."),
    "connecting": ("Opening the evidence line", "Connecting to the official DataHub MCP server."),
    "evidence": ("Walking the lineage", "Reading the affected asset and its live upstream dependencies."),
    "reasoning": ("Separating signal from guesswork", "The diagnosis is being constrained to the returned catalog evidence."),
    "containment": ("Verifying catalog tags", "Writing through MCP and reading back before any containment claim."),
    "repair": ("Preparing a reversible proposal", "Any code change remains sandbox-only until a person approves it."),
    "visualizing": ("Mapping the evidence trail", "Rendering the actual lineage path used by the investigation."),
    "complete": ("Evidence report ready", "The result below separates facts, actions, and remaining uncertainty."),
}


def _detective_html(phase: str = "ready", detail: str | None = None) -> str:
    """A compact, animated status companion—not a fake progress display."""
    title, default_detail = _STAGE_COPY.get(phase, _STAGE_COPY["ready"])
    image = _mascot_data_uri()
    visual = (f'<img class="ld-mascot" alt="Lineage Detective" src="{image}">' if image
              else '<div class="ld-fallback">LD</div>')
    tags = "" if phase != "containment" else (
        '<span class="ld-tag ld-tag-one">QUARANTINE</span>'
        '<span class="ld-tag ld-tag-two">IMPACT</span>'
    )
    return f"""
<style>
@keyframes ld-float {{ 0%,100%{{transform:translateY(0) rotate(-1deg)}} 50%{{transform:translateY(-8px) rotate(1deg)}} }}
@keyframes ld-scan {{ 0%{{transform:scale(.74);opacity:.75}} 100%{{transform:scale(1.25);opacity:0}} }}
@keyframes ld-drop {{ 0%{{opacity:0;transform:translateY(-18px) scale(.7)}} 55%{{opacity:1}} 100%{{opacity:1;transform:translateY(0) scale(1)}} }}
.ld-hero {{ position:relative; overflow:hidden; display:flex; align-items:center; gap:14px; min-height:120px;
  margin:4px 0 14px; padding:12px 16px; border:1px solid #1e3a5f; border-radius:16px;
  background:radial-gradient(circle at 12% 50%,#102a43 0,#08111f 45%,#050a13 100%); color:#e5eefb; }}
.ld-hero:after {{ content:""; position:absolute; inset:0; pointer-events:none; opacity:.25;
  background:linear-gradient(115deg,transparent 30%,#22d3ee12 50%,transparent 70%); }}
.ld-visual {{ position:relative; width:104px; min-width:104px; height:94px; z-index:1; display:grid; place-items:center; }}
.ld-mascot {{ width:106px; height:106px; object-fit:contain; animation:ld-float 3.2s ease-in-out infinite; filter:drop-shadow(0 10px 12px #0009); }}
.ld-fallback {{ width:68px;height:68px;border-radius:50%;display:grid;place-items:center;background:#0f2847;border:2px solid #22d3ee;color:#fbbf24;font-weight:900; }}
.ld-copy {{ position:relative; z-index:1; min-width:0; }}
.ld-kicker {{ color:#67e8f9; font:700 11px/1.2 ui-monospace,SFMono-Regular,Menlo,monospace; letter-spacing:.11em; text-transform:uppercase; }}
.ld-title {{ margin:4px 0 3px; color:#f8fafc; font:800 19px/1.1 system-ui,sans-serif; }}
.ld-detail {{ color:#b6c7df; font:400 13px/1.35 system-ui,sans-serif; }}
.ld-scan {{ position:absolute; width:48px;height:48px;border:1px solid #22d3ee;border-radius:50%; animation:ld-scan 1.4s ease-out infinite; }}
.ld-tag {{ position:absolute; right:-4px; padding:3px 6px; border-radius:99px; background:#164e63; border:1px solid #22d3ee; color:#cffafe; font:800 9px/1 ui-monospace,monospace; animation:ld-drop .48s ease-out both; }}
.ld-tag-one {{ top:17px; }} .ld-tag-two {{ top:43px; animation-delay:.16s; background:#3f2412; border-color:#fbbf24; color:#fef3c7; }}
.ld-complete .ld-mascot {{ animation:none; }} .ld-complete .ld-scan {{ display:none; }}
div.stButton > button[kind="primary"] {{ background:linear-gradient(110deg,#0891b2,#2563eb) !important; border:1px solid #67e8f9 !important; color:#f8fafc !important; border-radius:10px !important; font-weight:750 !important; box-shadow:0 7px 18px #082f4966; }}
div.stButton > button[kind="primary"]:hover {{ border-color:#fbbf24 !important; color:#fff !important; box-shadow:0 9px 22px #0e749080; }}
@media (max-width:560px) {{ .ld-hero{{gap:8px;padding:10px}} .ld-visual{{width:78px;min-width:78px}} .ld-mascot{{width:86px;height:86px}} .ld-title{{font-size:16px}} }}
</style>
<section class="ld-hero ld-{phase}" aria-label="Lineage Detective status">
  <div class="ld-visual">{visual}<span class="ld-scan"></span>{tags}</div>
  <div class="ld-copy"><div class="ld-kicker">Lineage Detective · live evidence path</div>
  <div class="ld-title">{title}</div><div class="ld-detail">{detail or default_detail}</div></div>
</section>
"""


def _render_detective(slot, phase: str = "ready", detail: str | None = None) -> None:
    slot.markdown(_detective_html(phase, detail), unsafe_allow_html=True)


def _asset_label(urn: str) -> str:
    parts = urn.rsplit("(", 1)[-1].rstrip(")").split(",")
    return parts[-2] if len(parts) >= 2 else urn


def _render_investigation(report: dict) -> None:
    if report.get("reasoning_mode") == "evidence_only_deterministic":
        st.info("Evidence-only judge mode: this run used real DataHub MCP evidence and deterministic checks. "
                "It is intentionally read-only and does not claim model reasoning.")
    st.success(f"Traced {report.get('_evidence_nodes', '?')} entities through live DataHub lineage.")
    dot = report.get("lineage_dot")
    if dot:
        st.subheader("Lineage the agent walked")
        st.caption("Live MCP lineage: symptom → root cause → downstream blast radius.")
        st.graphviz_chart(dot, width="stretch")

    st.subheader("Diagnosis")
    st.write(report.get("summary", ""))
    st.subheader("Ranked root-cause suspects")
    for index, suspect in enumerate(report.get("suspects", []), 1):
        # These values originate in catalog/model output and enter an HTML card below.
        # Escape them before interpolation so a catalog description cannot become markup.
        suspect = dict(suspect)
        for key in ("owner", "why", "check_next"):
            suspect[key] = html.escape(str(suspect.get(key) or ""), quote=True)
        suspect["asset_label"] = html.escape(_asset_label(suspect.get("urn", "")), quote=True)
        bg, fg, label = _CONF.get(str(suspect.get("confidence", "")).lower(), ("#374151", "#d1d5db", "?"))
        st.markdown(
            f"<div style='background:{bg};border-radius:10px;padding:14px;margin:8px 0'>"
            f"<span style='color:{fg};font-weight:800'>#{index} · {label}</span> "
            f"<span style='color:#e5e7eb;font-weight:700'>{suspect['asset_label']}</span> "
            f"<span style='color:#9ca3af'>→ contact: {suspect.get('owner') or 'owner unknown'}</span><br>"
            f"<span style='color:#e5e7eb'><b>Evidence:</b> {suspect.get('why', '')}</span><br>"
            f"<span style='color:#cbd5e1'><b>Check next:</b> {suspect.get('check_next', '')}</span>"
            f"</div>", unsafe_allow_html=True)

    action = report.get("action")
    if action:
        if action.get("applied"):
            st.success(f"Contained in DataHub: `{_asset_label(action['urn'])}` was tagged "
                       "`QUARANTINE_INCIDENT`, then read back through MCP.")
        else:
            st.warning("Containment was attempted but the tag write was not confirmed. No write is claimed.")
    blast = report.get("blast_radius")
    if blast:
        st.error(f"Blast radius: {blast.get('impacted_count', 0)} downstream assets; "
                 f"{blast.get('tagged', 0)} tag writes confirmed.")
        columns = st.columns(2)
        with columns[0]:
            st.markdown("**Dashboards**\n\n" + ("\n".join(f"- {x}" for x in blast.get("dashboards", [])) or "_none_"))
        with columns[1]:
            st.markdown("**Data assets**\n\n" + ("\n".join(f"- {x}" for x in blast.get("assets", [])) or "_none_"))

    if report.get("missing_evidence"):
        with st.expander("What would confirm this?"):
            st.write(report["missing_evidence"])


def _render_repair(report: dict) -> None:
    repair = report.get("repair")
    if not repair:
        return
    st.divider()
    st.subheader("Repair-and-verify")
    if repair.get("state") == "not_applicable":
        st.info("No code repair is proposed for this incident. This class needs an upstream data fix, "
                "not a model edit.")
        return
    if repair.get("state") in {"proposal_failed", "proposal_rejected"}:
        st.warning(repair.get("error") or repair.get("reason") or "Repair proposal unavailable.")
        return
    if repair.get("state") != "approval_required":
        st.warning(f"Repair state: {repair.get('state', 'unknown')}")
        return

    st.info("A repair was proposed from the diagnosis and schemas. It has not run anywhere yet.")
    st.caption(repair.get("rationale") or "No additional rationale returned.")
    st.code(repair.get("diff", ""), language="diff")
    st.warning("Sandbox only — never production. A passing sandbox result is evidence, not a production guarantee.")
    with st.expander("Representativeness boundary", expanded=False):
        st.write(repair.get("representativeness", ""))

    approved = st.checkbox(
        "I approve this exact diff for one isolated sandbox trial (not production).",
        key=f"approve-{repair.get('repair_id', 'current')}",
    )
    if st.button("Run approved sandbox trial", type="primary", disabled=not approved,
                 width="stretch", key=f"trial-{repair.get('repair_id', 'current')}"):
        status = st.status("Starting the isolated sandbox trial...", expanded=True)
        bar = st.progress(8, text="Resetting the disposable sandbox. No production connector exists in this path.")
        bar.progress(45, text="Running dbt and checking the real assertion before and after the proposed change...")
        st.session_state["repair_receipt"] = execute_sandbox_trial(
            repair, approval="interactive-ui-approval"
        )
        receipt = st.session_state["repair_receipt"]
        if receipt.get("verified"):
            bar.progress(100, text="Verified in the isolated sandbox; rollback was checked.")
            status.update(label="Sandbox receipt verified", state="complete", expanded=False)
        else:
            bar.progress(100, text="The sandbox run completed without a verified repair. No production claim was made.")
            status.update(label="Sandbox receipt needs review", state="error", expanded=True)

    receipt = st.session_state.get("repair_receipt")
    if receipt and receipt.get("repair_id") == repair.get("repair_id"):
        st.subheader("Sandbox receipt")
        before, after = receipt.get("before") or {}, receipt.get("after") or {}
        metrics = st.columns(3)
        metrics[0].metric("Before", f"{before.get('filled', '?')}/{before.get('total', '?')}",
                          "FAIL expected" if before and not before.get("passed") else None)
        metrics[1].metric("After", f"{after.get('filled', '?')}/{after.get('total', '?')}",
                          "PASS" if after.get("passed") else "not verified")
        metrics[2].metric("Rollback", "confirmed" if receipt.get("rollback_verified") else "not confirmed")
        if receipt.get("verified"):
            st.success("Sandbox trial verified: the assertion flipped from FAIL to PASS. The patch was not applied to production.")
        else:
            st.error(receipt.get("error") or "Sandbox trial did not verify. No production claim is made.")
        st.download_button("Download JSON receipt", receipt_for_display(receipt),
                           file_name="lineage-detective-sandbox-receipt.json", mime="application/json")
        with st.expander("Full receipt"):
            st.code(receipt_for_display(receipt), language="json")


st.title("🕵️ Lineage Detective")
st.caption("Data-incident investigation, containment, and approval-gated sandbox repair through DataHub.")
detective_status = st.empty()
_render_detective(detective_status)
st.markdown(
    "<div style='background:#0b1220;border:1px solid #1e293b;border-radius:8px;padding:9px 12px;"
    "margin:-4px 0 12px;color:#bfdbfe;font-size:.9rem'><b>Truth boundary:</b> DataHub MCP supplies "
    "lineage and metadata; model-backed mode reasons over it, while no-key judge mode applies disclosed "
    "deterministic checks. Confirmed incidents can be contained only from the model-backed lane. Any code repair is a human-approved, isolated sandbox trial — never an automatic "
    "production change.</div>", unsafe_allow_html=True)

with st.sidebar:
    st.header("Connection")
    server = st.text_input("DataHub server", value=os.environ.get("DATAHUB_SERVER", "http://localhost:8080"))
    token = st.text_input("DataHub token (optional for local DataHub)", type="password")
    max_hops = st.slider("Max upstream hops", 1, 6, 3)
    model_available = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if model_available:
        st.success("Model-backed reasoning available for this process.")
    else:
        st.info("Free judge mode: real DataHub MCP evidence + deterministic anomaly checks. No API key required; read-only by design.")
    contain = st.checkbox("Write verified containment tags to DataHub", value=False,
                          disabled=not model_available,
                          help="Optional model-backed action: writes quarantine/impact tags through MCP and reads them back to confirm. Evidence-only judge mode is intentionally read-only.")
    st.caption("No token is stored by this app. A private cloud tenant may require one.")

example = st.selectbox("Start from an example incident", list(EXAMPLES.keys()))
symptom = st.text_area("What looks wrong?", value=EXAMPLES[example][0], height=90)
affected = st.text_input("Affected asset URN", value=EXAMPLES[example][1])

if st.button("Investigate", type="primary", width="stretch"):
    def _run_investigation() -> None:
        status = st.status("Preparing investigation...", expanded=True)
        bar = st.progress(3, text="Starting a live evidence path; no diagnosis has been made yet.")
        checkpoints = {
            "connecting": (15, "Connecting to DataHub through its official MCP server..."),
            "evidence": (35, "Reading live lineage and metadata. This can take a moment on a new catalog..."),
            "reasoning": (58, "Evidence is in. Grounding the diagnosis in the returned DataHub facts..."),
            "containment": (74, "Confirming catalog containment through MCP readback..."),
            "repair": (86, "Checking for a reviewable, sandbox-only repair proposal..."),
            "visualizing": (94, "Rendering the lineage path used as evidence..."),
            "complete": (100, "Evidence report ready."),
        }

        def show_progress(phase: str, detail: str) -> None:
            percent, default = checkpoints.get(phase, (10, detail))
            bar.progress(percent, text=detail or default)
            status.write(detail or default)
            _render_detective(detective_status, phase, detail or default)

        try:
            if contain:
                bar.progress(9, text="Checking the incident-tag vocabulary used for verified containment...")
                status.write("Checking the incident-tag vocabulary used for verified containment...")
                vocab = _vocab_ready(server, token or None)
                if vocab != "ok":
                    status.write(f"Vocabulary setup {vocab}; the report will state whether any write was actually confirmed.")
            st.session_state["report"] = investigate(
                symptom, affected, server=server, token=token or None, max_hops=max_hops, act=contain,
                on_progress=show_progress, reasoning_mode="auto",
            )
            st.session_state.pop("repair_receipt", None)
            status.update(label="Evidence report ready", state="complete", expanded=False)
            _render_detective(detective_status, "complete")
        except Exception as exc:
            bar.progress(100, text="Investigation stopped before a report could be verified.")
            status.update(label="Investigation stopped", state="error", expanded=True)
            _render_detective(detective_status, "ready", "The investigation stopped before a report could be verified. Review the recoverable error below.")
            st.error(f"Investigation failed: {type(exc).__name__}: {exc}")

    _run_investigation()

if st.session_state.get("report"):
    _render_investigation(st.session_state["report"])
    _render_repair(st.session_state["report"])
