/**
 * Lineage Detective judge gateway.
 *
 * The browser never receives the provider key. This Worker holds it as an encrypted
 * Cloudflare secret, rate-limits judge requests, fixes the model/token ceiling, and
 * returns only the model response needed by the local DataHub judge build.
 */

const MAX_BODY_BYTES = 60_000;
const MAX_SYSTEM_CHARS = 12_000;
const MAX_USER_CHARS = 42_000;
const MAX_OUTPUT_TOKENS = 1_500;
const MODEL = "claude-sonnet-5";
const DEFAULT_DAILY_REQUEST_CAP = 200;
const DEFAULT_ACCESS_EXPIRES = "2026-09-15T23:59:59Z";
const REPORT_SCHEMA = {
  type: "object",
  properties: {
    summary: { type: "string" },
    suspects: {
      type: "array",
      items: {
        type: "object",
        properties: {
          urn: { type: "string" },
          why: { type: "string" },
          check_next: { type: "string" },
          owner: { type: ["string", "null"] },
          confidence: { type: "string", enum: ["high", "medium", "low"] },
        },
        required: ["urn", "why", "check_next", "owner", "confidence"],
        additionalProperties: false,
      },
    },
    missing_evidence: { type: ["string", "null"] },
  },
  required: ["summary", "suspects", "missing_evidence"],
  additionalProperties: false,
};

function cors() {
  // A judge runs the app locally, so the origin is not known in advance. The access code,
  // fixed model, payload limits, and Worker rate limiter protect the endpoint; no secret
  // is in this response or in browser storage.
  return {
    "access-control-allow-origin": "*",
    "access-control-allow-methods": "POST, OPTIONS",
    "access-control-allow-headers": "content-type, x-lineage-judge-code",
    "access-control-max-age": "600",
    "content-type": "application/json; charset=utf-8",
  };
}

function reply(status, payload) {
  return new Response(JSON.stringify(payload), { status, headers: cors() });
}

function validText(value, max) {
  return typeof value === "string" && value.length > 0 && value.length <= max;
}

function validOptionalText(value, max) {
  return value === undefined || (typeof value === "string" && value.length <= max);
}

function accessWindow(env, now = new Date()) {
  const configured = env.JUDGE_ACCESS_EXPIRES || DEFAULT_ACCESS_EXPIRES;
  const expiresAt = new Date(configured);
  if (Number.isNaN(expiresAt.getTime())) {
    return { configured, valid: false, expired: true };
  }
  return { configured: expiresAt.toISOString(), valid: true, expired: now >= expiresAt };
}

/**
 * A strongly consistent shared request ledger. Cloudflare's rate-limit binding
 * throttles per IP at the edge; this Durable Object additionally enforces a
 * whole-gateway daily ceiling so a leaked judge code cannot create unbounded
 * provider spend. The browser cannot address this object directly.
 */
export class JudgeBudget {
  constructor(state) {
    this.state = state;
  }

