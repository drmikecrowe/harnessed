# Architecture

**Analysis Date:** 2026-06-22

`harnessed` composes hand-authored recipes into named stacks, assembles them into
committed profiles, and launches isolated shared-netns groups (a podman **pod**, or a
docker shared-netns pair via `lib/harnessed-runtime.sh`) — a **harness container**
(`claude`, `omp`, `opencode`, `gemini`, `antigravity`, or `codex`) plus a **hatago** MCP
hub, with optional shared service sidecars. The architectural source of truth is
`docs/harnessed-design.md`; this document distills the *implemented* architecture and the
rootless networking model the launcher actually ships.

---

## Pattern

**Emit-only build-time assembler + host-native launcher. No Docker-out-of-Docker (DooD).**

Two engines, one hard boundary between them:

| Engine | Language | Runs where | Touches podman? |
|---|---|---|---|
| **Assembler** (`tools/harnessed/`) | Python | inside the `harnessed-tools` image | **Never.** Only reads/writes a mounted dir and *emits* files. |
| **Launcher** (`harnessed` + `lib/*.sh`) | Bash | on the host | **Yes — natively.** Every `podman build`/`podman run`/`podman pod` runs on the host. |

The rationale (design §15) is that splitting "generate the build/run inputs" (needs
Python) from "execute `podman build`/`podman run`" (needs the daemon) removes every cost
of driving the daemon from inside a container:

- **No API socket to mount, no `CONTAINER_HOST`/`DOCKER_HOST`.** podman is invoked
  directly on the host.
- **No host-absolute-path footgun.** The launcher runs on the host, so `$HOME`/`$PWD`/
  project paths are host-native by construction — the classic DooD bind-path gotcha
  cannot occur.
- **Clean TTY for free.** The interactive `podman exec -it` attach is host-native.

Within that, the runtime model is **composition at runtime, not at build time** (§3/§6):
`FROM` is linear inheritance and cannot union two sibling systems, so a running stack is
composed in a **shared-netns group** (podman pod, or docker `--network container:` pair,
via `lib/harnessed-runtime.sh`) — never baked into one image.

### Rootless networking model (the implemented truth)

This is the single most-load-bearing invariant in the runtime, and the design that the
launcher commits to:

- **Default networking is rootless `pasta`.** Pods/instances are created with **no
  `--network` flag** and therefore get podman's default rootless (pasta) netns — *not* a
  bridge. A rootless bridge is unsupported on most hosts (`netavark: create bridge:
  Operation not supported`), so the launcher never assumes one. See
  `lib/harnessed-isolated.sh:140-150`.
- **Shared services publish their port to `0.0.0.0`.** `svc_up` runs the sidecar with
  `-p "$port:$port"` and *no* `--network` flag (`lib/harnessed-services.sh:120-127`); the
  comment at `lib/harnessed-services.sh:101-105` names this the "plan 04-01 rootless fix."
- **Peers reach a service via the podman host gateway.** Because the service is published
  to the host and the pod shares a rootless netns, the harness/hatago reach it at
  `host.containers.internal:<port>`. The assembler bakes this URL into the hatago config
  at *emit time*: `_resolve_service_servers` in `tools/harnessed/assemble.py:51-70` sets
  `server.url = f"http://host.containers.internal:{svc.port}/mcp"`.
- **`harnessed-net` is an explicit opt-in bridge**, not the default. `HARNESSED_NET` env
  var (empty by default) is the only thing that turns the bridge on for
  bridge-capable hosts (`lib/harnessed-isolated.sh:147-150`,
  `lib/harnessed-services.sh:27-30`). On such a host, services become reachable by DNS
  name (`http://<service>:<port>`); everywhere else the publish + host-gateway model is
  authoritative.

Two operator-side prerequisites this model depends on (documented in design §9, not
implemented by the launch path — they already ship):

