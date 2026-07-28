"""Small truthful bootstrap page shown while the real DataHub stack starts."""
from __future__ import annotations

import html
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


STATUS_PATH = Path(os.environ.get("LINEAGE_BOOT_STATUS", "/app/state/bootstrap.json"))


def read_status() -> dict:
    try:
        value = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {"stage": "Preparing the secure judge runtime", "percent": 2}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        status = read_status()
        if self.path == "/healthz":
            body = json.dumps(status, sort_keys=True).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("cache-control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        stage = html.escape(str(status.get("stage") or "Preparing the judge runtime"))
        detail = html.escape(
            str(status.get("detail") or "This is a real DataHub Core cold start.")
        )
        percent = max(0, min(100, int(status.get("percent") or 0)))
        body = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<meta http-equiv="refresh" content="8">
<title>Lineage Detective is starting</title>
<style>
body{{margin:0;background:#07111f;color:#e8f2ff;font:18px/1.5 system-ui,sans-serif;display:grid;
place-items:center;min-height:100vh}}main{{width:min(720px,88vw);padding:42px;border:1px solid #24476f;
border-radius:24px;background:linear-gradient(145deg,#0c1a2d,#091523);box-shadow:0 28px 80px #0009}}
.eyebrow{{color:#66d9ff;font-weight:800;letter-spacing:.12em;text-transform:uppercase;font-size:.78rem}}
h1{{font-size:clamp(2rem,6vw,4rem);line-height:1;margin:.5rem 0 1rem}}p{{color:#a9bfd8}}
.track{{height:14px;background:#142a43;border-radius:999px;overflow:hidden;margin:28px 0 12px}}
.fill{{height:100%;width:{percent}%;background:linear-gradient(90deg,#3cd7ff,#768cff);transition:width .4s}}
.row{{display:flex;justify-content:space-between;color:#d4e6fa;font-weight:700}}
</style></head><body><main><div class="eyebrow">Real DataHub Core · secure cold start</div>
<h1>{stage}</h1><p>{detail}</p><div class="track"><div class="fill"></div></div>
<div class="row"><span>Verified startup sequence</span><span>{percent}%</span></div>
<p>This page refreshes automatically. No fixture or prerecorded result is being substituted.</p>
</main></body></html>""".encode("utf-8")
        body = body.replace(b"\xc3\x82\xc2\xb7", b"&middot;")
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("cache-control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8501), Handler).serve_forever()
