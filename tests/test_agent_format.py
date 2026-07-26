"""No-network tests for Lineage Detective's structured-report parser."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent import _GatewayMessages, _extract_json_report, _evidence_only_report  # noqa: E402
from datahub_evidence import NodeEvidence  # noqa: E402


class AgentFormatTests(unittest.TestCase):
    def test_accepts_plain_json(self):
        self.assertEqual(_extract_json_report('{"summary":"ok","suspects":[]}')["summary"], "ok")

    def test_accepts_fenced_or_preamble_json(self):
        self.assertEqual(_extract_json_report('```json\n{"summary":"ok"}\n```')["summary"], "ok")
        self.assertEqual(_extract_json_report('Here is the report:\n{"summary":"ok"}')["summary"], "ok")

    def test_rejects_non_json(self):
        self.assertIsNone(_extract_json_report("No structured response"))

    def test_gateway_sends_only_evidence_and_judge_code_not_a_provider_key(self):
        captured = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"text":"{\\\"summary\\\":\\\"ok\\\",\\\"suspects\\\":[]}"}'

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return Response()

        with patch("agent.urllib.request.urlopen", fake_urlopen):
            response = _GatewayMessages("https://judge.example", "judge-only-code").create(
                model="ignored-by-gateway", max_tokens=1, system="system facts",
                messages=[
                    {"role": "user", "content": "original DataHub evidence"},
                    {"role": "user", "content": "format correction"},
                ],
            )
        self.assertEqual(captured["url"], "https://judge.example/reason")
        self.assertEqual(captured["headers"]["X-lineage-judge-code"], "judge-only-code")
        self.assertEqual(captured["headers"]["User-agent"], "Lineage-Detective-Judge/1.0")
        self.assertNotIn("api-key", " ".join(captured["headers"]).lower())
        self.assertEqual(captured["body"]["system"], "system facts")
        self.assertIn("original DataHub evidence", captured["body"]["user"])
        self.assertIn("format correction", captured["body"]["user"])
        self.assertEqual(response.content[0].text, '{"summary":"ok","suspects":[]}')


class EvidenceOnlyReasoningTests(unittest.TestCase):
    def test_ranks_a_real_volume_delta_without_model_or_hardcoded_urn(self):
        report = _evidence_only_report([
            NodeEvidence("urn:li:dataset:(urn:li:dataPlatform:looker,bi.metric,PROD)"),
            NodeEvidence("urn:li:dataset:(urn:li:dataPlatform:bigquery,warehouse.raw.transactions,PROD)",
                         owners=["urn:li:corpuser:owner"], custom_properties={
                             "rows_loaded_latest_run": "450", "rows_prior_7day_avg": "1000",
                             "volume_test": "not_configured"}),
        ])
        self.assertEqual(report["reasoning_mode"], "evidence_only_deterministic")
        self.assertEqual(report["suspects"][0]["urn"], "urn:li:dataset:(urn:li:dataPlatform:bigquery,warehouse.raw.transactions,PROD)")
        self.assertIn("55% below", report["suspects"][0]["why"])

    def test_detects_schema_null_surge_from_generic_metadata(self):
        report = _evidence_only_report([
            NodeEvidence("dashboard"),
            NodeEvidence("staging", schema_fields=["id", "email"], custom_properties={
                "email_null_rate_current": "1.00", "email_null_rate_prior": "0.01"}),
            NodeEvidence("raw", schema_fields=["id", "email", "email_address"]),
        ])
        self.assertEqual(report["suspects"][0]["urn"], "staging")
        self.assertIn("email_address", report["suspects"][0]["why"])

    def test_declines_to_diagnose_sparse_evidence(self):
        report = _evidence_only_report([NodeEvidence("dataset", custom_properties={"team": "analytics"})])
        self.assertEqual(report["suspects"], [])
        self.assertIn("no deterministic", report["summary"])


if __name__ == "__main__":
    unittest.main()
