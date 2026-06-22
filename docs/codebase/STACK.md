# Technology Stack

**Analysis Date:** 2026-06-22

`harnessed` is an isolated, composable harness-stack launcher. There is **no
`package.json`, `Cargo.toml`, or `go.mod` at the repo root** — the project is
deliberately polyglot and host-light. It splits cleanly into two engines:

- a **dependency-free Bash host launcher** (`harnessed` + `lib/*.sh`) that drives
  podman/docker directly on the host; and
- an **EMIT-ONLY Python assembler** (`tools/harnessed/*.py`) that runs inside the
  `harnessed-tools` container image and only reads/writes a mounted build dir —
  it never drives the daemon (no Docker-out-of-Docker; design §15 / D-12).

The only thing a user must have on the host is **podman or docker**
(`install.sh:31-33` warns if neither is found). Everything else is provisioned
inside images.

## Languages

**Primary:**

- **Bash** — the host launcher. `harnessed` is a thin bootstrap that sources
  `lib/harnessed-common.sh` and dispatches to a per-stack launcher
  (`lib/harnessed-transparent.sh`, `lib/harnessed-isolated.sh`,
  `lib/harnessed-services.sh`, `lib/harnessed-mounts.sh`,
  `lib/harnessed-isolated-config.sh`, `lib/harnessed-claude-config.sh`,
  `lib/harnessed-secrets.sh`, `lib/harnessed-rescan.sh`,
  `lib/egress-firewall.sh`). Bash was chosen because every podman/docker call is
  a host-native shell command — no runtime to install, no version roulette
  (`docs/harnessed-design.md` §15). `set -euo pipefail` is the baseline
  (`harnessed:27`).

- **Python ≥ 3.12** — the assembler. All assembly logic lives in
  `tools/harnessed/*.py` and runs in a `python:3.13-slim` image
  (`tools/Dockerfile:13`). The host NEVER runs this Python directly for a build;
  the launcher `podman run`s the `harnessed-tools` image
  (`lib/harnessed-common.sh` `ensure_tools_image` / `build_stack`). The one
  host-Python code path is `harnessed test <stack>`, which resolves deps via
  `uv run --no-project --with ruamel.yaml --with rich` first
  (`harnessed:368-377`) so the persistent host surface stays "podman only."

**Secondary:**

- **YAML manifests** — the declarative inputs and policy:
  `stacks/<name>/stack.yaml`, `recipes/<name>/recipe.yaml`,
  `services/<name>/service.yaml`, and `lib/pnpm/config.yaml`. Parsed with
  `ruamel.yaml` `typ="safe"` (`tools/harnessed/schema.py:23-25`).
- **Dockerfile** — image lineage. `FROM` is **lineage only** (design §6):
  `base/Dockerfile.harnessed-base` → six harness images
  (`base/Dockerfile.harnessed-{claude,omp,opencode,gemini,antigravity,codex}`),
  plus `base/Dockerfile.hatago`. Side images: `tools/Dockerfile` (assembler),
  `services/ping/Dockerfile` (sidecar).
- **Python for service sidecars** — `services/ping/server.py` is a FastMCP
  streamable-http server (see INTEGRATIONS.md).

## Runtime

- **Container runtime: podman (preferred) or docker (fallback), rootless by
  default.** This is the *only* host dependency. Detection is the launcher's
  first act (`detect_runtime()` in `lib/harnessed-common.sh`, sourced from
  `lib/harnessed-runtime.sh`). Every subsequent image/container/pod call uses
  `"$CONTAINER_RUNTIME"`, so the launcher is runtime-agnostic.

  - **Rootless UID mapping:** the in-container `harnessed` user (UID 1000) maps
    to the host user so bind-mounted project/profile/credential paths are owned
    correctly. This is **provider-abstracted** by `rt_userns_args()` in
    `lib/harnessed-runtime.sh`: podman rootless emits `--userns=keep-id`
    (set once in `lib/harnessed-mounts.sh:16`); rootless docker remaps uids
    daemon-side and emits nothing (`--userns=keep-id` is invalid there).
  - **Group model (isolated stacks):** the harness container and hatago **share
    a netns** so the harness reaches hatago at `http://localhost:3535/mcp` with
    no cross-container networking. The shared-netns "group" is abstracted by
    `lib/harnessed-runtime.sh`: podman → a **pod** (`pod create` + `run --pod`;
    `--userns=keep-id` is a pod-level property, stripped from member args);
    docker → a **shared-netns pair** (`--network container:<instance>-hatago`).

