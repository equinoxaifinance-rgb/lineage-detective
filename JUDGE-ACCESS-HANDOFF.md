# Judge access handoff

This tracked file contains no credential. It defines the exact release path.

## Public judge path

The final release is designed to require one judge-only invitation URL:

1. Open the private Project URL supplied to judges through Devpost.
2. The app consumes the bounded invitation once, removes it from the address
   bar, and authenticates the fixed reasoning gateway automatically.
3. The app connects
   server-side to a dedicated, non-sensitive DataHub judge catalog.
4. Select an included incident or search the live catalog.
5. Run the investigation. The app reads DataHub through MCP, contains through
   MCP when requested, reads writes back, proposes a repair, runs the isolated
   trial, and presents downloadable receipts/handoff.

Judges are never asked for a provider, DataHub, GitHub, warehouse,
orchestrator, or Cloudflare secret in the public mode.

## Required pre-release configuration

The public Cloudflare Container bundles an isolated DataHub Core v1.6 catalog
and the pinned official MCP Server. Internal MySQL and token-service
credentials are generated randomly on each cold start and never leave the
private container network. No DataHub credential is shipped in source or sent
to the browser.

The gateway must contain encrypted secrets:

- `ANTHROPIC_API_KEY`
- `JUDGE_CODE`

The public app must pass `tools/verify_judge_catalog.py` against its bundled
catalog, and the gateway must pass authenticated `/preflight`, before the code
is placed in Devpost. The access window is configured through
`2026-09-15T23:59:59Z`, after the August 31 judging end.

## Security and budget controls

- The judge code is an invitation credential, not the provider key.
- The browser never receives the provider or DataHub token.
- Authentication attempts and reasoning requests are independently throttled.
- A strongly consistent daily gateway cap limits account-level spend.
- Request and response sizes and model output are bounded.
- The fixed public runtime rejects arbitrary connector credentials and
  deployment commands.
- The final code is stored only in an encrypted local owner handoff and the
  judge-only Devpost Project URL.

## Self-hosted evaluator path

The public repository also supports `python quickstart.py`. It starts a real
local DataHub, seeds three reproducible incidents, and launches the app in
`self_hosted` mode. Customer connectors and deployment commands are available
only there because their credentials and network belong inside the evaluator's
own process.

## Current state

The reasoning gateway has its encrypted provider secret and bounded invitation
lane. The hosted app runs a real bundled DataHub catalog and has completed the
full public workflow through MCP read/write/readback, model-backed diagnosis,
dbt/DuckDB repair verification, rollback proof, and downloadable handoff.

The invitation code used during testing was intentionally temporary and is now
rejected by the gateway. The final code was generated after the last browser
test, installed as an encrypted Cloudflare secret, authenticated through the
live `/preflight` endpoint, and stored in the encrypted local owner handoff.
Only its SHA-256 is present in the rotation receipt. The invitation is present
only in Devpost's judge-only Project URL; the public gallery URL remains
secret-free. See [LIVE-STATUS.md](LIVE-STATUS.md) for the current release
stage.
