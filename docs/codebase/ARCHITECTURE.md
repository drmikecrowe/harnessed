# Architecture

**Analysis Date:** 2026-06-16

`harnessed` composes hand-authored recipes into named stacks, assembles them into
committed profiles, and launches isolated shared-netns groups (a podman pod, or a docker
shared-netns pair via `lib/harnessed-runtime.sh`) — a harness container (claude,
omp, opencode, gemini, antigravity, or codex) plus a hatago MCP hub, with optional shared service sidecars. The architectural
source of truth is `docs/harnessed-design.md`; this document distills the *implemented*
architecture (Phases 1–4).

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

---

## Layers

Five layers, ordered build-time → run-time. Each layer only depends on the layer(s) above
it in this list.

### 1. Authored inputs (data, not code)
- `recipes/<name>/recipe.yaml` — one hand-authored integration definition per project
  (MCP servers + file-extension dirs).
- `stacks/<name>/stack.yaml` — composes a harness + a chosen set of recipes (+ services).
- `services/<name>/service.yaml` — a shared sidecar definition (image/port/volume).

### 2. Build-time assembler — `tools/harnessed/` (Python, emit-only)
Runs inside the `harnessed-tools` image. Holds *all* assembly logic: parse/validate
YAML, fan skills/commands with collision-checking, merge `hatago.config.json`, generate
the harness `.mcp.json`/`settings.json`, lint recipes, scan supply-chain. It reads
`recipes/`+`stacks/`+`services/` under a root and **emits** `profiles/<stack>/` +
`hatago.config.json` + a baked-servers manifest. It never invokes podman.

### 3. Image tier — `base/`, `services/`, `tools/Dockerfile`
Standalone, independently-versioned images, built by the **host** (`podman build`):
- `base/Dockerfile.harnessed-base` → `base/Dockerfile.harnessed-claude` / `.harnessed-omp` / `.harnessed-opencode` / `.harnessed-gemini` / `.harnessed-antigravity` / `.harnessed-codex`
  (lineage via `FROM`).
- `base/Dockerfile.hatago` — the MCP hub + light stdio servers baked in.
- `services/<name>/Dockerfile` — one per heavy/stateful sidecar.
- `tools/Dockerfile` — the assembler image itself.

### 4. Generated artifacts — `profiles/<stack>/` (committed, mounted)
The assembler's output. Committed to git and **mounted** into the harness container at
run time: `.claude/{skills,commands,agents,hooks,rules}/`, `.mcp.json`, `settings.json`,
`hatago.config.json`, `baked-servers.json`.

### 5. Host runtime — `harnessed` + `lib/*.sh` (bash)
The launcher. Computes the §4a/§4b mounts on the host, runs the shared-netns group via host
`$CONTAINER_RUNTIME` (podman pod, or docker pair — abstracted by `lib/harnessed-runtime.sh`),
attaches with host-native `podman exec -it`. Also drives the assembler image
(`build_stack` runs `podman run harnessed-tools assemble …`).

> **Layering rule of thumb:** `tools/` emits files; `lib/` runs containers. If you are
> tempted to call podman from Python, or to parse YAML from bash, you are crossing the
> boundary in the wrong direction.

---

## Entry Points

### `harnessed` — the host launcher (`harnessed`)
A thin host bash bootstrap. It sources `lib/harnessed-common.sh`, then runs a single
`while [[ $# -gt 0 ]]; do case "$1" in …` arg-parse loop (`harnessed:81-210`). The case
arms dispatch to one of three shapes:

1. **Top-level subcommands** (each dispatches then `exit 0` — not a launch path):
   - `build [<stack>]` → `build_stack` (assemble + host build) or `build_images`
     (rebuild base/claude/hatago). `harnessed:270-279`
   - `test <stack>` → ensures the build, then runs the host-side capability test via
     `python -m harnessed.cli test`. `harnessed:287-327`
   - `svc up|down|list <service>` → sources `lib/harnessed-services.sh` and dispatches.
     `harnessed:228-243`
   - `list | stop <stack> | rm <stack> | new <stack> | install | uninstall` → source
     `lib/harnessed-cli.sh` and dispatch. `harnessed:248-267`

