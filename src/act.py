"""act.py — the agent's hands, now acting through DataHub's MCP Server.

Most 'agents' only read. Lineage Detective closes the loop: once it identifies a root cause it
ACTS in DataHub — via the MCP `add_tags` tool — so every downstream consumer is warned in the
catalog they already use. Read -> reason -> WRITE, all through the DataHub MCP Server, and every
write is read back to prove it persisted.
"""
from __future__ import annotations

from datahub_mcp import MCPDataHub
from datahub_evidence import gather_downstream

QUARANTINE_TAG = "urn:li:tag:QUARANTINE_INCIDENT"
IMPACT_TAG = "urn:li:tag:IMPACTED_BY_INCIDENT"


def quarantine_node(client: MCPDataHub, urn: str, note: str | None = None) -> dict:
    """Tag the root-cause dataset as quarantined via the MCP add_tags tool; the client reads it
    back to confirm it stuck (we never claim a write we didn't verify)."""
    applied = client.add_tag(urn, QUARANTINE_TAG)
    return {"urn": str(urn), "tag": QUARANTINE_TAG, "applied": applied,
            "note": note, "downstream_warned": applied}


def map_and_contain_blast_radius(client: MCPDataHub, root_urn: str) -> dict:
    """From the root cause, walk lineage DOWNSTREAM (via MCP get_lineage) to find every
    contaminated asset (the blast radius), tag each 'IMPACTED_BY_INCIDENT' via MCP add_tags, and
    return the damage map. Find -> contain -> map the full blast zone, autonomously, in the catalog."""
    impacted = gather_downstream(client, root_urn)
    assets, dashboards, tagged = [], [], 0
    for n in impacted:
        label = n.name or n.urn
        is_dash = bool(n.platform and ("looker" in n.platform or "dashboard" in n.platform))
        (dashboards if is_dash else assets).append(label)
        if client.add_tag(n.urn, IMPACT_TAG):
            tagged += 1
    return {"impacted_count": len(impacted), "tagged": tagged,
            "assets": assets, "dashboards": dashboards}
