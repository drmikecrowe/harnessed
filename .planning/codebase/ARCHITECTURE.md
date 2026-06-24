<!-- refreshed: 2026-06-24 -->
# Architecture

**Analysis Date:** 2026-06-24

## System Overview

```text
┌─────────────────────────────────────────────────────────────────┐
│               Host: `harnessed` bash bootstrap                   │
│               (`harnessed`, `lib/harnessed-common.sh`)           │
└──────┬──────────────┬────────────────┬───────────────────────────┘
       │              │                │
       ▼              ▼                ▼
┌──────────┐  ┌─────────────┐  ┌──────────────────┐
│  build   │  │  test       │  │  launch (isolated)│
│  path    │  │  path       │  │  path             │
│(emit+scan│  │(capability  │  │(pod: harness +    │
│+podman   │  │ test)       │  │ hatago + services)│
│ build)   │  │             │  │                   │
└────┬─────┘  └──────┬──────┘  └──────┬────────────┘
     │               │                │
     ▼               ▼                ▼
┌─────────────────────────────────────────────────────────────────┐
│      harnessed-tools Python package (`tools/harnessed/`)         │
│  schema.py → assemble.py → emit.py  |  scan.py  |  capability.py│
└─────────────────────────────────────────────────────────────────┘
     │ writes
     ▼
┌─────────────────────────────────────────────────────────────────┐
│   Committed Profile (`profiles/<stack>/`)                        │
│   .claude/{skills,commands}  hatago.config.json  .mcp.json      │
│   baked-servers.json  settings.json                              │
└─────────────────────────────────────────────────────────────────┘
     │ mounted into pod
     ▼
┌──────────────────────────┐   shared pod netns (localhost)
│  Harness Container       │ ◄──────────────────────────────┐
│  (harnessed-claude/omp/  │                                │
│   opencode/gemini/etc.)  │  http://localhost:3535/mcp     │
│  Reads .mcp.json →       │ ──────────────────────────────►│
│  connects to hatago      │                                │
└──────────────────────────┘                                │
                                        ┌───────────────────┴─┐
                                        │  hatago MCP Hub      │
                                        │  (harnessed-hatago)  │
                                        │  Spawns stdio child  │
                                        │  MCP servers         │
                                        └──────────────────────┘
                                                │
                                        via host.containers.internal
                                                │
                                        ┌───────▼──────────────┐
                                        │  Shared Services      │
                                        │  (e.g. harnessed-ping)│
                                        │  own image + volume   │
                                        └──────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| `harnessed` bootstrap | CLI entry point, arg parsing, dispatch to lib | `harnessed` |
| `harnessed-common.sh` | Image names, runtime detection (podman/docker), instance lifecycle | `lib/harnessed-common.sh` |
| `harnessed-isolated.sh` | Launch isolated stack pod (harness + hatago) | `lib/harnessed-isolated.sh` |
| `harnessed-mounts.sh` | §4a host-integration mounts (SSH, GPG, git, project dir) | `lib/harnessed-mounts.sh` |
| `harnessed-isolated-config.sh` | §4b auth seeding (ro credentials.json + token-free stub) | `lib/harnessed-isolated-config.sh` |
| `harnessed-services.sh` | Shared service lifecycle (svc up/down/list) | `lib/harnessed-services.sh` |
| `harnessed-manifest-mounts.sh` | Per-harness profile file mounts from manifests | `lib/harnessed-manifest-mounts.sh` |
| `harnessed-cli.sh` | First-class subcommands: list, stop, rm, new, install | `lib/harnessed-cli.sh` |
| `harnessed-secrets.sh` | Optional varlock + 1Password secrets layer | `lib/harnessed-secrets.sh` |
| `harnessed-runtime.sh` | Runtime abstraction (podman pods vs docker) | `lib/harnessed-runtime.sh` |
| `harnessed-rescan.sh` | Post-build nightly CVE rescan (SEC-04) | `lib/harnessed-rescan.sh` |
| `schema.py` | Parse/validate recipe.yaml + stack.yaml into typed dataclasses | `tools/harnessed/schema.py` |
| `assemble.py` | Orchestrate the emit-only assembly: read → fan → merge → emit | `tools/harnessed/assemble.py` |
| `emit.py` | Write profile artifacts (.mcp.json, hatago.config.json, etc.) | `tools/harnessed/emit.py` |
| `scan.py` | Supply-chain scan gate (osv-scanner + pip-audit + snyk) | `tools/harnessed/scan.py` |
| `capability.py` | Per-stack capability test: manifest oracle vs live pod introspection | `tools/harnessed/capability.py` |
| `report.py` | Rich terminal rendering of capability test results | `tools/harnessed/report.py` |
| `synclinks.py` | Fan skills/commands from recipes into profile tree (collision-detect) | `tools/harnessed/synclinks.py` |
| `cli.py` | harnessed-tools CLI entry point (assemble/test/scan subcommands) | `tools/harnessed/cli.py` |

## Pattern Overview

**Overall:** Emit-Only Assembler + Runtime Pod Composition

**Key Characteristics:**
- The assembler (`harnessed-tools`) reads manifests and writes profile artifacts; it NEVER invokes podman/docker
- Profiles are committed to `profiles/<stack>/` and are a pure function of their recipes/stack manifests (reproducible)
- At launch, the host bash bootstrap runs all `podman` commands directly (no Docker-out-of-Docker, no daemon socket)
- All harnesses share ONE Claude-canonical profile format (`.claude/` tree); non-claude harnesses adapt via image-baked config pointing at hatago
- hatago is the single MCP hub; harness `.mcp.json` points only at `http://localhost:3535/mcp` — never at individual servers directly

