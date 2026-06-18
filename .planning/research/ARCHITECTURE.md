# Architecture Research

**Domain:** Containerized, composable AI-coding-harness launcher (rootless podman pod orchestrator + build-time assembler)
**Researched:** 2026-06-14
**Confidence:** MEDIUM — core architecture (§2–§9 of the design spec) is confirmed; repo layout / schemas / CLI (§10–§13) are proposed; external facts (podman pods, MCP transports, pnpm, scanners, 1Password) are web-verified HIGH.

## Standard Architecture

### System Overview

`harnessed` composes harness *stacks* as **podman pods** at runtime. The fat **`harnessed-tools` Python image** is a build-time **assembler**: it reads recipes/stacks and emits files only — a `Dockerfile` (+ build context), the committed `profiles/<stack>/`, `hatago.config.json`, and a generated host launcher — into a mounted build dir. The **host** then runs `podman build`. At runtime a generated, dependency-free **host bash launcher** (`~/.local/bin/<stack>`) runs the pod with the host podman CLI (`podman pod`/`run`/`exec -it`). The tools image never touches the container daemon; podman/docker stays the only host dependency.

```
┌──────────────────────────── HOST (user namespace, rootless) ─────────────────────────────┐
│                                                                                          │
│  BUILD TIME  (assemble → build)                                                           │
│  ┌──────────────────────────┐  emits files    ┌────────────────────────────────────────┐│
│  │  harnessed-tools         │ ──────────────▶ │ build dir: Dockerfile(s) + build context││
│  │  ASSEMBLER (build-time)  │  (mounts the     │ + profiles/<stack>/ + hatago.config.json││
│  │  rich/textual yq jq git  │   build dir)     │ + generated launcher script             ││
│  │  pnpm uv scanners varlock│                  └──────────────────┬─────────────────────┘│
│  └──────────────────────────┘                                     │                      │
│     (no daemon access — pure file emitter)      HOST: podman build │ + install            │
│                                                                    ▼                      │
│                                          baked images  +  ~/.local/bin/<stack> launcher   │
│                                                                                          │
│  RUN TIME                                                                                 │
│  $ harnessed <stack> [path]  ─▶  ~/.local/bin/<stack>  (generated HOST bash launcher)     │
│        │ host podman: pod create / run / exec -it   (native CLI, host paths + TTY)        │
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
| **`harnessed` bootstrap** | Dependency-free host entry on `PATH`: resolve the stack and exec the generated `~/.local/bin/<stack>` launcher; on first use of an isolated stack, drive assemble (run the tools image) → host `podman build` → install the launcher. Owns nothing else. | Single POSIX/bash script symlinked onto `PATH` (mirrors existing `install.sh`/`container.sh` install path). |
| **`harnessed-tools` image** | The build-time **assembler** (no daemon access): parse/validate YAML, vendor plugins, fan skills/commands (`sync-plugin-links`), merge `hatago.config.json`, generate `.claude.json` stub, write permissions config, run supply-chain scanners, and **emit** the build inputs — `Dockerfile`(s) + build context + `profiles/<stack>/` + a generated host launcher — into a mounted build dir. The **host** then runs `podman build`. | One Python image: `rich`/`textual` TUI + `yq`/`jq` + `git` + `pnpm` + `uv` + osv-scanner/pip-audit (+snyk/socket) + `varlock` + `op`. |
| **harness container** | Run the harness (`claude`/`omp`) against the mounted project, auth seeded, with the stack profile mounted into the harness config dir. The only container the user "is in". | `FROM harnessed-base` → `harnessed-claude` / `harnessed-omp` (mise/node/python base). |
| **hatago hub** | Aggregate the stack's MCP servers behind **one** Streamable-HTTP endpoint (default `:3535`); run light `pnpm dlx`/`uvx` **stdio** servers as its own children (stdio→HTTP) and **proxy** heavy network-native servers. Keeps `npx`/`uvx` out of the harness container. | `@himorishige/hatago-mcp-hub` baked into `Dockerfile.hatago` with light servers; HTTP serve mode. |
| **service sidecars** | Heavy/stateful systems (hindsight = postgres+MCP, openbrain). Each owns its image/container/**service-scoped volume**/lifecycle, independent of any instance; multiple instances attach concurrently over `harnessed-net`. | `services/<svc>/Dockerfile`, standalone & independently versioned; volume named for the *service* (`hindsight-data`). |
| **profile (committed → mounted)** | The assembled Claude-canonical file-extension tree (`skills/commands/agents/hooks/rules/.mcp.json/settings.json`) for one stack — editable, git-versioned, mounted read/write into the harness config dir. | Generated dir `profiles/<stack>/.claude/…` + `hatago.config.json`; produced by the assembler, committed. |
| **baked images** | Reproducible, pinned MCP-server dependencies (`pnpm dlx`/`uvx`/python deps) and base lineage — kept out of the profile so the host stays clean. | Build-time Docker images: `harnessed-base`/`-claude`/`-omp`, `hatago`, per-service. |

## Recommended Project Structure

```
code-container/
├── harnessed                       # thin bash bootstrap → assemble (tools img) + host podman build + run generated launcher (§15)
├── container                       # back-compat alias → `harnessed transparent` (§14: keep)
├── .env.schema.example             # varlock template → ~/.config/harnessed/.env.schema (§16)
├── tools/                          # the assembler — harnessed-tools image (emits Dockerfile + context + profile + launcher)
│   ├── Dockerfile                  # python + rich/textual + yq/jq + git + pnpm/uv + scanners + varlock + op
│   ├── pyproject.toml
│   └── harnessed/                  # cli, assemble, vendor, sync-links, validate, emit Dockerfile + launcher
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

