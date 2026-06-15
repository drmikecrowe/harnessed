# Architecture Research

**Domain:** Containerized, composable AI-coding-harness launcher (rootless podman pod orchestrator + build-time assembler)
**Researched:** 2026-06-14
**Confidence:** MEDIUM — core architecture (§2–§9 of the design spec) is confirmed; repo layout / schemas / CLI (§10–§13) are proposed; external facts (podman pods, MCP transports, pnpm, scanners, 1Password) are web-verified HIGH.

## Standard Architecture

### System Overview

`harnessed` is a two-image control plane (a dependency-free **bash bootstrap** on the host + a fat **`harnessed-tools` Python image** that holds all logic) that composes harness *stacks* as **podman pods** at runtime. The tools image is the "brain": it drives the **host** podman over the rootless socket (Docker-out-of-Docker), assembles profiles, and `podman run`s the pod — but the final interactive attach is performed **host-natively** by the bootstrap for a clean TTY.

```
┌──────────────────────────── HOST (user namespace, rootless) ─────────────────────────────┐
│                                                                                          │
│  $ harnessed <stack> [path]                                                              │
│        │                                                                                 │
│        ▼                                                                                 │
│  ┌──────────────────────┐   builds/ensures, then runs (DooD)   ┌──────────────────────┐ │
│  │  harnessed (bash)    │ ───────────────────────────────────▶ │  harnessed-tools     │ │
│  │  bootstrap, dep-free │   -v repo  -v ~/.claude/.credentials  │  (Python = "brain")  │ │
│  │  • detect runtime    │   --env HOST_HOME/HOST_PWD            │  rich/textual yq jq  │ │
│  │  • ensure tools img  │   -v podman.sock (CONTAINER_HOST)     │  git pnpm uv scanners│ │
│  │  • final attach ─────┼──┐                                    │  varlock op          │ │
│  └──────────────────────┘  │                                    └──────────┬───────────┘ │
│                            │  podman exec -it (host-native TTY)             │ drives host  │
│                            │                                                │ podman via   │
│   rootless podman.socket ◀─┼────────────────────────────────────────────────┘ mounted sock│
│   /run/user/$UID/podman/podman.sock                                                       │
│        │ podman run --pod                                                                 │
│        ▼                                                                                  │
│  ┌──────── podman pod: harnessed-<stack>-<projhash>  (shared netns; localhost:port) ────┐ │
│  │  ┌─────────────────────────┐   .mcp.json → localhost:3535   ┌──────────────────────┐│ │
│  │  │ harnessed-<harness>     │ ─────────────────────────────▶ │ hatago (MCP hub)     ││ │
│  │  │  claude | omp           │   MCP / Streamable HTTP        │  one HTTP endpoint    ││ │
│  │  │  -v cwd  -v profile     │                               │  child stdio servers  ││ │
│  │  │  auth seeded            │                               │  (pnpm dlx / uvx)     ││ │
│  │  └─────────────────────────┘                               └──────────┬───────────┘│ │
│  └────────────────────────────────────────────────────────────────────  │  ───────────┘ │
│                                                          MCP over harnessed-net (by name) │
│                          ┌───────────────────────────────────┴───────────────────────┐  │
│                          ▼                                                             ▼  │
│              ┌───────────────────────┐                            ┌───────────────────────┐
│              │ hindsight (sidecar)   │                            │ openbrain (sidecar)   │
│              │ postgres + MCP        │                            │ own image · volume    │
│              │ service-scoped volume │                            │ service-scoped · shared│
│              │ shared · concurrent   │                            │ lifecycle independent │
│              └───────────────────────┘                            └───────────────────────┘
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

**Transparent mode is the degenerate case:** harness container only — no pod siblings, no hatago, no sidecars. Host `~/.claude` (+ `.codex`/`.config/opencode`/`.gemini`) is mounted live; MCP comes from the host's own config. The pod / hatago / sidecar machinery applies **only** to `isolated` stacks.

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| **`harnessed` bootstrap** | Dependency-free host entry: detect runtime, ensure/build `harnessed-tools`, hand off to it, then perform the **host-native interactive attach** (`podman exec -it`). Owns nothing else. | Single POSIX/bash script symlinked onto `PATH` (mirrors existing `install.sh`/`container.sh` install path). |
| **`harnessed-tools` image** | The brain: parse/validate YAML, vendor plugins, fan skills/commands (`sync-plugin-links`), merge `hatago.config.json`, generate `.claude.json` stub, write permissions config, run supply-chain scanners, and **drive host podman** (build images, create pod, run containers) over the mounted rootless socket. | One Python image: `rich`/`textual` TUI + `yq`/`jq` + `git` + `pnpm` + `uv` + osv-scanner/pip-audit (+snyk/socket) + `varlock` + `op`. |
| **harness container** | Run the harness (`claude`/`omp`) against the mounted project, auth seeded, with the stack profile mounted into the harness config dir. The only container the user "is in". | `FROM harnessed-base` → `harnessed-claude` / `harnessed-omp` (mise/node/python base). |
| **hatago hub** | Aggregate the stack's MCP servers behind **one** Streamable-HTTP endpoint (default `:3535`); run light `pnpm dlx`/`uvx` **stdio** servers as its own children (stdio→HTTP) and **proxy** heavy network-native servers. Keeps `npx`/`uvx` out of the harness container. | `@himorishige/hatago-mcp-hub` baked into `Dockerfile.hatago` with light servers; HTTP serve mode. |
| **service sidecars** | Heavy/stateful systems (hindsight = postgres+MCP, openbrain). Each owns its image/container/**service-scoped volume**/lifecycle, independent of any instance; multiple instances attach concurrently over `harnessed-net`. | `services/<svc>/Dockerfile`, standalone & independently versioned; volume named for the *service* (`hindsight-data`). |
| **profile (committed → mounted)** | The assembled Claude-canonical file-extension tree (`skills/commands/agents/hooks/rules/.mcp.json/settings.json`) for one stack — editable, git-versioned, mounted read/write into the harness config dir. | Generated dir `profiles/<stack>/.claude/…` + `hatago.config.json`; produced by the assembler, committed. |
| **baked images** | Reproducible, pinned MCP-server dependencies (`pnpm dlx`/`uvx`/python deps) and base lineage — kept out of the profile so the host stays clean. | Build-time Docker images: `harnessed-base`/`-claude`/`-omp`, `hatago`, per-service. |

## Recommended Project Structure

```
code-container/
├── harnessed                       # thin bash bootstrap → builds/runs the tools image (§15)
├── container                       # back-compat alias → `harnessed transparent` (§14: keep)
├── .env.schema.example             # varlock template → ~/.config/harnessed/.env.schema (§16)
├── tools/                          # the brain — harnessed-tools image (assemble + orchestrate)
│   ├── Dockerfile                  # python + rich/textual + yq/jq + git + pnpm/uv + scanners + varlock + op
│   ├── pyproject.toml
│   └── harnessed/                  # cli, assemble, vendor, sync-links, validate, orchestrate
├── base/                           # base-lineage images (FROM = lineage only, §6)
│   ├── Dockerfile.harnessed-base   # mise/node/python + common tooling + managed pnpm config
│   ├── Dockerfile.harnessed-claude # FROM harnessed-base + claude install
│   ├── Dockerfile.harnessed-omp    # FROM harnessed-base + omp install
│   └── Dockerfile.hatago           # hatago + light pnpm-dlx/uvx stdio MCP servers
├── services/                       # heavy/stateful sidecars, each its own image/volume/lifecycle
│   ├── hindsight/Dockerfile
│   └── openbrain/Dockerfile
├── recipes/                        # hand-authored per-integration definitions (inputs)
│   ├── omp/recipe.yaml             # base recipe: claude-hooks-bridge + pi-adapter
│   ├── hindsight/recipe.yaml
│   ├── gsd/recipe.yaml
│   └── caveman/recipe.yaml
├── stacks/                         # authored stack manifests (composition: harness + recipes)
│   ├── claude-openbrain-headroom-caveman/stack.yaml
│   └── transparent/stack.yaml      # built-in host-mirror mode (the old `container`)
├── profiles/                       # GENERATED + committed; mounted into the harness container
│   └── claude-openbrain-headroom-caveman/
│       ├── .claude/{skills,commands,agents,hooks,rules}/
│       └── hatago.config.json
└── lib/                            # runtime bash mounted INTO instances (not the assembler)
    ├── mounts.sh                   # shared host-integration mount layer (§4a)
    ├── egress-firewall.sh          # ported verbatim from existing repo
    └── hooks/{run-hook.sh,lib-pi-adapter.sh}