## Layers

**Manifest Layer (source of truth):**
- Purpose: Declare stack composition (harness + recipes) and recipe contents (MCP servers, skills)
- Location: `stacks/<name>/stack.yaml`, `recipes/<name>/recipe.yaml`
- Contains: YAML declarations — harness, recipe list, MCP servers, skills paths
- Depends on: Nothing (leaf input)
- Used by: schema.py, assemble.py

**Assembler Layer (build-time, emit-only):**
- Purpose: Transform manifests into committed profile artifacts
- Location: `tools/harnessed/` (Python package, run inside `harnessed-tools` container)
- Contains: schema.py, assemble.py, emit.py, synclinks.py, scan.py
- Depends on: Manifest layer
- Used by: `harnessed build <stack>` (host bash → `podman run harnessed-tools assemble`)

**Profile Layer (committed artifact):**
- Purpose: Committed output of assembly — the harness profile mounted at launch
- Location: `profiles/<stack>/`
- Contains: `.claude/skills/`, `.claude/commands/`, `.mcp.json`, `hatago.config.json`, `baked-servers.json`, `settings.json`
- Depends on: Assembler layer (generated from)
- Used by: `harnessed-isolated.sh` (mounted into the harness container at launch)

**Image Layer (Dockerfile lineage):**
- Purpose: Container images providing toolchains and harness binaries
- Location: `base/Dockerfile.harnessed-*`, `Dockerfile.hatago`, `services/<name>/Dockerfile`, `tools/Dockerfile`
- Contains: harnessed-base (lineage root) → harness-specific images (harnessed-claude, omp, opencode, gemini, antigravity, codex)
- Depends on: harnessed-base (all harness images inherit FROM it)
- Used by: `harnessed build` (host runs `podman build`)

**Runtime Layer (host bash, launch-time):**
- Purpose: Compose and launch the pod at runtime
- Location: `lib/harnessed-isolated.sh`, `lib/harnessed-common.sh`, `lib/harnessed-mounts.sh`, `lib/harnessed-isolated-config.sh`
- Contains: Mount construction, pod lifecycle, auth seeding, egress firewall
- Depends on: Profile layer (reads committed artifacts), Image layer (pulls built images)
- Used by: `harnessed <stack> [path]`

**Service Layer (independent sidecars):**
- Purpose: Long-lived shared services reachable across stack instances
- Location: `services/<name>/` (own Dockerfile + service.yaml + server)
- Contains: Network-native MCP servers (e.g. `services/ping/server.py`)
- Depends on: Nothing from other layers
- Used by: Recipes that declare `service: <name>` in their MCP server entries

## Data Flow

### Build Path: `harnessed build <stack>`

1. Parse `stacks/<stack>/stack.yaml` + each `recipes/<name>/recipe.yaml` → typed objects (`tools/harnessed/schema.py`)
2. Validate: no raw npm/npx, harness compat, no floating Dockerfile refs (`tools/harnessed/assemble.py`)
3. Run source scan: osv-scanner + pip-audit over recipe dirs (`tools/harnessed/scan.py:run_source_scan`)
4. Fan skills/commands from each recipe into profile tree, detect collisions (`tools/harnessed/synclinks.py`)
5. Merge all recipe MCP servers → `hatago.config.json` (`tools/harnessed/emit.py:write_hatago_config`)
6. Emit `.mcp.json` with single hatago endpoint, `settings.json`, `baked-servers.json` (`tools/harnessed/emit.py`)
7. Write derived `Dockerfile` for hatago image with baked servers (`tools/harnessed/emit.py:write_derived_dockerfile`)
8. Host runs `podman build` on emitted Dockerfile → `harnessed-hatago:<stack>` image
9. Run image scan on built image (`tools/harnessed/scan.py:run_image_scan`)
10. Committed profile lands in `profiles/<stack>/`

