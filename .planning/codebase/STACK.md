# Technology Stack

**Analysis Date:** 2026-06-24

## Languages

**Primary:**
- Bash — Host bootstrap (`harnessed`, `install.sh`) and all shell library modules (`lib/*.sh`). Dependency-free; podman/docker is the only host requirement.
- Python 3.12 / 3.13 — `harnessed-tools` image: the build-time assembler (`tools/`) and the `ping` shared service (`services/ping/server.py`).
- JavaScript / TypeScript — Harness CLIs (Claude Code, Codex, Gemini, opencode), the hatago MCP hub, and recipe JS deps; managed via pnpm inside images.

**Secondary:**
- YAML — Stack and recipe definition format (`stacks/*/stack.yaml`, `recipes/*/recipe.yaml`), parsed by ruamel.yaml.
- TOML — codex config baked into `harnessed-codex` image (`~/.codex/config.toml`).
- JSON — hatago config output (`hatago.config.json`), gemini/opencode baked configs, osv-scanner output.

## Runtime

**Container engine (host — the only host dependency):**
- Podman ≥ 5.6, current 5.8.2 (rootless, preferred). Falls back to Docker if podman is not found.
- Rootless podman pods provide shared network namespace for harness + hatago containers.
- No API socket mounted inside containers; all podman commands run host-side.

**Base image OS:**
- Ubuntu 24.04 (`harnessed-base`, `harnessed-tools` uses `python:3.13-slim`)

**Tool manager (in-image):**
- `mise` (calendar-versioned, 2026.x) — installs and shims node, python, pnpm, fd, ripgrep, and harness-specific CLIs inside all images derived from `harnessed-base`.

**Package Manager (JS):**
- `pnpm@11` — the only JS package manager; governed by managed supply-chain policy in `lib/pnpm/config.yaml` (COPY'd into every image).
- Policy: `minimumReleaseAge: 1440`, `minimumReleaseAgeStrict: true`, `blockExoticSubdeps: true`, `verifyStoreIntegrity: true`, `strictDepBuilds: true`.
- Per-project `allowBuilds` goes in `tools/pnpm-workspace.yaml` (not global config).
- No npm or npx anywhere in the project.

**Package Manager (Python):**
- `uv` 0.11.8 — installed via the official shell installer into `harnessed-hatago` image; manages Python deps and runs Python MCP servers via `uvx`.
- `pip` — used only in the `harnessed-tools` image for the assembler's own install (`pip install --no-cache-dir .`).

## Frameworks

**Core (Python assembler — `tools/`):**
- `rich` ≥14,<15 — terminal rendering for capability reports and build output.
- `ruamel.yaml` ≥0.18,<0.19 — YAML parse/emit with round-trip comment preservation for recipe and stack manifests.
- `pip-audit` 2.10.1 — credential-free Python dependency audit; part of the supply-chain scan gate.

**MCP Layer:**
- `@himorishige/hatago-mcp-hub` 0.0.16 (pnpm global, `harnessed-hatago` image) — aggregates all stack MCP servers behind a single Streamable-HTTP endpoint on `:3535`.
- `mcp-server-time` 2026.6.4 (uvx, baked into `harnessed-hatago`) — tracer-bullet stdio MCP server for time/timezone queries; spawned as hatago child.
- `fastmcp` (mcp Python SDK) — used by `services/ping/server.py` for the ping tracer shared service.

**Build/Dev:**
- `osv-scanner` 2.3.8 (static Go binary, `harnessed-tools` image) — credential-free CVE scan of lockfiles and images at build time; HIGH threshold gate (CVSS ≥ 7.0).
- `snyk` (pnpm global, token-gated) — `snyk test --severity-threshold=high` on npm/pnpm trees; warn-and-skip without token.
- `socket` CLI (token-gated) — optional supply-chain behavioral signals; warn-and-skip without token.
- `jq` (system package, `harnessed-tools` image) — JSON shaping of emitted artifacts.
- `yq` (mikefarah Go binary) — YAML/JSON munging in shell assembler glue.

## Key Dependencies

**Critical:**
- `@himorishige/hatago-mcp-hub@0.0.16` — the MCP aggregation hub; every stack's harness reaches MCP capabilities exclusively through it at `http://localhost:3535/mcp`.
- `ruamel.yaml>=0.18` — parses all recipe and stack manifests; the assembler's data contract.
- `rich>=14` — the sole terminal rendering library; used in capability reports.

**Infrastructure:**
- `pip-audit==2.10.1` — locked version; part of the non-optional build gate alongside osv-scanner.
- `1password-cli` (op) + `1password` desktop app — installed via official apt repo in `harnessed-base` and `harnessed-tools` images; `op` binary only (no desktop app) in `harnessed-tools`.
- `varlock` (`dmno-dev/varlock`) — opt-in secrets layer; inert unless `~/.config/harnessed/.env.schema` exists.

## Configuration

**Environment:**
- No host `.env` file. Credentials are env-only, injected at launch.
- Optional varlock + 1Password for `op://` secret resolution (`harnessed auth snyk|socket` for scanner tokens).
- `HARNESSED_DIR` — set by `harnessed` bootstrap to the resolved repo directory.
- `CONTAINER_HOME=/home/harnessed` — in-container home for all harness images.
- `HARNESSED_NET` — opt-in bridge network name for bridge-capable hosts; default is `host.containers.internal` via pasta networking.
- `NO_FIREWALL` — set to `true` to skip egress firewall (default: `false`).
- `XDG_CACHE_HOME=/opt/osv-cache` — offline OSV database location in `harnessed-tools` image.

**Build:**
- `base/Dockerfile.harnessed-base` — lineage root; all harness images build `FROM` this.
- `base/Dockerfile.hatago` — MCP hub image; `FROM harnessed-base`.
- `base/Dockerfile.harnessed-{claude,omp,opencode,gemini,antigravity,codex}` — per-harness images; each `FROM harnessed-base`.
- `tools/Dockerfile` — assembler image; `FROM python:3.13-slim` (independent lineage).
- `lib/pnpm/config.yaml` — master pnpm supply-chain policy; COPY'd into every image.
- `tools/pnpm-workspace.yaml` — project-scoped `allowBuilds` (snyk only); COPY'd into tools image.

## Platform Requirements

**Development (host):**
- Podman ≥ 5.6 (rootless) or Docker. `loginctl enable-linger $USER` required for rootless socket persistence.
- `git` — for `install.sh` repo clone.
- No host Python, Node, or uv required.

**Production / Deployment:**
- Local only. Stacks run as podman pods on the user's own machine.
- Each stack = one pod (`harnessed-<stack>-<projhash>`) containing harness container + hatago container.
- Shared services (e.g., ping) run as standalone containers outside the pod, host-published on fixed ports.

---

*Stack analysis: 2026-06-24*
