import { Container } from "@cloudflare/containers";

export class LineageDetectiveContainer extends Container {
  defaultPort = 8501;
  sleepAfter = "15m";
  enableInternet = true;
  envVars = {
    HOSTED_MODE: "1",
  };

  async onStart() {
    console.log("Lineage Detective container started");
  }

  async onError(error) {
    console.error("Lineage Detective container error", error);
  }
}

export default {
  async fetch(request, env) {
    const container = env.LINEAGE_DETECTIVE.getByName("judge");
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
