# Stack Research

**Domain:** Rootless-container orchestration tool (AI-coding-harness stacks: podman pods + MCP hub + supply-chain-gated build, Python-in-container CLI)
**Researched:** 2026-06-14
**Confidence:** HIGH

> Scope: the toolchain for building **harnessed** itself — the host bootstrap, the `harnessed-tools`
> Python image, the base/hatago/service images, and the build-time supply-chain gate. This is a
> greenfield tool grown on top of the existing `container` repo (Ubuntu 24.04 + mise image,
> `container.sh` host-mirror sandbox). Every choice is grounded against rootless podman, MCP-over-HTTP,
> pnpm supply-chain policy, and Claude-canonical config.

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **podman** (rootless) | ≥ 5.6, current **5.8.2** (Apr 2026) | Container/pod engine; the **only** host dependency. Runs on the **host** for both `podman build` and pod run | Native **pods** (shared netns + lifecycle) are exactly the §3 stack unit; rootless = no host root, scoped to your UID; Docker-CLI-compatible so existing `container.sh` `podman`/`docker` detection ports as-is. The `harnessed-tools` image is a build-time **assembler** that only emits a `Dockerfile` + build context + a host launcher — no API socket is mounted; the host runs podman natively. |
| **Python** | 3.12 / 3.13 | Implementation language for all `harnessed-tools` logic (parse/validate YAML, vendor, sync-links, merge hatago config, generate `.claude.json` stub, scan, emit the `Dockerfile` + build context + `~/.local/bin/<stack>` launcher) | `sync-plugin-links` prior art is already Python; rich/textual TUI is Python; pinned **inside** the image so the host needs no Python (§15). Managed by mise/uv, not the host. |
| **mise-en-place** | 2026.x (calendar-versioned, rolling) | In-image tool/runtime manager (node, python, pnpm, fd, ripgrep, …) | Already the install mechanism in this repo's `Dockerfile`; one declarative `mise use -g` layer, deterministic shims on PATH. Keeps the base image reproducible without per-tool curl installers. |
| **uv** (astral) | 0.11.x (current **0.11.8**, Apr 2026) | Python package/venv manager for recipe Python deps and `uvx` MCP servers | Rust-fast, lockfile-driven; `uv pip install -r requirements.txt` / `uv venv && uv pip install -e .` per §11 deps; `uvx <pkg>` runs light Python MCP servers as hatago children. Replaces pip/pipx entirely. |
| **pnpm** | **11.x** (current 11.0, Apr 2026; floor 10.19) | The **only** JS package manager — global, per-recipe, and hatago's bundled servers | Supply-chain policy is the whole point (§7): `minimumReleaseAge`, lifecycle default-deny, content-addressed store with integrity verification. `pnpm dlx` replaces `npx`. See <https://pnpm.io/supply-chain-security>. |
| **hatago MCP hub** (`@himorishige/hatago-mcp-hub`) | latest npm (run via `pnpm dlx`) | Aggregates a stack's MCP servers behind **one** HTTP endpoint in the pod | Lightweight, multi-transport (STDIO/HTTP/SSE/WebSocket), proxies remote servers and spawns stdio servers as children — exactly the §3 "one `.mcp.json` → `localhost:<port>`" model. Keeps `npx`/`uvx` out of the harness container. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| **rich** | 14.x | Terminal rendering — capability-report markdown→terminal, build progress, tables | Always (in `harnessed-tools`); §18 capability report renders with rich. |
| **textual** | latest (built on rich) | Full-screen TUI | Only **if** a TUI lands (stack picker / live build dashboard); optional per design. Same author as rich, zero friction to add later. |
| **PyYAML** / **ruamel.yaml** | PyYAML 6.x or ruamel 0.18.x | Parse/validate `recipe.yaml` + `stack.yaml`; emit `hatago.config.json` | Always. Use **ruamel.yaml** if round-trip comment preservation on generated manifests matters; PyYAML if plain load/dump suffices. |
| **yq** (mikefarah, Go) | 4.x | Shell-side YAML/JSON munging in the bootstrap + assembler glue | When bash-level YAML edits are cleaner than a Python round-trip; pairs with jq. Note: this is the Go `yq`, not the Python wrapper. |
| **jq** | 1.7.x | JSON munging — `.claude.json` stub generation, `pnpm ls`/`npm ls -g` → synthesized `package.json` for snyk, hatago config merge | Always available in the image; the `nightly-updates` manifest-synthesis trick depends on it. |
| **git** | 2.4x | Vendor plugins (git-subdir + sha), profile commit, repo ops | Always. |
| **varlock** (`dmno-dev/varlock`) | 0.x (CLI) | Optional secrets layer: reads `.env.schema` (@env-spec DSL), resolves `op(op://…)` refs, injects via `varlock run -- <cmd>` | **Opt-in only.** Present when `~/.config/harnessed/.env.schema` exists; otherwise never invoked (§16). |
| **1Password CLI (`op`)** | 2.x | Resolves `op://Vault/Item/field` secret refs for varlock / scanner tokens | With varlock, or standalone for `op run`/`op read`. Auth via mounted desktop-app agent socket **or** `OP_SERVICE_ACCOUNT_TOKEN` (see Variants). |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| **osv-scanner** (Google, Go) | Credential-free vuln scan of lockfiles / `node_modules` / images at build time | **v2.3.5+** (V2 line, 2026); static Go binary, no auth, uses osv.dev. V2 adds container scanning + transitive Python (`requirements.txt` via deps.dev). Baseline gate alongside pip-audit. `--min-severity` to filter; `harnessed build` fails on high. |
| **pip-audit** (PyPA) | Credential-free Python dependency audit | Scans any recipe shipping `requirements.txt`/`pyproject.toml`; uses PyPI advisory DB + OSV. No token. Second half of the always-on baseline gate. |
| **snyk** (CLI) | `snyk test --severity-threshold=high` on npm/pnpm trees | **Token-gated** (`SNYK_TOKEN`). Synthesize a `package.json` from `pnpm ls`/`npm ls -g` for manifest-less globals (the `nightly-updates` trick). **Warn-and-skip** if no token — never prompt (build stays non-interactive). |
| **Socket.dev CLI** (`socket`) | Deeper supply-chain behavioral signals (optional) | **Token-gated** (`SOCKET_SECURITY_API_KEY`). Optional extra layer; same warn-and-skip rule. |
| **`harnessed auth snyk\|socket`** | One-time token setup — runs the vendor CLI's own `auth` inside the tool container, persists to mounted host config | Keeps tokens deliberate and off image layers / repo. |
| **systemd user timer** | Nightly re-scan of installed images (CVEs disclosed post-build) | Port the `nightly-updates` timer pattern; re-runs osv-scanner against pinned images. |

