"""Lineage Detective's Streamlit judge surface.

The UI makes the control boundary visible: investigation and catalog containment are one flow;
repair is a proposal -> explicit action -> sandbox verification flow. After verification, the
human can download the evidence packet or atomically apply the exact hash-bound rewrite to a
checked-out dbt model with a recoverable backup.
"""
import base64
import hashlib
import html
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import streamlit as st
from agent import investigate  # noqa: E402
from autonomous_workflow import run_approved_workflow  # noqa: E402
from datahub_mcp import MCPDataHub  # noqa: E402
from datahub_oauth import DATAHUB_GLOBAL_MCP, authorize_datahub  # noqa: E402
from repair import (  # noqa: E402
    BROKEN_SQL,
    apply_verified_repair,
    build_handoff_packet,
    execute_sandbox_trial,
    receipt_for_display,
    restore_applied_repair,
)
from remediation_connectors import (  # noqa: E402
    AirflowConnector,
    DataHubAssertionConnector,
    DbtCloudConnector,
    FivetranConnector,
    GitHubPullRequestConnector,
    JsonTransport,
    SnowflakeSqlConnector,
    failure_receipt,
    run_project_validation,
)
from setup_vocab import ensure_incident_vocabulary  # noqa: E402

MASCOT = Path(__file__).with_name("assets") / "lineage-detective-mascot.png"
DROID_NAME = "Trace"
DEFAULT_JUDGE_ENDPOINT = "https://lineage-detective-judge-gateway.equinoxaifinance.workers.dev"
_VOCAB_READY_SUCCESSES: set[tuple[str, str]] = set()
_WORKFLOW_RESULT_KEYS = (
    "report",
    "repair_receipt",
    "handoff_packet",
    "apply_receipt",
    "deployment_receipt",
    "restore_receipt",
    "autonomous_workflow_result",
    "autonomous_workflow_error",
)


class WorkflowCancelled(RuntimeError):
    """Raised at cooperative checkpoints after the visible cancel action."""


def _local_catalog_preflight(server_url: str, timeout: float = 2.0) -> tuple[bool, str | None]:
    """Fail quickly when the bundled local catalog is down; do not probe private remote tenants."""
    parsed = urlsplit(server_url)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        return True, None
    health_url = f"{server_url.rstrip('/')}/health"
    try:
        request = Request(health_url, headers={"User-Agent": "lineage-detective-preflight"})
        with urlopen(request, timeout=timeout) as response:
            if response.status == 200:
                return True, None
            return False, f"Local DataHub health check returned HTTP {response.status}."
    except Exception as exc:
        return False, (
            "Local DataHub is not ready at "
            f"{server_url}. Start Lineage Detective with run.bat (Windows) or run.sh "
            f"(macOS/Linux), then retry. Health check: {type(exc).__name__}."
        )


def _vocab_ready(server_url: str, token: str | None) -> str:
    """Cache only successful vocabulary setup; a transient failure must remain retryable."""
    credential_scope = hashlib.sha256((token or "").encode("utf-8")).hexdigest()
    cache_key = (server_url.rstrip("/"), credential_scope)
    if cache_key in _VOCAB_READY_SUCCESSES:
        return "ok"
    try:
        ensure_incident_vocabulary(server_url, token=token or None)
        _VOCAB_READY_SUCCESSES.add(cache_key)
        return "ok"
    except Exception as exc:
        return f"skipped ({type(exc).__name__})"


st.set_page_config(page_title="Lineage Detective", page_icon=str(MASCOT), layout="centered")

_CONF = {"high": ("#7f1d1d", "#fca5a5", "HIGH"),
         "medium": ("#78350f", "#fcd34d", "MEDIUM"),
         "low": ("#374151", "#d1d5db", "LOW")}

REPAIR_EXAMPLE = "Customer 360 emails went blank (full repair walkthrough)"
CUSTOM_INCIDENT = "My own DataHub incident"

EXAMPLES = {
    CUSTOM_INCIDENT: ("", ""),
    REPAIR_EXAMPLE: (
        "The Customer 360 dashboard shows blank/null email for most customers since yesterday, no errors.",
        "urn:li:dataset:(urn:li:dataPlatform:looker,bi.customer_360,PROD)"),
    "Revenue dashboard dropped 40% (verified volume guard)": (
        "The Revenue Overview dashboard shows a ~40% drop in daily revenue since yesterday, "
        "but nothing in the pipeline reported an error.",
        "urn:li:dataset:(urn:li:dataPlatform:looker,bi.revenue_overview,PROD)"),
    "Finance USD revenue looks frozen (verified freshness guard)": (
        "USD-converted revenue on the Finance dashboard looks frozen — it hasn't changed in days.",
        "urn:li:dataset:(urn:li:dataPlatform:looker,bi.finance_fx,PROD)"),
}

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
    "repair": ("Drafting a reviewable repair", f"{DROID_NAME} is converting the evidence-bound diagnosis into an exact diff for review and verification."),
    "sandbox": ("Testing the approved change", f"{DROID_NAME} is following real sandbox milestones while the isolated build runs."),
    "handoff": ("Packing the verified change", f"{DROID_NAME} is binding the exact diff and receipt into a human implementation packet."),
    "verified": ("Change verified", "The approved diff passed the isolated assertion and rollback was confirmed."),
    "visualizing": ("Mapping the evidence trail", "Rendering the actual lineage path used by the investigation."),
    "complete": ("Evidence report ready", "The result below separates facts, actions, and remaining uncertainty."),
    "contained": ("Containment confirmed", f"{DROID_NAME} dropped catalog tags through MCP and the app read them back."),
}


def _render_detective(slot, phase: str = "ready", detail: str | None = None) -> None:
    slot.markdown(_workflow_html(phase, detail=detail), unsafe_allow_html=True)


def _title_html() -> str:
    """Render product identity without duplicating the live workflow status."""
    image = _mascot_data_uri()
    visual = (
        f'<img class="ld-title-mascot" alt="{DROID_NAME}, the Lineage Detective droid" src="{image}">'
        if image
        else '<div class="ld-fallback">LD</div>'
    )
    return f"""
    <style>
      @keyframes ld-float {{0%,100%{{transform:translateY(0) rotate(-1deg)}}50%{{transform:translateY(-7px) rotate(1deg)}}}}
      @keyframes ld-search {{0%,100%{{transform:translateY(0) rotate(-1deg)}}50%{{transform:translateY(-2px) rotate(1deg)}}}}
      @keyframes ld-lens {{0%,100%{{transform:scale(.82);opacity:.35}}50%{{transform:scale(1.2);opacity:.95}}}}
      @keyframes ld-beam {{0%,100%{{transform:rotate(-14deg);opacity:.15}}50%{{transform:rotate(14deg);opacity:.72}}}}
      @keyframes ld-node-one {{0%,18%,100%{{opacity:.22}}20%,42%{{opacity:1}}}}
      @keyframes ld-node-two {{0%,42%,100%{{opacity:.22}}44%,66%{{opacity:1}}}}
      @keyframes ld-node-three {{0%,66%,100%{{opacity:.22}}68%,90%{{opacity:1}}}}
      @keyframes ld-scan {{0%{{transform:scale(.74);opacity:.75}}100%{{transform:scale(1.25);opacity:0}}}}
      @keyframes ld-runner-bob {{0%,100%{{transform:translateY(0)}}50%{{transform:translateY(-4px)}}}}
      .ld-title-shell{{display:flex;align-items:center;justify-content:space-between;gap:18px;margin:2px 0 8px}}
      .ld-title-copy h1{{margin:0;color:#f8fafc;font:800 clamp(2rem,5vw,3.1rem)/1.02 system-ui,sans-serif;letter-spacing:-.035em}}
      .ld-title-copy p{{margin:8px 0 0;color:#a9bdd5;font:500 .98rem/1.45 system-ui,sans-serif}}
      .ld-title-visual{{position:relative;width:116px;height:94px;flex:0 0 116px;display:grid;place-items:center}}
      .ld-title-mascot{{width:112px;height:112px;object-fit:contain;animation:ld-float 3.4s ease-in-out infinite;filter:drop-shadow(0 9px 12px #0009)}}
      .ld-title-orbit{{position:absolute;width:70px;height:70px;border:1px solid #22d3ee55;border-radius:50%;animation:ld-scan 2.6s ease-out infinite}}
      .ld-title-spark{{position:absolute;right:8px;top:18px;width:7px;height:7px;border-radius:50%;background:#fbbf24;box-shadow:0 0 12px #fbbf24;animation:ld-lens 2.2s ease-in-out infinite}}
      .ld-fallback{{width:68px;height:68px;border-radius:50%;display:grid;place-items:center;background:#0f2847;border:2px solid #22d3ee;color:#fbbf24;font-weight:900}}
      div.stButton>button[kind="primary"]{{background:linear-gradient(110deg,#0891b2,#2563eb)!important;border:1px solid #67e8f9!important;color:#f8fafc!important;border-radius:10px!important;font-weight:750!important;box-shadow:0 7px 18px #082f4966}}
      div.stButton>button[kind="primary"]:hover{{border-color:#fbbf24!important;color:#fff!important;box-shadow:0 9px 22px #0e749080}}
      @media(max-width:560px){{.ld-title-shell{{gap:8px}}.ld-title-visual{{width:82px;height:74px;flex-basis:82px}}.ld-title-mascot{{width:84px;height:84px}}.ld-title-copy p{{font-size:.85rem}}}}
      @media(prefers-reduced-motion:reduce){{.ld-title-mascot,.ld-title-orbit,.ld-title-spark,.ld-workflow-runner,.ld-activity-droid,.ld-lens-pulse,.ld-scan-beam,.ld-evidence-node{{animation:none!important}}}}
    </style>
    <section class="ld-title-shell" aria-label="Lineage Detective">
      <div class="ld-title-copy"><h1>Lineage Detective</h1>
      <p>Data-incident investigation, containment, verified repair, and human-directed implementation through DataHub.</p></div>
      <div class="ld-title-visual">{visual}<span class="ld-title-orbit"></span><span class="ld-title-spark"></span></div>
    </section>
    """


