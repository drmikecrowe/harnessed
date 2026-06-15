See @AGENTS.md for project instructions

<!-- GSD:project-start source:PROJECT.md -->

## Project

**harnessed**

`harnessed` is one executable that launches **isolated, composable harness stacks** — each a
podman pod running an AI coding harness (`claude`/`omp`) plus an MCP hub (hatago) plus optional
shared services (hindsight, openbrain). It evolves this repo's existing `container` tool: the
current "my laptop, sandboxed" behavior folds in as the built-in `transparent` stack, while new
`isolated` stacks let you experiment with curated sets of skills/commands/hooks/MCP/memory systems
**per container**, where isolation makes the collisions that killed a host-merge approach
disappear by construction.

It is for developers (initially the author) who want to compose and trial harness configurations
— different skill/plugin/MCP/memory combinations — in clean, reproducible, throwaway-or-persistent
environments without dragging every host default into the container or polluting `~`.

**Core Value:** You can compose a named stack (one harness + chosen recipes) and launch an isolated, authenticated
instance that exposes **exactly** the skills/commands/MCP/services it declares — nothing from the
host config — reproducibly, with podman as the only host dependency.

### Constraints

- **Tech stack**: Host bootstrap in dependency-free bash; all logic in a containerized
  `harnessed-tools` Python image (rich/textual + yq/jq + git + pnpm + scanners + varlock + op) — keep host deps to podman/docker only (§15)

- **Architecture**: Stacks composed at runtime in a podman pod, never via build-time `FROM` union (§3, §6)
- **Docker-out-of-Docker**: every `-v` the tool issues must use **host absolute paths** (pass host `HOME`/`PWD` as env); use the **rootless** podman socket; keep the final interactive attach host-native for a clean TTY (§15)
- **Canonical format**: Claude Code format is the single source of truth; other harnesses adapt out of it (§8)
- **Supply chain**: pnpm everywhere (no npm/npx); build-time scan gate fails on high-severity; credentials referenced from host, never baked/committed (§7)
- **Security/secrets**: auth and scanner/1Password secrets are env-only, never an image layer or repo file; varlock + 1Password are optional opt-in (§16)
- **Compatibility**: keep `container` working as an alias for muscle memory (§14, recommendation: keep)
- **Testing**: integration-only, behavior asserted through the running instance against the stack manifest as oracle; build harnessed itself in vertical slices (§18)
- **Docs**: each documentation section lands with the feature it documents — a feature isn't done until its docs exist (§17)

<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->

## Technology Stack

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **podman** (rootless) | ≥ 5.6, current **5.8.2** (Apr 2026) | Container/pod engine; the **only** host dependency | Native **pods** (shared netns + lifecycle) are exactly the §3 stack unit; rootless = no host root, scoped to your UID; Docker-CLI-compatible so existing `container.sh` `podman`/`docker` detection ports as-is. v5.x ships the stable user `podman.socket` needed for Docker-out-of-Docker (DooD). |
| **`podman.socket`** (user unit) | bundled with podman 5.x | Rootless API socket the tool container drives the host engine through | `systemctl --user enable --now podman.socket` exposes `unix:///run/user/$UID/podman/podman.sock`. The tool sets `CONTAINER_HOST` (podman-native) / `DOCKER_HOST` (compat) to it — the canonical DooD pattern, no privileged daemon. Pair with `loginctl enable-linger $USER` so the socket survives logout. |
| **Python** | 3.12 / 3.13 | Implementation language for all `harnessed-tools` logic (parse/validate YAML, vendor, sync-links, merge hatago config, generate `.claude.json` stub, scan, orchestrate podman) | `sync-plugin-links` prior art is already Python; rich/textual TUI is Python; pinned **inside** the image so the host needs no Python (§15). Managed by mise/uv, not the host. |
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

# --- HOST: the only prerequisite ---

# bootstrap then drives the host engine over the socket:

# --- IN harnessed-tools IMAGE (Dockerfile): brain + scanners + secrets ---

# system layer

# go/static binaries

#   osv-scanner  -> prebuilt release binary (V2, v2.3.x)

#   yq (mikefarah) -> prebuilt release binary (v4.x)

# runtimes via mise (already this repo's pattern)

# python tooling (uv, pinned in pyproject.toml)

# JS supply-chain CLIs via pnpm (token-gated ones run on demand)

# secrets layer (inert unless a .env.schema exists)

#   1Password CLI (op) -> official apt repo (as in current Dockerfile)

# --- IN harnessed-base / hatago IMAGE ---

# hatago + light MCP servers run via pnpm dlx / uvx, baked pinned:

# managed pnpm supply-chain config — shipped in harnessed-base/lib/, applied to ALL pnpm trees

# pnpm-workspace.yaml (pnpm 11 reads policy from here, not .npmrc)