## Installation

> harnessed installs by `git clone` + symlinking the dependency-free `harnessed` bash bootstrap;
> the bootstrap builds `harnessed-tools` on first run. The package lists below are what land
> **inside** the images — never on the host (host = podman only).

```bash
# --- HOST: the only prerequisite ---
sudo apt-get install -y podman                       # or distro equivalent; ≥ 5.6
# the host runs `podman build` (on the assembler-emitted Dockerfile) and the
# pod natively — the tools image only emits files; nothing is mounted to drive the engine.

# --- IN harnessed-tools IMAGE (Dockerfile): brain + scanners + secrets ---
# system layer
apt-get install -y git jq                             # + ca-certificates, gnupg
# go/static binaries
#   osv-scanner  -> prebuilt release binary (V2, v2.3.x)
#   yq (mikefarah) -> prebuilt release binary (v4.x)
# runtimes via mise (already this repo's pattern)
mise use -g node@24 pnpm@11 python@3.13 uv fd ripgrep
# python tooling (uv, pinned in pyproject.toml)
uv pip install rich textual ruamel.yaml pip-audit     # textual only if TUI lands
# JS supply-chain CLIs via pnpm (token-gated ones run on demand)
pnpm add -g snyk @socketsecurity/cli                  # optional credentialed scanners
# secrets layer (inert unless a .env.schema exists)
pnpm add -g varlock                                   # @env-spec resolver
#   1Password CLI (op) -> official apt repo (as in current Dockerfile)

# --- IN harnessed-base / hatago IMAGE ---
mise use -g node@24 pnpm@11 python@3.13 uv             # shared base toolchain
# hatago + light MCP servers run via pnpm dlx / uvx, baked pinned:
pnpm dlx @himorishige/hatago-mcp-hub --version         # hub; light servers as children
```

