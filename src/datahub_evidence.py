"""datahub_evidence.py — the agent's senses.

Pulls the evidence Lineage Detective reasons over, straight from a live DataHub instance,
using the real acryl-datahub SDK (verified against v1.6.0.13):
  - client.lineage.get_lineage(source_urn=..., direction='upstream'|'downstream', max_hops, count)
  - client.entities.get(urn) -> Entity  (schema, ownership, description, ...)

No metadata is invented — every fact the agent uses comes from DataHub here.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

from datahub.sdk import DataHubClient


def make_client(server: str, token: str | None = None) -> DataHubClient:
    """Connect to a DataHub GMS server (e.g. http://localhost:8080)."""
    return DataHubClient(server=server, token=token)


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


def _safe(fn, default=None):
    """DataHub SDK Entity properties RAISE when an aspect is unset (e.g. `.schema` throws
    'Schema is not set'). So every field access must be isolated — one unset aspect must not
    wipe out the fields we did read."""
    try:
        return fn()
    except Exception:
        return default


def _name_from_urn(urn: str) -> str:
    # urn:li:dataset:(urn:li:dataPlatform:bigquery,prod.raw.orders,PROD) -> prod.raw.orders
    inner = urn.rsplit("(", 1)[-1].rstrip(")")
    parts = inner.split(",")
    return parts[-2].strip() if len(parts) >= 2 else urn


def _entity_facts(client: DataHubClient, urn: str, hops: int) -> NodeEvidence:
    """Fetch one entity's metadata into NodeEvidence — every field guarded independently, because
    Entity properties raise on unset aspects. Whatever DataHub exposes we capture; nothing invented."""
    ev = NodeEvidence(urn=str(urn), hops_from_symptom=hops)
    e = _safe(lambda: client.entities.get(urn))
    if e is None:
        ev.description = "(entity not found in DataHub)"
        return ev
    ev.raw = e
    ev.name = _safe(lambda: e.display_name) or _safe(lambda: e.qualified_name) or _name_from_urn(str(urn))
    ev.name = str(ev.name) if ev.name else None
    ev.platform = _safe(lambda: str(e.platform))
    ev.description = _safe(lambda: e.description)
    ev.custom_properties = _safe(lambda: dict(e.custom_properties)) or {}
    owners = _safe(lambda: list(e.owners)) or []
    ev.owners = [str(_safe(lambda o=o: o.owner_urn, o)) for o in owners]
    fields = _safe(lambda: list(e.schema.fields)) or []
    ev.schema_fields = [str(_safe(lambda f=f: f.field_path, f)) for f in fields]
    return ev


def _walk(client: DataHubClient, start_urn: str, direction: str, max_hops: int,
          max_nodes: int) -> list[NodeEvidence]:
    """BFS the lineage graph in one direction, collecting evidence at each node."""
    seen: set[str] = {str(start_urn)}
    out: list[NodeEvidence] = [_entity_facts(client, start_urn, 0)]
    frontier = [(str(start_urn), 0)]
    while frontier and len(out) < max_nodes:
        urn, depth = frontier.pop(0)
        if depth >= max_hops:
            continue
        try:
            results = client.lineage.get_lineage(source_urn=urn, direction=direction,
                                                 max_hops=1, count=500)
        except Exception:
            results = []
        for r in results:
            nxt = str(getattr(r, "urn", None) or getattr(r, "source_urn", "") or r)
            if not nxt or nxt in seen:
                continue
            seen.add(nxt)
            out.append(_entity_facts(client, nxt, depth + 1))
            frontier.append((nxt, depth + 1))
            if len(out) >= max_nodes:
                break
    return out


def gather_upstream(client: DataHubClient, start_urn: str, max_hops: int = 3,
                    max_nodes: int = 40) -> list[NodeEvidence]:
    """Walk UPSTREAM from the symptom — a broken metric's cause lives upstream."""
    return _walk(client, start_urn, "upstream", max_hops, max_nodes)


def gather_downstream(client: DataHubClient, start_urn: str, max_hops: int = 5,
                      max_nodes: int = 60) -> list[NodeEvidence]:
    """Walk DOWNSTREAM from the root cause — everything it contaminated (the BLAST RADIUS)."""
    return _walk(client, start_urn, "downstream", max_hops, max_nodes)