def _workflow_phase() -> str:
    report = st.session_state.get("report") or {}
    repair = report.get("repair") or {}
    receipt = st.session_state.get("repair_receipt") or {}
    restored = (st.session_state.get("restore_receipt") or {}).get("restored")
    if st.session_state.get("handoff_packet") or (
        (st.session_state.get("apply_receipt") or {}).get("applied") and not restored
    ):
        return "handoff"
    if receipt.get("verified"):
        return "sandbox"
    if repair.get("state") == "approval_required":
        return "review"
    if report:
        return "report"
    return "investigate"


def _workflow_html(phase: str, detail: str | None = None) -> str:
    """One judge-facing progress surface, colocated with the approval action."""
    progress = {
        "ready": 2,
        "error": 2,
        "investigate": 2,
        "connecting": 10,
        "evidence": 22,
        "reasoning": 36,
        "containment": 47,
        "contained": 61,
        "repair": 57,
        "visualizing": 60,
        "report": 61,
        "review": 62,
        "sandbox": 72,
        "sandbox_reset": 65,
        "sandbox_seed": 70,
        "sandbox_baseline": 76,
        "sandbox_rewrite": 82,
        "sandbox_verify": 88,
        "sandbox_rollback": 94,
        "sandbox_complete": 97,
        "verified": 97,
        "handoff": 100,
        "complete": 100,
    }.get(phase, 2)
    stage_copy = {
        "investigate": ("Ready for one approval", "Trace will investigate, verify the repair, prove rollback, and prepare the handoff."),
        "error": ("Investigation paused", "The run stopped before it earned a verified result."),
        "report": ("Evidence gathered", "The live lineage and diagnosis are ready for the repair path."),
        "review": ("Repair ready for review", "The exact proposed bytes are visible below."),
        "sandbox_reset": ("Resetting the isolated workspace", "Preparing a clean, disposable verification environment."),
        "sandbox_seed": ("Loading representative source rows", "Building the evidence-backed fixture used by the assertion."),
        "sandbox_baseline": ("Measuring the broken baseline", "Proving the failure exists before the proposed bytes run."),
        "sandbox_rewrite": ("Applying the approved sandbox rewrite", "Only the reviewed bytes enter the disposable workspace."),
        "sandbox_verify": ("Rebuilding and checking the assertion", "The repaired result must pass the real check."),
        "sandbox_rollback": ("Restoring and verifying rollback", "The original bytes must return before the receipt can pass."),
        "sandbox_complete": ("Binding the verification receipt", "Hashes, assertions, and rollback evidence are being sealed."),
        "sandbox": ("Sandbox verification passed", "The approved diff and rollback earned a verified receipt."),
        "handoff": ("Verified workflow complete", "The exact repair, implementation proof, and human handoff are ready."),
        "complete": ("Verified workflow complete", "The exact repair, implementation proof, and human handoff are ready."),
    }
    title, default_detail = stage_copy.get(phase, _STAGE_COPY.get(phase, _STAGE_COPY["ready"]))
    image = _mascot_data_uri() or ""
    runner = (
        f'<img class="ld-workflow-runner" alt="{DROID_NAME} workflow progress" src="{image}" '
        f'style="left:calc({progress}% - 23px)">'
        if image
        else '<span class="ld-workflow-runner ld-runner-fallback">LD</span>'
    )
    state_class = (
        "ld-workflow-error"
        if phase == "error"
        else ("ld-workflow-complete" if progress == 100 else "ld-workflow-active")
    )
    return f"""
    <style>
      .ld-workflow{{position:relative;margin:8px 0 10px;padding:13px 15px 12px;border:1px solid #1e3a5f;
        border-radius:14px;background:linear-gradient(135deg,#071321,#081b2e);color:#dbeafe;overflow:hidden}}
      .ld-workflow-head{{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;margin-bottom:12px}}
      .ld-workflow-kicker{{color:#fbbf24;font:800 10px/1.2 ui-monospace,monospace;letter-spacing:.1em;text-transform:uppercase}}
      .ld-workflow-title{{margin:3px 0 2px;color:#67e8f9;font:800 15px/1.2 system-ui,sans-serif}}
      .ld-workflow-detail{{color:#bfd3e9;font:500 12px/1.35 system-ui,sans-serif}}
      .ld-workflow-percent{{color:#e0f2fe;font:800 15px/1 ui-monospace,monospace}}
      .ld-workflow-track{{position:relative;height:50px;margin:4px 9px 0}}
      .ld-workflow-line{{position:absolute;left:0;right:0;top:17px;height:5px;border-radius:99px;background:#17243a;box-shadow:inset 0 0 0 1px #334155}}
      .ld-workflow-fill{{position:absolute;left:0;top:17px;height:5px;width:{progress}%;border-radius:99px;background:linear-gradient(90deg,#0891b2,#22d3ee,#fbbf24);box-shadow:0 0 12px #22d3ee66}}
      .ld-workflow-runner{{position:absolute;top:-10px;width:48px;height:48px;object-fit:contain;z-index:2;
        filter:drop-shadow(0 5px 7px #000b);animation:ld-runner-bob 1.8s ease-in-out infinite}}
      .ld-runner-fallback{{display:grid;place-items:center;border:1px solid #22d3ee;border-radius:50%;background:#0f2847;color:#fbbf24;font:800 9px/1 monospace}}
      .ld-workflow-label{{position:absolute;top:32px;color:#7890ad;font:700 8px/1 ui-monospace,monospace;text-transform:uppercase;transform:translateX(-50%)}}
      .ld-label-1{{left:0;transform:none}}.ld-label-2{{left:34%}}.ld-label-3{{left:67%}}.ld-label-4{{right:0;transform:none}}
      .ld-workflow-complete{{border-color:#166534;background:linear-gradient(135deg,#052e16,#071b24)}}
      .ld-workflow-complete .ld-workflow-title{{color:#86efac}}
      .ld-workflow-error{{border-color:#7f1d1d;background:linear-gradient(135deg,#2a0b12,#111827)}}
      .ld-workflow-error .ld-workflow-title{{color:#fca5a5}}
      @media(max-width:560px){{.ld-workflow{{padding:11px}}.ld-workflow-detail{{font-size:11px}}.ld-workflow-label{{font-size:7px}}}}
    </style>
    <section class="ld-workflow {state_class}" aria-label="Verified workflow progress">
      <div class="ld-workflow-head"><div><div class="ld-workflow-kicker">{DROID_NAME} · live execution</div>
      <div class="ld-workflow-title">{html.escape(title)}</div>
      <div class="ld-workflow-detail">{html.escape(detail or default_detail)}</div></div>
      <div class="ld-workflow-percent">{progress}%</div></div>
      <div class="ld-workflow-track"><div class="ld-workflow-line"></div><div class="ld-workflow-fill"></div>{runner}
      <span class="ld-workflow-label ld-label-1">Evidence</span><span class="ld-workflow-label ld-label-2">Diagnosis</span>
      <span class="ld-workflow-label ld-label-3">Test</span><span class="ld-workflow-label ld-label-4">Handoff</span></div>
    </section>
    """


def _load_example(example_name: str) -> None:
    symptom_value, asset_value = EXAMPLES[example_name]
    st.session_state["incident_example"] = example_name
    st.session_state["incident_symptom"] = symptom_value
    st.session_state["incident_asset"] = asset_value
    for key in _WORKFLOW_RESULT_KEYS:
        st.session_state.pop(key, None)


def _load_selected_example() -> None:
    _load_example(st.session_state["incident_example"])


def _load_full_repair_example() -> None:
    _reset_demo_apply_target()
    _load_example(REPAIR_EXAMPLE)


def _select_search_result() -> None:
    selected = st.session_state.get("asset_search_selection")
    if selected:
        st.session_state["incident_asset"] = selected
        st.session_state["incident_example"] = CUSTOM_INCIDENT
        for key in _WORKFLOW_RESULT_KEYS:
            st.session_state.pop(key, None)


def _queue_autonomous_workflow() -> None:
    """Turn the start control into a cancel control on the next Streamlit rerun."""
    st.session_state["workflow_cancel_requested"] = False
    st.session_state["workflow_running"] = False
    st.session_state["workflow_run_requested"] = True


