# harnessed

## What This Is

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

## Core Value

You can compose a named stack (one harness + chosen recipes) and launch an isolated, authenticated
instance that exposes **exactly** the skills/commands/MCP/services it declares — nothing from the
host config — reproducibly, with podman as the only host dependency.

## Requirements

### Validated

<!-- Already shipped/working in the existing `container` tool; folds in as `transparent`. -->

- ✓ Host-mirror sandbox: bind-mount host `~/.claude` (+ `.codex`/`.opencode`/`.gemini`), project, and host auth into an isolated container — existing (`container.sh`)
- ✓ Host-integration mount layer: 1Password SSH agent, GPG/YubiKey signing, `~/.ssh` (ro), git config (ro), egress firewall, project mount — existing (`container.sh` `start_new_container`)
- ✓ Installer + PATH symlink + image build/list/stop/remove/clean lifecycle — existing (`install.sh`, `container.sh`)

### Active

<!-- New `harnessed` scope. Hypotheses until shipped and validated. -->

- [ ] One `harnessed` engine with two config modes: `transparent` (host-mirror, the old `container`) and `isolated` (auth seeded + composed profile, zero host config)
- [ ] Runtime stack composition as a podman pod: harness container + hatago MCP hub on a shared network (`harnessed-net`)
- [ ] hatago MCP hub aggregating a stack's MCP servers behind one HTTP endpoint; light `pnpm dlx`/`uvx` stdio servers baked as hatago children
- [ ] Shared, service-scoped sidecars (hindsight, openbrain) — own image/volume/lifecycle, concurrently attachable by multiple instances
- [ ] `isolated` auth seeding: mount `~/.claude/.credentials.json` read-only + generate a minimal `.claude.json` stub (no host config), with profile-supplied skills/commands/agents/hooks/rules/`.mcp.json`/`settings.json`
- [ ] Hand-authored recipes (`recipes/<name>/recipe.yaml`) contributing an MCP layer and/or a Claude-canonical file-extension layer
- [ ] Authored stack manifests (`stacks/<name>/stack.yaml`) composing harness + recipes + services + permissions + state
- [ ] Build-time assembler (runs in the `harnessed-tools` container, emits files only): vendor plugins, fan skills/commands into harness-native paths (fail-fast on collision), wire hooks, emit a `Dockerfile` (+ build context) + committed `profiles/<name>/` + `hatago.config.json` + a generated launcher; the host runs `podman build` to produce baked images
- [ ] Supply-chain gate at build time: osv-scanner + pip-audit (credential-free) always; snyk + Socket.dev when a token is present (warn-and-skip otherwise); fail on high-severity
- [ ] pnpm-everywhere policy (managed config: `minimumReleaseAge`, lifecycle-script default-deny, store integrity); recipe validation flags raw `npm`/`npx`
- [ ] omp harness support via `claude-hooks-bridge` + pi-adapter (Claude format is canonical; one harness per stack)
- [ ] State & lifecycle: persistent by default, `--fresh` for throwaway; service volumes service-scoped; harness session state (`projects/` + `history.jsonl`) persisted host-side by default
- [ ] CLI surface: `harnessed <stack> [path]`, `build`, `install`/`uninstall` (launcher shim), `new`, `list`, `stop`, `rm`, `svc up/down/list`, `auth snyk|socket`, `--fresh`
- [ ] Containerized tooling, host runs podman natively (no Docker-out-of-Docker): thin dependency-free `harnessed` bash bootstrap + `harnessed-tools` assembler image that emits files; host `podman build` builds the images; a generated `~/.local/bin/<stack>` host-bash launcher runs the pod
- [ ] `container` retained as a thin alias → `harnessed transparent`
- [ ] Documentation as gated deliverable: README, design doc, recipe-authoring guide, stack guide, secrets setup, service authoring, troubleshooting/ops
- [ ] Integration-only capability test per stack: build → run `--fresh` headless → assert declared MCP/skills/commands present → render a markdown capability report

### Out of Scope

- Combining two harness systems via Docker `FROM` — `FROM` is linear inheritance + multi-stage `COPY`, not a union operator; systems are combined at runtime in a pod (§6)
- Runtime/dynamic assembly of recipes — recipes are hand-authored and assembled ahead of time into committed artifacts (§5)
- More than one harness per stack — a stack targets exactly `claude` or `omp`, never both (§8)
- A second config canonical format — Claude Code format is the single source of truth; omp adapts out of it via bridge (§8)
- npm/npx for JavaScript installs — pnpm everywhere for supply-chain safety (§7)
- Assembler unit tests — testing internals couples to implementation; behavior is verified transitively through the running instance (§18)
- Requiring host Python/node/uv — podman/docker is the only host dependency (§15)
- Baking or committing credentials (Claude auth, scanner tokens, 1Password secrets) — referenced from host, injected as env only, never an image layer or repo file (§7, §16)

