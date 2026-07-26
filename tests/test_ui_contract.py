"""Release checks for the judge-facing UI contract without a browser or network."""
from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "app.py").read_text(encoding="utf-8")
AGENT = (ROOT / "src" / "agent.py").read_text(encoding="utf-8")
RECORDER = (ROOT / "tools" / "record_judge_demo.py").read_text(encoding="utf-8")
VIDEO_BUILDER = (ROOT / "tools" / "build_judge_video.py").read_text(encoding="utf-8")


class JudgeUiContractTests(unittest.TestCase):
    def test_original_mascot_asset_is_shipped_as_a_png(self):
        mascot = ROOT / "assets" / "lineage-detective-mascot.png"
        self.assertTrue(mascot.is_file(), "judge checkout must include the mascot asset")
        self.assertEqual(mascot.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_progress_copy_is_evidence_bound_not_a_fake_timer(self):
        for phase in (
            "connecting", "evidence", "reasoning", "containment", "repair",
            "sandbox", "handoff", "visualizing", "verified", "complete",
        ):
            self.assertIn(f'"{phase}"', APP)
        self.assertIn("reading back before any containment claim", APP)
        self.assertIn('"Investigation paused"', APP)
        self.assertIn('on_progress=show_sandbox_progress', APP)
        self.assertIn('"sandbox_rollback": 94', APP)

    def test_primary_action_uses_a_deliberate_non_alarm_style(self):
        self.assertIn('button[kind="primary"]', APP)
        self.assertIn("linear-gradient(110deg,#0891b2,#2563eb)", APP)

    def test_catalog_and_model_text_is_escaped_before_entering_html_cards(self):
        self.assertIn("import html", APP)
        self.assertIn('suspect["asset_label"] = html.escape(_asset_label(suspect.get("urn", "")), quote=True)', APP)
        self.assertIn('for key in ("owner", "why", "check_next"):', APP)
        self.assertIn('html.escape(str(suspect.get(key) or ""), quote=True)', APP)

    def test_free_judge_path_is_explicitly_real_evidence_and_read_only(self):
        self.assertIn("Evidence-only mode: real DataHub MCP evidence", APP)
        self.assertIn("disabled=not model_available", APP)
        self.assertIn('reasoning_mode="auto"', APP)
        self.assertIn("Evidence-only judge mode", APP)

    def test_model_backed_judge_path_uses_a_code_but_never_embeds_a_provider_key(self):
        self.assertIn('DEFAULT_JUDGE_ENDPOINT = "https://lineage-detective-judge-gateway.equinoxaifinance.workers.dev"', APP)
        self.assertIn('"Judge model gateway URL (optional)"', APP)
        self.assertIn('"Judge access code (optional)"', APP)
        self.assertIn("reasoning_endpoint=judge_endpoint or None, judge_code=judge_code or None", APP)
        self.assertIn("provider key remains server-side", APP)

    def test_containment_tags_appear_only_after_an_actual_confirmed_action(self):
        self.assertIn('confirmed_action = (st.session_state["report"].get("action") or {}).get("applied")', APP)
        confirmed = APP.index("if confirmed_action:")
        contained = APP.index('"contained"', confirmed)
        readback = APP.index('"The requested tags were read back from DataHub."', contained)
        self.assertLess(confirmed, contained)
        self.assertLess(contained, readback)

    def test_repair_droid_effect_is_bound_to_the_actual_repair_phase(self):
        self.assertIn('progress("repair", "Checking whether the evidence supports a reviewable repair proposal...")', AGENT)
        self.assertIn("_render_detective(detective_status, display_phase, current_detail)", APP)
        self.assertIn('"Drafting a reviewable repair"', APP)

    def test_full_rewrite_walkthrough_is_the_default_judge_path(self):
        self.assertIn('REPAIR_EXAMPLE = "Customer 360 emails went blank (full repair walkthrough)"', APP)
        self.assertIn('"Load the complete rewrite walkthrough"', APP)
        self.assertIn('["Exact diff", "Current artifact", f"Proposed {change_noun}"]', APP)
        self.assertIn('f"Approve this {change_noun} & run the sandbox"', APP)
        self.assertIn('f"Apply verified {change_noun} to this file"', APP)
        self.assertIn('"Restore the verified backup"', APP)
        self.assertIn('"Download restore receipt"', APP)
        self.assertIn("st.session_state.pop(\"restore_receipt\", None)", APP)
        self.assertIn("and not restored", APP)
        self.assertIn("workflow_slot.markdown(_workflow_html(\"sandbox\")", APP)
        self.assertIn("st.rerun()", APP)
        self.assertIn('"Download verified human handoff packet (.zip)"', APP)

    def test_explicit_actions_replace_redundant_approval_checkboxes(self):
        self.assertIn(
            "Clicking the action below is the explicit approval for this exact displayed diff.",
            APP,
        )
        self.assertIn('approval="interactive-ui-approval"', APP)
        self.assertIn('approval="interactive-ui-apply-button"', APP)
        self.assertNotIn("sandbox_approved = st.checkbox", APP)
        self.assertNotIn("handoff_approved = st.checkbox", APP)

    def test_autonomous_primary_path_preserves_optional_manual_control(self):
        self.assertIn('"Approve & run full verified workflow"', APP)
        self.assertIn('"Manual mode & advanced settings"', APP)
        self.assertIn('"Pause for review at every stage"', APP)
        self.assertIn('"Prove safe write + prepare handoff"', APP)
        self.assertIn('"Prepare verified handoff only"', APP)
        self.assertIn('"Apply to selected SQL + prepare handoff"', APP)
        self.assertIn('approval="one-click-ui-full-workflow"', APP)
        self.assertIn("run_approved_workflow(", APP)

    def test_start_control_becomes_a_real_cancel_control(self):
        self.assertIn('"Cancel current run"', APP)
        self.assertIn("on_click=_cancel_autonomous_workflow", APP)
        self.assertIn("def _check_workflow_cancelled()", APP)
        self.assertIn("_check_workflow_cancelled()", APP)
        self.assertIn("except WorkflowCancelled:", APP)
        self.assertIn('st.session_state["workflow_running"] = False', APP)

    def test_autonomous_failures_survive_the_final_streamlit_rerun(self):
        self.assertIn('"autonomous_workflow_error"', APP)
        self.assertIn('autonomous_error = st.session_state.get("autonomous_workflow_error")', APP)
        self.assertIn("if autonomous_error:", APP)
        self.assertIn(
            '"The autonomous workflow stopped before completion. "',
            APP,
        )
        self.assertIn(
            'autonomous_result_status and not autonomous_result_status.get("verified")',
            APP,
        )
        self.assertIn(
            'st.session_state["autonomous_workflow_error"] = (',
            APP,
        )

    def test_stationary_mascot_appears_inside_real_investigation_progress(self):
        self.assertIn('DROID_NAME = "Trace"', APP)
        self.assertIn("workflow_status = st.empty()", APP)
        self.assertIn('aria-label="Verified workflow progress"', APP)
        self.assertIn("ld-workflow-runner", APP)
        self.assertIn("ld-workflow-fill", APP)
        self.assertIn("animation:ld-runner-bob 1.8s ease-in-out infinite", APP)
        self.assertNotIn("animation:ld-spin", APP)
        self.assertNotIn("animation:ld-roam", APP)
        self.assertNotIn("position:fixed", APP)
        self.assertNotIn("activity = st.empty()", APP)
        self.assertNotIn('st.status("Preparing investigation..."', APP)
        self.assertNotIn("Starting a live evidence path; no diagnosis has been made yet.", APP)
        self.assertIn("@media(prefers-reduced-motion:reduce)", APP)
        self.assertIn('f"Constrained {change_noun} drafted"', APP)
        self.assertIn('"Trace used the returned evidence to propose this exact diff. Nothing has been executed yet."', APP)

    def test_every_long_running_ui_path_uses_the_named_droid_panel(self):
        self.assertIn("sandbox_stage = st.empty()", APP)
        self.assertIn("sandbox_stage.markdown(", APP)
        self.assertIn('"sandbox",', APP)
        self.assertIn("_workflow_html(phase, detail=detail)", APP)
        self.assertNotIn("st.status(", APP)
        self.assertNotIn("status.write(", APP)
        self.assertNotIn("status.update(", APP)
        self.assertNotIn("st.progress(", APP)

    def test_title_and_execution_progress_have_distinct_nonduplicated_roles(self):
        self.assertIn("def _title_html()", APP)
        self.assertIn('aria-label="Lineage Detective"', APP)
        self.assertIn("ld-title-mascot", APP)
        self.assertIn("st.markdown(_title_html(), unsafe_allow_html=True)", APP)
        self.assertIn("# progress surface; no second execution banner is rendered at the top.", APP)
        self.assertNotIn("_render_detective(detective_status)", APP)
        self.assertNotIn("def _detective_html(", APP)
        self.assertNotIn('aria-label="Lineage Detective status"', APP)

    def test_video_recorder_requires_visible_monotonic_action_local_progress(self):
        self.assertIn('[aria-label="Verified workflow progress"]', RECORDER)
        self.assertIn('status.wait_for(state="visible"', RECORDER)
        self.assertIn("Workflow progress moved backward:", RECORDER)
        self.assertIn('f"progress:{value}"', RECORDER)
        self.assertIn('"progress:100"', RECORDER)
        status_region = RECORDER.split("status = page.locator", 1)[1].split(
            "complete = page.get_by_text", 1
        )[0]
        self.assertNotIn("scroll_into_view_if_needed", status_region)
        self.assertNotIn("except Exception", status_region)

    def test_video_builder_rejects_narration_overlap(self):
        self.assertIn("The live timeline, not a minimum narration preference", VIDEO_BUILDER)
        self.assertIn('"mixed_seconds"', VIDEO_BUILDER)
        self.assertIn('"ends_at"', VIDEO_BUILDER)
        self.assertIn("Narration timing collision:", VIDEO_BUILDER)
        self.assertIn("Final narration overruns the captured video:", VIDEO_BUILDER)
        self.assertIn("MAX_SILENCE_SECONDS = 3.0", VIDEO_BUILDER)
        self.assertIn("silencedetect=noise=-38dB:d=1.0", VIDEO_BUILDER)
        self.assertIn("Narration left an unsupported visual stretch:", VIDEO_BUILDER)
        self.assertNotIn("\"I'm Codex.", VIDEO_BUILDER)

    def test_completed_autonomous_run_cannot_be_rendered_back_as_review(self):
        autonomous = APP.index("if autonomous_is_current:")
        handoff = APP.index('workflow_slot.markdown(_workflow_html("handoff")', autonomous)
        sandbox = APP.index('workflow_slot.markdown(_workflow_html("sandbox")', handoff)
        review = APP.index('workflow_slot.markdown(_workflow_html("review")', sandbox)
        self.assertLess(autonomous, handoff)
        self.assertLess(handoff, sandbox)
        self.assertLess(sandbox, review)

    def test_preflight_vocabulary_check_does_not_move_progress_past_reasoning(self):
        vocab_check = APP.index('"Checking the incident-tag vocabulary once before the investigation."')
        preceding = APP[max(0, vocab_check - 180):vocab_check]
        self.assertIn('"connecting"', preceding)
        self.assertNotIn('"containment"', preceding)

    def test_real_autonomous_phase_sequence_is_monotonic(self):
        tree = ast.parse(APP)
        progress_map = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_workflow_html":
                for child in node.body:
                    if (
                        isinstance(child, ast.Assign)
                        and any(isinstance(target, ast.Name) and target.id == "progress"
                                for target in child.targets)
                    ):
                        progress_map = ast.literal_eval(child.value.func.value)
        self.assertIsNotNone(progress_map)
        agent_phases = re.findall(r'progress\("([^"]+)"', AGENT)
        displayed_agent_phases = [
            "report" if phase == "complete" else phase
            for phase in agent_phases
        ]
        full_sequence = (
            ["connecting"]
            + displayed_agent_phases
            + ["contained", "review"]
            + [
                "sandbox_reset", "sandbox_seed", "sandbox_baseline",
                "sandbox_rewrite", "sandbox_verify", "sandbox_rollback",
                "sandbox_complete", "handoff",
            ]
        )
        values = [progress_map[phase] for phase in full_sequence]
        self.assertEqual(values, sorted(values), full_sequence)

    def test_verified_rewrite_has_a_safe_immediately_selectable_demo_target(self):
        self.assertIn("def _ensure_demo_apply_target(repair: dict | None = None)", APP)
        self.assertIn("def _reset_demo_apply_target(repair: dict | None = None)", APP)
        self.assertIn('backup.unlink()', APP)
        self.assertIn("if example == REPAIR_EXAMPLE:", APP)
        self.assertIn('"Safe disposable demo copy"', APP)
        self.assertIn('f"Apply verified {change_noun} to safe demo copy"', APP)
        self.assertNotIn("disabled=not bool(target_file)", APP)
        self.assertIn("Browser-only judges should use the safe demo copy.", APP)
        self.assertIn("Enter an existing host-machine `.sql` path above", APP)

    def test_local_catalog_is_checked_before_slow_mcp_startup(self):
        self.assertIn("def _local_catalog_preflight", APP)
        self.assertIn("catalog_ready, catalog_error = _local_catalog_preflight(server)", APP)
        self.assertIn("raise ConnectionError(catalog_error)", APP)
        preflight = APP.index("catalog_ready, catalog_error = _local_catalog_preflight(server)")
        investigate = APP.index('st.session_state["report"] = investigate(')
        self.assertLess(preflight, investigate)

    def test_vocabulary_setup_caches_success_but_never_transient_failure(self):
        self.assertIn("_VOCAB_READY_SUCCESSES", APP)
        self.assertIn("_VOCAB_READY_SUCCESSES.add(cache_key)", APP)
        vocab_region = APP.split("def _vocab_ready", 1)[0]
        self.assertNotIn("@st.cache_resource", vocab_region[-80:])

    def test_custom_incident_lane_uses_live_search_and_arbitrary_inputs(self):
        self.assertIn('CUSTOM_INCIDENT = "My own DataHub incident"', APP)
        self.assertIn('"Search connected DataHub"', APP)
        self.assertIn("search_client.search(", APP)
        self.assertIn('"Use this affected asset"', APP)
        self.assertIn('symptom = st.text_area("What looks wrong?"', APP)
        self.assertIn('affected = st.text_input("Affected asset URN"', APP)
        self.assertIn('"Existing .sql file path"', APP)
        self.assertIn("repair_artifact=repair_artifact", APP)

    def test_custom_incident_errors_are_immediate_and_actionable(self):
        self.assertIn("No matching assets were returned by this DataHub.", APP)
        self.assertIn("Describe what looks wrong before starting the investigation.", APP)
        self.assertIn("enter a valid DataHub URN beginning with `urn:li:`", APP)

    def test_cli_accepts_the_same_real_checked_out_repair_target(self):
        self.assertIn('"--repair-file"', AGENT)
        self.assertIn("Path(args.repair_file).expanduser().resolve(strict=True)", AGENT)
        self.assertIn("repair_artifact=repair_artifact", AGENT)

    def test_verified_repair_exposes_real_target_system_connectors(self):
        self.assertIn("def _render_external_remediation(", APP)
        for label in (
            "Open a GitHub pull request",
            "Trigger a dbt Cloud job",
            "Trigger an Airflow DAG",
            "Pause, resume, or sync Fivetran",
            "Execute one Snowflake statement",
            "Create a DataHub prevention assertion",
            "Run this repository's tests",
        ):
            self.assertIn(label, APP)
        self.assertIn('type="password"', APP)
        self.assertIn("Download connector receipt", APP)
        self.assertIn('"Row-count range"', APP)
        self.assertIn('"Custom SQL metric"', APP)

    def test_datahub_cloud_managed_mcp_is_a_first_class_connection(self):
        self.assertIn('"DataHub Cloud managed MCP"', APP)
        self.assertIn("/integrations/ai/mcp/", APP)
        self.assertIn("Scoped service-account token", APP)
        self.assertIn("mcp_url=mcp_url or None", APP)
        self.assertIn('"Sign in with DataHub OAuth"', APP)
        self.assertIn("authorize_datahub()", APP)


if __name__ == "__main__":
    unittest.main()
