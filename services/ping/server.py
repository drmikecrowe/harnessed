"""ping — a minimal FastMCP streamable-http tracer service (plan 04-01 / SVC-01).

Exposes one `ping` tool over MCP streamable-http on :8080 and a plain /health
endpoint for container healthchecks. Lightweight: no external state, no DB.

The service runs standalone on harnessed-net; hatago proxies it as a network-native
MCP server ({url: http://ping:8080/mcp, type: http}). The /health route is what
`svc up` polls to confirm readiness (design §9 lifecycle).
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from starlette.responses import PlainTextResponse
from starlette.routing import Route

mcp = FastMCP("ping")


@mcp.tool()
def ping() -> str:
    """Return pong."""
    return "pong"


async def _health(_request):
    """Readiness probe for the container HEALTHCHECK and `svc up`."""
    return PlainTextResponse("ok")


# FastMCP.streamable_http_app() returns a Starlette app whose MCP endpoint lives at /mcp.
# We add /health alongside it on the same port so the container HEALTHCHECK can probe it.
app = mcp.streamable_http_app()
app.router.routes.insert(0, Route("/health", _health, methods=["GET"]))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
