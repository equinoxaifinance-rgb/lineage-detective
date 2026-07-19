# Sample outputs

Real, unedited reports produced by Lineage Detective running against a live DataHub through the
DataHub **MCP Server** — so you can see what it does without setting anything up. Each was generated
by `python src/agent.py "<symptom>" "<affected URN>"` against the three seeded demo incidents.

| File | Incident | Root cause the agent found |
|------|----------|----------------------------|
| [`A_partial_load.txt`](A_partial_load.txt) | Revenue dashboard dropped ~40%, no errors | `prod.raw.orders` — silent partial load (source API returned ~40% fewer rows) |
| [`B_schema_drift.txt`](B_schema_drift.txt) | Customer 360 emails went blank | `prod.raw.customers` — CRM renamed `email` → `email_address` |
| [`C_stale_feed.txt`](C_stale_feed.txt) | Finance USD revenue frozen | `prod.ref.exchange_rates` — vendor FX feed down 6 days, job "succeeds" writing no rows |

Each report ends with the ranked suspects, the owner to contact, and (when run with `--act`) the
`QUARANTINE_INCIDENT` / `IMPACTED_BY_INCIDENT` tags the agent writes back to DataHub via the MCP
`add_tags` tool. The agent generalizes beyond these — see the "Use it on your own DataHub" section
of the top-level README.
