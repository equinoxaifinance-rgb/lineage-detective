"""graph_viz.py — turn the lineage the agent actually walked into a Graphviz picture.

Given the affected asset and the finished report, we re-walk DataHub lineage (via the same MCP
`get_lineage` tool) to recover the real edges, then emit a DOT graph with the root cause and the
downstream blast radius lit up. Pure visualization: it never touches the investigation, and any
failure here is swallowed so the agent's result is unaffected.
"""
from __future__ import annotations
import re

from datahub_mcp import MCPDataHub


def _short(urn: str) -> str:
    inner = urn.rsplit("(", 1)[-1].rstrip(")")
    parts = inner.split(",")
    return parts[-2].strip() if len(parts) >= 2 else urn


def _platform(urn: str) -> str:
    m = re.search(r"dataPlatform:([^,]+)", urn)
    return m.group(1) if m else ""


def _walk_edges(client: MCPDataHub, start: str, upstream: bool, max_hops: int,
                max_nodes: int = 40):
    """Bounded BFS that records real lineage edges in one direction."""
    seen = {start}
    nodes = {start}
    edges: set[tuple[str, str]] = set()
    frontier = [(start, 0)]
    while frontier and len(nodes) < max_nodes:
        urn, depth = frontier.pop(0)
        if depth >= max_hops:
            continue
        try:
            neigh = client.get_lineage(urn, upstream=upstream, max_hops=1, max_results=50)
        except Exception:
            neigh = []
        for n in neigh:
            nu = n.get("urn")
            if not nu:
                continue
            edges.add((nu, urn) if upstream else (urn, nu))
            nodes.add(nu)
            if nu not in seen:
                seen.add(nu)
                frontier.append((nu, depth + 1))
    return nodes, edges


def lineage_dot(client: MCPDataHub, affected_urn: str, report: dict,
                max_hops: int = 3) -> str | None:
    """Build a Graphviz DOT string of the investigated lineage, root cause + blast radius lit up."""
    try:
        up_nodes, up_edges = _walk_edges(client, affected_urn, upstream=True, max_hops=max_hops)
        root = ((report.get("action") or {}).get("urn")
                or ((report.get("suspects") or [{}])[0] or {}).get("urn"))
        down_nodes, down_edges = (set(), set())
        if root:
            down_nodes, down_edges = _walk_edges(client, root, upstream=False, max_hops=6)
        nodes = up_nodes | down_nodes
        edges = up_edges | down_edges
        if not nodes:
            return None
        impacted = {n for n in down_nodes if n != root} if root else set()

        def node_line(urn: str) -> str:
            name = _short(urn)
            plat = _platform(urn)
            label = f"{name}\\n({plat})" if plat else name
            if urn == root:
                return (f'"{urn}" [label="{label}\\n🔒 QUARANTINE", style="filled,bold", '
                        f'fillcolor="#7f1d1d", fontcolor="#fee2e2", color="#ef4444", penwidth=2];')
            if urn == affected_urn:
                return (f'"{urn}" [label="{label}\\n⚠ symptom", style="filled", '
                        f'fillcolor="#1e3a8a", fontcolor="#dbeafe", color="#60a5fa", penwidth=2];')
            if urn in impacted:
                return (f'"{urn}" [label="{label}\\nIMPACTED", style="filled", '
                        f'fillcolor="#78350f", fontcolor="#fef3c7", color="#f59e0b"];')
            return f'"{urn}" [label="{label}", style="filled", fillcolor="#1f2937", fontcolor="#e5e7eb", color="#374151"];'

        lines = ['digraph lineage {', '  rankdir=LR; bgcolor="transparent";',
                 '  node [shape=box, style=filled, fontname="Segoe UI", fontsize=11, margin="0.15,0.08"];',
                 '  edge [color="#6b7280", arrowsize=0.8];']
        for u in nodes:
            lines.append("  " + node_line(u))
        for a, b in edges:
            if a in nodes and b in nodes:
                lines.append(f'  "{a}" -> "{b}";')
        lines.append("}")
        return "\n".join(lines)
    except Exception:
        return None