### Launch Path: `harnessed <stack> [path]`

1. Parse harness from `stacks/<stack>/stack.yaml` → select harness image (`lib/harnessed-isolated.sh`)
2. Lazy-build non-claude harness images if not present (`lib/harnessed-common.sh:ensure_*_image`)
3. Construct mount args: §4a host-integration mounts (`lib/harnessed-mounts.sh`)
4. Seed auth: ro credentials.json mount + generated `.claude.json` stub (`lib/harnessed-isolated-config.sh`)
5. Auto-start declared shared services (`lib/harnessed-services.sh:ensure_service_up`)
6. Create pod (`podman pod create`) with harness container + hatago container in shared netns
7. Apply egress firewall via `lib/egress-firewall.sh` (iptables inside harness container)
8. Start pod → hatago spawns its configured stdio children
9. Interactive: attach to harness (`claude --mcp-config`, `opencode`, etc.); headless: `sleep infinity` for introspection

### Test Path: `harnessed test <stack>`

1. Launch stack `--fresh` in headless mode (`HARNESSED_HEADLESS=true`)
2. Wait for hatago port 3535 to bind (readiness signal)
3. Introspect live pod: query `hatago://servers` resource for MCP servers; scan mounted profile dirs for skills/commands (`tools/harnessed/capability.py:introspect`)
4. Compare actual vs expected (derived from manifest via `schema.py:expected_capabilities`)
5. Build `CapabilityReport` → render with rich (`tools/harnessed/report.py`)
6. Teardown (`--fresh` removes pod)

**State Management:**
- Pod names follow `harnessed-<stack>-<projhash>` convention
- Service volumes (`<service>-data`) persist across `svc down`; `--purge` destroys them
- History dirs (`~/.claude/projects`, `~/.claude/file-history`, etc.) mounted rw from host for session continuity

## Key Abstractions

**Stack (`stack.yaml`):**
- Purpose: Declares ONE harness + list of recipes to compose
- Examples: `stacks/tracer-time/stack.yaml`, `stacks/ping-time/stack.yaml`
- Pattern: Minimal YAML; assembler parses forward (tolerant of unknown fields per D-14)

**Recipe (`recipe.yaml`):**
- Purpose: Declares MCP servers and skills/commands to add to a harness
- Examples: `recipes/time/recipe.yaml`, `recipes/ping/recipe.yaml`
- Pattern: `mcp.servers[]` (name, command, args, transport) + `skills[]` (path)

**Profile (committed artifact):**
- Purpose: Assembled, committed harness config — single source of truth at launch
- Examples: `profiles/tracer-time/`, `profiles/ping-time/`
- Pattern: Pure function of recipes/stack; regenerated from scratch on `harnessed build <stack>`

**Agent Manifest (`agents/<harness>/agent.yaml`):**
- Purpose: Declares harness image + Dockerfile for lazy build
- Examples: `agents/claude/agent.yaml`, `agents/omp/agent.yaml`
- Pattern: `type: agent`, `harness:`, `image:`, `dockerfile:`

**Service (`services/<name>/`):**
- Purpose: Long-lived shared sidecar with own image + volume + port
- Examples: `services/ping/`
- Pattern: `service.yaml` (name, image, volume, port, healthcheck) + `Dockerfile` + `server.py`

**Harness Manifest (`lib/manifests/<harness>.yaml`):**
- Purpose: Declares which profile files to mount and which history dirs to expose per harness
- Examples: `lib/manifests/claude.yaml`, `lib/manifests/omp.yaml`
- Pattern: `profile_files:` + `history_dirs:`

## Entry Points

**`harnessed` (bootstrap):**
- Location: `harnessed` (repo root)
- Triggers: User invocation (or shim at `~/.local/bin/<stack>`)
- Responsibilities: Parse all subcommands, source lib scripts, dispatch to correct path

