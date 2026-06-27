# Codebase Structure

**Analysis Date:** 2026-06-27

## Directory Layout

```
harnessed/
├── src/harnessed/          # Python application — all assembly + launch logic
│   ├── __init__.py         # Package init + __version__
│   ├── launcher.py         # `harnessed` CLI entry point (Typer)
│   ├── cli.py              # `harnessed-tools` CLI entry point (argparse, build-time)
│   ├── assemble.py         # Assembly orchestrator (emit-only pipeline)
│   ├── emit.py             # Profile artifact writer (.mcp.json, hatago.config, Dockerfile)
│   ├── synclinks.py        # Recipe skill/command fan-out with collision detection
│   ├── schema.py           # Typed models + YAML parsing (Agent/Recipe/Service/Stack)
│   ├── paths.py            # Single source of truth for host/container path resolution
│   ├── capability.py       # Capability test: manifest oracle vs live pod introspection
│   ├── report.py           # Rich terminal render of CapabilityReport
│   └── scan.py             # Supply-chain scanning (osv-scanner, pip-audit, snyk)
├── catalog/                # Contributor-authored content (source of truth)
│   ├── agents/             # AI harness definitions
│   │   ├── claude/         #   agent.yaml + Dockerfile reference
│   │   └── omp/            #   agent.yaml + Dockerfile reference
│   ├── base/               # Shared base images + supporting files
│   │   ├── Dockerfile.harnessed-base
│   │   ├── Dockerfile.harnessed-claude
│   │   ├── Dockerfile.harnessed-omp
│   │   ├── Dockerfile.harnessed-opencode
│   │   ├── Dockerfile.harnessed-gemini
│   │   ├── Dockerfile.harnessed-antigravity
│   │   ├── Dockerfile.harnessed-codex
│   │   ├── Dockerfile.hatago
│   │   ├── egress-firewall.sh
│   │   ├── harnessed-scan  # In-image scan script (RUN in derived Dockerfile)
│   │   └── pnpm/           # pnpm supply-chain policy files
│   ├── recipes/            # Composable capability bundles
│   │   ├── floating-recipe/
│   │   ├── greet/          #   recipe.yaml [+ skills/ commands/]
│   │   ├── gstack/
│   │   ├── ping/
│   │   └── time/           #   recipe.yaml + skills/time-helper/
│   ├── services/           # Shared sidecar definitions
│   │   └── ping/           #   service.yaml + Dockerfile + server.py
│   └── stacks/             # Stack manifests (agent + recipe composition)
│       ├── claude_floating-recipe/  stack.yaml
│       ├── claude_gstack_ping_time_greet/  stack.yaml
│       ├── claude_time/             stack.yaml
│       └── omp_gstack_ping_time_greet/    stack.yaml
├── profiles/               # Generated profiles in-repo (reference copies; production: XDG_DATA_HOME)
│   ├── tracer-time/        #   profiles/<stack>/.mcp.json, hatago.config.json, etc.
│   ├── gstack-time/
│   └── ...
├── schemas/                # JSON Schema files for YAML validation
│   ├── agent.schema.json
│   ├── recipe.schema.json
│   ├── service.schema.json
│   └── stack.schema.json
├── tests/                  # pytest suite
│   ├── __init__.py
│   ├── fixtures/           #   fixture catalog trees (not the main catalog)
│   │   ├── recipes/        #   low-recipe/, npm-recipe/, svc-recipe/
│   │   ├── services/       #   svc-test/
│   │   └── stacks/         #   low-stack/, npm-stack/, svc-stack/
│   ├── test_schema.py
│   ├── test_emit.py
│   ├── test_paths.py
│   ├── test_scan.py
│   ├── test_recipes_integration.py
│   ├── test_launcher_install.py
│   ├── test_claude_config_seed.py
│   └── test_omp_auth_seed.py
├── docs/                   # Documentation
│   ├── harnessed-design.md # Full design rationale (the "why")
│   ├── guides/             # How-to guides (recipe-authoring, stacks, service-authoring, secrets, troubleshooting)
│   ├── prompts/
│   ├── research/
│   └── todos/
├── tools/                  # Developer tooling (minimal)
│   ├── harnessed/          # (compiled/cached artifacts)
│   └── test-fixtures/
├── web/                    # Web content
│   ├── src/
│   │   ├── components/
│   │   ├── data/
│   │   ├── layouts/
│   │   ├── pages/
│   │   └── styles/
│   └── public/
├── systemd/                # systemd user timer units (nightly re-scan)
├── .agents/                # Agent skills (Claude Code skill tree)
├── .planning/              # GSD planning artifacts
│   └── codebase/           # Codebase maps (this file)
├── pyproject.toml          # Python project config + entry points + deps
├── pnpm-workspace.yaml     # pnpm supply-chain policy
├── ARCHITECTURE.md         # Authoritative architecture doc (in-repo, checked in)
├── AGENTS.md               # AI assistant instructions
├── CLAUDE.md               # Project conventions + tech stack reference
├── CONTRIBUTING.md         # Contributor guide
├── README.md               # User-facing entry point
└── schemas/                # JSON Schema (validates recipe/stack/agent/service YAML)
```

