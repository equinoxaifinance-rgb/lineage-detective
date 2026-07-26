# Release Verification — 2026-07-26

This is an execution log, not a promise about future external services.

## Executed receipts

| Surface | Command / action | Observed result |
|---|---|---|
| Source syntax | `python -m compileall -q app.py src tests quickstart.py tools` | exit 0 |
| Hermetic suite | `py -3.11 -m unittest discover -s tests -v` | 109 passed, 0 failed in 48.024 seconds |
| Rollback fail-closed regression | successful assertion followed by forced rollback failure | receipt downgraded to `sandbox_failed`; apply and handoff both rejected it |
| Concurrent-run isolation | eight simultaneous custom repair trials using the default template | eight distinct OS temporary workspaces; all eight verified, rolled back, and were removed |
| Source-drift conflict | selected SQL changed after proposal generation | apply rejected the stale proposal before backup or write; later human bytes were preserved |
| Handoff-before-write journal | forced handoff packaging exception with an eligible apply target | exception occurred before the applier was called; target remained untouched |
| Hosted network policy | public HTTPS, private DNS, loopback, link-local, userinfo, HTTP, and nonstandard-port cases | public HTTPS accepted; every hosted private/local/credential-bearing invalid target rejected |
| Executed examples | `python tools/verify_release_examples.py` | 3 cases verified; every standalone artifact and handoff ZIP hash/CRC matched its manifest and receipt |
| Universal-remediation protocols | `python -m unittest tests.test_remediation_connectors -v` | GitHub PR, dbt Cloud run, Airflow DAG run, Fivetran pause/resume/sync, one-statement Snowflake, three DataHub assertion types, customer command, failure receipts, and hosted SSRF boundaries passed |
| Live GitHub connector | product `GitHubPullRequestConnector` against `equinoxaifinance-rgb/lineage-detective` | branch created, hash-bound bytes committed, PR [#1](https://github.com/equinoxaifinance-rgb/lineage-detective/pull/1) opened, and PR read back as open; independent GitHub API readback matched commit `5060247a8c9f3eae554f574bf17ff8033076e59f` and content SHA-256 `a34920ad06a737c59e746e7ca6cf6fd707e0d2d48b5b322ea6e9485cef0daa4c`; connector receipt SHA-256 `eed8fc75982290fc014670f33d848f7fb4c5f48e16131c4b0a11f34d1c3fa484` |
| DataHub Cloud vocabulary fallback | `python -m unittest tests.test_setup_vocab -v` | existing-tag, create-and-readback, and false-success rejection paths passed |
| Interactive DataHub OAuth contract | `python -m unittest tests.test_datahub_oauth -v` | in-memory token/client storage and official global managed-MCP endpoint contract passed; live consent remains user-driven |
| Boundary shape | `python tools/verify_security_boundary.py` | pass; no packaging inputs; direct pins and both SHA-256 hash locks present |
| Clean runtime install | disposable Python 3.11 virtual environment + `pip install --require-hashes -r requirements-runtime.lock` | installed from the lock, `pip check` passed, and `streamlit`, `anthropic`, `mcp`, and `duckdb` imported successfully |
| Clean sidecar install | disposable Python 3.11 virtual environment + `pip install --require-hashes -r requirements-datahub-sidecar.lock` | installed from the lock, `pip check` passed, and `datahub` plus `mcp_server_datahub` imported successfully |
| Judge-facing runtime | `.venv: pip check` and `python -m pip_audit --strict` | both exit 0; no known vulnerabilities reported |
| Linux release image | `docker build --platform linux/amd64 -t lineage-detective:final .` | hash-locked image built; the first build exposed and fixed an unconditional Windows-only `pywin32` lock entry |
| Packaged release execution | `lineage-detective:release-candidate` on Linux/amd64 | exact candidate image digest `sha256:f67902d39550812fecb455c2cd932db8d4c525bba4f405e3adc6dd57b0f5132f`; `pip check` passed; all 109 tests passed in 28.779 seconds; all 3 example cases and every bound artifact verified |
| Hosted Cloudflare release | `wrangler deploy`, `wrangler containers list`, independent HTTPS request | container application became active with 2 instances; the public URL returned HTTP 200 |
| Hosted visible UI | fresh in-app browser load of `https://lineage-detective.equinoxaifinance.workers.dev` | title and Lineage Detective heading rendered; DataHub Cloud managed MCP was the default; tenant URL, scoped-token, judge-gateway, and investigation controls rendered |
| Release secret scan | tracked and untracked text artifacts, checking recognizable Anthropic, AWS, and GitHub token forms | no matches found |
| DataHub sidecar | `.datahub-mcp-venv: pip check` | exit 0 |
| Sidecar security scan | `.venv: pip_audit --path .datahub-mcp-venv/Lib/site-packages --strict` | one known upstream distribution: `setuptools 81.0.0`, reported twice as `PYSEC-2026-3447` |
| Forced compatibility probe | disposable environment with `acryl-datahub 1.6.0.15`, `mcp-server-datahub 0.6.0`, forcibly upgraded to `setuptools 83.0.0` | `pip check` correctly failed the declared `<82` requirement; DataHub CLI/SDK imports and an actual MCP lineage read succeeded on this Windows/local-DataHub run |
| Bridge readback | fixed runtime (`setuptools 83.0.0`) to isolated official MCP sidecar | live MCP readback: 3 lineage entities, 1 entity response, 6 tools exposed |
| Progress contract | live DataHub + live model diagnosis, no containment write | six emitted checkpoints; 4 evidence nodes and 3 suspects returned |
| Live tenant asset discovery | custom-incident browser path + official MCP `search` against local DataHub | plain-language `customer` query returned 6 live catalog results; the selector displayed the real asset name and URN |
| Visible custom-incident path | arbitrary plain-English symptom entered in the browser against a live search-selected URN | traced 4 live DataHub entities; quarantine readback confirmed; 2 downstream impact-tag writes confirmed; exact reviewable repair rendered |
| Custom incident + checked-out repair | non-example symptom and affected asset + live DataHub + live model + real checked-out dbt file | traced 3 evidence nodes and ranked 3 suspects; produced `custom_dbt_sql_repair`; exact candidate passed structural sandbox and rollback; disposable apply hash matched; restore returned the original bytes; receipt SHA-256 `f2b5b25ac741ec99bde4815ac4f1fba910dc235e67a308729af66794ca5d252b` |
| Browser judge path | fresh Streamlit session, containment left unchecked | animated evidence stage advanced from MCP connection to completed report; 4 real entities traced; no containment write requested |
| Free judge path | fresh Streamlit process with `ANTHROPIC_API_KEY` absent | containment control disabled; live MCP investigation ranked `prod.raw.orders` from its observed 40% volume delta and labeled the result evidence-only rather than model reasoning |
| Free judge scenario path | three live local DataHub incidents, no model key | 3/3 deterministic diagnoses: `prod.raw.orders`, `analytics.staging.stg_customers`, and `prod.ref.exchange_rates`; no catalog action was requested or performed |
| Judge gateway static deployment check | `node --check` + `wrangler deploy --dry-run` | Worker source parsed; Worker binding shape validated: encrypted secret boundary, Rate Limit binding, and Durable Object budget guard |
| Judge gateway live boundary | `GET /health`, unauthorized request, authorized model request | health returned 200; missing code returned 401; authorized request returned provider-generated JSON without exposing the provider credential |
| Judge gateway durable availability | `wrangler deployments list`, `wrangler secret list`, live health request, and a fresh authorized `/reason` probe | active deployment present; encrypted `ANTHROPIC_API_KEY` and `JUDGE_CODE` bindings present; health returned 200; bounded request returned exactly `GATEWAY_OK`; provider credential never entered the app, browser, repository, or command output |
| Full judge gateway investigation | local DataHub schema-drift incident, provider key absent from app process | 4 live evidence nodes; `model_backed_judge_gateway`; 3 suspects; repair proposal reached `approval_required` |
| Full judge gateway containment | local DataHub schema-drift incident, containment enabled | incident vocabulary provisioned; quarantine applied to `analytics.staging.stg_customers`; 2 downstream assets tagged; fresh independent MCP entity read confirmed the quarantine tag |
| Stalled-MCP recovery | deliberately nonresponsive MCP child process | startup produced the explicit retryable timeout in under 4 seconds rather than leaving the UI at Connecting; child cleanup was inspected afterward |
| Post-startup MCP recovery | a real protocol-speaking test MCP initialized normally, then ignored a tool call | tool call produced the explicit retryable timeout in under 4 seconds rather than leaving the UI at Reading lineage |
| Evidence-card safety | unit contract for catalog/model text rendered into HTML cards | asset label, owner, evidence, and next-check strings are HTML-escaped before interpolation |
| Responsive UI | current final browser state at 390x844 and default desktop width | document, body, and viewport widths all measured 390 px with no horizontal overflow; sidebar collapsed; diff and action surfaces remained usable |
| Complete judge repair path | fresh Streamlit session using the default schema-drift walkthrough | live investigation traced 4 DataHub entities, confirmed quarantine plus 2 impact-tag writes, produced a constrained model rewrite, and the explicit sandbox action ran 0/8 failing assertions to 8/8 passing assertions with rollback confirmed |
| Stale-feed write path | browser-selected Finance incident, live DataHub + local model key | traced 3 entities; confirmed quarantine plus 2 impact writes; produced `tests/exchange_rates_freshness_guard.sql`; sandbox detected the seeded six-day stale feed and verified rollback; safe-demo apply SHA-256 `5b4dda12e9325b343d13a220beea46e35b45f81bc89fd0b371867690916e86e8` matched the proposal; restore returned the original 70-byte artifact and backup count to zero |
| Partial-load write path | browser-selected Revenue incident, live DataHub + local model key | traced 4 entities; confirmed quarantine plus 3 impact writes; produced `tests/orders_ingestion_volume_guard.sql`; sandbox detected the seeded 44% volume shortfall and verified rollback |
| Checked-out-file implementation | browser-selected disposable `.sql` model followed by independent file inspection | exact sandbox-approved proposal was written; target SHA-256 `b4e321e471bb5c46533ef60caa410b7e703f84230d6622b2804fbb9c6e54e4b5` matched the proposal; one backup existed with original SHA-256 `55c07c97cb7b39444e20d902158a8a687dde824efa68d362b93059c386e9457b` |
| Verified restore | browser restore action followed by independent file inspection | original SHA-256 `55c07c97cb7b39444e20d902158a8a687dde824efa68d362b93059c386e9457b` returned; verified mapping was absent; backup count returned to zero |
| Restore-state UI readback | final patched browser run after verified restore | restored-state explanation and restore receipt were visible; stale applied-success banner and restore button were absent; workflow returned to the apply-or-handoff choice |
| Apply/restore hostile paths | hermetic write-failure, restore-failure, later-edit, and receipt-tamper tests | apply failure returned a receipt and restored the original; restore failure preserved the backup; later human edits were not overwritten; tampered receipts were rejected |
| Browser diagnostics | current final desktop and 390x844 runs | 0 console errors; GraphViz reported its non-blocking main-thread worker fallback, and the deliberate app restart produced one WebSocket-close warning |
| Downloaded handoff artifact | browser download followed by independent ZIP and JSON inspection | 4 entries present (`README.md`, exact diff, proposed model, sandbox receipt); embedded receipt reported `sandbox_verified`, before fail, after pass, and rollback verified |
| Handoff integrity | downloaded ZIP and embedded receipt hashed independently | ZIP SHA-256 `FE1EDFF52E3D2E6253BFEA92F82077414358FF8077A73AC71EF835C9EF0F29A9`; receipt SHA-256 `a616d5e27913f4990364ecdf32bc27b26f5a5fca9dc0991e74f2db311112d4cd`; proposal SHA-256 `32cc5e84c88fc4cff8ed51ed5638e518a39c47f6688890ed18ee1eadf6dbb070` |
| Current browser receipt download | real `Download JSON receipt` click followed by independent JSON parse and hash recomputation | browser download event fired; 3,534-byte JSON parsed; state `sandbox_verified`; `verified=true`; `rollback_verified=true`; embedded receipt SHA-256 recomputed successfully |
| Current browser handoff download | real prepare + ZIP download clicks followed by independent archive and content verification | browser download event fired; 2,701-byte ZIP passed CRC; exactly 4 entries present (`README.md`, exact diff, proposed model, sandbox receipt); embedded receipt hash and proposed-model hash both recomputed successfully |
| Custom checked-out-model UX | browser switched from safe demo to custom target, exercised blank target, then used an existing `.sql` file | apply remained selectable; blank target returned actionable host-path guidance; valid path was detected; apply succeeded with hash readback and restore remained available |
| Disposable workspace recovery | prior interrupted demo apply followed by `Load the complete rewrite walkthrough` and independent filesystem inspection | the reset touched only `.lineage-detective-demo`; known-broken model SHA-256 returned to `3D6189E222BF7AD1892763FC7BDE18A5E87EE8E368D90E4FF8587CB1838D6FE7`; orphan demo backup count returned to zero |
| Warm URL render | browser reload to visible `Lineage Detective` heading | 669 ms observed; a roughly two-second first open remains ordinary Streamlit/browser initialization rather than application-work latency |
| Activity UI contract | live desktop investigation, source contract, and recorder gate | the title owns one compact Trace mascot; the approval area owns one and only one execution rail; its copy and percentage are driven by real connection, evidence, diagnosis, containment, sandbox, apply, and handoff callbacks; the recorder rejects a missing, duplicated, backward-moving, under-sampled, or non-100-percent rail; reduced-motion CSS disables nonessential animation |
| Named wait-state and one-click demo implementation | fresh browser run through live investigation, sandbox, apply, independent file readback, restore, and second readback | Trace owned the sandbox phase copy; no expanding status transcript remained; default safe-demo apply control was enabled; sandbox measured 0/8 to 8/8; applied file SHA-256 `9EB595363DA5691DCD8332C619C30511316E97BCD51534ED9864C75ADFC28C3B` matched the approved proposal; exactly one backup existed; restore returned original SHA-256 `3D6189E222BF7AD1892763FC7BDE18A5E87EE8E368D90E4FF8587CB1838D6FE7`; backup count returned to zero |
| Autonomous orchestration contract | `python -m unittest tests.test_autonomous_workflow tests.test_ui_contract -q` plus full suite | one displayed approval ran sandbox → handoff prebuild → optional exact-byte apply; failed rollback, invalid receipt hash, handoff failure, and missing approval blocked implementation; the primary control changed to Cancel only while active |
| Live optional-cancel path | fresh local browser session, start one-click workflow, press `Cancel current run` during live MCP investigation | returned to the start state; generated diagnosis and partial result state were absent; no failure or success was reported |
| Live uninterrupted one-click path | fresh local browser session, select safe-demo finish, press Start once, do not intervene | real DataHub investigation traced 4 entities; containment and 2 impact writes were read back; sandbox changed 0/8 failing assertions to 8/8 passing and confirmed rollback; exact bytes were applied; implementation receipt and verified handoff downloads rendered |
| Autonomous exact-byte readback | independent filesystem inspection after the uninterrupted browser run | target `.lineage-detective-demo/models/stg_customers.sql` SHA-256 `b4e321e471bb5c46533ef60caa410b7e703f84230d6622b2804fbb9c6e54e4b5` matched the displayed proposal; exactly one backup existed with SHA-256 `3d6189e222bf7ad1892763fc7bde18a5e87ee8e368d90e4ff8587cb1838d6fe7` |
| Manual-mode preservation | fresh browser state toggled `Pause for review at every stage` | the autonomous Start control was replaced by the manual investigation control; separate later-stage actions remained available; toggling back restored the one-shot path |
| Judge video release artifact | real Chrome/Streamlit run, event-timed narration, full decode, loudness scan, 12-frame contact sheet, exact key-frame inspection, and independent transcription | 148.100 seconds; 1920x1080 30 fps H.264 + AAC; both streams decoded without error; -16.3 LUFS / -1.4 dB true peak; timeline captured 12 monotonic progress values from 10 through 100 percent; transcript preserved all load-bearing claims and the human/AI authorship note; SHA-256 `b3d7a8595b232e0b08620ee31991cd832e3c333b644ff87f77274363cc666856` |
| Earlier scenario suite | `prove_scenarios.py` against local DataHub | 3/3: partial load, schema drift, and stale feed reached the expected action locus |
| Earlier containment proof | `tools/prove_writeback.py` | root quarantine and 3 downstream impact tags independently read back through MCP |
| Earlier repair proof | fresh Streamlit path + sandbox trial | proposal stayed approval-gated; approved isolated trial changed 0/8 to 8/8 and rollback was confirmed |

## Security interpretation

`PYSEC-2026-3447` is **not false**: current DataHub metadata requires
`setuptools<82`, while the advisory fix is `>=83`. It is also not a demonstrated
failure of this application's Windows/local DataHub operations: the forced
runtime test completed real MCP reads. That is evidence for this tested path,
not proof that `setuptools 81` is safe on every operating system or packaging
workflow.

The application therefore keeps the audited judge-facing runtime on the fixed
version and automatically routes only the current DataHub CLI/SDK/MCP chain
through an isolated sidecar. The sidecar carries the upstream condition openly.
See [SECURITY.md](SECURITY.md) and [COMPATIBILITY.md](COMPATIBILITY.md).

## Deliberate product boundaries

- A repair proposal does not write or execute before explicit approval.
- After sandbox verification, target-system connectors still require their own explicit action and
  return a secret-free receipt. A queued external job is called a verified initiation, not a
  completed production repair.
- The hosted app rejects connector URLs that resolve to private, loopback, link-local, reserved, or
  multicast addresses. Local installs may explicitly reach private customer infrastructure.
- Interactive DataHub OAuth uses DCR and a temporary loopback callback only in the local app; tokens
  remain in memory. Hosted/unattended use follows DataHub's service-account-token recommendation.
- Unsafe generated SQL is rejected before the sandbox.
- Missing sandbox is a recoverable failure, not a silent success.
- An approved trial uses an isolated dbt + DuckDB sandbox and restores the broken
  fixture afterward. Only a separate explicit action can apply the exact verified
  bytes to a human-selected checked-out `.sql` file; it creates a backup, verifies
  the post-write hash, rolls back on failure, and refuses to overwrite later edits.
- The UI shows actual investigation and sandbox milestones rather than a silent spinner or
  fabricated countdown. One action-local rail stays beside the approval point and advances only
  from real callbacks; Trace reaches handoff only after the bound workflow completes.
- Evidence-only mode is read-only. With a configured local key or judge gateway, containment is enabled by default and can be unchecked for a read-only model-backed investigation.
- No-key judge mode remains real: it reads the local DataHub through MCP and applies disclosed deterministic evidence checks. It is read-only and is not represented as a substitute for model-backed reasoning.
- The judge gateway holds the provider credential only as an encrypted Worker secret. It accepts a separate access code, fixes the model/output ceiling, rejects oversized requests, rate-limits each IP/code, and has a strongly consistent whole-gateway daily request cap.
- Both application and DataHub-sidecar dependency graphs are hash-locked; bootstrap uses `pip --require-hashes`.
- Bootstrap has no separate unhashed pip-upgrade step. The future unified route refuses to install unless it has a reviewed matching hash lock.
- A nonresponsive MCP server has a bounded startup timeout and a clear retryable error.
- `quickstart.py` stops on failed dependency installation or `datahub docker
  quickstart`; it does not print an unchecked success.
