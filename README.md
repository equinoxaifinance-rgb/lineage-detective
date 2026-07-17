# 🕵️ Lineage Detective — Autonomous Data-Incident Root-Cause Agent

**Built with [DataHub](https://datahub.com) — driven through the DataHub **MCP Server** — for the
Build with DataHub: The Agent Hackathon.**

When a dashboard number looks wrong, a data team's first hour is spent *manually* clicking through
lineage asking "where did this break?" Lineage Detective does that investigation autonomously.

Give it a plain-English symptom and the affected asset. It walks **upstream through DataHub's
lineage graph**, reads the real metadata at every hop (descriptions, custom properties, ownership,
schema), reasons over the evidence like an on-call engineer, returns a **ranked root-cause report
with the owner to contact**, and then **acts** — quarantining the root cause and tagging the whole
blast radius in the catalog — all **through DataHub's MCP Server**.

> **It never invents metadata.** Every fact in a report comes from DataHub (via MCP tools); the LLM
> only *reasons* over real evidence and is instructed to say when the evidence is insufficient
> rather than bluff.

---

## It's a DataHub *agent*: everything goes through the MCP Server

The DataHub **MCP Server** (`mcp-server-datahub`) is DataHub's agent-facing surface. Lineage
Detective launches it and speaks MCP over stdio — it does not touch the catalog any other way:

| Step | MCP tool used | What it does |
|------|---------------|--------------|
| Sense (upstream) | `get_lineage` (`upstream=true`) | walk the lineage graph up from the symptom |
| Sense (detail)   | `get_entities` | pull owner / description / custom properties at each node |
| **Reason**       | *(frontier LLM)* | rank root-cause suspects over ONLY that evidence |
| Act (contain)    | `add_tags` | quarantine the root-cause node so consumers are warned |
| Map blast radius | `get_lineage` (`upstream=false`) + `add_tags` | find & tag every contaminated downstream asset |

Every write is **read back** (`get_entities`) to prove it persisted — the agent never claims an
action it can't confirm in the catalog.

## It works — verified live across three distinct incidents

Against a real DataHub instance, the agent correctly root-causes three *materially different*
failure types — a silent partial load, a schema-drift column rename, and a stale upstream feed —
each with the right owner to contact, then contains each in the catalog:

```
====================================================================
  LINEAGE DETECTIVE — Autonomous Data-Incident Report
====================================================================
Symptom  : Revenue Overview dashboard shows a ~40% drop in daily revenue, no pipeline errors.
Traced   : 4 upstream entities via DataHub lineage (MCP get_lineage)

SUMMARY
  The 40% revenue drop matches an ingestion anomaly at the raw orders source: prod.raw.orders
  logged ~40% fewer rows than the 7-day average due to a suspected upstream API partial outage,
  with no backfill run yet. stg_orders is a 1:1 passthrough and fct_revenue a simple sum with no
  volume tests, so the shortfall passed silently through dbt into the dashboard.

ROOT-CAUSE SUSPECTS (ranked)
  1. [!!!] [HIGH] prod.raw.orders   → contact: alice@data-eng
       why : last_run_note reports ~40% fewer rows than the 7-day avg at 2026-07-11 02:00 UTC,
              matching the magnitude and timing of the drop; backfill not yet run.
       next: Check the Orders API incident log, confirm row counts, trigger the backfill.

ACTION TAKEN (autonomous write-back to DataHub, via MCP add_tags)
  [OK] APPLIED: tagged prod.raw.orders 'QUARANTINE_INCIDENT' — downstream consumers now warned.

BLAST RADIUS — 3 downstream assets contaminated (3 tagged IMPACTED)
  dashboards affected: bi.revenue_overview
  data assets affected: analytics.staging.stg_orders, analytics.marts.fct_revenue
====================================================================
```

Reproduce the proofs yourself: `python prove_scenarios.py` (3/3 root-caused) and
`python tools/prove_writeback.py` (clean-slate → agent acts → independent read-back confirms the
tags were written through MCP).

## Code map

- **`src/datahub_mcp.py`** — the MCP connection. Launches `mcp-server-datahub`, holds one MCP
  session open on a dedicated worker thread, and exposes `get_lineage` / `get_entities` / `add_tag`.
- **`src/datahub_evidence.py`** — the agent's senses. Turns MCP `get_lineage` + `get_entities`
  output into the evidence the LLM reasons over. No metadata invented.
- **`src/act.py`** — the agent's hands. Quarantines the root cause and tags the blast radius via
  the MCP `add_tags` tool, reading each write back to confirm it stuck.
- **`src/agent.py`** — the investigator. `investigate(symptom, affected_urn, act=True)` → gather
  evidence (MCP) → LLM reasoning → strict-JSON report → contain (MCP) → `render_report()`.

## DataHub features used
DataHub **MCP Server** (`get_lineage`, `get_entities`, `add_tags`) · bidirectional lineage
traversal · entity metadata (ownership, description, custom properties, schema) · catalog
write-back (tags). *(Roadmap: data-quality **assertions** as first-class smoking-gun evidence.)*

## Quickstart
```bash
pip install -r requirements.txt
# install uv (runs the DataHub MCP server): https://docs.astral.sh/uv/
datahub docker quickstart                 # stand up DataHub locally (GMS :8080, UI :9002)
python seed_demo.py                        # plant the demo incidents + tags (prints the URNs)
export ANTHROPIC_API_KEY=...               # the reasoning model
export DATAHUB_GMS_URL=http://localhost:8080
python src/agent.py "the revenue dashboard dropped 40%, no errors" \
  "urn:li:dataset:(urn:li:dataPlatform:looker,bi.revenue_overview,PROD)" --act
```
The agent auto-launches the DataHub MCP server (`uvx mcp-server-datahub@latest`); set
`DATAHUB_MCP_CMD` to override how it's launched. On DataHub Cloud, point `DATAHUB_GMS_URL` /
`DATAHUB_GMS_TOKEN` at your tenant instead.

## Why it's original
Not a data catalog, not a chatbot over docs — an **autonomous investigator** that drives DataHub's
own MCP tools to turn lineage + metadata into *answered, contained* incidents. Data-observability
vendors sell exactly this triage as a product; here it's an open MCP agent anyone can point at their
own DataHub.

## Provenance & disclosure
Newly created during the hackathon submission period (July 2026). Built with standard, publicly
available tools only — the DataHub SDK/CLI (`acryl-datahub`), the official DataHub MCP server
(`mcp-server-datahub`), the MCP client SDK (`mcp`), the Anthropic SDK, and Streamlit. No
pre-existing or proprietary code was incorporated.

## License
Apache-2.0 — see [LICENSE](LICENSE).
