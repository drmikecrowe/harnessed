# Codebase Structure

**Analysis Date:** 2026-06-22

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
├── uninstall.sh                    # removes the PATH symlinks
├── copy-configs.sh                 # helper to copy host harness configs into the repo for dev
├── .env.schema.example             # varlock secrets template (§16) — copy to ~/.config/harnessed/
├── extra-tools.txt                 # operator-editable list of extra tools to install in images
├── extra-tools.default.txt         # default extra-tools.txt (seeded on first build)
├── Dockerfile                      # = tools/Dockerfile (repo-root convenience copy)
├── DESIGN.md                       # symlink/alias → docs/harnessed-design.md
├── AGENTS.md  CLAUDE.md  README.md  Permissions.md
├── lib/                            # HOST runtime bash (mounted-into-instance + launcher libs)
│   ├── harnessed-common.sh         #   shared helpers: detect_runtime, build_images,
│   │                               #   build_stack, ensure_images, instance lifecycle, logging
│   ├── harnessed-runtime.sh        #   container-runtime abstraction: podman pod vs docker
│   │                               #   shared-netns, userns, network/volume/group existence
│   ├── harnessed-isolated.sh       #   isolated-stack launcher (group: harness + hatago)
│   ├── harnessed-transparent.sh    #   transparent-stack launcher (host config, live)
│   ├── harnessed-mounts.sh         #   §4a host-integration mounts (auth/signing/agents/firewall)
│   ├── harnessed-isolated-config.sh#   §4b isolated auth (ro credential + generated stub,
│   │                               #   harness-aware: claude/omp/gemini/codex/opencode/antigravity)
│   ├── harnessed-claude-config.sh  #   transparent .claude.json copy-on-start
│   ├── harnessed-services.sh       #   shared service lifecycle (svc up/down/list)
│   ├── harnessed-cli.sh            #   §13 subcommands (list/stop/rm/new/install/uninstall)
│   ├── harnessed-secrets.sh        #   varlock/1Password secret resolution (opt-in; inert otherwise)
│   ├── harnessed-rescan.sh         #   SEC-04 nightly online image re-scan
│   ├── egress-firewall.sh          #   per-session egress firewall (NET_ADMIN); mounted INTO the
│   │                               #   instance — allows host.containers.internal (service proxy)
│   └── pnpm/config.yaml            #   managed pnpm supply-chain config (shipped into images)
│
├── tools/                          # BUILD-TIME assembler (Python, EMIT-ONLY — never drives podman)
│   ├── Dockerfile                  #   builds the harnessed-tools image
│   ├── pyproject.toml              #   package meta + deps (ruamel.yaml, rich)
│   ├── uv.lock                     #   locked dep versions
│   ├── pnpm-workspace.yaml         #   pnpm allow-build scoping (project-scoped, not global)
│   ├── harnessed/                  #   the assembler package
│   │   ├── cli.py                  #     CLI entrypoint: assemble / test / scan / scan-image / scan-image-online
│   │   ├── assemble.py             #     orchestrate: load → lint → fan → merge → resolve → emit
│   │   ├── schema.py               #     parse + validate YAML → Stack/Recipe/McpServer/ServiceDef/FileExt
│   │   ├── synclinks.py            #     LinkSyncer: fan skills/commands, fail-fast on collision
│   │   ├── emit.py                 #     write profile/.mcp.json/settings/hatago.config/baked manifest
│   │   ├── scan.py                 #     supply-chain source + image scans (BLD-02)
│   │   ├── capability.py           #     per-stack capability test (launch + introspect + assert)
│   │   ├── report.py               #     render the capability report (markdown / JSON)
│   │   └── __init__.py
│   ├── uat/                        #   host-side UAT suites (bash); ./tools/uat/run-uat.sh [N] [--quick]
│   │   ├── run-uat.sh              #   phase dispatcher
│   │   ├── uat-common.sh           #   shared AAA helpers + harness bootstrap
│   │   ├── phase-04.sh             #   isolated-stack UAT
│   │   ├── phase-05.sh             #   shared-services UAT
│   │   └── phase-06.sh             #   harness-matrix UAT (one proof stack per harness)
│   └── test-fixtures/              #   fixture stacks/recipes/services for the assembler + capability tests
│       ├── stacks/                 #     {svc-stack, low-stack, vuln-stack, npm-stack}/stack.yaml
│       ├── recipes/                #     {svc-recipe, low-recipe, vuln-recipe, npm-recipe}/recipe.yaml
│       └── services/               #     svc-test/service.yaml
│
├── base/                           # IMAGE TIER — standalone Dockerfiles, built by the host
│   ├── Dockerfile.harnessed-base   #   mise + node + python + common tooling (the lineage root)
│   ├── Dockerfile.harnessed-claude #   FROM harnessed-base + claude install
│   ├── Dockerfile.harnessed-omp    #   FROM harnessed-base + omp + claude-hooks-bridge
│   ├── Dockerfile.harnessed-opencode # FROM harnessed-base + opencode + baked ~/.config/opencode MCP config
│   ├── Dockerfile.harnessed-gemini #   FROM harnessed-base + gemini-cli (in base) + baked ~/.gemini/settings.json
│   ├── Dockerfile.harnessed-antigravity # FROM harnessed-base + agy (vendor installer) + baked ~/.gemini/config/mcp_config.json
│   ├── Dockerfile.harnessed-codex  #   FROM harnessed-base + codex-cli (in base) + baked ~/.codex/config.toml
│   └── Dockerfile.hatago           #   hatago hub + light stdio servers (baked, pinned)
│
├── services/                       # SHARED SERVICE SIDECARS — each its own image/container/volume
│   └── ping/                       #   the tracer service (FastMCP streamable-http)
│       ├── service.yaml            #     name, image, port (8080), volume, healthcheck
│       ├── Dockerfile              #     standalone image (FROM python:…)
│       └── server.py               #     the service's MCP server impl (allowed_hosts incl. host.containers.internal)
│
├── recipes/                        # AUTHORED recipe inputs (one per integration)
│   ├── <name>/recipe.yaml          #   name, mcp.servers[], skills[], commands[], deps
│   └── <name>/skills/<skill-name>/ #   standalone skill dir(s) shipped by the recipe
│   # current: time, ping, omp, greet, opencode, gemini, antigravity, codex
│
├── stacks/                         # AUTHORED stack manifests (compose harness + recipes + services)
│   └── <name>/stack.yaml           #   e.g. tracer-time/stack.yaml
│   # current: transparent, tracer-time, ping-time, claude-multi, omp-time,
│   #          opencode-time, gemini-time, antigravity-time, codex-time
│
├── profiles/                       # GENERATED + COMMITTED assembler output (mounted into instances)
│   └── <stack>/                    #   e.g. tracer-time/
│       ├── .claude/                #     the harness profile (Claude-canonical — all 6 harnesses)
│       │   ├── skills/             #     fanned by LinkSyncer
│       │   ├── commands/  agents/  hooks/  rules/
│       │   ├── .mcp.json           #     ONE entry → hatago endpoint (localhost:3535/mcp)
│       │   └── settings.json       #     pre-approves the hatago hub's tools
│       ├── hatago.config.json      #     hatago mcpServers (stdio children + URL proxies)
│       └── baked-servers.json      #     which stdio servers the hatago image must bake
│
├── systemd/                        # SEC-04 nightly re-scan (user units)
│   ├── harnessed-rescan.service    #   ExecStart = `harnessed rescan`
│   └── harnessed-rescan.timer      #   schedule
│
├── docs/
│   ├── harnessed-design.md         # ARCHITECTURE SOURCE OF TRUTH (§1–§18). Read this first.
│   ├── guides/                     #   operator guides (recipe/stack/service/secrets/troubleshooting authoring)
│   ├── prompts/                    #   recipe-authoring prompt
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
└── skills-lock.json                # lockfile for skills synced into the repo
```

> **`recipes/`, `stacks/`, `profiles/` all mirror the stack/recipe name exactly.** Adding
> a harness does not add a directory tier — all six harnesses read the *same* committed
> `.claude` profile; the harness is a single field in `stack.yaml` (see ARCHITECTURE.md →
> Key Abstractions).

---

## Key Locations

**Entry points**
- Host launcher: `harnessed` (bash bootstrap) → dispatches into `lib/harnessed-*.sh`.
- Assembler CLI: `tools/harnessed/cli.py` → `python -m harnessed.cli` (run inside the
  `harnessed-tools` image by `build_stack`).
- Back-compat alias: `container` → `harnessed transparent`.

**Build-time (emit-only)**
- Assembler package: `tools/harnessed/` (`assemble.py`, `schema.py`, `synclinks.py`,
  `emit.py`, `scan.py`, `capability.py`, `report.py`, `cli.py`).
- Assembler image: `tools/Dockerfile` (repo-root `Dockerfile` is the same file).
- Fixture stacks/recipes/services: `tools/test-fixtures/` (exercised by `tools/uat/`).

**Runtime (host-native)**
- Shared helpers + image build + instance lifecycle: `lib/harnessed-common.sh`.
- Container-runtime abstraction (podman pod | docker shared-netns; userns + existence checks): `lib/harnessed-runtime.sh`.
- Mode launchers: `lib/harnessed-isolated.sh`, `lib/harnessed-transparent.sh`.
- Mount layers: `lib/harnessed-mounts.sh` (§4a, all stacks),
  `lib/harnessed-isolated-config.sh` (§4b isolated auth, harness-aware),
  `lib/harnessed-claude-config.sh` (§4b transparent copy-on-start).
- Service lifecycle: `lib/harnessed-services.sh`.
- Secret resolution (opt-in): `lib/harnessed-secrets.sh`.
- Nightly re-scan: `lib/harnessed-rescan.sh` (+ `systemd/harnessed-rescan.{service,timer}`).
- First-class CLI ops: `lib/harnessed-cli.sh`.
- Egress firewall (mounted INTO the instance): `lib/egress-firewall.sh`.

**Inputs (authored)**
- Recipes: `recipes/<name>/recipe.yaml` (+ `recipes/<name>/skills/<skill-name>/`).
- Stacks: `stacks/<name>/stack.yaml`.
- Services: `services/<name>/{service.yaml,Dockerfile,server.py}`.

**Generated (committed, mounted)**
- Profiles: `profiles/<stack>/.claude/{skills,commands,agents,hooks,rules}/` +
  `.mcp.json` + `settings.json`, and `profiles/<stack>/{hatago.config.json,baked-servers.json}`.

**Images**
- Harness lineage: `harnessed-base`, `harnessed-claude`, `harnessed-omp`,
  `harnessed-opencode`, `harnessed-gemini`, `harnessed-antigravity`, `harnessed-codex`
  (all `:latest`, all `FROM harnessed-base`).
- Hub: `harnessed-hatago`. Assembler: `harnessed-tools`. Sidecars: `harnessed-<service>`
  (e.g. `harnessed-ping`).

**Spec / planning**
- Architecture source of truth: `docs/harnessed-design.md`.
- Operator guides: `docs/guides/{recipe-authoring,stacks,service-authoring,secrets,troubleshooting}.md`.
- Planning: `.planning/ROADMAP.md`, `.planning/STATE.md`, `.planning/phases/<NN>-<slug>/`.

---

## Naming Conventions

**Files in `lib/`** — `harnessed-<role>.sh`, one responsibility each:
`harnessed-common.sh` (shared helpers), `harnessed-runtime.sh` (container-runtime
abstraction), `harnessed-isolated.sh` / `harnessed-transparent.sh` (mode launchers),
`harnessed-mounts.sh` / `harnessed-isolated-config.sh` / `harnessed-claude-config.sh`
(mount layers), `harnessed-services.sh`, `harnessed-cli.sh`, `harnessed-secrets.sh`,
`harnessed-rescan.sh`. The one non-`harnessed-` file is `egress-firewall.sh` (a script
mounted *into* the instance, not a launcher lib).

**Images in `base/`** — `Dockerfile.harnessed-<tier>` for the lineage
(`harnessed-base`, `harnessed-claude`, `harnessed-omp`, `harnessed-opencode`,
`harnessed-gemini`, `harnessed-antigravity`, `harnessed-codex`) and `Dockerfile.hatago`
for the hub. Sidecar images live at `services/<name>/Dockerfile` (no `Dockerfile.`
prefix).

**Instances / pods** — `harnessed-<stack>-<projhash>` (from `generate_instance_name`,
`lib/harnessed-common.sh:288-300`). The pod and the harness member share this base name;
the hatago member is `harnessed-<stack>-<projhash>-hatago`. The project path is part of
identity because bind mounts are fixed at creation.

**Shared services** — global by name. The container is `<service>`, the volume is
`<service>-data` (service-scoped, survives `svc down`), the label is
`harnessed-service=<name>`. The container **publishes its port to `0.0.0.0`** and peers
reach it via the podman host gateway `host.containers.internal:<port>` (the primary
reachability model — rootless `pasta` networking, *not* a bridge). The `harnessed-net`
bridge + DNS-by-name is the **`HARNESSED_NET` opt-in** for bridge-capable hosts only.
Never describe a shared service as "on `harnessed-net`" by default — it is not.

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

**Harness switch** — `harness: claude | omp | opencode | gemini | antigravity | codex` in
`stack.yaml` (exactly one). All six mount the same `.claude` profile; the harness only
changes how it is read + how it reaches hatago.

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

> See `docs/guides/recipe-authoring.md` for the full worked example.

> A skill/command name collision across two recipes in the same stack is a **hard error**
> (`CollisionError` from `LinkSyncer`). Rename one — there is no last-wins fallback.

### A new stack
- **Scaffold:** `harnessed new <stack> --harness <claude|omp|opencode|gemini|antigravity|codex> --recipes a,b,c`
  → writes `stacks/<stack>/stack.yaml` (refuses overwrite; validates harness).
- **Or hand-author:** `stacks/<stack>/stack.yaml` with `name`, `config: isolated`,
  `harness`, `recipes: […]`, optional `services: […]`, `permissions`, `state`.
- **Build + install:** `harnessed build <stack>` then `harnessed install <stack>` (writes
  a `~/.local/bin/<stack>` shim so the stack launches by name from any cwd).
- **Launch:** `harnessed <stack> [path]`.

> See `docs/guides/stacks.md`.

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
   server impl (`server.py`). If the server is a FastMCP streamable-http service proxied
   over `host.containers.internal`, **add `host.containers.internal` to
   `TransportSecuritySettings.allowed_hosts`** or FastMCP returns `421 Misdirected
   Request` — copy the pattern from `services/ping/server.py:19-26`.
3. **Reference it** so instances attach: either from a recipe
   (`mcp.servers[].service: <name>`, resolved to a hatago URL-proxy entry pointing at
   `http://host.containers.internal:<port>/mcp` by `_resolve_service_servers`) and/or from
   a stack (`services: [<name>]`, auto-started by the isolated launcher's
   `ensure_service_up` loop).