## Directory Purposes

**`src/harnessed/`:**
- Purpose: The entire Python application — all assembly and launch logic
- Contains: 10 modules covering CLI, assembly pipeline, schema, paths, scanning, capability testing
- Key files: `launcher.py` (user CLI), `assemble.py` + `emit.py` (assembly pipeline), `schema.py` (data models)

**`catalog/`:**
- Purpose: Everything contributors author — the source of truth for agents, recipes, services, stacks
- Contains: YAML manifests + Dockerfiles + skills dirs + service servers
- Key files: `catalog/base/Dockerfile.*` (shared images), `catalog/recipes/time/recipe.yaml` (reference recipe), `catalog/stacks/claude_time/stack.yaml` (minimal stack)

**`catalog/base/`:**
- Purpose: Shared base images and supporting infrastructure (egress firewall, pnpm policy, scan script)
- Contains: All per-harness Dockerfiles, hatago Dockerfile, pnpm supply-chain config, `harnessed-scan` script
- Key files: `Dockerfile.harnessed-base`, `Dockerfile.hatago`, `egress-firewall.sh`, `harnessed-scan`

**`schemas/`:**
- Purpose: JSON Schema validation for all YAML manifests (used by editor tooling; `# yaml-language-server: $schema=` comments in YAMLs)
- Contains: Four schemas — `agent.schema.json`, `recipe.schema.json`, `service.schema.json`, `stack.schema.json`
- Generated: No — hand-maintained

**`tests/fixtures/`:**
- Purpose: Minimal synthetic catalog trees for unit/integration tests (NOT the main catalog)
- Contains: `low-recipe/`, `npm-recipe/`, `svc-recipe/` + matching stacks and services
- Key convention: Test fixtures use minimal valid manifests to cover specific schema/behavior cases

**`profiles/`:**
- Purpose: In-repo reference copies of generated profiles (for review/diff); production profiles go to `$XDG_DATA_HOME/harnessed/profiles/<stack>/`
- Generated: Yes — by `harnessed build`
- Committed: Yes (as reference; `.gitignore` may exclude some)

**`.agents/`:**
- Purpose: Claude Code agent skills available in this workspace
- Contains: skill subdirectories (e.g., `diagnose`, `tdd`, `review`, etc.)

## Key File Locations

**Entry Points:**
- `src/harnessed/launcher.py`: `harnessed` CLI (Typer `app` + `main()`)
- `src/harnessed/cli.py`: `harnessed-tools` CLI (argparse `main()`)

**Configuration:**
- `pyproject.toml`: Python project, deps, entry points
- `pnpm-workspace.yaml`: pnpm supply-chain policy (`minimumReleaseAge`, `onlyBuiltDependencies`)
- `catalog/base/pnpm/`: Per-tree pnpm policy applied to all recipe pnpm trees

**Core Logic:**
- `src/harnessed/assemble.py`: Assembly orchestrator (the main pipeline)
- `src/harnessed/emit.py`: All profile artifact writes (deterministic, pure function)
- `src/harnessed/schema.py`: All YAML parsing and typed models
- `src/harnessed/paths.py`: All path computation (single source of truth)

**Testing:**
- `tests/`: Pytest suite (unit tests + podman-gated integration tests)
- `tests/fixtures/`: Synthetic catalog trees for isolated unit tests

**Documentation:**
- `ARCHITECTURE.md`: Architecture overview (checked in, authoritative)
- `docs/harnessed-design.md`: Full design rationale
- `docs/guides/`: How-to guides (recipe-authoring.md, stacks.md, service-authoring.md, secrets.md, troubleshooting.md)

## Naming Conventions

