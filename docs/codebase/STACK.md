# Technology Stack

**Analysis Date:** 2026-06-17

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
  `lib/egress-firewall.sh`). Bash was chosen because every podman/docker call is
  a host-native shell command — no runtime to install, no version roulette
  (`docs/harnessed-design.md` §15). `set -euo pipefail` is the baseline
  (`harnessed:25`).

- **Python ≥ 3.12** — the assembler. All assembly logic lives in
  `tools/harnessed/*.py` and runs in a `python:3.13-slim` image
  (`tools/Dockerfile:13`). The host NEVER runs this Python directly for a build;
  the launcher `podman run`s the `harnessed-tools` image
  (`lib/harnessed-common.sh:106-108`). The one host-Python code path is
  `harnessed test <stack>`, which resolves deps via `uv run --with ruamel.yaml
  --with rich` first (`harnessed:316-318`) so the persistent host surface stays
  "podman only."

**Secondary:**

- **YAML manifests** — the declarative inputs and policy:
  `stacks/<name>/stack.yaml`, `recipes/<name>/recipe.yaml`,
  `services/<name>/service.yaml`, and `lib/pnpm/config.yaml`. Parsed with
  `ruamel.yaml` `typ="safe"` (`tools/harnessed/schema.py:23-25`).
- **Dockerfile** — image lineage. `FROM` is **lineage only** (design §6):
  `base/Dockerfile.harnessed-base` → `base/Dockerfile.harnessed-claude`,
  `base/Dockerfile.harnessed-omp`, `base/Dockerfile.hatago`. Plus
  `tools/Dockerfile` (assembler), `services/ping/Dockerfile` (sidecar), and the
  legacy root `Dockerfile` (the old `container` SKU, superseded by
  `harnessed-base`).
- **Python for service sidecars** — `services/ping/server.py` is a FastMCP
  streamable-http server (see INTEGRATIONS.md).

## Runtime

- **Container runtime: podman (preferred) or docker (fallback).** Detection is
  the launcher's first act:

  ```bash
  # lib/harnessed-common.sh:31-40
  detect_runtime() {
      if command -v podman >/dev/null 2>&1; then
          CONTAINER_RUNTIME="podman"
      elif command -v docker >/dev/null 2>&1; then
          CONTAINER_RUNTIME="docker"
      else
          print_error "Neither podman nor docker found on PATH. Install podman (recommended) or docker."
          exit 1
      fi
  }
  ```

  Every subsequent image/container/pod call uses `"$CONTAINER_RUNTIME"`, so the
  launcher is runtime-agnostic. **Rootless by default**: every instance runs
  `--userns=keep-id` and `--cap-add NET_ADMIN` (set once in
  `lib/harnessed-mounts.sh:15`, reused by all stacks). Isolated stacks are a
  **podman pod** (`pod create --userns=keep-id`, `lib/harnessed-isolated.sh:127`)
  so the harness container and hatago share a netns.