```

### Structure Rationale

- **`tools/` (Python brain) vs `lib/` (runtime bash):** hard split between *build/orchestration logic* (runs inside `harnessed-tools`, never on the host) and *per-instance runtime glue* (mounted into the launched harness container). Keeping them apart stops the assembler from leaking host-runtime assumptions and keeps the only host dependency podman/docker (§15).
- **`recipes/` (inputs) → `stacks/` (composition) → `profiles/` (output):** a clean pipeline boundary. Recipes are reusable single-integration definitions; stacks pick a harness + a set of recipes; profiles are the **generated** artifact. Recipes/stacks are hand-authored and reviewed; profiles are regenerable, so a diff in `profiles/` is auditable evidence of what the assembler produced.
- **`base/` separate from `services/`:** `base/` holds *lineage* images consumed by every stack (harness + hatago); `services/` holds *independently versioned, standalone* sidecars reusable across stacks. Encodes the §6 rule — `FROM` is for base lineage, not for unioning systems.
- **`profiles/` committed and mounted (not baked):** the file-extension layer must be editable and versioned (satisfies "commands/skills/agents/hooks proxied to a git-controlled folder"); MCP deps are baked into images instead so the host stays pinned/clean. This split is the central structural decision.
- **`transparent/stack.yaml` lives beside isolated stacks:** transparent is *just another stack* (one engine, two modes), so it belongs in `stacks/`, not in a special-cased code path.

## Architectural Patterns

### Pattern 1: Runtime pod composition (not build-time `FROM` union)

**What:** Two sibling systems (a harness + an MCP hub, plus shared sidecars) are combined by placing them in a **podman pod** sharing one network namespace, assembled at `podman run` time — never by an image build step.
**When to use:** Whenever you must combine independently-built, independently-versioned systems that each own runtime state. Here: harness ⊕ hatago ⊕ sidecars.
**Trade-offs:** (+) Each component stays independently built, versioned, and scaled; sidecars outlive instances and are shared concurrently. (+) Containers in a pod reach each other on `localhost:<port>` (shared netns), so the harness's `.mcp.json` points at `localhost:3535` with no DNS. (−) Composition logic moves to runtime orchestration (the tools image) instead of a declarative Dockerfile; the pod must be (re)created when bind mounts change.

**Why `FROM` cannot do this:** `FROM` is *linear inheritance*; multiple `FROM`s make a *multi-stage* build whose **last** stage is the image, with `COPY --from=…` pulling artifacts forward. There is **no "union two images" operator.** You cannot merge two running systems (each with its own processes/state) into one image — only copy files between build stages. Hence runtime, not build time.

```bash
# Compose at runtime — pod gives shared netns + localhost addressing
podman pod create --name "harnessed-${stack}-${projhash}" --network harnessed-net
podman run -d --pod "harnessed-${stack}-${projhash}" --name hatago      harnessed-hatago
podman run -d --pod "harnessed-${stack}-${projhash}" --name "${harness}" \
  -v "${HOST_PWD}:/home/harnessed/${relpath}" \
  -v "${HOST_HOME}/code-container/profiles/${stack}/.claude:/home/harnessed/.claude:rw" \
  "harnessed-${harness}"