- **`tools/` (Python assembler) vs `lib/` (runtime bash):** hard split between *build-time assembly logic* (runs inside `harnessed-tools`, emits files only — never touches the daemon) and *per-instance runtime glue* (mounted into the launched harness container). Keeping them apart stops the assembler from leaking host-runtime assumptions and keeps the only host dependency podman/docker (§15).
- **`recipes/` (inputs) → `stacks/` (composition) → `profiles/` (output):** a clean pipeline boundary. Recipes are reusable single-integration definitions; stacks pick a harness + a set of recipes; profiles are the **generated** artifact. Recipes/stacks are hand-authored and reviewed; profiles are regenerable, so a diff in `profiles/` is auditable evidence of what the assembler produced.
- **`base/` separate from `services/`:** `base/` holds *lineage* images consumed by every stack (harness + hatago); `services/` holds *independently versioned, standalone* sidecars reusable across stacks. Encodes the §6 rule — `FROM` is for base lineage, not for unioning systems.
- **`profiles/` committed and mounted (not baked):** the file-extension layer must be editable and versioned (satisfies "commands/skills/agents/hooks proxied to a git-controlled folder"); MCP deps are baked into images instead so the host stays pinned/clean. This split is the central structural decision.
- **`transparent/stack.yaml` lives beside isolated stacks:** transparent is *just another stack* (one engine, two modes), so it belongs in `stacks/`, not in a special-cased code path.

## Architectural Patterns

### Pattern 1: Runtime pod composition (not build-time `FROM` union)

**What:** Two sibling systems (a harness + an MCP hub, plus shared sidecars) are combined by placing them in a **podman pod** sharing one network namespace, assembled at `podman run` time — never by an image build step.
**When to use:** Whenever you must combine independently-built, independently-versioned systems that each own runtime state. Here: harness ⊕ hatago ⊕ sidecars.
**Trade-offs:** (+) Each component stays independently built, versioned, and scaled; sidecars outlive instances and are shared concurrently. (+) Containers in a pod reach each other on `localhost:<port>` (shared netns), so the harness's `.mcp.json` points at `localhost:3535` with no DNS. (−) Composition logic lives in the generated host launcher (run at `podman run` time) instead of a declarative Dockerfile; the pod must be (re)created when bind mounts change.

**Why `FROM` cannot do this:** `FROM` is *linear inheritance*; multiple `FROM`s make a *multi-stage* build whose **last** stage is the image, with `COPY --from=…` pulling artifacts forward. There is **no "union two images" operator.** You cannot merge two running systems (each with its own processes/state) into one image — only copy files between build stages. Hence runtime, not build time.

