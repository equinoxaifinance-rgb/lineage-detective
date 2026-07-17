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

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _server_command() -> tuple[str, list[str]]:
    """Resolve how to launch the DataHub MCP server, most-specific first, so this runs on a
    judge's machine as well as ours:
      1. DATAHUB_MCP_CMD env override (full command line),
      2. an installed `mcp-server-datahub` console script on PATH,
      3. `uvx mcp-server-datahub@latest` (the launcher DataHub documents),
      4. `python -m uv tool run mcp-server-datahub@latest`.
    """
    override = os.environ.get("DATAHUB_MCP_CMD")
    if override:
        parts = override.split()
        return parts[0], parts[1:]
    exe = shutil.which("mcp-server-datahub")
    if exe:
        return exe, []
    uvx = shutil.which("uvx")
    if uvx:
        return uvx, ["mcp-server-datahub@latest"]
    return sys.executable, ["-m", "uv", "tool", "run", "mcp-server-datahub@latest"]


class MCPDataHub:
    """Synchronous facade over the DataHub MCP server (stdio). Use as a context manager."""

    def __init__(self, gms_url: str | None = None, token: str | None = None,
                 enable_mutations: bool = True):
        self.gms_url = gms_url or os.environ.get("DATAHUB_GMS_URL", "http://localhost:8080")
        self.token = token if token is not None else os.environ.get("DATAHUB_GMS_TOKEN", "")
        self.enable_mutations = enable_mutations
        self.tools: set[str] = set()
        # The MCP session lives entirely inside one task on a dedicated thread, so every anyio
        # cancel scope is entered AND exited in the same task (mixing tasks raises at teardown).
        self._thread: threading.Thread | None = None
        self._reqq: "queue.Queue" = queue.Queue()
        self._ready = threading.Event()
        self._open_error: BaseException | None = None

    # ---- lifecycle -------------------------------------------------------------
    def __enter__(self) -> "MCPDataHub":
        self._thread = threading.Thread(target=self._run, name="datahub-mcp", daemon=True)
        self._thread.start()
        self._ready.wait()
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
            cmd, args = _server_command()
            env = dict(os.environ)
            env["DATAHUB_GMS_URL"] = self.gms_url
            env["DATAHUB_GMS_TOKEN"] = self.token or ""
            env["TOOLS_IS_MUTATION_ENABLED"] = "true" if self.enable_mutations else "false"
            params = StdioServerParameters(command=cmd, args=args, env=env)
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    self.tools = {t.name for t in listed.tools}
                    self._ready.set()
                    loop = asyncio.get_event_loop()
                    while True:
                        req = await loop.run_in_executor(None, self._reqq.get)
                        if req is None:
                            break
                        tool, targs, fut = req
                        try:
                            res = await session.call_tool(tool, targs)
                            text = "".join(getattr(c, "text", "") for c in (res.content or []))
                            fut.set_result(text)
                        except BaseException as e:  # surface to the caller, keep serving
                            fut.set_exception(e)
        except BaseException as e:
            self._open_error = e
            self._ready.set()

    # ---- raw tool call ---------------------------------------------------------
    def _call(self, tool: str, args: dict) -> str:
        fut: concurrent.futures.Future = concurrent.futures.Future()
        self._reqq.put((tool, args, fut))
        return fut.result(timeout=180)

    @staticmethod
    def _loads(text: str):
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return None

    # ---- high-level DataHub reads/writes (via MCP tools) -----------------------
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
        """Call the MCP `get_entities` tool; return {urn: entity_dict} with full metadata."""
        urns = [u for u in dict.fromkeys(urns) if u]
        if not urns:
            return {}
        text = self._call("get_entities", {"urns": urns})
        data = self._loads(text)
        entities = data if isinstance(data, list) else (data.get("entities", []) if data else [])
        return {e.get("urn"): e for e in entities if isinstance(e, dict) and e.get("urn")}

    def add_tag(self, entity_urn: str, tag_urn: str) -> bool:
        """Call the MCP `add_tags` tool, then read the entity back to PROVE the tag stuck."""
        if "add_tags" not in self.tools:
            return False
        self._call("add_tags", {"tag_urns": [tag_urn], "entity_urns": [entity_urn]})
        check = self.get_entities([entity_urn]).get(entity_urn, {})
        applied = tag_urn in _tag_urns(check)
        return applied


def _tag_urns(entity: dict) -> list[str]:
    return [t.get("tag", {}).get("urn") for t in ((entity.get("tags") or {}).get("tags") or [])]