# pnpm 11 migration note: prefer `allowBuilds` map; `onlyBuiltDependencies` still honored as legacy

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| **podman (rootless) + pods** | Docker Engine + Compose | If a team is already all-in on Docker and rootless isn't a requirement. harnessed stays Docker-compatible (CLI + `DOCKER_HOST`), so `docker` works as the engine — but you lose rootless-by-default and the first-class `pod` primitive (Compose projects approximate it). |
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
| **Rootful podman / privileged Docker daemon** | Grants host-root blast radius for a personal dev tool; unnecessary. | **Rootless** `podman.socket` scoped to your UID (full control of *your* user's containers — acceptable, state it). |
| **Bind-mounting `~/.claude.json` rw** | Single whole-file blob Claude rewrites constantly; a shared rw mount races the host (lost writes/corruption) and merges container state back into the host file (§4b). | **transparent:** copy-on-start writable per-instance copy (or `CLAUDE_CONFIG_DIR` relocation). **isolated:** generate a minimal stub; never mount it. Mount only `~/.claude/.credentials.json` (ro). |
| **Container-internal paths in `-v` flags** | DooD bind sources resolve on the **host** daemon; the tool container's internal view points at nothing. The classic DooD footgun. | Pass host `HOME`/`PWD` as env; every `-v` the tool issues uses **host-absolute** paths. |
| **Baking/committing credentials** (Claude OAuth, `SNYK_TOKEN`, `SOCKET_SECURITY_API_KEY`, `op://` secrets) | Tokens in an image layer or repo file leak permanently and can't be rotated cleanly. | Reference from host, inject as **env only** at launch; `harnessed auth …` persists to mounted host config, never a layer. |
| **`OP_SERVICE_ACCOUNT_TOKEN` left in a long-lived shell env** | A visible service-account token can leak into unintended processes sharing the env (documented 1Password caution). | Prefer the **mounted desktop-app agent socket** (app-auth, `allowAppAuth`) for interactive use; reserve the service-account token for headless/CI where no agent exists, and scope it narrowly. |
| **Interactive scanner prompts in `harnessed build`** | Breaks non-interactive/reproducible builds (CI, nightly timer). | **Warn-and-skip** the credentialed scanner; credential-free osv-scanner + pip-audit remain the gate. |
| **MCP SSE transport for new servers** | SSE is **deprecated** in the current MCP spec (2025-06-18) and in Claude Code. | **Streamable HTTP** (one endpoint, POST + optional GET/SSE stream); hatago wraps stdio→HTTP for servers that only speak stdio. |

## Stack Patterns by Variant

- **Engine:** podman, but **no pod, no hatago, no services** — harness container only (the degenerate case, §3).
- **Config source:** bind-mount host `~/.claude` (rw), `~/.codex`, `~/.config/opencode`, `~/.gemini` (rw) live; MCP comes from the host's own `.mcp.json`/`.claude.json`.
- **`.claude.json`:** copy-on-start per-instance copy (or `CLAUDE_CONFIG_DIR`) — **never** rw-bind the host file.
- Because it's "my laptop, sandboxed" — the supply-chain/hatago/profile machinery doesn't apply.
- **Engine:** podman **pod** `harnessed-<stack>-<projhash>` on `harnessed-net`: harness container + **hatago** + shared services by reference.
- **Config source:** auth seeded (`~/.claude/.credentials.json` ro + generated minimal `.claude.json` stub); skills/commands/agents/hooks/rules/`.mcp.json`/`settings.json` come **only** from the committed `profiles/<name>/` mount; `.mcp.json` → `localhost:<hatago-port>`.
- Full supply-chain gate at build; pnpm-everywhere; capability test as oracle (§18).
- Native canonical format — mount the profile's `.claude/` tree directly; `claude mcp list` / `hatago://servers` for capability assertions.
- Headless capability test: `claude -p … --output-format json`.
- Claude format is still canonical; omp consumes it via **`claude-hooks-bridge`** + `lib-pi-adapter.sh` (no re-authoring). The `omp` base recipe pulls `npm:@ryan_nookpi/pi-extension-claude-hooks-bridge` (installed via pnpm).
- One harness per stack — never claude+omp together (§8).
- Bake it into the **hatago** image; hatago spawns it as a child and wraps **stdio→HTTP**. Run via `pnpm dlx <pkg>` (Node) or `uvx <pkg>` (Python).
- Its **own** `services/<name>/Dockerfile`, **own** volume (`hindsight-data`, service-scoped), independent lifecycle (`harnessed svc up/down`); likely already network-native Streamable HTTP, proxied by hatago rather than child-spawned.
- Resolve `op://` via the **mounted agent socket** (`allowAppAuth`) already in the §4a mount layer — no token on disk.
- Use a narrowly-scoped **`OP_SERVICE_ACCOUNT_TOKEN`**, injected as env at launch only. *(Confirm which your setup supports — [INFERENCE], to verify in §14.)*

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| `podman@5.6–5.8` | rootless `podman.socket` + `CONTAINER_HOST`/`DOCKER_HOST` | Socket is stable in 5.x; `loginctl enable-linger` required for persistence. Docker CLI + `DOCKER_HOST` compatibility holds — existing `container.sh` engine-detection ports unchanged. |
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

- <https://docs.podman.io/en/latest/markdown/podman-system-service.1.html> — `podman.socket`, `DOCKER_HOST`, `systemctl --user enable podman.socket`, lingering — HIGH
- <https://github.com/containers/podman/releases> / releasealert.dev — current podman **v5.8.2** (Apr 2026), 5.6.0 (Aug 2025) — HIGH
- <https://oneuptime.com/blog/post/2026-03-18-enable-podman-socket-rootless-users/view> — rootless socket env (`DOCKER_HOST=unix:///run/user/<UID>/podman/podman.sock`) — HIGH
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

<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->

## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->

## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->

## Project Skills

| Skill | Description | Path |
|-------|-------------|------|
| caveman | > Ultra-compressed communication mode. Cuts token usage ~75% by dropping filler, articles, and pleasantries while keeping full technical accuracy. Use when user says "caveman mode", "talk like caveman", "use caveman", "less tokens", "be brief", or invokes /caveman. | `.agents/skills/caveman/SKILL.md` |
| design-an-interface | Generate multiple radically different interface designs for a module using parallel sub-agents. Use when user wants to design an API, explore interface options, compare module shapes, or mentions "design it twice". | `.agents/skills/design-an-interface/SKILL.md` |
| diagnose | Disciplined diagnosis loop for hard bugs and performance regressions. Reproduce → minimise → hypothesise → instrument → fix → regression-test. Use when user says "diagnose this" / "debug this", reports a bug, says something is broken/throwing/failing, or describes a performance regression. | `.agents/skills/diagnose/SKILL.md` |
| edit-article | Edit and improve articles by restructuring sections, improving clarity, and tightening prose. Use when user wants to edit, revise, or improve an article draft. | `.agents/skills/edit-article/SKILL.md` |
| git-guardrails-claude-code | Set up Claude Code hooks to block dangerous git commands (push, reset --hard, clean, branch -D, etc.) before they execute. Use when user wants to prevent destructive git operations, add git safety hooks, or block git push/reset in Claude Code. | `.agents/skills/git-guardrails-claude-code/SKILL.md` |
| grill-me | Interview the user relentlessly about a plan or design until reaching shared understanding, resolving each branch of the decision tree. Use when user wants to stress-test a plan, get grilled on their design, or mentions "grill me". | `.agents/skills/grill-me/SKILL.md` |
| grill-with-docs | Grilling session that challenges your plan against the existing domain model, sharpens terminology, and updates documentation (CONTEXT.md, ADRs) inline as decisions crystallise. Use when user wants to stress-test a plan against their project's language and documented decisions. | `.agents/skills/grill-with-docs/SKILL.md` |
| handoff | Compact the current conversation into a handoff document for another agent to pick up. | `.agents/skills/handoff/SKILL.md` |
| improve-codebase-architecture | Find deepening opportunities in a codebase, informed by the domain language in CONTEXT.md and the decisions in docs/adr/. Use when the user wants to improve architecture, find refactoring opportunities, consolidate tightly-coupled modules, or make a codebase more testable and AI-navigable. | `.agents/skills/improve-codebase-architecture/SKILL.md` |
| migrate-to-shoehorn | Migrate test files from `as` type assertions to @total-typescript/shoehorn. Use when user mentions shoehorn, wants to replace `as` in tests, or needs partial test data. | `.agents/skills/migrate-to-shoehorn/SKILL.md` |
| obsidian-vault | Search, create, and manage notes in the Obsidian vault with wikilinks and index notes. Use when user wants to find, create, or organize notes in Obsidian. | `.agents/skills/obsidian-vault/SKILL.md` |
| prototype | Build a throwaway prototype to flesh out a design before committing to it. Routes between two branches — a runnable terminal app for state/business-logic questions, or several radically different UI variations toggleable from one route. Use when the user wants to prototype, sanity-check a data model or state machine, mock up a UI, explore design options, or says "prototype this", "let me play with it", "try a few designs". | `.agents/skills/prototype/SKILL.md` |
| qa | Interactive QA session where user reports bugs or issues conversationally, and the agent files GitHub issues. Explores the codebase in the background for context and domain language. Use when user wants to report bugs, do QA, file issues conversationally, or mentions "QA session". | `.agents/skills/qa/SKILL.md` |
| request-refactor-plan | Create a detailed refactor plan with tiny commits via user interview, then file it as a GitHub issue. Use when user wants to plan a refactor, create a refactoring RFC, or break a refactor into safe incremental steps. | `.agents/skills/request-refactor-plan/SKILL.md` |
| review | Review the changes since a fixed point (commit, branch, tag, or merge-base) along two axes — Standards (does the code follow this repo's documented coding standards?) and Spec (does the code match what the originating issue/PRD asked for?). Runs both reviews in parallel sub-agents and reports them side by side. Use when the user wants to review a branch, a PR, work-in-progress changes, or asks to "review since X". | `.agents/skills/review/SKILL.md` |
| scaffold-exercises | Create exercise directory structures with sections, problems, solutions, and explainers that pass linting. Use when user wants to scaffold exercises, create exercise stubs, or set up a new course section. | `.agents/skills/scaffold-exercises/SKILL.md` |
| setup-matt-pocock-skills | Sets up an `## Agent skills` block in AGENTS.md/CLAUDE.md and `docs/agents/` so the engineering skills know this repo's issue tracker (GitHub or local markdown), triage label vocabulary, and domain doc layout. Run before first use of `to-issues`, `to-prd`, `triage`, `diagnose`, `tdd`, `improve-codebase-architecture`, or `zoom-out` — or if those skills appear to be missing context about the issue tracker, triage labels, or domain docs. | `.agents/skills/setup-matt-pocock-skills/SKILL.md` |
| setup-pre-commit | Set up Husky pre-commit hooks with lint-staged (Prettier), type checking, and tests in the current repo. Use when user wants to add pre-commit hooks, set up Husky, configure lint-staged, or add commit-time formatting/typechecking/testing. | `.agents/skills/setup-pre-commit/SKILL.md` |
| tdd | Test-driven development with red-green-refactor loop. Use when user wants to build features or fix bugs using TDD, mentions "red-green-refactor", wants integration tests, or asks for test-first development. | `.agents/skills/tdd/SKILL.md` |
| teach | Teach the user a new skill or concept, within this workspace. | `.agents/skills/teach/SKILL.md` |
| to-issues | Break a plan, spec, or PRD into independently-grabbable issues on the project issue tracker using tracer-bullet vertical slices. Use when user wants to convert a plan into issues, create implementation tickets, or break down work into issues. | `.agents/skills/to-issues/SKILL.md` |
| to-prd | Turn the current conversation context into a PRD and publish it to the project issue tracker. Use when user wants to create a PRD from the current context. | `.agents/skills/to-prd/SKILL.md` |
| triage | Triage issues through a state machine driven by triage roles. Use when user wants to create an issue, triage issues, review incoming bugs or feature requests, prepare issues for an AFK agent, or manage issue workflow. | `.agents/skills/triage/SKILL.md` |
| ubiquitous-language | Extract a DDD-style ubiquitous language glossary from the current conversation, flagging ambiguities and proposing canonical terms. Saves to UBIQUITOUS_LANGUAGE.md. Use when user wants to define domain terms, build a glossary, harden terminology, create a ubiquitous language, or mentions "domain model" or "DDD". | `.agents/skills/ubiquitous-language/SKILL.md` |
| write-a-skill | Create new agent skills with proper structure, progressive disclosure, and bundled resources. Use when user wants to create, write, or build a new skill. | `.agents/skills/write-a-skill/SKILL.md` |
| writing-beats | Shape an article as a journey of beats, choose-your-own-adventure style. The user picks a starting beat from the raw material, you write only that beat, then offer options for where to pivot next, beat by beat, until the article reaches a natural end. Use when the user has raw material and wants to assemble it as a narrative rather than an argument. | `.agents/skills/writing-beats/SKILL.md` |
| writing-fragments | Grilling session that mines the user for fragments — heterogeneous nuggets of writing (claims, vignettes, sharp sentences, half-thoughts) — and appends them to a single document as raw material for a future article. Use when the user wants to develop ideas before imposing structure, or mentions "fragments", "ideate", or "raw material" for writing. | `.agents/skills/writing-fragments/SKILL.md` |
| writing-shape | Take a markdown file of raw material and shape it into an article through a conversational session — drafting candidate openings, growing the piece paragraph by paragraph, arguing about format (lists, tables, callouts, quotes) at each step. Use when the user has a pile of notes, fragments, or a rough draft and wants help turning it into something publishable. | `.agents/skills/writing-shape/SKILL.md` |
| zoom-out | Tell the agent to zoom out and give broader context or a higher-level perspective. Use when you're unfamiliar with a section of code or need to understand how it fits into the bigger picture. | `.agents/skills/zoom-out/SKILL.md` |
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->

## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:

- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->

## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
