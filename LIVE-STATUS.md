# Lineage Detective release status — 2026-07-26

This file separates implemented, tested, packaged, deployed, published, and submitted states.

## Green: implemented and independently exercised

- Live DataHub MCP search, lineage traversal, entity evidence, containment writes, and write
  readback.
- Model-backed and disclosed evidence-only reasoning lanes.
- Evidence-bound schema rewrite, partial-load guard, stale-feed guard, and arbitrary checked-out
  dbt SQL proposal.
- One-approval workflow plus manual review mode.
- Per-run sandbox isolation, rollback-required receipt integrity, source-drift rejection, atomic
  apply/backup/restore, and handoff-before-write journaling.
- Optional GitHub, dbt Cloud, Airflow, Fivetran, Snowflake, DataHub assertion, and customer-command
  connectors with scoped credentials and secret-free receipts.
- Hosted public-network policy and redirect rejection for credential-bearing requests.
- 102/102 local tests and 102/102 tests from a clean Linux/amd64 image after the final redirect
  regression was added.
- Three executed example cases with independently verified hashes and handoff ZIPs.
- Local browser full run: four live lineage entities, containment plus two impact writes read back,
  0/8 to 8/8 sandbox assertion, rollback confirmed, session-isolated exact-byte apply, handoff and
  receipt downloads rendered, zero console errors, and no desktop/mobile horizontal overflow.

## Green: packaged release

- Image proof pass: `lineage-detective:proof-current`
- Proof-pass digest:
  `sha256:436e8a565e1e683e228ef86bf4f850915819482c876f1cf34be3b37957af4127`
- Clean health check: HTTP 200 `ok`
- `pip check`: no broken requirements
- App-runtime audit: no known vulnerabilities
- Secret scan: zero recognizable provider/cloud token files

The exact deployment image is rebuilt after this status file is committed. Its digest is recorded
in the external deployment receipt and Cloudflare version readback rather than written back into
the image that it hashes.

## Yellow until downstream readback

- Public GitHub synchronization and CI result.
- Cloudflare deployment of the exact current source plus public header/UI/runtime checks.
- Fresh authorized judge-gateway probe and encrypted-secret inventory.
- Final under-three-minute live video and independent media QA.

## Intentionally not started

- Devpost publication/submission. Bryan requested the final video first. After he approves it, run
  the final independent council against the shipped artifact, address any evidenced finding, then
  publish and submit.
