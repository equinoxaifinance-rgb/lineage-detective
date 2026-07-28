"""Regression checks for the DataHub/setuptools compatibility bridge.

They never install packages or start DataHub.  The live compatibility probe is
kept separate because its result depends on the release metadata available when
the judge runs it.
"""
from __future__ import annotations

import importlib.util
import io
import os
import subprocess
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
sys.path.insert(0, str(ROOT / "src"))
import datahub_mcp  # noqa: E402


class CompatibilityBridgeTests(unittest.TestCase):
    def test_quickstart_help_is_read_only_and_available_without_docker(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "quickstart.py"), "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("self-hosted quickstart", result.stdout)
        self.assertIn("Requires Docker Desktop", result.stdout)

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

    def test_release_path_refuses_execution_time_mcp_install(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(datahub_mcp.os.path, "exists", return_value=False),
            patch.object(datahub_mcp.shutil, "which", return_value="uvx"),
        ):
            with self.assertRaisesRegex(FileNotFoundError, "Run quickstart.py"):
                datahub_mcp._server_command()

    def test_unpinned_override_requires_explicit_development_opt_in(self):
        with (
            patch.dict(
                os.environ,
                {
                    "LINEAGE_ALLOW_UNPINNED_MCP": "1",
                    "DATAHUB_MCP_CMD": "custom-mcp --dev",
                },
                clear=True,
            ),
            patch.object(datahub_mcp.os.path, "exists", return_value=False),
        ):
            self.assertEqual(datahub_mcp._server_command(), ("custom-mcp", ["--dev"]))

    def test_arbitrary_selected_executable_is_rejected_without_opt_in(self):
        with (
            patch.dict(
                os.environ,
                {"DATAHUB_MCP_EXECUTABLE": r"C:\Windows\System32\cmd.exe"},
                clear=True,
            ),
            patch.object(datahub_mcp.os.path, "isfile", return_value=True),
            patch.object(datahub_mcp.os.path, "islink", return_value=False),
        ):
            with self.assertRaisesRegex(PermissionError, "outside the hash-locked"):
                datahub_mcp._server_command()

    def test_public_container_accepts_only_its_root_owned_hash_locked_sidecar(self):
        packaged = "/opt/datahub-sidecar/bin/mcp-server-datahub"
        with (
            patch.dict(
                os.environ,
                {
                    "LINEAGE_RUN_MODE": "public_judge",
                    "LINEAGE_BUNDLED_DATAHUB": "1",
                    "DATAHUB_MCP_EXECUTABLE": packaged,
                },
                clear=True,
            ),
            patch.object(datahub_mcp.os.path, "isfile", return_value=True),
            patch.object(datahub_mcp.os.path, "islink", return_value=False),
            patch.object(datahub_mcp.os.path, "realpath", side_effect=lambda value: value),
        ):
            self.assertEqual(datahub_mcp._server_command(), (packaged, []))

    def test_packaged_sidecar_path_stays_rejected_without_public_bundle_flag(self):
        packaged = "/opt/datahub-sidecar/bin/mcp-server-datahub"
        with (
            patch.dict(
                os.environ,
                {
                    "LINEAGE_RUN_MODE": "public_judge",
                    "DATAHUB_MCP_EXECUTABLE": packaged,
                },
                clear=True,
            ),
            patch.object(datahub_mcp.os.path, "isfile", return_value=True),
            patch.object(datahub_mcp.os.path, "islink", return_value=False),
            patch.object(datahub_mcp.os.path, "realpath", side_effect=lambda value: value),
        ):
            with self.assertRaisesRegex(PermissionError, "outside the hash-locked"):
                datahub_mcp._server_command()

    def test_selected_executable_on_another_drive_is_rejected(self):
        with (
            patch.dict(
                os.environ,
                {"DATAHUB_MCP_EXECUTABLE": r"D:\tools\mcp-server-datahub.exe"},
                clear=True,
            ),
            patch.object(datahub_mcp.os.path, "isfile", return_value=True),
            patch.object(datahub_mcp.os.path, "islink", return_value=False),
            patch.object(datahub_mcp.os.path, "commonpath", side_effect=ValueError),
        ):
            with self.assertRaisesRegex(PermissionError, "outside the hash-locked"):
                datahub_mcp._server_command()

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