**`harnessed-tools` (Python CLI):**
- Location: `tools/harnessed/cli.py` (entrypoint `harnessed.cli:main`)
- Triggers: Called inside `harnessed-tools` container by `harnessed build <stack>`
- Responsibilities: assemble, test (capability), scan subcommands

**`harnessed_isolated()` (launch function):**
- Location: `lib/harnessed-isolated.sh`
- Triggers: `harnessed <stack> [path]` dispatch
- Responsibilities: Build mount args, create pod, attach interactive or headless

## Architectural Constraints

- **Emit-only assembler:** `tools/harnessed/` NEVER calls podman/docker; all container operations are host-native bash
- **No Docker-out-of-Docker:** Every `-v` uses host absolute paths (host `HOME`/`PWD` passed as env); no daemon socket mounted into containers
- **FROM = lineage only:** `base/Dockerfile.harnessed-*` uses `FROM harnessed-base` for toolchain inheritance only; harness composition is runtime pod (never build-time `FROM` union)
- **One harness per stack:** Exactly one of claude/omp/opencode/gemini/antigravity/codex per stack manifest
- **Claude-canonical profile:** All harnesses read the same `.claude/` profile; non-claude harnesses adapt via image-baked config pointing at hatago
- **SSE deprecated:** MCP transport must be `streamable-http` or `stdio` (wrapped by hatago to HTTP); SSE is rejected
- **pnpm everywhere:** `npm`/`npx` are linted out by the assembler (BLD-03); `pnpm dlx` replaces `npx`
- **Global state:** `CONTAINER_RUNTIME`, `HARNESSED_DIR`, `MOUNT_ARGS` (array) are module-level bash globals shared across sourced lib scripts
- **Threading:** Single-threaded bash launcher; Python assembler is single-process (no async)

## Anti-Patterns

### Mounting `~/.claude.json` read-write

**What happens:** Bind-mounting the host's whole `~/.claude.json` into the container rw
**Why it's wrong:** Claude rewrites this file constantly; a shared rw mount races with the host process and corrupts state
**Do this instead:** Generate a minimal token-free stub in `lib/harnessed-isolated-config.sh`; mount only `~/.claude/.credentials.json` ro

### Using `FROM` to compose two harness systems

**What happens:** Trying to `FROM harnessed-claude` and `FROM harnessed-omp` together in one Dockerfile
**Why it's wrong:** `FROM` is linear inheritance; there is no "union two sibling images" operator
**Do this instead:** Compose at runtime in a podman pod — separate images, shared network namespace

### Calling podman from within the assembler

**What happens:** Any podman/docker call inside `tools/harnessed/`
**Why it's wrong:** The assembler runs inside `harnessed-tools` container; it has no daemon access and is emit-only by design
**Do this instead:** Emit artifacts only; the host bash bootstrap runs all `podman build`/`podman run` calls

### Using container-internal paths in `-v` flags

**What happens:** `-v /home/harnessed/something:/dest` where the source resolves inside the tool container
**Why it's wrong:** DooD bind sources resolve on the HOST daemon; the container's internal view points at nothing
**Do this instead:** Pass host `HOME`/`PWD` as env vars; use them in every `-v` source

## Error Handling

**Strategy:** Fail-fast with explicit error messages; structured exceptions in Python; `set -euo pipefail` in bash

**Patterns:**
- Python assembler raises typed exceptions: `SchemaError`, `RecipeLintError`, `CollisionError`, `ScanError`, `CapabilityError`
- Bash scripts use `print_error` + `exit 1` for user-visible failures
- Supply-chain scan: HIGH severity (CVSS >= 7.0) raises `ScanError` and aborts the build; lower findings are warnings
- Capability test: returns structured `CapabilityReport` with per-capability pass/fail; CI exit code driven by report

## Cross-Cutting Concerns

**Logging:** Bash: colored `print_info/success/warning/error` helpers in `lib/harnessed-common.sh`. Python: `rich.Console` for terminal rendering.
**Validation:** Assembler validates all manifests before any file emission (fail-fast order: lint → compat → pin → scan → emit)
**Authentication:** Credentials referenced from host, never baked. Claude: ro `.credentials.json` + token-free stub. opencode: ro `auth.json`. gemini: ro OAuth files. codex: ro `auth.json`. All via `lib/harnessed-isolated-config.sh`.
**Supply-chain:** pnpm supply-chain policy baked into base image at `lib/pnpm/config.yaml`; osv-scanner + pip-audit are always-on gate; snyk/socket are token-gated and warn-and-skip when no token.

---

*Architecture analysis: 2026-06-24*
