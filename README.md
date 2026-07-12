# 🕵️ Lineage Detective — Autonomous Data-Incident Root-Cause Agent

**Built with [DataHub](https://datahub.com) for the Build with DataHub: The Agent Hackathon.**

When a dashboard number looks wrong, a data team's first hour is spent *manually* clicking through
lineage asking "where did this break?" Lineage Detective does that investigation autonomously.

Give it a plain-English symptom and the affected asset. It walks **upstream through DataHub's
lineage graph**, reads the real metadata at every hop (descriptions, custom properties, ownership,
schema), reasons over the evidence like an on-call engineer, and returns a **ranked root-cause
report with the owner to contact** — in seconds.

> **It never invents metadata.** Every fact in a report comes from DataHub; the LLM only *reasons*
> over real evidence and is instructed to say when the evidence is insufficient rather than bluff.

---

## It works — here's a real run

Seeded a classic *silent* incident: `raw.orders` (BigQuery) had a partial overnight load (~40% of
rows missing) → `stg_orders` → `fct_revenue` → a Looker dashboard. **Nothing errored** — the
dashboard just quietly showed less revenue. Given only the symptom, the agent found it:

```
====================================================================
  LINEAGE DETECTIVE — Autonomous Data-Incident Report
====================================================================
Symptom  : Revenue Overview dashboard shows a ~40% drop in daily revenue, no pipeline errors.
Traced   : 4 upstream entities via DataHub lineage

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
  2. [!! ] [MEDIUM] analytics.staging.stg_orders   → contact: bob@analytics
  3. [!  ] [LOW]    analytics.marts.fct_revenue    → contact: bob@analytics
====================================================================
```

## How it works

```
symptom (NL) ──▶ Lineage Detective
                   │  1. gather_upstream(): walk DataHub lineage upstream from the affected asset,
                   │     collecting per-node evidence (owner / schema / description / custom props)
                   │  2. reason: a frontier LLM ranks root-cause suspects over ONLY that evidence
                   ▼
             ranked root-cause report + owner to contact + what to check next
```

- **`src/datahub_evidence.py`** — the agent's senses. Uses the DataHub Python SDK
  (`DataHubClient.lineage.get_lineage`, `entities.get`) to traverse lineage and pull metadata.
  Every Entity field is guarded independently (DataHub properties raise on unset aspects).
- **`src/agent.py`** — the investigator. `investigate(symptom, affected_urn)` → gathers evidence →
  LLM reasoning → strict-JSON report → `render_report()` for the human-readable output above.

## DataHub features used
Lineage graph traversal · entity metadata (schema, ownership, description, custom properties) ·
search/resolve. *(Roadmap: data-quality **assertions** as first-class smoking-gun evidence.)*

## Quickstart
```bash
pip install -r requirements.txt
datahub docker quickstart                 # stand up DataHub locally
python seed_demo.py                        # plant the demo incident (prints the URNs)
export ANTHROPIC_API_KEY=...               # the reasoning model
python src/agent.py "the revenue dashboard dropped 40%, no errors" \
  "urn:li:dataset:(urn:li:dataPlatform:looker,bi.revenue_overview,PROD)"
```

## Why it's original
Not a data catalog, not a chatbot over docs — an **autonomous investigator** that turns DataHub's
lineage + metadata into answered incidents. Data-observability vendors sell exactly this triage as a
product; here it's an open agent anyone can point at their own DataHub.

## License
Apache-2.0 — see [LICENSE](LICENSE).
