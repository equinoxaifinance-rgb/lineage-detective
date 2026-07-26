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
- 109/109 local tests in 48.024 seconds and 109/109 tests from the exact clean
  Linux/amd64 release-candidate image in 28.779 seconds.
- Three executed example cases with independently verified hashes and handoff ZIPs.
- Local browser full run: four live lineage entities, containment plus two impact writes read back,
  0/8 to 8/8 sandbox assertion, rollback confirmed, session-isolated exact-byte apply, handoff and
  receipt downloads rendered, zero console errors, and no desktop/mobile horizontal overflow.

## Green: packaged release

- Image proof pass: `lineage-detective:release-candidate`
- Proof-pass digest:
  `sha256:f67902d39550812fecb455c2cd932db8d4c525bba4f405e3adc6dd57b0f5132f`
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
- Final video owner approval and external publication.

## Green: final judge video artifact

- 148.100 seconds, 1920x1080, 30 fps, H.264 video plus AAC audio.
- The browser recording contains one uninterrupted real approval-to-repair workflow; its event
  timeline recorded the single action-local rail advancing monotonically through
  10, 22, 36, 47, 57, 60, 61, 70, 76, 88, 94, and 100 percent, then reached live lineage,
  diagnosis, exact diff, sandbox receipt, autonomous completion, and verified handoff.
- Both streams decoded end to end with zero decoder errors. Integrated loudness measured
  -16.3 LUFS with -1.4 dB true peak.
- An independent speech-to-text pass recovered the intended technical claims, including
  zero rows passing before and all eight rows passing after, plus the human/AI authorship note.
- SHA-256:
  `b3d7a8595b232e0b08620ee31991cd832e3c333b644ff87f77274363cc666856`

## Intentionally not started

- Devpost publication/submission. Bryan requested the final video first. After he approves it, run
  the final independent council against the shipped artifact, address any evidenced finding, then
  publish and submit.
