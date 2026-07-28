"""Provision the incident-tag vocabulary and verify it by readback.

Local quickstart uses the isolated official-SDK sidecar. Hosted DataHub Cloud
deployments use the tenant's GraphQL API because there is no local SDK process
inside that runtime. Both paths create the same tags and read them back before
returning success.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import json
from urllib.request import HTTPRedirectHandler, Request, build_opener

try:
    from .network_policy import validate_network_url, validate_resolution
    from .runtime_mode import is_bundled_catalog_url, is_self_hosted
except ImportError:
    from network_policy import validate_network_url, validate_resolution
    from runtime_mode import is_bundled_catalog_url, is_self_hosted

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
    """Create and read back the two tag entities through the available route."""
    allow_private = is_self_hosted() or is_bundled_catalog_url(server)
    server = validate_network_url(
        server,
        allow_private=allow_private,
        label="DataHub server URL",
    )
    python = _sidecar_python()
    if not os.path.exists(python):
        return _ensure_via_graphql(server, token)
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


def _graphql(server: str, token: str | None, query: str, variables: dict) -> dict:
    allow_private = is_self_hosted() or is_bundled_catalog_url(server)
    validate_resolution(
        server,
        allow_private=allow_private,
        label="DataHub server URL",
    )
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(
        f"{server.rstrip('/')}/api/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    class _RejectRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise RuntimeError(f"DataHub GraphQL returned an unexpected redirect to {newurl}")

    with build_opener(_RejectRedirect).open(request, timeout=20) as response:
        return json.loads(response.read() or b"{}")


def _ensure_via_graphql(server: str, token: str | None) -> list[str]:
    """Container/Cloud fallback: create and read back the two tags without the SDK sidecar."""
    query = "query TagByUrn($urn: String!) { tag(urn: $urn) { urn } }"
    create = """
    mutation CreateTag($input: CreateTagInput!) {
      createTag(input: $input)
    }
    """
    created: list[str] = []
    for name, description in INCIDENT_VOCABULARY:
        urn = f"urn:li:tag:{name}"
        before = _graphql(server, token, query, {"urn": urn})
        existing = ((before.get("data") or {}).get("tag") or {}).get("urn")
        if not existing:
            result = _graphql(
                server, token, create,
                {"input": {"name": name, "id": name, "description": description}},
            )
            if (result.get("data") or {}).get("createTag") != urn:
                raise RuntimeError(f"DataHub did not confirm creation of {urn}: {result.get('errors')}")
        after = _graphql(server, token, query, {"urn": urn})
        if ((after.get("data") or {}).get("tag") or {}).get("urn") != urn:
            raise RuntimeError(f"DataHub did not read back {urn} after setup")
        created.append(name)
    return created
