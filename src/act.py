"""act.py — the agent's hands.

Most 'agents' only read. Lineage Detective closes the loop: once it identifies a root cause it
ACTS in DataHub — tags the offending node so every downstream consumer is warned in the catalog
they already use. Read -> reason -> WRITE. Verified against a live DataHub instance.
"""
from __future__ import annotations
from datahub.sdk import DataHubClient

from datahub_evidence import gather_downstream

QUARANTINE_TAG = "urn:li:tag:QUARANTINE_INCIDENT"
IMPACT_TAG = "urn:li:tag:IMPACTED_BY_INCIDENT"


def quarantine_node(client: DataHubClient, urn: str, note: str | None = None) -> dict:
    """Tag the root-cause dataset as quarantined, then read it back to PROVE it persisted."""
    ds = client.entities.get(urn)
    ds.add_tag(QUARANTINE_TAG)
    client.entities.update(ds)
    # read back — never claim we wrote something without confirming it stuck
    check = client.entities.get(urn)
    tags = [str(t) for t in (getattr(check, "tags", None) or [])]
    applied = any("QUARANTINE" in t for t in tags)
    return {"urn": str(urn), "tag": QUARANTINE_TAG, "applied": applied,
            "note": note, "downstream_warned": applied}


def map_and_contain_blast_radius(client: DataHubClient, root_urn: str) -> dict:
    """The flourish: from the root cause, walk lineage DOWNSTREAM to find every contaminated
    asset (the blast radius), tag each 'IMPACTED_BY_INCIDENT', and return the damage map.
    Find -> contain -> map the full blast zone, autonomously, in the catalog."""
    downstream = gather_downstream(client, root_urn)
    impacted = [n for n in downstream if str(n.urn) != str(root_urn)]
    assets, dashboards, tagged = [], [], 0
    for n in impacted:
        label = n.name or n.urn
        (dashboards if (n.platform and ("looker" in n.platform or "dashboard" in (n.platform or "")))
         else assets).append(label)
        try:
            ds = client.entities.get(n.urn)
            ds.add_tag(IMPACT_TAG)
            client.entities.update(ds)
            tagged += 1
        except Exception:
            pass
    return {"impacted_count": len(impacted), "tagged": tagged,
            "assets": assets, "dashboards": dashboards}