```bash
# Compose at runtime — pod gives shared netns + localhost addressing
podman pod create --name "harnessed-${stack}-${projhash}" --network harnessed-net
podman run -d --pod "harnessed-${stack}-${projhash}" --name hatago      harnessed-hatago
podman run -d --pod "harnessed-${stack}-${projhash}" --name "${harness}" \
  -v "${PWD}:/home/harnessed/${relpath}" \
  -v "${HOME}/code-container/profiles/${stack}/.claude:/home/harnessed/.claude:rw" \
  "harnessed-${harness}"
# harness reaches hatago at http://localhost:3535 (same netns); sidecars by name on harnessed-net
```

### Pattern 2: Split assembly output — committed→mounted profile + baked→images

**What:** The assembler emits to **two distinct sinks**: the Claude-canonical file tree → a git-committed `profiles/<stack>/` dir **mounted** into the harness; MCP servers and their `pnpm dlx`/`uvx`/python deps → **baked** into images.
**When to use:** When some artifacts must stay human-editable and versioned (skills/commands/hooks) while others must stay pinned, reproducible, and off the host (dependency trees).
**Trade-offs:** (+) Editable, diffable extensions without rebuilding an image; pinned, clean dependency closure without polluting `~`. (+) "Nothing assembled at container start" → satisfies "not dynamic." (−) Two artifact lifecycles to keep in sync; a profile edit that needs a new MCP dep still requires an image rebuild.

### Pattern 3: Assembler emits a Dockerfile; the host builds it

**What:** The `harnessed-tools` container is a pure **file emitter** — it reads recipes/stacks and writes a `Dockerfile` (+ build context), `profiles/<stack>/`, `hatago.config.json`, and a generated launcher into a mounted build dir. It never talks to the container daemon. The **host** then runs `podman build` on the emitted Dockerfile(s).
**When to use:** When generating build inputs needs a rich toolchain (Python/git/pnpm/scanners) but the actual `build` must run on the host engine without a host language runtime.
**Trade-offs:** (+) Only host dependency is podman/docker; no Python/node/uv version roulette on the host, and no daemon socket mounted into any container (the assembler is "a tool in a container", a pure file emitter). (+) The emitted Dockerfile + context is an auditable, reproducible artifact the host builds verbatim. (−) Two steps (emit, then build) instead of one; the emitted Dockerfile and launcher are regenerated when recipes change.

### Pattern 4: Generated host-bash launcher runs the pod natively

**What:** `harnessed install <stack>` writes a self-contained **host bash** launcher to `~/.local/bin/<stack>`. At runtime it computes the §4a conditional mounts on the host and runs the pod with the host podman CLI (`podman pod create`/`podman run`/`exec -it`). `harnessed <stack>` and `container` delegate to it.
**When to use:** When the orchestration must run with the user's own host paths, TTY, and podman — without a controller container in the middle.
**Trade-offs:** (+) `$HOME`/`$PWD`/project paths are **host-native by construction**, so bind mounts are correct with no path translation. (+) The interactive `podman exec -it` attach allocates a clean TTY because it is host bash by definition (no tunneling). (+) The launcher is dependency-free, so the only host requirement stays podman/docker. (−) Launch logic lives in generated bash rather than the Python assembler, so it is regenerated (not hand-edited) when the mount/runtime contract changes.

### Pattern 5: Claude-canonical format + omp bridge adapter

**What:** Claude Code format is the **single source of truth** for skills/commands/hooks/plugins. `claude` mounts it natively; `omp` adapts *out* of it at runtime via `claude-hooks-bridge` + `lib-pi-adapter.sh` (no re-authoring). Exactly **one harness per stack**.
**When to use:** Multi-harness support where re-authoring per harness would be the real cost.
**Trade-offs:** (+) One authoring format, no drift, no duplicate maintenance; new harnesses are an adapter, not a fork of all content. (−) Non-Claude harnesses inherit a translation layer (the pi-adapter normalizes omp/GSD hook payloads → Claude shape); a Claude-only construct with no omp analogue can't be expressed.

### Pattern 6: One engine, two config modes on a single mount axis

**What:** `transparent` and `isolated` share the *same* base image, host-integration mounts (§4a), project mount, and auth. They differ on **one axis only** — where the config layer comes from: host `~/.claude` bind-mounted live (transparent) vs auth-seeded + assembled profile mounted (isolated).
**When to use:** When two seemingly different products are actually the same engine with one swapped input — collapse them rather than maintaining parallel code paths.
**Trade-offs:** (+) Minimal surface; `transparent` == the old `container` for free; isolated adds the pod/hatago/sidecar machinery only when `config: isolated`. (−) The shared host-integration layer means isolated instances are *authenticated and signed* (SSH/GPG/1Password), not hermetic — a deliberate choice (credentials are not the experiment surface), but worth gating if a truly empty environment is ever needed (§14).