# harness reaches hatago at http://localhost:3535 (same netns); sidecars by name on harnessed-net
```

### Pattern 2: Split assembly output — committed→mounted profile + baked→images

**What:** The assembler emits to **two distinct sinks**: the Claude-canonical file tree → a git-committed `profiles/<stack>/` dir **mounted** into the harness; MCP servers and their `pnpm dlx`/`uvx`/python deps → **baked** into images.
**When to use:** When some artifacts must stay human-editable and versioned (skills/commands/hooks) while others must stay pinned, reproducible, and off the host (dependency trees).
**Trade-offs:** (+) Editable, diffable extensions without rebuilding an image; pinned, clean dependency closure without polluting `~`. (+) "Nothing assembled at container start" → satisfies "not dynamic." (−) Two artifact lifecycles to keep in sync; a profile edit that needs a new MCP dep still requires an image rebuild.

### Pattern 3: Docker-out-of-Docker with host-absolute bind paths

**What:** The tools container drives the **host** podman through the mounted **rootless** socket (`CONTAINER_HOST=unix:///run/user/$UID/podman/podman.sock`). Because bind-mount sources resolve on the **host** daemon, every `-v` the tool issues MUST use **host-absolute** paths — so the bootstrap passes host `HOME`/`PWD` in as env.
**When to use:** When a containerized controller must create sibling containers on the host engine without requiring host language runtimes.
**Trade-offs:** (+) Only host dependency is podman/docker; no Python/node/uv version roulette. (+) Rootless scopes blast radius to the user. (−) The classic DooD gotcha: a path that looks right *inside* the tools container is wrong on the host daemon — using the tool's internal view silently mounts the wrong thing. (−) Rootless socket may need `systemctl --user enable --now podman.socket`; first-run image build adds latency (mitigate by pinning/publishing the tools image). (−) Keep the **final interactive attach host-native** (bootstrap, not tunneled through the tool container) so TTY allocation is clean.