1. **An egress-firewall allow rule for `host.containers.internal`.**
   `lib/egress-firewall.sh:55-63` resolves `PODMAN_GW=$(getent ahosts
   host.containers.internal …)` and adds an iptables allow for it. Because iptables is
   netns-wide, this unblocks the whole pod, including the hatago MCP proxy.
2. **FastMCP `allowed_hosts`.** A Streamable-HTTP service proxied over
   `host.containers.internal` MUST add it to `TransportSecuritySettings.allowed_hosts`,
   or FastMCP's DNS-rebinding protection returns `421 Misdirected Request`. Canonical
   implementation: `services/ping/server.py:19-26`.

> **Read the old docs with care.** Any framing that puts shared services "on
> `harnessed-net`" by default, or describes `harnessed-net` as the primary/only network,
> is stale. `harnessed-net` exists (idempotent in `ensure_named_net` /
> `ensure_harnessed_net`) but is inert unless `HARNESSED_NET` is set.

---

## Layers

Five layers, ordered build-time → run-time. Each layer only depends on the layer(s) above
it in this list.

### 1. Authored inputs (data, not code)
- `recipes/<name>/recipe.yaml` — one hand-authored integration definition per project
  (MCP servers + file-extension dirs). See `recipes/time/recipe.yaml`.
- `stacks/<name>/stack.yaml` — composes a harness + a chosen set of recipes (+ services).
  See `stacks/tracer-time/stack.yaml`.
- `services/<name>/service.yaml` — a shared sidecar definition
  (image/port/volume/healthcheck). See `services/ping/service.yaml`.

### 2. Build-time assembler — `tools/harnessed/` (Python, emit-only)
Runs inside the `harnessed-tools` image. Holds *all* assembly logic: parse/validate
YAML, fan skills/commands with collision-checking, merge `hatago.config.json`, generate
the harness `.mcp.json`/`settings.json`, lint recipes, scan supply-chain. It reads
`recipes/`+`stacks/`+`services/` under a root and **emits** `profiles/<stack>/` +
`hatago.config.json` + a baked-servers manifest. It never invokes podman.

### 3. Image tier — `base/`, `services/`, `tools/Dockerfile`
Standalone, independently-versioned images, built by the **host** (`podman build`):
- `base/Dockerfile.harnessed-base` → `base/Dockerfile.harnessed-claude` /
  `.harnessed-omp` / `.harnessed-opencode` / `.harnessed-gemini` /
  `.harnessed-antigravity` / `.harnessed-codex` (lineage via `FROM`).
- `base/Dockerfile.hatago` — the MCP hub + light stdio servers baked in.
- `services/<name>/Dockerfile` — one per heavy/stateful sidecar.
- `tools/Dockerfile` — the assembler image itself.

### 4. Generated artifacts — `profiles/<stack>/` (committed, mounted)
The assembler's output. Committed to git and **mounted** into the harness container at
run time: `.claude/{skills,commands,agents,hooks,rules}/`, `.mcp.json`, `settings.json`,
`hatago.config.json`, `baked-servers.json`. See `profiles/tracer-time/`.

### 5. Host runtime — `harnessed` + `lib/*.sh` (bash)
The launcher. Computes the §4a/§4b mounts on the host, runs the shared-netns group via
host `$CONTAINER_RUNTIME` (podman pod, or docker pair — abstracted by
`lib/harnessed-runtime.sh`), attaches with host-native `podman exec -it`. Also drives the
assembler image (`build_stack` runs `podman run harnessed-tools assemble …`).

> **Layering rule of thumb:** `tools/` emits files; `lib/` runs containers. If you are
> tempted to call podman from Python, or to parse YAML from bash, you are crossing the
> boundary in the wrong direction.

---

## Entry Points

