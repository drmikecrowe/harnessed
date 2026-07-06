# agentmemory recipe — implementation plan

Goal: expose agentmemory's 53-tool MCP memory surface to a stack as **shared, instance-independent
persistent memory** — one memory server read/written by every agent and every instance, surviving across
sessions.

Upstream: <https://github.com/rohitg00/agentmemory> · TypeScript · Apache-2.0 · npm
`@agentmemory/agentmemory` (latest **0.9.27**) · built on the [iii engine](https://github.com/iii-hq/iii),
pinned to **v0.11.2**.

See the stress-test's `### 2. agentmemory` (classification: **service + recipe**; GAP 1 HTTP-native, GAP 2
hooks) — *analysis only, snippets there are obsolete pre-restructure*. This file is the *how*.

## Recipe shape — a shared SERVICE store + a per-instance stdio child

```
catalog/services/agentmemory/   ← the store sidecar: own image/volume/port, host-published, instance-independent
catalog/recipes/agentmemory/
  recipe.yaml          # one stdio MCP child (the shim) → hatago; expect.mcp
  Dockerfile           # bake the MCP shim into the agent image
  PLAN.md
```

**Two pieces, cleanly split:**

- **The service** is the **data store**: agentmemory's REST API (`:3111`) + its self-managed iii-engine
  (embedded SQLite, "0 external DBs"). Instance-independent, shared, long-lived — the `ping`/hindsight
  model. **No MCP surface, no adapter** — it is just the store, host-published on `:3111`.
- **The recipe** is the **MCP adapter**: agentmemory's stdio shim (`@agentmemory/mcp`, a thin MCP↔REST
  proxy) declared as a **hatago stdio child** in the harness container, pointed at the shared store via
  `AGENTMEMORY_URL`. hatago wraps the shim's stdio → HTTP for the agent.

```
   [ service: agentmemory ]  REST store :3111  (shared, instance-independent, embedded SQLite)
              ▲
              │ http://host.containers.internal:3111   (AGENTMEMORY_URL)
              │
   harness container  (hatago in-container)
     hatago  ──stdio──►  agentmemory-mcp   (the shim; stateless proxy → the store)
     hatago serves one Streamable-HTTP endpoint :3535  ──►  agent connects
```

The shared-memory property lives in the **store**: every instance's shim points at the *same* shared store,
so all agents read/write one memory. The shim is stateless and disposable — per-instance, killed on
`--fresh`, costs nothing. This is the textbook split for a shared, network-reachable data system: state in
the service, the protocol adapter per-instance behind hatago.

> [!IMPORTANT]
> **Contingent on the hatago consolidation**
> ([docs/todos/2026-06-29-hatago-consolidation.md](../../todos/2026-06-29-hatago-consolidation.md)).
> The shim is a hatago stdio child, and recipes can only bake stdio children into the harness image once
> hatago lives in it (today stdio children must be hand-baked into the separate hatago image — the gap the
> consolidation closes). The shim needs no project access (it proxies to the store over the network), so
> this is a *build-mechanism* dependency, not a project-access one. Until the consolidation lands, this
> recipe is correct in shape but cannot ship — do not ship it.

### Critical decision: service, not a harness daemon

agentmemory is a **shared** memory server. The README is explicit: *"All agents share the same memory
server. One server, memories shared across all of them,"* with a first-class multi-agent model (`AGENT_ID`
+ `AGENTMEMORY_AGENT_SCOPE` = `shared`/`isolated`: *"several roles share one agentmemory server
(architect/developer/reviewer/…)"*). That is the textbook **service** lifecycle (instance-independent,
shared, long-lived), **not** a per-project/per-instance harness daemon. Confirmed.

It also needs **no project access**: it stores conversational/semantic *observations* of what the agent
does (tool calls, compressions, sessions), not project files. The `/enrich` endpoint gets file context
*passed by the agent*, not by reading the FS. So the store has no reason to live in the harness instance —
a host-published sidecar with no project mount is correct.

### The MCP-surface finding (decides the split — read this first)

`:3111` is **REST-only**. Verified against `src/triggers/api.ts`: every route is an iii-sdk
`registerTrigger({type:"http", api_path:"/agentmemory/…"})` REST endpoint (`/livez`, `/health`, `/observe`,
`/smart-search`, `/remember`, …). There is **no** `/mcp` / JSON-RPC / `McpServer` / `tools/list` anywhere
in the API source. The README port table's "MCP HTTP" label for `:3111` is misleading — that is the REST
API the tools call internally.

