"""Release checks for the judge-facing UI contract without a browser or network."""
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "app.py").read_text(encoding="utf-8")


class JudgeUiContractTests(unittest.TestCase):
    def test_original_mascot_asset_is_shipped_as_a_png(self):
        mascot = ROOT / "assets" / "lineage-detective-mascot.png"
        self.assertTrue(mascot.is_file(), "judge checkout must include the mascot asset")
        self.assertEqual(mascot.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_progress_copy_is_evidence_bound_not_a_fake_timer(self):
        for phase in ("connecting", "evidence", "reasoning", "containment", "repair", "visualizing", "complete"):
            self.assertIn(f'"{phase}"', APP)
        self.assertIn("reading back before any containment claim", APP)
        self.assertIn("status.update(label=\"Investigation stopped\"", APP)

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


if __name__ == "__main__":
    unittest.main()