### Pattern 4: Claude-canonical format + omp bridge adapter

**What:** Claude Code format is the **single source of truth** for skills/commands/hooks/plugins. `claude` mounts it natively; `omp` adapts *out* of it at runtime via `claude-hooks-bridge` + `lib-pi-adapter.sh` (no re-authoring). Exactly **one harness per stack**.
**When to use:** Multi-harness support where re-authoring per harness would be the real cost.
**Trade-offs:** (+) One authoring format, no drift, no duplicate maintenance; new harnesses are an adapter, not a fork of all content. (−) Non-Claude harnesses inherit a translation layer (the pi-adapter normalizes omp/GSD hook payloads → Claude shape); a Claude-only construct with no omp analogue can't be expressed.

### Pattern 5: One engine, two config modes on a single mount axis

**What:** `transparent` and `isolated` share the *same* base image, host-integration mounts (§4a), project mount, and auth. They differ on **one axis only** — where the config layer comes from: host `~/.claude` bind-mounted live (transparent) vs auth-seeded + assembled profile mounted (isolated).
**When to use:** When two seemingly different products are actually the same engine with one swapped input — collapse them rather than maintaining parallel code paths.
**Trade-offs:** (+) Minimal surface; `transparent` == the old `container` for free; isolated adds the pod/hatago/sidecar machinery only when `config: isolated`. (−) The shared host-integration layer means isolated instances are *authenticated and signed* (SSH/GPG/1Password), not hermetic — a deliberate choice (credentials are not the experiment surface), but worth gating if a truly empty environment is ever needed (§14).