def _cancel_autonomous_workflow() -> None:
    """Request cancellation and clear only Lineage Detective's current run artifacts."""
    st.session_state["workflow_cancel_requested"] = True
    st.session_state["workflow_run_requested"] = False
    st.session_state["workflow_running"] = False
    for key in _WORKFLOW_RESULT_KEYS:
        st.session_state.pop(key, None)


def _check_workflow_cancelled() -> None:
    if st.session_state.get("workflow_cancel_requested"):
        raise WorkflowCancelled("Cancelled by the user.")


def _demo_apply_root() -> Path:
    """Return a judge-session-specific disposable checkout root."""
    root = st.session_state.get("demo_apply_root")
    if not root:
        root = str(
            Path(tempfile.gettempdir())
            / "lineage-detective-sessions"
            / uuid.uuid4().hex
        )
        st.session_state["demo_apply_root"] = root
    return Path(str(root))


def _demo_apply_target(repair: dict | None = None) -> Path:
    relative = Path(str((repair or {}).get("file_name") or "models/stg_customers.sql"))
    if relative.is_absolute() or ".." in relative.parts:
        raise OSError("The disposable demo target must stay inside its workspace.")
    return _demo_apply_root() / relative


def _reset_demo_apply_target(repair: dict | None = None) -> Path:
    """Reset only the clearly disposable demo copy and remove its orphaned demo backups."""
    root = _demo_apply_root()
    target = _demo_apply_target(repair)
    if root.is_symlink() or target.is_symlink():
        raise OSError("The disposable demo workspace may not be a symbolic link.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        str((repair or {}).get("current_sql") or BROKEN_SQL),
        encoding="utf-8",
        newline="\n",
    )
    for backup in target.parent.glob(f".{target.name}.lineage-detective-*.bak"):
        if backup.is_file() and not backup.is_symlink():
            backup.unlink()
    return target.resolve(strict=True)


def _ensure_demo_apply_target(repair: dict | None = None) -> Path:
    """Create a disposable checked-out model so the full apply/restore path is testable."""
    root = _demo_apply_root()
    target = _demo_apply_target(repair)
    if root.is_symlink() or target.is_symlink():
        raise OSError("The disposable demo workspace may not be a symbolic link.")
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_text(
            str((repair or {}).get("current_sql") or BROKEN_SQL),
            encoding="utf-8",
            newline="\n",
        )
    return target.resolve(strict=True)


def _asset_label(urn: str) -> str:
    parts = urn.rsplit("(", 1)[-1].rstrip(")").split(",")
    return parts[-2] if len(parts) >= 2 else urn


def _droid_action_html(title: str, detail: str, state: str = "working") -> str:
    """A stationary work-state companion placed beside real progress messages."""
    image = _mascot_data_uri() or ""
    return f"""
    <div style="display:flex;align-items:center;gap:12px;padding:10px 12px;margin:8px 0;
                border:1px solid #1e3a5f;border-radius:12px;background:#071321;color:#dbeafe">
      <div style="position:relative;width:76px;height:72px;flex:0 0 76px;display:grid;place-items:center;overflow:visible">
        <img class="ld-activity-droid" src="{image}" alt="{DROID_NAME}, the Lineage Detective droid" style="width:68px;height:68px;object-fit:contain;
             {'animation:ld-search 3.6s ease-in-out infinite;' if state == 'working' else ''}">
        {('<span class="ld-lens-pulse" style="position:absolute;left:8px;top:24px;width:21px;height:21px;border:2px solid #67e8f9;border-radius:50%;box-shadow:0 0 12px #22d3ee;animation:ld-lens 2.1s ease-in-out infinite"></span>'
          '<span class="ld-scan-beam" style="position:absolute;left:24px;top:35px;width:47px;height:2px;transform-origin:left center;background:linear-gradient(90deg,#67e8f9,transparent);animation:ld-beam 2.8s ease-in-out infinite"></span>'
          '<span class="ld-evidence-node" style="position:absolute;right:5px;top:15px;width:6px;height:6px;border-radius:50%;background:#67e8f9;animation:ld-node-one 3.6s linear infinite"></span>'
          '<span class="ld-evidence-node" style="position:absolute;right:0;top:33px;width:6px;height:6px;border-radius:50%;background:#60a5fa;animation:ld-node-two 3.6s linear infinite"></span>'
          '<span class="ld-evidence-node" style="position:absolute;right:7px;top:52px;width:6px;height:6px;border-radius:50%;background:#fbbf24;animation:ld-node-three 3.6s linear infinite"></span>') if state == 'working' else ''}
      </div>
      <div><div style="font:800 10px/1.2 ui-monospace,monospace;letter-spacing:.1em;text-transform:uppercase;color:#fbbf24">{DROID_NAME}</div>
      <div style="font-weight:800;color:#67e8f9">{html.escape(title)}</div>
      <div style="font-size:.9rem;color:#bfdbfe">{html.escape(detail)}</div></div>
    </div>"""


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


