# Technology Stack

**Analysis Date:** 2026-06-27

## Languages

**Primary:**
- Python 3.12 — all host-side CLI logic in `src/harnessed/` (launcher, assembler, schema parser, scan gate, capability test)
- Bash — host bootstrap script; `catalog/base/harnessed-scan` in-image scan runner

**Secondary (in-image, managed by mise):**
- Node.js 22 LTS — JS package manager (pnpm) + hatago hub + gemini/codex/omp harness CLIs
- Go 1.24 — in-image via mise; osv-scanner static binary uses Go toolchain at build
- Rust 1.87 — in-image via mise (available to recipes that need it)
- Bun 1.2 — in-image via mise (required by omp plugins; omp extensions are Bun-based)

## Runtime

**Host Environment:**
- Podman (rootless) ≥ 5.6, current 5.8.2 — the only required host dependency
- Rootless `podman.socket` (`unix:///run/user/$UID/podman/podman.sock`) for Docker-out-of-Docker

**In-image Runtime Manager:**
- mise (mise-en-place, 2026.x rolling) — manages node, python, pnpm, bun, rust, go, fd, ripgrep, and extra-tools inside `harnessed-base` image
- Config: `catalog/base/Dockerfile.harnessed-base` (the `mise use -g` layer)

**Package Manager:**
- uv 0.11.8 (astral) — Python dep management + `uvx` for stdio MCP servers
- Lockfile: `uv.lock` (present, committed)
- pnpm 11 — JS package management inside images; routes through mise's `npm.package_manager=pnpm` hook

## Frameworks

**Core (Python CLI):**
- Typer 0.12.x — CLI framework for `harnessed` launcher (`src/harnessed/launcher.py`) and `harnessed-tools` assembler (`src/harnessed/cli.py`)
- rich 14.x — terminal rendering for capability reports, build output, tables (`src/harnessed/report.py`)

**Testing:**
- pytest 8.x — test runner; config in `pyproject.toml` (`[tool.pytest.ini_options]`)
- pytest-cov — coverage reporting

**Build:**
- setuptools ≥ 68 — Python build backend (`pyproject.toml` `[build-system]`)
- Two entry points: `harnessed` (launcher) and `harnessed-tools` (assembler only)

## Key Dependencies

**Critical Python:**
- `ruamel.yaml 0.18.x` — YAML parsing for `recipe.yaml`, `stack.yaml`, `service.yaml`, `agent.yaml` (`src/harnessed/schema.py`)
- `typer 0.12.x` — CLI surface for both entry points
- `rich 14.x` — all terminal output
- `pip-audit 2.10.1` — Python supply-chain scan gate (credential-free; always-on baseline)

**Dev:**
- `pytest ≥ 8`, `pytest-cov` — testing only; listed in `[project.optional-dependencies]` dev group

**In-image (baked):**
- `@himorishige/hatago-mcp-hub 0.0.16` — MCP hub, installed via `pnpm add -g` in `catalog/base/Dockerfile.hatago`
- `mcp-server-time 2026.6.4` — tracer stdio MCP server, installed via `uv tool install` in hatago image
- `osv-scanner` (Google, V2 2.3.x) — image/source vulnerability scan; Go static binary, credential-free
- `snyk` — JS/Python supply-chain scan; installed via `pnpm add -g` in `catalog/base/Dockerfile.harnessed-base`; token-gated, warn-and-skip without `SNYK_TOKEN`
- `mcp[cli]` (FastMCP) — used by `catalog/services/ping/Dockerfile` for the tracer shared service

**Extra in-image CLI tools** (via `extra-tools.txt`, installed by mise):
- `bat`, `eza`, `sd`, `dua`, `gping` — modern CLI replacements
- `jq`, `jless`, `glow`, `hexyl`, `yq` — data processing
- `lazygit` — git TUI
- `ast-grep`, `ruff`, `stylua`, `markdownlint-cli2` — code tooling

## Configuration

**Environment:**
- No `.env` file; secrets are strictly env-at-launch or resolved via varlock + 1Password
- Optional schema at `~/.config/harnessed/.env.schema` (uses varlock DSL; `@plugin(@varlock/1password-plugin@1.2.0)`)
- Example: `extra-tools.default.txt` and `extra-tools.txt` control which extra mise tools are baked into the image

**Build:**
- `pyproject.toml` — Python project config, deps, entry points, pytest config
- `uv.lock` — Python lockfile
- `pnpm-workspace.yaml` — project-level JS supply-chain allowlist (`allowBuilds: {snyk: true}`)
- `catalog/base/pnpm/config.yaml` — global pnpm supply-chain policy baked into every image:
  - `minimumReleaseAge: 1440` (1 day hold)
  - `minimumReleaseAgeStrict: true`
  - `blockExoticSubdeps: true`
  - `verifyStoreIntegrity: true`
  - `strictDepBuilds: true` (lifecycle default-deny)
- JSON schemas for manifest validation: `schemas/recipe.schema.json`, `schemas/stack.schema.json`, `schemas/service.schema.json`, `schemas/agent.schema.json`
- Nightly re-scan timer: `systemd/harnessed-rescan.timer` + `systemd/harnessed-rescan.service`

## Image Hierarchy

```
ubuntu:24.04
  └── harnessed-base (mise + node@22 + pnpm@11 + python@3.12 + bun@1.2 + rust@1.87 + go@1.24 + scanners)
        ├── harnessed-claude   (curl claude.ai/install.sh)
        ├── harnessed-omp      (mise: github:can1357/oh-my-pi; omp plugin install @drmikecrowe/omp-claude-hooks-bridge)
        ├── harnessed-opencode (curl opencode.ai/install; baked ~/.config/opencode/opencode.json)
        ├── harnessed-gemini   (mise: npm:@google/gemini-cli; baked ~/.gemini/settings.json)
        ├── harnessed-codex    (mise: npm:@openai/codex; baked ~/.codex/config.toml)
        ├── harnessed-antigravity (curl antigravity.google/cli/install.sh; baked ~/.gemini/config/mcp_config.json)
        └── harnessed-hatago   (pnpm: @himorishige/hatago-mcp-hub@0.0.16; uv: mcp-server-time; EXPOSE 3535)

python:3.12-slim
  └── harnessed-ping (service image; pip install mcp[cli]; EXPOSE 8080)
```

## Platform Requirements

**Development (host):**
- Podman ≥ 5.6 (rootless); `systemctl --user enable --now podman.socket`; `loginctl enable-linger $USER`
- Python 3.12 + uv (for running `harnessed` and `harnessed-tools` on host)

**Production/Run:**
- Same as development — single-user local tooling
- All other dependencies (node, python runtimes, scanners) live inside images

---

*Stack analysis: 2026-06-27*
