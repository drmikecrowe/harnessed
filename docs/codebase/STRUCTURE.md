# Codebase Structure

**Analysis Date:** 2026-06-16

`harnessed` is a two-engine repo: an EMIT-ONLY Python assembler (`tools/`) that produces
files, and a host-native bash launcher (`harnessed` + `lib/`) that runs podman. This
document maps where everything lives, how it is named, and where to add new code.

---

## Directory Layout

```
code-container/
├── harnessed                       # HOST launcher entrypoint (bash). Arg-parse + dispatch.
├── container                       # back-compat alias → `harnessed transparent` (§2)
├── install.sh                      # symlinks `harnessed` + `container` onto PATH
├── lib/                            # HOST runtime bash (mounted-into-instance + launcher libs)
│   ├── harnessed-common.sh         #   shared helpers: detect_runtime, build_images,
│   │                               #   build_stack, ensure_images, instance lifecycle, logging
│   ├── harnessed-runtime.sh        #   container-runtime abstraction: podman pod vs docker shared-netns, userns, existence checks
│   ├── harnessed-isolated.sh       #   isolated-stack launcher (group: harness + hatago via lib/harnessed-runtime.sh)
│   ├── harnessed-transparent.sh    #   transparent-stack launcher (host config, live)
│   ├── harnessed-mounts.sh         #   §4a host-integration mounts (auth/signing/agents/firewall)
│   ├── harnessed-isolated-config.sh#   §4b isolated auth (ro credential + generated stub)
│   ├── harnessed-claude-config.sh  #   transparent .claude.json copy-on-start
│   ├── harnessed-services.sh       #   shared service lifecycle (svc up/down/list)
│   ├── harnessed-cli.sh            #   §13 subcommands (list/stop/rm/new/install/uninstall)
│   ├── egress-firewall.sh          #   per-session egress firewall (NET_ADMIN)
│   └── pnpm/config.yaml            #   managed pnpm supply-chain config (shipped into images)
│
├── tools/                          # BUILD-TIME assembler (Python, EMIT-ONLY — never drives podman)
│   ├── Dockerfile                  #   builds the harnessed-tools image
│   ├── pyproject.toml              #   package meta + deps (ruamel.yaml, rich)
│   ├── uv.lock                     #   locked dep versions
│   └── harnessed/                  #   the assembler package
│       ├── cli.py                  #     CLI entrypoint: assemble / test / scan / scan-image
│       ├── assemble.py             #     orchestrate: load → lint → fan → merge → emit
│       ├── schema.py               #     parse + validate YAML → Stack/Recipe/McpServer/ServiceDef
│       ├── synclinks.py            #     LinkSyncer: fan skills/commands, fail-fast on collision
│       ├── emit.py                 #     write profile/.mcp.json/settings/hatago.config/baked manifest
│       ├── scan.py                 #     supply-chain source + image scans (BLD-02)
│       ├── capability.py           #     per-stack capability test (launch + introspect + assert)
│       ├── report.py               #     render the capability report (markdown / JSON)
│       └── __init__.py
│   ├── uat/                        #   host-side UAT suites (bash); ./tools/uat/run-uat.sh [N] [--quick]
│   │   ├── run-uat.sh              #   phase dispatcher
│   │   ├── uat-common.sh           #   shared AAA helpers + harness bootstrap
│   │   ├── phase-04.sh             #   isolated-stack UAT
│   │   ├── phase-05.sh             #   shared-services UAT
│   │   └── phase-06.sh             #   harness-matrix UAT (one proof stack per harness)
│   └── test-fixtures/              #   fixture stacks/recipes for the assembler + capability tests
│
├── base/                           # IMAGE TIER — standalone Dockerfiles, built by the host
│   ├── Dockerfile.harnessed-base   #   mise + node + python + common tooling (the lineage root)
│   ├── Dockerfile.harnessed-claude #   FROM harnessed-base + claude install
│   ├── Dockerfile.harnessed-omp    #   FROM harnessed-base + omp + claude-hooks-bridge
│   ├── Dockerfile.harnessed-opencode #   FROM harnessed-base + opencode + baked ~/.config/opencode MCP config
│   ├── Dockerfile.harnessed-gemini #   FROM harnessed-base + gemini-cli (in base) + baked ~/.gemini/settings.json MCP config
│   ├── Dockerfile.harnessed-antigravity #   FROM harnessed-base + agy (vendor installer) + baked ~/.gemini/config/mcp_config.json
│   ├── Dockerfile.harnessed-codex #   FROM harnessed-base + codex-cli (in base) + baked ~/.codex/config.toml MCP config
│   └── Dockerfile.hatago           #   hatago hub + light stdio servers (baked, pinned)
│
├── services/                       # SHARED SERVICE SIDECARS — each its own image/container/volume
│   └── <name>/                     #   e.g. ping/
│       ├── service.yaml            #     name, image, port, volume, healthcheck
│       ├── Dockerfile              #     standalone image (FROM python:…, etc.)
│       └── server.py               #     the service's MCP server impl
│
├── recipes/                        # AUTHORED recipe inputs (one per integration)
│   └── <name>/                     #   e.g. time/
│       ├── recipe.yaml             #     name, mcp.servers[], skills[], commands[], deps
│       └── skills/<skill-name>/    #     standalone skill dir(s) shipped by the recipe
│
├── stacks/                         # AUTHORED stack manifests (compose harness + recipes + services)
│   └── <name>/stack.yaml           #   e.g. tracer-time/stack.yaml
│
├── profiles/                       # GENERATED + COMMITTED assembler output (mounted into instances)
│   └── <stack>/                    #   e.g. tracer-time/
│       ├── .claude/                #     the harness profile (Claude-canonical)
│       │   ├── skills/             #     fanned by LinkSyncer
│       │   ├── commands/
│       │   ├── agents/  hooks/  rules/
│       │   ├── .mcp.json           #     ONE entry → hatago endpoint (localhost:3535/mcp)
│       │   └── settings.json       #     pre-approves the hatago hub's tools
│       ├── hatago.config.json      #     hatago mcpServers (children + URL proxies)
│       └── baked-servers.json      #     which stdio servers the hatago image must bake
│
├── docs/
│   ├── harnessed-design.md         # ARCHITECTURE SOURCE OF TRUTH (§1–§18). Read this first.
│   └── codebase/                   #   generated codebase analysis (this file + siblings)
│
├── .planning/                      # GSD planning artifacts (roadmap, state, per-phase plans)
│   ├── ROADMAP.md  STATE.md  REQUIREMENTS.md  PROJECT.md  config.json
│   ├── research/
│   └── phases/
│       └── <NN>-<slug>/            #   e.g. 04-shared-services-recipe-breadth-full-cli/
│           ├── <NN>-<mm>-PLAN.md   #     per-task plan (mm = task index within the phase)
│           ├── <NN>-<mm>-SUMMARY.md#     per-task completion summary
│           ├── <NN>-RESEARCH.md    #     phase research
│           └── <NN>-UAT.md         #     user-acceptance test notes
│
├── .claude/  .agents/  .codex/  .opencode/  .gemini/   # local dev harness configs (not shipped)
├── .env.schema.example             # varlock secrets template (§16) — copy to ~/.config/harnessed/
├── CLAUDE.md  AGENTS.md  README.md  Permissions.md
├── extra-tools.txt                 # operator-editable list of extra tools to install in images
├── extra-tools.default.txt         # default extra-tools.txt (seeded on first build)
└── Dockerfile                      # = tools/Dockerfile (repo-root convenience copy)
```