def _render_external_remediation(repair: dict, receipt: dict, *, server_url: str, server_token: str) -> None:
    """Offer real target-system actions only after the exact repair earned a sandbox receipt."""
    repair_id = str(repair.get("repair_id") or "current")
    with st.expander("Continue into the system that owns the fix", expanded=False):
        st.caption(
            "Each connector uses credentials only for this browser session. Nothing runs until its "
            "specific action button is clicked, and every result returns a downloadable receipt."
        )
        connector_targets = (
            "Open a GitHub pull request",
            "Trigger a dbt Cloud job",
            "Trigger an Airflow DAG",
            "Pause, resume, or sync Fivetran",
            "Execute one Snowflake statement",
            "Create a DataHub prevention assertion",
        )
        if os.environ.get("HOSTED_MODE") != "1":
            connector_targets = ("Run this repository's tests",) + connector_targets
        target = st.selectbox(
            "Implementation target",
            connector_targets,
            key=f"connector-target-{repair_id}",
        )
        result = None
        transport = JsonTransport(allow_private=os.environ.get("HOSTED_MODE") != "1")
        try:
            if target == "Run this repository's tests":
                root = st.text_input(
                    "Project directory", key=f"validation-root-{repair_id}",
                    placeholder=r"C:\work\analytics",
                ).strip()
                command = st.text_input(
                    "Test command", key=f"validation-command-{repair_id}",
                    placeholder="dbt test --select stg_customers+",
                    help="Executed directly without a command shell.",
                ).strip()
                if st.button("Run project validation", type="primary", width="stretch",
                             key=f"validation-run-{repair_id}"):
                    result = run_project_validation(command, cwd=root)

            elif target == "Open a GitHub pull request":
                github_token = st.text_input(
                    "GitHub fine-grained token", type="password", key=f"github-token-{repair_id}"
                )
                repo = st.text_input(
                    "Repository", placeholder="owner/repository", key=f"github-repo-{repair_id}"
                ).strip()
                path = st.text_input(
                    "Repository path", value=str(repair.get("file_name") or ""),
                    key=f"github-path-{repair_id}",
                ).strip()
                columns = st.columns(2)
                base = columns[0].text_input("Base branch", value="main", key=f"github-base-{repair_id}")
                branch = columns[1].text_input(
                    "Repair branch", value=f"lineage-detective/{repair_id[:8]}",
                    key=f"github-branch-{repair_id}",
                )
                if st.button("Open verified repair pull request", type="primary", width="stretch",
                             key=f"github-run-{repair_id}"):
                    result = GitHubPullRequestConnector(
                        github_token, repo, transport=transport
                    ).apply(
                        path=path,
                        content=str(repair.get("fixed_sql") or ""),
                        base_branch=base,
                        branch=branch,
                        title=f"Lineage Detective: repair {repair.get('target', path)}",
                        body=(
                            "Evidence-bound repair generated by Lineage Detective.\n\n"
                            f"Sandbox receipt: `{receipt.get('receipt_sha256')}`"
                        ),
                        expected_source_sha256=str(receipt.get("proposal_sha256") or ""),
                    )

            elif target == "Trigger a dbt Cloud job":
                dbt_token = st.text_input(
                    "dbt Cloud service token", type="password", key=f"dbt-token-{repair_id}"
                )
                columns = st.columns(2)
                account = columns[0].text_input("Account ID", key=f"dbt-account-{repair_id}")
                job = columns[1].text_input("Job ID", key=f"dbt-job-{repair_id}")
                steps = st.text_area(
                    "Optional step overrides, one per line", key=f"dbt-steps-{repair_id}",
                    placeholder="dbt build --select stg_customers+",
                )
                if st.button("Trigger dbt verification job", type="primary", width="stretch",
                             key=f"dbt-run-{repair_id}"):
                    result = DbtCloudConnector(
                        dbt_token, account, job, transport=transport
                    ).trigger(
                        cause=f"Lineage Detective repair {repair_id}",
                        steps_override=[line.strip() for line in steps.splitlines() if line.strip()] or None,
                    )

            elif target == "Trigger an Airflow DAG":
                airflow_url = st.text_input(
                    "Airflow URL", placeholder="https://airflow.example.com",
                    key=f"airflow-url-{repair_id}",
                )
                airflow_token = st.text_input(
                    "Airflow bearer token", type="password", key=f"airflow-token-{repair_id}"
                )
                dag_id = st.text_input("DAG ID", key=f"airflow-dag-{repair_id}")
                if st.button("Trigger remediation DAG", type="primary", width="stretch",
                             key=f"airflow-run-{repair_id}"):
                    result = AirflowConnector(
                        airflow_url, airflow_token, transport=transport
                    ).trigger(
                        dag_id=dag_id,
                        conf={
                            "repair_id": repair_id,
                            "proposal_sha256": receipt.get("proposal_sha256"),
                            "target": repair.get("target"),
                        },
                    )

            elif target == "Pause, resume, or sync Fivetran":
                columns = st.columns(2)
                key = columns[0].text_input(
                    "Fivetran API key", type="password", key=f"fivetran-key-{repair_id}"
                )
                secret = columns[1].text_input(
                    "Fivetran API secret", type="password", key=f"fivetran-secret-{repair_id}"
                )
                connection = st.text_input(
                    "Connection ID", key=f"fivetran-connection-{repair_id}"
                )
                action = st.radio(
                    "Connection action", ("pause", "resume", "sync"), horizontal=True,
                    key=f"fivetran-action-{repair_id}",
                )
                if st.button(f"{action.title()} Fivetran connection", type="primary",
                             width="stretch", key=f"fivetran-run-{repair_id}"):
                    result = FivetranConnector(
                        key, secret, connection, transport=transport
                    ).act(action)

            elif target == "Execute one Snowflake statement":
                snowflake_url = st.text_input(
                    "Snowflake account URL", placeholder="https://account.snowflakecomputing.com",
                    key=f"snowflake-url-{repair_id}",
                )
                snowflake_token = st.text_input(
                    "Snowflake OAuth, key-pair JWT, or programmatic access token",
                    type="password", key=f"snowflake-token-{repair_id}",
                )
                token_type = st.selectbox(
                    "Token type", ("OAUTH", "KEYPAIR_JWT", "PROGRAMMATIC_ACCESS_TOKEN"),
                    key=f"snowflake-token-type-{repair_id}",
                )
                statement = st.text_area(
                    "Exactly one reviewed SQL statement", key=f"snowflake-sql-{repair_id}",
                    help="This is not prefilled from a dbt model because a model SELECT is not a warehouse repair.",
                )
                context = st.columns(4)
                warehouse = context[0].text_input("Warehouse", key=f"snowflake-wh-{repair_id}")
                database = context[1].text_input("Database", key=f"snowflake-db-{repair_id}")
                schema = context[2].text_input("Schema", key=f"snowflake-schema-{repair_id}")
                role = context[3].text_input("Role", key=f"snowflake-role-{repair_id}")
                if st.button("Execute reviewed Snowflake statement", type="primary", width="stretch",
                             key=f"snowflake-run-{repair_id}"):
                    result = SnowflakeSqlConnector(
                        snowflake_url, snowflake_token, token_type=token_type,
                        transport=transport,
                    ).execute(
                        statement=statement, warehouse=warehouse, database=database,
                        schema=schema, role=role,
                    )

            else:
                assertion_kind = st.selectbox(
                    "Prevention monitor",
                    ("Freshness", "Row-count range", "Custom SQL metric"),
                    key=f"assertion-kind-{repair_id}",
                )
                dataset_urn = str(st.session_state.get("incident_asset") or "")
                cron = st.text_input(
                    "Evaluation schedule", value="0 */2 * * *", key=f"assertion-cron-{repair_id}"
                )
                st.caption(
                    "DataHub Cloud requires Edit Assertions and Edit Monitors privileges."
                )
                connector = DataHubAssertionConnector(
                    server_url, server_token, transport=transport
                )
                if assertion_kind == "Freshness":
                    hours = st.number_input(
                        "Maximum freshness age (hours)", min_value=1, max_value=720, value=8,
                        key=f"assertion-hours-{repair_id}",
                    )
                    if st.button("Create active freshness assertion", type="primary",
                                 width="stretch", key=f"assertion-run-{repair_id}"):
                        result = connector.create_freshness(
                            dataset_urn=dataset_urn, hours=int(hours), cron=cron,
                        )
                elif assertion_kind == "Row-count range":
                    ranges = st.columns(2)
                    minimum = ranges[0].number_input(
                        "Minimum rows", min_value=0, value=1,
                        key=f"assertion-min-rows-{repair_id}",
                    )
                    maximum = ranges[1].number_input(
                        "Maximum rows", min_value=0, value=10_000_000,
                        key=f"assertion-max-rows-{repair_id}",
                    )
                    if st.button("Create active volume assertion", type="primary",
                                 width="stretch", key=f"assertion-run-{repair_id}"):
                        result = connector.create_volume(
                            dataset_urn=dataset_urn, minimum=int(minimum),
                            maximum=int(maximum), cron=cron,
                        )
                else:
                    sql = st.text_area(
                        "Read-only query returning one number",
                        placeholder="SELECT COUNT(*) FROM analytics.orders WHERE order_id IS NULL",
                        key=f"assertion-sql-{repair_id}",
                    )
                    minimum = st.number_input(
                        "Minimum passing value", value=0.0,
                        key=f"assertion-minimum-value-{repair_id}",
                    )
                    description = st.text_input(
                        "Monitor description", value="Lineage Detective prevention monitor",
                        key=f"assertion-description-{repair_id}",
                    )
                    if st.button("Create active SQL assertion", type="primary",
                                 width="stretch", key=f"assertion-run-{repair_id}"):
                        result = connector.create_sql_metric(
                            dataset_urn=dataset_urn, statement=sql, minimum=float(minimum),
                            description=description, cron=cron,
                        )
        except Exception as exc:
            result = failure_receipt(target, exc)

        if result is not None:
            st.session_state[f"connector-receipt-{repair_id}"] = result
        connector_receipt = st.session_state.get(f"connector-receipt-{repair_id}")
        if connector_receipt:
            if connector_receipt.get("verified"):
                st.success(
                    f"{connector_receipt.get('connector', target)} action was read back or returned "
                    "a target-system identifier."
                )
            else:
                st.error(
                    connector_receipt.get("error")
                    or "The target system did not provide enough evidence to verify this action."
                )
            st.download_button(
                "Download connector receipt",
                json.dumps(connector_receipt, indent=2, sort_keys=True, default=str),
                file_name="lineage-detective-connector-receipt.json",
                mime="application/json",
                key=f"connector-download-{repair_id}",
            )


def _run_autonomous_followthrough(
    report: dict,
    workflow_slot,
    *,
    finish_mode: str,
    deployment_profile: dict | None = None,
) -> dict:
    """Complete the verified repair path after the user's single up-front approval."""
    _check_workflow_cancelled()
    repair = report.get("repair") or {}
    if repair.get("state") != "approval_required":
        st.info(
            "The investigation completed, but this incident did not produce a safe code change. "
            "Trace stopped instead of inventing one."
        )
        result = {
            "state": "no_verified_repair_available",
            "verified": False,
        }
        st.session_state["autonomous_workflow_result"] = result
        return result

    is_guardrail = str(repair.get("action_type", "")).endswith("_guardrail")
    artifact_label = "dbt test" if is_guardrail else "dbt model"
    target_file = None
    if finish_mode == "Prove safe write + prepare handoff":
        target_file = str(_ensure_demo_apply_target(repair))
    elif finish_mode == "Apply to selected SQL + prepare handoff":
        candidate = Path(str(repair.get("source_path") or "")).expanduser()
        if candidate.is_symlink() or not candidate.is_file() or candidate.suffix.lower() != ".sql":
            raise OSError(
                f"The selected {artifact_label} is no longer an existing regular .sql file."
            )
        target_file = str(candidate.resolve(strict=True))
    elif finish_mode == "Deploy verified repair + confirm live health":
        candidate = Path(str(repair.get("source_path") or "")).expanduser()
        if candidate.is_symlink() or not candidate.is_file() or candidate.suffix.lower() != ".sql":
            raise OSError(
                f"The selected {artifact_label} is no longer an existing regular .sql file."
            )
        if not deployment_profile:
            raise ValueError("Complete the self-hosted deployment profile before starting.")
        target_file = str(candidate.resolve(strict=True))

    _render_detective(
        workflow_slot,
        "sandbox_reset",
        "Your approval covers this displayed proposal, its isolated test, and the selected finish action.",
    )

    def show_progress(phase: str, detail: str) -> None:
        _check_workflow_cancelled()
        _render_detective(workflow_slot, phase, detail)

    result = run_approved_workflow(
        report,
        approval="one-click-ui-full-workflow",
        apply_target=target_file,
        on_progress=show_progress,
        deployment_profile=deployment_profile,
        allow_local_deployment=os.environ.get("HOSTED_MODE") != "1",
    )
    _check_workflow_cancelled()
    receipt = result.get("repair_receipt")
    if receipt is not None:
        st.session_state["repair_receipt"] = receipt
    apply_receipt = result.get("apply_receipt")
    if apply_receipt is not None:
        st.session_state["apply_receipt"] = apply_receipt
    deployment_receipt = result.get("deployment_receipt")
    if deployment_receipt is not None:
        st.session_state["deployment_receipt"] = deployment_receipt
    handoff = result.get("handoff_packet")
    if handoff is not None:
        st.session_state["handoff_packet"] = handoff

    if result.get("verified"):
        st.session_state["autonomous_workflow_result"] = {
            "state": result.get("state"),
            "verified": True,
            "finish_mode": finish_mode,
                "repair_id": repair.get("repair_id"),
                "deployed": bool(deployment_receipt and deployment_receipt.get("verified")),
        }
        _render_detective(
            workflow_slot,
            "complete",
            (
                "Trace proved the exact change, verified rollback, completed the selected "
                "implementation path, confirmed any selected live deployment, and prepared "
                "the downloadable handoff."
            ),
        )
        st.success(
            "Autonomous run complete: evidence gathered, repair verified, the selected finish "
            "action confirmed, and the handoff prepared."
        )
    else:
        st.session_state["autonomous_workflow_result"] = {
            "state": result.get("state"),
            "verified": False,
            "finish_mode": finish_mode,
                "repair_id": repair.get("repair_id"),
                "deployed": False,
        }
        _render_detective(
            workflow_slot,
            "error",
            str(
                (deployment_receipt or {}).get("error")
                or (receipt or {}).get("error")
                or result.get("state")
                or "Verification failed."
            ),
        )
        st.error(
            "The autonomous workflow stopped before implementation because verification did not pass."
        )
    return result


