"""prove_writeback.py — causal proof that the agent WRITES to DataHub through the MCP Server.

1. Clean slate: remove the incident tags from the scenario-A chain (via MCP remove_tags).
2. Confirm they are gone (independent read).
3. Run the agent with act=True — it should quarantine the root cause and tag the blast radius.
4. Independently read the tags back and confirm they were freshly applied by the agent.
"""
import sys, os
sys.path.insert(0, "src")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from datahub_mcp import MCPDataHub
from agent import investigate

QUAR = "urn:li:tag:QUARANTINE_INCIDENT"
IMPACT = "urn:li:tag:IMPACTED_BY_INCIDENT"
ROOT = "urn:li:dataset:(urn:li:dataPlatform:bigquery,prod.raw.orders,PROD)"
CHAIN = [
    ROOT,
    "urn:li:dataset:(urn:li:dataPlatform:dbt,analytics.staging.stg_orders,PROD)",
    "urn:li:dataset:(urn:li:dataPlatform:dbt,analytics.marts.fct_revenue,PROD)",
    "urn:li:dataset:(urn:li:dataPlatform:looker,bi.revenue_overview,PROD)",
]
DASH = CHAIN[-1]


def tags_on(client, urn):
    e = client.get_entities([urn]).get(urn, {})
    return [t.get("tag", {}).get("urn") for t in ((e.get("tags") or {}).get("tags") or [])]


# ---- 1+2: clean slate ------------------------------------------------------------
with MCPDataHub() as c:
    for u in CHAIN:
        c._call("remove_tags", {"tag_urns": [QUAR, IMPACT], "entity_urns": [u]})
    before = {u: tags_on(c, u) for u in CHAIN}
print("BEFORE (after clearing):")
for u, t in before.items():
    print(f"  {u.rsplit(',',2)[-2]:24s} tags={t}")
assert not any(QUAR in t or IMPACT in t for t in before.values()), "clean slate failed"
print("  -> clean slate confirmed (no incident tags)\n")

# ---- 3: agent acts ---------------------------------------------------------------
rep = investigate(
    "The Revenue Overview dashboard shows a ~40% drop in daily revenue since yesterday, no pipeline errors.",
    DASH, server="http://localhost:8080", act=True)
act = rep.get("action", {})
br = rep.get("blast_radius", {})
print(f"AGENT ACTED: quarantined={act.get('urn','').rsplit(',',2)[-2] if act.get('urn') else None} "
      f"applied={act.get('applied')}  blast_radius tagged={br.get('tagged')}/{br.get('impacted_count')}\n")

# ---- 4: independent read-back ----------------------------------------------------
with MCPDataHub() as c:
    after = {u: tags_on(c, u) for u in CHAIN}
print("AFTER (independent read-back):")
for u, t in after.items():
    print(f"  {u.rsplit(',',2)[-2]:24s} tags={t}")

root_quar = QUAR in after[ROOT]
downstream_tagged = sum(1 for u in CHAIN[1:] if IMPACT in after[u])
print()
ok = root_quar and downstream_tagged >= 1 and act.get("applied")
print(f"WRITE-BACK PROVEN: root quarantined={root_quar}, downstream IMPACTED tagged={downstream_tagged} "
      f"-> {'PASS' if ok else 'FAIL'}")
sys.exit(0 if ok else 1)