```toml
# managed pnpm supply-chain config — shipped in harnessed-base/lib/, applied to ALL pnpm trees
# pnpm-workspace.yaml (pnpm 11 reads policy from here, not .npmrc)
minimumReleaseAge: 1440          # minutes; quarantine newly published versions ~1 day (pnpm 11 default)
minimumReleaseAgeStrict: true    # fail rather than silently fall back to an older mature version
blockExoticSubdeps: true         # pnpm 11 default; block git/tarball/non-registry subdeps
onlyBuiltDependencies: []        # lifecycle scripts DENIED by default; allowlist explicitly
# pnpm 11 migration note: prefer `allowBuilds` map; `onlyBuiltDependencies` still honored as legacy
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| **podman (rootless) + pods** | Docker Engine + Compose | If a team is already all-in on Docker and rootless isn't a requirement. harnessed stays Docker-CLI-compatible, so `docker` works as the engine — but you lose rootless-by-default and the first-class `pod` primitive (Compose projects approximate it). |
| **hatago MCP hub** | mcphub (`@samanhappy/mcphub`), DXHeroes local-mcp-gateway, unrelated-ai/mcp-gateway | If you need a web UI / OAuth 2.1 / multi-tenant isolation. harnessed is single-user personal tooling, so hatago's lightweight, config-file, multi-transport model fits better; revisit if a shared/team gateway with auth is needed. |
| **pnpm 11** | npm + overrides, Yarn Berry | Only if a recipe's upstream truly cannot run under pnpm's hoisting. Even then, pnpm's `node-linker: hoisted` usually suffices; npm forfeits `minimumReleaseAge` + lifecycle default-deny, the core supply-chain guard. |
| **uv** | pip + venv, Poetry, pipx | If a recipe ships a Poetry-only build backend. uv reads `pyproject.toml`/`requirements.txt` natively and is far faster; `uvx` replaces pipx run. |
| **osv-scanner + pip-audit (credential-free baseline)** | Trivy, Grype | Trivy/Grype are excellent for OS-package + container-layer CVEs; add Trivy if you want image-OS-layer coverage beyond app deps. osv-scanner V2 now also does container scanning, narrowing the gap. |
| **varlock + 1Password** | `op run`/`op inject` alone, sops, doppler, plain env | If you don't want the @env-spec schema layer, `op run -- <cmd>` injects `op://` refs directly. varlock adds **validation + typing + AI-safe schema**; keep it opt-in so the no-secrets path stays zero-config. |
| **rich (report) / textual (TUI)** | plain stdout, prompt_toolkit, Bubble Tetra (Go) | If the tool were rewritten in Go. Within the Python image, rich is the de-facto standard; textual only when a full TUI is justified. |
| **mise (in-image)** | asdf, Nix, raw apt | Nix gives stronger reproducibility but is a heavy host/image dependency and a steep authoring curve; mise is already this repo's convention and lighter to maintain. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| **npm / npx** | No release-age quarantine, no lifecycle default-deny, no content-addressed integrity store — the exact supply-chain holes §7 closes. `npx` pulls-and-runs arbitrary latest code. | **pnpm** / **`pnpm dlx`**. Recipe validation flags raw `npm`/`npx` and points at the equivalent (and the ported `vendor-plugin` must drop its `npm install`). |
| **Build-time `FROM`-union of two harness systems** | `FROM` is linear inheritance + multi-stage `COPY --from`; there is **no** "union two sibling images" operator (§6). Trying to bake hindsight+openbrain into one image fails by construction. | Compose at **runtime** in a podman **pod** (§3): separate images, shared network, shared services attached by reference. |
| **Host Python / node / uv as a runtime dependency** | Version roulette on every user's machine; defeats "podman is the only host dep" (§15). | All logic in the **`harnessed-tools`** image; host runs a dependency-free bash bootstrap. |
| **Rootful podman / privileged Docker daemon** | Grants host-root blast radius for a personal dev tool; unnecessary. | **Rootless** podman scoped to your UID (full control of *your* user's containers — acceptable, state it); build + run on the host. |
| **Bind-mounting `~/.claude.json` rw** | Single whole-file blob Claude rewrites constantly; a shared rw mount races the host (lost writes/corruption) and merges container state back into the host file (§4b). | **transparent:** copy-on-start writable per-instance copy (or `CLAUDE_CONFIG_DIR` relocation). **isolated:** generate a minimal stub; never mount it. Mount only `~/.claude/.credentials.json` (ro). |
| **Baking/committing credentials** (Claude OAuth, `SNYK_TOKEN`, `SOCKET_SECURITY_API_KEY`, `op://` secrets) | Tokens in an image layer or repo file leak permanently and can't be rotated cleanly. | Reference from host, inject as **env only** at launch; `harnessed auth …` persists to mounted host config, never a layer. |
| **`OP_SERVICE_ACCOUNT_TOKEN` left in a long-lived shell env** | A visible service-account token can leak into unintended processes sharing the env (documented 1Password caution). | Prefer the **mounted desktop-app agent socket** (app-auth, `allowAppAuth`) for interactive use; reserve the service-account token for headless/CI where no agent exists, and scope it narrowly. |
| **Interactive scanner prompts in `harnessed build`** | Breaks non-interactive/reproducible builds (CI, nightly timer). | **Warn-and-skip** the credentialed scanner; credential-free osv-scanner + pip-audit remain the gate. |
| **MCP SSE transport for new servers** | SSE is **deprecated** in the current MCP spec (2025-06-18) and in Claude Code. | **Streamable HTTP** (one endpoint, POST + optional GET/SSE stream); hatago wraps stdio→HTTP for servers that only speak stdio. |

## Stack Patterns by Variant

**If `transparent` stack (the old `container`, host-mirror):**
- **Engine:** podman, but **no pod, no hatago, no services** — harness container only (the degenerate case, §3).
- **Config source:** bind-mount host `~/.claude` (rw), `~/.codex`, `~/.config/opencode`, `~/.gemini` (rw) live; MCP comes from the host's own `.mcp.json`/`.claude.json`.
- **`.claude.json`:** copy-on-start per-instance copy (or `CLAUDE_CONFIG_DIR`) — **never** rw-bind the host file.
- Because it's "my laptop, sandboxed" — the supply-chain/hatago/profile machinery doesn't apply.

**If `isolated` stack (recipe-composed):**
- **Engine:** podman **pod** `harnessed-<stack>-<projhash>` on `harnessed-net`: harness container + **hatago** + shared services by reference.
- **Config source:** auth seeded (`~/.claude/.credentials.json` ro + generated minimal `.claude.json` stub); skills/commands/agents/hooks/rules/`.mcp.json`/`settings.json` come **only** from the committed `profiles/<name>/` mount; `.mcp.json` → `localhost:<hatago-port>`.
- Full supply-chain gate at build; pnpm-everywhere; capability test as oracle (§18).

**If harness = `claude`:**
- Native canonical format — mount the profile's `.claude/` tree directly; `claude mcp list` / `hatago://servers` for capability assertions.
- Headless capability test: `claude -p … --output-format json`.

**If harness = `omp`:**
- Claude format is still canonical; omp consumes it via **`claude-hooks-bridge`** + `lib-pi-adapter.sh` (no re-authoring). The `omp` base recipe pulls `npm:@ryan_nookpi/pi-extension-claude-hooks-bridge` (installed via pnpm).
- One harness per stack — never claude+omp together (§8).

**If a recipe ships a light MCP server (stdio):**
- Bake it into the **hatago** image; hatago spawns it as a child and wraps **stdio→HTTP**. Run via `pnpm dlx <pkg>` (Node) or `uvx <pkg>` (Python).

**If a recipe needs a heavy/stateful service (hindsight = postgres+MCP, openbrain):**
- Its **own** `services/<name>/Dockerfile`, **own** volume (`hindsight-data`, service-scoped), independent lifecycle (`harnessed svc up/down`); likely already network-native Streamable HTTP, proxied by hatago rather than child-spawned.

**If 1Password = desktop app present (interactive workstation):**
- Resolve `op://` via the **mounted agent socket** (`allowAppAuth`) already in the §4a mount layer — no token on disk.

**If 1Password = headless/CI (no desktop app):**
- Use a narrowly-scoped **`OP_SERVICE_ACCOUNT_TOKEN`**, injected as env at launch only. *(Confirm which your setup supports — [INFERENCE], to verify in §14.)*

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| `podman@5.6–5.8` | host build + run (rootless) | Runs natively on the host for both `podman build` and pod run. Docker-CLI-compatible — existing `container.sh` engine-detection ports unchanged. |
| `pnpm@11` | Node ≥ 20 (use node@24 LTS) | pnpm 11 is ESM-distributed, new store format, **policy in `pnpm-workspace.yaml`**. `minimumReleaseAge=1440` + `blockExoticSubdeps=true` default-on; `onlyBuiltDependencies` honored but `allowBuilds` is the new form. If pinned to 10.19, `minimumReleaseAge`/`onlyBuiltDependencies` exist but are **off by default** — set them explicitly. |
| `mise (2026.x)` | node@24, python@3.13, pnpm@11, uv | mise installs node tools via its `npm:` backend — [INFERENCE: confirm it routes through pnpm or use `pnpm add -g` directly so installs honor pnpm policy (§14)]. |
| `uv@0.11` | Python 3.12 / 3.13, `uvx` MCP servers | Standalone static binary; bundles a build backend. Reads `pyproject.toml`/`requirements.txt`. |
| `hatago-mcp-hub` (latest) | MCP spec **2025-06-18**, Node ≥ 20 | Multi-transport (STDIO/HTTP/SSE/WebSocket); use **Streamable HTTP** to the harness (SSE deprecated). Config-file driven; restart on config change (no hot-reload). |
| `osv-scanner@2.3.x` | lockfiles (npm/pnpm/pip/…), `node_modules`, container images | V2 adds container scanning + transitive Python via deps.dev. Credential-free. |
| `snyk` CLI | npm/pnpm trees + synthesized `package.json` | Needs `SNYK_TOKEN`; `--severity-threshold=high`. Manifest-less globals → synthesize from `pnpm ls`/`npm ls -g`. |
| `varlock@0.x` + `op@2.x` | `.env.schema` (@env-spec), `op://` refs | `varlock run -- <cmd>` injects resolved env; resolution via app-auth socket or `OP_SERVICE_ACCOUNT_TOKEN`. Inert with no schema present. |
| `rich@14` / `textual` | Python 3.12+ | textual builds on rich; add only if a TUI lands. |
| Claude Code config | `~/.claude/.credentials.json` (OAuth), `~/.claude.json` (metadata+~450KB state), `~/.claude/projects/*.jsonl` | Mount credentials ro; **never** rw-mount `.claude.json`. `CLAUDE_CONFIG_DIR` relocation — [INFERENCE: verify it relocates `.claude.json` too, not just the dir (§14)]. |

## Sources

- <https://github.com/containers/podman/releases> / releasealert.dev — current podman **v5.8.2** (Apr 2026), 5.6.0 (Aug 2025) — HIGH
- <https://pnpm.io/supply-chain-security> — `minimumReleaseAge`, `minimumReleaseAgeStrict`, lifecycle scripts, store integrity — HIGH
- <https://pnpm.io/blog/releases/11.0> — pnpm 11 defaults: `minimumReleaseAge=1440`, `blockExoticSubdeps=true`, `allowBuilds` replaces legacy `onlyBuiltDependencies` — HIGH
- <https://pnpm.io/blog/releases/10.19> — `onlyBuiltDependencies` exact-version support, `minimumReleaseAgeExclude` — HIGH
- <https://socket.dev/blog/pnpm-11-adds-new-supply-chain-protection-defaults> — corroboration of pnpm 11 minimum-release-age default — MEDIUM
- <https://github.com/himorishige/hatago-mcp-hub> + <https://www.npmjs.com/package/@himorishige/hatago-mcp-hub> + <https://hatago.dev/en/> — hatago hub, npx/pnpm-dlx invocation, multi-transport, stdio→HTTP child spawning, restart-on-config — HIGH
- <https://github.com/google/osv-scanner> + <https://google.github.io/osv-scanner/> + appsecsanta.com — osv-scanner **V2 (v2.3.5, Mar 2026)**, credential-free, container + transitive-Python scanning — HIGH
- <https://www.npmjs.com/package/snyk> + <https://docs.snyk.io/.../set-severity-thresholds-for-cli-tests> — `snyk test --severity-threshold=high|...`, token-gated — HIGH
- <https://github.com/dmno-dev/varlock> — @env-spec DSL, `op()` refs, `varlock run --`; AI-safe `.env` schema — HIGH
- <https://schalkneethling.com/posts/stop-storing-secrets-on-disk-replace-your-env-with-varlock-and-1password/> — varlock + 1Password `op(op://Vault/Item/field)` pattern — MEDIUM
- <https://developer.1password.com/docs/service-accounts/use-with-1password-cli/> — `OP_SERVICE_ACCOUNT_TOKEN`, precedence, service-account auth — HIGH
- <https://www.1password.community/discussions/developers/link-the-1password-cli-in-a-container-to-the-1password-application-on-the-host/167032> — container `op`: agent socket vs token, token-leak caution — MEDIUM
- <https://docs.astral.sh/uv/> + <https://github.com/astral-sh/uv> — uv current **0.11.8** (Apr 2026), `uvx`, build backend — HIGH
- <https://mise.jdx.dev/lang/python.html> — mise + uv integration, python management — HIGH
- <https://modelcontextprotocol.io/specification/2025-03-26/basic/transports> + <https://code.claude.com/docs/en/mcp> — Streamable HTTP (`streamable-http`), **SSE deprecated**, current spec 2025-06-18 — HIGH
- <https://auth0.com/blog/mcp-streamable-http/> + <https://www.truefoundry.com/blog/mcp-stdio-vs-streamable-http-enterprise> — SSE→Streamable-HTTP rationale, stdio vs HTTP — MEDIUM
- <https://inventivehq.com/knowledge-base/claude/where-configuration-files-are-stored> + Claude Code MCP docs — `~/.claude/` layout, `projects/*.jsonl` session state — MEDIUM
- Repo: `Dockerfile` (mise + node@22 + pnpm + Ubuntu 24.04 base), `docs/harnessed-design.md` §6/§7/§15/§16, `.planning/PROJECT.md` — HIGH (in-repo ground truth)
- rich@14 / textual versions — [INFERENCE, MEDIUM] — current major lines; exact pin to confirm at `pyproject.toml` authoring time.

---
*Stack research for: rootless-podman AI-harness stack orchestrator (harnessed)*
*Researched: 2026-06-14*
