# headroom

Context compression on demand — `headroom_compress`, `headroom_retrieve`, `headroom_stats`. Squeezes
JSON, code, and other structured payloads before they reach the model, and lets the agent pull the
full text back when it actually needs it.

Wired as a **stdio MCP server** — hatago spawns it as a child.

Upstream: <https://github.com/headroomlabs-ai/headroom>
