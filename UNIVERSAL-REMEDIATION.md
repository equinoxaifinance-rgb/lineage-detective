# Universal remediation contract

Lineage Detective uses DataHub as the evidence and containment control plane. A target-system
adapter implements the change or validation in the system that owns it. “Universal” means a stable,
extensible adapter contract; it does not mean one credential can safely control every system.

## Shipped target adapters

| Target | Real action | Verification |
|---|---|---|
| Local checkout | Apply exact sandbox-approved bytes; create backup | File readback and SHA-256 |
| GitHub | Create repair branch, update the exact file, open PR | Read PR back as open |
| dbt Cloud | Trigger a configured job with optional step overrides | Read the new run state |
| Airflow | Trigger a DAG run with the repair receipt in `conf` | Read the DAG-run state |
| Fivetran | Pause, resume, or sync a connection | Read the connection sync state |
| Snowflake | Execute exactly one reviewed SQL statement with a unique request ID | Read successful statement handle |
| DataHub Cloud | Create an active freshness, row-count, or custom-SQL assertion | Read assertion URN from the GraphQL mutation |
| Any local project | Run an explicit customer test command without a command shell | Exit code, bounded output, SHA-256 |
| Self-hosted deployment profile | Exact write, customer deploy command, live check, automatic source restore and rollback command | Separate live-health and rollback-health commands plus a secret-free SHA-256 receipt |

Every connector credential is accepted only in the active UI session and omitted from receipts.
Individual connector actions have explicit buttons. The self-hosted deployment profile is the one
exception by design: the human selects its full scope first, then one clearly labeled approval runs
sandbox proof, exact write, deploy, live readback, and automatic verified rollback. A DataHub
containment tag never silently becomes a source-system mutation.

The hosted release rejects URLs that resolve to loopback, link-local, reserved, or private network
addresses so connector fields cannot be abused as an SSRF route. A local installation may
explicitly enable private endpoints for customer-controlled Airflow, Snowflake, or DataHub
infrastructure.

## Required customer authority

- GitHub: fine-grained token with repository Contents write and Pull Requests write.
- dbt Cloud: service token plus account and job IDs.
- Airflow: bearer credential able to create and read DAG runs.
- Fivetran: scoped API key/secret able to manage the selected connection.
- Snowflake: OAuth, key-pair JWT, or programmatic access token with the role required by the exact SQL.
- DataHub assertions: DataHub Cloud token with **Edit Assertions** and **Edit Monitors**.
- Self-hosted deployment: the target project and its selected SQL must be present on the host.
  Provider credentials remain in that customer's existing environment or credential manager. The
  customer defines deploy, live-health, rollback, and rollback-health commands once. A self-hosted
  instance can preload them through the documented `LINEAGE_DEPLOY_*` environment variables.

## Deliberate boundaries

- GitHub opens a pull request; it does not merge it.
- dbt and Airflow trigger existing customer-controlled jobs/DAGs; they do not invent infrastructure.
- Fivetran never deletes a connection.
- Snowflake accepts one reviewed statement, attaches an idempotency request ID, and never defaults a
  warehouse repair from a dbt model’s `SELECT`.
- Local validation runs without a shell, with a time limit and captured receipt.
- Self-hosted deployment commands also run without a shell and are hidden in receipts behind hashes.
  The public hosted app does not expose either arbitrary local validation or arbitrary deployment
  commands.
- Deployment is not called verified when only the deploy command exits successfully. The separate
  downstream health check must pass. Any failure enters rollback; a failed rollback readback remains
  red rather than being softened into success.
- A returned target-system ID is not called a successful data repair unless the target also exposes
  a state that can be read back.

## Adding another system

An adapter qualifies only when it provides:

1. a bounded authenticated call;
2. a target-specific idempotency or unique run identifier;
3. a readback or target-system state;
4. a secret-free, SHA-256-bound receipt;
5. failure behavior that cannot be mistaken for success.

The connector implementations live in `src/remediation_connectors.py`; the transactional deployment
controller lives in `src/deployment_workflow.py`. Hermetic protocol and real subprocess tests live in
`tests/test_remediation_connectors.py` and `tests/test_deployment_workflow.py`.

## Validation levels

Connector status is reported at three distinct levels so a protocol test is never mistaken for a
customer-account result:

1. **Contract tested** — request shape, authentication placement, failure handling, secret
   redaction, receipt hashing, and readback logic passed against an injected transport.
2. **Provider authenticated** — the current account accepted a bounded capability check.
3. **Live action verified** — the provider accepted the explicit action and its resulting state was
   read back from that provider.

The release may prove one connector live without claiming that every optional provider has been
tested against an account. Each provider remains yellow until its own authenticated check or live
action has a receipt.

The GitHub adapter has a live provider receipt: it created a repair branch, committed the approved
hash-bound bytes, opened [PR #1](https://github.com/equinoxaifinance-rgb/lineage-detective/pull/1),
and read the pull request back as open. The dbt Cloud, Airflow, Fivetran, Snowflake, and hosted
DataHub Cloud adapters remain contract-tested until customer accounts are supplied.

## DataHub onboarding

- Local interactive users can choose **Sign in with DataHub OAuth**. Lineage Detective uses
  DataHub's global managed MCP endpoint, Dynamic Client Registration, PKCE, and a temporary
  loopback callback. Access and refresh tokens stay in memory.
- Hosted and unattended use accepts a scoped service-account token. This follows DataHub's
  documented recommendation for agentic/CI workflows and avoids storing users' OAuth refresh
  tokens in a shared container.