---

## Key Locations

**Entry points**
- Host launcher: `harnessed` (bash bootstrap) → dispatches into `lib/harnessed-*.sh`.
- Assembler CLI: `tools/harnessed/cli.py` → `python -m harnessed.cli` (run inside the
  `harnessed-tools` image by `build_stack`).

**Build-time (emit-only)**
- Assembler package: `tools/harnessed/` (`assemble.py`, `schema.py`, `synclinks.py`,
  `emit.py`, `scan.py`, `capability.py`, `report.py`).
- Assembler image: `tools/Dockerfile` (repo-root `Dockerfile` is the same file).

**Runtime (host-native)**
- Shared helpers + image build + instance lifecycle: `lib/harnessed-common.sh`.
- Container-runtime abstraction (podman pod | docker shared-netns; userns + existence checks): `lib/harnessed-runtime.sh`.
- Mode launchers: `lib/harnessed-isolated.sh`, `lib/harnessed-transparent.sh`.
- Mount layers: `lib/harnessed-mounts.sh` (§4a, all stacks),
  `lib/harnessed-isolated-config.sh` (§4b isolated auth), `lib/harnessed-claude-config.sh`
  (§4b transparent copy-on-start).
- Service lifecycle: `lib/harnessed-services.sh`.
- First-class CLI ops: `lib/harnessed-cli.sh`.

