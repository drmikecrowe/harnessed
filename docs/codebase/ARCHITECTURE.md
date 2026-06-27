<!-- refreshed: 2026-06-27 -->
# Architecture

**Analysis Date:** 2026-06-27

## System Overview

```text
┌─────────────────────────────────────────────────────────────────┐
│                   HOST: harnessed CLI                           │
│  `harnessed` (Typer)           `harnessed-tools` (argparse)    │
│  src/harnessed/launcher.py     src/harnessed/cli.py            │
└────────────────────────────────────┬────────────────────────────┘
                                     │
                    ┌────────────────▼──────────────┐
                    │    Assembly Pipeline           │
                    │  assemble.py → emit.py         │
                    │  synclinks.py                  │
                    └────────────────┬──────────────┘
                                     │
       ┌─────────────────────────────▼────────────────────────────┐
       │                Schema / Model Layer                       │
       │         src/harnessed/schema.py  src/harnessed/paths.py  │
       └─────────────────────────────┬────────────────────────────┘
                                     │
       ┌─────────────────────────────▼────────────────────────────┐
       │                   Catalog (source of truth)              │
       │  catalog/agents/   catalog/recipes/   catalog/stacks/    │
       │  catalog/services/ catalog/base/                         │
       │  ~/.config/harnessed/catalog/  (user overlay, wins)      │
       └─────────────────────────────┬────────────────────────────┘
                                     │ podman build / pod create
       ┌─────────────────────────────▼────────────────────────────┐
       │               PODMAN POD (runtime)                       │
       │   harness container + hatago MCP hub + service sidecars  │
       └──────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| Launcher | Host-facing Typer CLI: build, launch, stop, rm, prune, test, new, svc | `src/harnessed/launcher.py` |
| CLI / Tools | argparse CLI for `harnessed-tools`: assemble, scan, scan-image, test | `src/harnessed/cli.py` |
| Assembler | Orchestrates catalog→profile pipeline; delegates to emit + synclinks | `src/harnessed/assemble.py` |
| Emitter | Writes profile artifacts: .mcp.json, settings.json, hatago.config.json, Dockerfile | `src/harnessed/emit.py` |
| LinkSyncer | Fans recipe skills/commands into profile .claude/ tree; detects name collisions | `src/harnessed/synclinks.py` |
| Schema | Typed dataclasses + ruamel.yaml parsing for agent/recipe/service/stack YAMLs | `src/harnessed/schema.py` |
| Paths | Single source of truth for all host/container path resolution and catalog roots | `src/harnessed/paths.py` |
| Scanner | Supply-chain scans (osv-scanner + pip-audit + snyk); CVSS gating logic | `src/harnessed/scan.py` |
| Capability | Manifest oracle vs live-pod introspection; structured CapabilityReport | `src/harnessed/capability.py` |
| Report | Rich terminal render of CapabilityReport; also emits JSON for CI | `src/harnessed/report.py` |

## Pattern Overview

**Overall:** Emit-only assembly pipeline feeding a host-native podman orchestrator.

**Key Characteristics:**
- Assembly is strictly **emit-only** — `assemble.py`, `emit.py`, `schema.py`, and `synclinks.py` never invoke podman. Only `launcher.py` drives the container runtime.
- Profiles are a **pure function** of the catalog: every `harnessed build` regenerates from scratch (`emit.reset_profile` wipes and recreates).
- **Two CLI binaries**: `harnessed` (user-facing, Typer) and `harnessed-tools` (build-time assembler, argparse). The launcher calls `harnessed-tools assemble` in-process via `assemble.assemble()`.
- **Catalog precedence**: user overlay `~/.config/harnessed/catalog` wins over repo `catalog/` on any name clash (see `paths.catalog_roots()`).
- **One structured result drives two audiences**: `CapabilityReport` serves both the rich terminal report and the CI exit code (design §18 / D-11). Same pattern in `ScanResult`.

## Layers

**CLI Layer:**
- Purpose: Entry points and user interaction
- Location: `src/harnessed/launcher.py`, `src/harnessed/cli.py`
- Contains: Typer commands (`launch`, `build`, `stop`, `rm`, `prune`, `test`, `new`, `svc`), argparse subcommands (`assemble`, `test`, `scan`, `scan-image`, `scan-image-online`, `scan-snyk-container`)
- Depends on: All other layers
- Used by: End user (host shell), `harnessed build` pipeline

**Assembly Layer:**
- Purpose: Catalog → profile transformation (emit-only, no podman)
- Location: `src/harnessed/assemble.py`, `src/harnessed/emit.py`, `src/harnessed/synclinks.py`
- Contains: `assemble()` orchestrator, file writers, skill/command fan-out with collision detection
- Depends on: Schema layer, Paths layer
- Used by: CLI layer (`launcher.build`, `cli._run_assemble`)

**Schema / Model Layer:**
- Purpose: Typed in-memory representation of all catalog manifests
- Location: `src/harnessed/schema.py`
- Contains: Dataclasses (`McpServer`, `Recipe`, `Stack`, `FileExt`, `Expect`, `Service`), YAML loaders, lint validators (`validate_no_raw_npm`, `validate_pin`)
- Depends on: Paths layer (catalog resolution via `paths.find_in_catalog`)
- Used by: Assembly layer, CLI layer, Capability layer

**Paths Layer:**
- Purpose: Single source of truth for all path computations
- Location: `src/harnessed/paths.py`
- Contains: XDG path helpers, catalog roots, profile dir, instance naming (`instance_name`), container path mirrors
- Depends on: Nothing (pure stdlib)
- Used by: All other layers

**Quality / Testing Layer:**
- Purpose: Supply-chain scanning and live capability verification
- Location: `src/harnessed/scan.py`, `src/harnessed/capability.py`, `src/harnessed/report.py`
- Contains: CVSS scoring, osv-scanner/pip-audit/snyk wrappers, headless pod introspection, rich report rendering
- Depends on: Schema layer, Paths layer
- Used by: CLI layer (`cli._run_scan`, `cli._run_test`, `launcher.test_stack`)

## Data Flow

### Build Path (`harnessed build <stack>`)

1. `launcher.build()` → calls `assemble.assemble(root, stack_name, build_dir)` (`src/harnessed/launcher.py:759`)
2. `assemble()` loads stack + recipes via `schema.load_stack_with_recipes()` (`src/harnessed/assemble.py`)
3. Validators run: `validate_no_raw_npm`, `validate_pin` on each recipe Dockerfile
4. `_merge_servers()` collects all MCP servers, detects name collisions
5. `_resolve_service_servers()` maps `service:` references → `host.containers.internal:<port>` URLs
6. `emit.*` writes profile artifacts to `profiles/<stack>/` (`src/harnessed/emit.py`)
7. `LinkSyncer.fan()` copies recipe skill/command dirs into profile `.claude/` tree (`src/harnessed/synclinks.py`)
8. Launcher runs `podman build` for the hatago image, then the derived harness image
9. `_merge_baked_extensions()` extracts baked skills/commands from image back into profile

### Launch Path (`harnessed <stack> <path>`)

1. `launcher.launch()` validates stack built, loads `stack.yaml` (`src/harnessed/launcher.py:576`)
2. `_ensure_harness_image()` lazy-builds agent image if missing
3. `_ensure_services()` idempotently starts any service sidecars (host-published)
4. `podman pod create` with shared network namespace
5. `podman run` hatago container (with `hatago.config.json` mount)
6. `podman run` harness container (with profile mounts, credential mounts, project mount)
7. `_wait_hatago()` polls port 3535 for readiness
8. `_attach()` exec-attaches the harness binary (e.g., `claude --mcp-config ... --strict-mcp-config`)

### Capability Test Path (`harnessed test <stack>`)

1. `capability.run_capability_test()` derives expected capabilities from manifest oracle (`schema.expected_capabilities`)
2. Launches stack `--fresh` headless via `HARNESSED_HEADLESS=true`
3. Introspects live pod: `hatago://servers` resource for MCP, filesystem for skills/commands
4. `build_report()` diffs actual vs expected into `CapabilityReport`
5. `report.emit()` renders rich table AND drives CI exit code (same result, two consumers)

