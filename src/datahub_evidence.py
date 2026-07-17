"""datahub_evidence.py — the agent's senses, now sourced through DataHub's MCP Server.

Every fact Lineage Detective reasons over is pulled from a live DataHub via the MCP tools
(`get_lineage`, `get_entities`) exposed by `datahub_mcp.MCPDataHub` — no metadata is invented.
This module turns raw MCP tool output into `NodeEvidence` the LLM can reason over.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

from datahub_mcp import MCPDataHub


@dataclass
class NodeEvidence:
    """Everything we could learn about one entity in the lineage graph."""
    urn: str
    name: str | None = None
    platform: str | None = None
    description: str | None = None
    owners: list[str] = field(default_factory=list)
    schema_fields: list[str] = field(default_factory=list)
    custom_properties: dict = field(default_factory=dict)
    hops_from_symptom: int = 0
    raw: Any = None

    def summary(self) -> str:
        own = ", ".join(self.owners) or self.custom_properties.get("owner") or "unknown"
        cols = f"{len(self.schema_fields)} cols" if self.schema_fields else "schema n/a"
        props = "  ".join(f"{k}={v}" for k, v in self.custom_properties.items() if k != "owner")
        return (f"[{self.hops_from_symptom} hop] {self.name or self.urn} "
                f"({self.platform or '?'}, {cols}, owner: {own})"
                + (f"\n    properties: {props}" if props else ""))


def _name_from_urn(urn: str) -> str:
    # urn:li:dataset:(urn:li:dataPlatform:bigquery,prod.raw.orders,PROD) -> prod.raw.orders
    inner = urn.rsplit("(", 1)[-1].rstrip(")")
    parts = inner.split(",")
    return parts[-2].strip() if len(parts) >= 2 else urn


def _ev_from_entity(e: dict, hops: int) -> NodeEvidence:
    """Build NodeEvidence from an MCP entity dict (as returned by get_entities/get_lineage).
    Every field guarded — DataHub only fills the aspects an asset actually has."""
    urn = e.get("urn", "")
    props = e.get("properties") or {}
    editable = e.get("editableProperties") or {}
    custom = {c.get("key"): c.get("value")
              for c in (props.get("customProperties") or []) if c.get("key")}
    owners = []
    for o in ((e.get("ownership") or {}).get("owners") or []):
        ou = (o.get("owner") or {}).get("urn") or o.get("ownerUrn")
        if ou:
            owners.append(str(ou))
    schema = e.get("schemaMetadata") or e.get("schema") or {}
    fields = [f.get("fieldPath") for f in (schema.get("fields") or []) if f.get("fieldPath")]
    return NodeEvidence(
        urn=str(urn),
        name=e.get("name") or props.get("name") or _name_from_urn(str(urn)),
        platform=(e.get("platform") or {}).get("name"),
        description=editable.get("description") or props.get("description"),
        owners=owners,
        schema_fields=fields,
        custom_properties=custom,
        hops_from_symptom=hops,
        raw=e,
    )


def _gather(client: MCPDataHub, start_urn: str, upstream: bool, max_hops: int,
            max_nodes: int) -> list[NodeEvidence]:
    """Walk lineage in one direction via the MCP get_lineage tool, then enrich every node with
    full metadata via get_entities (that's where the incident clues — custom properties — live)."""
    lineage = client.get_lineage(start_urn, upstream=upstream, max_hops=max_hops,
                                 max_results=max_nodes)
    urns = [start_urn] + [e.get("urn") for e in lineage if e.get("urn")]
    urns = list(dict.fromkeys(u for u in urns if u))[:max_nodes]
    entities = client.get_entities(urns)
    out: list[NodeEvidence] = []
    for i, u in enumerate(urns):
        e = entities.get(u) or {"urn": u}
        out.append(_ev_from_entity(e, 0 if i == 0 else 1))
    return out


def gather_upstream(client: MCPDataHub, start_urn: str, max_hops: int = 3,
                    max_nodes: int = 40) -> list[NodeEvidence]:
    """Walk UPSTREAM from the symptom — a broken metric's cause lives upstream."""
    return _gather(client, start_urn, upstream=True, max_hops=max_hops, max_nodes=max_nodes)


def gather_downstream(client: MCPDataHub, start_urn: str, max_hops: int = 5,
                      max_nodes: int = 60) -> list[NodeEvidence]:
    """Walk DOWNSTREAM from the root cause — everything it contaminated (the BLAST RADIUS)."""
    ev = _gather(client, start_urn, upstream=False, max_hops=max_hops, max_nodes=max_nodes)
    return [n for n in ev if str(n.urn) != str(start_urn)]  # exclude the root itself