def _render_repair(report: dict, detective_slot, workflow_slot) -> None:
    repair = report.get("repair")
    if not repair:
        return
    st.divider()
    st.subheader("2 · Review the proposed code change")
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

    is_guardrail = str(repair.get("action_type", "")).endswith("_guardrail")
    change_noun = "guardrail" if is_guardrail else "rewrite"
    artifact_label = "dbt test" if is_guardrail else "dbt model"
    st.markdown(_droid_action_html(
        f"Constrained {change_noun} drafted",
        "Trace used the returned evidence to propose this exact diff. Nothing has been executed yet.",
        state="complete",
    ), unsafe_allow_html=True)
    st.info(
        f"The agent proposed this exact {artifact_label} change from the diagnosis and live evidence. "
        "It has not run anywhere yet."
    )
    st.caption(repair.get("rationale") or "No additional rationale returned.")
    metadata = st.columns(2)
    metadata[0].metric("Target", repair.get("target", "unknown"))
    metadata[1].metric("Proposal hash", str(repair.get("proposal_sha256") or "missing")[:12])
    change_tab, current_tab, proposed_tab = st.tabs(
        ["Exact diff", "Current artifact", f"Proposed {change_noun}"]
    )
    with change_tab:
        st.code(repair.get("diff", ""), language="diff")
    with current_tab:
        st.code(repair.get("current_sql", BROKEN_SQL), language="sql")
    with proposed_tab:
        st.code(repair.get("fixed_sql", ""), language="sql")
    st.info(
        f"Sandbox first: prove the exact {change_noun} here, then choose whether to apply it to a "
        f"checked-out {artifact_label} or download the verified handoff."
    )
    with st.expander("Representativeness boundary", expanded=False):
        st.write(repair.get("representativeness", ""))

    existing_receipt = st.session_state.get("repair_receipt") or {}
    receipt_is_current = bool(
        existing_receipt.get("verified")
        and existing_receipt.get("repair_id") == repair.get("repair_id")
    )
    autonomous_result = st.session_state.get("autonomous_workflow_result") or {}
    autonomous_is_current = bool(
        autonomous_result.get("verified")
        and autonomous_result.get("repair_id") == repair.get("repair_id")
    )
    if autonomous_is_current:
        workflow_slot.markdown(_workflow_html("handoff"), unsafe_allow_html=True)
    elif receipt_is_current:
        workflow_slot.markdown(_workflow_html("sandbox"), unsafe_allow_html=True)
    else:
        workflow_slot.markdown(_workflow_html("review"), unsafe_allow_html=True)
    if autonomous_is_current:
        st.success(
            "One-click workflow completed this proposal through sandbox verification and the "
            "selected finish action. Manual controls remain available in Advanced settings for a new run."
        )
    elif not receipt_is_current:
        st.caption("Clicking the action below is the explicit approval for this exact displayed diff.")
    if not receipt_is_current and st.button(
        f"Approve this {change_noun} & run the sandbox",
        type="primary",
        width="stretch",
        key=f"trial-{repair.get('repair_id', 'current')}",
    ):
        sandbox_stage = st.empty()
        sandbox_stage.markdown(
            _workflow_html(
                "sandbox_reset",
                detail="Resetting a disposable workspace before any approved bytes are executed.",
            ),
            unsafe_allow_html=True,
        )

        def show_sandbox_progress(phase: str, detail: str) -> None:
            sandbox_stage.markdown(
                _workflow_html(phase, detail=detail),
                unsafe_allow_html=True,
            )

        st.session_state["repair_receipt"] = execute_sandbox_trial(
            repair, approval="interactive-ui-approval", on_progress=show_sandbox_progress,
        )
        receipt = st.session_state["repair_receipt"]
        if receipt.get("verified"):
            sandbox_stage.markdown(
                _workflow_html(
                    "sandbox",
                    detail=str(
                        repair.get("verification_summary")
                        or "The exact change passed its isolated assertion and rollback."
                    ),
                ),
                unsafe_allow_html=True,
            )
            workflow_slot.markdown(_workflow_html("sandbox"), unsafe_allow_html=True)
        else:
            sandbox_stage.markdown(
                _workflow_html(
                    "error",
                    detail=str(
                        receipt.get("error")
                        or f"The {change_noun} did not earn a verified receipt."
                    ),
                ),
                unsafe_allow_html=True,
            )

    receipt = st.session_state.get("repair_receipt")
    if receipt and receipt.get("repair_id") == repair.get("repair_id"):
        st.subheader("3 · Sandbox verification receipt")
        before, after = receipt.get("before") or {}, receipt.get("after") or {}
        metrics = st.columns(3)
        before_value = repair.get("before_display") or f"{before.get('filled', '?')}/{before.get('total', '?')}"
        after_value = repair.get("after_display") or f"{after.get('filled', '?')}/{after.get('total', '?')}"
        metrics[0].metric("Before", before_value,
                          "FAIL expected" if before and not before.get("passed") else None)
        metrics[1].metric(
            "After",
            after_value,
            ("DETECTED" if is_guardrail else "PASS") if after.get("passed") else "not verified",
        )
        metrics[2].metric("Rollback", "confirmed" if receipt.get("rollback_verified") else "not confirmed")
        if receipt.get("verified"):
            st.success(
                "Sandbox trial verified: "
                + str(repair.get("verification_summary") or "the assertion flipped from FAIL to PASS.")
                + " The patch was not applied outside the disposable workspace."
            )
            st.markdown(_droid_action_html(
                f"Sandbox {change_noun} verified",
                "The exact diff passed the isolated assertion and is ready to apply or hand off.",
                state="complete",
            ), unsafe_allow_html=True)
            st.subheader("4 · Choose what happens next")
            st.write(
                f"The sandbox verified the {change_noun}. Download the packet, or explicitly apply the "
                f"same hash-bound SQL to an existing checked-out {artifact_label}."
            )
            source_path = str(repair.get("source_path") or "")
            target_options = (
                ("Safe disposable demo copy", "Selected file from this run", "Another checked-out dbt model")
                if source_path
                else ("Safe disposable demo copy", "My checked-out dbt model")
            )
            target_mode = st.radio(
                "Where should Trace prove the implementation step?",
                target_options,
                horizontal=True,
                key=f"apply-mode-{repair.get('repair_id', 'current')}",
                help="The demo copy proves the exact write, hash readback, backup, and restore path without touching a real project.",
            )
            if target_mode == "Safe disposable demo copy":
                try:
                    target_file = str(_ensure_demo_apply_target(repair))
                    st.caption(f"Disposable {artifact_label} ready: `{target_file}`")
                except OSError as exc:
                    target_file = ""
                    st.error(f"Could not prepare the disposable model: {exc}")
            elif target_mode == "Selected file from this run":
                target_file = source_path
                selected = Path(target_file)
                if selected.is_file() and selected.suffix.lower() == ".sql" and not selected.is_symlink():
                    st.success(f"Selected SQL artifact is still available: `{selected}`")
                else:
                    target_file = ""
                    st.error("The SQL file selected before investigation is no longer available.")
            else:
                target_file = st.text_input(
                    f"Checked-out {artifact_label} file to update",
                    key=f"apply-target-{repair.get('repair_id', 'current')}",
                    placeholder=(
                        r"C:\path\to\dbt_project\tests\incident_guard.sql"
                        if is_guardrail
                        else r"C:\path\to\dbt_project\models\stg_customers.sql"
                    ),
                    help=f"Choose an existing .sql {artifact_label}. Lineage Detective creates a sibling backup and verifies the written bytes.",
                ).strip()
                if not target_file:
                    st.info(
                        f"Paste the full path to an existing `.sql` {artifact_label} on the machine running "
                        "Lineage Detective. Browser-only judges should use the safe demo copy."
                    )
                else:
                    candidate = Path(target_file).expanduser()
                    if candidate.is_file() and candidate.suffix.lower() == ".sql" and not candidate.is_symlink():
                        st.success(f"Existing SQL {artifact_label} found. Trace can apply the verified {change_noun}.")
                    else:
                        st.warning(
                            "That host-machine path is not an existing regular `.sql` file yet. "
                            "Correct it, or switch to the safe demo copy."
                        )
            action_columns = st.columns(2)
            with action_columns[0]:
                apply_clicked = st.button(
                    (f"Apply verified {change_noun} to safe demo copy"
                     if target_mode == "Safe disposable demo copy"
                     else f"Apply verified {change_noun} to this file"),
                    type="primary",
                    width="stretch",
                    key=f"apply-button-{repair.get('repair_id', 'current')}",
                )
            with action_columns[1]:
                handoff_clicked = st.button(
                    "Prepare downloadable handoff",
                    width="stretch",
                    key=f"handoff-button-{repair.get('repair_id', 'current')}",
                )
            if apply_clicked:
                if not target_file:
                    st.error(
                        "Enter an existing host-machine `.sql` path above, or select the safe "
                        "disposable demo copy."
                    )
                else:
                    st.session_state.pop("restore_receipt", None)
                    st.session_state["apply_receipt"] = apply_verified_repair(
                        receipt,
                        target_file=target_file,
                        approval="interactive-ui-apply-button",
                    )
                    if st.session_state["apply_receipt"].get("applied"):
                        workflow_slot.markdown(_workflow_html("handoff"), unsafe_allow_html=True)
            if handoff_clicked:
                _render_detective(
                    detective_slot, "handoff",
                    "Binding the exact reviewed diff, proposed model, and verification receipt into one packet.",
                )
                st.session_state["handoff_packet"] = build_handoff_packet(receipt)
                _render_detective(detective_slot, "complete", "Verified handoff ready for the human production-change process.")
                workflow_slot.markdown(_workflow_html("handoff"), unsafe_allow_html=True)
            apply_receipt = st.session_state.get("apply_receipt")
            if apply_receipt:
                if apply_receipt.get("applied"):
                    restore_receipt = st.session_state.get("restore_receipt") or {}
                    if restore_receipt.get("restored"):
                        st.info(
                            f"The verified {change_noun} was applied, read back, and then restored from its "
                            "hash-verified backup. Reapply it or prepare the handoff when ready."
                        )
                    else:
                        st.success(
                            f"Verified {change_noun} applied to the selected file. The post-write hash matches "
                            "the sandbox-approved proposal and a sibling backup is available."
                        )
                    st.download_button(
                        "Download implementation receipt",
                        receipt_for_display(apply_receipt),
                        file_name="lineage-detective-implementation-receipt.json",
                        mime="application/json",
                        key=f"apply-receipt-{repair.get('repair_id', 'current')}",
                    )
                    if not restore_receipt.get("restored"):
                        if st.button(
                            "Restore the verified backup",
                            width="stretch",
                            key=f"restore-button-{repair.get('repair_id', 'current')}",
                        ):
                            st.session_state["restore_receipt"] = restore_applied_repair(
                                apply_receipt,
                                approval="interactive-ui-restore-button",
                            )
                            restore_receipt = st.session_state["restore_receipt"]
                            if restore_receipt.get("restored"):
                                workflow_slot.markdown(_workflow_html("sandbox"), unsafe_allow_html=True)
                                st.rerun()
                    if restore_receipt:
                        if restore_receipt.get("restored"):
                            st.success("Backup restored and its original hash was verified.")
                            st.download_button(
                                "Download restore receipt",
                                receipt_for_display(restore_receipt),
                                file_name="lineage-detective-restore-receipt.json",
                                mime="application/json",
                                key=f"restore-receipt-{repair.get('repair_id', 'current')}",
                            )
                        else:
                            st.error(restore_receipt.get("error") or "Backup restore was not verified.")
                else:
                    st.error(apply_receipt.get("error") or f"The verified {change_noun} was not applied.")
            deployment_receipt = st.session_state.get("deployment_receipt")
            if deployment_receipt:
                st.subheader("5 · Live deployment receipt")
                if deployment_receipt.get("verified"):
                    st.success(
                        "The exact verified repair was deployed and a separate downstream health "
                        "check confirmed the live result."
                    )
                elif deployment_receipt.get("rollback_verified"):
                    st.warning(
                        "The live health check did not pass. Trace restored the prior source, ran "
                        "the rollback path, and independently verified the prior state."
                    )
                else:
                    st.error(
                        deployment_receipt.get("rollback_error")
                        or deployment_receipt.get("error")
                        or "Deployment and rollback were not fully verified."
                    )
                st.download_button(
                    "Download deployment receipt",
                    receipt_for_display(deployment_receipt),
                    file_name="lineage-detective-deployment-receipt.json",
                    mime="application/json",
                    key=f"deployment-receipt-{repair.get('repair_id', 'current')}",
                )
            handoff = st.session_state.get("handoff_packet")
            if handoff:
                st.subheader("4 · Verified human handoff")
                st.success("The packet contains the exact diff, proposed SQL, instructions, and hash-bound sandbox receipt.")
                st.download_button(
                    "Download verified human handoff packet (.zip)", handoff,
                    file_name="lineage-detective-human-handoff.zip", mime="application/zip",
                    key=f"handoff-download-{repair.get('repair_id', 'current')}",
                )
            _render_external_remediation(
                repair,
                receipt,
                server_url=server,
                server_token=token or "",
            )
        else:
            st.error(receipt.get("error") or "Sandbox trial did not verify. No production claim is made.")
        st.download_button("Download JSON receipt", receipt_for_display(receipt),
                           file_name="lineage-detective-sandbox-receipt.json", mime="application/json")
        with st.expander("Full receipt"):
            st.code(receipt_for_display(receipt), language="json")


