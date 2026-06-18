# External Integrations

**Analysis Date:** 2026-06-17

`harnessed` is, at its core, an **integrator**: it composes a harness (claude /
omp), an MCP hub (hatago), MCP servers (stdio children + HTTP sidecars), shared
services, host auth/signing, and supply-chain scanners into one isolated podman
pod. This document covers every external system `harnessed` talks to and the
file that wires it.

The cardinal rule, repeated throughout: **no Docker-out-of-Docker**
(design §15). Every podman/docker call runs on the **host** via
`"$CONTAINER_RUNTIME"` (`lib/harnessed-common.sh:31-40`). The assembler image
only emits files; it never mounts a daemon socket.

## Container Runtime (the core integration)

**podman (preferred) or docker (fallback), rootless.** This is the *only* host
dependency and the substrate every other integration rides on.

- **Detection:** `detect_runtime()` in `lib/harnessed-common.sh:31-40` prefers
  podman, falls back to docker, exits if neither is found.
- **Rootless UID mapping:** every instance gets `--userns=keep-id` so the
  in-container `harnessed` user (UID 1000) maps to the host user and bind-mounted
  project/profile/credential paths are owned correctly. Set once in
  `lib/harnessed-mounts.sh:15`, reused by every stack.
- **Pod model (isolated stacks):** the harness container and hatago are
  **pod members sharing a netns** (`lib/harnessed-isolated.sh:127`), so the
  harness reaches hatago at `http://localhost:3535/mcp` with no cross-container
  networking. `--userns=keep-id` is a **pod-level** property; it is stripped
  from member args (`lib/harnessed-isolated.sh:152-156`).
- **Networking:** rootless **pasta** is the default (NOT a bridge — rootless
  bridges are unsupported on most hosts). Shared services publish their port to
  `0.0.0.0` and pod members reach them via the host gateway
  `host.containers.internal:<port>`. `HARNESSED_NET=<name>` is an explicit
  opt-in bridge override (`lib/harnessed-isolated.sh:111-121`).
- **`host.containers.internal`** is whitelisted by the egress firewall
  (`lib/egress-firewall.sh:62-63`) so the pod can reach host-published services.
- **Transparent mode is degenerate:** a single container, no pod, no hatago
  (`lib/harnessed-transparent.sh:94`).

## hatago — the MCP Hub

**`@himorishige/hatago-mcp-hub@0.0.16`** (pinned, pnpm global — never npm/npx).
hatago aggregates every MCP server a stack declares behind **one**
Streamable-HTTP endpoint, so the harness's `.mcp.json` points at a single URL
instead of N stdio children.

- **Image:** `base/Dockerfile.hatago` (`FROM harnessed-base`). The hub is
  installed via `pnpm add -g "@himorishige/hatago-mcp-hub@${HATAGO_VERSION}"`
  with the managed `lib/pnpm/config.yaml` policy in effect
  (`base/Dockerfile.hatago:24-35`). `PNPM_HOME/bin` is pre-created on PATH
  (`:22-23`).
- **Endpoint:** `hatago serve --http --port 3535` (`base/Dockerfile.hatago:46`).
  The harness reaches `http://localhost:3535/mcp` (the constant
  `tools/harnessed/emit.py:25-26`, `tools/harnessed/capability.py:47`).
- **Pod member:** launched as the second pod member and **waited on** before
  the harness attaches — hatago connects its stdio children, fires
  `tools/list_changed`, THEN binds :3535; attaching before that yields an empty
  MCP connection (`lib/harnessed-isolated.sh:144-171`).
- **Config:** the per-stack `hatago.config.json` (emitted by the assembler,
  `tools/harnessed/emit.py:94-105`) is mounted **read-only** and appended to
  the CMD via `--config` (`lib/harnessed-isolated.sh:144-147`). See the
  generated `profiles/tracer-time/hatago.config.json`:
  ```json
  {"version":1,"logLevel":"info","mcpServers":{"time":{"command":"uvx","args":["mcp-server-time"]}}}
  ```
- **Introspection:** the hub exposes a `hatago://servers` resource (JSON snapshot
  of connected children) used by the capability test
  (`tools/harnessed/capability.py:49`, design §18).

## MCP Servers (two transport shapes)

Recipes declare MCP servers in `recipes/<name>/recipe.yaml` under `mcp.servers`.
The assembler routes each to one of two shapes based on its declaration
(`tools/harnessed/assemble.py`, `tools/harnessed/emit.py`):

