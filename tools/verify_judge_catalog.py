"""Read-only release probe for the dedicated Lineage Detective judge catalog."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from datahub_mcp import MCPDataHub  # noqa: E402


def urn(platform: str, name: str) -> str:
    return f"urn:li:dataset:(urn:li:dataPlatform:{platform},{name},PROD)"


CHAINS = (
    (
        urn("bigquery", "prod.raw.orders"),
        urn("dbt", "analytics.staging.stg_orders"),
        urn("dbt", "analytics.marts.fct_revenue"),
        urn("looker", "bi.revenue_overview"),
    ),
    (
        urn("s3", "prod.crm_exports.customers_v2"),
        urn("bigquery", "prod.landing.crm_customers"),
        urn("dbt", "analytics.bronze.crm_customers"),
        urn("bigquery", "prod.raw.customers"),
        urn("dbt", "analytics.staging.stg_customers"),
        urn("dbt", "analytics.marts.dim_customers"),
        urn("looker", "bi.customer_360"),
    ),
    (
        urn("bigquery", "prod.ref.exchange_rates"),
        urn("dbt", "analytics.marts.fct_revenue_usd"),
        urn("looker", "bi.finance_fx"),
    ),
)
REQUIRED_TOOLS = {
    "search",
    "get_lineage",
    "get_entities",
    "add_tags",
    "remove_tags",
}
PROBE_URN = urn("datahub", "lineage_detective.release_probe")
PROBE_TAG = "urn:li:tag:QUARANTINE_INCIDENT"


def main() -> int:
    server = os.environ.get("DATAHUB_SERVER", "").strip()
    mcp_url = os.environ.get("DATAHUB_MCP_URL", "").strip()
    token = os.environ.get("DATAHUB_GMS_TOKEN", "").strip()
    if not server:
        raise SystemExit("DATAHUB_SERVER is required.")
    try:
        startup_timeout = float(
            os.environ.get("LINEAGE_RELEASE_MCP_STARTUP_TIMEOUT", "180")
        )
        tool_timeout = float(
            os.environ.get("LINEAGE_RELEASE_MCP_TOOL_TIMEOUT", "45")
        )
    except ValueError as exc:
        raise SystemExit("Release MCP timeouts must be numeric.") from exc
    if not 30 <= startup_timeout <= 300:
        raise SystemExit(
            "LINEAGE_RELEASE_MCP_STARTUP_TIMEOUT must be between 30 and 300 seconds."
        )
    if not 15 <= tool_timeout <= 120:
        raise SystemExit(
            "LINEAGE_RELEASE_MCP_TOOL_TIMEOUT must be between 15 and 120 seconds."
        )
    all_urns = [value for chain in CHAINS for value in chain]
    with MCPDataHub(
        server,
        token=token,
        mcp_url=mcp_url or None,
        enable_mutations=True,
        startup_timeout=startup_timeout,
        tool_timeout=tool_timeout,
    ) as catalog:
        search_results = catalog.search("revenue", num_results=5)
        entities = catalog.get_entities(all_urns + [PROBE_URN])
        missing_entities = sorted(set(all_urns) - set(entities))
        lineage_failures: list[dict[str, object]] = []
        for chain in CHAINS:
            affected = chain[-1]
            upstream = {
                str(row.get("urn"))
                for row in catalog.get_lineage(affected, upstream=True, max_hops=6)
                if row.get("urn")
            }
            missing_upstream = sorted(set(chain[:-1]) - upstream)
            if missing_upstream:
                lineage_failures.append({
                    "affected_urn": affected,
                    "missing_upstream": missing_upstream,
                })
        mutation = {
            "attempted": PROBE_URN in entities,
            "add_readback": False,
            "remove_readback": False,
        }
        if mutation["attempted"]:
            mutation["add_readback"] = catalog.add_tag(PROBE_URN, PROBE_TAG)
            mutation["remove_readback"] = catalog.remove_tag(PROBE_URN, PROBE_TAG)
        mutation_verified = all(mutation.values())
        missing_tools = sorted(REQUIRED_TOOLS - catalog.tools)
    receipt = {
        "state": "judge_catalog_verified" if not (
            missing_tools or missing_entities or lineage_failures or not mutation_verified
        ) else "judge_catalog_failed",
        "verified": not (
            missing_tools or missing_entities or lineage_failures or not mutation_verified
        ),
        "entity_count_expected": len(all_urns),
        "entity_count_read_back": len(entities),
        "chain_count_expected": len(CHAINS),
        "longest_chain_edges": max(len(chain) - 1 for chain in CHAINS),
        "search_result_count": len(search_results),
        "missing_tools": missing_tools,
        "missing_entities": missing_entities,
        "lineage_failures": lineage_failures,
        "reversible_mcp_mutation": mutation,
        "transport": "remote_http" if mcp_url else "official_stdio",
        "authentication": "bearer" if token else "private_internal_gms",
        "server_sha256": hashlib.sha256(server.encode("utf-8")).hexdigest(),
        "mcp_url_sha256": (
            hashlib.sha256(mcp_url.encode("utf-8")).hexdigest()
            if mcp_url
            else None
        ),
    }
    receipt["receipt_sha256"] = hashlib.sha256(
        json.dumps(receipt, sort_keys=True).encode("utf-8")
    ).hexdigest()
    print(json.dumps(receipt, indent=2, sort_keys=True))
    if not receipt["verified"]:
        # The container keeps stdout as the durable receipt. Emit one bounded,
        # secret-free failure line to stderr as well so authenticated platform
        # logs identify the exact failed proof instead of forcing blind retries.
        print(
            "LINEAGE_CATALOG_FAILURE_RECEIPT="
            + json.dumps(receipt, sort_keys=True, separators=(",", ":")),
            file=sys.stderr,
        )
    if receipt["verified"]:
        return 0
    # DataHub writes are accepted before every search/lineage index and tag
    # readback is necessarily visible. During a brand-new catalog bootstrap,
    # those completed-but-not-yet-indexed states are retryable; a missing MCP
    # tool is a hard incompatibility and must still fail closed immediately.
    eventual_state_pending = bool(
        missing_entities
        or lineage_failures
        or not mutation_verified
        or not search_results
    )
    return 75 if eventual_state_pending and not missing_tools else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TimeoutError as exc:
        # EX_TEMPFAIL lets the container retry only a genuinely transient MCP
        # timeout. A completed-but-failed catalog receipt remains a hard stop.
        print(f"transient_timeout={exc}", file=sys.stderr)
        raise SystemExit(75) from exc