2. **Launch path** — the fallthrough. First bareword is a stack name (if
   `stacks/$1/stack.yaml` exists) or a project path (if it's a directory); second bareword
   is the project path. Resolves to an instance name, then `case "$STACK"` dispatches to
   the mode launcher (`harnessed:342-359`):
   - `transparent` → `lib/harnessed-transparent.sh::harnessed_transparent`
   - anything else → `lib/harnessed-isolated.sh::harnessed_isolated`

3. **Legacy flags** (`--list`/`--stop`/`--remove`/`--clean`/`--fresh`/`--no-firewall`) keep
   back-compat with the old `container` command.

`detect_runtime` (run at the top) prefers podman, falls back to docker — podman/docker is
the only host dependency.

### `tools/harnessed/cli.py` — the assembler CLI entrypoint
`python -m harnessed.cli`, run *inside* the `harnessed-tools` image by `build_stack`. An
argparse CLI with four required subcommands (`cli.py:28-105`):

- **`assemble <stack> --build-dir <dir> [--root <dir>]`** — the core emit step. Calls
  `assemble.assemble()`; writes `profiles/<stack>/` + `hatago.config.json`.
- **`test <stack> [--project …] [--keep] [--json]`** — the per-stack capability test
  (design §18). Launches the stack `--fresh` headless via the *host* `harnessed` launcher,
  introspects the live instance, asserts the manifest's declared capabilities are present,
  and renders a markdown report (or JSON for CI). This one subcommand drives host podman —
  it is the exception that proves the emit-only rule, and it runs host-native, not inside
  the tools image.
- **`scan <stack> --build-dir <dir>`** — the scoped source/Python supply-chain scan
  (BLD-02); exit 1 on any HIGH+ finding.
- **`scan-image <archive>`** — the image-archive scan (osv-scanner over a `podman save`
  tar); exit 1 on any HIGH+ finding.

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

### 2. `harnessed build <stack>` → `lib/harnessed-common.sh::build_stack`
Four host-driven steps (`harnessed-common.sh:94-144`):

```bash
# (a) ensure the emit-only assembler image exists (built from tools/Dockerfile)
ensure_tools_image

# (b) EMIT: the assembler only reads/writes the mounted ROOT; it never drives podman.
"$CONTAINER_RUNTIME" run --rm --userns=keep-id \
    -v "$ROOT":"$ROOT" -w "$ROOT" \
    "$HARNESSED_TOOLS_IMAGE" assemble "$stack" --root "$ROOT" --build-dir "$ROOT"

# (c) SOURCE SCAN (BLD-02a): scoped to this stack's recipe dirs + emitted profile.
"$CONTAINER_RUNTIME" run --rm … "$HARNESSED_TOOLS_IMAGE" scan "$stack" --root "$ROOT" --build-dir "$ROOT"

# (d) BUILD: the HOST builds the hatago image from base/Dockerfile.hatago, then IMAGE SCAN.
"$CONTAINER_RUNTIME" build -t "$HARNESSED_HATAGO_IMAGE" -f …/base/Dockerfile.hatago …
"$CONTAINER_RUNTIME" save "$HARNESSED_HATAGO_IMAGE" -o "$img_tar"   # host → tar
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
The launch path (`harnessed-isolated.sh:31-196`). Per-instance state is the pivot:

```bash
# Copy-on-start the committed profile into a per-instance state dir (PERSISTENT by default;
# wiped only on first create or under --fresh). The profile is the immutable template.
local run_claude="${XDG_STATE_HOME:-$HOME/.local/state}/harnessed/$instance/.claude"
if [ "$fresh" = "true" ] || [ ! -d "$run_claude" ]; then
    rm -rf "$run_claude"; cp -a "$profile_dir/.claude" "$run_claude"
fi

# Compose the pod (harness + hatago share the netns). userns=keep-id is a POD-level property.
"$CONTAINER_RUNTIME" pod create --name "$pod" --userns=keep-id …

# Auto-start the stack's declared shared services (design §9: an instance starts it if absent).
for svc in $svc_line; do ensure_service_up "$svc"; done

# hatago member: one Streamable-HTTP endpoint on :3535 from the mounted per-stack config.
"$CONTAINER_RUNTIME" run -d --pod "$pod" --name "${instance}-hatago" \
    -v "$profile_dir/hatago.config.json:…/hatago.config.json:ro" \
    "$HARNESSED_HATAGO_IMAGE" hatago serve --http --port "$HATAGO_PORT" --config …

# harness member: profile-only config + §4a + §4b mounts; sleeps until attach.
"$CONTAINER_RUNTIME" run -d --pod "$pod" --name "$instance" "${member_args[@]}" "$harness_image" sleep infinity

apply_firewall "$instance"           # egress firewall (NET_ADMIN) on the harness container
# …wait for hatago's port…
"$CONTAINER_RUNTIME" exec -it … "$instance" bash -lc "$mise_init && claude --mcp-config '$mcp_cfg' --strict-mcp-config"
```

The harness `.mcp.json` points at exactly **one** endpoint —
`http://localhost:3535/mcp` (`emit.py::HATAGO_ENDPOINT`) — because pod members share a
netns. hatago aggregates every MCP server behind that one endpoint: light stdio servers
run as hatago's children (baked into the hatago image), heavy services are proxied by URL
over the network.

> **Provider portability:** the launch path above is the podman shape. `lib/harnessed-runtime.sh`
> abstracts the shared-netns group so the same launcher also runs on docker (hatago starts first,
> the harness joins with `--network container:<instance>-hatago`; no `--userns` — rootless docker
> remaps uids daemon-side). Apple `container` (one VM+IP per container, no shared netns) is a
> tracked follow-up, not yet supported.

`transparent` is the degenerate case (`lib/harnessed-transparent.sh`): no pod, no hatago,
no services — just a harness container with the host config mounted live.

---

## Key Abstractions

All defined in `tools/harnessed/schema.py` unless noted. The assembler is the single
source of truth for these types; the host launcher reads the manifests with flat `sed`
greps (it has no YAML dependency).

- **`Stack`** (`schema.py:104`) — a composed unit: `name`, `config` (`isolated`|
  `transparent`), `harness` (`claude`|`omp`|`opencode`|`gemini`|`antigravity`|`codex`, exactly one), `recipes[]`, `services[]`,
  `permissions`, `state{}`. The `harness_config_dir` property maps harness → the
  Claude-canonical `.claude` dir (omp and opencode consume the *same* profile — omp via the
  bridge, opencode natively; gemini, antigravity, and codex also map to `.claude` but do NOT natively
  consume Claude skills/commands — their capability wiring is MCP via image-baked config → hatago;
  no re-authoring for any of them — design §8).
- **`Recipe`** (`schema.py:93`) — one integration: `servers[]`, `skills[]`,
  `commands[]`, `root` (the recipe dir, for resolving relative paths), `raw` (forward-
  parsed unknown fields, D-14).
- **`McpServer`** (`schema.py:54`) — one MCP server. `transport` is explicit (RESEARCH
  Pitfall B): a `stdio` server with a `command` is run by hatago as a child
  (`is_stdio_child` → True → baked into the hatago image); a network-native server or a
  `service:`-referenced one is proxied by URL. Carries `url_env`, `env`, `headers`.
- **`ServiceDef`** (`schema.py:124`) — a shared sidecar: `name`, `image`, `port`,
  `volume` (defaults `<name>-data`), `healthcheck`. Referenced from a recipe via
  `mcp.servers[].service`; resolved by `_resolve_service_servers` into a hatago URL-proxy
  entry.
- **`Capabilities` / `expected_capabilities(stack, recipes)`** (`schema.py:330-348`) — the
  **test oracle** (design §18). Derives the MCP servers + skills + commands the running
  instance must expose, directly from the manifest. The capability test asserts the live
  instance matches.
- **`LinkSyncer`** (`synclinks.py:26`) — the collision-checking fan. Registers each
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
  are authored once in Claude format; omp adapts *out* of it at runtime via
  `claude-hooks-bridge`. One harness per stack.

---

## State Management

Three independent state scopes, by design (§9). They must not be confused.

### Per-instance state dir (harness state)
Location: `${XDG_STATE_HOME:-$HOME/.local/state}/harnessed/<instance>/` — one directory
per running instance, keyed by the instance name. Holds:
- `.claude/` — **copy-on-start** from the committed profile
  (`lib/harnessed-isolated.sh:103-108`). Persistent across recreates by default (STA-01):
  the wipe + reseed runs only on first create (state dir absent) or under `--fresh`. This
  is where `projects/`, `history.jsonl`, and harness caches accumulate host-side (STA-02),
  so a memory system survives instance recreation and stays inspectable.
- `claude.json` — a **generated, token-free** stub
  (`lib/harnessed-isolated-config.sh:56-67`): `hasCompletedOnboarding`, `firstStartTime`,
  `numStartups`, `oauthAccount`, `userID`. The host whole-file blob is *never* mounted
  (it races with host Claude and corrupts state). Auth comes from the read-only
  `~/.claude/.credentials.json` mount — the only credential surface.

`--fresh` is meaningfully distinct from a normal run: it wipes the state dir, giving a
clean-room comparison; a normal recreate reuses accumulated state.

### Service-scoped volumes (shared services)
Named `<service>-data` (e.g. `ping-data`), declared in `services/<name>/service.yaml`.
**Service-scoped and harness-independent** (§9): the volume is named after the *service*,
not the stack or instance — this is what lets a `claude+ping` stack and an `omp+ping`
stack share **one** memory. The volume **survives `svc down`** by default (that's the
value); `svc down --purge` is the explicit destroy (`lib/harnessed-services.sh:132-150`).

### Shared service lifecycle (containers, not volumes)
A shared service is its **own** image/container on `harnessed-net` (or, rootless, reached
via the host gateway `host.containers.internal:<port>`), labelled
`harnessed-service=<name>`, with a lifecycle **independent of any instance** (§3/§9). One
long-lived container serves multiple instances concurrently; an instance starts it if
absent (`ensure_service_up`), and it outlives instances (`harnessed svc up|down`).

### Instance/pod identity
`generate_instance_name` (`lib/harnessed-common.sh:179-191`) mints
`harnessed-<stack>-<projhash>` — the harness member and hatago peer share this base name
(`${instance}` + `${instance}-hatago`): podman groups them in a pod, docker as a flat container
pair. The project path is part of identity because bind mounts are fixed at creation, so the
same stack is runnable across projects without recreate.

### In-container home
`CONTAINER_HOME=/home/harnessed` (`harnessed-common.sh:27`). The project mounts at
`/home/harnessed/<relpath>` so the harness's session slug is legible
(`-home-harnessed-<relpath>`) and lives under a harnessed-owned dir that never pollutes
the host's own `~/.claude`.
