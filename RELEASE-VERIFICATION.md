# Release Verification — 2026-07-25

This is an execution log, not a promise about future external services.

## Executed receipts

| Surface | Command / action | Observed result |
|---|---|---|
| Source syntax | `python -m compileall -q app.py src tests quickstart.py tools` | exit 0 |
| Hermetic suite | `python -m unittest discover -s tests -v` | 27 passed, 0 failed |
| Boundary shape | `python tools/verify_security_boundary.py` | pass; no packaging inputs; direct pins and both SHA-256 hash locks present |
| Clean runtime install | disposable Python 3.11 virtual environment + `pip install --require-hashes -r requirements-runtime.lock` | installed from the lock, `pip check` passed, and `streamlit`, `anthropic`, `mcp`, and `duckdb` imported successfully |
| Clean sidecar install | disposable Python 3.11 virtual environment + `pip install --require-hashes -r requirements-datahub-sidecar.lock` | installed from the lock, `pip check` passed, and `datahub` plus `mcp_server_datahub` imported successfully |
| Judge-facing runtime | `.venv: pip check` and `python -m pip_audit --strict` | both exit 0; no known vulnerabilities reported |
| Release secret scan | tracked and untracked text artifacts, checking recognizable Anthropic, AWS, and GitHub token forms | no matches found |
| DataHub sidecar | `.datahub-mcp-venv: pip check` | exit 0 |
| Sidecar security scan | `.venv: pip_audit --path .datahub-mcp-venv/Lib/site-packages --strict` | one known upstream distribution: `setuptools 81.0.0`, reported twice as `PYSEC-2026-3447` |
| Forced compatibility probe | disposable environment with `acryl-datahub 1.6.0.15`, `mcp-server-datahub 0.6.0`, forcibly upgraded to `setuptools 83.0.0` | `pip check` correctly failed the declared `<82` requirement; DataHub CLI/SDK imports and an actual MCP lineage read succeeded on this Windows/local-DataHub run |
| Bridge readback | fixed runtime (`setuptools 83.0.0`) to isolated official MCP sidecar | live MCP readback: 3 lineage entities, 1 entity response, 6 tools exposed |
| Progress contract | live DataHub + live model diagnosis, no containment write | six emitted checkpoints; 4 evidence nodes and 3 suspects returned |
| Browser judge path | fresh Streamlit session, containment left unchecked | animated evidence stage advanced from MCP connection to completed report; 4 real entities traced; no containment write requested |
| Free judge path | fresh Streamlit process with `ANTHROPIC_API_KEY` absent | containment control disabled; live MCP investigation ranked `prod.raw.orders` from its observed 40% volume delta and labeled the result evidence-only rather than model reasoning |
| Free judge scenario path | three live local DataHub incidents, no model key | 3/3 deterministic diagnoses: `prod.raw.orders`, `analytics.staging.stg_customers`, and `prod.ref.exchange_rates`; no catalog action was requested or performed |
| Stalled-MCP recovery | deliberately nonresponsive MCP child process | startup produced the explicit retryable timeout in under 4 seconds rather than leaving the UI at Connecting; child cleanup was inspected afterward |
| Post-startup MCP recovery | a real protocol-speaking test MCP initialized normally, then ignored a tool call | tool call produced the explicit retryable timeout in under 4 seconds rather than leaving the UI at Reading lineage |
| Evidence-card safety | unit contract for catalog/model text rendered into HTML cards | asset label, owner, evidence, and next-check strings are HTML-escaped before interpolation |
| Responsive UI | local browser at 390 px and default desktop width | mascot/status panel, safety copy, and form controls remained readable; desktop primary action rendered blue/cyan rather than an alarm color |
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
- Unsafe generated SQL is rejected before the sandbox.
- Missing sandbox is a recoverable failure, not a silent success.
- An approved trial uses an isolated dbt + DuckDB sandbox, restores the broken
  model afterward, and has no production connector or apply control.
- The UI shows actual investigation checkpoints rather than a silent spinner.
- Catalog containment is explicit opt-in; a fresh judge session starts read-only.
- No-key judge mode remains real: it reads the local DataHub through MCP and applies disclosed deterministic evidence checks. It is read-only and is not represented as a substitute for model-backed reasoning.
- Both application and DataHub-sidecar dependency graphs are hash-locked; bootstrap uses `pip --require-hashes`.
- Bootstrap has no separate unhashed pip-upgrade step. The future unified route refuses to install unless it has a reviewed matching hash lock.
- A nonresponsive MCP server has a bounded startup timeout and a clear retryable error.
- `quickstart.py` stops on failed dependency installation or `datahub docker
  quickstart`; it does not print an unchecked success.
