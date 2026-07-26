"""Release checks for the judge-facing UI contract without a browser or network."""
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "app.py").read_text(encoding="utf-8")
AGENT = (ROOT / "src" / "agent.py").read_text(encoding="utf-8")


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
        self.assertIn('"sandbox_rollback": 90', APP)

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
        self.assertIn('tags = "" if phase != "contained"', APP)
        self.assertIn('confirmed_action = (st.session_state["report"].get("action") or {}).get("applied")', APP)

    def test_repair_droid_effect_is_bound_to_the_actual_repair_phase(self):
        self.assertIn('if phase == "repair" else ""', APP)
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

    def test_stationary_mascot_appears_inside_real_investigation_progress(self):
        self.assertIn('DROID_NAME = "Trace"', APP)
        self.assertIn("activity = st.empty()", APP)
        self.assertIn('"Investigation in progress"', APP)
        self.assertIn("animation:ld-search 3.6s ease-in-out infinite", APP)
        self.assertIn("ld-lens-pulse", APP)
        self.assertIn("ld-scan-beam", APP)
        self.assertIn("ld-evidence-node", APP)
        self.assertNotIn("animation:ld-spin", APP)
        self.assertNotIn("animation:ld-roam", APP)
        self.assertNotIn("position:fixed", APP)
        self.assertNotIn('st.status("Preparing investigation..."', APP)
        self.assertNotIn("Starting a live evidence path; no diagnosis has been made yet.", APP)
        self.assertIn("@media (prefers-reduced-motion:reduce)", APP)
        self.assertIn('f"Constrained {change_noun} drafted"', APP)
        self.assertIn('"Trace used the returned evidence to propose this exact diff. Nothing has been executed yet."', APP)

    def test_every_long_running_ui_path_uses_the_named_droid_panel(self):
        self.assertIn("sandbox_stage = st.empty()", APP)
        self.assertIn("_droid_action_html(sandbox_titles.get", APP)
        self.assertNotIn("st.status(", APP)
        self.assertNotIn("status.write(", APP)
        self.assertNotIn("status.update(", APP)
        self.assertNotIn("bar.progress(sandbox_progress.get(phase, 5), text=", APP)

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