### stdio children (hatago wraps stdio → HTTP)

A server with `transport: stdio` + `command` is spawned **by hatago as a child
process**; hatago speaks stdio to it and HTTP to the harness. The harness never
invokes the command directly.

- **Canonical example:** `recipes/time/recipe.yaml:17-22` —
  `command: uvx`, `args: [mcp-server-time]`.
- **Baked for offline determinism:** stdio servers the hatago image must bake
  are recorded in `profiles/<stack>/baked-servers.json`
  (`tools/harnessed/emit.py:108-126`) and installed image-time. Today one is
  baked: **`mcp-server-time==2026.6.4`** via
  `uv tool install` (`base/Dockerfile.hatago:38-39`), so `uvx mcp-server-time`
  resolves offline at run time (egress firewall blocks the network).
- **uvx (not pip):** astral's runner is the convention for Python stdio MCP
  servers; uv's cache makes them resolvable offline.

### HTTP service sidecars (hatago proxies by URL)

A server declared with `service: <name>` + `transport: http` is **resolved by
the assembler to a network-native URL** (`tools/harnessed/assemble.py:51-70`,
plan 04-01) by reading `services/<name>/service.yaml`. hatago proxies it; the
service runs as its **own** container on `harnessed-net`.

- **Canonical example:** `recipes/ping/recipe.yaml:10-14` — `service: ping`
  resolves to `{url: http://ping:8080/mcp, type: http}`.

> **MCP transport note (design §14):** SSE is deprecated in the current MCP spec
> (2025-06-18) and in Claude Code. Use **Streamable HTTP**. hatago's
> stdio→HTTP wrapping is how servers that only speak stdio get exposed over
> Streamable HTTP.

## Shared Services (sidecars over harnessed-net)

A shared service is its **own image/container/volume** on `harnessed-net`, with
a lifecycle **independent of any instance** (design §3/§9). Multiple harnessed
instances attach to the same running service concurrently.

- **Lifecycle:** `harnessed svc up|down|list <service>` in
  `lib/harnessed-services.sh`. `--purge` destroys the named volume; without it
  the volume survives `svc down` (service-scoped persistence — the whole point).
  Isolated stacks auto-start declared services via `ensure_service_up`
  (`lib/harnessed-isolated.sh:133-140`).
- **Service-scoped volumes:** named `<service>-data` (e.g. `ping-data`), NOT
  `harnessed-data-<stack>` — this is what lets `claude+X` and `omp+X` share one
  memory.
- **ping** (`services/ping/`) — the tracer sidecar. A minimal **FastMCP**
  streamable-http server (`services/ping/server.py`) exposing one `ping` tool on
  :8080 and a `/health` route for the container HEALTHCHECK. Notably, it
  explicitly allows `host.containers.internal:*` in FastMCP's
  `TransportSecuritySettings` (`services/ping/server.py:22-25`) because the
  rootless model proxies through that Host header, which DNS-rebinding
  protection rejects by default (421).
- **hindsight / openbrain** — designed (design §3, §9, §16) as heavy/stateful
  sidecars (postgres+MCP). **Not yet implemented**: `services/` currently
  contains only `ping/`.

## Supply-Chain Scanners (build-time gate, BLD-02)

`harnessed build <stack>` runs a **scoped** scan of exactly what that build
assembles — the stack's recipe dirs + the emitted profile, never the whole repo
— then an **image** scan of the built hatago image. Both abort on any HIGH+
(CVSS ≥ 7.0) finding (`tools/harnessed/scan.py:30`, `HIGH = 7.0`).

- **osv-scanner v2.3.8** (credential-free) — both halves:
  - source scan: `osv-scanner scan source --offline --offline-vulnerabilities`
    (`scan.py:169`), offline DB pre-seeded in the image.
  - image scan: host `podman save` → `osv-scanner scan image --offline …
    --archive` (`lib/harnessed-common.sh:131-137`, `scan.py:241`). No daemon
    socket mounted — only the saved tar is passed read-only.
- **pip-audit 2.10.1** (credential-free) — any `requirements.txt` found by
  `rglob` in a recipe dir or the emitted profile; findings are **warnings only**
  (its JSON carries no CVSS, so it cannot gate) (`scan.py:186-199, 222-223`).
