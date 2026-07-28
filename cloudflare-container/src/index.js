import { Container } from "@cloudflare/containers";
import { env } from "cloudflare:workers";

export class LineageDetectiveContainer extends Container {
  defaultPort = 8501;
  // A real DataHub Core bootstrap is intentionally heavier than a static demo.
  // Keep the verified runtime warm across a judging workday, then scale to zero.
  sleepAfter = "8h";
  enableInternet = true;
  envVars = {
    LINEAGE_RUN_MODE: "public_judge",
    DATAHUB_SERVER: "http://127.0.0.1:8080",
    DATAHUB_GMS_URL: "http://127.0.0.1:8080",
    DATAHUB_GMS_TOKEN: "",
    DATAHUB_MCP_URL: "",
    DATAHUB_MCP_EXECUTABLE: "/opt/datahub-sidecar/bin/mcp-server-datahub",
    LINEAGE_BUNDLED_DATAHUB: "1",
    LINEAGE_REASONING_ENDPOINT:
      env.LINEAGE_REASONING_ENDPOINT ||
      "https://lineage-detective-judge-gateway.equinoxaifinance.workers.dev",
  };

  async onStart() {
    const event = {
      at: new Date().toISOString(),
      type: "started",
    };
    await this.ctx.storage.put("lineage_container_last_start", event);
    console.log("Lineage Detective container started", event);
  }

  async onError(error) {
    const event = {
      at: new Date().toISOString(),
      type: "error",
      message: error instanceof Error ? error.message : String(error),
      stack: error instanceof Error ? error.stack || null : null,
    };
    await this.ctx.storage.put("lineage_container_last_error", event);
    console.error("Lineage Detective container error", event);
    throw error;
  }

  async onStop({ exitCode, reason }) {
    const event = {
      at: new Date().toISOString(),
      exitCode: exitCode ?? null,
      reason,
      type: "stopped",
    };
    await this.ctx.storage.put("lineage_container_last_stop", event);
    console.log("Lineage Detective container stopped", event);
  }

  async lifecycleReceipt() {
    const [lastStart, lastError, lastStop, state] = await Promise.all([
      this.ctx.storage.get("lineage_container_last_start"),
      this.ctx.storage.get("lineage_container_last_error"),
      this.ctx.storage.get("lineage_container_last_stop"),
      this.getState(),
    ]);
    return {
      lastError: lastError || null,
      lastStart: lastStart || null,
      lastStop: lastStop || null,
      state,
    };
  }
}

export default {
  async fetch(request, env) {
    const container = env.LINEAGE_DETECTIVE.getByName("judge");
    const requestUrl = new URL(request.url);
    if (requestUrl.pathname === "/_lineage_runtime_receipt") {
      const receipt = await container.lifecycleReceipt();
      return Response.json(receipt, {
        headers: { "Cache-Control": "no-store" },
      });
    }
    const response = await container.fetch(request);
    if (response.webSocket) {
      return response;
    }
    const headers = new Headers(response.headers);
    headers.set("Strict-Transport-Security", "max-age=31536000; includeSubDomains");
    headers.set("X-Content-Type-Options", "nosniff");
    headers.set("X-Frame-Options", "DENY");
    headers.set("Referrer-Policy", "no-referrer");
    headers.set(
      "Permissions-Policy",
      "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    );
    headers.set(
      "Content-Security-Policy",
      "frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
    );
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers,
    });
  },
};
