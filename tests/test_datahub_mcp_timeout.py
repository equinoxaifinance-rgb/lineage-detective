"""Failure-path tests for the official DataHub MCP connection."""
from __future__ import annotations

import sys
import tempfile
import time
import unittest
import textwrap
from pathlib import Path

from src.datahub_mcp import MCPDataHub


class McpStartupTimeoutTests(unittest.TestCase):
    def test_nonresponsive_server_fails_with_a_bounded_recoverable_error(self):
        """A child that never answers initialize must not leave a judge at Connecting."""
        with tempfile.TemporaryDirectory() as directory:
            sleeper = Path(directory) / "nonresponsive_mcp.py"
            sleeper.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
            started = time.monotonic()
            with self.assertRaisesRegex(TimeoutError, "did not initialize"):
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