The actual 53-tool MCP surface is a **stdio shim**: `@agentmemory/mcp` (`packages/mcp/bin.mjs` →
`dist/standalone.mjs`), which `agentmemory connect <agent>` wires as `npx -y @agentmemory/mcp` for *every*
supported agent. It is a thin protocol adapter that proxies to `:3111` over REST (`AGENTMEMORY_URL`).

Consequence: the service is **not** itself an MCP endpoint — it is a REST store. The shim is the MCP
adapter, and it belongs as a per-instance hatago stdio child (hatago wraps stdio→HTTP; the consolidation
makes recipe-baked stdio children possible). Nothing in the service speaks MCP.

## catalog/services/agentmemory/service.yaml (sketch — do NOT create yet)

```yaml
# yaml-language-server: $schema=../../../schemas/service.schema.json
# Shared persistent-memory STORE. Own image/container/volume, host-published,
# instance-independent (one memory across all agents/instances — design §9).
# REST-only :3111. No MCP surface — the recipe's stdio shim is the MCP adapter.
name: agentmemory
image: harnessed-agentmemory:latest
volume: agentmemory-data        # persists ~/.agentmemory (store) + iii-engine state
port: 3111                      # the REST store (the recipe shim proxies this over MCP)
healthcheck: "curl -sf http://localhost:3111/agentmemory/livez || exit 1"
```

- `port: 3111` is what the assembler resolves `service: agentmemory` references to. The recipe's shim env
  points here (`AGENTMEMORY_URL=http://host.containers.internal:3111`). The viewer (`:3113`),
  iii-engine (`:3112`/`:49134`) stay internal to the container — not modeled by the single `port:`.
- The real-time viewer (`http://host.containers.internal:3113`) is operator-only and not modeled by the
  service's single `port:`; publish it ad hoc if wanted.

## catalog/services/agentmemory/Dockerfile (sketch — the store image)

Services carry their **own** `FROM` (like `catalog/services/ping/`). The image runs `agentmemory` (which
self-manages its pinned iii-engine as a subprocess). **Two processes** (Node app + iii-engine). **No MCP
adapter, no bridge** — the store is REST-only.

```dockerfile
FROM node:20-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
        && rm -rf /var/lib/apt/lists/*
# pnpm everywhere (NEVER npm/npx). corepack ships pnpm on node:20-slim.
RUN corepack enable && corepack prepare pnpm@9.15.9 --activate

RUN useradd --create-home --uid 1000 harnessed
USER harnessed
ENV PNPM_HOME="/home/harnessed/.local/share/pnpm"
ENV PATH="/home/harnessed/.local/share/pnpm:${PATH}"
WORKDIR /home/harnessed

# 1) the store (REST :3111 + viewer :3113), pinned (no @latest). Lands the `agentmemory` bin.
ARG AGENTMEMORY_VERSION=0.9.27
RUN mkdir -p "$PNPM_HOME/bin" && pnpm add -g "@agentmemory/agentmemory@${AGENTMEMORY_VERSION}"

# 2) Pre-bake the pinned iii-engine binary so first start is deterministic and network-free
#    (the store self-manages the engine; placing it where agentmemory looks — ~/.agentmemory/bin —
#    makes it skip the runtime download).
ARG III_VERSION=0.11.2
RUN mkdir -p /home/harnessed/.agentmemory/bin \
    && curl -fsSL "https://github.com/iii-hq/iii/releases/download/iii/v${III_VERSION}/iii-x86_64-unknown-linux-gnu.tar.gz" \
       | tar -xz -C /home/harnessed/.agentmemory/bin \
    && chmod +x /home/harnessed/.agentmemory/bin/iii
ENV AGENTMEMORY_III_VERSION=${III_VERSION}

# 3) Entrypoint: start the store and wait for livez (foreground = PID 1).
COPY --chown=harnessed:harnessed entrypoint.sh /home/harnessed/entrypoint.sh
EXPOSE 3111
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
    CMD curl -sf http://localhost:3111/agentmemory/livez || exit 1
CMD ["bash", "/home/harnessed/entrypoint.sh"]
```

`entrypoint.sh` (sketch):

