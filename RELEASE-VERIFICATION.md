# Release verification

Verified on 2026-07-28 EDT. This document records executed facts and unresolved
external gates. It does not claim contest placement or production safety for an
unknown customer environment.

## Executed release receipts

| Surface | Verification | Result |
|---|---|---|
| Complete Python suite | Canonical aggregate runner over `tests/` | 211 passed, 0 failed, 1 platform skip in 39.559s |
| Source syntax | `python -m compileall -q /app` inside the packaged image | exit 0 |
| Python dependency graph | `python -m pip check` inside the packaged image | no broken requirements |
| Python advisories | `pip-audit==2.10.1` against `requirements-runtime.lock` with hashes and pip resolution disabled | no known vulnerabilities |
| Runtime privilege | Entry-point drop plus `id -u` in the running application process | user `lineage`, UID 1000 |
| Packaged startup | Fresh container, Streamlit health endpoint and root HTTP request | health `ok`; root HTTP 200; UID 1000; `.streamlit/config.toml` and current README present |
| Rendered UI | Fresh in-app browser session against the current runtime image | heading, concise trust disclosure, incident selector, inputs, primary workflow action, and live progress region rendered; fresh browser log contained 0 errors |
| Missing-catalog UI | Streamlit AppTest in `public_judge` mode with all DataHub catalog variables absent | judge-code field absent; judge lane disabled; no credential requested from the judge; no exception |
| Docker packaging | Fresh image build runs compilation, the complete suite, the security-boundary verifier, and example verification before export | Final deployment receipt is captured after the last source commit |
| Windows writer locks | Live two-writer collision plus stale/live-owner probes | Windows-safe process liveness query; no `os.kill(pid, 0)` self-termination; collision refused cleanly |
| Example artifacts | `python tools/verify_release_examples.py` | 3 cases and every bound artifact verified |
| Security boundary | `python tools/verify_security_boundary.py` | fixed app runtime; disclosed isolated upstream compatibility boundary |
| Judge gateway | Node syntax, 8 runtime tests, npm audit, Wrangler dry-run | all passed; 0 vulnerabilities |
| Hosted app Worker | npm audit and Wrangler dry-run including Container image build | passed; 0 vulnerabilities |
| Credential redirect defense | Two live local HTTP servers: gateway redirector and collection sink | request rejected at HTTP 307; sink received no request or judge code |
| CI supply chain | Workflow inspection plus live official tag resolution | actions pinned to exact commit SHAs |
| Public judge workflow | Fresh browser run against the deployed app | live MCP traced six dependency edges and returned seven entities; containment tag write/readback; model-backed diagnosis; evidence-compiled bounded proposal; sandbox 0/8 -> 8/8; rollback verified; exact safe-copy apply hash matched; all 3 artifacts downloaded |
| Judge credential | Fresh secret rotation plus authenticated live `/preflight`; independent invalid-code request | valid code HTTP 200 through 2026-09-15; invalid code HTTP 401 |
| Judge video | Signal QA plus alignment/transcript receipt | 169.733s; one natural-speed narration take; no black or silence events; personal note present |

The full suite includes normal behavior and hostile paths for malformed model
output, unobserved URNs, request limits, authentication, rate and spend caps,
redirects, private-network policy, MCP startup/tool timeouts, concurrent
writers, stale locks, human edits, rollback failure, receipt tampering,
connector response loss and partial success, GitHub exact-head PR recovery,
DataHub assertion readback, Snowflake terminal semantics,
deployment cancellation, and restoration.

## What the receipts prove

- The packaged application starts and its tested workflows behave as the code
  claims.
- The public mode fails closed when its fixed DataHub backend or gateway is not
  configured; it never substitutes static catalog data.
- The self-hosted mode can investigate a customer DataHub and can continue a
  verified change through configured connectors or customer deployment
  commands.
- A successful sandbox receipt proves the exact proposal against the included
  representative fixture. It is not a universal production guarantee.
- A deployment receipt becomes verified only after a separate downstream
  health check. If that check fails, the controller restores source, runs the
  customer rollback command, and verifies the prior state.

## Upstream compatibility boundary

The judge-facing application uses the fixed modern runtime in
`requirements-runtime.lock`, including `setuptools==83.0.0`. The pinned DataHub
CLI/SDK/MCP release currently constrains its own environment to
`setuptools<82`, so those official tools run in a separate checked-in,
hash-locked sidecar. The app automatically uses a reviewed unified lock when a
compatible DataHub release exists. No runtime `uv`, `uvx`, PATH discovery, or
unhashed install is permitted in release mode.

`tools/verify_security_boundary.py` reports this as an upstream compatibility
boundary because the isolated DataHub tool process still contains the older
package. It does not execute untrusted source packages in the app runtime, and
the normal tested DataHub MCP path works, but it is not mislabeled as an
upstream fix.

## Final synchronization gates

- The final source commit must be pushed and read back anonymously before the
  repository is called synchronized.
- The final Container image must be deployed, cold-started, and exercised
  through the private invitation path before the hosted build is called
  synchronized.
- Devpost submission `1077519` already carries the final public video and
  current product story. Its thumbnail, tagline, judge-only Project URL,
  sample-output URL, and DataHub technology selections must be saved and read
  back after the final deployment.

These release-order gates are tracked in [LIVE-STATUS.md](LIVE-STATUS.md).

## Primary-source rule check

Accessed 2026-07-26 EDT:

- Official overview: <https://datahub.devpost.com/>
- Official rules: <https://datahub.devpost.com/rules>

The official pages require a working DataHub application, easy judge access, a
public Apache-2.0 repository, a public demonstration video under three minutes
showing the product in action, and free/unrestricted project access through the
end of judging. The rules also state that judges may rely only on the
description, images, and video, so media is deliberately the last release
artifact rather than a substitute for the current product.