**Inputs (authored)**
- Recipes: `recipes/<name>/recipe.yaml` (+ `recipes/<name>/skills/<skill-name>/`).
- Stacks: `stacks/<name>/stack.yaml`.
- Services: `services/<name>/{service.yaml,Dockerfile,server.py}`.

**Generated (committed, mounted)**
- Profiles: `profiles/<stack>/.claude/{skills,commands,agents,hooks,rules}/` +
  `.mcp.json` + `settings.json`, and `profiles/<stack>/{hatago.config.json,baked-servers.json}`.

**Images**
- `harnessed-base:latest`, `harnessed-claude:latest`, `harnessed-omp:latest`, `harnessed-opencode:latest`,
  `harnessed-gemini:latest`, `harnessed-antigravity:latest`, `harnessed-codex:latest`, `harnessed-hatago:latest`, `harnessed-tools:latest`,
  `harnessed-<service>:latest`.

**Spec / planning**
- Architecture source of truth: `docs/harnessed-design.md`.
- Planning: `.planning/ROADMAP.md`, `.planning/STATE.md`, `.planning/phases/<NN>-<slug>/`.

---

## Naming Conventions

**Files in `lib/`** — `harnessed-<role>.sh`, one responsibility each:
`harnessed-common.sh` (shared helpers), `harnessed-runtime.sh` (container-runtime abstraction), `harnessed-isolated.sh` /
`harnessed-transparent.sh` (mode launchers), `harnessed-mounts.sh` /
`harnessed-isolated-config.sh` / `harnessed-claude-config.sh` (mount layers),
`harnessed-services.sh`, `harnessed-cli.sh`. The one non-`harnessed-` file is
`egress-firewall.sh` (a script mounted *into* the instance, not a launcher lib).

**Images in `base/`** — `Dockerfile.harnessed-<tier>` for the lineage
(`harnessed-base`, `harnessed-claude`, `harnessed-omp`, `harnessed-opencode`, `harnessed-gemini`, `harnessed-antigravity`, `harnessed-codex`) and `Dockerfile.hatago` for the
hub. Sidecar images live at `services/<name>/Dockerfile` (no `Dockerfile.` prefix).

**Instances / pods** — `harnessed-<stack>-<projhash>` (from `generate_instance_name`). The
pod and the harness member share this base name; the hatago member is
`harnessed-<stack>-<projhash>-hatago`. The project path is part of identity because bind
mounts are fixed at creation.

**Shared services** — global by name on `harnessed-net`: the container is `<service>`,
the volume is `<service>-data`, the label is `harnessed-service=<name>`.

**Python modules** — `tools/harnessed/<topic>.py`, one topic per module (`schema`,
`assemble`, `emit`, `synclinks`, `scan`, `capability`, `report`, `cli`). Lowercase,
no underscores.

**Profiles** — mirror the stack name exactly: `profiles/<stack>/`.

**Planning artifacts** — `.planning/phases/<NN>-<slug>/` where `NN` is the two-digit phase
number and `<slug>` is a kebab description (e.g. `04-shared-services-recipe-breadth-full-cli`).
Within a phase: `<NN>-PLAN.md` (whole-phase plan), `<NN>-<mm>-PLAN.md` +
`<NN>-<mm>-SUMMARY.md` (per-task `mm`), `<NN>-RESEARCH.md`, `<NN>-UAT.md`,
`<NN>-VERIFICATION.md`, `<NN>-SUMMARY.md`.