```bash
#!/usr/bin/env bash
set -euo pipefail
# Store: REST :3111 (+ viewer :3113); self-spawns the pinned iii-engine (:3112/:49134).
exec agentmemory   # long-lived; runs as harnessed (engine inherits this UID — no distroless 65532 dance)
```

Notes:
- **No `iiidev/iii` Docker image.** We use the iii-engine **binary** (pre-baked), so the engine runs as
  `harnessed` — sidestepping the distroless UID-65532 + `iii-init` chown dance the upstream
  `docker-compose.yml` needs (that compose only runs the engine image; agentmemory itself is never
  containerized upstream — npm-only publish, confirmed: `publish.yml` publishes to npm, no ghcr image).
- **Verify** agentmemory detects the pre-placed `~/.agentmemory/bin/iii` and does not re-fetch at runtime
  (set `AGENTMEMORY_III_VERSION` to the same value). If it insists on managing its own fetch, fall back to
  letting it download on first `svc up` (service containers are host-published with egress) — less
  deterministic.
- **`AGENTMEMORY_SECRET`** is intentionally unset (localhost-open, like `ping`). For a multi-tenant host,
  set it (via varlock) and pass the same secret to the shim env + a hatago `headers:` `Authorization:
  Bearer …` — flagged, not blocking.

## catalog/recipes/agentmemory/recipe.yaml (sketch)

```yaml
name: agentmemory
description: >
  Persistent shared memory for AI coding agents — 53 MCP tools (save / smart-search / sessions /
  governance / …) over a shared memory service. BM25+vector+graph retrieval, session recall, 4-tier
  consolidation. One memory across all agents.

# The stdio shim is a hatago child (in the harness container). It proxies to the shared REST store over
# the network — no project access needed. The agent image gets the shim baked; the store lives in the
# service. Contingent on the consolidation (recipe-baked stdio child).
mcp:
  servers:
    - name: agentmemory
      command: agentmemory-mcp
      transport: stdio
      env:
        AGENTMEMORY_URL: http://host.containers.internal:3111

expect:
  mcp: [agentmemory]      # capability test: agentmemory connected through hatago
```

### catalog/recipes/agentmemory/Dockerfile (sketch — bake the shim)

Appended to `Dockerfile.harnessed-<stack>`. Installs only the MCP shim (the protocol adapter), not the
store (the store is the service).

```dockerfile
USER harnessed
# The stdio MCP shim (proxies to the store over AGENTMEMORY_URL). Confirm at build whether the
# `agentmemory-mcp` bin comes from `@agentmemory/agentmemory` or a separate `@agentmemory/mcp` package,
# and pin the exact source. pnpm — never npm/npx.
ARG AGENTMEMORY_VERSION=0.9.27
RUN pnpm add -g "@agentmemory/agentmemory@${AGENTMEMORY_VERSION}"
```

No `hooks:` block today (see *Hooks (GAP 2)*). No authored skill — upstream offers none; a user may add one
later.

## Hooks (GAP 2 — flagged, not conflated with launcher startup-hooks)

agentmemory's "12 auto hooks" are **Claude Code `PreToolUse` / `PostToolUse` / `SessionStart` /
`PreCompact` / `Stop` / `UserPromptSubmit` tool-hooks** — registered upstream via
`/plugin install agentmemory`, which also wires the stdio MCP shim and 15 skills. These are **GAP 2**
(recipe model has no `hooks:` field merged into `settings.json` today). They are **NOT** the launcher's
startup-hooks ([docs/todos/2026-06-29-startup-hooks.md](../../todos/2026-06-29-startup-hooks.md)) — do not
conflate the two. Startup-hooks fire at instance create/attach and cannot express per-tool-call
interception.

Impact: without the hooks, **auto-capture does not fire** — observations are not recorded silently on
every tool call, and `AGENTMEMORY_INJECT_CONTEXT` recall injection into SessionStart/PreToolUse is inert.
The 53 MCP tools still work fully (manual save/recall directly via the MCP tools — no skill is shipped).
When GAP 2 lands, a recipe `hooks:` block would merge the hook scripts (baked by a then-needed recipe
Dockerfile) into `settings.json`, with hook env pointing the scripts at the service over REST
(`AGENTMEMORY_URL=http://host.containers.internal:3111`). Until then: the agent must call the `memory_*`
tools manually (no skill is shipped, no auto-capture).