- **CVSS gating** is computed in pure Python (`scan.py:72-115`) — the FIRST.org
  v3.1 base-score formula — so the HIGH decision is unit-testable and does not
  depend on scanner exit codes (which are deliberately swallowed, `scan.py:160`).

### Token-gated scanners (designed, warn-and-skip)

**snyk** and **Socket.dev** are in the design (`docs/harnessed-design.md` §7,
CLAUDE.md tool table) as token-gated extras (`SNYK_TOKEN`,
`SOCKET_SECURITY_API_KEY`). The contract is **warn-and-skip**: if the token is
absent, skip that scanner silently and keep the build non-interactive; the
credential-free osv-scanner + pip-audit baseline gate always runs. `harnessed
auth snyk|socket` is the designed one-time setup path. **Not yet implemented**
in `scan.py` — only osv-scanner + pip-audit are wired today.

## 1Password (SSH signing + optional secrets)

- **SSH commit signing (`op-ssh-sign`)** — the 1Password CLI + desktop app are
  installed from 1Password's apt repo in `base/Dockerfile.harnessed-base:27-33`
  (and the legacy root `Dockerfile:30-35`).
- **SSH agent socket** — the default `SSH_AUTH_SOCK` source. Mounted from
  `~/.1password/agent.sock` and exported
  (`lib/harnessed-mounts.sh:23-27`).
- **Optional secrets resolution (design §16)** — varlock + `op` resolve
  `op(op://Vault/Item/field)` refs into env. The repo ships a ready-to-copy
  `.env.schema.example` (the `@env-spec` DSL with `@varlock/1password-plugin@0.3.2` +
  `@initOp(allowAppAuth=true)`, holding the `SNYK_TOKEN` / `SOCKET_SECURITY_API_KEY` refs); copy it to
  `~/.config/harnessed/.env.schema` to opt in. Resolution runs **on the host** via
  `lib/harnessed-secrets.sh::resolve_secret_env`, which calls `varlock load --format env` and spreads
  the resolved dotenv into the container as a mode-0600 temp `--env-file` (unlinked after launch). It
  reaches **all four** launch paths: the isolated pod (`harnessed-isolated.sh`), the transparent
  instance (`harnessed-transparent.sh`), sidecar services (`harnessed-services.sh` +
  `~/.config/<service>/.env.schema`), and the build scan (`harnessed-common.sh build_stack`). See
  STACK.md → Secrets.

Resolution model (design §16): 1Password's desktop app authorizes the `op` CLI by *calling
application* (your terminal), so **app-auth runs on the host** — an `op` inside the throwaway
container has no host app to bind the grant to and fails ("cannot connect to 1Password app") no
matter which socket is mounted. The `~/.1password/agent.sock` mount above is the **SSH agent** (git
signing), not the `op` app-auth transport. Hosts without `varlock` fall back to in-container
resolution, which then requires `OP_SERVICE_ACCOUNT_TOKEN` (HTTPS bearer auth — no desktop app);
scope that token narrowly, since it leaks into any process sharing the env.

## Host Integration Mounts (§4a — shared by EVERY stack)

`lib/harnessed-mounts.sh:harnessed_host_integration_mounts()` is sourced by both
the transparent and isolated launchers and appends podman/docker `-v`/`--device`
flags to a shared `MOUNT_ARGS` array. These are **operational** mounts
(auth/signing/agents/firewall) — not the config-experiment surface, which is
mode-specific (§4b). Everything is conditional on the host actually having the
artifact, so a bare host still launches.

| Integration | Mount | File |
|---|---|---|
| 1Password SSH agent | `~/.1password/agent.sock` → `$CONTAINER_HOME/.1password/agent.sock`, `SSH_AUTH_SOCK` set | `lib/harnessed-mounts.sh:23-27` |
| GPG agent SSH socket (YubiKey) | `/run/user/$UID/gnupg/S.gpg-agent.ssh` → `.gnupg-sockets/S.gpg-agent.ssh` | `:30-35` |
| GPG config (YubiKey commit/SSH signing) | `~/.gnupg` ro | `:38` |
| YubiKey USB device | `--device /dev/bus/usb/$bus/$dev` (Yubico vendor 1050, probed via `lsusb`) | `:41-47` |
| Z.AI config (GLM models) | `~/.zai.json` ro | `:50` |
| Per-tool `~/.config/<tool>` dirs | e.g. nvim; from `extra-tools.txt`, with a name-remap table (`neovim→nvim`, skip-list for `ast-grep`/`markdownlint-cli2`) | `:54-68` |
| Git config | `~/.config/git` ro, else legacy `~/.gitconfig` ro | `:71-75` |
| Host machine-id | `/etc/machine-id` ro (lets Claude Code see the same machine, avoids re-auth) | `:78` |
| SSH keys/config | `~/.ssh` ro | `:81` |
| Egress firewall script | `lib/egress-firewall.sh` → `/usr/local/sbin/egress-firewall` ro, applied via `--cap-add NET_ADMIN` | `:20`, applied `lib/harnessed-common.sh:apply_firewall` |
| Project | `$project_path` → `$CONTAINER_HOME/<relpath>`, set as workdir | `:16-17` |

