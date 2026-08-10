# Release verification

Verified on 2026-08-10 EDT. This records executed facts, not contest placement
or universal production safety in an unknown customer environment.

## Executed receipts

| Surface | Executed verification | Result |
|---|---|---|
| Complete Python suite | `python -m unittest discover -s tests -q` | 217 passed, 0 failed, 1 skipped |
| Python dependencies | both `pip check` paths and hash-locked `pip-audit` | no broken requirements; runtime 0 known vulnerabilities; isolated sidecar 0 actionable vulnerabilities with 2 instances of the documented, unreachable `PYSEC-2026-3447` ignored |
| Source and examples | compilation, security-boundary verifier, bound-example verifier | all passed |
| Judge gateway | 10 Node tests, syntax, npm audit, dry-run packaging, live authenticated provider probe | passed; 0 npm vulnerabilities; schema-valid response hashed |
| Hosted Worker | syntax, npm audit, Cloudflare deployment readback | passed; hourly warm-up trigger present |
| Container | packaged test/build gates, public root, Cloudflare health readback | Streamlit HTTP 200; healthy; zero rollout errors; no authorized SSH keys |
| Public access boundary | authenticated `/preflight` plus independent invalid code | valid invitation accepted through 2026-09-15; invalid code HTTP 401 |
| Public judge workflow | fresh signed-in browser run against the deployed URL | 100%; three live entities; containment write read back; sandbox freshness guard verified; exact-byte apply, handoff, and hash-verified backup restore completed |
| Sandbox repair | downloaded JSON receipt | baseline 0/8; repaired 8/8; rollback verified |
| Exact-byte implementation | downloaded JSON receipt | `applied_verified`; proposal, expected, and post-write hashes match; backup recorded |
| Handoff | downloaded ZIP plus archive integrity test | valid archive containing README, diff, model SQL, and embedded sandbox receipt |
| Public repository | anonymous GitHub API and raw-file reads | public `main`; Apache-2.0; generated example manifest reachable |
| Public video | local signal/alignment receipts plus YouTube metadata readback | 169.733s; public; no black/silence events in final media QA |
| Upstream contribution | fork/branch readback plus GitHub PR API and UI | DataHub PR #135 open and mergeable at head `7333bf3`; maintainer workflow approval and review remain pending |
| Devpost | signed-in field, save navigation, reload, and finalization readback | submitted 5/5; contribution field contains PR #135; public story reconciled and read back |

The public workflow receipt is
`.release-work/v43-public-workflow-receipt.json`. It binds the downloaded
artifact sizes and SHA-256 hashes. The corresponding progress timeline proves
that the run advanced from live DataHub evidence through diagnosis, sandbox,
rollback, receipt binding, and a terminal 100% state.

## What the receipts prove

- The packaged application starts and the tested judge workflow behaves as the
  submission claims.
- DataHub is the evidence and action plane: the run used real catalog entities,
  lineage, containment writes, and independent readback.
- The hosted model cannot return a suspect outside the exact evidence-URN set.
  Truncated or invalid structured output is rejected rather than repaired by
  invention.
- The sandbox receipt proves the exact proposal against the included
  representative fixture. It is not a universal production guarantee.
- A real customer deployment remains customer-controlled: scoped credentials,
  an explicit target, a live health check, and a verified rollback path are
  required.

## Upstream compatibility boundary

The judge-facing application uses the fixed modern runtime in
`requirements-runtime.lock`, including `setuptools==83.0.0`. The pinned
DataHub CLI/SDK/MCP release constrains its own environment to `setuptools<82`,
so those official tools run in a separate checked-in, hash-locked sidecar.
Lineage Detective automatically uses a reviewed unified lock when a compatible
DataHub release exists.

This is isolation, not concealment and not an upstream fix. The application
runtime remains current and audit-green while the official DataHub tool
process retains its declared constraint. No untrusted runtime install or
PATH-discovered package is permitted in release mode.

## Official-rule check

Primary sources accessed 2026-08-10 EDT:

- <https://datahub.devpost.com/>
- <https://datahub.devpost.com/rules>

The entry supplies a working DataHub application, easy judge access, a public
Apache-2.0 repository with setup instructions and sample outputs, an English
description, and a public product video under three minutes. Free judge access
extends beyond the August 31 judging deadline.

The optional bonus concerns meaningful contributions submitted upstream to
DataHub—connectors, skills, fixes, RFCs, or documentation improvements. The
evidence-backed incident-response skill was submitted as
<https://github.com/datahub-project/datahub-skills/pull/135>, and that exact URL
was saved and read back in Devpost's contribution field. The PR is open and
mergeable; maintainer approval, review, merge, and any bonus decision remain
external and are not claimed.
