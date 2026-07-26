"""Provision incident tags through the isolated DataHub sidecar.

This is catalog setup, not agent behavior. The judge-facing app remains a clean
MCP client; the official DataHub SDK performs the one create-if-missing setup
inside `.datahub-mcp-venv` only.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

INCIDENT_VOCABULARY = (
    ("QUARANTINE_INCIDENT", "Root cause of a data incident — quarantined by Lineage Detective."),
    ("IMPACTED_BY_INCIDENT", "Downstream asset contaminated by an upstream incident."),
)

ROOT = Path(__file__).resolve().parents[1]
SIDECAR_SCRIPT = ROOT / "tools" / "setup_vocab_sidecar.py"


def _sidecar_python() -> str:
    override = os.environ.get("DATAHUB_BOOTSTRAP_PYTHON")
    if override:
        return override
    return str(ROOT / ".datahub-mcp-venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))


def ensure_incident_vocabulary(server: str, token: str | None = None) -> list[str]:
    """Create the two tag entities via the isolated official-SDK sidecar.

    Raises a concrete setup error when quickstart has not provisioned the
    sidecar, rather than silently falling back to an unpinned global install.
    """
    python = _sidecar_python()
    if not os.path.exists(python):
        raise RuntimeError("DataHub sidecar is missing; run `python quickstart.py` first.")
    env = dict(os.environ)
    env["DATAHUB_GMS_URL"] = server
    if token:
        env["DATAHUB_GMS_TOKEN"] = token
    result = subprocess.run([python, str(SIDECAR_SCRIPT)], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=45)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown sidecar error").strip()
        raise RuntimeError(f"DataHub tag setup failed: {detail}")
    return [name for name, _ in INCIDENT_VOCABULARY]
