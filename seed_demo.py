"""seed_demo.py — plant THREE data-incident scenarios in a live DataHub using REAL, NATIVE
metadata signals the agent must REASON over — never a plain-English statement of the cause.

Each root cause is discoverable ONLY by reasoning over genuine evidence, exactly as an on-call
engineer would — nothing in the catalog says "I am the cause":

  A. SILENT PARTIAL LOAD — prod.raw.orders loaded ~61k rows this run vs a ~102k 7-day average
     (a ~40% collapse), yet run_status is 'success' and no volume test guards it. The agent must
     spot the row-count anomaly against the node's own baseline.
  B. SCHEMA DRIFT        — prod.raw.customers renamed its email column to 'email_address', but
     analytics.staging.stg_customers still exposes the OLD 'email' field, which now reads 100% NULL.
     The agent must DIFF the real schemas across the two hops to find the rename.
  C. STALE / FRESHNESS   — prod.ref.exchange_rates 'succeeds' but has added 0 rows across its last
     5 daily runs and its latest rate_date is frozen at 2026-07-05. The agent must reason about
     freshness (a job that succeeds while adding no data).

The clue is always a REAL signal — a row-count delta, a schema diff, a freshness gap. The plain-
English "answer key" that used to sit in a custom property has been removed on purpose.
"""
from datahub.sdk import DataHubClient, Dataset, Tag

c = DataHubClient(server="http://localhost:8080")

# Incident vocabulary the agent applies via the MCP add_tags tool. The MCP server validates that a
# tag entity EXISTS before it can be attached (unlike the raw SDK, which auto-creates), so these
# tags are part of the catalog setup — defined once, then used by the autonomous agent.
for _tag, _desc in (("QUARANTINE_INCIDENT", "Root cause of a data incident — quarantined by Lineage Detective."),
                    ("IMPACTED_BY_INCIDENT", "Downstream asset contaminated by an upstream incident.")):
    c.entities.upsert(Tag(name=_tag, description=_desc))


def make(platform, name, description, props, schema):
    d = Dataset(platform=platform, name=name, description=description,
                custom_properties=props, schema=schema)
    c.entities.upsert(d)
    return str(d.urn)


def chain(*urns):
    for up, down in zip(urns, urns[1:]):
        c.lineage.add_lineage(upstream=up, downstream=down)


# ---- A. SILENT PARTIAL LOAD (volume anomaly vs the node's own baseline) -----------
a_raw = make("bigquery", "prod.raw.orders", "Raw orders, hourly from the Orders REST API.",
             {"owner": "alice@data-eng", "latest_run_status": "success",
              "rows_loaded_latest_run": "61240", "rows_prior_7day_avg": "101800",
              "latest_load_partition": "2026-07-11", "volume_test": "not_configured"},
             [("order_id", "number"), ("customer_id", "number"),
              ("order_ts", "timestamp"), ("amount_usd", "number")])
a_stg = make("dbt", "analytics.staging.stg_orders", "1:1 passthrough of raw.orders.",
             {"owner": "bob@analytics", "latest_run_status": "success", "model_type": "passthrough",
              "dbt_tests": "not_null, unique (schema-only; no volume/row-count test)"},
             [("order_id", "number"), ("customer_id", "number"),
              ("order_ts", "timestamp"), ("amount_usd", "number")])
a_fct = make("dbt", "analytics.marts.fct_revenue", "Daily sum of order totals.",
             {"owner": "bob@analytics", "latest_run_status": "success",
              "model_type": "sum(amount_usd) group by order_day", "dbt_tests": "schema-only"},
             [("order_day", "date"), ("total_revenue_usd", "number")])
a_dash = make("looker", "bi.revenue_overview", "Executive Revenue Overview dashboard.",
              {"owner": "carol@bi"}, [("order_day", "date"), ("total_revenue_usd", "number")])
chain(a_raw, a_stg, a_fct, a_dash)

# ---- B. SCHEMA DRIFT (column rename upstream, old name still used downstream) ------
b_raw = make("bigquery", "prod.raw.customers", "Raw customer records from the CRM export.",
             {"owner": "dan@data-eng", "latest_run_status": "success",
              "crm_export_version": "v2 (effective 2026-07-11)"},
             [("customer_id", "number"), ("full_name", "string"), ("email", "string"),
              ("email_address", "string"), ("created_at", "timestamp")])
b_stg = make("dbt", "analytics.staging.stg_customers",
             "Typed customer staging; maps the CRM export into the analytics schema.",
             {"owner": "bob@analytics", "latest_run_status": "success",
              "email_null_rate_current": "1.00", "email_null_rate_prior": "0.02",
              "dbt_tests": "schema-only (no not_null assertion on email)"},
             [("customer_id", "number"), ("full_name", "string"),
              ("email", "string"), ("created_at", "timestamp")])
b_dim = make("dbt", "analytics.marts.dim_customers", "Customer dimension feeding Customer 360.",
             {"owner": "bob@analytics", "latest_run_status": "success"},
             [("customer_id", "number"), ("full_name", "string"), ("email", "string")])
b_dash = make("looker", "bi.customer_360", "Customer 360 dashboard (contactability KPIs).",
              {"owner": "carol@bi"}, [("customer_id", "number"), ("email", "string")])
chain(b_raw, b_stg, b_dim, b_dash)

# ---- C. STALE / FRESHNESS (job 'succeeds' but adds no rows; latest data frozen) ---
c_ref = make("bigquery", "prod.ref.exchange_rates", "Daily FX rates reference table.",
             {"owner": "erin@data-eng", "latest_run_status": "success", "refresh_cadence": "daily",
              "latest_rate_date": "2026-07-05", "rows_added_last_5_runs": "0",
              "freshness_test": "not_configured"},
             [("rate_date", "date"), ("currency", "string"), ("usd_rate", "number")])
c_fct = make("dbt", "analytics.marts.fct_revenue_usd",
             "Revenue converted to USD using exchange_rates (join on rate_date).",
             {"owner": "bob@analytics", "latest_run_status": "success",
              "model_type": "revenue * usd_rate, join exchange_rates on rate_date",
              "dbt_tests": "schema-only"},
             [("order_day", "date"), ("revenue_usd", "number")])
c_dash = make("looker", "bi.finance_fx", "Finance USD-revenue dashboard.",
              {"owner": "frank@finance"}, [("order_day", "date"), ("revenue_usd", "number")])
chain(c_ref, c_fct, c_dash)

print("SEEDED 3 incident scenarios (real signals only; no plain-English cause).")
print("A_PARTIAL_LOAD dashboard=" + a_dash + " root=" + a_raw)
print("B_SCHEMA_DRIFT dashboard=" + b_dash + " root=" + b_raw)
print("C_STALE       dashboard=" + c_dash + " root=" + c_ref)
