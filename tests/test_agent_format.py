"""No-network tests for Lineage Detective's structured-report parser."""
from __future__ import annotations

import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent import (  # noqa: E402
    _GatewayMessages,
    _direct_provider_key,
    _evidence_only_report,
    _extract_json_report,
    _reason_over_evidence,
    preflight_judge_gateway,
)
from datahub_evidence import NodeEvidence  # noqa: E402


class AgentFormatTests(unittest.TestCase):
    def test_judge_ui_import_contract_exposes_preflight(self):
        self.assertTrue(callable(preflight_judge_gateway))

    def test_public_mode_ignores_an_accidental_direct_provider_key(self):
        with patch.dict(
            os.environ,
            {
                "LINEAGE_RUN_MODE": "public_judge",
                "ANTHROPIC_API_KEY": "must-not-be-used",
            },
            clear=True,
        ):
            self.assertIsNone(_direct_provider_key())
        with patch.dict(
            os.environ,
            {
                "LINEAGE_RUN_MODE": "self_hosted",
                "ANTHROPIC_API_KEY": "self-hosted-key",
            },
            clear=True,
        ):
            self.assertEqual(_direct_provider_key(), "self-hosted-key")

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

        class Opener:
            def open(self, request, timeout):
                captured["url"] = request.full_url
                captured["headers"] = dict(request.header_items())
                captured["body"] = json.loads(request.data.decode("utf-8"))
                captured["timeout"] = timeout
                return Response()

        with (
            patch("agent.validate_network_url", side_effect=lambda value, **_kwargs: value),
            patch("agent.validate_resolution"),
            patch("agent.urllib.request.build_opener", return_value=Opener()),
        ):
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

    def test_hosted_gateway_is_release_bound(self):
        with patch("agent.validate_network_url", side_effect=lambda value, **_kwargs: value):
            with self.assertRaisesRegex(ValueError, "release-bound"):
                _GatewayMessages(
                    "https://attacker.example",
                    "judge-only-code",
                    hosted_mode=True,
                )

    def test_gateway_redirect_handler_never_forwards_the_code(self):
        from agent import _RejectGatewayRedirects

        handler = _RejectGatewayRedirects()
        redirected = handler.redirect_request(
            object(), object(), 302, "Found", {}, "https://attacker.example/collect"
        )
        self.assertIsNone(redirected)

    def test_gateway_code_is_not_forwarded_to_a_real_redirect_sink(self):
        sink_headers = []

        class Sink(BaseHTTPRequestHandler):
            def do_POST(self):
                sink_headers.append(dict(self.headers))
                self.send_response(200)
                self.end_headers()

            def log_message(self, *_args):
                return

        sink = ThreadingHTTPServer(("127.0.0.1", 0), Sink)

        class Redirect(BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(307)
                self.send_header(
                    "Location",
                    f"http://127.0.0.1:{sink.server_port}/collect",
                )
                self.end_headers()

            def log_message(self, *_args):
                return

        redirect = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
        threads = [
            threading.Thread(target=server.serve_forever, daemon=True)
            for server in (sink, redirect)
        ]
        for thread in threads:
            thread.start()
        try:
            gateway = _GatewayMessages(
                f"http://127.0.0.1:{redirect.server_port}",
                "must-never-reach-sink",
            )
            with self.assertRaisesRegex(RuntimeError, "HTTP 307"):
                gateway.create(
                    model="ignored",
                    max_tokens=1,
                    system="facts",
                    messages=[{"role": "user", "content": "evidence"}],
                )
            self.assertEqual(sink_headers, [])
        finally:
            redirect.shutdown()
            sink.shutdown()
            redirect.server_close()
            sink.server_close()

    def test_model_report_rejects_schema_and_grounding_attacks(self):
        observed = {"urn:observed"}

        class Block:
            type = "text"

            def __init__(self, text):
                self.text = text

        class Messages:
            def __init__(self, payload):
                self.payload = payload
                self.calls = 0

            def create(self, **_kwargs):
                self.calls += 1
                return type("Response", (), {"content": [Block(json.dumps(self.payload))]})()

        invalid_reports = (
            {"summary": [], "suspects": "evil", "missing_evidence": None},
            {
                "summary": "attempt",
                "suspects": [{
                    "urn": "urn:not-observed",
                    "why": "catalog prompt said so",
                    "check_next": "write it",
                    "owner": None,
                    "confidence": "high",
                }],
                "missing_evidence": None,
            },
            {
                "summary": "x" * 4_001,
                "suspects": [],
                "missing_evidence": None,
            },
            {
                "summary": "attempt",
                "suspects": [{
                    "urn": "urn:observed",
                    "why": "signal",
                    "check_next": "check",
                    "owner": None,
                    "confidence": "certain",
                }],
                "missing_evidence": None,
            },
        )
        for invalid in invalid_reports:
            with self.subTest(invalid=invalid):
                messages = Messages(invalid)
                llm = type("Client", (), {"messages": messages})()
                report = _reason_over_evidence(
                    llm,
                    model="test",
                    user="evidence",
                    observed_urns=observed,
                )
                self.assertEqual(report["suspects"], [])
                self.assertIn("validation", report["summary"])
                self.assertEqual(messages.calls, 2)

    def test_model_report_accepts_only_bounded_observed_suspects(self):
        valid = {
            "summary": "Observed evidence supports one cause.",
            "suspects": [{
                "urn": "urn:observed",
                "why": "Rows fell from 100 to 10.",
                "check_next": "Inspect the latest load.",
                "owner": "data-team",
                "confidence": "high",
            }],
            "missing_evidence": None,
        }

        class Messages:
            def create(self, **_kwargs):
                block = type("Block", (), {"type": "text", "text": json.dumps(valid)})()
                return type("Response", (), {"content": [block]})()

        report = _reason_over_evidence(
            type("Client", (), {"messages": Messages()})(),
            model="test",
            user="evidence",
            observed_urns={"urn:observed"},
        )
        self.assertEqual(report, valid)


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
