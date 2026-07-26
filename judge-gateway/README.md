# Judge gateway deployment

This is the server-side model gateway for the judge build. It contains **no secrets**.

1. Authenticate Wrangler to the intended Cloudflare account.
2. From this directory, deploy the Worker: `npx wrangler deploy`.
3. Set the two encrypted Worker secrets interactively — never in Git or Devpost:
   - `npx wrangler secret put ANTHROPIC_API_KEY`
   - `npx wrangler secret put JUDGE_CODE`
4. Verify `GET /health`, then make a bounded model request with the supplied judge code.

The Worker fixes the model and output-token ceiling, rejects oversized requests, and applies a
10-request-per-minute per-IP/code Cloudflare Rate Limiting binding. A strongly consistent
Durable Object also caps the entire gateway at 200 model requests per UTC day (configurable as
`JUDGE_DAILY_REQUEST_CAP`), so an access-code leak cannot cause unbounded provider spend.
The local app passes only DataHub evidence and the judge access code; it never contains the
provider secret. The judge access code is a bounded invitation credential, **not** an Anthropic
API key.
