"""Static release checks for the server-side judge gateway.

These tests deliberately do not call a provider. They prove the checked-in Worker
has no credential value and keeps the provider credential on its server-side boundary.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "judge-gateway" / "src" / "index.js").read_text(encoding="utf-8")
CONFIG = json.loads((ROOT / "judge-gateway" / "wrangler.jsonc").read_text(encoding="utf-8"))


class JudgeGatewayContractTests(unittest.TestCase):
    def test_provider_key_is_server_side_and_never_returned(self):
        self.assertIn('"x-api-key": env.ANTHROPIC_API_KEY', SOURCE)
        self.assertNotIn("sk-ant-", SOURCE)
        self.assertNotIn("ANTHROPIC_API_KEY:", SOURCE)
        self.assertIn('return reply(200, { text })', SOURCE)

    def test_judge_access_is_bounded_before_provider_call(self):
        self.assertIn('x-lineage-judge-code', SOURCE)
        self.assertIn('env.JUDGE_RATE.limit', SOURCE)
        self.assertIn('MAX_OUTPUT_TOKENS = 1_500', SOURCE)
        self.assertIn('MAX_BODY_BYTES = 60_000', SOURCE)
        self.assertIn('validOptionalText(body?.system, MAX_SYSTEM_CHARS)', SOURCE)
        self.assertEqual(CONFIG["ratelimits"][0]["simple"]["limit"], 10)
        self.assertEqual(CONFIG["ratelimits"][0]["simple"]["period"], 60)
        self.assertIn("env.JUDGE_BUDGET.getByName", SOURCE)
        self.assertEqual(CONFIG["durable_objects"]["bindings"][0]["class_name"], "JudgeBudget")
        self.assertEqual(CONFIG["migrations"][0]["new_sqlite_classes"], ["JudgeBudget"])


if __name__ == "__main__":
    unittest.main()