**Mount-axis detail (the `.claude.json` safety fix):** `~/.claude.json` is a single whole-file blob Claude rewrites constantly (~450 KB of state, not auth). It is **never rw-bind-mounted** in either mode — transparent seeds a writable per-instance copy (copy-on-start) or relocates via `CLAUDE_CONFIG_DIR`; isolated **generates** a minimal stub (candidate fields `oauthAccount`/`userID`/`hasCompletedOnboarding`, §14). Only the real credential `~/.claude/.credentials.json` is mounted read-only.

## Data Flow

### Assemble pipeline (`harnessed build <stack>`)

```
recipes/<r>/recipe.yaml  ─┐
stacks/<stack>/stack.yaml ┴─▶ podman run harnessed-tools   (assembler; mounts build dir, EMITS files only)
                                 │ vendor-plugin   → resolve marketplace/url/git plugins, install uv/pnpm deps
                                 │ sync-plugin-links → fan skills/commands → harness-native paths (FAIL-FAST on collision)
                                 │ wire hooks      → <Event>.d handlers + pi-adapter
                                 │ merge MCP       → hatago.config.json
                                 │ emit build      → Dockerfile(s) + build context + generated launcher
                                 │ SUPPLY-CHAIN GATE → osv-scanner + pip-audit (always);
                                 │                     snyk + Socket.dev (token present, else warn-skip);
                                 │                     FAIL on high-severity  ◀── gate before any commit/build
                                 ▼
            ┌──────────────── split output ────────────────┐
            ▼                                               ▼
   profiles/<stack>/  (committed, mounted)        Dockerfile(s) + context  ─▶  HOST: podman build
   .claude/{skills,…} + hatago.config.json        → baked images (pinned, host-clean):
   + generated launcher → ~/.local/bin/<stack>       harnessed-base/-claude/-omp, hatago, services/*
```

### Launch flow (`harnessed <stack> [path]`)