### `harnessed` — the host launcher (`harnessed`)
A thin host bash bootstrap (412 lines). It sources `lib/harnessed-common.sh`, then runs a
single `while [[ $# -gt 0 ]]; do case "$1" in …` arg-parse loop (`harnessed:92-239`).
Bare invocation (`$# == 0`) prints help instead of silently launching transparent
(`harnessed:91`). The case arms dispatch to one of three shapes:

1. **Top-level subcommands** (each dispatches then `exit 0` — not a launch path):
   - `build [<stack>]` → `build_stack` (assemble + host build) or `build_images`
     (rebuild base/claude/hatago). `harnessed:318-327`
   - `test <stack>` → ensures the build, then runs the host-side capability test via
     `python -m harnessed.cli test`. `harnessed:329-379`
   - `svc up|down|list <service>` → sources `lib/harnessed-services.sh` and dispatches.
     `harnessed:258-273`
   - `list | stop <stack> | rm <stack> | new <stack> | install | uninstall` → source
     `lib/harnessed-cli.sh` and dispatch. `harnessed:278-297`
   - `auth snyk|socket` → one-shot scanner-token setup (sources secrets lib). `harnessed:298-305`
   - `rescan` → SEC-04 nightly image re-scan (sources rescan lib). `harnessed:306-315`

