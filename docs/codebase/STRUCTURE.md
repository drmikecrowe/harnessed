# Repository structure — `harnessed`

> Generated 2026-06-22. Walks the top-level directories, key locations, naming conventions, and where
> to add new code. Read alongside `docs/codebase/ARCHITECTURE.md` (the *how it's wired*) and
> `docs/harnessed-design.md` (the *why*).

`harnessed` is a bash-first CLI plus a containerized Python toolset. The repository is organized so
that **inputs are hand-authored** (`recipes/`, `stacks/`, `services/`, `base/`), **outputs are
generated-and-committed** (`profiles/`), and **the engine is split** between host bash (`harnessed` +
`lib/`) and the containerized assembler (`tools/`).

```
code-container/
├── harnessed                # host bootstrap CLI (dependency-free bash) — the entry point
├── container                # back-compat alias → harnessed transparent
├── lib/                     # bash module library (sourced just-in-time by `harnessed`)
├── tools/                   # harnessed-tools: the build-time assembler (Python; its own image)
│   ├── harnessed/           #   the Python package: schema·assemble·emit·scan·capability·report
│   └── uat/                 #   user-acceptance test scripts (per-phase)
├── base/                    # Dockerfile.harnessed-* (harness images) + Dockerfile.hatago
├── recipes/                 # hand-authored per-capability definitions (recipe.yaml)
├── stacks/                  # authored stack manifests (stack.yaml)
├── services/                # shared sidecar services (own Dockerfile + service.yaml + server)
├── profiles/                # GENERATED + committed; mounted into isolated harness containers
├── web/                     # Astro marketing/docs site (pnpm)
├── systemd/                 # user units for the nightly rescan timer
├── docs/                    # design doc + guides + this codebase map
├── install.sh / uninstall.sh
├── .env.schema.example      # varlock secrets template (copy to ~/.config/harnessed/)
├── extra-tools.default.txt  # default extra-tools list (apt/mise tools to bake into harnessed-base)
└── Dockerfile               # (legacy host-image; the active images live in base/)
```

---

## Top-level directories

### `lib/` — the bash module library

Host-native bash, sourced just-in-time by `harnessed`. Every module's header states the contract it
expects and what it appends. **Do not put Python here** — all assembly logic lives in `tools/`.

| File | Role |
|---|---|
| `lib/harnessed-common.sh` | The substrate: logging (`print_*`), `detect_runtime`, image build/ensure (`build_images`, `build_stack`, `ensure_images`), instance lifecycle (`generate_instance_name`, `stop_instance`, `remove_instance`, `apply_firewall`). Sources `harnessed-runtime.sh`. |
| `lib/harnessed-runtime.sh` | Provider abstraction (`rt_*`): podman pods vs docker shared-netns; `rt_group_create`, `rt_hatago_placement`, `rt_harness_placement`, `rt_group_teardown`. |
| `lib/harnessed-cli.sh` | First-class subcommands by name: `list_all`, `stop_stack`, `rm_stack`, `new_stack`, `install_stack`, `uninstall_stack`. |
| `lib/harnessed-mounts.sh` | The shared §4a host-integration mount layer (auth/signing/agents/firewall) — `harnessed_host_integration_mounts`. |
| `lib/harnessed-transparent.sh` | The transparent launcher — `harnessed_transparent`. |
| `lib/harnessed-isolated.sh` | The isolated launcher — `harnessed_isolated` (composes the pod, attaches). |
| `lib/harnessed-isolated-config.sh` | Isolated §4b auth seeding — `harnessed_isolated_auth_mounts`. |
| `lib/harnessed-claude-config.sh` | Transparent `.claude.json` copy-on-start — `harnessed_claude_json_copy_mount`. |
| `lib/harnessed-services.sh` | Shared service lifecycle — `svc_up`, `svc_down`, `svc_list`, `ensure_service_up`, `build_service_image`. |
| `lib/harnessed-secrets.sh` | Opt-in varlock + 1Password (`resolve_secret_env`) + scanner-token auth (`auth_scanner`). |
| `lib/harnessed-rescan.sh` | Nightly image re-scan — `harnessed_rescan_images`. |
| `lib/egress-firewall.sh` | The whitelist egress firewall; runs **inside** each instance as `/usr/local/sbin/egress-firewall`. |
| `lib/pnpm/config.yaml` | Managed pnpm supply-chain policy (shipped into the base + tools images). |

**Naming convention:** `lib/harnessed-<concern>.sh`. A module exports one or more namespaced
functions (snake_case, optionally `harnessed_<verb>` / `svc_<verb>` / `rt_<verb>`) and documents its
contract in a header comment. Source a new lib lazily in the bootstrap's dispatch, not eagerly.

### `tools/` — the build-time assembler (Python; its own image)

The `harnessed-tools` image (`tools/Dockerfile`). **Emit-only**: it reads/writes a bind-mounted build
dir and never invokes podman. Built from `python:3.13-slim` + jq + pinned osv-scanner + pre-seeded
offline OSV DBs + varlock/op/snyk/socket (all inert unless a schema/token exists).

| File | Role |
|---|---|
| `tools/Dockerfile` | The assembler image. UID-paired to 1000 (`--userns=keep-id`); managed pnpm config inlined. |
| `tools/pyproject.toml` | The Python package definition (`[project.scripts] harnessed-tools`). |
| `tools/uv.lock` | Locked deps (uv). |
| `tools/pnpm-workspace.yaml` | Project-scoped `allowBuilds` (snyk's postinstall). |
| `tools/harnessed/schema.py` | Typed models (`Recipe`, `Stack`, `McpServer`, `FileExt`, `ServiceDef`); `HARNESS_CONFIG_DIR`; raw-npm lint (`validate_no_raw_npm`); `expected_capabilities`. |
| `tools/harnessed/assemble.py` | The assembly orchestration (`assemble`). |
| `tools/harnessed/emit.py` | Pure file-emission (`write_mcp_json`, `write_hatago_config`, `write_baked_manifest`); `HATAGO_ENDPOINT`. |
| `tools/harnessed/scan.py` | The supply-chain gate: CVSS math, `gate`, `run_source_scan`, `run_image_scan`, `run_image_scan_online`. |
| `tools/harnessed/capability.py` | The capability test (`run_capability_test`). |
| `tools/harnessed/report.py` | Renders the capability result (rich table or `--json`). |
| `tools/harnessed/synclinks.py` | Fans skills/commands into harness-native paths; `CollisionError`. |
| `tools/uat/` | Per-phase UAT scripts (`run-uat.sh` driver, `phase-04..06.sh`, `uat-common.sh`). |

**Convention:** keep the pure logic (CVSS, manifest→expected, collision check) separate from the
subprocess-invoking code so it is unit-testable without podman. Add a new assembler behavior by
extending `schema.py` (parse) → `assemble.py` (orchestrate) → `emit.py` (write).

### `base/` — image definitions (Dockerfiles)

Per the "FROM is lineage only" rule (design §6), every image is a thin layer over `harnessed-base`:

| File | Image | Purpose |
|---|---|---|
| `base/Dockerfile.harnessed-base` | `harnessed-base:latest` | Lineage root: Ubuntu 24.04 + mise + node@22 + pnpm@11 + python + 1Password + iptables + a `harnessed` user (uid 1000). |
| `base/Dockerfile.harnessed-claude` | `harnessed-claude:latest` | `FROM harnessed-base` + the Claude Code CLI. |
| `base/Dockerfile.harnessed-omp` | `harnessed-omp:latest` | `FROM harnessed-base` + omp + pre-installed `claude-hooks-bridge`. |
| `base/Dockerfile.harnessed-opencode` | `harnessed-opencode:latest` | `FROM harnessed-base` + opencode + baked `~/.config/opencode` MCP config → hatago. |
| `base/Dockerfile.harnessed-gemini` | `harnessed-gemini:latest` | `FROM harnessed-base` (gemini-cli already in base) + baked `~/.gemini/settings.json`. |
| `base/Dockerfile.harnessed-antigravity` | `harnessed-antigravity:latest` | `FROM harnessed-base` + the `agy` CLI + baked `~/.gemini/config/mcp_config.json`. |
| `base/Dockerfile.harnessed-codex` | `harnessed-codex:latest` | `FROM harnessed-base` (codex already in base) + baked `~/.codex/config.toml`. |
| `base/Dockerfile.hatago` | `harnessed-hatago:latest` | `FROM harnessed-base` + uv/uvx + hatago hub (pinned, pnpm) + baked light stdio servers. |

**Naming convention:** `base/Dockerfile.harnessed-<harness>` for a harness image,
`base/Dockerfile.hatago` for the hub. Harness images are **lazy-built** (`ensure_<harness>_image`)
only when a stack with that `harness:` launches — claude-only users never build omp/opencode/etc.

### `recipes/` — hand-authored capability definitions

A **recipe** is one capability bundle (an MCP server, a set of skills, a vendored plugin). One dir
per recipe; the assembler fans its layers into the profile.

```
recipes/<name>/
  recipe.yaml                  # required: name, optional mcp.servers / skills / commands / deps
  skills/<skill-name>/SKILL.md # optional: a standalone skill shipped by the recipe
  commands/<cmd-name>/...      # optional: a standalone command
```

Worked examples in this repo:

- `recipes/time/` — the tracer bullet: one **stdio** MCP server (`command: uvx`, `args: [mcp-server-time]`, `transport: stdio`) + one standalone skill (`skills/time-helper`). Network-free, credential-free.
- `recipes/ping/` — a **service reference**: no `command`, just `service: ping` + `transport: http`. The assembler resolves it to a hatago URL-proxy entry pointing at the running sidecar.
- `recipes/greet/` — the file-extension-only analog: a standalone skill, no MCP server (proves multi-recipe composition in `stacks/claude-multi`).
- `recipes/omp/` — a contract-only recipe: declares the `claude-hooks-bridge` extension dependency (the bridge itself is baked into `harnessed-omp`).
- `recipes/gstack/`, `recipes/codex/`, `recipes/gemini/`, `recipes/opencode/`, `recipes/antigravity/` — further recipe examples.

**Key schema points** (`tools/harnessed/schema.py`): `transport` is **explicit** (stdio = hatago
child, http = network-native); skills/commands are fanned by **leaf name** and **fail fast on
collision**; `validate_no_raw_npm` rejects raw `npm`/`npx` and points at the pnpm equivalent. See
`docs/guides/recipe-authoring.md`.

### `stacks/` — authored stack manifests

A **stack** composes one harness + a chosen set of recipes + (optional) services.

```
stacks/<name>/stack.yaml
```

Key fields (`tools/harnessed/schema.py` `Stack`): `name`, `config: isolated|transparent`,
`harness: claude|omp|opencode|gemini|antigravity|codex` (exactly one, omitted for transparent),
`recipes: [...]`, `services: [...]`, `permissions: prompt|yolo`, `state: { persist, session_state }`.

Worked examples:

- `stacks/tracer-time/stack.yaml` — the Phase 2 tracer: `config: isolated`, `harness: claude`, `recipes: [time]`.
- `stacks/transparent/stack.yaml` — the built-in host-mirror: `config: transparent`, `harness` omitted.
- `stacks/ping-time/stack.yaml` — `recipes: [time, ping]` + `services: [ping]` (multi-recipe + a shared sidecar).
- `stacks/omp-time/`, `stacks/opencode-time/`, `stacks/gemini-time/`, `stacks/antigravity-time/`, `stacks/codex-time/` — the same `time` recipe across the other five harnesses (one canonical profile, six harnesses).
- `stacks/claude-multi/` — two recipes on claude (proves multi-recipe composition).

**Naming convention:** `<harness>-<flavor>` for proof stacks (`<harness>-time`, `<harness>-multi`);
descriptive for real stacks. Scaffold a new stack with `harnessed new <stack> --harness <h> --recipes a,b`.

### `services/` — shared sidecar services

A **shared service** is its own image/container/volume, host-published, lifecycle independent of any
instance (design §3, §9). Attached by reference from a stack's `services:` list.

```
services/<name>/
  service.yaml    # required: name, image, volume, port, healthcheck
  Dockerfile      # the service image
  server.py       # the MCP server (FastMCP streamable-http; host: 0.0.0.0:<port>)
```

Worked example — `services/ping/`:

- `services/ping/service.yaml` — `name: ping`, `image: harnessed-ping:latest`, `volume: ping-data`,
  `port: 8080`, `healthcheck: "curl -sf http://localhost:8080/health || exit 1"`.
- `services/ping/Dockerfile` — builds the service image.
- `services/ping/server.py` — a FastMCP streamable-http service exposing one `ping` tool on `:8080`
  plus a `/health` route. **Load-bearing detail:** it adds `host.containers.internal` to
  `TransportSecuritySettings.allowed_hosts` so hatago's proxy over the podman host gateway isn't
  rejected as a DNS-rebinding attack (421 Misdirected Request). See `docs/guides/service-authoring.md`.

A service volume is **service-scoped** (`<service>-data`) and survives `svc down`; `--purge`
destroys it. Manage with `harnessed svc up|down|list <service>`.

### `profiles/` — generated + committed output

The assembler writes `profiles/<stack>/` (`tools/harnessed/emit.py`). **Committed and
version-controlled** — it is the source of truth mounted into the isolated harness container.

```
profiles/<stack>/
  .claude/
    .mcp.json            # exactly ONE entry → hatago (http://localhost:3535/mcp)
    settings.json        # pre-approves the hatago hub's MCP tools
    skills/<name>/       # fanned from each recipe's skills/
    commands/<name>/     # fanned from each recipe's commands/
    agents/ hooks/ rules/
  hatago.config.json     # declares each MCP server as a hatago child/proxy
  baked-servers.json     # the stdio servers the hatago image must bake
```

Example — `profiles/ping-time/.claude/.mcp.json`:
```json
{ "mcpServers": { "hatago": { "type": "http", "url": "http://localhost:3535/mcp" } } }
```

**Never edit by hand.** Regenerate with `harnessed build <stack>`. The profile dir is wiped and
re-emitted on each build (`emit.reset_profile`) so emission is fully reproducible.

### `web/` — Astro marketing/docs site

A pnpm-managed Astro site (not part of the runtime). `web/astro.config.mjs`,
`web/package.json`, `web/pnpm-workspace.yaml`, `web/src/{components,data,layouts,pages,styles}/`,
`web/public/`. The build is independent of the harnessed engine.

### `systemd/` — user units for the nightly rescan

- `systemd/harnessed-rescan.timer` — `OnCalendar=daily`, `Persistent=true`; its `ExecStart` is
  `%h/.local/bin/harnessed rescan`.
- `systemd/harnessed-rescan.service` — the matching service unit.

**Prerequisite:** `loginctl enable-linger $USER` or the timer does not fire while logged out. Copy to
`~/.config/systemd/user/` and `systemctl --user enable --now harnessed-rescan.timer`.

### `docs/` — design + guides + codebase map

- `docs/harnessed-design.md` — the authoritative design spec (the *why*).
- `docs/guides/` — `recipe-authoring.md`, `stacks.md`, `service-authoring.md`, `secrets.md`,
  `troubleshooting.md`.
- `docs/prompts/` — authoring prompts.
- `docs/codebase/` — this structured map (architecture, structure, conventions, tech, concerns).

> Note: `DESIGN.md` at the repo root is **stale/unrelated** (a MiniMax design-system spec). The
> authoritative design reference is `docs/harnessed-design.md`; project instructions live in
> `CLAUDE.md` / `AGENTS.md`.

---

## Naming conventions (summary)

- **Instance/pod:** `harnessed-<stack>-<projhash>` — `generate_instance_name`
  (`lib/harnessed-common.sh:289-300`). Identity is stack + project path, so the same stack runs
  across projects without recreate.
- **Images:** `harnessed-<thing>:latest` (`harnessed-base`, `harnessed-claude`, `harnessed-hatago`,
  `harnessed-tools`, `harnessed-<service>`). Harness images are lazy-built.
- **Service containers/volumes:** labelled `harnessed-service=<name>`; volume `<service>-data`.
- **Lib modules:** `lib/harnessed-<concern>.sh`.
- **Functions:** snake_case, namespaced (`svc_up`, `rt_group_create`, `harnessed_isolated`,
  `ensure_images`).
- **In-container home:** `/home/harnessed` (`CONTAINER_HOME`); project mounted at
  `/home/harnessed/<relpath>` for a legible Claude session slug.
- **hatago endpoint:** `http://localhost:3535/mcp` (the single MCP entry every harness sees).

---

## Where to add new code

### Add a new recipe

1. `mkdir recipes/<name>/` and author `recipes/<name>/recipe.yaml` (copy the shape from
   `recipes/time/recipe.yaml`). Set `name`; add `mcp.servers` (stdio `command`/`args`/`transport`, or
   a `service:`/`url` http ref) and/or `skills`/`commands` (`path: skills/<leaf>`).
2. If shipping a standalone skill, add `recipes/<name>/skills/<leaf>/SKILL.md`. The assembler fans it
   to `.claude/skills/<leaf>` and **fails fast on collision**.
3. Reference it from a stack: add `<name>` to a `stacks/<stack>/stack.yaml` `recipes:` list (or
   `harnessed new <stack> --recipes ...,<name>`).
4. `harnessed build <stack>` to regenerate the profile; `harnessed test <stack>` for the capability
   report.

Rules: **pnpm everywhere** (no raw `npm`/`npx` — `validate_no_raw_npm` fails the build); `uvx` for
light Python MCP servers; `transport` is always explicit. See `docs/guides/recipe-authoring.md`.

### Add a new stack

1. Scaffold: `harnessed new <stack> --harness <claude|omp|opencode|gemini|antigravity|codex> --recipes a,b`
   (writes `stacks/<stack>/stack.yaml`; refuses overwrite; validates `--harness`; warns — doesn't
   fail — on a missing recipe dir).
2. Set `config: isolated`; list `recipes:` and (optional) `services:`.
3. `harnessed build <stack>` → `harnessed <stack>` to run; `harnessed install <stack>` writes a
   `~/.local/bin/<stack>` launcher shim to launch by name from any cwd.

See `docs/guides/stacks.md`.

### Add a new shared service

1. `mkdir services/<name>/` and add `service.yaml` (`name`, `image`, `volume`, `port`,
   `healthcheck`), a `Dockerfile`, and the server (`server.py`, a FastMCP streamable-http app on
   `0.0.0.0:<port>` with a `/health` route).
2. **Add `host.containers.internal` to `TransportSecuritySettings.allowed_hosts`** so hatago's proxy
   over the podman host gateway isn't rejected (canonical: `services/ping/server.py:19-25`).
3. Reference it from a recipe (`mcp.servers: [{ name, service: <name>, transport: http }]`) and add
   the service to a stack's `services:` list. The isolated launcher auto-starts it
   (`ensure_service_up`).
4. Manage with `harnessed svc up|down|list <name>`; the volume (`<name>-data`) survives `down`.

See `docs/guides/service-authoring.md`.

### Add a new harness base image

1. Add `base/Dockerfile.harnessed-<harness>` as `FROM harnessed-base:latest` + the harness install +
   any image-baked MCP config pointing at hatago (`http://localhost:3535/mcp`).
2. Add the image constant + a lazy `ensure_<harness>_image` builder in
   `lib/harnessed-common.sh`, and an `HARNESSED_<HARNESS>_IMAGE` var.
3. Add `"<harness>": ".claude"` to `HARNESS_CONFIG_DIR` in `tools/harnessed/schema.py` (every harness
   consumes the **same** Claude-canonical profile).
4. Wire the harness branch in `lib/harnessed-isolated.sh` (image selection + the attach command) and
   the `harnessed new` `--harness` validation in `harnessed`/`lib/harnessed-cli.sh`.
5. Add a proof stack `stacks/<harness>-time/` and extend the harness-matrix UAT (`tools/uat/phase-06.sh`).

Remember: **one harness per stack**, and `FROM` is lineage only — never try to bake two harness
systems into one image (compose them at runtime in a pod instead).

### Extend the host bash engine

Add a new concern as `lib/harnessed-<concern>.sh` with a header documenting its contract, source it
just-in-time from the relevant dispatch arm in `harnessed`, and keep it host-native (no Python). For
new mount logic that applies to *all* stacks, extend `lib/harnessed-mounts.sh` (the §4a layer); for
config-mode-specific logic, extend the per-mode launcher.

### Extend the assembler (Python)

Parse new fields in `tools/harnessed/schema.py`, orchestrate in `tools/harnessed/assemble.py`, emit
in `tools/harnessed/emit.py`. Keep pure logic (no subprocess) separate from the podman-touching code
so it stays unit-testable. The capability test (`tools/harnessed/capability.py`) is the oracle — wire
the wrong thing and it fails.

## See also

- `docs/codebase/ARCHITECTURE.md` — the layered wiring, config-mode split, runtime composition.
- `docs/harnessed-design.md` — the authoritative design decisions (§2–§9 confirmed; §10–§13 schemas).
- `docs/guides/` — step-by-step authoring guides.
