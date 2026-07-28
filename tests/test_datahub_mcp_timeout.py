"""Failure-path tests for the official DataHub MCP connection."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
import textwrap
from pathlib import Path
from unittest import mock

from src.datahub_mcp import MCPDataHub


class McpStartupTimeoutTests(unittest.TestCase):
    def setUp(self):
        self.mode = mock.patch.dict(
            os.environ, {"LINEAGE_RUN_MODE": "self_hosted"}, clear=False
        )
        self.mode.start()
        self.addCleanup(self.mode.stop)

    def test_get_entities_batches_large_reads_and_merges_all_shapes(self):
        client = MCPDataHub(enable_mutations=False, entity_batch_size=3)
        calls = []

        def fake_call(tool, args):
            calls.append((tool, list(args["urns"])))
            entities = [
                {"urn": value, "name": value.rsplit(":", 1)[-1]}
                for value in args["urns"]
            ]
            if len(calls) % 2:
                return json.dumps(entities)
            return json.dumps({"entities": entities})

        client._call = fake_call
        urns = [f"urn:li:dataset:{index}" for index in range(7)]
        result = client.get_entities(urns + [urns[0]])

        self.assertEqual([len(args) for _tool, args in calls], [3, 3, 1])
        self.assertTrue(all(tool == "get_entities" for tool, _args in calls))
        self.assertEqual(set(result), set(urns))

    def test_get_entities_rejects_invalid_batch_configuration(self):
        with mock.patch.dict(
            os.environ, {"LINEAGE_MCP_ENTITY_BATCH_SIZE": "not-a-number"}
        ):
            with self.assertRaisesRegex(ValueError, "must be an integer"):
                MCPDataHub(enable_mutations=False)

    def test_search_normalizes_plain_language_and_returns_selectable_entities(self):
        client = MCPDataHub(enable_mutations=False)
        captured = {}

        def fake_call(tool, args):
            captured.update(tool=tool, args=args)
            return """{
              "searchResults": [
                {"entity": {"urn": "urn:li:dataset:(urn:li:dataPlatform:dbt,analytics.orders,PROD)",
                            "properties": {"name": "analytics.orders"}}},
                {"entity": {"urn": "urn:li:dashboard:(looker,revenue)",
                            "properties": null}}
              ]
            }"""

        client._call = fake_call
        results = client.search("customer revenue", num_results=80)
        self.assertEqual(captured["tool"], "search")
        self.assertEqual(captured["args"]["query"], "/q customer revenue")
        self.assertEqual(captured["args"]["num_results"], 50)
        self.assertEqual(results[0]["name"], "analytics.orders")
        self.assertEqual(results[1]["name"], "revenue")

    def test_unused_document_tools_are_disabled_without_removing_core_mcp_tools(self):
        source = (Path(__file__).resolve().parents[1] / "src" / "datahub_mcp.py").read_text(encoding="utf-8")
        self.assertIn('env["DATAHUB_MCP_DOCUMENT_TOOLS_DISABLED"] = "true"', source)
        self.assertIn('env["DATAHUB_TELEMETRY_ENABLED"] = "false"', source)
        for tool in ("get_lineage", "get_entities", "add_tags", "remove_tags"):
            self.assertIn(tool, source)

    def test_remove_tag_requires_mutation_tool_and_proves_absence(self):
        client = MCPDataHub(enable_mutations=True)
        client.tools = {"remove_tags"}
        captured = {}

        def fake_call(tool, args):
            captured.update(tool=tool, args=args)
            return '{"success": true}'

        client._call = fake_call
        client.get_entities = lambda urns: {
            urns[0]: {"urn": urns[0], "tags": {"tags": []}}
        }
        self.assertTrue(client.remove_tag("urn:li:dataset:test", "urn:li:tag:probe"))
        self.assertEqual(captured["tool"], "remove_tags")
        self.assertEqual(captured["args"]["tag_urns"], ["urn:li:tag:probe"])

    def test_remove_tag_surfaces_a_missing_tool_as_an_error(self):
        client = MCPDataHub(enable_mutations=False)
        client._call = mock.Mock(
            side_effect=RuntimeError("DataHub MCP tool 'remove_tags' returned an error")
        )
        with self.assertRaisesRegex(RuntimeError, "remove_tags"):
            client.remove_tag("urn:li:dataset:test", "urn:li:tag:probe")

    def test_add_tag_waits_for_read_after_write_visibility(self):
        client = MCPDataHub(enable_mutations=True)
        client._call = mock.Mock(return_value='{"success": true}')
        urn = "urn:li:dataset:test"
        tag = "urn:li:tag:probe"
        readbacks = iter([
            {urn: {"urn": urn, "tags": {"tags": []}}},
            {
                urn: {
                    "urn": urn,
                    "tags": {"tags": [{"tag": {"urn": tag}}]},
                }
            },
        ])
        client.get_entities = lambda urns: next(readbacks)
        with mock.patch.dict(
            os.environ,
            {"LINEAGE_MCP_MUTATION_READBACK_SECONDS": "1"},
        ), mock.patch("src.datahub_mcp.time.sleep") as sleep:
            self.assertTrue(client.add_tag(urn, tag))
        sleep.assert_called_once()

    def test_remove_tag_waits_for_read_after_write_visibility(self):
        client = MCPDataHub(enable_mutations=True)
        client._call = mock.Mock(return_value='{"success": true}')
        urn = "urn:li:dataset:test"
        tag = "urn:li:tag:probe"
        readbacks = iter([
            {
                urn: {
                    "urn": urn,
                    "tags": {"tags": [{"tag": {"urn": tag}}]},
                }
            },
            {urn: {"urn": urn, "tags": {"tags": []}}},
        ])
        client.get_entities = lambda urns: next(readbacks)
        with mock.patch.dict(
            os.environ,
            {"LINEAGE_MCP_MUTATION_READBACK_SECONDS": "1"},
        ), mock.patch("src.datahub_mcp.time.sleep") as sleep:
            self.assertTrue(client.remove_tag(urn, tag))
        sleep.assert_called_once()

    def test_startup_does_not_depend_on_tools_list_advertising(self):
        """A real initialized session is usable even if tools/list middleware stalls."""
        fake_server = textwrap.dedent(
            """
            import json, sys, time
            for line in sys.stdin:
                request = json.loads(line)
                method = request.get('method')
                request_id = request.get('id')
                if method == 'initialize':
                    response = {'jsonrpc': '2.0', 'id': request_id, 'result': {
                        'protocolVersion': '2025-03-26', 'capabilities': {},
                        'serverInfo': {'name': 'direct-call-test', 'version': '1.0'}}}
                    print(json.dumps(response), flush=True)
                elif method == 'tools/list':
                    time.sleep(30)
            """
        )
        with tempfile.TemporaryDirectory() as directory:
            server = Path(directory) / "no_list_mcp.py"
            server.write_text(fake_server, encoding="utf-8")
            started = time.monotonic()
            with MCPDataHub(
                enable_mutations=False,
                startup_timeout=2,
                server_command=(sys.executable, [str(server)]),
            ) as client:
                self.assertEqual(client.tools, set())
            self.assertLess(time.monotonic() - started, 4.0)

    def test_managed_cloud_path_uses_streamable_http_and_bearer_header(self):
        source = (Path(__file__).resolve().parents[1] / "src" / "datahub_mcp.py").read_text(encoding="utf-8")
        self.assertIn("streamable_http_client", source)
        self.assertIn('headers = {"Authorization": f"Bearer {self.token}"}', source)
        self.assertIn("await self._serve_remote()", source)

    def test_nonresponsive_server_fails_with_a_bounded_recoverable_error(self):
        """A child that never answers initialize must not leave a judge at Connecting."""
        with tempfile.TemporaryDirectory() as directory:
            sleeper = Path(directory) / "nonresponsive_mcp.py"
            sleeper.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
            started = time.monotonic()
            with self.assertRaisesRegex(
                TimeoutError,
                "did not initialize.*last startup phase=initialize_request",
            ):
                with MCPDataHub(
                    enable_mutations=False,
                    startup_timeout=0.25,
                    server_command=(sys.executable, [str(sleeper)]),
                ):
                    pass
            self.assertLess(
                time.monotonic() - started,
                4.0,
                "startup failure must be bounded rather than waiting for the child process",
            )

    def test_initialized_server_that_never_answers_a_tool_call_is_bounded(self):
        """A catalog that stalls after startup gets the same retryable boundary."""
        fake_server = textwrap.dedent(
            """
            import json, sys, time
            for line in sys.stdin:
                request = json.loads(line)
                method = request.get('method')
                request_id = request.get('id')
                if method == 'initialize':
                    response = {'jsonrpc': '2.0', 'id': request_id, 'result': {
                        'protocolVersion': '2025-03-26', 'capabilities': {},
                        'serverInfo': {'name': 'slow-test', 'version': '1.0'}}}
                    print(json.dumps(response), flush=True)
                elif method == 'tools/list':
                    print(json.dumps({'jsonrpc': '2.0', 'id': request_id, 'result': {'tools': []}}), flush=True)
                elif method == 'tools/call':
                    time.sleep(30)
            """
        )
        with tempfile.TemporaryDirectory() as directory:
            server = Path(directory) / "slow_tool_mcp.py"
            server.write_text(fake_server, encoding="utf-8")
            with MCPDataHub(
                enable_mutations=False,
                startup_timeout=2,
                tool_timeout=0.25,
                server_command=(sys.executable, [str(server)]),
            ) as client:
                started = time.monotonic()
                with self.assertRaisesRegex(TimeoutError, "tool 'get_lineage' did not respond"):
                    client._call("get_lineage", {})
                self.assertLess(time.monotonic() - started, 4.0)


if __name__ == "__main__":
    unittest.main()