## Context

- **Existing repo:** `container.sh` (host-mirror sandbox), `Dockerfile`, `install.sh`,
  `egress-firewall.sh`, `Permissions.md`, `.env.schema.example`. The new tool ports and supersedes
  much of this; `container` becomes an alias.
- **Prior art to port** (from host): `~/.agents/bin/vendor-plugin` (plugin resolve/install),
  `~/.agents.20260603/bin/sync-plugin-links` (fan skills/commands into harness paths, conflict
  reporting), universal-hooks `run-hook.sh`/`lib-pi-adapter.sh` (per-runtime hook dispatch),
  `~/.config/dorothy/commands/nightly-updates` (supply-chain audit suite + systemd-timer pattern).
- **Failed prior approach:** merging a curated set into the host config (`~/.agents` +
  `sync-plugin-links` + universal-hooks) failed because a single shared host namespace can't hold
  every experiment at once (openbrain/hindsight collide, `settingSources` drift, vendored deps
  pollute `~`). The per-container merge is the fix.
- **Harness config layout grounded in real `~/.claude`:** credential is
  `~/.claude/.credentials.json` (OAuth); `~/.claude.json` is metadata + ~450 KB state, not auth —
  do not mount, generate a stub.
- **Design source of truth:** `docs/harnessed-design.md` — architecture decisions (§2–§9)
  confirmed; schemas/repo-layout/CLI (§10–§13) proposed; §14 items to verify during execution.
- **Bridge dependency:** `claude-hooks-bridge` lives at
  `~/Programming/AI/omp-extensions/claude-hooks-bridge`.

## Constraints

- **Tech stack**: Host bootstrap in dependency-free bash; all logic in a containerized
  `harnessed-tools` Python image (rich/textual + yq/jq + git + pnpm + scanners + varlock + op) — keep host deps to podman/docker only (§15)
- **Architecture**: Stacks composed at runtime in a podman pod, never via build-time `FROM` union (§3, §6)
- **Execution model**: the `harnessed-tools` container emits files only (Dockerfile + profile + launcher); the **host** runs `podman build` and the generated host-bash launcher runs the pod via host `podman` — no daemon-in-container, no API socket, no host-absolute-path footgun, host-native TTY (§15)
- **Canonical format**: Claude Code format is the single source of truth; other harnesses adapt out of it (§8)
- **Supply chain**: pnpm everywhere (no npm/npx); build-time scan gate fails on high-severity; credentials referenced from host, never baked/committed (§7)
- **Security/secrets**: auth and scanner/1Password secrets are env-only, never an image layer or repo file; varlock + 1Password are optional opt-in (§16)
- **Compatibility**: keep `container` working as an alias for muscle memory (§14, recommendation: keep)
- **Testing**: integration-only, behavior asserted through the running instance against the stack manifest as oracle; build harnessed itself in vertical slices (§18)
- **Docs**: each documentation section lands with the feature it documents — a feature isn't done until its docs exist (§17)

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| One engine, two config modes (`transparent`/`isolated`) | Same base image/mounts/auth; differ only on config source — minimal surface, `transparent` = old `container` | — Pending |
| Per-container merge, not host merge | Isolation removes the collision that killed the host-merge attempt | — Pending |
| Compose stacks at runtime in a podman pod | `FROM` can't union two sibling systems; runtime pod can | — Pending |
| hatago in the pod over HTTP (not stdio in harness container) | Keeps `npx`/`uvx` out of the harness container; one MCP endpoint | — Pending |
| Shared services are service-scoped, harness-independent | Lets `claude+hindsight` and `omp+hindsight` share one memory volume | — Pending |
| Claude Code format canonical; omp via bridge | Single source of truth, no re-authoring; one harness per stack | — Pending |
| Hand-authored recipes assembled ahead of time (not dynamic) | Reproducible, committed artifacts; "not dynamic" | — Pending |
| Split output: committed→mounted profile (files) + baked→images (MCP deps) | Editable/versioned extensions; clean/pinned host | — Pending |
| pnpm everywhere with managed supply-chain config | Quarantine new releases, deny lifecycle scripts, store integrity | — Pending |
| `harnessed-tools` is a file-emitting assembler; host runs podman build/run | Only host dep is podman/docker; avoids DooD (no socket, no host-path footgun, clean TTY) | — Pending |
| Default persistent, `--fresh` to wipe | Accumulation is the value of memory systems; `--fresh` for clean-room runs | — Pending |
| Integration-only testing, manifest as oracle | Tests survive refactors; capability report doubles as user artifact | — Pending |
| varlock + 1Password optional (opt-in) | Works fully without it; copy `.env.schema.example` to turn on | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-06-14 after initialization*
