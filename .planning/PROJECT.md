# harnessed

## What This Is

`harnessed` is one executable that launches **containerized, composable harness stacks** — each
a podman pod running an AI coding harness (`claude`/`omp`/`opencode`/`gemini`/`antigravity`/`codex`)
plus an MCP hub (hatago) plus optional shared services. A **stack** is one harness + chosen
recipes; a **recipe** is a Dockerfile + a YAML manifest that runs a framework's own installer
(pinned to a tag/SHA). Each stack produces a separate derived image (`harnessed-<stack>`), so
`claude+gstack` and `claude+gsd` coexist without conflict.

It is for developers (initially the author) who want to compose and trial harness configurations
— different skill/plugin/MCP/memory combinations — in clean, reproducible, throwaway-or-persistent
environments without dragging every host default into the container or polluting `~`.

## Current State: v2.0 Shipped 2026-06-24

**Shipped:** 3-layer image lineage (harnessed-base → harnessed-<harness> → harnessed-<stack>);
Dockerfile recipe model (recipes run frameworks' own installers, pinned to tag/SHA); surgical profile
mounts (.mcp.json + settings.json only, image-baked skills survive); osv-scanner V2 supply-chain gate;
per-harness YAML mount manifests; full architecture documentation updated.

**Deferred to next milestone:** Phase 10 (opencode/codex history investigation + two-oracle capability test).

**Next milestone:** To be defined via `/gsd-new-milestone`. Key work: Phase 10 completion (TST2-01/02/03, MNT2-07) + additional harness support.

## Previous Milestone: v2.0 Recipe Architecture & Agent Rebuild ✅

**Goal:** Replace the typed-YAML recipe model with a Dockerfile-based model where recipes run frameworks' own installers, rebuild the image lineage into 3 layers (base → agent → stack), and validate with a combined capability test backed by a supply-chain gate.

**Target features:**
- Fat base (`harnessed-base`): all runtimes pre-installed (node@24, bun, rust, go, python, pnpm@11); NO harness CLIs in base
- `agents/` directory: `type:agent` recipes that build standalone cached harness images (`harnessed-claude`, `harnessed-omp`)
- Dockerfile-based recipe model: `recipe.yaml` (`harnesses:`, `mcp:`, `expect:`) + `Dockerfile` that runs the framework's own installer, pinned to a tag/SHA, with `--host ${HARNESS}`
- Assembler: harness-compatibility check, pin validation, Dockerfile body concatenation, `HARNESS` build ARG injection
- Surgical profile mount: `.mcp.json` + `settings.json` only — image-baked skills survive
- Supply-chain gate: assembler rejects unpinned sources; osv-scanner V2 scans derived image post-build; nightly rescan continues
- Combined capability test: structured MCP probe (deterministic) + un-primed ask-the-agent with negative control (decoy)
- Proof-of-concept: `recipes/gstack/` + `stacks/gstack-time/` verified green end-to-end

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
- ✓ `harnessed transparent` + `container` alias: host-mirror sandbox via the host-native harnessed engine (bash bootstrap + base/claude images, `podman build` on the host) — Phase 1
- ✓ `~/.claude.json` corruption fixed: per-instance copy-on-start (host whole-file blob never rw-bind-mounted) — Phase 1

### Active

<!-- v2.0 scope. Hypotheses until shipped and validated. -->

- [ ] **IMG-01**: Fat `harnessed-base` with all runtimes pre-installed (node@24, bun, rust, go, python, pnpm@11) — NO harness CLIs in base (harnesses move to per-agent images)
- [ ] **IMG-02**: `agents/` directory — `type:agent` recipes that build standalone cached harness images (`harnessed-claude`, `harnessed-omp`) via `FROM harnessed-base + one harness CLI`
- [ ] **IMG-03**: `harnessed-<stack>` derived image: `FROM harnessed-<agent>` + recipe Dockerfile bodies concatenated by the assembler; one per stack, built by the host
- [ ] **RCP-01**: Recipe is a `Dockerfile` + `recipe.yaml` (`harnesses:`, `mcp:`, `expect:`); `Dockerfile` runs the framework's own installer, parameterized by `--host ${HARNESS}`, pinned to a tag/SHA
- [ ] **RCP-02**: `harnesses:` field in `recipe.yaml` declares which harnesses the recipe's installer supports; assembler refuses unsupported compositions with a clean error
- [ ] **RCP-03**: `expect:` is a smoke-check subset (stable entries confirming the install landed, not a completeness oracle); assembled and passed to the capability test
- [ ] **ASM-01**: Assembler harness-compatibility check (recipe `harnesses:` vs stack `harness:`) before any Dockerfile emission
- [ ] **ASM-02**: Assembler pin validation — floating `--branch main` / unpinned package refs are a validation error; `git clone --branch <tag>` or exact version required
- [ ] **ASM-03**: Assembler emits `profiles/<stack>/Dockerfile.harnessed-<stack>` with `ARG HARNESS=<agent>` and concatenated recipe bodies; host runs `podman build --build-arg HARNESS=<agent>`
- [ ] **MNT-01**: Surgical profile mount — launcher mounts individual config files (`.mcp.json`, `settings.json`) not the whole `~/.claude/` dir; image-baked skills survive (no dir-replace)
- [ ] **SC-01**: Supply-chain gate on `harnessed build <stack>`: assembler rejects unpinned sources (ASM-02); osv-scanner V2 scans the derived image post-build; fail on high-severity
- [ ] **SC-02**: Nightly rescan timer rescans built stack images (existing systemd-timer pattern continues); residual known-limitation documented
- [ ] **TST-01**: Structured MCP probe: assert manifest's MCP servers connected via hatago `/servers` (deterministic, no model call)
- [ ] **TST-02**: Un-primed ask-the-agent skills/tools probe with negative control: a decoy entry mixed into the prompt; agent claimed-decoy-present → INVALID (priming detected), non-zero exit
- [ ] **TST-03**: Markdown capability report: ✓/✗ per MCP server (structured) and per `expect:` entry (agent); INVALID banner on priming detection
- [x] **DOC-01**: All narrative docs updated to new architecture — fat base, Dockerfile recipes, pinned sources, combined capability test; no "isolated"/"transparent" terminology remains — Validated in Phase 11: architecture-documentation

### Out of Scope

- Combining two harness systems via Docker `FROM` — `FROM` is linear inheritance, not a union operator; systems are combined at runtime in a pod (§6)
- More than one harness per stack — a stack targets exactly one harness, never two (§8)
- A second config canonical format — Claude Code format is the single source of truth; omp adapts out of it via bridge (§8)
- npm/npx for JavaScript installs — pnpm everywhere for supply-chain safety (§7)
- Assembler unit tests — testing internals couples to implementation; behavior is verified transitively through the running instance (§18)
- Requiring host Python/node/uv — podman/docker is the only host dependency (§15)
- Baking or committing credentials (Claude auth, scanner tokens, 1Password secrets) — referenced from host, injected as env only (§7, §16)
- Reinterpreting vendor framework installers — recipes run the framework's own `./setup`; the assembler does not parse skill trees or understand the framework's layout
- Version-controlling vendor skill data — the reproducibility unit is the pinned tag/SHA in the recipe, not a committed copy of the vendor's installed files
- Closing the pnpm-cooldown gap for vendor `./setup` scripts — a vendor installer shelling raw `npm install` bypasses our pnpm policy; documented known limitation, not a blocking issue (§8 supply-chain gate)
- `completeness oracle` capability tests — `expect:` is a smoke check (stable subset confirming install landed), not an enumeration of everything a framework ships

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
| One engine, two config modes (`transparent`/`isolated`) | Same base image/mounts/auth; differ only on config source — minimal surface, `transparent` = old `container` | ✓ transparent shipped (P1); isolated pending |
| Per-container merge, not host merge | Isolation removes the collision that killed the host-merge attempt | — Pending |
| Compose stacks at runtime in a podman pod | `FROM` can't union two sibling systems; runtime pod can | — Pending |
| hatago in the pod over HTTP (not stdio in harness container) | Keeps `npx`/`uvx` out of the harness container; one MCP endpoint | — Pending |
| Shared services are service-scoped, harness-independent | Lets `claude+hindsight` and `omp+hindsight` share one memory volume | — Pending |
| Claude Code format canonical; omp via bridge | Single source of truth, no re-authoring; one harness per stack | — Pending |
| Hand-authored recipes assembled ahead of time (not dynamic) | Reproducible, committed artifacts; "not dynamic" | — Pending |
| Split output: committed→mounted profile (files) + baked→images (MCP deps) | Editable/versioned extensions; clean/pinned host | — Pending |
| pnpm everywhere with managed supply-chain config | Quarantine new releases, deny lifecycle scripts, store integrity | — Pending |
| `harnessed-tools` is a file-emitting assembler; host runs podman build/run | Only host dep is podman/docker; avoids DooD (no socket, no host-path footgun, clean TTY) | ✓ host-native transparent shipped (P1) |
| Default persistent, `--fresh` to wipe | Accumulation is the value of memory systems; `--fresh` for clean-room runs | — Pending |
| Integration-only testing, manifest as oracle | Tests survive refactors; capability report doubles as user artifact | — Pending |
| varlock + 1Password optional (opt-in) | Works fully without it; copy `.env.schema.example` to turn on | — Pending |
| Bash launchers run under `set -euo pipefail`; fallible probes use `local var=$(…)` or `\|\| true` | A bare `var=$(pipeline)` aborts the launcher when the pipeline fails (e.g. YubiKey/jq probe with no match) — caught live in P1 | ✓ Good (P1 bugfix `a963a69`) |
| Recipes are Dockerfiles, not typed-YAML skill trees | "Run the framework's installer" — the assembler doesn't reinterpret the install/layout. Assembler does not parse SKILL.md files or discover skill trees. | — v2.0 |
| We version the recipe's tag, not the vendor's data | Pinned tag/SHA in recipe.yaml is the reproducibility unit; committed vendored skill trees were a mistake (required surveilling every install destination) | — v2.0 |
| Supply chain: pin + scan-the-image (not scan-vendored-deps) | Nothing is vendored; installer runs at build; gate = assembler rejects unpinned + osv-scanner V2 image scan + nightly rescan | — v2.0 |
| Harness is parameterized in recipe Dockerfiles (`--host ${HARNESS}`) | Recipe declares `harnesses:` it supports; assembler injects `ARG HARNESS` and refuses unsupported compositions with a clean error | — v2.0 |
| Capability test: two oracles, un-primed | Structured probe for MCP (deterministic); ask-the-agent for skills/tools with a negative control (decoy) to detect priming/sycophancy | — v2.0 |

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
*Last updated: 2026-06-23 — milestone v2.0 started (Recipe Architecture & Agent Rebuild). NOTE: the Active/Validated split from v1.0 was not fully migrated phase-by-phase — a full milestone review (`/gsd-complete-milestone`) should move v1.0 shipped items Active → Validated after v2.0 ships.*
