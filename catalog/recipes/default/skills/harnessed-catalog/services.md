# `service.yaml` — sidecars

A service is a heavy or stateful sidecar with its **own** image, container, and volume, and a
lifecycle **independent of any instance**. Reach for one when the thing is stateful, shared, or
speaks a protocol that is not stdio — not for a light MCP server, which belongs inline as a
`command:`/`args:` stdio child in a recipe.

A service ships three files under `<catalog>/services/<name>/`: `service.yaml`, its own
`Dockerfile`, and the server itself.

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/drmikecrowe/harnessed/main/schemas/service.schema.json
name: <service>                 # required
image: <name>:<tag>             # required — the service's own lineage, not a harness image
scope: global                   # global (default) | project
port: 8080                      # the port INSIDE the container
publish: ephemeral              # ephemeral | stable — how `port` reaches the host (loopback only)
socket: run/<name>.sock         # unix socket relative to the data dir; excludes `publish`
client_env: {VAR: "{host}:{port}"}   # env a CLIENT needs; templated on {host} {port} {socket} {password}
data: {persist: .mydata}        # scope: project — names a recipe `persist:` entry as the data dir
volume: <name>-data             # service-scoped named volume (default `<name>-data`, at /data)
healthcheck: "<cmd>"            # readiness probe `svc up` polls
exclusive_lock: dolt            # basename of a process that flocks the data dir
sync: "<cmd>"                   # run in the container by `harnessed svc sync <name>`
```

Only `name` and `image` are required. A socket-backed service has no `port` at all.

## The two scopes

- **`scope: global`** (default) — ONE shared container, host-published on a loopback port, reached at
  `host.containers.internal:<port>`. Outlives every instance. `claude+X` and `omp+X` share one store.
- **`scope: project`** — ONE container per project, keyed by git-common-dir. For a service holding an
  **exclusive lock over per-project data** that therefore cannot be shared (`dolt sql-server` is the
  motivating case). Its data dir is a bind mount of a `persist:` entry a recipe in the stack
  declares (`data.persist:`), so the service **follows the recipe's placement** rather than owning a
  volume.

## Reaching it

Both published forms bind loopback only, so a service using either **must** authenticate.

| Form | Behavior |
| --- | --- |
| `publish: ephemeral` | the runtime allocates the host port; the launcher reads it back each launch. Nothing recorded, nothing stale — and nothing outside a harnessed launch can be configured with it. |
| `publish: stable` | one free loopback port allocated per project **once**, recorded in `$XDG_DATA_HOME/harnessed/svc-ports.json`. Survives restarts and recreates, so the project can hold its own client config. |
| `socket: run/x.sock` | no host port at all — a filesystem object riding the shared bind mount, so it crosses containers with no network namespace and no port allocation. Requires `scope: project`; mutually exclusive with `publish`. A client that speaks TCP for any part of its work cannot use this. |

`client_env` lives on the service because only the service knows its own protocol's variable names.
Use it — not a recipe `env:` — for anything that does not exist until the container runs; a recipe
`env` value is resolved at emit time. `{host}` resolves per mode: `127.0.0.1` for a host agent,
`host.containers.internal` for a containerized one. The launcher also exports
`$HARNESSED_<NAME>_SOCKET` for socket-backed services.

`exclusive_lock` names the executable that takes the on-disk lock, turning "nothing else may open
this data dir" into an enforced precondition — a *host* process holding that lock otherwise leaves
the sidecar dead on arrival.

## Attaching it

- With an MCP surface → a recipe references it: `mcp.servers[].service: <name>`, `transport: http`.
  The assembler resolves that to a hatago URL-proxy entry.
- Without an MCP surface (a `dolt sql-server` speaks MySQL) → list it under the recipe's `services:`
  or the stack's `services:`. Both lists are unioned; the launcher auto-starts it at launch.

Manage by name: `harnessed svc up|down|list|sync <name>`.

Worked examples: `catalog/services/ping/` (smallest possible) and
`catalog/services/agentmemory/` (host-published, own image/volume,
`exclusive_lock` — and comments explaining each choice). Long form:
`docs/guides/service-authoring.md`.
