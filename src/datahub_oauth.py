"""Interactive DataHub OAuth + DCR login for a local Lineage Detective session.

The authorization code returns to a temporary loopback listener. Tokens remain
in memory and are returned to the caller; this module never writes them to disk
or logs them. Hosted deployments use service-account tokens because DataHub
recommends that route for unattended agents and a public multi-user callback
requires a dedicated encrypted token broker.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import queue
import threading
from urllib.parse import parse_qs, urlsplit
import webbrowser

import httpx
from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken


DATAHUB_GLOBAL_MCP = "https://mcp.datahub.com/mcp"


@dataclass
class MemoryTokenStorage:
    tokens: OAuthToken | None = None
    client_info: OAuthClientInformationFull | None = None

    async def get_tokens(self) -> OAuthToken | None:
        return self.tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self.client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self.client_info = client_info


class _CallbackServer:
    def __init__(self) -> None:
        self.result: queue.Queue[tuple[str, str | None] | Exception] = queue.Queue(maxsize=1)
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                values = parse_qs(urlsplit(self.path).query)
                if values.get("error"):
                    owner.result.put(RuntimeError(f"DataHub authorization failed: {values['error'][0]}"))
                    status, body = 400, b"DataHub authorization failed. You may close this tab."
                elif values.get("code"):
                    owner.result.put((values["code"][0], (values.get("state") or [None])[0]))
                    status, body = 200, b"DataHub is connected. Return to Lineage Detective."
                else:
                    status, body = 400, b"Missing OAuth authorization code."
                self.send_response(status)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format: str, *_args) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def redirect_uri(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}/callback"

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def wait(self, timeout: float) -> tuple[str, str | None]:
        value = self.result.get(timeout=timeout)
        if isinstance(value, Exception):
            raise value
        return value


async def _authorize(timeout: float) -> OAuthToken:
    callback = _CallbackServer()
    callback.start()
    storage = MemoryTokenStorage()

    async def redirect_handler(url: str) -> None:
        if not webbrowser.open(url, new=1):
            raise RuntimeError("The DataHub sign-in page could not be opened")

    async def callback_handler() -> tuple[str, str | None]:
        try:
            return await asyncio.to_thread(callback.wait, timeout)
        except queue.Empty as exc:
            raise TimeoutError("DataHub sign-in did not finish before the local callback expired") from exc

    provider = OAuthClientProvider(
        DATAHUB_GLOBAL_MCP,
        OAuthClientMetadata(
            redirect_uris=[callback.redirect_uri],
            client_name="Lineage Detective",
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
        ),
        storage,
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
        timeout=timeout,
    )
    try:
        async with httpx.AsyncClient(
            auth=provider, follow_redirects=True, timeout=timeout
        ) as client:
            async with streamable_http_client(
                DATAHUB_GLOBAL_MCP, http_client=client
            ) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
        if storage.tokens is None:
            raise RuntimeError("DataHub OAuth completed without returning a token")
        return storage.tokens
    finally:
        callback.close()


def authorize_datahub(timeout: float = 300.0) -> OAuthToken:
    """Open DataHub sign-in and return an in-memory OAuth token."""
    return asyncio.run(_authorize(timeout))
