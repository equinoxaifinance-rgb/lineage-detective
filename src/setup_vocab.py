"""setup_vocab.py — catalog SETUP (not the agent): ensure the incident-tag vocabulary exists.

The official DataHub MCP `add_tags` tool validates that a tag entity EXISTS before attaching it
(unlike the raw SDK, which auto-creates). On our demo instance `seed_demo.py` creates the two
incident tags; on YOUR OWN DataHub they wouldn't exist yet — so the app ensures them at startup,
idempotently (create-if-missing; harmless if present).

This lives in the setup layer on purpose: the AGENT still drives DataHub entirely through the
official MCP Server (`get_lineage` / `get_entities` / `add_tags`). Setting the table is not
playing the meal.
"""
from datahub.sdk import DataHubClient, Tag

INCIDENT_VOCABULARY = (
    ("QUARANTINE_INCIDENT", "Root cause of a data incident — quarantined by Lineage Detective."),
    ("IMPACTED_BY_INCIDENT", "Downstream asset contaminated by an upstream incident."),
)


def ensure_incident_vocabulary(server: str, token: str | None = None) -> list[str]:
    """Idempotently create the incident tags on `server`. Returns the tag names ensured.
    Raises on connection failure — callers decide whether that is fatal (the investigation
    itself does not need the tags; only the act step does)."""
    c = DataHubClient(server=server, token=token) if token else DataHubClient(server=server)
    for name, desc in INCIDENT_VOCABULARY:
        c.entities.upsert(Tag(name=name, description=desc))
    return [name for name, _ in INCIDENT_VOCABULARY]