2. **Launch path** — the fallthrough. First bareword is a stack name (if
   `stacks/$1/stack.yaml` exists) or a project path (if it's a directory); second bareword
   is the project path. Resolves to an instance name, then `case "$STACK"` dispatches to
   the mode launcher (`harnessed:394-411`):
   - `transparent` → `lib/harnessed-transparent.sh::harnessed_transparent`
   - anything else → `lib/harnessed-isolated.sh::harnessed_isolated`

3. **Legacy flags** (`--list`/`--stop`/`--remove`/`--clean`/`--fresh`/`--no-firewall`) keep
   back-compat with the old `container` command.

`detect_runtime` (run at the top) prefers podman, falls back to docker — podman/docker is
the only host dependency.

### `tools/harnessed/cli.py` — the assembler CLI entrypoint
`python -m harnessed.cli`, run *inside* the `harnessed-tools` image by `build_stack`. An
argparse CLI with five subcommands (`cli.py:28-110`):

- **`assemble <stack> --build-dir <dir> [--root <dir>]`** — the core emit step. Calls
  `assemble.assemble()`; writes `profiles/<stack>/` + `hatago.config.json`.
- **`test <stack> [--project …] [--keep] [--json]`** — the per-stack capability test
  (design §18). Launches the stack `--fresh` headless via the *host* `harnessed` launcher,
  introspects the live instance, asserts the manifest's declared capabilities are present,
  and renders a markdown report (or JSON for CI). This one subcommand drives host podman —
  it is the exception that proves the emit-only rule, and it runs host-native, not inside
  the tools image.
- **`scan <stack> --build-dir <dir>`** — the scoped source/Python supply-chain scan
  (BLD-02a); exit 1 on any HIGH+ finding.
- **`scan-image <archive>`** — the image-archive scan (osv-scanner over a `podman save`
  tar); exit 1 on any HIGH+ finding. (BLD-02b)
- **`scan-image-online <archive>`** — the ONLINE variant (fresh osv.dev DB) used by the
  SEC-04 nightly re-scan.

---

## Data Flow: assemble → build → launch

### 1. Author
Write `recipes/<name>/recipe.yaml` (MCP servers + skills/commands) and compose it in
`stacks/<name>/stack.yaml`:

```yaml
# stacks/tracer-time/stack.yaml
name: tracer-time
config: isolated
harness: claude
recipes: [time]
```

```yaml
# recipes/time/recipe.yaml — a light stdio server + a standalone skill
mcp:
  servers:
    - name: time
      command: uvx
      args: [mcp-server-time]
      transport: stdio          # stdio → hatago runs it as a child
skills:
  - path: skills/time-helper    # standalone dir, fanned into .claude/skills/time-helper
```

### 2. `harnessed build <stack>` → `lib/harnessed-common.sh::build_stack`
Five host-driven steps (`lib/harnessed-common.sh:115-191`):

```bash
# (a) ensure the emit-only assembler image exists (built from tools/Dockerfile)
ensure_tools_image

# (b) EMIT: the assembler only reads/writes the mounted ROOT; it never drives podman.
#     Fail-fast: a recipe lint / collision abort propagates via errexit before emit.
"$CONTAINER_RUNTIME" run --rm $(rt_userns_args) \
    -v "$ROOT":"$ROOT" -w "$ROOT" \
    "$HARNESSED_TOOLS_IMAGE" assemble "$stack" --root "$ROOT" --build-dir "$ROOT"

# (c) SOURCE SCAN (BLD-02a): scoped to THIS stack's recipe dirs + emitted profile only.
"$CONTAINER_RUNTIME" run --rm … "$HARNESSED_TOOLS_IMAGE" scan "$stack" --root "$ROOT" --build-dir "$ROOT"

# (d) BUILD: the HOST builds the hatago image from base/Dockerfile.hatago.
"$CONTAINER_RUNTIME" build -t "$HARNESSED_HATAGO_IMAGE" -f …/base/Dockerfile.hatago …

# (e) IMAGE SCAN (BLD-02b): host → tar → osv-scanner in a throwaway tools container.
"$CONTAINER_RUNTIME" save "$HARNESSED_HATAGO_IMAGE" -o "$img_tar"
"$CONTAINER_RUNTIME" run --rm -v "$img_tar":"$img_tar":ro "$HARNESSED_TOOLS_IMAGE" scan-image "$img_tar"
```

Inside step (b), `tools/harnessed/assemble.py::assemble` runs the full pipeline
(`assemble.py:73-112`):

```
load_stack_with_recipes(root, stack_name)            # parse stack.yaml + every recipe
  → validate_no_raw_npm(recipe)  for each recipe     # BLD-03 lint, fail-fast, pre-emit
  → LinkSyncer.add_recipe(recipe)  for each recipe   # register skills/commands, collision-check
  → _merge_servers(recipes)                          # collect MCP servers, collision-check on name
  → _resolve_service_servers(servers, root)          # service: refs → http://host.containers.internal:<port>/mcp
  → emit.reset_profile / ensure_profile_tree         # wipe + recreate .claude/{skills,commands,…}/
  → syncer.fan(harness_dir)                          # copytree each registered skill/command
  → emit.write_mcp_json(harness_dir)                 # .mcp.json = ONE entry → hatago endpoint
  → emit.write_settings_json(harness_dir, servers)   # pre-approve the hatago hub's tools
  → emit.write_hatago_config(profile_dir, servers)   # hatago.config.json (children + URL proxies)
  → emit.write_baked_manifest(profile_dir, stack, baked)  # which stdio servers the hatago image bakes
```

Both collision checks (`LinkSyncer._register` on skill/command names,
`_merge_servers` on MCP server names) raise **before any file is written**, so a failed
build leaves no half-emitted profile.

### 3. `harnessed <stack> [path]` → `lib/harnessed-isolated.sh::harnessed_isolated`
The launch path (`lib/harnessed-isolated.sh:33-274`). Per-instance state is the pivot:

```bash
# Copy-on-start the committed profile into a per-project/per-stack state dir (PERSISTENT
# by default; wiped only on first create or under --fresh). Keyed by a LEGIBLE flattened
# project path + stack, NOT the opaque instance hash. The profile is the immutable template.
local state_project="${relpath//'/'/-}"
local run_claude="${XDG_STATE_HOME:-$HOME/.local/state}/harnessed/$state_project/$stack/.claude"
if [ "$fresh" = "true" ] || [ ! -d "$run_claude" ]; then
    rm -rf "$run_claude"; cp -a "$profile_dir/.claude" "$run_claude"
fi

# Compose the shared-netns group. keep-id maps the container user → host UID; userns is a
# POD-level property. Rootless (pasta) networking by default — NO bridge.
local pod_net_args=()
if [ -n "${HARNESSED_NET:-}" ]; then              # the ONLY thing that turns the bridge on
    ensure_named_net "$HARNESSED_NET"
    pod_net_args=( --network "$HARNESSED_NET" )
fi
rt_group_create "$instance" "$pod" "${pod_net_args[@]}"

# Auto-start the stack's declared shared services (design §9). Each service is a STANDALONE
# container that publishes its port to 0.0.0.0 — NOT a pod member. Its lifecycle is
# independent of this pod.
for svc in $svc_line; do ensure_service_up "$svc"; done

# hatago member: one Streamable-HTTP endpoint on :3535 from the mounted per-stack config.
"$CONTAINER_RUNTIME" run -d $(rt_hatago_placement "$instance" "$pod") --name "${instance}-hatago" \
    -v "$profile_dir/hatago.config.json:…/hatago.config.json:ro" \
    "$HARNESSED_HATAGO_IMAGE" hatago serve --http --port "$HATAGO_PORT" --config …

# harness member: profile-only config + §4a + §4b mounts; sleeps until attach.
"$CONTAINER_RUNTIME" run -d $(rt_harness_placement "$instance" "$pod") --name "$instance" \
    "${member_args[@]}" "$harness_image" sleep infinity

apply_firewall "$instance"           # egress firewall (NET_ADMIN) on the harness container
# …wait for hatago's port (shared netns → localhost:3535)…
"$CONTAINER_RUNTIME" exec -it … "$instance" bash -lc "$mise_init && claude --mcp-config '$mcp_cfg' --strict-mcp-config"
```

The harness `.mcp.json` points at exactly **one** endpoint —
`http://localhost:3535/mcp` (`emit.py::HATAGO_ENDPOINT`) — because pod members share a
netns. hatago aggregates every MCP server behind that one endpoint: light stdio servers
run as hatago's children (baked into the hatago image), heavy services are proxied by URL
over the network at `http://host.containers.internal:<port>/mcp`.

> **Provider portability:** the launch path above is the podman shape.
> `lib/harnessed-runtime.sh` (`rt_*` helpers) abstracts the shared-netns group so the same
> launcher also runs on docker (hatago starts first, the harness joins with `--network
> container:<instance>-hatago`; no `--userns` — rootless docker remaps uids daemon-side).
> Apple `container` (one VM+IP per container, no shared netns) is a tracked follow-up, not
> yet supported.

`transparent` is the degenerate case (`lib/harnessed-transparent.sh`): no pod, no hatago,
no services — just a harness container with the host config mounted live.

### Networking recap (service-referenced recipe → live instance)

```
recipe declares:  mcp.servers[].service: ping        (no command → not a stdio child)
                                                              │
  emit time                                                   ▼
  _resolve_service_servers ──► url = http://host.containers.internal:8080/mcp
  tools/harnessed/assemble.py:67                              │
                                                              │  baked into hatago.config.json
                                                              ▼
  launch time                                                 │
  ensure_service_up(ping) ──► podman run -d -p 8080:8080 …     │   (publishes to 0.0.0.0; no --network)
  lib/harnessed-services.sh:120-127                           │
                                                              │  hatago (in the pod) proxies the URL
                                                              ▼
  harness ──► .mcp.json → localhost:3535/mcp ──► hatago ──► host.containers.internal:8080/mcp ──► ping
```

The harness never speaks to the service host directly; it only ever talks to hatago over
the shared pod netns. hatago's URL-proxy entry is what crosses the rootless boundary to
the host-published port.

---

## Key Abstractions

All defined in `tools/harnessed/schema.py` unless noted. The assembler is the single
source of truth for these types; the host launcher reads the manifests with flat `sed`
greps (it has no YAML dependency).

- **`Stack`** (`schema.py:118`) — a composed unit: `name`, `config` (`isolated`|
  `transparent`), `harness` (`claude`|`omp`|`opencode`|`gemini`|`antigravity`|`codex`,
  exactly one), `recipes[]`, `services[]`, `permissions`, `state{}`. The
  `harness_config_dir` property (`schema.py:136`) maps harness → the Claude-canonical
  `.claude` dir. **All six harnesses consume the same committed `.claude` profile**
  (`HARNESS_CONFIG_DIR` in `schema.py:41-48`) — single source of truth. They differ only
  in *how* they read it and reach hatago (design §8):
    - `claude` — native (`.mcp.json` + skills/commands/agents).
    - `omp` — Claude hooks/skills via the pre-installed `claude-hooks-bridge`.
    - `opencode` — reads `.claude/skills/**/SKILL.md` + `~/.claude/CLAUDE.md` natively;
      MCP via the image-baked `~/.config/opencode` config (ignores `.mcp.json`).
    - `gemini` — MCP via the image-baked `~/.gemini/settings.json`; Claude skills/commands
      are NOT natively consumed.
    - `antigravity` (agy) — MCP via the image-baked `~/.gemini/config/mcp_config.json`;
      Claude skills/commands NOT natively consumed.
    - `codex` — MCP via the image-baked `~/.codex/config.toml` (`[mcp_servers.hatago]`,
      native streamable-HTTP); reads `AGENTS.md` but NOT Claude skills/commands.
  No separate profile dir, no re-authoring for any harness.
- **`Recipe`** (`schema.py:107`) — one integration: `servers[]`, `skills[]`,
  `commands[]`, `root` (the recipe dir, for resolving relative paths), `raw` (forward-
  parsed unknown fields, D-14).
- **`McpServer`** (`schema.py:69`) — one MCP server. `transport` is explicit (RESEARCH
  Pitfall B): a `stdio` server with a `command` is run by hatago as a child
  (`is_stdio_child` → True → baked into the hatago image); a network-native server or a
  `service:`-referenced one is proxied by URL. Carries `url_env`, `env`, `headers`,
  `service`.
- **`ServiceDef`** (`schema.py:139`) — a shared sidecar: `name`, `image`, `port`,
  `volume` (defaults `<name>-data`), `healthcheck`. Referenced from a recipe via
  `mcp.servers[].service`; resolved by `_resolve_service_servers` into a hatago URL-proxy
  entry pointing at `host.containers.internal:<port>/mcp`.
- **`FileExt`** (`schema.py:95`) — a standalone file-extension dir shipped by a recipe;
  `leaf` is the harness-native leaf name used for collision-checking.
- **`Capabilities` / `expected_capabilities(stack, recipes)`** (`schema.py:347-365`) — the
  **test oracle** (design §18). Derives the MCP servers + skills + commands the running
  instance must expose, directly from the manifest. The capability test asserts the live
  instance matches.
- **`LinkSyncer`** (`synclinks.py`) — the collision-checking fan. Registers each
  recipe's skills/commands by harness-native leaf name as recipes are added; two recipes
  shipping the same name is a **fail-fast `CollisionError`** that names both source paths
  — never a silent last-wins overwrite. `fan()` then `copytree`s the registered tree.
- **`AssembleResult`** (`assemble.py:24`) — the assembler's return value: `stack`,
  `recipes`, `profile_dir`, `servers`, `baked` (the stdio children the hatago image must
  bake), `skills[]`, `commands[]`.

Two cross-cutting invariants the abstractions enforce:

- **Fail-fast, pre-emit.** `validate_no_raw_npm`, the skill/command collision check, and
  the MCP-server-name collision check all run *before* `emit.reset_profile` wipes
  anything. A bad build leaves the previous profile intact.
- **Claude-canonical format is the single source of truth** (§8). Skills/commands/hooks
  are authored once in Claude format; every harness mounts the same `.claude` profile and
  adapts *out* of it at runtime. One harness per stack.

---

## State Management

Four independent state scopes, by design (§9). They must not be confused.

### 1. Per-project/per-stack harness profile (the live `.claude`)
Location: `${XDG_STATE_HOME:-$HOME/.local/state}/harnessed/<state_project>/<stack>/.claude`
where `<state_project>` is the legible flattened `$HOME`-relative project path
(`lib/harnessed-isolated.sh:131-132`). This is the **copy-on-start** of the committed
profile — the running harness writes runtime state (`projects/`, `history.jsonl`, caches,
backups) here, never back into the version-controlled `profiles/<stack>/` tree.
Persistent across recreates by default (STA-01): the wipe + reseed runs only on first
create (state dir absent) or under `--fresh`. Keyed by a *legible* project path so a
memory system accumulates host-side and stays inspectable (STA-02); the opaque `$instance`
hash still keys the pod/container (DNS-label ≤63-char limits apply there, not here).

### 2. Per-instance `.claude.json` stub (onboarding bypass)
Location: `${XDG_STATE_HOME:-$HOME/.local/state}/harnessed/<instance>/claude.json`
(`lib/harnessed-isolated-config.sh:97`). A **generated, token-free** stub built with `jq`:
`hasCompletedOnboarding`, `firstStartTime`, `numStartups`, `oauthAccount`, `userID`
(`lib/harnessed-isolated-config.sh:114-124`). The host whole-file blob is *never* mounted
(it races with host Claude and corrupts state). Auth comes from the read-only
`~/.claude/.credentials.json` mount — the only credential surface. Other harnesses seed
their own credential stores instead: opencode → `~/.local/share/opencode/auth.json` ro,
gemini → `~/.gemini/oauth_creds.json` ro, codex → `~/.codex/auth.json` ro; antigravity
has no mountable credential (interactive login on first launch) — all in
`lib/harnessed-isolated-config.sh`.

### 3. Service-scoped sidecar volumes (shared memory)
Location: podman named volume `<service>-data` (e.g. `ping-data`), mounted at the
service's `data_path` (default `/data`, `lib/harnessed-services.sh:79-82`). Survives
`svc down` by default — that is the whole point of a shared service (one memory across
instances, design §9). `svc down --purge` is the explicit destroy. The service *container*
is named `<service>` and labelled `harnessed-service=<name>`; its lifecycle is independent
of any instance (`ensure_service_up` starts it if absent, instances attach concurrently).

### 4. Committed profile template (`profiles/<stack>/`)
Location: `profiles/<stack>/.claude/{skills,commands,agents,hooks,rules}/` +
`.mcp.json` + `settings.json`, and `profiles/<stack>/{hatago.config.json,baked-servers.json}`.
The assembler's output, committed to git, treated as the **immutable template** the live
profile (scope 1) is seeded from. Never written to at run time.

> **The transparent contrast.** `transparent` (`lib/harnessed-transparent.sh`) has no
> profile, no hatago, no service scopes. Host `~/.claude` is mounted rw live, and a
> writable per-instance copy of `~/.claude.json` is seeded at start
> (`lib/harnessed-claude-config.sh`) — copy-on-start of the host blob rather than a
> generated stub. MCP comes from the host's own `.mcp.json`/`.claude.json`.

### Resolved-secret transient state (opt-in)
When `~/.config/harnessed/.env.schema` (or `~/.config/<service>/.env.schema`) is present,
`resolve_secret_env` (`lib/harnessed-secrets.sh`) resolves `op(op://…)` refs via varlock +
1Password into a **mode-0600 temp env-file** that is spread into the pod via `--env-file`
and **unlinked right after launch** (a RETURN-trap guarantees cleanup on any exit path,
`lib/harnessed-isolated.sh:187-192`). Inert when no schema exists. Resolved secrets reach
the pod as **env only** — never the profile or an image layer.