**State Management:**
- Profiles are stateless artifacts regenerated from catalog on every build
- Pod instances are named `harnessed-<stack>-<sha1[:8] of project_path>` for stable re-attach
- Per-stack state lives in `$XDG_DATA_HOME/harnessed/profiles/<stack>/`
- omp is a deliberate exception: shares host `~/.omp/agent` read-write (not isolated)

## Key Abstractions

**Recipe (`schema.Recipe`):**
- Purpose: A composable capability bundle — MCP servers + skills + commands + optional Dockerfile
- Examples: `catalog/recipes/time/`, `catalog/recipes/ping/`, `catalog/recipes/gstack/`
- Pattern: Harness-independent; branches on `${HARNESS}` build arg inside recipe Dockerfile

**Stack (`schema.Stack`):**
- Purpose: One agent + a set of recipes, named `<agent>_<recipe>[_<recipe>...]`
- Examples: `catalog/stacks/claude_time/stack.yaml`, `catalog/stacks/claude_gstack_ping_time_greet/stack.yaml`
- Pattern: Read-only manifest; the assembled profile is what the pod consumes

**Profile:**
- Purpose: Assembled output — the committed artifact the pod mounts
- Location: `$XDG_DATA_HOME/harnessed/profiles/<stack>/` (not repo; generated)
- Pattern: Pure function of catalog; wiped and regenerated each build

