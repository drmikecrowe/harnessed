# agentmemory

Persistent shared memory for coding agents — 53 MCP tools (save / smart-search / sessions /
governance) over BM25 + vector + graph retrieval, with session recall and 4-tier consolidation.

Two halves. The **service** (`catalog/services/agentmemory/`) is the REST store on :3111 — shared,
long-lived, no MCP surface. This **recipe** bakes only the stdio MCP adapter (`agentmemory-mcp`,
from the `@agentmemory/mcp` package), which hatago spawns per instance and which proxies the store
over `AGENTMEMORY_URL`.

> **A stack using this recipe must also declare `services: [agentmemory]`.** The adapter is a stdio
> child, so it cannot carry a `service:` ref, which means the store is invisible to the launcher's
> service resolution through this recipe alone. Without that line the adapter still starts, finds
> nothing at :3111, and silently degrades to a 7-tool local-only fallback.

Upstream: <https://github.com/rohitg00/agentmemory>
