# Lineage Detective release state

Last reconciled: 2026-07-28 06:24 EDT

This file is the canonical state ledger. `Implemented`, `tested`, `packaged`,
`deployed`, `published`, and `submitted` are intentionally separate.

## Green: implemented and packaged locally

- Two explicit runtime modes:
  - `public_judge` is the fail-closed default. It accepts only the release-bound
    reasoning gateway and server-side contest DataHub configuration. It does not
    expose customer connector credentials or arbitrary deployment commands.
  - `self_hosted` enables customer-controlled DataHub, repository, connector,
    validation, and deployment configuration.
- Real DataHub MCP search, upstream and downstream lineage, entity reads, tag
  writes, and independent tag readback.
- Evidence-grounded model output with strict schema validation, observed-URN
  enforcement, and one bounded correction retry.
- Approval-gated proposal, isolated dbt/DuckDB verification, exact-byte apply,
  source-drift protection, serialized writers, backup, restore, and signed
  receipts.
- Connector protocols for GitHub pull requests, dbt Cloud, Airflow, Fivetran,
  Snowflake SQL, DataHub assertions, and customer validation commands.
- Self-hosted deployment profile with an independent live check and mandatory
  verified rollback on failure.
- Judge gateway with an access window, authentication attempt throttling,
  reasoning throttling, request-size limits, fixed model/output limits, and a
  durable whole-gateway daily budget.
- Cloudflare Container packaging from digest-pinned Python and rootless-Docker
  bases, a minimized build context, and an unprivileged application process.
  The image build itself runs compilation, the full test suite, the security
  boundary verifier, and the bound-example verifier before export.

## Green: current receipts

- Latest final image-build suite: **205 passed, 0 failed** in 32.771 seconds.
- Deployed runtime image digest:
  `sha256:2d6da7d2a742318e067a6901e50fb44a7edaba518466b05512b268c8e5e640fd`.
- Final UI/Container capture-contract regression suite: 55 passed.
- Packaged app:
  - `pip check`: no broken requirements.
  - `pip-audit 2.10.1`: no known vulnerabilities in the checked-in,
    hash-locked runtime requirements.
  - source compilation: exit 0.
  - DataHub, MCP, and Streamlit runtime UID: 1000 (`lineage`), not root.
  - health endpoint: `ok`.
  - root page: HTTP 200.
  - shipped Streamlit config:
    `sha256:4c0d35e1ff8638b26ce3d826737615dbe05e23dd6f0d3033be702ac668276abe`.
- Judge gateway:
  - 8 Node runtime tests passed.
  - syntax check passed.
  - `npm audit`: 0 vulnerabilities.
  - Wrangler 4.114.0 dry-run passed.
- Hosted Container Worker:
  - `npm audit`: 0 vulnerabilities.
  - Wrangler 4.114.0 rebuilt the digest-pinned verified image and passed dry-run.
  - Cloudflare Container version 41 is active on the exact image digest above.
  - Cloudflare readback reports one healthy instance, zero rollout errors, and
    an explicit empty `authorized_keys` list.
- Three committed output examples and every bound receipt/artifact verified.
- GitHub Actions are pinned to exact commit SHAs; CI repeats tests, audits,
  example verification, and both Cloudflare dry-runs.

## Green: executed public-path receipts

- The public one-approval browser workflow completed at 100% against the real
  bundled DataHub catalog using the server-side judge gateway.
- DataHub returned seven catalog entities across six dependency edges; the
  gateway produced the constrained diagnosis and the evidence compiler bound
  the repair proposal to the observed schema transition.
- The dbt/DuckDB trial measured the broken baseline, applied the exact rewrite,
  passed eight of eight assertions, and verified rollback.
- The public browser downloaded the JSON sandbox receipt, exact-byte
  implementation receipt, and human-handoff ZIP. The standalone receipt and
  the receipt embedded in the ZIP both report the verified 0/8 -> 8/8 result
  and rollback proof. The implementation receipt reports `applied_verified`,
  a proposal/expected/post-write hash match, and a recorded backup.
- Independent MCP readback confirmed:
  - `QUARANTINE_INCIDENT` on
    `analytics.staging.stg_customers`;
  - `IMPACTED_BY_INCIDENT` on
    `analytics.marts.dim_customers`; and
  - `IMPACTED_BY_INCIDENT` on `bi.customer_360`.
- The browser-test invitation was rotated after the live run. The final
  invitation passed authenticated `/preflight`; an independent wrong code was
  rejected at HTTP 401. The final code is stored in the encrypted local owner
  handoff and remains valid through 2026-09-15.

## Yellow: remaining external release gates

These are real gates, not product-code failures:

1. **Current public repository.** The remote `main` branch is behind the local
   release work. Push only after the final release receipt is generated.
2. **Video publication.** The final 169.733-second live demonstration is
   locally complete and QA-verified. It still needs Bryan's approval, a public
   YouTube upload, and anonymous readback.
3. **Devpost synchronization.** Devpost confirmed submission `1077519` on
   2026-07-12, and the public project page at
   `https://devpost.com/software/lineage-detective` independently renders as
   submitted to the DataHub hackathon. That published entry is an earlier
   build: it still embeds YouTube video `3DDZsz4BtJU`, links the repository but
   no live app, and describes the original diagnose/contain workflow rather
   than this release candidate. Owner eligibility/IP attestations, the final
   video, synchronized repository, live app, and judge instructions must be
   entered and read back only after the preceding gates are green.

## Release order

1. Freeze source and documentation; bind the final release receipt.
2. Push the public Apache-2.0 repository and read it back anonymously.
3. After owner approval, upload the final live video publicly and read it back
   anonymously.
4. Update the already-submitted Devpost entry and read back every public field.

Until those release-synchronization steps complete, the honest state is:
**final product and public judge path verified; repository, media, and Devpost
are not yet synchronized to this release.**