st.markdown(_title_html(), unsafe_allow_html=True)
st.markdown(
    "<div style='background:#0b1220;border:1px solid #1e293b;border-radius:8px;padding:9px 12px;"
    "margin:-4px 0 12px;color:#bfdbfe;font-size:.9rem'><b>Truth boundary:</b> DataHub MCP supplies "
    "lineage and metadata; model-backed mode reasons over it, while no-key judge mode applies disclosed "
    "deterministic checks. Confirmed incidents can be contained only from the model-backed lane. "
    "For any asset, Trace can investigate lineage and verify catalog containment. If the affected "
    "dbt SQL file is available to this host, Trace can also draft a constrained patch; a proposed "
    "change runs in isolation first. Autonomous mode treats its clearly labeled start button as "
    "approval for the displayed full scope; manual mode pauses at each stage. After verification, "
    "a self-hosted customer can run one approved path through exact write, deployment, independent "
    "live readback, and automatic verified rollback. Individual GitHub, dbt Cloud, Airflow, "
    "Fivetran, Snowflake, and DataHub assertion connectors remain available for governed actions.</div>",
    unsafe_allow_html=True)

with st.sidebar:
    st.header("Connection")
    connection_mode = st.selectbox(
        "DataHub connection",
        ("Local / self-hosted MCP", "DataHub Cloud managed MCP"),
        index=1 if os.environ.get("HOSTED_MODE") == "1" else 0,
        help=(
            "The managed Cloud path uses DataHub's streamable-HTTP MCP endpoint directly. "
            "For an unattended agent, DataHub recommends a scoped service-account token."
        ),
    )
    if connection_mode == "DataHub Cloud managed MCP":
        server = st.text_input(
            "DataHub Cloud tenant URL",
            value=os.environ.get("DATAHUB_SERVER", ""),
            placeholder="https://tenant.acryl.io",
        ).strip()
        hosted = os.environ.get("HOSTED_MODE") == "1"
        auth_mode = "Service-account token"
        if not hosted:
            auth_mode = st.radio(
                "Authentication",
                ("Service-account token", "Sign in with DataHub OAuth"),
                horizontal=True,
                help=(
                    "OAuth opens DataHub in your browser and returns to a temporary loopback "
                    "callback. It is available only when Lineage Detective runs locally."
                ),
            )
        if auth_mode == "Sign in with DataHub OAuth":
            if st.button("Connect DataHub in browser", width="stretch"):
                with st.spinner("Waiting for DataHub sign-in..."):
                    try:
                        oauth = authorize_datahub()
                        st.session_state["datahub_oauth_access_token"] = oauth.access_token
                        st.success("DataHub OAuth connected for this session.")
                    except Exception as exc:
                        st.error(f"DataHub OAuth failed: {type(exc).__name__}: {exc}")
            token = str(st.session_state.get("datahub_oauth_access_token") or "")
            mcp_url = DATAHUB_GLOBAL_MCP
            if token:
                st.success("OAuth token is held in memory for this Streamlit session.")
            else:
                st.info("Use the button above to authorize DataHub.")
        else:
            token = st.text_input("Scoped service-account token", type="password")
            mcp_url = (
                os.environ.get("DATAHUB_MCP_URL")
                or (f"{server.rstrip('/')}/integrations/ai/mcp/" if server else "")
            )
        st.caption(f"Managed MCP endpoint: `{mcp_url or 'enter the tenant URL'}`")
    else:
        server = st.text_input(
            "DataHub server", value=os.environ.get("DATAHUB_SERVER", "http://localhost:8080")
        ).strip()
        mcp_url = ""
        token = st.text_input("DataHub token (optional for local DataHub)", type="password")
    max_hops = st.slider("Max upstream hops", 1, 6, 3)
    local_model_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    judge_endpoint_default = os.environ.get("LINEAGE_REASONING_ENDPOINT", DEFAULT_JUDGE_ENDPOINT)
    judge_endpoint = st.text_input(
        "Judge model gateway URL (optional)", value=judge_endpoint_default,
        placeholder="https://lineage-detective-judge-gateway.<account>.workers.dev",
        help="This is a server-side relay. It does not reveal or store the provider API key in this app.",
    ).strip()
    judge_code = st.text_input(
        "Judge access code (optional)", type="password",
        help="Provided with the judge instructions. It authorizes the bounded server-side model relay; it is not a provider API key.",
    ).strip()
    gateway_model = bool(judge_endpoint and judge_code)
    model_available = local_model_key or gateway_model
    if local_model_key:
        st.success("Model-backed reasoning available with this process's private server key.")
    elif gateway_model:
        st.success("Model-backed judge gateway ready. The provider key remains server-side.")
    else:
        st.info(
            "Evidence-only mode: real DataHub MCP evidence + deterministic checks. The bounded "
            "judge gateway URL is preloaded; enter the supplied judge access code for full "
            "model-backed reasoning and repair."
        )
    contain = st.checkbox("Contain the confirmed incident in DataHub", value=model_available,
                          disabled=not model_available,
                          help="Model-backed default: writes quarantine/impact tags through MCP and reads them back to confirm. You may uncheck it for a read-only model-backed investigation. Evidence-only judge mode is always read-only.")
    st.caption("No token is stored by this app. A private cloud tenant may require one.")

    if "incident_example" not in st.session_state:
        _load_full_repair_example()