**Config-mode switch** — `config: isolated | transparent` in `stack.yaml`. `transparent`
is the built-in host-mirror stack (`stacks/transparent/stack.yaml`); everything else is
`isolated`.

**Pinned versions** — every external install in an image is pinned via an `ARG`
(`UV_VERSION=0.11.8`, `HATAGO_VERSION=0.0.16`, `MCP_SERVER_TIME_VERSION=2026.6.4` in
`base/Dockerfile.hatago`). Never `npm`/`npx` — always `pnpm`/`pnpm dlx`
(`validate_no_raw_npm` enforces this in recipes).

---

## Where to Add New Code

### A new recipe
1. `mkdir recipes/<name>/` and write `recipes/<name>/recipe.yaml`:
   ```yaml
   name: <name>
   description: …
   mcp:
     servers:
       - name: <server>
         command: uvx              # or pnpm dlx — NEVER npm/npx (BLD-03 lint fails the build)
         args: [<pkg>]
         transport: stdio          # explicit (stdio → hatago child; http → URL proxy)
   skills:
     - path: skills/<skill-name>   # a standalone dir under recipes/<name>/
   ```
2. Ship the skill dir: `recipes/<name>/skills/<skill-name>/SKILL.md` (Claude-canonical).
3. Reference it from a stack: add `<name>` to `recipes: […]` in a `stacks/<stack>/stack.yaml`.
4. `harnessed build <stack>` → the assembler fans the skill, merges the server, emits the
   profile, scans, and builds the hatago image.

> A skill/command name collision across two recipes in the same stack is a **hard error**
> (`CollisionError` from `LinkSyncer`). Rename one — there is no last-wins fallback.

### A new stack
- **Scaffold:** `harnessed new <stack> --harness claude --recipes a,b,c` → writes
  `stacks/<stack>/stack.yaml` (refuses overwrite; validates `harness ∈ {claude, omp, opencode, gemini, antigravity, codex}`).
- **Or hand-author:** `stacks/<stack>/stack.yaml` with `name`, `config: isolated`,
  `harness`, `recipes: […]`, optional `services: […]`, `permissions`, `state`.
- **Build + install:** `harnessed build <stack>` then `harnessed install <stack>` (writes
  a `~/.local/bin/<stack>` shim so the stack launches by name from any cwd).
- **Launch:** `harnessed <stack> [path]`.

### A new shared service
1. `mkdir services/<name>/` and write `service.yaml`:
   ```yaml
   name: <name>
   image: harnessed-<name>:latest
   volume: <name>-data            # service-scoped; survives svc down (§9)
   port: 8080
   healthcheck: "curl -sf http://localhost:8080/health || exit 1"
   ```
2. Write `services/<name>/Dockerfile` (standalone — `FROM python:3.12-slim`, etc.) and the
   server impl (`server.py`).
3. **Reference it** so instances attach: either from a recipe
   (`mcp.servers[].service: <name>`, resolved to a hatago URL-proxy entry by
   `_resolve_service_servers`) and/or from a stack (`services: [<name>]`, auto-started by
   the isolated launcher's `ensure_service_up` loop).
4. **Manage it:** `harnessed svc up <name>` (builds the image on first use, runs the BLD-02
   image scan, starts the container on `harnessed-net` with the named volume). `svc down`
   stops it (volume kept); `svc down --purge` destroys the volume.

### A new lib helper (host runtime)
Add `lib/harnessed-<role>.sh` and `source` it from `harnessed` or another `lib/` file
(launchers source their dependencies explicitly with `.` / `shellcheck source=` hints).
The shared helpers in `lib/harnessed-common.sh` (logging, image build, instance
lifecycle) are already available to every sourced lib. Keep it host-native: every podman
call runs on the host — no daemon socket, no `CONTAINER_HOST`.

### A new assembler module (build-time)
Add `tools/harnessed/<topic>.py` and import it from `tools/harnessed/cli.py` (for a new
subcommand) or `tools/harnessed/assemble.py` (for a new assembly step). Keep it
**emit-only**: read from the mounted root, write to the build dir, never invoke podman.
Add new manifest fields by parsing them forward on `Recipe.raw` / `Stack.raw` (D-14) so
existing recipes keep working without a schema change.