**Files:**
- Python modules: `snake_case.py` (e.g., `synclinks.py`, `assemble.py`)
- Dockerfiles: `Dockerfile.harnessed-<harness>` (base images), `Dockerfile.harnessed-<stack>` (generated derived images)
- YAML schemas: `<kind>.schema.json` (e.g., `recipe.schema.json`)
- Test files: `test_<module_or_concern>.py`

**Directories:**
- Catalog items: `<name>/` (lowercase, hyphens allowed within, e.g., `time-helper/`, `gstack/`)
- Stacks: `<agent>_<recipe>[_<recipe>...]` (underscores between fields, hyphens allowed within names)
- Profiles: `<stack-name>/` mirroring the stack naming

**Python identifiers:**
- Classes: `PascalCase` (e.g., `McpServer`, `CapabilityReport`, `LinkSyncer`)
- Functions: `snake_case`; private helpers prefixed with `_` (e.g., `_merge_servers`, `_run_assemble`)
- Constants: `UPPER_SNAKE` (e.g., `HATAGO_PORT`, `HATAGO_ENDPOINT`, `CONTAINER_HOME`)
- Exceptions: `PascalCase` ending in `Error` (e.g., `SchemaError`, `CollisionError`, `ScanError`)

**YAML manifests:**
- `name:` field: lowercase, hyphens (e.g., `name: time`, `name: ping`)
- `harness:` field: one of `claude|omp|opencode|gemini|antigravity|codex`

## Where to Add New Code

**New Recipe:**
- Manifest: `catalog/recipes/<name>/recipe.yaml` (use `# yaml-language-server: $schema=../../../schemas/recipe.schema.json`)
- Skills: `catalog/recipes/<name>/skills/<skill-name>/` (SKILL.md + content)
- Commands: `catalog/recipes/<name>/commands/<cmd-name>/`
- Dockerfile (optional): `catalog/recipes/<name>/Dockerfile` (body only — no FROM, no bare ARG HARNESS)
- Integration test: add a fixture under `tests/fixtures/recipes/<name>/` and test in `tests/test_recipes_integration.py`

**New Agent:**
- Manifest: `catalog/agents/<name>/agent.yaml`
- Base Dockerfile: `catalog/base/Dockerfile.harnessed-<name>`
- Launcher hook: add entry to `_HARNESS_ATTACH_CMD` dict in `src/harnessed/launcher.py`
- Schema constant: add to `HARNESS_CONFIG_DIR` dict in `src/harnessed/schema.py`

**New Service (sidecar):**
- Manifest: `catalog/services/<name>/service.yaml`
- Dockerfile: `catalog/services/<name>/Dockerfile`
- Server: `catalog/services/<name>/server.py` (or equivalent)
- Schema: `schemas/service.schema.json` already covers the format

**New Stack:**
- Manifest: `catalog/stacks/<agent>_<recipe>[_<recipe>...]/stack.yaml`
- No code changes needed if using existing agents and recipes

**New Feature in Assembly Pipeline:**
- Emit logic: add to `src/harnessed/emit.py` (write a new artifact)
- Model field: add to the relevant dataclass in `src/harnessed/schema.py`
- Orchestration: wire in `src/harnessed/assemble.py`

**New CLI Command:**
- User-facing interactive: add `@app.command()` in `src/harnessed/launcher.py`
- Build-time/CI: add subparser + handler in `src/harnessed/cli.py`

**Utility / Shared Path Logic:**
- Host/container paths: `src/harnessed/paths.py` only — never compute paths ad-hoc in callers

**Tests:**
- Unit tests: `tests/test_<module>.py` with fixtures from `tests/fixtures/`
- Podman-gated integration: mark with `pytest.mark.podman` (guarded by `HARNESSED_PODMAN=1`)

## Special Directories

**`profiles/` (in-repo):**
- Purpose: Reference copies of assembled profiles for review; CI may check these
- Generated: Yes — by `harnessed build`
- Committed: Yes (reference); production profiles land in `$XDG_DATA_HOME/harnessed/profiles/`
- Note: Never hand-edit — always regenerate with `harnessed build <stack>`

**`.planning/`:**
- Purpose: GSD planning artifacts (phases, codebase maps)
- Generated: Yes — by GSD workflow commands
- Committed: Yes

**`tools/`:**
- Purpose: Developer tooling support files
- Generated: Partially (compiled artifacts in `tools/harnessed/__pycache__`)
- Committed: Yes (source); caches in `.gitignore`

---

*Structure analysis: 2026-06-27*