st.button(
    "Load the complete rewrite walkthrough",
    on_click=_load_full_repair_example,
    help="Loads the repairable schema-drift incident so every judge-facing stage can be tested.",
    width="stretch",
)
example = st.selectbox(
    "Start from an example incident",
    list(EXAMPLES.keys()),
    key="incident_example",
    on_change=_load_selected_example,
)
if example == CUSTOM_INCIDENT:
    st.info(
        "Custom mode is live, not a canned scenario: search this connected DataHub, choose an asset, "
        "describe the symptom, and optionally attach the checked-out dbt SQL file that may need repair."
    )
elif example == REPAIR_EXAMPLE:
    st.success("Full path selected: investigate → evidence-bound rewrite → explicit approval → real sandbox test → apply or hand off.")
else:
    st.success(
        "Full path selected: investigate, confirm DataHub writes, draft an incident-specific dbt "
        "guard, prove it in a real sandbox, then apply or hand off."
    )

with st.expander("Find an asset in this DataHub", expanded=example == CUSTOM_INCIDENT):
    st.caption(
        "Search uses the connected tenant's official DataHub MCP search tool. Results are not a local list."
    )
    asset_query = st.text_input(
        "Asset name or business term",
        key="asset_search_query",
        placeholder="customer revenue, orders, finance dashboard…",
    ).strip()
    if st.button("Search connected DataHub", width="stretch", key="asset-search-button"):
        if not asset_query:
            st.warning("Enter an asset name or business term.")
        else:
            st.session_state["asset_search_completed"] = False
            try:
                with MCPDataHub(
                    gms_url=server,
                    token=token or None,
                    enable_mutations=False,
                    mcp_url=mcp_url or None,
                ) as search_client:
                    live_results = search_client.search(
                        asset_query,
                        num_results=15,
                    )
                    st.session_state["asset_search_results"] = live_results
                    st.session_state["asset_search_completed"] = True
                    if live_results:
                        st.session_state["asset_search_selection"] = str(live_results[0]["urn"])
                        st.session_state["incident_asset"] = str(live_results[0]["urn"])
            except Exception as exc:
                st.session_state["asset_search_results"] = []
                st.session_state["asset_search_completed"] = True
                st.error(f"DataHub search failed: {type(exc).__name__}: {exc}")
    search_results = st.session_state.get("asset_search_results") or []
    if search_results:
        result_by_urn = {str(item["urn"]): item for item in search_results}
        st.selectbox(
            "Use this affected asset",
            list(result_by_urn),
            format_func=lambda urn: f"{result_by_urn[urn]['name']} · {urn}",
            key="asset_search_selection",
            on_change=_select_search_result,
        )
        st.caption(f"{len(search_results)} live catalog result(s). Pick one to populate the incident.")
    elif st.session_state.get("asset_search_completed") and asset_query:
        st.warning("No matching assets were returned by this DataHub. Try a broader business term.")

symptom = st.text_area("What looks wrong?", key="incident_symptom", height=90)
affected = st.text_input("Affected asset URN", key="incident_asset")

repair_artifact = None
with st.expander("Optional: give Trace the real dbt SQL file to repair", expanded=False):
    st.caption(
        "Use this when the likely fault is in a checked-out dbt model or singular test available "
        "on the machine running Lineage Detective. Trace reads it for this run only."
    )
    repair_path_text = st.text_input(
        "Existing .sql file path",
        key="incident_repair_path",
        placeholder=r"C:\work\analytics\models\orders.sql",
    ).strip()
    if repair_path_text:
        candidate = Path(repair_path_text).expanduser()
        try:
            resolved_candidate = candidate.resolve(strict=True)
            if candidate.is_symlink() or not resolved_candidate.is_file() or resolved_candidate.suffix.lower() != ".sql":
                raise OSError("Choose an existing regular .sql file.")
            if resolved_candidate.stat().st_size > 200_000:
                raise OSError("The selected SQL file exceeds the 200 KB repair limit.")
            repair_artifact = {
                "path": str(resolved_candidate),
                "file_name": resolved_candidate.name,
                "sql": resolved_candidate.read_text(encoding="utf-8"),
            }
            st.success(f"Repair target loaded: `{resolved_candidate}`")
        except (OSError, UnicodeError) as exc:
            st.error(f"Repair target unavailable: {exc}")

if model_available and repair_artifact:
    manual_primary_label = "Investigate, contain & draft file repair" if contain else "Investigate & draft file repair"
elif model_available and example == CUSTOM_INCIDENT:
    manual_primary_label = "Investigate & contain this incident" if contain else "Investigate this incident"
elif model_available and example == REPAIR_EXAMPLE:
    manual_primary_label = "Investigate, contain & draft rewrite" if contain else "Investigate & draft rewrite"
elif model_available:
    manual_primary_label = "Investigate, contain & draft guard" if contain else "Investigate & draft guard"
else:
    manual_primary_label = "Investigate (evidence-only, read-only)"

