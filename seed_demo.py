"""seed_demo.py — plant THREE distinct data-incident scenarios in a live DataHub, so Lineage
Detective can be shown diagnosing materially different failure types (not one hardcoded case).
Each is a real lineage chain with a realistic metadata clue at the true root cause — never a sign
that says 'I AM BROKEN'; the agent has to reason to it.

  A. SILENT PARTIAL LOAD  — raw.orders lost ~40% of rows overnight (revenue drops, no error)
  B. SCHEMA DRIFT         — raw.customers renamed a column; downstream emails go null
  C. STALE / FRESHNESS    — ref.exchange_rates feed frozen for days; USD revenue looks stuck
"""
from datahub.sdk import DataHubClient, Dataset, Tag

c = DataHubClient(server="http://localhost:8080")

# Incident vocabulary the agent applies via the MCP add_tags tool. The MCP server validates that a
# tag entity EXISTS before it can be attached (unlike the raw SDK, which auto-creates), so these
# tags are part of the catalog setup — defined once, then used by the autonomous agent.
for _tag, _desc in (("QUARANTINE_INCIDENT", "Root cause of a data incident — quarantined by Lineage Detective."),
                    ("IMPACTED_BY_INCIDENT", "Downstream asset contaminated by an upstream incident.")):
    c.entities.upsert(Tag(name=_tag, description=_desc))


def make(platform, name, description, props):
    d = Dataset(platform=platform, name=name, description=description, custom_properties=props)
    c.entities.upsert(d)
    return str(d.urn)


def chain(*urns):
    for up, down in zip(urns, urns[1:]):
        c.lineage.add_lineage(upstream=up, downstream=down)


# ---- A. SILENT PARTIAL LOAD ------------------------------------------------------
a_raw = make("bigquery", "prod.raw.orders", "Raw orders, hourly from the Orders REST API.",
             {"owner": "alice@data-eng", "run_status": "success",
              "last_run_note": "2026-07-11 02:00 UTC: source API returned ~40% fewer rows than 7-day avg (suspected upstream partial outage); backfill NOT yet run"})
a_stg = make("dbt", "analytics.staging.stg_orders", "1:1 passthrough of raw.orders.",
             {"owner": "bob@analytics", "run_status": "success", "tests": "passed"})
a_fct = make("dbt", "analytics.marts.fct_revenue", "Daily sum of order totals.",
             {"owner": "bob@analytics", "run_status": "success", "tests": "passed"})
a_dash = make("looker", "bi.revenue_overview", "Executive Revenue Overview dashboard.",
              {"owner": "carol@bi"})
chain(a_raw, a_stg, a_fct, a_dash)

# ---- B. SCHEMA DRIFT -------------------------------------------------------------
b_raw = make("bigquery", "prod.raw.customers", "Raw customer records from the CRM export.",
             {"owner": "dan@data-eng", "run_status": "success",
              "last_run_note": "2026-07-11: CRM export schema changed — column 'email' renamed to 'email_address'; downstream column mappings not updated, so email now resolves NULL"})
b_stg = make("dbt", "analytics.staging.stg_customers", "Typed customer staging; maps CRM fields.",
             {"owner": "bob@analytics", "run_status": "success", "tests": "passed (schema tests only)"})
b_dim = make("dbt", "analytics.marts.dim_customers", "Customer dimension feeding Customer 360.",
             {"owner": "bob@analytics", "run_status": "success"})
b_dash = make("looker", "bi.customer_360", "Customer 360 dashboard (contactability KPIs).",
              {"owner": "carol@bi"})
chain(b_raw, b_stg, b_dim, b_dash)

# ---- C. STALE / FRESHNESS --------------------------------------------------------
c_ref = make("bigquery", "prod.ref.exchange_rates", "Daily FX rates reference table.",
             {"owner": "erin@data-eng", "run_status": "success",
              "last_run_note": "STALE: last successful load 2026-07-05; upstream FX vendor feed has been DOWN 6 days; job 'succeeds' but writes no new rows, so rates are frozen"})
c_fct = make("dbt", "analytics.marts.fct_revenue_usd", "Revenue converted to USD using exchange_rates.",
             {"owner": "bob@analytics", "run_status": "success", "tests": "passed"})
c_dash = make("looker", "bi.finance_fx", "Finance USD-revenue dashboard.",
              {"owner": "frank@finance"})
chain(c_ref, c_fct, c_dash)

print("SEEDED 3 incident scenarios.")
print("A_PARTIAL_LOAD dashboard=" + a_dash + " root=" + a_raw)
print("B_SCHEMA_DRIFT dashboard=" + b_dash + " root=" + b_raw)
print("C_STALE       dashboard=" + c_dash + " root=" + c_ref)
