# Independent release review and remediation

This is a closure ledger, not a claim that reviewers can guarantee contest placement. Reviews were
run against a source-only snapshot on 2026-07-26. Raw responses are preserved outside the public
repository with model/version, timestamp, scope, status, and SHA-256.

## Review receipts

| Reviewer family | Live model | Raw-response SHA-256 |
|---|---|---|
| xAI | `grok-4.3` | `545925cad10d178f29864d943f702a31bb1faf81f5975f41acdb059e35ba3532` |
| DeepSeek | `deepseek-v4-pro` | `3d3fdee26fd973527119107c0adf01bed83c7eebf1da96511b4cefd7d69e7e8d` |
| OpenAI | `gpt-5.4-2026-03-05` | `0403b805a62a422dc7077c1f1fec9af7b328ee909afa0343867fea85dcb17d87` |
| Google | `gemini-3.1-pro-preview` | `eeb7f306f873e0c228a9df1e58abd57104d281bada18ce66eafe02269c99cea4` |

Council prompt SHA-256:
`2201ebe93b1f3c8c46e1cc20a222bed6e96de9baaddae38`.

Three additional independent engineering, judge/product, and workflow/market reviews inspected the
repository and live product. Cross-review agreement prioritized the following work; it did not
substitute for the executed tests.

## Accepted findings and closure

| Finding | Implemented change | Regression / receipt |
|---|---|---|
| A successful assertion could remain `verified` after cleanup failed | Receipt sealing now occurs after rollback; cleanup failure forces `sandbox_failed`; apply and handoff require a valid receipt hash, verified state, and `rollback_verified=true` | `test_successful_rewrite_with_failed_rollback_is_not_verified` |
| Public sessions could share writable sandbox/demo files | The immutable sandbox template is copied into a new OS temporary directory for every run; the UI creates a unique demo checkout per Streamlit session | eight concurrent trials use eight distinct paths and all verify removal |
| A file could change after proposal generation | Every proposal binds `source_sha256`; apply compares current bytes and rejects drift before backup or write | `test_apply_refuses_source_drift_after_proposal` |
| Handoff packaging could fail after a file was already changed | The workflow builds the verified recovery/handoff artifact before any selected target is touched | `test_handoff_packaging_failure_happens_before_any_apply` |
| Hosted DataHub inputs bypassed connector URL policy | One shared policy now covers DataHub GMS, managed MCP, vocabulary GraphQL, and remediation connectors; hosted mode requires public HTTPS and rechecks DNS before requests | `tests/test_network_policy.py` plus connector tests |
| Credential-bearing HTTP could redirect to another host | Connector and DataHub GraphQL requests reject redirects; managed MCP disables redirects | transport and network-policy contract tests |
| Public examples showed investigation only | Three current repair cases now ship exact SQL, diff, sandbox receipt, handoff ZIP, manifest sizes, and SHA-256 values | `python tools/verify_release_examples.py` |
| Public repository lacked durable automated evaluation | A least-privilege GitHub Actions release gate installs the hash-locked runtime, compiles, runs the full suite, checks dependencies/security boundary, and verifies all example artifacts | `.github/workflows/ci.yml` |

## Deliberate boundaries

- DataHub is the evidence/control plane; a real target-system credential is required to change a
  real GitHub repository, dbt Cloud job, Airflow DAG, Fivetran connector, Snowflake account, or
  DataHub Cloud assertion.
- The hosted app does not contain a shared customer DataHub credential. Judges may connect a scoped
  tenant token, or use the repository quickstart for the bundled real local DataHub catalog.
- A sandbox receipt proves the tested fixture and exact bytes. It does not claim universal
  production safety across every warehouse, data volume, permission model, or deployment process.

See [`RELEASE-VERIFICATION.md`](RELEASE-VERIFICATION.md) for executed release and browser receipts.
