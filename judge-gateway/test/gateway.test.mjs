import assert from "node:assert/strict";
import test from "node:test";

import worker from "../src/index.js";

const future = "2099-12-31T23:59:59Z";

function environment(overrides = {}) {
  const calls = { rate: 0, budget: 0 };
  return {
    calls,
    env: {
      JUDGE_ACCESS_EXPIRES: future,
      JUDGE_CODE: "test-judge-code",
      ANTHROPIC_API_KEY: "test-provider-key",
      JUDGE_RATE: {
        async limit() {
          calls.rate += 1;
          return { success: true };
        },
      },
      JUDGE_BUDGET: {
        getByName() {
          return {
            async fetch(url) {
              if (new URL(url).pathname === "/status") {
                return Response.json({ allowed: true, used: 0, remaining: 200 });
              }
              calls.budget += 1;
              return Response.json({ allowed: true, remaining: 199 });
            },
          };
        },
      },
      ...overrides,
    },
  };
}

test("health exposes the access window without a credential", async () => {
  const { env } = environment();
  const response = await worker.fetch(new Request("https://gateway.test/health"), env);
  const body = await response.json();
  assert.equal(response.status, 200);
  assert.equal(body.access_active, true);
  assert.equal(body.access_expires, new Date(future).toISOString());
  assert.equal(JSON.stringify(body).includes("test-judge-code"), false);
  assert.equal(JSON.stringify(body).includes("test-provider-key"), false);
});

test("invalid access-window configuration fails closed", async () => {
  const { env } = environment({ JUDGE_ACCESS_EXPIRES: "not-a-date" });
  const health = await worker.fetch(new Request("https://gateway.test/health"), env);
  assert.equal(health.status, 503);
  const reason = await worker.fetch(
    new Request("https://gateway.test/reason", {
      method: "POST",
      headers: { "x-lineage-judge-code": "test-judge-code" },
      body: JSON.stringify({ user: "hello" }),
    }),
    env,
  );
  assert.equal(reason.status, 503);
});

test("expired access is rejected before authentication or budget work", async () => {
  const { env, calls } = environment({ JUDGE_ACCESS_EXPIRES: "2020-01-01T00:00:00Z" });
  const response = await worker.fetch(
    new Request("https://gateway.test/reason", {
      method: "POST",
      headers: { "x-lineage-judge-code": "test-judge-code" },
      body: JSON.stringify({ user: "hello" }),
    }),
    env,
  );
  assert.equal(response.status, 410);
  assert.deepEqual(calls, { rate: 0, budget: 0 });
});

test("malformed authenticated input does not consume global budget", async () => {
  const { env, calls } = environment();
  const response = await worker.fetch(
    new Request("https://gateway.test/reason", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-lineage-judge-code": "test-judge-code",
      },
      body: "{broken",
    }),
    env,
  );
  assert.equal(response.status, 400);
  assert.equal(calls.rate, 2);
  assert.equal(calls.budget, 0);
});

test("wrong codes are rate limited before comparison", async () => {
  const { env, calls } = environment();
  const response = await worker.fetch(
    new Request("https://gateway.test/reason", {
      method: "POST",
      headers: { "x-lineage-judge-code": "wrong-code" },
      body: JSON.stringify({ user: "hello" }),
    }),
    env,
  );
  assert.equal(response.status, 401);
  assert.deepEqual(calls, { rate: 1, budget: 0 });
});

test("authorized preflight validates bindings without provider spend", async () => {
  const { env, calls } = environment();
  const response = await worker.fetch(
    new Request("https://gateway.test/preflight", {
      method: "POST",
      headers: { "x-lineage-judge-code": "test-judge-code" },
    }),
    env,
  );
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.equal(body.ready, true);
  assert.equal(body.daily_requests_remaining, 200);
  assert.deepEqual(calls, { rate: 1, budget: 0 });
});

