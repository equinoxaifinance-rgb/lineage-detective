# 🕵️ Lineage Detective — Autonomous Data-Incident Root-Cause Agent

**Built with [DataHub](https://datahub.com) — driven through the DataHub **MCP Server** — for the
Build with DataHub: The Agent Hackathon.**

When a dashboard number looks wrong, a data team's first hour is spent *manually* clicking through
lineage asking "where did this break?" Lineage Detective does that investigation autonomously.

Search the connected DataHub in plain English, choose an affected asset, and describe the symptom.
It walks **upstream through DataHub's
lineage graph**, reads the real metadata at every hop (descriptions, custom properties, ownership,
schema), reasons over the evidence like an on-call engineer, returns a **ranked root-cause report
with the owner to contact**, and then **acts** — quarantining the root cause and tagging the whole
blast radius in the catalog — all **through DataHub's MCP Server**.

> **It never invents metadata.** Every fact in a report comes from DataHub (via MCP tools); the LLM
> only *reasons* over real evidence and is instructed to say when the evidence is insufficient
> rather than bluff.

The agent's investigation and containment operations are MCP-driven. One idempotent setup step
uses the official SDK only to create the two incident-tag definitions if a new catalog does not
already contain them; the agent itself does not use the SDK to read, diagnose, or tag assets.

---

## It's a DataHub *agent*: everything goes through the MCP Server

The DataHub **MCP Server** (`mcp-server-datahub`) is DataHub's agent-facing surface. Lineage
Detective launches it and speaks MCP over stdio for every investigation and containment operation:

| Step | MCP tool used | What it does |
|------|---------------|--------------|
| Discover | `search` | find real assets in the connected tenant; no hard-coded URN required |
| Sense (upstream) | `get_lineage` (`upstream=true`) | walk the lineage graph up from the symptom |
| Sense (detail)   | `get_entities` | pull owner / description / custom properties at each node |
| **Reason**       | *(frontier LLM)* | rank root-cause suspects over ONLY that evidence |
| Act (contain)    | `add_tags` | quarantine the root-cause node so consumers are warned |
| Map blast radius | `get_lineage` (`upstream=false`) + `add_tags` | find & tag every contaminated downstream asset |

Every write is **read back** (`get_entities`) to prove it persisted — the agent never claims an
action it can't confirm in the catalog.

## It works — live receipts across investigation, containment, and repair

Against a real DataHub instance, the agent correctly root-causes three *materially different*
failure types — a silent partial load, a schema-drift column rename, and a stale upstream feed —
each with the right owner to contact, then contains each in the catalog:

```
====================================================================
  LINEAGE DETECTIVE — Autonomous Data-Incident Report
====================================================================
Symptom  : Revenue Overview dashboard shows a ~40% drop in daily revenue, no pipeline errors.
Traced   : 4 upstream entities via DataHub lineage (MCP get_lineage)

SUMMARY
  The 40% revenue drop matches an ingestion anomaly at the raw orders source: prod.raw.orders
  loaded 61,240 rows versus a 101,800 seven-day baseline (about 40% lower), while its run status
  remains successful and no volume test is configured. stg_orders is a 1:1 passthrough and
  fct_revenue is a simple sum with no volume test, so the shortfall can pass silently into the
  dashboard.

ROOT-CAUSE SUSPECTS (ranked)
  1. [!!!] [HIGH] prod.raw.orders   → contact: alice@data-eng
       why : 61,240 rows loaded versus a 101,800 seven-day baseline, combined with a successful
              status and no configured volume test, matches the magnitude of the reported drop.
       next: Confirm the source extract and row-count history, then run the governed backfill.

ACTION TAKEN (autonomous write-back to DataHub, via MCP add_tags)
  [OK] APPLIED: tagged prod.raw.orders 'QUARANTINE_INCIDENT' — downstream consumers now warned.

BLAST RADIUS — 3 downstream assets contaminated (3 tagged IMPACTED)
  dashboards affected: bi.revenue_overview
  data assets affected: analytics.staging.stg_orders, analytics.marts.fct_revenue
====================================================================
```

Reproduce the live catalog proofs yourself: `python prove_scenarios.py` exercises three materially
different incident classes (partial load, schema drift, stale feed), and
`python tools/prove_writeback.py` performs a clean-slate → agent containment → independent MCP
read-back. Both require the local DataHub demo and a valid `ANTHROPIC_API_KEY`; results can vary
when a model is unavailable, so neither script converts a failed run into a claim.

Current executed repair artifacts are in [`examples/generated`](examples/generated/), with a
machine-verified manifest of every file hash. The independent review/fix ledger is
[`COUNCIL-REMEDIATION.md`](COUNCIL-REMEDIATION.md), and the full executed release matrix is
[`RELEASE-VERIFICATION.md`](RELEASE-VERIFICATION.md).

Every bundled incident reaches an evidence-appropriate code-change path. Schema drift gets a
corrective dbt-model diff. A silent partial load gets a volume guard; a frozen FX feed gets a
freshness guard. The latter two do not pretend downstream SQL can recreate missing source data:
they convert silent bad-data runs into explicit failing dbt tests while containment and owner
handoff address the upstream outage. Clicking the sandbox action explicitly approves the exact
displayed diff. The trial writes and executes that artifact only inside the bundled DuckDB
sandbox, checks a real incident-specific assertion, and verifies rollback afterward. Once the
receipt is green, the human can download the evidence packet or apply the same hash-bound SQL to a
chosen checked-out `.sql` artifact. The apply path writes atomically, creates a sibling backup,
reads the result back by SHA-256, rolls back automatically on failure, and offers a verified
restore without overwriting a later human edit.

The examples are not the product boundary. **My own DataHub incident** searches the connected
tenant through MCP, accepts arbitrary symptom text, and investigates any selected asset. When the
machine running Lineage Detective also has the affected checked-out dbt `.sql` file, the user can
attach that real artifact. The model proposes a diff constrained to the returned evidence and the
file's existing relation scope. The generic verifier rejects write-capable SQL and new
`ref()`/`source()` relations, verifies exact bytes and single-statement parsing in a disposable
workspace, and can atomically apply or restore the hash-bound file. This generic path proves
structural safety and artifact integrity; business correctness still requires the target
repository's own fixtures and tests. The three bundled cases retain stronger incident-specific
semantic assertions.

The default judge walkthrough exposes that complete path as **one approved run**. The user chooses
the asset, symptom, target, containment setting, and finish action, then clicks
**Approve & run full verified workflow**.
The app continuously shows the real stage it is executing while it investigates live lineage,
reads back containment writes, drafts the evidence-bound repair, proves the exact bytes in the
sandbox, applies them to the selected safe target when requested, and prepares the handoff packet.
The same button becomes **Cancel current run** while work is active; if it is not pressed, the
workflow proceeds uninterrupted to its selected finish. Cancellation is cooperative at real stage
boundaries and clears partial UI state rather than presenting an incomplete run as success.

For reviewers who want individual decision points, **Manual mode & advanced settings** restores the
separate investigation, sandbox, apply, restore, connector, and handoff actions. The autonomous
path does not remove any safety check: it records the user's displayed scope as the approval, gives
every run its own disposable workspace, requires both verification and confirmed rollback,
validates the receipt hash, and refuses to apply or export downstream work if any bound receipt
field fails. It also rejects implementation when the selected source file changed after the
proposal was created.

## Code map

- **`src/datahub_mcp.py`** — the MCP connection. Launches `mcp-server-datahub`, holds one MCP
  session open on a dedicated worker thread, and exposes `search` / `get_lineage` /
  `get_entities` / `add_tag`.
- **`src/datahub_evidence.py`** — the agent's senses. Turns MCP `get_lineage` + `get_entities`
  output into the evidence the LLM reasons over. No metadata invented.
- **`src/act.py`** — the agent's hands. Quarantines the root cause and tags the blast radius via
  the MCP `add_tags` tool, reading each write back to confirm it stuck.
- **`src/agent.py`** — the investigator. `investigate(symptom, affected_urn, act=True)` → gather
  evidence (MCP) → LLM reasoning → strict-JSON report → contain (MCP) → `render_report()`.
- **`src/repair.py`** — the repair boundary. It proposes a constrained corrective model diff,
  incident-specific volume/freshness guard, or evidence-bound change to a user-selected dbt SQL
  file. It validates the artifact as read-only, runs the approved diff in a disposable dbt +
  DuckDB sandbox, and can atomically apply the verified bytes to a human-selected checked-out
  artifact with hash-bound apply and restore receipts.
- **`src/autonomous_workflow.py`** — the one-approval orchestrator. It creates the verified handoff
  before touching a selected target, then performs the optional exact-byte apply. A failed,
  tampered, cleanup-incomplete, or source-drifted stage blocks implementation and returns a
  structured receipt.
- **`src/network_policy.py`** — the shared hosted-network boundary. It requires public HTTPS,
  rejects embedded credentials and nonstandard ports, checks every DNS answer for private/local
  addresses, and rechecks resolution immediately before credential-bearing requests.
- **`repair_sandbox/`** — the deliberately broken dbt project used by the isolated repair trial.
- **`tests/`** — hermetic tests for malformed reasoning recovery, unsafe repair rejection,
  explicit-action boundaries, real assertion flip, rollback failure, receipt tampering,
  concurrent-run isolation, exact-byte apply and restore, later-human-edit protection, hosted
  network restrictions, timeout recovery, and missing-sandbox failure.
- **`src/graph_viz.py`** — visualization only (fail-open). Re-walks lineage via MCP `get_lineage`
  to recover the real edges and renders the graph the agent walked, root cause and blast radius
  lit up. A failure here never affects the investigation.

## DataHub features used
DataHub **MCP Server** (`search`, `get_lineage`, `get_entities`, `add_tags`) · asset discovery · bidirectional lineage
traversal · entity metadata (ownership, description, custom properties, schema) · catalog
write-back (tags) · approval-gated dbt/DuckDB repair sandbox · human-directed checked-out-model
implementation with backup and hash readback. The app does not claim a DataHub production-repair
API: DataHub grounds the diagnosis and containment; implementation changes only the exact local
file the human selects.

## Quickstart — one command

**Prerequisite:** Docker Desktop running. **No personal provider API key is required to test the judge build.**
Without `ANTHROPIC_API_KEY`, the app runs an honest, read-only **evidence-only mode**: it connects
to the real local DataHub through the official MCP server and deterministically ranks observable
volume, freshness, and null-rate anomalies. It does not claim model reasoning or permit catalog
writes in that mode. For the complete judge path, the deployed **judge gateway URL is preloaded**;
enter the separately supplied **judge access code** in the sidebar. That route enables live model-backed reasoning,
containment, and repair proposals without placing any provider key in the repository, browser,
ZIP, or local environment. The access code is a bounded, rate-limited invitation credential, not
an API key; the provider key remains an encrypted Cloudflare Worker secret.
The secret-free submission checklist is in [`JUDGE-ACCESS-HANDOFF.md`](JUDGE-ACCESS-HANDOFF.md).

```bash
# Windows:  double-click run.bat   (or:  python quickstart.py)
# macOS / Linux:
./run.sh                                     # or:  python3 quickstart.py
```
`quickstart.py` creates an isolated project `.venv`, installs checked-in SHA-256 hash-locked dependencies there, brings up a local DataHub, plants the demo
incidents, and launches the web app at http://localhost:8501 — then you just describe a symptom and
click **Investigate**. For the schema-drift sample, the UI shows a diff first; a separate explicit
approval is required before it may run one isolated repair trial. It's safe to re-run; each step is
skipped if already done.

### Hosted DataHub Cloud path

The same application is deployed at
**https://lineage-detective.equinoxaifinance.workers.dev** in a Cloudflare Container. It defaults
to DataHub Cloud's managed streamable-HTTP MCP endpoint. Enter a tenant URL and a scoped DataHub
service-account token; the token stays in the active Streamlit session and is not written to the
repository or a receipt. The hosted path requires public HTTPS for DataHub and connector endpoints,
rejects embedded credentials and nonstandard ports, and rejects DNS answers that resolve to local
or private network addresses. Credential-bearing requests do not follow redirects. Use local
quickstart when the DataHub or Airflow endpoint is private.

The hosted URL is not represented as a shared fake catalog. It performs real work only after it is
connected to a real DataHub Cloud tenant. The one-command local path remains the credential-free
way to reproduce the bundled incidents against a real local DataHub deployment.

**Safe judge default:** Evidence-only mode starts read-only. With a local provider key or
supplied judge gateway access, containment is enabled by default; uncheck it for a read-only
model-backed investigation. Every requested tag is read back through MCP
before the UI calls it confirmed. During investigation, **Trace**, the stationary droid, performs a subtle
evidence scan: its lens pulses, a beam sweeps, and evidence nodes illuminate while the adjacent
text reports real callbacks from connection, lineage, reasoning, and readback. The sandbox uses
its own real reset/seed/baseline/rewrite/verification/rollback milestones. These are activity
indicators, not fabricated countdowns.

The startup chooses the secure DataHub toolchain automatically: it uses a unified fixed runtime only
when both DataHub's published dependency metadata **and** a reviewed matching hash lock permit it;
otherwise it routes only the official DataHub CLI/SDK/MCP process through an isolated compatibility
environment. The agent behavior and available MCP tools are identical in either route. See
[COMPATIBILITY.md](COMPATIBILITY.md) and [SECURITY.md](SECURITY.md) for the exact boundary and
verification rules.

<details><summary>Manual steps (if you'd rather run them yourself)</summary>

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
python -m pip install --require-hashes -r requirements-runtime.lock
# Let quickstart choose the official MCP route, install its separate sidecar,
# start DataHub, and seed the incidents. It never installs into global Python.
python quickstart.py
# It launches the UI after setup. For a one-off CLI run in another terminal:
export ANTHROPIC_API_KEY=...               # the reasoning model
export DATAHUB_GMS_URL=http://localhost:8080
python src/agent.py "the revenue dashboard dropped 40%, no errors" \
  "urn:li:dataset:(urn:li:dataPlatform:looker,bi.revenue_overview,PROD)" --act
```
</details>

The agent uses the pinned official DataHub MCP server (`mcp-server-datahub==0.6.0`) selected by
quickstartâ€”in the fixed app runtime when upstream supports it, otherwise in the isolated sidecar.
Advanced users can set `DATAHUB_MCP_CMD` to override its launch command. On DataHub Cloud, point
`DATAHUB_GMS_URL` / `DATAHUB_GMS_TOKEN` at your tenant instead.

For DataHub Cloud v0.3.12+, select **DataHub Cloud managed MCP** in the app. The app derives the
tenant’s `/integrations/ai/mcp/` streamable-HTTP endpoint and sends the scoped service-account token
in the Authorization header. DataHub recommends service accounts for unattended agentic workflows;
interactive personal clients can instead use DataHub’s OAuth + Dynamic Client Registration endpoint.
When the app runs locally, **Sign in with DataHub OAuth** performs that DCR flow through DataHub's
global managed MCP endpoint and a temporary loopback callback; the resulting token stays in the
Streamlit session and is never written to disk. The public multi-user deployment deliberately uses
the service-account path instead of persisting individual OAuth refresh tokens.

## Use it on your own DataHub (not just the demo)
The seeded incidents are only a guaranteed showcase — **the agent is not hardcoded to them.** Point
it at *any* asset in *any* DataHub and it investigates the real lineage and metadata there:
```bash
python src/agent.py "<your symptom in plain English>" "<any dataset/dashboard URN>" --act
```
To ask for a constrained repair against a real checked-out dbt model, add
`--repair-file path/to/model.sql`. The CLI returns a reviewable proposal; use the app to inspect the
exact diff, run the isolated trial, and explicitly apply or export it.

After a sandbox receipt is verified, the app can continue into a real target system: open a GitHub
pull request, trigger dbt Cloud or Airflow validation, pause/resume/sync Fivetran, execute one
reviewed Snowflake statement, create a DataHub Cloud freshness, volume, or custom-SQL assertion, or run a customer project
test command. Each adapter requires the customer’s scoped credential and returns a secret-free
receipt. See [UNIVERSAL-REMEDIATION.md](UNIVERSAL-REMEDIATION.md).

It reasons only over what the catalog actually holds: rich metadata (run notes, descriptions,
ownership) yields a sharp, high-confidence root cause; a sparse catalog yields ranked suspects plus
an honest "insufficient evidence — check X" rather than a bluff. The incident-tag vocabulary
(`QUARANTINE_INCIDENT` / `IMPACTED_BY_INCIDENT`) is **created automatically on your instance** the
first time you run with `--act` (or launch the app) by a create-if-missing setup helper using the
official SDK; the agent itself still acts through the MCP `add_tags` tool. Verified on incident types it had
never seen, including a root cause buried mid-chain (not the obvious raw source).

## Why it's original
Not a data catalog, not a chatbot over docs — an **autonomous investigator** that drives DataHub's
own MCP tools to turn lineage + metadata into *answered, contained* incidents. Data-observability
vendors sell exactly this triage as a product; here it's an open MCP agent anyone can point at their
own DataHub.

## A note from the builder
I'm the AI that built this — every line of code, the tests, the demo video, and this README —
working autonomously for the founder who imagined it. Built entirely during the submission
period, disclosed per the rules.

I built the agent to separate evidence, action, and claim: DataHub facts are gathered through MCP;
containment writes are read back before they are announced; and a suggested repair remains a proposal
until a human explicitly runs its isolated sandbox trial. A sandbox pass is not presented as a
production guarantee. After it passes, the human can apply those exact verified bytes to a selected
checked-out model with a backup and hash readback, or export the handoff. The reproduction commands
above are the receipts, not a substitute for running them.

An agent, that built an agent — for an agent hackathon.

## Provenance & disclosure
Newly created during the hackathon submission period (July 2026). Built with standard, publicly
available tools only — the DataHub SDK/CLI (`acryl-datahub`), the pinned official DataHub MCP server
(`mcp-server-datahub`), the MCP client SDK (`mcp`), the Anthropic SDK, and Streamlit. No
pre-existing or proprietary code was incorporated.

## Also ships a DataHub Skill (open-source contribution)
Beyond driving the MCP Server, this repo contributes a **DataHub Skill** in the official
[`datahub-skills`](https://github.com/datahub-project/datahub-skills) format:
[`skill/datahub-incident-response/SKILL.md`](skill/datahub-incident-response/SKILL.md). It packages
the investigate → root-cause → **contain** → map-blast-radius loop as a reusable recipe over the
DataHub MCP tools (`get_lineage` / `get_entities` / `add_tags`) — the containment-grade sibling of
the existing read-only `datahub-lineage` skill, offered upstream. So Lineage Detective exercises
**two** of the hackathon's DataHub agent surfaces: the **MCP Server** (the running agent) and a
**DataHub Skill** (the reusable recipe).

## License
Apache-2.0 — see [LICENSE](LICENSE).
