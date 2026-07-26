# Adaptive DataHub compatibility route

Lineage Detective keeps its judge-facing application on a fixed modern Python
packaging runtime while preserving the official DataHub MCP server and all
DataHub capabilities.

`quickstart.py` makes the decision automatically:

1. It asks pip to **dry-resolve** the selected `acryl-datahub` version together
   with `setuptools>=83`. No installation is changed by that check.
2. If the resolver accepts it **and** a reviewed SHA-256
   `requirements-datahub-unified.lock` matches the selected packages, the DataHub CLI,
   SDK, and official MCP server run in the same fixed application environment
   (`unified-fixed-runtime`). The unified installer refuses unhashed packages.
3. If the resolver rejects it—as current DataHub 1.6.0.15 does because it
   declares `setuptools<82`—the app keeps its fixed runtime and routes DataHub
   CLI, SDK, and official MCP work through `.datahub-mcp-venv`
   (`isolated-upstream-compatibility`).
   Auto mode also keeps this equivalent isolated route if a future compatible release has
   not yet received a reviewed unified lock.

The public interface does not change: `python quickstart.py` starts the same
local DataHub, seeds the same real incident graph, and launches the same MCP
agent. This is a compatibility bridge, not a reduced-feature mode.

The app also reports real checkpoints in its interface: connecting to MCP,
reading lineage, evidence-grounded reasoning, optional containment readback,
repair-proposal review, and graph rendering. A checkpoint appears only when
that stage has actually begun; it is not a fake timer or a progress estimate.

For a future DataHub release, update `LINEAGE_DATAHUB_PACKAGE`, generate and verify a matching
`requirements-datahub-unified.lock`, rerun the release matrix, and auto mode will choose the
unified path only if both pip's resolver and the hash-lock gate accept it.