**Mount-axis detail (the `.claude.json` safety fix):** `~/.claude.json` is a single whole-file blob Claude rewrites constantly (~450 KB of state, not auth). It is **never rw-bind-mounted** in either mode — transparent seeds a writable per-instance copy (copy-on-start) or relocates via `CLAUDE_CONFIG_DIR`; isolated **generates** a minimal stub (candidate fields `oauthAccount`/`userID`/`hasCompletedOnboarding`, §14). Only the real credential `~/.claude/.credentials.json` is mounted read-only.

## Data Flow

### Assemble pipeline (`harnessed build <stack>`)

```
recipes/<r>/recipe.yaml  ─┐
stacks/<stack>/stack.yaml ┴─▶ harnessed-tools (Python brain)
                                 │ vendor-plugin   → resolve marketplace/url/git plugins, install uv/pnpm deps
                                 │ sync-plugin-links → fan skills/commands → harness-native paths (FAIL-FAST on collision)
                                 │ wire hooks      → <Event>.d handlers + pi-adapter
                                 │ merge MCP       → hatago.config.json
                                 │ SUPPLY-CHAIN GATE → osv-scanner + pip-audit (always);
                                 │                     snyk + Socket.dev (token present, else warn-skip);
                                 │                     FAIL on high-severity  ◀── gate before any commit/publish
                                 ▼
            ┌──────────────── split output ────────────────┐
            ▼                                               ▼
   profiles/<stack>/  (committed, mounted)        baked images (pinned, host-clean)
   .claude/{skills,…} + hatago.config.json        harnessed-base/-claude/-omp, hatago, services/*
```

### Launch flow (`harnessed <stack> [path]`)

```
bootstrap (bash)
  └▶ ensure harnessed-tools image (build on first run)
       └▶ podman run harnessed-tools  (DooD: rootless sock + HOST_HOME/HOST_PWD env)
            ├▶ resolve stack, validate, ensure pod images present (build if missing)
            ├▶ ensure shared services up on harnessed-net (start if absent; svc-scoped volume)
            ├▶ podman pod create harnessed-<stack>-<projhash>  (--network harnessed-net)
            ├▶ podman run hatago (HTTP :3535) into the pod
            └▶ podman run harness into the pod
                 -v HOST_PWD:/home/harnessed/<relpath>      (host-absolute!)
                 -v profiles/<stack>/.claude  -v ~/.claude/.credentials.json:ro
       ◀── control returns to bootstrap
  └▶ podman exec -it harnessed-<stack>-<projhash> <harness>   (HOST-NATIVE TTY)
```

`--fresh` swaps persistent state volumes for throwaway ones; `session_state: host` (default) persists `projects/` + `history.jsonl` to a harnessed-owned host dir (path-mirrored for a legible Claude slug), `: volume` opts into a per-instance throwaway volume (§9, §14).

### MCP flow (request path inside a running isolated stack)

```
harness (claude/omp) reads profile .mcp.json  → http://localhost:3535  (same pod netns)
        │ Streamable HTTP (JSON-RPC 2.0; SSE only for back-compat)
        ▼
hatago MCP hub  ─┬─▶ child stdio server (pnpm dlx / uvx)   stdio→HTTP wrapped, baked in hatago image
                 └─▶ proxied network-native server          over harnessed-net, by service name
                         e.g. hindsight (postgres+MCP, likely Streamable-HTTP-native, §14)
```

### Key Data Flows

1. **Recipe → capability:** a recipe contributes an MCP layer (→ hatago config / service ref) and/or a Claude-canonical file-extension layer (→ profile). The stack manifest selects recipes; the assembler is the only place these merge.
2. **Manifest as test oracle:** `stack.yaml`'s declared recipes/services derive expected capabilities; the integration capability test asserts the **live** instance matches (hatago `hatago://servers` resource + `claude mcp list` for MCP; headless harness JSON introspection for skills/commands), rendering a `rich` markdown capability report (§18).
3. **Secret resolution (opt-in):** if a `.env.schema` exists, the launch is wrapped in `varlock run --` so `op(op://…)` refs resolve from 1Password and reach the tool container / instance / sidecar as **env only** — never an image layer or committed file (§16).