- **Host Python (transient):** the host never needs Python for a build (the
  assembler runs in its own image). `harnessed test <stack>` is the lone
  host-Python path; it resolves its deps via `uv` (`harnessed:368-377`) or an
  explicit `HARNESSED_PYTHON` override, never pip-installing on the host.

- **Lockfiles:** none for the host (it's dependency-free Bash). The assembler's
  dependency lock is `tools/pyproject.toml` (+ `tools/uv.lock`); image-level
  pins live as `ARG *_VERSION=` lines in each Dockerfile.

### Networking model (rootless-first)

The **default** networking is rootless **pasta**, not a bridge. Rootless bridges
are unsupported on most hosts — podman netavark returns
`create bridge: Operation not supported` (see the comment block at
`lib/harnessed-isolated.sh:23-28` and `lib/harnessed-services.sh:101-105`).
Therefore:

- **Shared services publish their port to `0.0.0.0`** and peers reach them via
  the podman host gateway **`host.containers.internal:<port>`**
  (`lib/harnessed-services.sh:71-127`, design §9). This is the **primary**
  reachability model.
- **`HARNESSED_NET=<name>` is an explicit opt-in bridge override** for
  bridge-capable hosts (DNS-by-name, `http://<service>:<port>`)
  (`lib/harnessed-isolated.sh:140-150`). It is NOT the default.
- Pod members share a netns either way, so the harness always reaches hatago at
  `localhost:$HATAGO_PORT` (default 3535).

### Package managers (multiple, by design)

The repo uses **five** distinct package managers, each scoped to its layer:

| Manager | Scope | Where |
|---|---|---|
| **mise** | in-image toolchain versions (node, python, pnpm, fd, ripgrep, harness CLIs) | `base/Dockerfile.harnessed-base:51,68-80`; each `Dockerfile.harnessed-*` |
| **pnpm @11** | all JavaScript installs (global, per-recipe, hatago bundled, scanner CLIs) — **never npm/npx** | policy at `lib/pnpm/config.yaml`; enforced via `mise settings set npm.package_manager pnpm` (`base/Dockerfile.harnessed-base:68-69`); allowlist at `tools/pnpm-workspace.yaml` |
| **uv / uvx** (astral) | Python stdio MCP servers + ephemeral `--with` deps for the capability test | `base/Dockerfile.hatago:16-17,38-39`; `harnessed:368-377` |
| **pip** | the assembler's own deps (installed from `tools/pyproject.toml` at image build) | `tools/Dockerfile:23` |
| **apt** | system packages in every Ubuntu-based image | all `Dockerfile.*` |

There is **no `.tool-versions`, `mise.toml`, or `.mise.toml`** at the repo root —
mise is configured **inside the images** via `mise settings set` +
`mise use -g`, not via a project-local config. The only mise-related host
artifacts are the generated per-image `~/.config/mise/config.toml`
(`base/Dockerfile.harnessed-base:80`) and `extra-tools.txt`, which lists
additional mise-managed CLI tools (`bat`, `eza`, `jq`, `lazygit`, `ast-grep`,
`ruff`, …) grafted in at build time (`base/Dockerfile.harnessed-base:85-89`).

## Key Dependencies

### Critical (the assembler depends on these)

From `tools/pyproject.toml:10-14`:

- **`ruamel.yaml` `>=0.18,<0.19`** — the only YAML parser. Used in
  `tools/harnessed/schema.py` to load every manifest into typed dataclasses
  (`Recipe`, `Stack`, `ServiceDef`, `McpServer`, `FileExt`). The pin matters:
  the recipe lint (`validate_no_raw_npm` in `schema.py`) regex-walks raw
  manifest strings, and emit/scan depend on the parsed shape.
- **`rich` `>=14,<15`** — terminal rendering. The capability report is rendered
  as a markdown table through `rich.markdown.Markdown`
  (`tools/harnessed/report.py`); `--json` bypasses rich for clean CI stdout.
  `rich.console.Console` is threaded through the CLI (`tools/harnessed/cli.py`).
- **`pip-audit` `==2.10.1`** — the Python half of the always-on supply-chain
  gate (BLD-02). Pinned exactly because its JSON schema drives
  `scan.py:_audit_pip`. Runs against any `requirements.txt` in a recipe dir or
  emitted profile.

### Infrastructure (baked into images, pinned)

- **`osv-scanner` v2.3.8** — a static Go binary, the source/image half of the
  supply-chain gate. Pinned to a GitHub release and **checksum-verified against
  the release `SHA256SUMS` before `chmod +x`** (threat T-03-05). The offline OSV
  DB is pre-seeded per-ecosystem so scans run deterministically with no network
  hit at scan time (`tools/Dockerfile:37-55`). Invoked offline:
  `osv-scanner scan source --offline --offline-vulnerabilities` and
  `scan image --archive` (`tools/harnessed/scan.py:170,326`).
- **`mise`** — the runtime manager inside every `harnessed-*` image. Installed
  from `https://mise.run` (`base/Dockerfile.harnessed-base:51`); shims go on
  PATH (`:52`); `experimental=true` + `npm.package_manager=pnpm` are set before
  `mise use -g` (`:68-69`) so the `npm:` harness CLIs route through pnpm.
- **`pnpm` @11** — required (not `@latest`) so the **v11** supply-chain defaults
  are in effect (Node 22+, `base/Dockerfile.harnessed-base:71`). Policy lives in
  `lib/pnpm/config.yaml` and is COPY'd into `~/.config/pnpm/config.yaml` in
  every image that runs pnpm.
- **1Password CLI (`op`) + desktop app** — installed from 1Password's apt repo
  in `base/Dockerfile.harnessed-base:27-33`; CLI-only in the tools image
  (`tools/Dockerfile:57-68`). Primary use is `op-ssh-sign` for SSH commit
  signing; optional secrets resolution via varlock (§16) is opt-in.
- **`uv` / `uvx` `0.11.8`** — astral's Python tool runner. Pinned
  (`base/Dockerfile.hatago:16-17`). `uv tool install` bakes `mcp-server-time`
  into the hatago image so the stdio child resolves offline at run time
  (`base/Dockerfile.hatago:38-39`).
- **hatago MCP hub `@himorishige/hatago-mcp-hub@0.0.16`** — pinned, pnpm global
  (`base/Dockerfile.hatago:24-35`). See INTEGRATIONS.md.

### Supply-chain scanners (committed, token-gated)

All four scanners ship in the `harnessed-tools` image (`tools/Dockerfile`):

- **`osv-scanner` 2.3.8** + **`pip-audit` 2.10.1** — credential-free, always-on
  gate (`tools/harnessed/scan.py`).
- **`snyk`** + **`socket`** (Socket.dev) — pnpm-global, **token-gated**
  (`tools/Dockerfile:116-125`). They activate only when `SNYK_TOKEN` /
  `SOCKET_SECURITY_API_KEY` is present (`scan.py:_scan_snyk:226`,
  `_scan_socket:261`); absent ⇒ warn-and-skip. One-time token setup:
  `harnessed auth snyk|socket` (`lib/harnessed-secrets.sh:130-193`).

### The managed pnpm supply-chain config

`lib/pnpm/config.yaml` is the **single source of truth** for the JS supply-chain
policy (BLD-01). It is intentionally v11-shaped — the removed v10 keys
(`onlyBuiltDependencies`, etc.) are absent, and `allowBuilds` is deliberately
**not** set globally (pnpm v11 rejects it from global config; it is
project-scoped in `tools/pnpm-workspace.yaml`). What IS set:

```yaml
# lib/pnpm/config.yaml:13-17
minimumReleaseAge: 1440          # minutes (1 day). v11 default; explicit so it is auditable.
minimumReleaseAgeStrict: true    # fail-closed rather than silently falling back.
blockExoticSubdeps: true         # block git/tarball/non-registry subdeps.
verifyStoreIntegrity: true       # content-addressed store integrity check on link.
strictDepBuilds: true            # lifecycle default-deny: non-zero exit on any unreviewed build/postinstall.
```

The `harnessed-base`, `hatago`, and `harnessed-tools` images all COPY this file
(or its five inlined keys — `tools/Dockerfile:101-103` inlines them because the
tools build context is `tools/`, not the repo root). The project-scoped
`allowBuilds` exception list lives in `tools/pnpm-workspace.yaml` (today:
`snyk: true`, because snyk's postinstall fetches its platform binary).

## Multi-Harness Support

A stack targets **exactly one** of six harnesses (design §8), selected by
`harness:` in `stacks/<name>/stack.yaml`. The canonical profile format is
Claude Code (`.claude/`); other harnesses adapt *out* of it
(`tools/harnessed/schema.py:41-48`, `HARNESS_CONFIG_DIR`):

| Harness | Image (lazy-built) | Profile consume | MCP wiring to hatago |
|---|---|---|---|
| `claude` | `harnessed-claude:latest` | native (skills/commands/agents/hooks) | `claude --mcp-config .mcp.json --strict-mcp-config` (`lib/harnessed-isolated.sh:267-270`) |
| `omp` | `harnessed-omp:latest` | Claude hooks/skills via pre-installed `claude-hooks-bridge` | via bridge → `localhost:3535` |
| `opencode` | `harnessed-opencode:latest` | `.claude/skills/**/SKILL.md` + `CLAUDE.md` natively (NOT commands/agents) | baked `~/.config/opencode` (ignores `.mcp.json`) |
| `gemini` | `harnessed-gemini:latest` | none (native format differs); profile mounted for parity | baked `~/.gemini/settings.json` `mcpServers` |
| `antigravity` (agy) | `harnessed-antigravity:latest` | none; profile mounted for parity | baked `~/.gemini/config/mcp_config.json` `serverUrl` |
| `codex` | `harnessed-codex:latest` | none (reads `AGENTS.md`); profile mounted for parity | baked `~/.codex/config.toml` `[mcp_servers.hatago]` (native streamable-HTTP) |

Non-claude harness images are **lazy-built** — `ensure_<harness>_image` runs
only when that harness stack first launches (`lib/harnessed-common.sh`,
`lib/harnessed-isolated.sh:50-55`), so claude-only users never pull omp/opencode/
gemini/antigravity/codex. Each harness has a proof stack: `stacks/{omp,opencode,
gemini,antigravity,codex}-time/` + a documenting base recipe in
`recipes/{omp,opencode,gemini,antigravity,codex}/`.

## Configuration Approach

Three distinct config layers — keep them straight:

1. **Declarative manifests** (authored inputs, parsed forward per design D-14):
   - `stacks/<name>/stack.yaml` — `name`, `config` (isolated|transparent),
     `harness` (exactly one of six), `recipes: [...]`, optional `services` /
     `permissions` / `state`. Schema in `schema.py:load_stack`.
   - `recipes/<name>/recipe.yaml` — `mcp.servers` + `skills`/`commands`/`agents`/
     `hooks` + optional `deps`/`extensions`. Schema in `schema.py:load_recipe`.
   - `services/<name>/service.yaml` — sidecar `image`/`volume`/`port`/
     `healthcheck` (flat scalars; host-parsed by `_svc_yaml_val` in
     `lib/harnessed-services.sh:32-38`). Schema in `schema.py:load_service`.

2. **Committed profile output** (generated, then committed):
   `profiles/<stack>/.claude/{skills,commands,agents,hooks,rules}/` +
   `hatago.config.json` + `baked-servers.json`. Emitted by
   `tools/harnessed/emit.py`; mounted into the harness container at run time
   (read-only at the committed layer; a per-instance copy-on-start makes it
   writable at `$XDG_STATE_HOME/harnessed/<project>/<stack>/.claude`,
   `lib/harnessed-isolated.sh:131-138`). See `profiles/tracer-time/` for a
   worked example.

3. **Policy / build configs** (not harnessed runtime):
   `lib/pnpm/config.yaml` + `tools/pnpm-workspace.yaml` (JS supply-chain),
   `tools/pyproject.toml` (assembler deps), `extra-tools.txt` (mise tool list).
   `.planning/` and `.claude/` are GSD workflow metadata, not product config.

### Secrets

**The default path is zero-config and token-free.** Secrets are an **opt-in**
layer (design §16):

- **varlock + 1Password** are OPTIONAL. The repo ships a ready-to-copy template
  (`.env.schema.example`, the `@env-spec` DSL with
  `@varlock/1password-plugin@0.3.2`, `@initOp(allowAppAuth=true)`, and
  `op(op://Private/Snyk/credential)` / `op(op://Private/SocketDev/credential)`
  refs for `SNYK_TOKEN` / `SOCKET_SECURITY_API_KEY`). Copy it to
  `~/.config/harnessed/.env.schema` (or `~/.config/<service>/.env.schema` for a
  per-service sidecar). When a schema is present, resolution runs **on the
  host** — `resolve_secret_env` (`lib/harnessed-secrets.sh:51-124`) calls
  `varlock load --format env` and spreads the resolved dotenv into the container
  as a mode-0600 temp `--env-file` (unlinked after launch, T-05-06). App-auth
  works on the host because the 1Password desktop app authorizes the calling
  terminal; an in-container `op` has no host app to bind the grant to (the
  `agent.sock` mount is the **SSH agent**, not the op app-auth transport). This
  reaches the isolated pod, the transparent instance, sidecar services
  (`lib/harnessed-services.sh:110-129`), and the build scan — resolved values
  stay **env only**, never written to a repo file, committed profile, or image
  layer. Hosts without `varlock` fall back to in-container resolution, which
  then needs `OP_SERVICE_ACCOUNT_TOKEN`.

- **Claude OAuth** is the one secret that always flows, and only as a
  **read-only bind mount**: `~/.claude/.credentials.json`
  (`lib/harnessed-isolated-config.sh`). A generated, token-free `~/.claude.json`
  stub carries only onboarding fields — the host whole-file blob is NEVER
  mounted (T-02-04/T-02-05). Harness-aware: opencode seeds via ro
  `~/.local/share/opencode/auth.json`; codex via ro `~/.codex/auth.json`.

- **1Password SSH agent** is the default signing path:
  `~/.1password/agent.sock` → `$CONTAINER_HOME/.1password/agent.sock`, exported
  as `SSH_AUTH_SOCK` (`lib/harnessed-mounts.sh:24-27`).

- **Scanner tokens** (snyk / Socket.dev) are set once via
  `harnessed auth snyk|socket` — a `--rm -it` tools container drives the vendor
  CLI's own auth so the token writes to the rw-mounted host `~/.config` (e.g.
  `~/.config/configstore/snyk.json`) and is never captured in an image layer
  (`lib/harnessed-secrets.sh:130-193`).

Use varlock when you want validated, typed, AI-safe secret refs; use plain `op
run -- <cmd>` or loose env if you don't want the schema layer. See INTEGRATIONS.md
for the full mount and secret-resolution picture.
