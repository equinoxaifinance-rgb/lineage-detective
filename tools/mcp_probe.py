"""mcp_probe.py — discover the DataHub MCP server's real tool schemas + response shapes.

Run AFTER `datahub docker quickstart` + `python seed_demo.py`. Prints every tool's input
schema, then makes sample get_lineage / get_entities / search calls against a seeded URN so we
build the evidence layer against REAL output, not guesses.
"""
from __future__ import annotations
import asyncio, os, sys, json

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

MCP_EXE = os.environ.get("DATAHUB_MCP_EXE", r"C:\Users\Jesse\.local\bin\mcp-server-datahub.exe")
SEED_DASH = "urn:li:dataset:(urn:li:dataPlatform:looker,bi.revenue_overview,PROD)"


def _server_env() -> dict:
    env = dict(os.environ)
    env["DATAHUB_GMS_URL"] = os.environ.get("DATAHUB_GMS_URL", "http://localhost:8080")
    env.setdefault("DATAHUB_GMS_TOKEN", os.environ.get("DATAHUB_GMS_TOKEN", ""))
    env["TOOLS_IS_MUTATION_ENABLED"] = "true"
    return env


def _dump(label, result):
    print(f"\n===== {label} =====")
    for c in getattr(result, "content", []) or []:
        txt = getattr(c, "text", None)
        print(txt[:2000] if txt else repr(c)[:2000])


async def main():
    params = StdioServerParameters(command=MCP_EXE, args=[], env=_server_env())
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = await s.list_tools()
            print("TOOLS EXPOSED:")
            for t in tools.tools:
                req = (t.inputSchema or {}).get("required", [])
                props = list(((t.inputSchema or {}).get("properties", {}) or {}).keys())
                print(f"  - {t.name}  required={req}  props={props}")

            names = {t.name for t in tools.tools}
            # sample read calls — tolerant of arg-name differences across versions
            async def call(name, args):
                try:
                    return await s.call_tool(name, args)
                except Exception as e:
                    print(f"  call {name}{args} -> ERROR {e}")
                    return None

            if "get_lineage" in names:
                for args in ({"urn": SEED_DASH, "direction": "UPSTREAM"},
                             {"urn": SEED_DASH, "direction": "upstream"},
                             {"entity_urn": SEED_DASH, "direction": "UPSTREAM"}):
                    res = await call("get_lineage", args)
                    if res is not None:
                        _dump(f"get_lineage {args}", res); break
            if "get_entities" in names:
                for args in ({"urns": [SEED_DASH]}, {"urn": SEED_DASH}):
                    res = await call("get_entities", args)
                    if res is not None:
                        _dump(f"get_entities {args}", res); break
            if "search" in names:
                res = await call("search", {"query": "orders"})
                if res is not None:
                    _dump("search orders", res)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    asyncio.run(main())
