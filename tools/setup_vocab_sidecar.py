"""Official-SDK-only sidecar for idempotent DataHub incident-tag provisioning."""
from __future__ import annotations

import os

from datahub.sdk import DataHubClient, Tag

VOCABULARY = (
    ("QUARANTINE_INCIDENT", "Root cause of a data incident — quarantined by Lineage Detective."),
    ("IMPACTED_BY_INCIDENT", "Downstream asset contaminated by an upstream incident."),
)


def main() -> int:
    server = os.environ.get("DATAHUB_GMS_URL", "http://localhost:8080")
    token = os.environ.get("DATAHUB_GMS_TOKEN")
    client = DataHubClient(server=server, token=token) if token else DataHubClient(server=server)
    for name, description in VOCABULARY:
        client.entities.upsert(Tag(name=name, description=description))
    print("ENSURED " + ", ".join(name for name, _ in VOCABULARY))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
