"""Fail-closed runtime boundary for the public judge app and customer deployments."""
from __future__ import annotations

import os
from urllib.parse import urlsplit


PUBLIC_JUDGE = "public_judge"
SELF_HOSTED = "self_hosted"
_VALID_MODES = {PUBLIC_JUDGE, SELF_HOSTED}


def runtime_mode() -> str:
    """Return the explicit mode; absence is the least-privileged public mode."""
    mode = os.environ.get("LINEAGE_RUN_MODE", PUBLIC_JUDGE).strip().lower()
    if mode not in _VALID_MODES:
        raise RuntimeError(
            "LINEAGE_RUN_MODE must be 'public_judge' or 'self_hosted'; "
            "sensitive capabilities stay disabled."
        )
    return mode


def is_public_judge() -> bool:
    return runtime_mode() == PUBLIC_JUDGE


def is_self_hosted() -> bool:
    return runtime_mode() == SELF_HOSTED


def is_bundled_catalog_url(value: str) -> bool:
    """Allow only the server-owned loopback GMS used by the public container.

    Public mode otherwise rejects private-network URLs. This exception cannot be
    selected from the browser: the deployment must opt in through its server-side
    environment and the URL must be the exact bundled DataHub GMS origin.
    """
    if not is_public_judge() or os.environ.get("LINEAGE_BUNDLED_DATAHUB") != "1":
        return False
    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme == "http"
            and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
            and parsed.port == 8080
            and parsed.path in {"", "/"}
            and not parsed.username
            and not parsed.password
            and not parsed.query
            and not parsed.fragment
        )
    except (TypeError, ValueError):
        return False
