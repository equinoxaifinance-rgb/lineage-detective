"""datahub_mcp.py — the agent's connection to DataHub through its official MCP Server.

This is the heart of what makes Lineage Detective a *DataHub agent* and not just a script that
imports an SDK: every fact the agent sees and every action it takes goes through the tools the
DataHub **MCP Server** (`mcp-server-datahub`) exposes — the same agent-facing surface DataHub built
for exactly this. Read tools: `get_lineage`, `get_entities`, `search`. Write tool: `add_tags`.

We speak MCP over stdio: we launch the server as a subprocess, initialize an MCP `ClientSession`,
and call its tools by name. The server talks to DataHub GMS via `DATAHUB_GMS_URL`/`DATAHUB_GMS_TOKEN`.

Design note: the agent code is synchronous, so `MCPDataHub` owns one asyncio loop and holds the MCP
session open across calls (server startup is ~2s — we pay it once, not per tool call).
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import queue
import shutil
import sys
import threading
import time

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

try:
    from .network_policy import validate_network_url, validate_resolution
    from .runtime_mode import is_bundled_catalog_url, is_self_hosted
except ImportError:
    from network_policy import validate_network_url, validate_resolution
    from runtime_mode import is_bundled_catalog_url, is_self_hosted


def _server_command() -> tuple[str, list[str]]:
    """Resolve the hash-locked DataHub MCP server selected by quickstart.

    Release execution accepts:
      1. DATAHUB_MCP_EXECUTABLE exact executable selected by quickstart,
      2. the root-owned packaged sidecar in the public container,
      3. the executable installed in this project's hash-locked sidecar.

    An unpinned PATH/command override is available only with the explicit
    LINEAGE_ALLOW_UNPINNED_MCP=1 developer opt-in. There is no execution-time
    uv/uvx install fallback in the release path.
    """
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sidecar_root = os.path.realpath(os.path.join(project_root, ".datahub-mcp-venv"))
    selected_exe = os.environ.get("DATAHUB_MCP_EXECUTABLE")
    if selected_exe:
        if not os.path.isfile(selected_exe):
            raise FileNotFoundError(
                "DATAHUB_MCP_EXECUTABLE was selected by setup but is no longer present: "
                f"{selected_exe}. Re-run quickstart.py."
            )
        resolved_selected = os.path.realpath(selected_exe)
        try:
            selected_is_locked_sidecar = (
                os.path.commonpath([sidecar_root, resolved_selected]) == sidecar_root
                and not os.path.islink(selected_exe)
            )
        except ValueError:
            # Windows raises when the selected executable and project sidecar
            # resolve to different drives. That is outside the locked sidecar,
            # not an internal error that should bypass the release boundary.
            selected_is_locked_sidecar = False
        packaged_exe = os.path.realpath(
            "/opt/datahub-sidecar/bin/mcp-server-datahub"
        )
        selected_is_packaged_sidecar = (
            os.environ.get("LINEAGE_RUN_MODE") == "public_judge"
            and os.environ.get("LINEAGE_BUNDLED_DATAHUB") == "1"
            and resolved_selected == packaged_exe
            and not os.path.islink(selected_exe)
        )
        if (
            not (selected_is_locked_sidecar or selected_is_packaged_sidecar)
            and os.environ.get("LINEAGE_ALLOW_UNPINNED_MCP") != "1"
        ):
            raise PermissionError(
                "DATAHUB_MCP_EXECUTABLE is outside the hash-locked project sidecar. "
                "Run quickstart.py or explicitly opt into a development override."
            )
        return resolved_selected, []
    sidecar_exe = os.path.join(
        project_root, ".datahub-mcp-venv", "Scripts" if os.name == "nt" else "bin",
        "mcp-server-datahub.exe" if os.name == "nt" else "mcp-server-datahub",
    )
    if os.path.exists(sidecar_exe):
        return sidecar_exe, []
    if os.environ.get("LINEAGE_ALLOW_UNPINNED_MCP") == "1":
        override = os.environ.get("DATAHUB_MCP_CMD")
        if override:
            parts = override.split()
            return parts[0], parts[1:]
        exe = shutil.which("mcp-server-datahub")
        if exe:
            return exe, []
    raise FileNotFoundError(
        "The hash-locked DataHub MCP sidecar is not installed. Run quickstart.py. "
        "For an intentional development-only override, set LINEAGE_ALLOW_UNPINNED_MCP=1."
    )


def _startup_timeout_from(error: BaseException) -> TimeoutError | None:
    """Extract our useful startup timeout from anyio's teardown ExceptionGroup."""
    if isinstance(error, TimeoutError) and str(error).startswith("DataHub MCP did not initialize"):
        return error
    if isinstance(error, BaseExceptionGroup):
        for nested in error.exceptions:
            timeout = _startup_timeout_from(nested)
            if timeout:
                return timeout
    return None