deployment_profile = None
deployment_profile_ready = True
with st.expander("Manual mode & advanced settings", expanded=False):
    manual_mode = st.checkbox(
        "Pause for review at every stage",
        value=False,
        key="manual_workflow_mode",
        help=(
            "Off: one approval runs investigation, containment, repair generation, sandbox proof, "
            "the selected finish action, and handoff. On: Trace pauses before sandbox and implementation."
        ),
    )
    finish_options = ["Prove safe write + prepare handoff", "Prepare verified handoff only"]
    if repair_artifact:
        finish_options.append("Apply to selected SQL + prepare handoff")
        if os.environ.get("HOSTED_MODE") != "1":
            finish_options.append("Deploy verified repair + confirm live health")
    autonomous_finish_mode = st.selectbox(
        "After the sandbox passes",
        finish_options,
        key="autonomous_finish_mode",
        help=(
            "The safe-write option applies only to Lineage Detective's disposable demonstration "
            "copy. A real selected SQL file is changed only when that explicit option is chosen. "
            "Self-hosted deployment additionally runs the customer's deploy, live-check, rollback, "
            "and rollback-check commands under the same approval."
        ),
    )
    if autonomous_finish_mode == "Deploy verified repair + confirm live health":
        st.info(
            "For a customer running Lineage Detective inside their own environment: Trace will "
            "write the exact verified file, deploy it, check the real service, and automatically "
            "restore and verify the prior release if that check fails. Credentials stay in the "
            "customer's existing environment or credential manager."
        )
        source_candidate = Path(str((repair_artifact or {}).get("path") or "")).expanduser()
        default_root = os.environ.get(
            "LINEAGE_DEPLOYMENT_ROOT",
            str(source_candidate.parent if source_candidate.name else Path.cwd()),
        )
        try:
            default_deployment_timeout = min(
                max(int(os.environ.get("LINEAGE_DEPLOYMENT_TIMEOUT", "300")), 1),
                1800,
            )
        except ValueError:
            default_deployment_timeout = 300
        deployment_name = st.text_input(
            "Deployment name",
            value=os.environ.get("LINEAGE_DEPLOYMENT_NAME", "Production data project"),
            key="deployment_profile_name",
        )
        deployment_root = st.text_input(
            "Project folder",
            value=default_root,
            key="deployment_profile_root",
            help="The selected SQL file must be inside this customer-controlled project.",
        )
        deployment_command = st.text_input(
            "Deploy command",
            value=os.environ.get("LINEAGE_DEPLOY_COMMAND", ""),
            key="deployment_profile_deploy",
            placeholder="dbt build --select path.to.model",
            help="Executed without a shell, so pipes and chained shell commands are not interpreted.",
        )
        verification_command = st.text_input(
            "Live health-check command",
            value=os.environ.get("LINEAGE_DEPLOY_VERIFY_COMMAND", ""),
            key="deployment_profile_verify",
            placeholder="python verify_production.py",
            help="This must read the downstream result. A successful deploy response alone is not proof.",
        )
        rollback_command = st.text_input(
            "Rollback command",
            value=os.environ.get("LINEAGE_DEPLOY_ROLLBACK_COMMAND", ""),
            key="deployment_profile_rollback",
            placeholder="dbt build --select path.to.model",
            help="Runs after Trace restores the exact prior source bytes.",
        )
        rollback_verification_command = st.text_input(
            "Rollback health-check command",
            value=os.environ.get("LINEAGE_DEPLOY_ROLLBACK_VERIFY_COMMAND", ""),
            key="deployment_profile_rollback_verify",
            placeholder="python verify_previous_release.py",
            help="Confirms the prior state is healthy after an automatic rollback.",
        )
        deployment_timeout = st.number_input(
            "Maximum seconds per deployment step",
            min_value=1,
            max_value=1800,
            value=default_deployment_timeout,
            step=30,
            key="deployment_profile_timeout",
        )
        deployment_profile = {
            "kind": "self_hosted_commands",
            "name": deployment_name,
            "cwd": deployment_root,
            "deploy_command": deployment_command,
            "verify_command": verification_command,
            "rollback_command": rollback_command,
            "rollback_verify_command": rollback_verification_command,
            "timeout_seconds": float(deployment_timeout),
        }
        missing_profile_fields = [
            label for label, value in (
                ("project folder", deployment_root),
                ("deploy command", deployment_command),
                ("live health-check command", verification_command),
                ("rollback command", rollback_command),
                ("rollback health-check command", rollback_verification_command),
            ) if not str(value).strip()
        ]
        if missing_profile_fields:
            deployment_profile_ready = False
            st.warning(
                "Complete before running: " + ", ".join(missing_profile_fields) + "."
            )
        else:
            st.success(
                "Deployment profile complete. One approval now covers sandbox proof, exact write, "
                "deployment, independent live readback, and verified rollback on failure."
            )
    st.caption(
        "Connection, reasoning, containment, lineage depth, and external-provider controls remain "
        "available in the sidebar and verified-result sections."
    )

workflow_active = bool(
    st.session_state.get("workflow_run_requested")
    or st.session_state.get("workflow_running")
)
manual_clicked = False
if manual_mode:
    manual_clicked = st.button(
        manual_primary_label,
        type="primary",
        width="stretch",
        disabled=workflow_active,
    )
    st.caption("Manual mode pauses after the proposal so you can review and approve each later action.")
elif workflow_active:
    st.button(
        "Cancel current run",
        type="primary",
        width="stretch",
        on_click=_cancel_autonomous_workflow,
        help="Stops at the next real workflow checkpoint and clears this run's generated artifacts.",
    )
    st.caption("Trace is working through the approved scope. Cancel remains available while it runs.")
else:
    st.button(
        "Approve & run full verified workflow",
        type="primary",
        width="stretch",
        on_click=_queue_autonomous_workflow,
        disabled=not deployment_profile_ready,
        help=(
            "One approval runs the complete evidence-to-verification path. It never merges a pull "
            "request or invents credentials. Complete every required deployment-profile field "
            "before a live deployment run."
        ),
    )
    st.caption(
        "One approval: investigate → contain → draft → sandbox-test → complete the selected finish "
        "action → prepare the receipt-backed handoff."
    )

workflow_status = st.empty()
workflow_status.markdown(_workflow_html(_workflow_phase()), unsafe_allow_html=True)
# Repair controls and investigation callbacks share this single action-local
# progress surface; no second execution banner is rendered at the top.
detective_status = workflow_status

autonomous_error = st.session_state.get("autonomous_workflow_error")
if autonomous_error:
    st.error(
        "The autonomous workflow stopped before completion. "
        f"{autonomous_error}"
    )
autonomous_result_status = st.session_state.get("autonomous_workflow_result") or {}
if autonomous_result_status and not autonomous_result_status.get("verified"):
    failed_receipt = st.session_state.get("repair_receipt") or {}
    failed_reason = (
        failed_receipt.get("error")
        or autonomous_result_status.get("state")
        or "The repair did not earn a verified receipt."
    )
    st.error(
        "The autonomous workflow stopped before completion. "
        f"{failed_reason}"
    )

run_autonomous_now = bool(
    not manual_mode
    and st.session_state.get("workflow_run_requested")
    and not st.session_state.get("workflow_running")
    and not st.session_state.get("workflow_cancel_requested")
)
if manual_clicked or run_autonomous_now:
    if run_autonomous_now:
        st.session_state["workflow_run_requested"] = False
        st.session_state["workflow_running"] = True

    def _run_investigation() -> None:
        _check_workflow_cancelled()
        for key in _WORKFLOW_RESULT_KEYS:
            st.session_state.pop(key, None)
        _render_detective(
            workflow_status,
            "connecting",
            "Checking the local catalog before Trace starts reading evidence.",
        )

        def show_progress(phase: str, detail: str) -> None:
            _check_workflow_cancelled()
            current_detail = detail or _STAGE_COPY.get(phase, ("Working", "Working"))[1]
            display_phase = "report" if phase == "complete" else phase
            _render_detective(detective_status, display_phase, current_detail)

        try:
            _check_workflow_cancelled()
            if not symptom.strip():
                raise ValueError("Describe what looks wrong before starting the investigation.")
            if not affected.strip().startswith("urn:li:"):
                raise ValueError(
                    "Choose a live search result or enter a valid DataHub URN beginning with `urn:li:`."
                )
            catalog_ready, catalog_error = _local_catalog_preflight(server)
            if not catalog_ready:
                raise ConnectionError(catalog_error)
            _render_detective(
                detective_status,
                "connecting",
                "The local DataHub health check passed. Starting the official MCP server.",
            )
            if contain:
                _render_detective(
                    detective_status,
                    "connecting",
                    "Checking the incident-tag vocabulary once before the investigation.",
                )
                vocab = _vocab_ready(server, token or None)
                if vocab != "ok":
                    _render_detective(
                        detective_status,
                        "connecting",
                        f"Setup {vocab}; continuing read-first and claiming only confirmed writes.",
                    )
            st.session_state["report"] = investigate(
                symptom, affected, server=server, token=token or None, max_hops=max_hops, act=contain,
                on_progress=show_progress, reasoning_mode="auto",
                reasoning_endpoint=judge_endpoint or None, judge_code=judge_code or None,
                repair_artifact=repair_artifact,
                mcp_url=mcp_url or None,
            )
            _check_workflow_cancelled()
            repair_proposal = st.session_state["report"].get("repair")
            if repair_proposal and repair_proposal.get("state") == "approval_required":
                _reset_demo_apply_target(repair_proposal)
            st.session_state.pop("repair_receipt", None)
            st.session_state.pop("handoff_packet", None)
            st.session_state.pop("apply_receipt", None)
            st.session_state.pop("restore_receipt", None)
            confirmed_action = (st.session_state["report"].get("action") or {}).get("applied")
            if confirmed_action:
                _render_detective(
                    detective_status,
                    "contained",
                    "The requested tags were read back from DataHub.",
                )
            else:
                _render_detective(
                    detective_status,
                    "report",
                    "The verified result is available below.",
                )
            workflow_status.markdown(_workflow_html(_workflow_phase()), unsafe_allow_html=True)
        except WorkflowCancelled:
            raise
        except Exception as exc:
            _render_detective(
                detective_status,
                "error",
                f"{type(exc).__name__}: {exc}",
            )
            st.error(f"Investigation failed: {type(exc).__name__}: {exc}")

    if run_autonomous_now:
        try:
            _run_investigation()
            if st.session_state.get("report"):
                _run_autonomous_followthrough(
                    st.session_state["report"],
                    workflow_status,
                    finish_mode=autonomous_finish_mode,
                    deployment_profile=deployment_profile,
                )
        except WorkflowCancelled:
            for key in _WORKFLOW_RESULT_KEYS:
                st.session_state.pop(key, None)
            st.info("The autonomous workflow was cancelled. No unverified downstream action was kept.")
        except Exception as exc:
            st.session_state["autonomous_workflow_error"] = (
                f"{type(exc).__name__}: {exc}"
            )
        finally:
            st.session_state["workflow_run_requested"] = False
            st.session_state["workflow_running"] = False
            st.session_state["workflow_cancel_requested"] = False
            st.rerun()
    else:
        _run_investigation()

if st.session_state.get("report"):
    _render_investigation(st.session_state["report"])
    _render_repair(st.session_state["report"], detective_status, workflow_status)
