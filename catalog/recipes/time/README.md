# time

Time and timezone queries — current time, conversions between zones.

Wired as a **stdio MCP server**: hatago spawns `uvx mcp-server-time` as a child. Nothing is baked
into the image and the server needs no network at run time (the tz database is local).

Upstream: <https://github.com/modelcontextprotocol/servers/tree/main/src/time>
