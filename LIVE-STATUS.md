# Lineage Detective release state

Last reconciled: 2026-07-28 EDT

This is the canonical state ledger. `Implemented`, `tested`, `deployed`,
`published`, and `submitted` are intentionally separate.

## Green: implemented

- `public_judge` is the fail-closed hosted mode. It accepts only the
  release-bound reasoning gateway and server-side contest DataHub
  configuration.
- `self_hosted` supports customer-controlled DataHub, repository, connector,
  validation, and deployment configuration.
- The agent searches DataHub, walks upstream and downstream lineage, reads
  entity evidence, writes containment tags, and independently reads those
  writes back.
- Model output is constrained by JSON Schema and by the exact URNs found in the
  current DataHub evidence. Invalid or truncated reasoning fails closed and the
  error survives the final Streamlit rerun.
- A single explicit approval can investigate, contain, draft a bounded change,
  test it in isolated dbt/DuckDB, prove rollback, apply the exact verified bytes
  to the selected safe target, and prepare a hash-bound handoff.
- GitHub, dbt Cloud, Airflow, Fivetran, Snowflake, DataHub assertion, customer
  validation, and verified deployment protocols are available in self-hosted
  mode with scoped customer credentials.
- The judge gateway keeps the provider key server-side and enforces an access
  window, authentication throttling, reasoning throttling, request-size and
  output limits, plus a durable account-wide daily request budget.
- The Cloudflare Container is non-root, digest-pinned at build inputs, and uses
  an hourly date-bounded warm-up trigger through the end of judging.

## Green: tested

- Canonical Python suite: **213 passed, 0 failed** in 32.640 seconds.
- All ten release-audit gates passed:
  - `pip check`;
  - hash-locked `pip-audit`;
  - source compilation;
  - security-boundary verification;
  - bound example verification;
  - judge-gateway tests and npm audit;
  - Container Worker npm audit;
  - both Worker syntax checks.
- Judge gateway: **10 Node tests passed**, including dynamic evidence-URN
  constraints; a real authenticated provider call returned schema-valid JSON.
- Hostile paths cover malformed model output, unobserved URNs, authentication,
  limits, redirects, MCP timeouts, concurrent writers, stale locks, source
  drift, rollback failure, receipt tampering, and partial connector outcomes.
- The public workflow automation now proves that the start click was accepted,
  records every changed progress state, and fails quickly if the session
  restarts or returns to idle without a terminal result.

## Green: deployed and exercised

- Public app:
  <https://lineage-detective.equinoxaifinance.workers.dev>
- Judge gateway:
  <https://lineage-detective-judge-gateway.equinoxaifinance.workers.dev>
- Cloudflare readback showed the deployed Container healthy with no rollout
  errors and no SSH authorized keys.
- The hourly warm-up schedule (`0 * * * *`) was present in deployment readback.
- The gateway accepted the encrypted owner invitation, rejected an invalid code
  at HTTP 401, and reports access through 2026-09-15.
- The final public browser workflow completed in about 70 seconds:
  - six upstream hops selected;
  - seven live DataHub entities returned;
  - 100% progress visible;
  - two downstream assets and two tag writes confirmed;
  - sandbox assertion changed from 0/8 to 8/8;
  - rollback verified;
  - exact-byte implementation hash matched;
  - JSON sandbox receipt, JSON implementation receipt, and valid handoff ZIP
    downloaded with zero browser-console errors.

## Green: published and submitted

- Public Apache-2.0 repository:
  <https://github.com/equinoxaifinance-rgb/lineage-detective>
- Public video (169.733 seconds):
  <https://www.youtube.com/watch?v=TG6erPXMv7M>
- Devpost:
  <https://devpost.com/software/lineage-detective>
- Devpost submission `1077519` was read back in submitted state with the final
  tagline, thumbnail, video, private judge URL, sample-output URL, category,
  and DataHub technology selections.
- The optional upstream-contribution bonus is intentionally left blank. This
  entry is a DataHub application, not a contribution submitted upstream to the
  DataHub project.

## Owner-controlled facts

Eligibility, conflicts, ownership, third-party authorization, and agreement to
the official rules are Bryan's legal attestations. The software receipts cannot
independently prove identity; Devpost records the submitted entry and the
entrant's agreement.

No contest placement is claimed or guaranteed.