class MCPDataHub:
    """Synchronous facade over the DataHub MCP server (stdio). Use as a context manager."""

    def __init__(self, gms_url: str | None = None, token: str | None = None,
                 enable_mutations: bool = True, startup_timeout: float = 45.0,
                 tool_timeout: float = 30.0,
                 server_command: tuple[str, list[str]] | None = None,
                 mcp_url: str | None = None,
                 entity_batch_size: int | None = None):
        self.gms_url = gms_url or os.environ.get("DATAHUB_GMS_URL", "http://localhost:8080")
        self.token = token if token is not None else os.environ.get("DATAHUB_GMS_TOKEN", "")
        self.mcp_url = mcp_url or os.environ.get("DATAHUB_MCP_URL")
        self.allow_private_network = (
            is_self_hosted() or is_bundled_catalog_url(self.gms_url)
        )
        self.gms_url = validate_network_url(
            self.gms_url,
            allow_private=self.allow_private_network,
            label="DataHub server URL",
        )
        if self.mcp_url:
            self.mcp_url = validate_network_url(
                self.mcp_url,
                allow_private=self.allow_private_network,
                label="DataHub MCP URL",
            )
        self.enable_mutations = enable_mutations
        # Bound startup so a failed catalog connection cannot leave the UI at
        # "Connecting" indefinitely. Individual tool calls retain their own timeout.
        self.startup_timeout = max(float(startup_timeout), 0.1)
        self.tool_timeout = max(float(tool_timeout), 0.1)
        configured_batch_size = (
            entity_batch_size
            if entity_batch_size is not None
            else os.environ.get("LINEAGE_MCP_ENTITY_BATCH_SIZE", "3")
        )
        try:
            parsed_batch_size = int(configured_batch_size)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "LINEAGE_MCP_ENTITY_BATCH_SIZE must be an integer between 1 and 10."
            ) from exc
        self.entity_batch_size = min(max(parsed_batch_size, 1), 10)
        self._server_command_override = server_command
        self.tools: set[str] = set()
        # The MCP session lives entirely inside one task on a dedicated thread, so every anyio
        # cancel scope is entered AND exited in the same task (mixing tasks raises at teardown).
        self._thread: threading.Thread | None = None
        self._reqq: "queue.Queue" = queue.Queue()
        self._ready = threading.Event()
        self._open_error: BaseException | None = None
        self._startup_phase = "not_started"

    def _set_startup_phase(self, phase: str) -> None:
        self._startup_phase = phase
        if os.environ.get("LINEAGE_MCP_DEBUG") == "1":
            print(
                f"LINEAGE_MCP_CLIENT phase={phase}",
                file=sys.stderr,
                flush=True,
            )

    # ---- lifecycle -------------------------------------------------------------
    def __enter__(self) -> "MCPDataHub":
        self._set_startup_phase("thread_start")
        self._thread = threading.Thread(target=self._run, name="datahub-mcp", daemon=True)
        self._thread.start()
        if not self._ready.wait(self.startup_timeout + 2):
            self._open_error = TimeoutError(
                f"DataHub MCP did not become ready within {self.startup_timeout:.1f}s; "
                f"last startup phase={self._startup_phase}. "
                "Check the catalog connection and retry."
            )
            self._reqq.put(None)
            if self._thread:
                self._thread.join(timeout=2)
        if self._open_error:
            raise self._open_error
        return self

    def __exit__(self, *exc) -> None:
        self._reqq.put(None)  # sentinel → break the serve loop, unwind the session cleanly
        if self._thread:
            self._thread.join(timeout=30)

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._serve())
        finally:
            loop.close()

    async def _serve(self) -> None:
        try:
            if self.mcp_url:
                await self._serve_remote()
            else:
                await self._serve_stdio()
        except BaseException as e:
            # anyio may wrap a timed-out initialize in an ExceptionGroup while
            # shutting down stdio. Preserve the actionable cause for the UI.
            self._open_error = _startup_timeout_from(e) or e
            self._ready.set()

    async def _serve_stdio(self) -> None:
        """Use the isolated official MCP subprocess for local/Core/GMS deployments."""
        cmd, args = self._server_command_override or _server_command()
        if os.environ.get("LINEAGE_MCP_DEBUG") == "1":
            # The official CLI's debug mode records MCP request/response
            # boundaries. Release bootstrap enables it only for the private
            # verification probe so a production hang is diagnosable without
            # changing the normal judge-session tool surface.
            args = [*args, "--debug"]
        env = dict(os.environ)
        env["DATAHUB_GMS_URL"] = self.gms_url
        env["DATAHUB_GMS_TOKEN"] = self.token or ""
        env["TOOLS_IS_MUTATION_ENABLED"] = "true" if self.enable_mutations else "false"
        # DataHub CLI telemetry is optional. In an egress-restricted judge
        # container its analytics retries can block the MCP process before it
        # answers the protocol initialize request. Keep the catalog path real,
        # but make startup independent of an unrelated telemetry endpoint.
        env["DATAHUB_TELEMETRY_ENABLED"] = "false"
        # This agent never calls the optional document-search tools. Disabling that surface
        # prevents the official server from running a catalog-wide document-existence query
        # during every startup while preserving lineage, entity, search, and tag operations.
        env["DATAHUB_MCP_DOCUMENT_TOOLS_DISABLED"] = "true"
        params = StdioServerParameters(command=cmd, args=args, env=env)
        self._set_startup_phase("launching_stdio_server")
        async with stdio_client(params) as (read, write):
            self._set_startup_phase("stdio_connected")
            async with ClientSession(read, write) as session:
                await self._serve_session(session)

    async def _serve_remote(self) -> None:
        """Connect directly to DataHub Cloud's managed streamable-HTTP MCP endpoint."""
        validate_resolution(
            str(self.mcp_url),
            allow_private=self.allow_private_network,
            label="DataHub MCP URL",
        )
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        async with httpx.AsyncClient(
            headers=headers,
            timeout=self.tool_timeout,
            follow_redirects=False,
        ) as http_client:
            async with streamable_http_client(str(self.mcp_url), http_client=http_client) as streams:
                read, write, _session_id = streams
                async with ClientSession(read, write) as session:
                    await self._serve_session(session)

    async def _serve_session(self, session: ClientSession) -> None:
        """Initialize either transport once, then service synchronous facade requests."""
        self._set_startup_phase("initialize_request")
        try:
            await asyncio.wait_for(session.initialize(), timeout=self.startup_timeout)
        except asyncio.TimeoutError as exc:
            raise TimeoutError(
                f"DataHub MCP did not initialize within {self.startup_timeout:.1f}s. "
                f"last startup phase={self._startup_phase}. "
                "Check the catalog connection and retry."
            ) from exc
        self._set_startup_phase("ready")
        self._ready.set()
        loop = asyncio.get_event_loop()
        while True:
            req = await loop.run_in_executor(None, self._reqq.get)
            if req is None:
                break
            tool, targs, fut = req
            try:
                res = await asyncio.wait_for(
                    session.call_tool(tool, targs), timeout=self.tool_timeout
                )
                text = "".join(getattr(c, "text", "") for c in (res.content or []))
                if getattr(res, "isError", False):
                    raise RuntimeError(
                        f"DataHub MCP tool '{tool}' returned an error: {text[:500]}"
                    )
                # A completed call is stronger capability evidence than a
                # tools/list advertisement. Record only executed tools.
                self.tools.add(tool)
                fut.set_result(text)
            except asyncio.TimeoutError:
                fut.set_exception(TimeoutError(
                    f"DataHub MCP tool '{tool}' did not respond within "
                    f"{self.tool_timeout:.1f}s. Check the catalog connection and retry."
                ))
            except BaseException as e:  # surface to the caller, keep serving
                fut.set_exception(e)

    # ---- raw tool call ---------------------------------------------------------
    def _call(self, tool: str, args: dict) -> str:
        fut: concurrent.futures.Future = concurrent.futures.Future()
        self._reqq.put((tool, args, fut))
        try:
            return fut.result(timeout=self.tool_timeout + 5)
        except TimeoutError:
            # If the async side supplied a specific timeout, retain it. Otherwise
            # the dispatch thread itself is unhealthy; give the UI the same clear
            # retry boundary rather than a raw concurrent-futures exception.
            if fut.done():
                raise
            raise TimeoutError(
                f"DataHub MCP tool '{tool}' did not complete within the {self.tool_timeout:.1f}s "
                "response budget. Check the catalog connection and retry."
            )

    @staticmethod
    def _loads(text: str):
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return None

    # ---- high-level DataHub reads/writes (via MCP tools) -----------------------
    def search(self, query: str, *, num_results: int = 12,
               entity_filter: str | None = None) -> list[dict]:
        """Search the connected tenant and return compact, selectable entity records.

        The official MCP search tool expects structured queries beginning with ``/q``.
        Human input is normalized here so the UI can accept ordinary words.
        """
        cleaned = " ".join(str(query or "").split()).strip()
        if not cleaned:
            return []
        structured = cleaned if cleaned.startswith("/q") else f"/q {cleaned}"
        args: dict[str, object] = {
            "query": structured,
            "num_results": max(1, min(int(num_results), 50)),
        }
        if entity_filter:
            args["filter"] = entity_filter
        data = self._loads(self._call("search", args)) or {}
        rows = data.get("searchResults", []) if isinstance(data, dict) else []
        results: list[dict] = []
        for row in rows:
            entity = row.get("entity", {}) if isinstance(row, dict) else {}
            urn = entity.get("urn") if isinstance(entity, dict) else None
            if not urn:
                continue
            properties = entity.get("properties") or {}
            name = properties.get("name") if isinstance(properties, dict) else None
            results.append({
                "urn": str(urn),
                "name": str(name or _urn_name(str(urn))),
            })
        return results

    def get_lineage(self, urn: str, upstream: bool = True, max_hops: int = 3,
                    max_results: int = 40) -> list[dict]:
        """Call the MCP `get_lineage` tool; return the list of entity dicts in that direction."""
        text = self._call("get_lineage", {"urn": urn, "upstream": upstream,
                                          "max_hops": max_hops, "max_results": max_results})
        data = self._loads(text) or {}
        block = data.get("upstreams") if upstream else data.get("downstreams")
        if block is None:  # be tolerant of shape drift across versions
            block = data.get("upstreams") or data.get("downstreams") or data
        results = block.get("searchResults", []) if isinstance(block, dict) else []
        return [r.get("entity", {}) for r in results if r.get("entity")]

    def get_entities(self, urns: list[str]) -> dict[str, dict]:
        """Read full metadata in bounded MCP batches.

        The official server resolves each entity through a detailed GraphQL
        fragment. A large list can exceed a truthful per-tool response budget
        on a newly started catalog even when every entity is healthy. Small
        batches preserve the official MCP path and fail the whole read if any
        batch fails rather than returning silently partial evidence.
        """
        urns = [u for u in dict.fromkeys(urns) if u]
        if not urns:
            return {}
        merged: dict[str, dict] = {}
        for offset in range(0, len(urns), self.entity_batch_size):
            batch = urns[offset:offset + self.entity_batch_size]
            text = self._call("get_entities", {"urns": batch})
            data = self._loads(text)
            entities = (
                data
                if isinstance(data, list)
                else (data.get("entities", []) if data else [])
            )
            merged.update({
                e.get("urn"): e
                for e in entities
                if isinstance(e, dict) and e.get("urn")
            })
        return merged

    def add_tag(self, entity_urn: str, tag_urn: str) -> bool:
        """Call MCP `add_tags`, then observe the tag through a bounded readback.

        DataHub's write acknowledgement can arrive before the updated aspect is
        visible to the next metadata read. Polling the official MCP read surface
        preserves the proof requirement without treating normal propagation
        delay as a failed mutation.
        """
        self._call("add_tags", {"tag_urns": [tag_urn], "entity_urns": [entity_urn]})
        return self._wait_for_tag_state(entity_urn, tag_urn, present=True)

    def remove_tag(self, entity_urn: str, tag_urn: str) -> bool:
        """Call MCP `remove_tags`, then observe absence through a bounded readback."""
        self._call(
            "remove_tags",
            {"tag_urns": [tag_urn], "entity_urns": [entity_urn]},
        )
        return self._wait_for_tag_state(entity_urn, tag_urn, present=False)

    def _wait_for_tag_state(
        self,
        entity_urn: str,
        tag_urn: str,
        *,
        present: bool,
    ) -> bool:
        configured = os.environ.get("LINEAGE_MCP_MUTATION_READBACK_SECONDS", "8")
        try:
            timeout = min(max(float(configured), 0.0), 30.0)
        except (TypeError, ValueError):
            timeout = 8.0
        deadline = time.monotonic() + timeout
        while True:
            check = self.get_entities([entity_urn]).get(entity_urn, {})
            observed = tag_urn in _tag_urns(check)
            if observed is present:
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.4, remaining))


def _tag_urns(entity: dict) -> list[str]:
    return [t.get("tag", {}).get("urn") for t in ((entity.get("tags") or {}).get("tags") or [])]


def _urn_name(urn: str) -> str:
    parts = urn.rsplit("(", 1)[-1].rstrip(")").split(",")
    if len(parts) >= 3:
        return parts[-2]
    if len(parts) == 2:
        return parts[-1]
    return urn
