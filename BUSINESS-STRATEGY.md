# Lineage Detective — business strategy

## The business in one sentence

Lineage Detective is the evidence-to-remediation layer for data incidents: it uses an existing
DataHub graph to find the likely failure, show the blast radius and owner, propose a constrained
repair, prove that repair in isolation, and carry the approved action into the system that owns it.

The contest is the launch event. The company-shaped product is the workflow that begins when a
data-quality alert appears and ends when a repair is independently verified and handed off or
implemented.

## Why this wedge exists

DataHub already provides discovery, lineage, assertions, ownership, and incident context. Its own
2026 product material describes root-cause analysis, blast-radius analysis, suggested actions, and
incident workflows as core observability jobs. It also describes more than 100 integrations and
native context from tools such as dbt, Airflow, Spark, and Snowflake.

That establishes the market need without pretending Lineage Detective replaces DataHub:

- [DataHub observability](https://datahub.com/products/data-observability/) covers detection,
  lineage-powered diagnosis, ownership, and incident context.
- [DataHub lineage](https://datahub.com/products/data-lineage/) supplies the dependency graph and
  downstream impact needed before a change.
- [DataHub MCP](https://docs.datahub.com/docs/features/feature-guides/mcp) exposes an official
  agent-facing route into that context.

Lineage Detective's wedge is the final operational mile: turn that context into a bounded,
reviewable, testable action while preserving a receipt for every claim.

## Initial customer

The first customer is not “everyone with data.” It is:

- a data-platform or analytics-engineering team already using DataHub;
- roughly 5–50 engineers or analysts, large enough for incidents and ownership handoffs to hurt;
- running dbt plus a warehouse and at least one orchestrator or ingestion service;
- responsible for business-critical dashboards, metrics, or AI data products;
- currently resolving incidents by moving manually between DataHub, source code, CI, warehouse,
  orchestration, and chat.

The first buyer is a head of data platform, analytics engineering lead, or data-reliability lead.
The daily user is the on-call data engineer.

## The job customers hire it for

> “A number is wrong. Tell me where it broke, what is affected, who owns it, what the safest fix is,
> whether that exact fix passes, and what happened after I approved it.”

Lineage Detective answers that job in one evidence chain:

1. Search a real DataHub tenant and select the affected asset.
2. Gather upstream lineage, ownership, schema, and operational evidence through DataHub MCP.
3. Rank only suspects that exist in the observed graph.
4. Optionally contain the confirmed incident and read the tags back.
5. Map downstream impact and owners.
6. Draft a constrained code or prevention change.
7. Run the exact proposed bytes in a disposable sandbox.
8. Verify rollback and seal a receipt.
9. With explicit approval, apply to a disposable copy, open a pull request, trigger validation, or
   run a customer-controlled deployment profile.
10. Read the downstream system back and preserve external IDs when verification is incomplete.

## Product editions

### Public proof edition

The contest release design is a restricted proof environment:

- fixed contest-owned DataHub tenant and managed-MCP origin;
- scoped server-side credentials;
- bounded judge reasoning access;
- demo assets and disposable workspaces;
- no customer production credentials;
- no arbitrary private destinations;
- downloadable evidence, sandbox, apply, restore, and handoff receipts.

This edition proves the workflow without turning a shared public process into a customer credential
broker. It is externally verified through the bundled isolated DataHub judge catalog,
seeded, deployed, and read back; that external gate is tracked in `LIVE-STATUS.md`.

### Self-hosted team edition

The commercial path runs inside the customer's environment:

- private or public DataHub tenant;
- checked-out repositories and customer tests;
- GitHub, dbt Cloud, Airflow, Fivetran, Snowflake, and DataHub assertion connectors;
- customer-defined deployment, live validation, rollback, and rollback-validation commands;
- secrets supplied through the customer's existing process or secret manager;
- audit receipts that omit credentials, raw commands, and raw provider errors.

The architecture does not require a customer to give a third-party SaaS unrestricted production
access on day one.

## Differentiation

Lineage Detective is not another catalog and not a general chat window.

| Alternative | What it does well | Lineage Detective's wedge |
|---|---|---|
| DataHub alone | Context, lineage, ownership, assertions, incidents | Closed-loop, receipt-bound repair and implementation |
| Generic coding agent | Edits code quickly | Grounds the action in the customer's lineage and incident evidence |
| Observability alert | Detects that something changed | Connects detection to root cause, blast radius, repair, and readback |
| Runbook or ticket | Preserves process | Executes the approved path and produces machine-verifiable receipts |
| Fully autonomous operator | Reduces clicks | Keeps explicit scope, drift checks, rollback, and customer-controlled credentials |

The defensible mechanism is not the mascot or interface. It is the chain of evidence boundaries:
observed URNs only, constrained proposals, exact-byte hashes, source-drift checks, isolated trials,
provider acknowledgement, independent readback, rollback, and secret-free receipts.

## Business-model hypotheses

Pricing is a hypothesis until customer interviews establish willingness to pay.

- **Team pilot:** fixed 30-day paid pilot covering one DataHub tenant, one repository, and one
  remediation connector.
- **Team subscription:** priced by connected DataHub tenant and active engineering team, not by
  every cataloged asset.
- **Enterprise:** annual self-hosted or VPC deployment, SSO/RBAC, audit retention, connector
  support, and service-level commitments.
- **Services:** optional incident-workflow mapping and custom connector implementation. Services
  should accelerate product adoption, not become the entire business.

Do not publish a price until five qualified buyers have reacted to the pilot scope and at least two
have discussed budget ownership.

## Go-to-market sequence

### Phase 1 — design partners

Recruit five DataHub users with a painful recent incident. The offer is not “try an AI agent.” It
is: “Give us one resolved incident and 45 minutes; we will reconstruct the evidence-to-fix path and
show where Lineage Detective would have removed manual work.”

Collect:

- minutes from alert to identified root cause;
- tools and handoffs used;
- time to identify the owner;
- time to propose and validate the repair;
- number of unsafe or unverified assumptions;
- whether the team would connect a read-only tenant and a test repository.

### Phase 2 — controlled pilots

For two design partners, run read-only investigation first. Add one write path only after the team
accepts the evidence quality. Start with GitHub pull requests or dbt Cloud validation because they
preserve review and already fit engineering workflows.

### Phase 3 — repeatable sale

Productize tenant setup, repository binding, connector permissions, policy profiles, receipt
retention, and outcome reporting. Publish case studies around incident time and verification, not
model novelty.

## North-star and guardrail metrics

North-star:

- median verified minutes from symptom to reviewable repair.

Supporting:

- percentage of investigations grounded entirely in observed DataHub entities;
- percentage that identify the accepted root cause in the top three;
- percentage of proposals that pass customer tests without manual rewriting;
- percentage of remote actions with independent readback;
- median owner-identification time;
- median blast-radius identification time;
- rollback success rate;
- repeat weekly use by on-call engineers.

Guardrails:

- zero production credentials in receipts or logs;
- zero silent remote partial failures;
- zero overwrites after source drift;
- zero “verified” claims without a bound receipt;
- explicit false-positive and insufficient-evidence rates.

## What must be proven before calling it a business

The software and contest entry can be real before the business is proven. Business proof requires
external behavior:

1. Five qualified discovery calls.
2. Two teams willing to connect a tenant in read-only mode.
3. One team willing to run a repair against a non-production repository.
4. One repeat user after the first incident.
5. A buyer who states who owns the budget and what outcome justifies payment.

Until then, the honest state is: working product and testable business strategy, not proven demand.

## Immediate launch plan

1. Finish and verify the restricted public judge path.
2. Publish the exact self-hosted quickstart and security boundary.
3. Submit the contest entry with the real-time product video.
4. Use the public result as the first credibility artifact, regardless of placement.
5. Recruit five design partners from the DataHub community and data-engineering networks.
6. Run incident-reconstruction interviews before adding more connectors.
7. Convert the strongest recurring workflow into the first paid pilot.
