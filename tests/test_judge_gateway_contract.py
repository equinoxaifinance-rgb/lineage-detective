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
        self.assertIn('judge-auth-attempt', SOURCE)
        self.assertIn('judge-reasoning', SOURCE)
        self.assertNotIn('${clientIp}:${suppliedCode}', SOURCE)
        self.assertIn('MAX_OUTPUT_TOKENS = 3_000', SOURCE)
        self.assertIn('MAX_BODY_BYTES = 60_000', SOURCE)
        self.assertIn('validOptionalText(body?.system, MAX_SYSTEM_CHARS)', SOURCE)
        self.assertEqual(CONFIG["ratelimits"][0]["simple"]["limit"], 10)
        self.assertEqual(CONFIG["ratelimits"][0]["simple"]["period"], 60)
        self.assertIn("env.JUDGE_BUDGET.getByName", SOURCE)
        self.assertEqual(CONFIG["durable_objects"]["bindings"][0]["class_name"], "JudgeBudget")
        self.assertEqual(CONFIG["migrations"][0]["new_sqlite_classes"], ["JudgeBudget"])

    def test_judge_access_has_a_visible_fail_closed_expiration(self):
        self.assertEqual(CONFIG["vars"]["JUDGE_ACCESS_EXPIRES"], "2026-09-15T23:59:59Z")
        self.assertIn("judge_access_window_misconfigured", SOURCE)
        self.assertIn("judge_access_expired", SOURCE)
        self.assertIn("access_expires", SOURCE)
        self.assertIn("access_active", SOURCE)
        self.assertIn('url.pathname === "/preflight"', SOURCE)
        self.assertIn('judge-budget/status?cap=', SOURCE)
        self.assertIn("daily_requests_remaining", SOURCE)

    def test_invalid_authenticated_requests_do_not_consume_daily_budget(self):
        validation = SOURCE.index("invalid_reasoning_request")
        consumption = SOURCE.index("judge-budget/consume?cap=")
        provider = SOURCE.index('fetch("https://api.anthropic.com/v1/messages"')
        self.assertLess(validation, consumption)
        self.assertLess(consumption, provider)

    def test_body_limit_is_enforced_on_read_bytes_not_only_content_length(self):
        self.assertIn("new Uint8Array(await request.arrayBuffer())", SOURCE)
        self.assertIn("rawBody.byteLength > MAX_BODY_BYTES", SOURCE)
        self.assertIn('new TextDecoder("utf-8", { fatal: true })', SOURCE)


if __name__ == "__main__":
    unittest.main()