## Build-Order & Scaling Considerations

The relevant "scale" axis is **number of stacks/instances/shared services and recipe count**, plus the **build order** of harnessed itself. There are no user-count tiers; concurrency is bounded by your machine and the shared-service model.

| Scale axis | Architecture adjustments |
|------------|--------------------------|
| 1 stack, 1 instance, 0 services | Pod = harness + hatago only; or transparent (harness only). Trivial; this is the first vertical slice. |
| Several stacks, concurrent instances, shared services | Services run **once** per service on `harnessed-net`, owned by the service not any instance; `claude+hindsight` and `omp+hindsight` share **one** `hindsight-data` volume. Instances start a service if absent (`harnessed svc up/down`). Pod identity includes the project hash so the same stack runs across projects without recreate. |
| Many recipes / large dependency closure | Supply-chain gate cost grows; cache vendored trees and baked layers; `minimumReleaseAge` quarantine window and `onlyBuiltDependencies`/`allowBuilds` allowlist need tuning (too tight blocks legit native builds, too loose weakens the guard). Nightly re-scan (systemd-timer pattern) catches CVEs disclosed after build. |

### Suggested build order — vertical slices (tracer bullets, §18)

1. **Slice 1 — minimal isolated stack green end-to-end:** one harness + one MCP server + one skill → assemble → run `--fresh` headless → capability test asserts MCP connected + skill present. This exercises bootstrap, tools image, DooD pod create, hatago, profile mount, and the test oracle in one thin path.
2. **Then add one recipe at a time**, each with its own red→green capability test (never "write all recipes, then all tests").
3. **Fold in `transparent`** as the degenerate stack (no pod siblings) once the engine exists.
4. **Add shared services** (hindsight/openbrain) once the single-pod path is proven; they introduce the cross-instance concurrency + service-scoped volume concerns.
5. **Layer the supply-chain gate and secrets (varlock/1Password)** last — they are policy/perimeter, gated on a working assemble→run→assert loop.

### Scaling priorities

1. **First bottleneck — first-run image build latency.** Pin and optionally publish a prebuilt `harnessed-tools` (and base) image; later runs are cache hits.
2. **Second bottleneck — shared-service contention / volume coupling.** One postgres serving multiple concurrent instances is fine for a personal tool; if it isn't, the service-scoped volume model is the seam to split (per-stack service volume) without touching the harness side.

## Anti-Patterns

### Anti-Pattern 1: Combining harness systems via `FROM` / multi-stage `COPY`
**What people do:** Try to "merge" claude + omp + an MCP system into one image with multiple `FROM`s.
**Why it's wrong:** `FROM` is linear inheritance; multi-stage only copies *files* between stages — there is no union of two **running** systems with their own processes/state.
**Do this instead:** Combine at runtime in a podman pod (Pattern 1); use `FROM` only for base lineage (§6).

### Anti-Pattern 2: Tool-internal paths in DooD `-v` flags
**What people do:** Use the path as seen *inside* `harnessed-tools` for bind mounts.
**Why it's wrong:** Bind sources resolve on the **host** daemon, so the mount silently points at the wrong place (or nothing).
**Do this instead:** Pass host `HOME`/`PWD` as env and build **host-absolute** paths for every `-v` (Pattern 3).

### Anti-Pattern 3: Bind-mounting `~/.claude.json` read/write
**What people do:** Mount the whole `~/.claude.json` into the container like the rest of `~/.claude`.
**Why it's wrong:** It's a constantly-rewritten whole-file blob; a shared rw mount races with host Claude (lost writes/corruption) and merges container state back into the host. Differing project paths only spare the path-keyed `projects` subtree, not the whole-file rewrite or top-level fields.
**Do this instead:** Mount only `~/.claude/.credentials.json:ro`; copy-on-start a per-instance copy or relocate via `CLAUDE_CONFIG_DIR` (transparent), or generate a minimal stub (isolated).

