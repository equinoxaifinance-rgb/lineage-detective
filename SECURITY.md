# Security boundary and known advisory

## PYSEC-2026-3447 / CVE-2026-59890

The official `acryl-datahub==1.6.0.15` package currently requires
`setuptools<82`, while the advisory is fixed in `setuptools>=83`.

This is **not marked fixed** here. It is a current upstream compatibility
constraint: upgrading setuptools to the advisory's fixed version makes
`pip check` fail for the supported DataHub package version.

### What the advisory affects

The affected `setuptools` code builds a Python **source distribution** on macOS
APFS/HFS+ and can mishandle Unicode-normalized filenames when applying
`MANIFEST.in` exclusions. The preconditions are a macOS package build, a
normalization-collision filename, and a relevant manifest exclusion.

Lineage Detective does not build or publish Python source distributions. This
repository has no `pyproject.toml`, `setup.py`, `setup.cfg`, or `MANIFEST.in`,
and the running application does not invoke `setuptools` packaging APIs. Its
Windows local DataHub/MCP workflow is therefore outside the advisory's observed
execution path.

That boundary is not a claim that the old setuptools version is safe for every
use. Do **not** use this project environment to build source distributions on
macOS. Re-evaluate this file when DataHub releases a compatible version that
permits `setuptools>=83`.

### Controls and receipts

1. The judge-facing `.venv` installs the checked-in, SHA-256 hash-locked
   `requirements-runtime.lock` with `pip --require-hashes`, pins
   `pip==26.1.2` and `setuptools==83.0.0`, and contains the app, MCP client, UI, and repair
   sandbox only. Its audit must be green.
2. At startup `quickstart.py` performs a dry dependency-resolution check. If
   DataHub can resolve with fixed `setuptools>=83`, it uses one unified runtime.
   While DataHub's package metadata rejects that safe path, it automatically
   uses `.datahub-mcp-venv` for the official DataHub MCP server plus local
   bootstrap/seed scripts. The advisory is isolated there, not hidden or ignored.
3. The DataHub sidecar installs its separately checked-in SHA-256 hash-locked
   `requirements-datahub-sidecar.lock` with `pip --require-hashes`. `quickstart.py`
   creates both environments; it does not install into the caller's global Python environment.
4. `tools/verify_security_boundary.py` checks the repository does not contain
   Python packaging inputs and records both dependency boundaries.
5. Release verification runs `pip check`, `pip-audit`, unit tests, and live
   DataHub/MCP proofs. In the 2026-08-10 readback, the runtime audit was green;
   the sidecar audit reported only `PYSEC-2026-3447` twice for the same
   `setuptools==81.0.0` distribution. The sidecar advisory remains explicit
   until upstream resolves it.

## Credentials

Keep `ANTHROPIC_API_KEY` and any `DATAHUB_GMS_TOKEN` only in local environment
variables or an ignored `.env`. Never commit them. A hosted DataHub tenant uses
its own scoped token; the public `demo.datahubproject.io` instance is not a
supported backend for this project.

## Self-hosted deployment commands

The public hosted app does not expose arbitrary local commands. A customer-controlled self-hosted
process may configure deployment commands after selecting an existing repair target inside the
same project root. Commands use `shell=False`, are individually time-bounded, and inherit
credentials from the customer's existing environment; credentials are not saved in a deployment
profile or receipt. Command text and output are represented by SHA-256 fingerprints in the final
receipt rather than copied verbatim.

The deploy command's exit code is not considered live proof. A separate health-check command must
read the downstream result. On deploy or health-check failure, Lineage Detective restores the exact
hash-verified backup, runs the configured rollback command, and runs a distinct rollback-health
check. An unverified rollback remains a red terminal state.