  async fetch(request) {
    const cap = Math.max(1, Number(new URL(request.url).searchParams.get("cap")) || DEFAULT_DAILY_REQUEST_CAP);
    const used = (await this.state.storage.get("used")) || 0;
    if (new URL(request.url).pathname === "/status") {
      return Response.json({ allowed: used < cap, used, remaining: Math.max(0, cap - used) });
    }
    if (used >= cap) {
      return Response.json({ allowed: false, remaining: 0, retry_after: "next UTC day" });
    }
    const next = used + 1;
    await this.state.storage.put("used", next);
    return Response.json({ allowed: true, remaining: cap - next });
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors() });
    if (url.pathname === "/health" && request.method === "GET") {
      const window = accessWindow(env);
      return reply(window.valid ? 200 : 503, {
        status: window.valid ? "ok" : "misconfigured",
        service: "lineage-detective-judge-gateway",
        access_expires: window.configured,
        access_active: window.valid && !window.expired,
        model: MODEL,
      });
    }
    if (!["/reason", "/preflight"].includes(url.pathname) || request.method !== "POST") {
      return reply(404, { error: "not_found" });
    }
    const window = accessWindow(env);
    if (!window.valid) {
      return reply(503, { error: "judge_access_window_misconfigured", retryable: false });
    }
    if (window.expired) {
      return reply(410, { error: "judge_access_expired", retryable: false });
    }
    const clientIp = request.headers.get("CF-Connecting-IP") || "unknown";
    const authLimited = await env.JUDGE_RATE.limit({ key: `${clientIp}:judge-auth-attempt` });
    if (!authLimited.success) {
      return reply(429, { error: "judge_auth_rate_limited", retryable: true });
    }
    const suppliedCode = request.headers.get("x-lineage-judge-code") || "";
    if (!env.JUDGE_CODE || suppliedCode !== env.JUDGE_CODE) {
      return reply(401, { error: "judge_access_required" });
    }
    if (!env.ANTHROPIC_API_KEY || !env.JUDGE_BUDGET) {
      return reply(503, { error: "reasoning_service_not_configured", retryable: false });
    }
    const day = new Date().toISOString().slice(0, 10);
    const dailyCap = Math.max(1, Number(env.JUDGE_DAILY_REQUEST_CAP) || DEFAULT_DAILY_REQUEST_CAP);
    const budgetStub = env.JUDGE_BUDGET.getByName(`daily-${day}`);
    if (url.pathname === "/preflight") {
      const budget = await (
        await budgetStub.fetch(`https://judge-budget/status?cap=${dailyCap}`)
      ).json();
      if (!budget.allowed) {
        return reply(429, {
          error: "judge_daily_cap_reached",
          retryable: true,
          retry_after: "next UTC day",
        });
      }
      return reply(200, {
        ready: true,
        access_expires: window.configured,
        model: MODEL,
        daily_requests_remaining: budget.remaining,
      });
    }
    const limited = await env.JUDGE_RATE.limit({ key: `${clientIp}:judge-reasoning` });
    if (!limited.success) {
      return reply(429, { error: "judge_rate_limited", retryable: true });
    }
    const length = Number(request.headers.get("content-length") || "0");
    if (length > MAX_BODY_BYTES) return reply(413, { error: "request_too_large" });
    let rawBody;
    try {
      rawBody = new Uint8Array(await request.arrayBuffer());
    } catch {
      return reply(400, { error: "invalid_request_body" });
    }
    if (rawBody.byteLength > MAX_BODY_BYTES) {
      return reply(413, { error: "request_too_large" });
    }
    let body;
    try {
      body = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(rawBody));
    } catch {
      return reply(400, { error: "invalid_json" });
    }
    if (!validOptionalText(body?.system, MAX_SYSTEM_CHARS) || !validText(body?.user, MAX_USER_CHARS)) {
      return reply(400, { error: "invalid_reasoning_request" });
    }
    const budget = await (await budgetStub.fetch(`https://judge-budget/consume?cap=${dailyCap}`)).json();
    if (!budget.allowed) {
      return reply(429, { error: "judge_daily_cap_reached", retryable: true, retry_after: budget.retry_after });
    }
    const upstream = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-api-key": env.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
      },
      body: JSON.stringify({
        model: MODEL,
        max_tokens: MAX_OUTPUT_TOKENS,
        output_config: {
          format: {
            type: "json_schema",
            schema: REPORT_SCHEMA,
          },
        },
        ...(typeof body.system === "string" && body.system ? { system: body.system } : {}),
        messages: [{ role: "user", content: body.user }],
      }),
    });
    if (!upstream.ok) {
      return reply(502, { error: "reasoning_provider_unavailable", retryable: upstream.status >= 500 });
    }
    const answer = await upstream.json();
    const text = (answer.content || []).filter((part) => part.type === "text").map((part) => part.text).join("").trim();
    if (!text) return reply(502, { error: "empty_reasoning_response", retryable: true });
    try {
      JSON.parse(text);
    } catch {
      return reply(502, {
        error: "invalid_structured_reasoning_response",
        retryable: answer.stop_reason === "max_tokens",
      });
    }
    return reply(200, { text });
  },
};