```
harnessed <stack> [path]
  └▶ ~/.local/bin/<stack>   (generated HOST bash launcher — plain host podman, no socket)
       ├▶ compute §4a conditional host-integration mounts (on the host)
       ├▶ ensure pod images present  (HOST podman build if missing)
       ├▶ ensure shared services up on harnessed-net (start if absent; svc-scoped volume)
       ├▶ podman pod create harnessed-<stack>-<projhash>  (--network harnessed-net)
       ├▶ podman run hatago (HTTP :3535) into the pod
       └▶ podman run harness into the pod
            -v $PWD:/home/harnessed/<relpath>            (host-native path by construction)
            -v profiles/<stack>/.claude  -v ~/.claude/.credentials.json:ro
  └▶ podman exec -it harnessed-<stack>-<projhash> <harness>   (host TTY)
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
3. **Secret resolution (opt-in):** if a `.env.schema` exists, `resolve_secret_env` runs `varlock load --format env` **on the host** (the 1Password desktop app authorizes the calling terminal) and spreads the resolved dotenv into the tool container / instance / sidecar / build scan as a temp `--env-file` — **env only**, never an image layer or committed file. The in-container fallback needs `OP_SERVICE_ACCOUNT_TOKEN` (§16).

## Build-Order & Scaling Considerations

The relevant "scale" axis is **number of stacks/instances/shared services and recipe count**, plus the **build order** of harnessed itself. There are no user-count tiers; concurrency is bounded by your machine and the shared-service model.

| Scale axis | Architecture adjustments |
|------------|--------------------------|
| 1 stack, 1 instance, 0 services | Pod = harness + hatago only; or transparent (harness only). Trivial; this is the first vertical slice. |
| Several stacks, concurrent instances, shared services | Services run **once** per service on `harnessed-net`, owned by the service not any instance; `claude+hindsight` and `omp+hindsight` share **one** `hindsight-data` volume. Instances start a service if absent (`harnessed svc up/down`). Pod identity includes the project hash so the same stack runs across projects without recreate. |
| Many recipes / large dependency closure | Supply-chain gate cost grows; cache vendored trees and baked layers; `minimumReleaseAge` quarantine window and `onlyBuiltDependencies`/`allowBuilds` allowlist need tuning (too tight blocks legit native builds, too loose weakens the guard). Nightly re-scan (systemd-timer pattern) catches CVEs disclosed after build. |

### Suggested build order — vertical slices (tracer bullets, §18)

1. **Slice 1 — minimal isolated stack green end-to-end:** one harness + one MCP server + one skill → assemble → run `--fresh` headless → capability test asserts MCP connected + skill present. This exercises the bootstrap, the assembler + host `podman build`, the generated host launcher's pod create, hatago, profile mount, and the test oracle in one thin path.
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

### Anti-Pattern 2: Bind-mounting `~/.claude.json` read/write
**What people do:** Mount the whole `~/.claude.json` into the container like the rest of `~/.claude`.
**Why it's wrong:** It's a constantly-rewritten whole-file blob; a shared rw mount races with host Claude (lost writes/corruption) and merges container state back into the host. Differing project paths only spare the path-keyed `projects` subtree, not the whole-file rewrite or top-level fields.
**Do this instead:** Mount only `~/.claude/.credentials.json:ro`; copy-on-start a per-instance copy or relocate via `CLAUDE_CONFIG_DIR` (transparent), or generate a minimal stub (isolated).

### Anti-Pattern 3: Running `npx`/`uvx` stdio servers inside the harness container
**What people do:** Put MCP stdio servers directly in the harness container.
**Why it's wrong:** Drags npm/npx/uvx and their dependency trees into the harness image, defeating the clean/pinned host goal and the pnpm-everywhere supply-chain policy.
**Do this instead:** Bake light stdio servers as hatago **children** (stdio→HTTP) and proxy heavy ones; the harness sees one HTTP endpoint (Pattern 1, MCP flow).

### Anti-Pattern 4: Baking or committing credentials
**What people do:** Add Claude auth / scanner tokens / 1Password secrets to an image layer or repo file for convenience.
**Why it's wrong:** Secrets in image layers or git are exfiltration-prone and non-rotatable.
**Do this instead:** Reference host creds, inject as **env only** at launch (varlock/`op` resolve at runtime). Missing credentialed scanner → warn-and-skip, never an interactive prompt (keeps build non-interactive/reproducible).

### Anti-Pattern 5: Dynamic/runtime recipe assembly & assembler unit tests
**What people do:** Resolve recipes at container start, and unit-test the vendor/sync/merge internals.
**Why it's wrong:** Runtime assembly breaks reproducibility ("not dynamic"); internal unit tests couple to implementation and break on refactor.
**Do this instead:** Assemble ahead of time into committed artifacts; verify behavior transitively through the running instance against the manifest oracle (§18).

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| **Host podman CLI** | The generated host launcher invokes the **host** `podman` CLI directly (`pod create`/`run`/`exec -it`); the assembler emits a `Dockerfile` + build context that the host builds with `podman build`. No daemon socket is mounted into any container. | Containers in a pod share netns → `localhost:port`; cross-pod via `harnessed-net` by name. |
| **1Password (secrets)** | Optional via varlock: `.env.schema` with `op(op://Vault/Item/field)` refs, resolved **on the host** via `resolve_secret_env` (`lib/harnessed-secrets.sh`) → temp `--env-file` spread into isolated/transparent/services/build. The `agent.sock` mount is the SSH agent, not the op app-auth transport. | App-auth runs on the host (the desktop app authorizes the calling terminal); an in-container `op` cannot be authorized, so the headless path needs `OP_SERVICE_ACCOUNT_TOKEN` (bearer auth). Inert unless a schema exists (§16). |
| **Host auth / signing** | Shared host-integration layer (every stack): 1Password SSH agent (`SSH_AUTH_SOCK`), GPG agent + `~/.gnupg:ro`, YubiKey `--device`, `~/.ssh:ro`, git config:ro, `/etc/machine-id:ro`, egress firewall (`--cap-add NET_ADMIN`). | Ported verbatim from `container.sh start_new_container`; credentials are not the experiment surface, so they belong in isolated too. |
| **Claude auth** | Mount `~/.claude/.credentials.json:ro` (OAuth); generate `.claude.json` stub (isolated). | Never the whole `~/.claude.json`; never baked. |
| **Supply-chain scanners** | osv-scanner + pip-audit always (credential-free, public DBs); snyk + Socket.dev when a token is present (env / host config / varlock ref), else warn-skip. | `harnessed build` fails on high-severity. `harnessed auth snyk|socket` sets a token once via the CLI's own `auth` inside the tools container. |
| **Container registries** | `pnpm`/`uv` pull MCP deps at **build** time under managed supply-chain config; images optionally published to skip first-run build. | pnpm everywhere (no npm/npx); `minimumReleaseAge` quarantine + lifecycle-script default-deny + content-addressed store. |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| **bootstrap ↔ assembler** | `podman run harnessed-tools` to emit build inputs (Dockerfile/context/profile/launcher); the host then runs `podman build`. | Assembler is a pure file emitter (no daemon access); the split keeps host deps = podman only. |
| **launcher ↔ host podman** | The generated `~/.local/bin/<stack>` calls the host `podman` CLI natively to build (if missing), create the pod, run containers, ensure services, and attach (`exec -it`). | Runs as the user with host paths/TTY by construction; full control of the user's containers (acceptable for a personal dev tool). |
| **harness ↔ hatago** | MCP over **Streamable HTTP** at `localhost:3535` (shared pod netns). | Harness `.mcp.json` is the only client config; hatago is the single aggregation point. |
| **hatago ↔ child/proxied servers** | Child stdio servers (stdio→HTTP, baked) + proxied network-native servers over `harnessed-net`. | Per-server transport varies; some speak Streamable HTTP natively, others need hatago wrapping (§14). |
| **instance ↔ shared service** | Over `harnessed-net` by service name; service is service-scoped, harness-independent, concurrent. | `hindsight-data` volume shared by `claude+hindsight` and `omp+hindsight`; service outlives instances (`harnessed svc up/down`). |
| **assembler ↔ profile/images** | Split output: committed→mounted profile (files) + emitted Dockerfile(s) the **host** bakes into images. | The only place recipes merge; nothing assembled at container start. |

## Sources

- harnessed design spec — `docs/harnessed-design.md` (§2–§18); project context — `.planning/PROJECT.md`.
- Podman pods & rootless networking — containers in a pod share the network namespace and communicate via `localhost:port`; cross-pod by name on a shared network: <https://github.com/containers/podman/blob/main/docs/tutorials/basic_networking.md>, <https://www.redhat.com/en/blog/container-networking-podman>, <https://docs.podman.io/en/stable/markdown/podman.1.html>.
- MCP transports (two standard: stdio + Streamable HTTP; SSE back-compat only) — spec 2025-03-26, reaffirmed 2025-11-25: <https://modelcontextprotocol.io/specification/2025-03-26/basic/transports>, <https://blog.modelcontextprotocol.io/posts/2025-12-19-mcp-transport-future/>.
- Hatago MCP Hub (lightweight multi-MCP aggregator; STDIO/HTTP/SSE/WS; proxy + child stdio; default HTTP `:3535`): <https://github.com/himorishige/hatago-mcp-hub>, <https://www.npmjs.com/package/@himorishige/hatago-mcp-hub>, <https://hatago.dev/en/>, <https://dev.to/himorishige/getting-started-with-multi-mcp-using-hatago-mcp-hub-one-config-to-connect-them-all-2bjp>.
- pnpm supply-chain config — `minimumReleaseAge` defaults to 1440 min (1 day) in pnpm v11; lifecycle-script default-deny via `onlyBuiltDependencies`/new `allowBuilds`; content-addressed store integrity: <https://pnpm.io/supply-chain-security>, <https://pnpm.io/settings>, <https://socket.dev/blog/pnpm-11-adds-new-supply-chain-protection-defaults>.
- osv-scanner (credential-free, container/lockfile scanning, CI fail-on-severity) & pip-audit: <https://github.com/google/osv-scanner>, <https://google.github.io/osv-scanner/>, <https://appsecsanta.com/osv-scanner>.
- 1Password CLI in containers — service-account token (`OP_SERVICE_ACCOUNT_TOKEN`) is the cleaner headless story vs desktop app-auth socket: <https://developer.1password.com/docs/service-accounts/use-with-1password-cli/>, <https://www.1password.community/discussions/developers/link-the-1password-cli-in-a-container-to-the-1password-application-on-the-host/167032>.

---
*Architecture research for: harnessed (composable AI-coding-harness pod orchestrator)*
*Researched: 2026-06-14*