**Catalog (`paths.catalog_roots()`):**
- Purpose: Two-tier catalog lookup — user overlay wins over repo catalog
- Examples: User: `~/.config/harnessed/catalog/recipes/`, Repo: `catalog/recipes/`
- Pattern: First-existing-wins across roots; `paths.find_in_catalog(kind, name)`

## Entry Points

**`harnessed` (user-facing):**
- Location: `src/harnessed/launcher.py` (Typer `app`)
- Triggers: User shell; registered as `[project.scripts]` in `pyproject.toml`
- Responsibilities: All interactive commands; drives podman subprocess

**`harnessed-tools` (build-time assembler):**
- Location: `src/harnessed/cli.py` (argparse `main()`)
- Triggers: `launcher.build()` in-process OR standalone in CI
- Responsibilities: `assemble`, `test`, `scan`, `scan-image`, `scan-snyk-container`

## Architectural Constraints

- **No container in container:** `harnessed` runs on the host and drives rootless podman directly — no tool container, no daemon socket DooD
- **Emit-only boundary:** `assemble.py`, `emit.py`, `schema.py`, `synclinks.py` must never invoke subprocess/podman; only `launcher.py` and `capability.py` may
- **Single harness per stack:** Exactly one of `claude|omp|opencode|gemini|antigravity|codex` per stack; one pod per `(stack, project_path)` pair
- **pnpm everywhere:** No npm/npx; recipe lint (`validate_no_raw_npm`) enforces this at build time
- **SSE deprecated:** MCP transport must be Streamable-HTTP (`type: http`); hatago wraps stdio servers
- **Credentials never baked:** Claude credentials mounted read-only; never in image layers or repo files
- **Global state:** `_out` and `_err` console instances in `launcher.py` are module-level singletons; HATAGO_PORT = 3535 constant shared across `emit.py`, `capability.py`, `paths.py`
- **omp auth exception:** omp bind-mounts `~/.omp/agent` read-write (shared host state); all other harnesses are isolated

## Anti-Patterns

### Re-declaring `FROM` or `ARG HARNESS` in recipe Dockerfiles

**What happens:** A recipe Dockerfile contains its own `FROM <base>` or bare `ARG HARNESS` line.
**Why it's wrong:** The assembler concatenates recipe Dockerfile bodies; a stray `FROM` resets the build stage, discarding all prior layers.
**Do this instead:** Recipe Dockerfiles contain only body instructions. The assembler emits `FROM harnessed-${HARNESS}:latest` and re-declares `ARG HARNESS` automatically. See `emit.write_derived_dockerfile()` in `src/harnessed/emit.py`.

### Hardcoding host paths in `-v` mount flags

**What happens:** A path computed inside the tool container is used as a `-v` source.
**Why it's wrong:** DooD bind sources resolve on the **host** daemon; the container's internal path points at nothing.
**Do this instead:** Pass host `HOME`/`PWD` as env; every `-v` uses host-absolute paths via `paths.*` helpers. See `launcher._build_mount_args()` in `src/harnessed/launcher.py`.

### Reading scanner exit code instead of parsing JSON output

**What happens:** Code treats osv-scanner exit 1 as "HIGH vulnerability found."
**Why it's wrong:** osv-scanner exits 1 on ANY finding with no severity flag; low/medium findings would abort the build.
**Do this instead:** Parse `--format json` output and apply `_cvss3_base()` gating at CVSS >= 7.0. See `src/harnessed/scan.py`.

## Error Handling

**Strategy:** Structured exceptions propagate through layers; CLI handlers catch, render with rich, return integer exit codes.

**Patterns:**
- `SchemaError` — malformed YAML or missing required fields (`schema.py`)
- `RecipeLintError` — raw npm/npx usage (`schema.py`)
- `PinValidationError` — floating Dockerfile refs like `:latest` (`schema.py`)
- `CollisionError` — duplicate skill/command/MCP-server name across recipes (`synclinks.py`)
- `ScanError` — CVSS >= HIGH finding in supply-chain scan (`scan.py`)
- `CapabilityError` — capability test cannot run (launch failed) (`capability.py`)
- All are caught at the CLI dispatch layer and rendered via `rich.Console(stderr=True)`

## Cross-Cutting Concerns

**Logging:** `rich.Console()` for stdout; `rich.Console(stderr=True)` for errors. No structured logging framework — `[blue][INFO][/blue]` prefix convention in launcher.
**Validation:** Two-phase: schema validation at parse time (ruamel.yaml + dataclasses) and lint validation at assemble time (`validate_no_raw_npm`, `validate_pin`).
**Authentication:** Per-harness. Claude: `~/.claude/.credentials.json` mounted read-only + token-free stub. omp: `~/.omp/agent` mounted read-write. Other harnesses: harness-specific credential files mounted read-only.

---

*Architecture analysis: 2026-06-27*
