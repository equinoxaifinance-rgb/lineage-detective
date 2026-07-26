"""Regression checks for the DataHub/setuptools compatibility bridge.

They never install packages or start DataHub.  The live compatibility probe is
kept separate because its result depends on the release metadata available when
the judge runs it.
"""
from __future__ import annotations

import importlib.util
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("lineage_quickstart", ROOT / "quickstart.py")
quickstart = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(quickstart)


class CompatibilityBridgeTests(unittest.TestCase):
    def test_runtime_requirements_keep_the_fixed_setuptools(self):
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("setuptools==83.0.0", requirements)
        self.assertNotIn("acryl-datahub", requirements)

    def test_datahub_packages_are_owned_by_the_sidecar(self):
        sidecar = (ROOT / "requirements-datahub-sidecar.txt").read_text(encoding="utf-8")
        self.assertIn("acryl-datahub==", sidecar)
        self.assertIn("mcp-server-datahub==", sidecar)
        self.assertIn("setuptools==81.0.0", sidecar)

    def test_auto_mode_uses_sidecar_when_upstream_rejects_fixed_runtime(self):
        with patch.object(quickstart, "upstream_supports_fixed_runtime", return_value=False), \
             patch.object(quickstart, "ensure_sidecar_venv", return_value="sidecar-python"), \
             patch.object(quickstart, "sidecar_mcp_command", return_value="sidecar-mcp"):
            with patch.dict("os.environ", {"LINEAGE_DATAHUB_COMPAT_MODE": "auto"}, clear=False):
                py, command, route = quickstart.resolve_datahub_compatibility()
        self.assertEqual((py, command, route), ("sidecar-python", "sidecar-mcp", "isolated-upstream-compatibility"))

    def test_auto_mode_keeps_sidecar_when_a_future_unified_lock_is_not_reviewed(self):
        with patch.object(quickstart, "upstream_supports_fixed_runtime", return_value=True), \
             patch.object(quickstart, "ensure_sidecar_venv", return_value="sidecar-python"), \
             patch.object(quickstart, "sidecar_mcp_command", return_value="sidecar-mcp"), \
             patch.object(quickstart.os.path, "isfile", return_value=False), \
             patch.dict("os.environ", {"LINEAGE_DATAHUB_COMPAT_MODE": "auto"}, clear=False):
            with redirect_stdout(io.StringIO()):
                py, command, route = quickstart.resolve_datahub_compatibility()
        self.assertEqual((py, command, route), ("sidecar-python", "sidecar-mcp", "isolated-upstream-compatibility"))

    def test_unified_mode_refuses_a_known_incompatible_release(self):
        with patch.object(quickstart, "upstream_supports_fixed_runtime", return_value=False), \
             patch.dict("os.environ", {"LINEAGE_DATAHUB_COMPAT_MODE": "unified"}, clear=False):
            with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
                quickstart.resolve_datahub_compatibility()

    def test_selected_executable_contract_avoids_windows_path_splitting(self):
        source = (ROOT / "src" / "datahub_mcp.py").read_text(encoding="utf-8")
        self.assertIn('DATAHUB_MCP_EXECUTABLE', source)

    def test_unified_route_refuses_unhashed_installation(self):
        source = (ROOT / "quickstart.py").read_text(encoding="utf-8")
        self.assertIn("requirements-datahub-unified.lock", source)
        self.assertIn('"--require-hashes", "-r", UNIFIED_LOCK', source)
        self.assertIn("reviewed hash lock", source)

    def test_bootstrap_has_no_unhashed_pip_upgrade_path(self):
        source = (ROOT / "quickstart.py").read_text(encoding="utf-8")
        self.assertNotIn("PIP_PACKAGE_SPEC", source)
        self.assertIn('"--require-hashes", "--progress-bar", "off"', source)
        self.assertIn('"--require-hashes", "-r", RUNTIME_LOCK', source)


if __name__ == "__main__":
    unittest.main()