test("chunked or missing-length oversized bodies are rejected before budget", async () => {
  const { env, calls } = environment();
  const response = await worker.fetch(
    new Request("https://gateway.test/reason", {
      method: "POST",
      headers: { "x-lineage-judge-code": "test-judge-code" },
      body: JSON.stringify({ user: "x".repeat(70_000) }),
    }),
    env,
  );
  assert.equal(response.status, 413);
  assert.deepEqual(calls, { rate: 2, budget: 0 });
});

test("valid access consumes one budget unit and returns only provider text", async () => {
  const { env, calls } = environment();
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    assert.equal(url, "https://api.anthropic.com/v1/messages");
    assert.equal(init.headers["x-api-key"], "test-provider-key");
    const providerBody = JSON.parse(init.body);
    assert.equal(providerBody.max_tokens, 6_000);
    assert.equal(providerBody.output_config.format.type, "json_schema");
    assert.equal(providerBody.output_config.format.schema.additionalProperties, false);
    assert.deepEqual(
      providerBody.output_config.format.schema.required,
      ["summary", "suspects", "missing_evidence"],
    );
    const report = JSON.stringify({
      summary: "Grounded report.",
      suspects: [],
      missing_evidence: null,
    });
    return Response.json({
      content: [{ type: "text", text: report }],
      stop_reason: "end_turn",
    });
  };
  try {
    const response = await worker.fetch(
      new Request("https://gateway.test/reason", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-lineage-judge-code": "test-judge-code",
        },
        body: JSON.stringify({ system: "Be concise.", user: "Return GATEWAY_OK." }),
      }),
      env,
    );
    assert.equal(response.status, 200);
    const body = await response.json();
    assert.equal(JSON.parse(body.text).summary, "Grounded report.");
    assert.deepEqual(calls, { rate: 2, budget: 1 });
  } finally {
    globalThis.fetch = realFetch;
  }
});

test("evidence URNs become the only schema-valid suspect identifiers", async () => {
  const { env } = environment();
  const observed = "urn:li:dataset:(urn:li:dataPlatform:postgres,analytics.raw.orders,PROD)";
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (_url, init) => {
    const providerBody = JSON.parse(init.body);
    assert.deepEqual(
      providerBody.output_config.format.schema.properties.suspects.items
        .properties.urn.enum,
      [observed],
    );
    return Response.json({
      content: [{
        type: "text",
        text: JSON.stringify({
          summary: "Grounded report.",
          suspects: [{
            urn: observed,
            why: "The observed row count dropped.",
            check_next: "Inspect the source extract.",
            owner: null,
            confidence: "high",
          }],
          missing_evidence: null,
        }),
      }],
      stop_reason: "end_turn",
    });
  };
  try {
    const response = await worker.fetch(
      new Request("https://gateway.test/reason", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-lineage-judge-code": "test-judge-code",
        },
        body: JSON.stringify({
          system: "Return JSON.",
          user: `Evidence:\n    urn: ${observed}\nDiagnose.`,
        }),
      }),
      env,
    );
    assert.equal(response.status, 200);
    assert.equal(JSON.parse((await response.json()).text).suspects[0].urn, observed);
  } finally {
    globalThis.fetch = realFetch;
  }
});

test("invalid provider output fails closed after one budget unit", async () => {
  const { env, calls } = environment();
  const realFetch = globalThis.fetch;
  globalThis.fetch = async () => Response.json({
    content: [{ type: "text", text: "not-json" }],
    stop_reason: "max_tokens",
  });
  try {
    const response = await worker.fetch(
      new Request("https://gateway.test/reason", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-lineage-judge-code": "test-judge-code",
        },
        body: JSON.stringify({ system: "Return JSON.", user: "Diagnose." }),
      }),
      env,
    );
    assert.equal(response.status, 502);
    assert.deepEqual(await response.json(), {
      error: "invalid_structured_reasoning_response",
      retryable: true,
    });
    assert.deepEqual(calls, { rate: 2, budget: 1 });
  } finally {
    globalThis.fetch = realFetch;
  }
});