### Anti-Pattern 4: Running `npx`/`uvx` stdio servers inside the harness container
**What people do:** Put MCP stdio servers directly in the harness container.
**Why it's wrong:** Drags npm/npx/uvx and their dependency trees into the harness image, defeating the clean/pinned host goal and the pnpm-everywhere supply-chain policy.
**Do this instead:** Bake light stdio servers as hatago **children** (stdio→HTTP) and proxy heavy ones; the harness sees one HTTP endpoint (Pattern 1, MCP flow).

### Anti-Pattern 5: Baking or committing credentials
**What people do:** Add Claude auth / scanner tokens / 1Password secrets to an image layer or repo file for convenience.
**Why it's wrong:** Secrets in image layers or git are exfiltration-prone and non-rotatable.
**Do this instead:** Reference host creds, inject as **env only** at launch (varlock/`op` resolve at runtime). Missing credentialed scanner → warn-and-skip, never an interactive prompt (keeps build non-interactive/reproducible).

### Anti-Pattern 6: Dynamic/runtime recipe assembly & assembler unit tests
**What people do:** Resolve recipes at container start, and unit-test the vendor/sync/merge internals.
**Why it's wrong:** Runtime assembly breaks reproducibility ("not dynamic"); internal unit tests couple to implementation and break on refactor.
**Do this instead:** Assemble ahead of time into committed artifacts; verify behavior transitively through the running instance against the manifest oracle (§18).

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| **Host podman engine** | Mount the **rootless** socket into `harnessed-tools`; set `CONTAINER_HOST`/`DOCKER_HOST`. All `-v` use host-absolute paths (DooD). | `unix:///run/user/$UID/podman/podman.sock`; may need `systemctl --user enable --now podman.socket`. Containers in a pod share netns → `localhost:port`; cross-pod via `harnessed-net` by name. |
| **1Password (secrets)** | Optional via varlock: `.env.schema` with `op(op://Vault/Item/field)` refs, resolved through the mounted **agent socket** (`allowAppAuth`, §4a) or a **service-account token**. | For headless/in-container resolution, `OP_SERVICE_ACCOUNT_TOKEN` is the cleaner story; the desktop app-auth socket is finicky inside containers. Confirm which your setup supports (§16, §14). Inert unless a schema exists. |
| **Host auth / signing** | Shared host-integration layer (every stack): 1Password SSH agent (`SSH_AUTH_SOCK`), GPG agent + `~/.gnupg:ro`, YubiKey `--device`, `~/.ssh:ro`, git config:ro, `/etc/machine-id:ro`, egress firewall (`--cap-add NET_ADMIN`). | Ported verbatim from `container.sh start_new_container`; credentials are not the experiment surface, so they belong in isolated too. |
| **Claude auth** | Mount `~/.claude/.credentials.json:ro` (OAuth); generate `.claude.json` stub (isolated). | Never the whole `~/.claude.json`; never baked. |
| **Supply-chain scanners** | osv-scanner + pip-audit always (credential-free, public DBs); snyk + Socket.dev when a token is present (env / host config / varlock ref), else warn-skip. | `harnessed build` fails on high-severity. `harnessed auth snyk|socket` sets a token once via the CLI's own `auth` inside the tools container. |
| **Container registries** | `pnpm`/`uv` pull MCP deps at **build** time under managed supply-chain config; images optionally published to skip first-run build. | pnpm everywhere (no npm/npx); `minimumReleaseAge` quarantine + lifecycle-script default-deny + content-addressed store. |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| **bootstrap ↔ tools** | `podman run` (DooD) for logic; bootstrap keeps the **final interactive attach** host-native. | Contract: bootstrap supplies host `HOME`/`PWD`/socket; tools never assumes its own path view for mounts. The split is what keeps host deps = podman only. |
| **tools ↔ host podman** | Rootless socket (`CONTAINER_HOST`); tools build images, create pod, run containers, ensure services. | Full control of the user's containers (acceptable for a personal dev tool, worth stating). |
| **harness ↔ hatago** | MCP over **Streamable HTTP** at `localhost:3535` (shared pod netns). | Harness `.mcp.json` is the only client config; hatago is the single aggregation point. |
| **hatago ↔ child/proxied servers** | Child stdio servers (stdio→HTTP, baked) + proxied network-native servers over `harnessed-net`. | Per-server transport varies; some speak Streamable HTTP natively, others need hatago wrapping (§14). |
| **instance ↔ shared service** | Over `harnessed-net` by service name; service is service-scoped, harness-independent, concurrent. | `hindsight-data` volume shared by `claude+hindsight` and `omp+hindsight`; service outlives instances (`harnessed svc up/down`). |
| **assembler ↔ profile/images** | Split output: committed→mounted profile (files) + baked→images (deps). | The only place recipes merge; nothing assembled at container start. |

