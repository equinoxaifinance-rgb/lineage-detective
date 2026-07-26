# Judge access handoff

The application preloads this bounded reasoning gateway:

`https://lineage-detective-judge-gateway.equinoxaifinance.workers.dev`

The hosted DataHub Cloud application is:

`https://lineage-detective.equinoxaifinance.workers.dev`

The provider API key is **never** given to a judge, placed in Git, embedded in the app, or pasted
into Devpost. It remains an encrypted Cloudflare Worker secret.

## Submission-time action

Place the current **judge access code** in Devpost's testing-instructions/additional-details field,
with these directions:

1. Start Lineage Detective.
2. Confirm the gateway URL is already present in the sidebar.
3. Paste the supplied judge access code.
4. The app should report that the model-backed judge gateway is ready.
5. Run the complete rewrite walkthrough.

For the hosted application, also supply a DataHub Cloud tenant URL and a scoped service-account
token, or use the repository quickstart for the bundled local DataHub walkthrough. The hosted
application intentionally does not contain a shared DataHub credential.

If the contest does not expose a testing-instructions field, provide the access code directly to
the organizer through its official participant-support channel. Do not publish it in the repository.

## Verified boundary — 2026-07-26

- Worker deployment exists.
- `ANTHROPIC_API_KEY` and `JUDGE_CODE` exist as encrypted Worker secrets.
- `GET /health` returned HTTP 200.
- An authorized `/reason` request returned `GATEWAY_OK`.
- An unauthorized request is rejected before provider access.
- Rate limit: 10 requests per minute per IP/code.
- Whole-gateway cap: 200 requests per UTC day through a Durable Object.

This handoff contains no secret values. Re-run the authorized probe immediately before submission
and after any credential rotation.