## Data model & persistence

- **Embedded SQLite in the iii-engine, "0 external DBs."** No Postgres, no shared-DB service story needed.
- State lives under `~/.agentmemory` (agentmemory's KV + SQLite) plus the iii-engine's working dir. The
  service volume (`agentmemory-data`) is bind-backed at those paths so memory survives `svc down` and grows
  across instances.
- **CONSIDERATION 3 (bind mounts vs named volumes):** this sketch uses a named volume
  (`volume: agentmemory-data`) to match the *current* service model (`catalog/services/ping/`). The
  stress-test's cross-cutting CONSIDERATION 3 recommends repo-wide migration to bind mounts at
  `~/.local/share/harnessed/agentmemory/` (inspectability, portable backups, consistency with the state
  dir). That is a **harness-wide** decision, not agentmemory-specific — when it lands, this service's
  `volume:` semantics change in lockstep with `ping`/hindsight, not separately.
- **Single-writer.** One agentmemory process owns the SQLite store; concurrent agents are *read/write
  clients* over REST, not co-owners. Do not run two `harnessed-agentmemory` containers on the same volume
  (port + lock contention).

## Test stack

```yaml
# catalog/stacks/claude_agentmemory/stack.yaml
name: claude_agentmemory
harness: claude
recipes: [agentmemory]
services: [agentmemory]      # isolated launcher runs ensure_service_up(agentmemory) on launch
```

## Build / test lifecycle

```bash
harnessed svc up agentmemory          # build the service image (first use) + volume + run -d + wait healthcheck
harnessed build claude_agentmemory    # assemble (recipe Dockerfile bakes the shim) + pin gate
harnessed claude_agentmemory          # launch; ensure_service_up starts the store; hatago spawns the shim
harnessed test  claude_agentmemory    # capability report: ✓ agentmemory (mcp) connected through hatago
```

Gated on the consolidation. Manual behavior verification (the capability test only proves the MCP
connects):

- After launch, `curl -fsS http://host.containers.internal:3111/agentmemory/health` returns
  `{status: ok|healthy}` (the store is up and self-managed engine is healthy).
- In the agent, `memory_save` a probe ("agentmemory install verification probe"), then
  `memory_smart_search "install verification probe"` returns it — proves the shim↔store↔hatago chain
  end-to-end and that the tool count is 53 (`memory_*` family), not the 7-tool local-fallback (fallback =
  shim couldn't reach the store — would indicate an `AGENTMEMORY_URL` wiring bug).
- Stop and re-launch a *different* stack with `services: [agentmemory]` against a different project: the
  earlier probe is still recallable — proves the **shared/instance-independent** property that justified
  the service shape.
- `harnessed svc down agentmemory` (volume kept) then `svc up`: memory survives.

## Risks / checks

- **Shim provenance:** confirm at build whether the `agentmemory-mcp` bin comes from
  `@agentmemory/agentmemory` or a separate `@agentmemory/mcp` package, and pin the exact source. The shim
  is the single integration risk — resolve at `harnessed svc up` + `harnessed test` (the tool-count check
  catches a broken proxy as the 7-tool local fallback).
- **`AGENTMEMORY_URL` reachability:** the shim runs in the harness container and reaches the store via
  `host.containers.internal:3111`. This needs the egress-firewall allow rule for
  `host.containers.internal` (`lib/egress-firewall.sh`, already applied per-instance). Verify the shim
  resolves + connects at `harnessed test` (the 7-tool fallback surfaces a connect failure).
- **Pre-baked engine detection:** verify agentmemory uses `~/.agentmemory/bin/iii` and does not re-fetch
  (egress-free determinism). The shim failing to reach the store surfaces as the 7-tool fallback — catch at
  the tool-count check.
- **Pin gate:** `@agentmemory/agentmemory@0.9.27` and the `releases/download/iii/v0.11.2/…` URL must pass
  ASM-02 pin validation (no `@latest`/`:latest`/floating ref). Resolved at `harnessed build`/`svc up`.
- **Multi-tenant exposure:** the store is host-published; on a shared host set `AGENTMEMORY_SECRET`
  (varlock) and pass it to the shim env + hatago `headers:`. Not blocking for single-operator use (matches
  `ping`'s open-localhost posture).
