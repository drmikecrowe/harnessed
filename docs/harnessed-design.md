# harnessed — Isolated, Composable Harness Stacks

> **Status:** Design spec (resolved via discuss/grill session). Architecture decisions
> (§2–§9) are **confirmed**. Schemas, repo layout, and CLI (§10–§13) are **proposed**
> and open for review. Items in §14 are **to verify during execution**.
>
> **Names:** the executable is **`harnessed`**; what it launches is a **stack** — a podman pod with
> the harness container + hatago + shared services. The existing `container` SKU folds in as the
> built-in `transparent` stack (§2); `container` remains a thin alias → `harnessed transparent`.

## 1. Problem

`container` (this repo's existing tool) builds an isolated container that **mirrors the
host's tool setup** — auth, config, skills, MCP, plugins all bind-mounted from `~`. That is
the right SKU for "my laptop, sandboxed."

It is the wrong SKU for *experimenting* with commands/skills/plugins/memory systems, because
it drags every host default into the container. A prior attempt to instead **merge** a curated
set into the host config (`~/.agents` + `sync-plugin-links` + universal-hooks) failed: a single
shared host namespace (`~/.claude`, `~/.agents`) cannot hold every experiment at once —
openbrain and hindsight collide, per-runtime `settingSources` drift, and vendored deps pollute
`~`.

**Insight:** do the merge **per container**, where each stack is isolated, so the collision
that killed the host merge disappears by construction.

## 2. One engine, two config modes

There is **one** executable, `harnessed`. Every stack shares the same base image, the same
host-integration mounts (§4), the same project mount, and host auth. Stacks differ on a
single axis — **where the config layer (skills/commands/hooks/MCP) comes from**:

| Mode | Config source | Mental model |
|---|---|---|
| **`transparent`** | host `~/.claude` (+ `.codex`/`.opencode`/`.gemini`) bind-mounted live | "my laptop, sandboxed" — the current `container` SKU |
| **`isolated`** | auth seeded + the assembled stack **profile** mounted; nothing from host config | "clean room with exactly what I picked" |

`transparent` is just a built-in stack (`stacks/transparent/`) that sets `config: transparent`
and mounts host skills/hooks/commands wholesale. `isolated` stacks embed recipe-composed
skills/hooks/commands. The old `container` command becomes an alias for `harnessed transparent`
(see §14 — keep alias vs remove).

## 3. Core model: stack = harness container + hatago + shared services

A running **stack** is composed **at runtime**, in a podman **pod** on a shared network — **not**
at build time. (`FROM` is linear inheritance + multi-stage `COPY --from`; it cannot union two
sibling systems. See §6.)

            podman pod: harnessed-<stack>-<proj>
        ┌──────────────────────────────────────────────┐
        │  [ harnessed-<harness> ]  ──→  [ hatago ]      │
        │    mounts cwd + profile      MCP hub · HTTP    │
        └───────────────────────────────────────┬───────┘
                                                 │ MCP over host.containers.internal (HARNESSED_NET: opt-in)
                          ┌──────────────────────┴──────────────────────┐
                          ▼                                              ▼
                   [ hindsight ]                               [ openbrain ]
                   shared · service-scoped                     shared · service-scoped
                   own image · volume · lifecycle              own image · volume · lifecycle
```

- **harness container** — runs the harness (`claude`/`omp`), auth seeded, current folder mounted,
  stack profile mounted into the harness config dir.
- **hatago** — MCP hub. Aggregates all of the stack's MCP servers behind **one** HTTP endpoint;
  the harness container's `.mcp.json` points at `localhost:<port>`. Light `npx`/`uvx` stdio servers run as
  hatago's children (baked into the hatago image); heavy services are proxied over the network.
- **shared services** — heavy/stateful systems (hindsight = postgres+MCP, openbrain). Each is
  its **own** image/container/volume, **service-scoped and harness-independent**, with a
  lifecycle independent of any instance. Multiple harnessed instances attach to the **same** running service concurrently.

**Transparent mode is the degenerate case:** harness container only — no hatago, no services. Host
config is mounted live, so MCP comes from the host's own `.mcp.json`/`.claude.json`. The pod,
hatago, and shared-service machinery above apply only to `isolated` stacks.

## 4. Mounts: shared host-integration layer + per-mode config source

Two distinct mount layers. The first is **identical for every stack**; the second is the only
thing `transparent` and `isolated` disagree on.

### 4a. Host-integration layer (shared by ALL stacks)

Ported verbatim from `container.sh`'s `start_new_container` — these are credentials, signing,
and agents, *not* the config-experiment surface, so they belong in every instance:

- 1Password SSH agent socket (`SSH_AUTH_SOCK`)
- GPG agent SSH socket + `~/.gnupg` (ro) — YubiKey SSH / commit signing
- YubiKey USB device passthrough (`--device`)
- `~/.ssh` (ro), git config (ro), `/etc/machine-id` (ro)
- `~/.zai.json` (ro) and per-tool `~/.config/<tool>` dirs (editor configs, etc.)
- egress firewall (`--cap-add NET_ADMIN`, `egress-firewall.sh`)
- the current project folder, mounted at the work dir

### 4b. Config source — the mode axis

**`transparent`:** bind-mount host config live (like today's `container`, with one safety fix —
the `.claude.json` caveat below):

- `~/.claude` mounted rw for live skills/commands/settings (per-path dirs + append-mostly → low race risk)
- **`~/.claude.json` is NOT rw-bind-mounted.** It's a single whole-file blob Claude rewrites
  constantly (see host `~/.claude/backups/*.backup.*`). A shared rw mount races with host claude
  (lost writes / corruption) and merges container state back into the host file — the differing
  project path only spares the path-keyed `projects` subtree, not the whole-file rewrite or the
  top-level fields. Seed a **writable per-instance copy** at start (copy-on-start), or relocate via
  `CLAUDE_CONFIG_DIR` (§14): container reads host state, writes only its own copy.
- `~/.codex`, `~/.config/opencode`, `~/.gemini` (rw)
- MCP comes from host config as-is; no hatago, no profile, no auth stub.

**`isolated`:** auth seeded, config from the profile (the core trick), grounded in the real
`~/.claude` layout:

- The real credential is **`~/.claude/.credentials.json`** (OAuth token). Mount it read-only.
- **`~/.claude.json`** is *not* auth — it's `oauthAccount` metadata + ~450 KB of config/state
  (`projects`, `mcpServers`, caches). **Do not mount it.** **Generate** a minimal stub with only
  the fields needed to skip onboarding (see §14 — exact set to verify).
- `skills/`, `commands/`, `agents/`, `hooks/`, `rules/`, `.mcp.json`, `settings.json` come
  **only** from the stack profile (§7); `.mcp.json` points at hatago.
- Session state — `~/.claude/projects/` + `history.jsonl` — persists to the **host** by default,
  so sessions survive instance recreation and stay inspectable. The project is mounted at a stable
  in-container path (e.g. `/home/harnessed/<relpath>`) so Claude's slug is legible
  (`-home-harnessed-<relpath>`), under a harnessed-owned dir so it never pollutes the host's own
  `~/.claude`. `session_state: volume` (§12) opts into a throwaway per-instance volume instead.

Net: `isolated` is authenticated but carries **no host defaults**; `transparent` is the full
host mirror. Same engine, same operational mounts, one switch.

## 5. Composition unit: recipes (hand-authored, not dynamic)

A **recipe** is a hand-authored integration definition for **one** project (hindsight, gsd,
caveman, headroom, …). A **stack** is a harness + a chosen set of recipes. Nothing is resolved
at runtime; recipes are assembled ahead of time into committed artifacts.

A recipe can contribute to **two layers**:
- **MCP layer** → server entries merged into the stack's hatago config (and/or a shared service ref).
- **File-extension layer** → `skills`/`commands`/`agents`/`hooks`/`rules` in Claude-canonical form.

## 6. Image tier — `FROM` is for base lineage only

`FROM` gives **linear** inheritance; multiple `FROM`s = multi-stage build whose **last** stage is
the image, with `COPY --from=…` pulling artifacts from earlier stages. There is **no** "union two
images" operator. So systems are **not** combined via `FROM`; they are combined at runtime (§3).

Legitimate build-time images:

- `harnessed-base` — mise/node/python + common tooling → `FROM harnessed-base` → **`harnessed-claude`**, **`harnessed-omp`**.
- `hatago` — the hub + the *light* `npx`/`uvx` stdio MCP servers baked in.
- **Per heavy service** — `services/hindsight/Dockerfile`, `services/openbrain/Dockerfile`, each
  standalone, independently versioned, reusable across stacks.

## 7. Assembly — split: build-time vendor/sync (committed) + baked images

The build-time assembler **reuses prior art** (to be ported into this repo):

| Step | Prior-art source (host) | Role |
|---|---|---|
| acquire | `~/.agents/bin/vendor-plugin` | resolve a Claude plugin (marketplace / url / git-subdir + sha) → copy + install uv/npm deps |
| colocate | `~/.agents.20260603/bin/sync-plugin-links` | fan a plugin's `skills/`+`commands/` into harness-native paths; **fail-fast on name collision** |
| wire hooks | `~/.agents.20260603/hooks/{run-hook.sh,<Event>.d,lib-pi-adapter.sh}` + universal-hooks `activate` | one hook codebase dispatched per runtime; pi-adapter normalizes omp/GSD payloads → Claude shape |

**Where output lands:**
- **Committed → mounted:** the assembled file-extension tree is written into the git-controlled
  **profile** dir and **mounted** into the harness container (editable, versioned — satisfies VISION's
  "commands, skills, agents and hooks proxied to a git-controlled folder").
- **Baked → images:** MCP servers + their `npx`/`uvx`/python deps are baked into images
  (host stays clean, reproducible, pinned).

Nothing is assembled at container start → satisfies "not dynamic."

### Supply-chain security (build-time gate)

Vendored deps and built images are **scanned before** a profile is committed or an image is
published — porting the audit suite from `~/.config/dorothy/commands/nightly-updates`:

- **osv-scanner** — credential-free; scan lockfiles / `node_modules` of vendored plugins + images.
- **snyk test** `--severity-threshold=high` — **needs a token**; npm/pnpm trees (synthesize a
  `package.json` from `pnpm ls`/`npm ls -g` for manifest-less globals, per the `nightly-updates` trick).
- **pip-audit** — credential-free; Python deps in any recipe shipping `requirements.txt`/`pyproject.toml`.
- **Socket.dev** (optional) — **needs a token**; deeper supply-chain signals if you add it.

`harnessed build` fails on high-severity findings. A nightly job (the systemd-timer pattern from
`nightly-updates`) can re-scan installed images so a CVE disclosed after build still surfaces.

### Scanner credentials (snyk / Socket.dev)

Only the credentialed scanners need this; `osv-scanner` and `pip-audit` use public DBs. Same rule
as Claude auth: **reference host creds, never bake or commit them.**

- **Present → use, silently.** Sources, in order: raw `SNYK_TOKEN` / `SOCKET_SECURITY_API_KEY` env
  or host config (`~/.config/configstore/snyk.json`); **or**, if you use varlock (§16, optional), an
  `op(op://…)` ref in `~/.config/harnessed/.env.schema`. Either way it reaches `harnessed-tools` at
  launch — never an image layer.
- **Missing → warn and skip that scanner**, not an interactive prompt. `harnessed build` must stay
  non-interactive / reproducible (CI, the nightly timer), and a typed token must never land in a
  repo or image layer. The credential-free `osv-scanner` + `pip-audit` remain the baseline gate.
- **Opt-in setup:** `harnessed auth snyk|socket` runs the CLI's own `auth` inside the tool
  container and persists to the mounted host config — so a token is set deliberately, once.

### pnpm everywhere (supply-chain policy)

All JavaScript installs — **global, per-recipe, and hatago's bundled servers** — use **pnpm**, not
npm/npx. Rationale: <https://pnpm.io/supply-chain-security>. A managed pnpm config (shipped in
`harnessed-base` / `lib/`) enables:

- **`minimumReleaseAge`** — quarantine newly published versions (cooldown) so a compromised
  release isn't installed the moment it lands.
- **lifecycle scripts default-denied** — `strictDepBuilds` (live in the global config) makes
  pnpm exit non-zero on any unreviewed postinstall/build script. The curated `allowBuilds`
  except-list is **project-scoped** (pnpm-workspace.yaml / config-dependencies): pnpm v11
  rejects it from the global config, so it is deferred until a build-script package (e.g.
  esbuild) actually needs to run.
- **store integrity verification** + content-addressed store.

`minimumReleaseAge`, `strictDepBuilds`, and store-integrity ship in the managed global
`~/.config/pnpm/config.yaml` (shipped from `lib/pnpm/config.yaml`) — **not** `.npmrc`, which
is auth/registry-only in v11. (`allowBuilds` is the one exception: it belongs in each
project's `pnpm-workspace.yaml`, not the global config — verified in the phase-3 checkpoint.)

`npx <pkg>` → `pnpm dlx <pkg>`; `npm install` → `pnpm install`. **Recipe validation** (part of
`harnessed build`) flags any raw `npm`/`npx` in a recipe's scripts/deps and points at the pnpm
equivalent. (Requires updating the ported `vendor-plugin`, which currently shells `npm install`.)

## 8. Canonical format = Claude Code; omp via bridge

Claude Code format is the **single source of truth** for skills/commands/hooks/plugins. Other
harnesses adapt *out* of it:

- **claude** — native; mount directly.
- **omp** — consumes Claude-format hooks/skills at runtime via
  `claude-hooks-bridge` (`~/Programming/AI/omp-extensions/claude-hooks-bridge`) +
  `lib-pi-adapter.sh`. **No re-authoring.** The `omp` base recipe pulls these in.

**One harness per stack.** A stack targets exactly `claude` *or* `omp`, never both at once.

## 9. State & lifecycle

- **Default persistent, `--fresh` to wipe.** Accumulation is the *value* of a memory system;
  `--fresh` gives a clean-room comparison run (throwaway volume).
- **Service volumes are service-scoped & harness-independent** — `hindsight-data`, not
  `harnessed-data-<stack>`. This is what lets `claude+hindsight` and `omp+hindsight` share **one**
  memory.
- **Shared instance, concurrent.** One long-lived `hindsight` container, owned by the *service*
  not any instance; postgres serves both instances at once. An instance starts it if absent; it
  outlives instances (`harnessed svc up/down`). The service **publishes its port to `0.0.0.0`**
  and peers reach it via the podman host gateway **`host.containers.internal:<port>`** (the
  primary reachability model); the `harnessed-net` bridge + DNS-by-name is the **`HARNESSED_NET`
  opt-in** for bridge-capable hosts (a rootless bridge is unsupported on most hosts — netavark
  "Operation not supported").
- **Harness-state** — `projects/` + `history.jsonl` persist to the **host** by default
  (harnessed-scoped, path-mirrored for a stable slug; `session_state: volume` for throwaway).
  Other ephemeral state (`sessions/`, caches) stays in a per-instance volume.

### Operator prerequisites for the host-gateway reachability model

The publish + host-gateway model above depends on two operator-side controls that already ship
in the repo. They are documented here as **prerequisites**, not implementation details:

1. **Egress-firewall allow rule for `host.containers.internal`.** Rootless podman exposes the
   host gateway at `host.containers.internal` (`169.254.1.2`). `lib/egress-firewall.sh:55-63`
   computes `PODMAN_GW=$(getent ahosts host.containers.internal …)` and adds an iptables allow
   rule for it — distinct from the default-route gateway. Without this rule the proxy path is
   blocked (iptables is netns-wide, so it gates hatago too).
2. **FastMCP `allowed_hosts`.** A Streamable-HTTP service proxied over
   `host.containers.internal` MUST add it to `TransportSecuritySettings.allowed_hosts`, or
   FastMCP's DNS-rebinding protection returns `421 Misdirected Request`. Canonical implementation:
   `services/ping/server.py:19-25` (commit `6f6c1b3`); see also the "Networking note" in
   `docs/guides/service-authoring.md`.

---

## 10. Proposed: repo layout

```
code-container/
  harnessed                    # thin host bash bootstrap → host podman build/run; drives the assembler (§15)
  container                    # back-compat alias → `harnessed transparent` (see §14)
  .env.schema.example          # varlock secrets template → ~/.config/harnessed/.env.schema (§16)
  tools/                       # harnessed-tools: the assembler image — emits Dockerfile+profile+launcher (Python)
    Dockerfile                 # python + rich/textual + yq/jq + git + pnpm + scanners + varlock + op
    pyproject.toml
    harnessed/                 # cli, assemble, vendor, sync-links, validate, emit Dockerfile/launcher
  base/
    Dockerfile.harnessed-base    # mise/node/python + common tooling
    Dockerfile.harnessed-claude  # FROM harnessed-base + claude install
    Dockerfile.harnessed-omp     # FROM harnessed-base + omp install
    Dockerfile.hatago          # hatago + light pnpm-dlx/uvx MCP servers
  services/                    # heavy/stateful sidecars, each its own image
    hindsight/Dockerfile
    openbrain/Dockerfile
  recipes/                     # hand-authored per-integration definitions
    omp/recipe.yaml            # base recipe: claude-hooks-bridge + pi-adapter
    hindsight/recipe.yaml
    gsd/recipe.yaml
    caveman/recipe.yaml
  stacks/                      # authored stack manifests (harness + recipes)
    claude-openbrain-headroom-caveman/stack.yaml
    transparent/stack.yaml     # built-in: host-mirror mode (the old `container`)
  profiles/                    # GENERATED + committed; mounted into the harness container
    claude-openbrain-headroom-caveman/
      .claude/{skills,commands,agents,hooks,rules}/
      hatago.config.json
  lib/                         # runtime bash mounted into instances (NOT the assembler — see tools/)
    mounts.sh                  # shared host-integration mount layer (§4a)
    hooks/{run-hook.sh,lib-*.sh}
```

Relationship: `recipes/` (inputs) + `stacks/<name>/stack.yaml` (composition) → **assemble** →
`profiles/<name>/` (committed output, mounted) + hatago config + ensured images.

## 11. Proposed: recipe schema (`recipes/<name>/recipe.yaml`)

```yaml
name: hindsight
description: Hindsight long-term memory (postgres + MCP)

# --- MCP layer ---
mcp:
  servers:
    - name: hindsight
      service: hindsight        # references services/hindsight → shared sidecar
      url_env: HINDSIGHT_URL    # optional env injected into the instance

    # light server alternative (hatago runs it as a child, wraps stdio→HTTP):
    # - name: fetch
    #   command: uvx
    #   args: ["mcp-server-fetch"]
    #   transport: stdio

# --- File-extension layer (Claude-canonical) ---
plugins:                        # vendored via vendor-plugin
  - marketplace: hindsight
    plugin: hindsight-memory
    # or: { url: ..., sha: ..., subdir: ... }

skills:                         # standalone skill dirs shipped by this recipe
  - path: skills/hindsight-docs

hooks:
  event_dir: hooks              # NN-name.sh handlers grouped under <Event>.d/

# Dependencies — uv for Python, pnpm for Node (never npm/npx — see §7). Usually AUTO-DETECTED
# from a vendored plugin's own files; declare here for standalone recipes / overrides.
deps:
  python: pyproject.toml        # requirements.txt → `uv pip install -r`
                                # pyproject.toml   → `uv venv` + `uv pip install -e .`
  node: package.json            # → `pnpm install` (managed supply-chain config)
```

`omp` base recipe:

```yaml
name: omp
description: omp/pi base — consume Claude-format hooks/skills

extensions:                     # omp-native extensions installed into the instance
  - package: npm:@ryan_nookpi/pi-extension-claude-hooks-bridge
```

## 12. Proposed: stack manifest (`stacks/<name>/stack.yaml`)

```yaml
# isolated stack (recipe-composed)
name: claude-openbrain-headroom-caveman
config: isolated              # isolated (default) | transparent
harness: claude               # claude | omp  (exactly one)
permissions: yolo             # prompt (default) | yolo — writes per-harness skip-permission
                              #   config (Permissions.md) into the profile; safe in an isolated instance

recipes: [openbrain, headroom, caveman]
services: [openbrain]         # shared services attached by reference

state:
  persist: true               # default; `--fresh` overrides at runtime
  session_state: host         # host (default — projects/history persist, inspectable) | volume
```

Built-in `transparent` stack (the old `container` — host-mirror, no recipes/services):

```yaml
name: transparent
config: transparent           # mount host ~/.claude, ~/.codex, ~/.config/opencode, ~/.gemini live
# harness omitted: transparent mirrors all host harness configs; pick one in the shell
```

## 13. Proposed: CLI surface

```
harnessed <stack> [path]      # start/attach a stack against cwd (or path), then exec the harness
harnessed transparent [path]  # host-mirror mode (= today's `container`); alias: `container`
harnessed build <stack>       # assemble recipes → profile + images (build-time)
harnessed install <stack>     # write ~/.local/bin/<stack> launcher shim (see below)
harnessed uninstall <stack>   # remove the launcher shim
harnessed --fresh <stack>     # start with empty state volumes
harnessed new <stack> --harness claude --recipes a,b,c   # scaffold a stack manifest
harnessed list                # stacks + running instances
harnessed stop <stack>
harnessed rm <stack>
harnessed svc up <service>    # start a shared service (publishes its port; peers reach it via host.containers.internal, or by DNS name under HARNESSED_NET)
harnessed svc down <service>
harnessed svc list
harnessed auth snyk|socket    # one-time: set a scanner token (persisted to host config)
```

**Naming/identity (proposed):**
- pod: `harnessed-<stack>-<projhash>` — same stack runnable across projects without recreate
  (bind mounts are fixed at creation, so the project is part of identity).
- shared services: global by name (`hindsight`), reached via the host gateway `host.containers.internal:<port>` (or by DNS name over the `HARNESSED_NET` bridge on bridge-capable hosts).

### Generated launcher shim (`harnessed install`)

`harnessed install <stack>` writes an executable `~/.local/bin/<stack>` so you can launch an instance
by name from anywhere (mirrors the repo's existing `install.sh`, which puts `container` on PATH):

```bash
#!/usr/bin/env bash
# generated by `harnessed install claude-openbrain-headroom-caveman`
HARNESSED_PATH=/home/you/Programming/.../harnessed     # abs path to the harnessed executable
HARNESSED_NAME=claude-openbrain-headroom-caveman       # the stack to launch
exec "$HARNESSED_PATH" "$HARNESSED_NAME" "$@"           # "$@" forwards an optional project path
```

Then `claude-openbrain-headroom-caveman [path]` from any directory starts that instance.
`harnessed uninstall <stack>` removes the shim.

## 14. Open / to verify during execution

- **Minimal `.claude.json` stub fields.** Boot an instance and confirm no re-login/onboarding prompt.
  Candidate set: `oauthAccount`, `userID`, `hasCompletedOnboarding` (+ possibly `firstStartTime`,
  `numStartups`). [INFERENCE — verify empirically.]
- **Per-server MCP transport.** Which servers already speak Streamable HTTP vs need hatago's
  stdio→HTTP wrapping (hindsight already runs as postgres+MCP, likely network-native).
- **Intra-stack collision policy.** Confirm fail-fast (reuse `sync-plugin-links`' conflict exit)
  is the desired behavior vs last-wins/namespacing when two recipes ship the same skill/command name.
- **Harness config mount points.** Exact target paths per harness (claude `~/.claude/...`;
  omp config dir) for the profile mount.
- **`container` alias.** Keep `container` as a thin alias → `harnessed transparent` for muscle
  memory, or remove once `harnessed` lands. (Recommendation: keep — zero cost.)
- **hatago placement.** Confirmed: in the pod over HTTP (not stdio inside the harness container) to keep npx/uvx out of
  the harness container — re-verify once a real stack is built.
- **Editor/tool configs in isolated mode.** §4a mounts `~/.config/<tool>` (nvim, etc.) for all
  stacks as operational. Confirm that's wanted in `isolated` instances, or gate behind a flag if a
  truly empty environment is ever needed.
- **Host-projects scope.** Does `session_state: host` write the host's own `~/.claude/projects/`
  (full continuity with host claude) or a harnessed-owned dir (`~/.harnessed/projects/`) to keep
  instance sessions separate? (Recommendation: harnessed-owned.)
- **Container home path.** `/home/harnessed/<relpath>` (vs `container.sh`'s `/container/$USER`)
  for a legible, stable project slug — confirm it doesn't break the harness installs.
- **pnpm rollout (resolved, phase 3).** mise routes its `npm:` backend through pnpm
  (`npm.package_manager=pnpm`, confirmed in the harnessed-base build). `minimumReleaseAge=1440`
  + `strictDepBuilds` (default-deny) ship in the global config. `allowBuilds` is project-scoped
  (pnpm-workspace.yaml) — v11 rejects it globally — so the allowlist is deferred until a
  build-script package (esbuild) actually needs to run.
- **`CLAUDE_CONFIG_DIR` relocation.** Verify whether it relocates `~/.claude.json` (not just the
  `.claude/` dir). If yes, both modes can point Claude at a per-instance config dir instead of
  copy-on-start, fully decoupling container state from the host file. [INFERENCE — verify.]

## 15. Proposed: implementation — single dependency, containerized assembler

**Goal: the only host dependency is podman/docker.** No host Python/node/uv version roulette.

Two phases, and the host runs podman **natively** throughout — the container only emits files, it
never drives the daemon (so there is no Docker-out-of-Docker):

- **Assemble (build time) — `harnessed-tools`, the assembler image (built first run / `--build`).**
  Python + `rich` (and `textual` if a TUI lands) + `yq`/`jq` + `git` + `pnpm` + the supply-chain
  scanners (+ varlock/`op`). Holds *all* assembly logic: parse/validate YAML, vendor
  (`vendor-plugin`), `sync-plugin-links` (already Python), merge `hatago.config.json`, generate the
  `.claude.json` stub, write yolo configs, scan. The host bootstrap runs it as
  `podman run -v <build-dir> harnessed-tools …`; it **only reads/writes the mounted dir and emits
  files** — a `Dockerfile` (+ build context) per image, the committed `profiles/<stack>/`,
  `hatago.config.json`, and a generated launcher. It does **not** run podman. (This is
  "tool-in-a-container", like running a linter in a container — not DooD.)
- **Build → install → launch (host).** The **host** runs `podman build` on the emitted Dockerfiles
  → pinned images. `harnessed install <stack>` writes the generated launcher to `~/.local/bin/<stack>`.
  That launcher is plain **host bash**: it computes the §4a conditional mounts on the host (like
  today's `container.sh`) and runs the pod via host `podman pod`/`podman run`, attaching with
  `podman exec -it`. `harnessed <stack>` and `container` delegate to it.
- **`harnessed` — thin host bootstrap (bash, dependency-free).** Detects the runtime; for
  `harnessed build` it ensures the assembler image exists then drives assemble → `podman build`; for
  `harnessed <stack>` (run) it invokes the generated host launcher.

This supersedes the earlier "bash orchestrator + Python assembler" split *and* the interim "one image
that drives the host daemon" idea: assembly logic consolidates into one container image that emits
files; building and launching are ordinary host podman commands. (Testing is integration-only — see
§18 — not assembler unit tests.)

**Why no DooD.** Separating "generate the build/run inputs" (the assembler, needs Python) from
"execute `podman build`/`podman run`" (the host, needs the daemon) removes every cost of driving the
daemon from inside a container:

- **No API socket to mount, no `CONTAINER_HOST`/`DOCKER_HOST`.** podman is invoked directly on the host.
- **No host-absolute-path footgun.** The launcher runs on the host, so `$HOME`/`$PWD`/project paths
  are host-native by construction — the classic DooD bind-path gotcha cannot occur.
- **Clean TTY for free.** The launcher is host bash, so the interactive `podman exec -it` attach is
  host-native with no tunneling.
- **First-run build latency** — mitigate by pinning the assembler image and optionally publishing a
  prebuilt one; later runs are cache hits.

`transparent` is the degenerate case: no recipes → no assembler and no `harnessed-tools` image. It is
just a host launcher running the prebuilt `harnessed-claude` image with the §4a mounts +
`.claude.json` copy-on-start. The assembler image is only needed once you assemble an `isolated` stack.

Net install: `git clone` + symlink the `harnessed` bootstrap; first `build` builds the assembler
image. Podman/docker is the only thing the user must have.

## 16. Proposed: secrets — varlock + 1Password (optional)

**varlock is optional — harnessed works fully without it.** It's an opt-in secrets source: if you
use it, secrets resolve from **1Password** instead of loose files. varlock reads a `.env.schema`
(`@env-spec` DSL) whose secret values are `op(op://Vault/Item/field)` references, validates them, and
injects the resolved values into a process (`varlock run -- <cmd>`, or `varlock load --format env`
to emit the dotenv, which is what harnessed uses — see below). Copying the shipped
`.env.schema.example` is what turns it on; users who skip it lose nothing else.

**Schema locations (XDG):**

- `~/.config/harnessed/.env.schema` — harnessed-level secrets (e.g. `SNYK_TOKEN`,
  `SOCKET_SECURITY_API_KEY`). The repo ships **`.env.schema.example`** to copy here.
- `~/.config/<service>/.env.schema` — per-service secrets (e.g. `~/.config/hindsight/.env.schema`),
  loaded when that service starts (`harnessed svc up <service>`).
- (optional, later) per-stack overrides referenced from `stack.yaml`.

**How harnessed uses it:**

- On launch, `harnessed` checks for a relevant `.env.schema`. **Present (opt-in) →** resolution runs
  `varlock load --format env` **on the host**; the resolved dotenv is written to a mode-0600 temp
  env-file that the launcher spreads into the container (`--env-file`, unlinked after launch). This
  reaches **all four** launch paths — the isolated pod, the transparent instance, per-service sidecars
  (`~/.config/<service>/.env.schema`), and the build scan. **Absent (the default) →** plain host env
  passthrough (the §7 scanner present/skip logic still applies); with no schema, varlock is never
  invoked.
- **App-auth runs on the host, not in the container.** 1Password's desktop app authorizes the `op` CLI
  by *calling application* — the user's terminal. An `op` running inside a throwaway container has no
  host app to bind the grant to, so app-auth (`@initOp(allowAppAuth=true)`) fails there ("cannot
  connect to 1Password app") regardless of which socket is mounted. The `~/.1password/agent.sock`
  mounted in §4a is the **SSH agent** (for git commit signing), **not** the `op` app-auth transport.
  So varlock + `op` run on the host; the resolved env is what crosses into the container.
- The in-container path is the **headless fallback**, used only when the host has no `varlock` (e.g.
  CI, the nightly timer): there the schema resolves inside a `--rm` tools container with
  `OP_SERVICE_ACCOUNT_TOKEN` (HTTPS bearer auth — no desktop app, no app-auth, no socket). It stays
  **inert unless a schema exists.**
- Resolved secrets are injected as **env only** — never written to the repo, a committed profile, or
  an image layer (same rule as Claude auth).

## 17. Proposed: documentation (first-class deliverable)

Docs are a **gated deliverable, not an afterthought** — `harnessed` is a tool other people (and
future-you) must operate. Required surface, by audience:

- **README.md** — what `harnessed` is, the two modes, install (`git clone` + bootstrap), first-run
  build, a 60-second quickstart. Updated alongside the existing `container` README.
- **docs/harnessed-design.md** (this file) — architecture + decisions; the source of truth for *why*.
- **Recipe authoring guide** — writing `recipes/<name>/recipe.yaml`: MCP servers, file extensions,
  deps, the Claude-canonical rule, the pnpm rule — with one worked example end to end.
- **Stack guide** — composing recipes into `stacks/<name>/stack.yaml`; `transparent` vs `isolated`;
  `permissions` / `session_state`; `harnessed install`.
- **Secrets setup** — varlock + 1Password (§16): copying `.env.schema.example`, `op(op://…)` refs.
- **Service authoring** — adding a heavy sidecar under `services/` (image + `.env.schema`).
- **Troubleshooting / ops** — podman socket, first-run build, auth/onboarding, `--fresh`,
  inspecting host-persisted sessions.

Cadence: each section lands **with** the feature it documents (a feature isn't "done" until its docs
exist), per this repo's existing AGENTS.md / README conventions. This design spec stays current as
decisions change (as it has through this session).

## 18. Proposed: testing — integration only, behavior through the instance

Per the project's TDD philosophy (`tdd` skill): **test behavior through the public interface, and
write tests that survive refactors.** For harnessed the public interface is the **running instance**, and
the behavior is "the instance exposes exactly the MCP servers / skills / commands its stack declares."

- **No assembler unit tests.** Testing `vendor`/`sync-links`/merge internals couples to
  implementation and breaks on refactor — the anti-pattern the TDD skill warns against. The
  assembler is covered *transitively*: wire the wrong thing and the capability test fails.
- **The stack manifest is the test oracle.** Expected capabilities (`recipes` → MCP servers +
  skills + commands; `services`) are derived from `stack.yaml`; the test asserts the live instance
  matches. It reads like a spec: "`claude-openbrain-headroom-caveman` exposes MCP `openbrain` and
  skills `headroom`, `caveman`."

**Canonical capability test (per stack):**

1. `harnessed build <stack>` → `harnessed <stack> --fresh <scratch-project>` in **headless** mode
   (claude `-p … --output-format json`; omp's non-interactive equivalent — exact flags to verify).
2. Assert the declared capabilities are present, preferring **machine-readable introspection** for
   determinism, with the LLM prompt as the behavioral backstop:
   - **MCP servers** — hatago's `hatago://servers` resource (JSON snapshot of connected servers)
     and/or `claude mcp list`; assert the manifest's servers are connected.
   - **Skills / commands** — ask the harness, headless, to emit the skills/commands it sees as JSON
     and diff against the manifest; the natural-language "confirm you can use skill X, MCP Y" prompt
     is the human-readable check on top.
3. Tear the instance down (`--fresh` guarantees no state bleed between runs).

**Capability report — the test output is a user artifact.** The same check renders a **markdown
report** ("how well the recipe built"), not just a CI pass/fail. The expected-from-manifest vs
present-in-instance comparison becomes a per-capability table:

```
## claude-openbrain-headroom-caveman — capability report
| capability | kind    | status                    |
|------------|---------|---------------------------|
| openbrain  | mcp     | ✓ connected               |
| headroom   | skill   | ✓ present                 |
| caveman    | skill   | ✓ present                 |
| gsd        | command | ✗ missing (sync conflict) |
```

`harnessed build` renders it with `rich` (already in the tools image; markdown → terminal); CI
consumes the same structured result as the assertion. One mechanism, two audiences — the user sees
how complete/healthy the build is, CI sees green/red.

**Build harnessed itself in vertical slices** (tracer bullets, not horizontal): the first slice is a
minimal stack — one harness + one MCP server + one skill — with its capability test green end to end
(assemble → run → assert). Then add recipes one at a time, each with its own red→green capability
test. Never "write all recipes, then all tests."

**Honest tradeoff:** integration-only means an assembler bug surfaces as a capability failure, not a
pinpointed unit failure — coarser to debug. Mitigate with clear assembler errors (e.g.
`sync-plugin-links`' explicit conflict reporting) so a failed build says *what* it couldn't wire.