### Egress firewall

`lib/egress-firewall.sh` is the primary exfiltration defense (closes the vector
identified in agentic-AI security research). It flushes `OUTPUT`, sets default
`DROP`, and allowlists a fixed domain set (`lib/egress-firewall.sh:11-34`):
Anthropic/Claude API, GitHub (git + gh + releases + raw), npm registry, PyPI,
and `mise.jdx.dev`. Extra domains (e.g. a Z.AI endpoint read from `~/.zai.json`
via jq) are appended at apply time (`lib/harnessed-transparent.sh:53-58`). It
also unblocks the podman host-gateway `host.containers.internal` so shared
services are reachable (`:60-63`). Re-applied each session; idempotent via a
`/run/egress-firewall-active` flag. Skip with `--no-firewall`.

## Harnesses (the things being launched)

Exactly **one** harness per stack (design §8), selected by `harness:` in
`stack.yaml`:

- **claude** (`harnessed-claude` image) — `base/Dockerfile.harnessed-claude`
  (`FROM harnessed-base` + the official Claude Code installer). The isolated
  launcher attaches via `claude --mcp-config <profile>/.claude/.mcp.json
  --strict-mcp-config` (`lib/harnessed-isolated.sh:191-192`) so only the
  profile's hatago endpoint loads and account-synced servers never leak in.
- **omp** (`harnessed-omp` image) — `base/Dockerfile.harnessed-omp`. Built
  **lazily** only when an `harness: omp` stack first launches
  (`lib/harnessed-common.sh:159-169`, plan 04-03 / HRN-01), so claude-only users
  never pull omp + the bridge. **omp v16.0.1** via
  `mise use -g "github:can1357/oh-my-pi@${OMP_VERSION}"`, plus **bun** (the
  bridge's plugins are Bun-based) and the pre-installed
  **`@drmikecrowe/omp-claude-hooks-bridge`** extension
  (`base/Dockerfile.harnessed-omp:17-25`).
- **Canonical format = Claude Code** (design §8). omp consumes the **same**
  `.claude/` profile as claude via the bridge — no re-authoring. The omp base
  recipe (`recipes/omp/recipe.yaml`) only **documents** the bridge extension
  dependency; it contributes no profile files of its own.
- **Transparent** (`stacks/transparent/`) mounts host `~/.claude`,
  `~/.codex`, `~/.config/opencode`, `~/.gemini` **live** (the degenerate,
  "my-laptop-sandboxed" case). It is the old `container` SKU; the `container`
  script is now a thin alias → `harnessed transparent` (`container:12`).

## Summary — what talks to what

```
HOST (podman/docker rootless)
  │
  ├── harnessed (bash bootstrap) ──lib/harnessed-*.sh──▶ podman pod create/run/exec
  │        │
  │        └── harnessed-tools (python assembler, emit-only) ──▶ profiles/<stack>/ + scans
  │
  └── pod: harnessed-<stack>-<proj>  (shared netns)
        ├── [ harness: claude | omp ]  ──▶ .mcp.json → http://localhost:3535/mcp
        │      mounts: §4a host-integration + profile (.claude/) + ro credential
        │
        └── [ hatago hub ]  :3535
               ├── stdio children (uvx mcp-server-time, baked offline)
               └── HTTP proxies ──▶ shared services on harnessed-net
                                      (ping FastMCP :8080; hindsight/openbrain designed)

SCANNERS (build-time): osv-scanner + pip-audit (always) ▸ snyk/Socket (token, opt-in)
SECRETS (opt-in):      varlock + 1Password op  ▸  inert unless ~/.config/harnessed/.env.schema
```
