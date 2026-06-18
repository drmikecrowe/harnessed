# Authoring shared services

A **shared service** is a heavy or stateful sidecar (hindsight = postgres+MCP, openbrain, a custom
MCP tool) that runs as its **own** image/container/volume on the shared network, with a lifecycle
**independent of any instance**. Multiple instances attach to one running service concurrently;
`claude+hindsight` and `omp+hindsight` read and write **one** memory (design §3, §9).

For the *why* (why services are service-scoped, why they outlive instances, why they're separate
images), read [docs/harnessed-design.md §3 & §9](../harnessed-design.md). This guide shows the *how*
with a worked example from [`services/ping/`](../../services/ping/).

## What a service is

A service lives at `services/<name>/` and ships **three** things:

| File | Role |
| --- | --- |
| `services/<name>/service.yaml` | the manifest: `name`, `image`, `port`, `volume`, `healthcheck` |
| `services/<name>/Dockerfile` | the service's **own** image lineage (independent of the harness images) |
| the server itself (e.g. `server.py`) | the actual MCP server (Streamable HTTP) |

You manage services by name with `harnessed svc up|down|list` (see [lib/harnessed-services.sh](../../lib/harnessed-services.sh)), and a stack references one by listing it under `services:`.

## The `service.yaml` manifest

The typed model lives in [`tools/harnessed/schema.py`](../../tools/harnessed/schema.py) (`ServiceDef`).
Flat scalars:

```yaml
name: <service>                       # required
image: <name>:<tag>                   # required — the service's own image
volume: <volume-name>                 # optional — service-scoped named volume (survives svc down)
port: <port>                          # required — the port the server listens on
healthcheck: "<cmd>"                  # optional — readiness probe for `svc up` to poll
```

A recipe references a service via `mcp.servers[].service: <name>`; the assembler resolves that to a
hatago URL-proxy entry pointing at `http://<name>:<port>/mcp` (see *Attaching from a recipe* below).

## Worked example: the `ping` service

`ping` is the smallest shared-service sidecar — one `ping` MCP tool over Streamable HTTP, no
external state. All three files:

### `services/ping/service.yaml`

```yaml
name: ping
image: harnessed-ping:latest
volume: ping-data
port: 8080
healthcheck: "curl -sf http://localhost:8080/health || exit 1"
```

- `image: harnessed-ping:latest` — `svc up` builds this from the service's own `Dockerfile` on first
  use (and the build-time BLD-02 image scan gates it).
- `volume: ping-data` — service-scoped; it **survives** `svc down` by default (that's the value — one
  memory across instances). `--purge` is the explicit destroy.
- `healthcheck` — what `svc up` polls to confirm readiness before returning.

### `services/ping/Dockerfile`

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir "mcp[cli]"
WORKDIR /app
COPY server.py /app/server.py
EXPOSE 8080
HEALTHCHECK --interval=5s --timeout=3s --start-period=3s --retries=3 \
    CMD curl -sf http://localhost:8080/health || exit 1
CMD ["python", "/app/server.py"]
```

The service has its **own** image lineage (`FROM python:3.12-slim`) — it is not built `FROM` any
harness image. The `HEALTHCHECK` mirrors the manifest's `healthcheck` so `podman` and `svc up` agree
on readiness.

### `services/ping/server.py`

A FastMCP server over **Streamable HTTP**, with a `/health` route alongside the MCP endpoint:

```python
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import PlainTextResponse
from starlette.routing import Route

mcp = FastMCP("ping")
# FastMCP's DNS-rebinding protection rejects the podman host-gateway Host header by default,
# so allow it alongside the localhost defaults (the service is proxied via host.containers.internal).
mcp.settings.transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*", "host.containers.internal:*"],
)

@mcp.tool()
def ping() -> str:
    """Return pong."""
    return "pong"

async def _health(_request):
    return PlainTextResponse("ok")

# FastMCP.streamable_http_app() serves the MCP endpoint at /mcp; add /health on the same port.
app = mcp.streamable_http_app()
app.router.routes.insert(0, Route("/health", _health, methods=["GET"]))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
```

- **Streamable HTTP** — one endpoint (`/mcp`), `POST` + optional `GET`/SSE stream. **SSE is
  deprecated** in the current MCP spec (2025-06-18) and in Claude Code; do not author new SSE
  servers (see the "What NOT to Use" table in [`CLAUDE.md`](../../CLAUDE.md)).
- A separate `/health` route lets the container `HEALTHCHECK` (and `svc up`) probe readiness without
  speaking MCP.
- The `allowed_hosts` entry for `host.containers.internal` matters on the default rootless
  networking model (see below).

## Lifecycle

`harnessed svc up|down|list` manages shared services by name — independent of any instance
([lib/harnessed-services.sh](../../lib/harnessed-services.sh)):

```bash
harnessed svc up ping        # build image (first use) + create volume + run -d + wait for healthcheck
harnessed svc list           # enumerate running harnessed-managed services
harnessed svc down ping      # stop + remove the container (volume KEPT)
harnessed svc down ping --purge   # stop + remove the container AND the volume
```

The service is labelled `harnessed-service=<name>` and runs on the shared network; it is **not** a
pod member. A stack that declares the service **auto-starts** it on launch:

```yaml
# stacks/ping-time/stack.yaml
name: ping-time
config: isolated
harness: claude
recipes: [time, ping]
services: [ping]            # ← the isolated launcher runs ensure_service_up(ping) on launch
```

The service outlives the instance — stop the stack and the sidecar keeps running, so the next
instance (or another stack) attaches to the same state.

## Attaching from a recipe

A recipe references a service via `mcp.servers[].service`. The assembler resolves the name to a
hatago URL-proxy entry, so hatago proxies the network-native server:

```yaml
# recipes/ping/recipe.yaml
mcp:
  servers:
    - name: ping
      service: ping        # ← resolved to http://ping:8080/mcp
      transport: http
```

**Networking note:** by default isolated stacks use rootless (pasta) networking, so pod members reach
a shared service via the host gateway `host.containers.internal:<port>`. That is why `server.py`
adds `host.containers.internal` to FastMCP's allowed hosts. On hosts that support rootless bridges,
set `HARNESSED_NET=<name>` and members resolve the service by DNS name instead (`http://<name>:<port>`).

## See also

- [docs/harnessed-design.md §3 & §9](../harnessed-design.md) — the *why* (runtime pod, service-scoped state & lifecycle).
- [Recipe-authoring guide](recipe-authoring.md) — the service-ref MCP shape (`service:` / `transport: http`).
- [Stacks guide](stacks.md) — declaring `services:` in a stack manifest.
- [`services/ping/`](../../services/ping/) — the worked example (manifest + image + server).
- [`tools/harnessed/schema.py`](../../tools/harnessed/schema.py) — the typed `ServiceDef` model.