## Sources

- harnessed design spec — `docs/harnessed-design.md` (§2–§18); project context — `.planning/PROJECT.md`.
- Podman pods & rootless networking — containers in a pod share the network namespace and communicate via `localhost:port`; cross-pod by name on a shared network: <https://github.com/containers/podman/blob/main/docs/tutorials/basic_networking.md>, <https://www.redhat.com/en/blog/container-networking-podman>, <https://docs.podman.io/en/stable/markdown/podman.1.html>.
- Rootless podman socket / DooD bind-mount path gotcha & enabling the socket: <https://oneuptime.com/blog/post/2026-03-18-enable-podman-socket-rootless-users/view>, <https://superuser.com/questions/1938342/mount-podman-socket-into-container-rootless-to-rootless>.
- MCP transports (two standard: stdio + Streamable HTTP; SSE back-compat only) — spec 2025-03-26, reaffirmed 2025-11-25: <https://modelcontextprotocol.io/specification/2025-03-26/basic/transports>, <https://blog.modelcontextprotocol.io/posts/2025-12-19-mcp-transport-future/>.
- Hatago MCP Hub (lightweight multi-MCP aggregator; STDIO/HTTP/SSE/WS; proxy + child stdio; default HTTP `:3535`): <https://github.com/himorishige/hatago-mcp-hub>, <https://www.npmjs.com/package/@himorishige/hatago-mcp-hub>, <https://hatago.dev/en/>, <https://dev.to/himorishige/getting-started-with-multi-mcp-using-hatago-mcp-hub-one-config-to-connect-them-all-2bjp>.
- pnpm supply-chain config — `minimumReleaseAge` defaults to 1440 min (1 day) in pnpm v11; lifecycle-script default-deny via `onlyBuiltDependencies`/new `allowBuilds`; content-addressed store integrity: <https://pnpm.io/supply-chain-security>, <https://pnpm.io/settings>, <https://socket.dev/blog/pnpm-11-adds-new-supply-chain-protection-defaults>.
- osv-scanner (credential-free, container/lockfile scanning, CI fail-on-severity) & pip-audit: <https://github.com/google/osv-scanner>, <https://google.github.io/osv-scanner/>, <https://appsecsanta.com/osv-scanner>.
- 1Password CLI in containers — service-account token (`OP_SERVICE_ACCOUNT_TOKEN`) is the cleaner headless story vs desktop app-auth socket: <https://developer.1password.com/docs/service-accounts/use-with-1password-cli/>, <https://www.1password.community/discussions/developers/link-the-1password-cli-in-a-container-to-the-1password-application-on-the-host/167032>.

---
*Architecture research for: harnessed (composable AI-coding-harness pod orchestrator)*
*Researched: 2026-06-14*
