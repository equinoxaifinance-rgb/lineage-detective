# Lineage Detective — Devpost submission draft

## Tagline

From a broken dashboard to a verified repair: a DataHub-native incident agent
that investigates, contains, fixes, tests, and hands off the exact evidence.

## Inspiration

When a dashboard suddenly looks wrong, the first hour is often a human opening
lineage tabs, asking who owns each asset, and guessing where the failure began.
The useful part of an AI agent is not confident prose; it is the ability to
ground a decision in the organization's real context, take a controlled
action, and prove what happened.

Lineage Detective was built around that standard. DataHub supplies the context
graph and the action surface. The model is allowed to reason over that
evidence, but it cannot invent assets, skip approval boundaries, or call an
action complete without readback.

## What it does

1. Search a connected DataHub and select the affected asset.
2. Walk upstream lineage and read entity metadata, ownership, schema, and
   observed incident properties through the official DataHub MCP Server.
3. Produce a ranked, evidence-bound diagnosis. Suspect URNs must exactly match
   entities returned by DataHub.
4. When requested, tag the likely root cause and downstream blast radius
   through MCP, then read those writes back.
5. Draft an exact repair or guardrail.
6. Run the approved change in an isolated dbt/DuckDB sandbox, measure the
   broken baseline and corrected result, verify rollback, and seal a receipt.
7. Apply the exact verified bytes to a selected checkout with drift detection,
   backup, restore, and serialized writers—or export a human handoff.
8. In a customer-controlled self-hosted process, continue through GitHub, dbt
   Cloud, Airflow, Fivetran, Snowflake, DataHub assertions, a customer test
   command, or a deployment profile with an independent live health check and
   verified rollback.

The public judge build keeps all catalog and provider secrets server-side.
Devpost's judge-only Project URL carries a bounded invitation which the app
verifies and removes from the address bar automatically. Customer credentials
are never requested by the shared public process.

## How we built it

- Python 3.11 and Streamlit for the application.
- DataHub MCP Server for search, lineage, entity reads, and catalog tag writes.
- DataHub SDK only for idempotent incident-tag vocabulary setup.
- A model-backed reasoning gateway with strict request limits, rate limiting,
  a durable daily spend cap, and no browser-visible provider key.
- dbt plus DuckDB for isolated, reproducible repair verification.
- Cloudflare Workers, Durable Objects, rate-limit bindings, and Containers for
  the hosted judge path.
- Digest-pinned, hash-locked dependencies and a non-root container.
- A comprehensive packaged suite covering normal, hostile, failure, retry,
  concurrency, authorization, integrity, connector, and rollback paths.

## Challenges

The hardest problem was preserving trust while adding autonomy. A model can
write plausible SQL quickly; that does not make the SQL correct, safe to apply,
or safe to deploy. We separated proposal, sandbox verification, source apply,
external action, downstream readback, and rollback into distinct states with
different receipts.

We also isolated an upstream DataHub packaging constraint. The application
stays on the fixed modern runtime while the pinned official DataHub CLI/SDK/MCP
tooling runs in a separate hash-locked compatibility environment. The app can
move to one unified environment when DataHub's published constraints and a
reviewed lock permit it.

## Accomplishments

- DataHub is both the evidence plane and the action plane.
- Invalid or ungrounded model output cannot trigger containment or repair.
- Catalog writes are not called successful until DataHub returns them.
- A sandbox pass binds the exact source and proposal hashes and verifies
  rollback.
- Concurrent or stale apply attempts cannot silently overwrite a human edit.
- Partial connector success is reported honestly with remote IDs preserved.
- A failed live deployment triggers source restoration, customer rollback, and
  an independent rollback check.
- Three different generated repair examples and their receipts ship in the
  public repository.

## What we learned

Autonomy is not the absence of human control. It is the removal of unnecessary
manual work while keeping the decision, evidence, and recovery path visible.
The strongest agent is not the one that claims the most; it is the one that
knows exactly which claim it has earned.

## What's next

- Run design-partner incidents against customer DataHub tenants and real test
  repositories.
- Measure time-to-diagnosis, proposal acceptance, sandbox pass rate, and
  rollback frequency.
- Package connector profiles for repeatable customer deployment.
- Contribute the reusable incident-response skill and compatibility findings
  upstream where maintainers find them useful.

## Personal note

Bryan supplied the direction, product standards, testing pressure, and every
accept/reject decision. Codex turned that direction into the implementation,
tests, interface, evidence system, and submission materials. Neither side did
the other's job: the product exists because human judgment and AI execution
kept correcting one another until the claims matched the work.

## Verified links

- Live app: `https://lineage-detective.equinoxaifinance.workers.dev`
- Public repository: `https://github.com/equinoxaifinance-rgb/lineage-detective`
- Public video: `https://www.youtube.com/watch?v=TG6erPXMv7M`
- Sample outputs: `https://github.com/equinoxaifinance-rgb/lineage-detective/tree/main/examples/generated`
- Judge testing path: the private Devpost Project URL consumes the bounded
  invitation automatically; no credential is committed here.