- **Lockfiles:** none for the host (it's dependency-free Bash). The assembler's
  dependency lock is `tools/pyproject.toml`; image-level pins live as
  `ARG *_VERSION=` lines in each Dockerfile.

### Package managers (multiple, by design)

The repo uses **four** distinct package managers, each scoped to its layer:

| Manager | Scope | Where |
|---|---|---|
| **mise** | in-image toolchain versions (node, python, pnpm, fd, ripgrep, harness CLIs) | `base/Dockerfile.harnessed-base:51,68-80`; `base/Dockerfile.harnessed-omp:20` |
| **pnpm @11** | all JavaScript installs (global, per-recipe, hatago bundled) — **never npm/npx** | policy at `lib/pnpm/config.yaml`; enforced via `mise settings set npm.package_manager pnpm` (`base/Dockerfile.harnessed-base:69`) |
| **uv / uvx** (astral) | Python stdio MCP servers + ephemeral `--with` deps for the capability test | `base/Dockerfile.hatago:16-17,39`; `harnessed:316-318` |
| **pip** | the assembler's own deps (installed from `tools/pyproject.toml` at image build) | `tools/Dockerfile:23` |
| **apt** | system packages in every Ubuntu-based image | all `Dockerfile.*` |

There is **no `.tool-versions`, `mise.toml`, or `.mise.toml`** at the repo root —
mise is configured **inside the images** via `mise settings set` +
`mise use -g`, not via a project-local config. The only mise-related host
artifacts are the generated per-image `~/.config/mise/config.toml`
(`base/Dockerfile.harnessed-base:80`) and `extra-tools.txt`, which lists
additional mise-managed CLI tools (`bat`, `eza`, `jq`, `lazygit`, `ast-grep`,
`ruff`, …) grafted in at build time (`base/Dockerfile.harnessed-base:87-89`).

## Key Dependencies

### Critical (the assembler depends on these)

From `tools/pyproject.toml:10-14`:

- **`ruamel.yaml` `>=0.18,<0.19`** — the only YAML parser. Used in
  `tools/harnessed/schema.py` to load every manifest into typed dataclasses
  (`Recipe`, `Stack`, `ServiceDef`, `McpServer`, `FileExt`). The pin matters:
  the recipe lint (`validate_no_raw_npm`, `schema.py:296`) regex-walks raw
  manifest strings, and emit/scan depend on the parsed shape.
- **`rich` `>=14,<15`** — terminal rendering. The capability report is rendered
  as a markdown table through `rich.markdown.Markdown`
  (`tools/harnessed/report.py:30-47`); `--json` bypasses rich for clean CI
  stdout. `rich.console.Console` is threaded through the CLI
  (`tools/harnessed/cli.py:17`).
- **`pip-audit` `==2.10.1`** — the Python half of the always-on supply-chain
  gate (BLD-02). Pinned exactly because its JSON schema drives
  `scan.py:_audit_pip`. Runs against any `requirements.txt` in a recipe dir or
  emitted profile (`scan.py:222-223`).

### Infrastructure (baked into images, pinned)

- **`osv-scanner` v2.3.8** — a static Go binary, the source/image half of the
  supply-chain gate. Pinned to a GitHub release and **checksum-verified against
  the release `SHA256SUMS` before `chmod +x`** (threat T-03-05). The offline OSV
  DB is pre-seeded per-ecosystem so scans run deterministically with no network
  hit at scan time (`tools/Dockerfile:37-55`). Invoked offline:
  `osv-scanner scan source --offline --offline-vulnerabilities` and `scan image
  --archive` (`tools/harnessed/scan.py:169,241`).
- **`mise`** — the runtime manager inside every `harnessed-*` image. Installed
  from `https://mise.run` (`base/Dockerfile.harnessed-base:51`); shims go on
  PATH (`:52`); `experimental=true` + `npm.package_manager=pnpm` are set before
  `mise use -g` (`:68-69`) so the `npm:` harness CLIs route through pnpm.
- **`pnpm` @11** — required (not `@latest`) so the **v11** supply-chain defaults
  are in effect (Node 22+, `base/Dockerfile.harnessed-base:71`). Policy lives in
  `lib/pnpm/config.yaml` and is COPY'd into `~/.config/pnpm/config.yaml` in
  every image that runs pnpm.
- **1Password CLI (`op`) + desktop app** — installed from 1Password's apt repo
  in `base/Dockerfile.harnessed-base:27-33` and the legacy root `Dockerfile`.
  Primary use today is `op-ssh-sign` for SSH commit signing; optional secrets
  resolution via varlock (§16) is opt-in.
- **`uv` / `uvx` `0.11.8`** — astral's Python tool runner. Pinned
  (`base/Dockerfile.hatago:16-17`). `uv tool install` bakes `mcp-server-time`
  into the hatago image so the stdio child resolves offline at run time
  (`base/Dockerfile.hatago:38-39`).

### The managed pnpm supply-chain config

`lib/pnpm/config.yaml` is the **single source of truth** for the JS supply-chain
policy (BLD-01). It is intentionally v11-shaped — the removed v10 keys
(`onlyBuiltDependencies`, etc.) are absent, and `allowBuilds` is deliberately
**not** set globally (pnpm v11 rejects it from global config; it is
project-scoped in `pnpm-workspace.yaml`). What IS set:

```yaml
# lib/pnpm/config.yaml:13-17
minimumReleaseAge: 1440          # minutes (1 day). v11 default; explicit so it is auditable.
minimumReleaseAgeStrict: true    # fail-closed rather than silently falling back.
blockExoticSubdeps: true         # block git/tarball/non-registry subdeps.
verifyStoreIntegrity: true       # content-addressed store integrity check on link.
strictDepBuilds: true            # lifecycle default-deny: non-zero exit on any unreviewed build/postinstall.
```

The `container` (legacy), `harnessed-base`, and `hatago` images all COPY this
file; the assembler image (`tools/Dockerfile:60-62`) intentionally does **not** —
it is emit-only Python with no JS installs.

## Configuration Approach

Three distinct config layers — keep them straight:

1. **Declarative manifests** (authored inputs, parsed forward per design D-14):
   - `stacks/<name>/stack.yaml` — harness + recipe list + optional
     `services`/`permissions`/`state`. Schema in `schema.py:load_stack`.
   - `recipes/<name>/recipe.yaml` — MCP servers + skills/commands/agents/hooks +
     optional deps/extensions. Schema in `schema.py:load_recipe`.
   - `services/<name>/service.yaml` — sidecar image/volume/port/healthcheck.
     Schema in `schema.py:load_service`.

2. **Committed profile output** (generated, then committed):
   `profiles/<stack>/.claude/{skills,commands,agents,hooks,rules}/` +
   `hatago.config.json` + `baked-servers.json`. Emitted by
   `tools/harnessed/emit.py`; mounted read-only into the harness container at
   run time. See `profiles/tracer-time/` for a worked example.

3. **GSD planning config** — `.planning/config.json` configures the
   `get-shit-done` workflow that built this repo (model profile, branching,
   security enforcement `block_on: high`, phase naming). It is a **build
   process** config, not a harnessed runtime config.

### Secrets

**The default path is zero-config and token-free.** Secrets are an **opt-in**
layer (design §16):

- **varlock + 1Password** are OPTIONAL. The repo ships a ready-to-copy
  template, `.env.schema.example`, using the `@env-spec` DSL with the
  `@varlock/1password-plugin@0.3.2` plugin, `@initOp(allowAppAuth=true)`, and
  `op(op://Private/Snyk/credential)` / `op(op://Private/SocketDev/credential)`
  refs for `SNYK_TOKEN` / `SOCKET_SECURITY_API_KEY` (copy to
  `~/.config/harnessed/.env.schema`; per-service to
  `~/.config/<service>/.env.schema`). When a schema is present, resolution runs **on the host** —
  `resolve_secret_env` (`lib/harnessed-secrets.sh`) calls `varlock load --format env` and spreads the
  resolved dotenv into the container as a mode-0600 temp `--env-file` (unlinked after launch).
  App-auth works on the host because the 1Password desktop app authorizes the calling terminal; an
  in-container `op` has no host app to bind the grant to (the `agent.sock` mount is the **SSH agent**,
  not the op app-auth transport). This reaches the isolated pod, the transparent instance, sidecar
  services, and the build scan — resolved values stay **env only**, never written to a repo file,
  committed profile, or image layer. Hosts without `varlock` fall back to in-container resolution,
  which then needs `OP_SERVICE_ACCOUNT_TOKEN`.

- **Claude OAuth** is the one secret that always flows, and only as a
  **read-only bind mount**: `~/.claude/.credentials.json`
  (`lib/harnessed-isolated-config.sh:31-33`). A generated, token-free
  `~/.claude.json` stub (`isolated-config.sh:57-67`) carries only onboarding
  fields — the host whole-file blob is NEVER mounted (T-02-04/T-02-05).

- **1Password SSH agent** is the default signing path:
  `~/.1password/agent.sock` → `$CONTAINER_HOME/.1password/agent.sock`, exported
  as `SSH_AUTH_SOCK` (`lib/harnessed-mounts.sh:23-27`).

Use varlock when you want validated, typed, AI-safe secret refs; use plain `op
run -- <cmd>` or loose env if you don't want the schema layer. See INTEGRATIONS.md
for the full mount and secret-resolution picture.