4. **Manage it:** `harnessed svc up <name>` (builds the image on first use, runs the BLD-02
   image scan, starts the container publishing its port to `0.0.0.0` with the named volume).
   `svc down` stops it (volume kept); `svc down --purge` destroys the volume.

> See `docs/guides/service-authoring.md` (incl. the "Networking note" on `allowed_hosts`).

> The service is a standalone host-published container — **not** on `harnessed-net` unless
> `HARNESSED_NET` is set. Peers reach it at `host.containers.internal:<port>`.

### A new harness
A new harness touches four places, all mirroring the existing six:
1. `base/Dockerfile.harnessed-<harness>` — `FROM harnessed-base` + the harness install +
   a baked MCP config pointing one remote server at `http://localhost:3535/mcp`.
2. `schema.py` `HARNESS_CONFIG_DIR` — map `<harness> → ".claude"` (single source of truth)
   + the harness-image selector branch in `lib/harnessed-isolated.sh:43-55` +
   `lib/harnessed-common.sh` (`HARNESSED_<HARNESS>_IMAGE`, `ensure_<harness>_image`).
3. `lib/harnessed-isolated-config.sh` — the harness's auth-seeding branch (which host
   credential file to mount ro, or the limitation if none is mountable).
4. A proof stack + recipe under `stacks/<harness>-time/` and `recipes/<harness>/`, plus a
   row in `tools/uat/phase-06.sh` (the harness-matrix regression gate).

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
