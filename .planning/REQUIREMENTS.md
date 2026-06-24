# Requirements: harnessed

**Defined:** 2026-06-14
**Core Value:** Compose a named stack (one harness + chosen recipes) and launch an isolated, authenticated instance that exposes exactly the skills/commands/MCP/services it declares — nothing from the host config — reproducibly, with podman as the only host dependency.

## v1 Requirements

Requirements for the initial release. Each maps to exactly one roadmap phase.

### Engine

- [x] **ENG-01**: A dependency-free `harnessed` bash bootstrap detects podman/docker and builds required images on first run (`--build` to force)
- [x] **ENG-02**: harnessed builds images via host `podman build` and launches stacks via a generated host-bash launcher using host `podman` — no daemon-in-container (no Docker-out-of-Docker); the only host dependency is podman/docker
- [x] **ENG-03**: The final interactive harness attach runs host-natively for a clean TTY

### Modes

- [x] **MODE-01**: `harnessed transparent [path]` launches a host-mirror instance (host `~/.claude` + `.codex`/`.config/opencode`/`.gemini` mounted live)
- [x] **MODE-02**: `container` invokes `harnessed transparent` as a thin alias with the same behavior as today
- [x] **MODE-03**: `harnessed <stack> [path]` (isolated) mounts only the assembled profile — no host config layer

### Auth

- [x] **AUTH-01**: Transparent instances are authenticated via the live-mounted host config (no re-login)
- [x] **AUTH-02**: Isolated instances authenticate by mounting `~/.claude/.credentials.json` read-only plus a generated `.claude.json` stub that boots headlessly with no onboarding/login prompt

### Mounts

- [x] **MNT-01**: Every stack mounts the host-integration layer (1Password SSH agent, GPG/YubiKey signing, `~/.ssh` ro, git config ro, `/etc/machine-id` ro)
- [x] **MNT-02**: Every stack mounts the project at a stable in-container path and applies the egress firewall
- [x] **MNT-03**: `~/.claude.json` is never rw-bind-mounted; transparent mode gets a writable per-instance copy (copy-on-start or `CLAUDE_CONFIG_DIR`)

### Recipes

- [x] **RCP-01**: A recipe (`recipes/<name>/recipe.yaml`) declares an MCP layer and/or a Claude-canonical file-extension layer
- [x] **RCP-02**: A stack manifest (`stacks/<name>/stack.yaml`) composes a harness plus a chosen set of recipes (and optional services/permissions/state)
- [x] **RCP-03**: `harnessed build <stack>` runs the assembler in the `harnessed-tools` container, which emits a `Dockerfile` (+ build context) + a committed `profiles/<stack>/` tree + a generated launcher; the host then runs `podman build` to produce baked images — nothing is assembled at container start
- [x] **RCP-04**: The assembler fans plugin skills/commands into harness-native paths and fails fast on name collisions

### MCP

- [x] **MCP-01**: A running isolated stack is a podman pod (harness container + hatago) on `harnessed-net`
- [x] **MCP-02**: hatago aggregates the stack's MCP servers behind one Streamable-HTTP endpoint that the harness `.mcp.json` points at
- [x] **MCP-03**: Light stdio MCP servers run as hatago children (stdio→HTTP), baked into the hatago image

### Testing

- [x] **TST-01**: A per-stack capability test asserts a live `--fresh` headless instance exposes exactly the MCP servers/skills/commands its manifest declares
- [x] **TST-02**: The capability check renders a markdown capability report (per-capability status table)

### Build

- [x] **BLD-01**: All JavaScript installs (global, per-recipe, hatago servers) use pnpm with managed supply-chain config (`minimumReleaseAge`, lifecycle default-deny, store integrity)
- [x] **BLD-02**: `harnessed build` runs osv-scanner + pip-audit (credential-free) and fails on high-severity findings
- [x] **BLD-03**: Recipe validation flags any raw `npm`/`npx` usage and points at the pnpm equivalent

### Services

- [x] **SVC-01**: A shared service sidecar (e.g. hindsight, openbrain) runs as its own image/container with a service-scoped volume
- [x] **SVC-02**: Multiple instances attach concurrently to one running shared service over `harnessed-net`
- [x] **SVC-03**: `harnessed svc up|down|list` manages shared services independently of any instance

### State

- [x] **STA-01**: Stacks are persistent by default; `--fresh` starts with empty throwaway state volumes
- [x] **STA-02**: Harness session state (`projects/` + `history.jsonl`) persists host-side with a legible Claude session slug

### CLI

- [x] **CLI-01**: `harnessed list|stop|rm` manage stacks and running instances
- [x] **CLI-02**: `harnessed new <stack> --harness <h> --recipes a,b,c` scaffolds a stack manifest
- [x] **CLI-03**: `harnessed install|uninstall <stack>` writes/removes a `~/.local/bin/<stack>` launcher shim

### Harness

- [x] **HRN-01**: A stack targets exactly one harness (`claude` or `omp`); omp consumes Claude-canonical extensions via `claude-hooks-bridge` + pi-adapter

### Secrets & Hardening

- [x] **SEC-01**: varlock + 1Password secrets are opt-in via `.env.schema` (inert when absent) and injected as env only — never baked or committed
- [x] **SEC-02**: Token-gated scanners (snyk/Socket.dev) run when a token is present and warn-and-skip otherwise, keeping `harnessed build` non-interactive
- [x] **SEC-03**: `harnessed auth snyk|socket` sets a scanner token once, persisted to host config (never an image layer)
- [x] **SEC-04**: A nightly re-scan timer re-runs osv-scanner against installed images to catch post-build CVEs

### Documentation

- [x] **DOC-01**: README documents what harnessed is, the two modes, install, first-run build, and a quickstart
- [x] **DOC-02**: Recipe-authoring and stack guides document writing recipes/stacks with a worked example
- [x] **DOC-03**: Secrets-setup, service-authoring, and troubleshooting/ops docs exist

## v2.0 Requirements — Recipe Architecture & Agent Rebuild (Active)

Active requirements for the v2.0 milestone. Each maps to a phase in ROADMAP.md.

### Image Lineage

- [ ] **IMG-01**: Fat `harnessed-base` with all runtimes pre-installed (mise, node@24, bun, rust, go, python, pnpm@11, 1Password CLI, osv-scanner, yq, jq, git, common dev tools, egress firewall, pnpm supply-chain config). **No harness CLIs in base** — harnesses move to per-agent images.
- [ ] **IMG-02**: `agents/` directory — `type:agent` recipe entries that build standalone cached harness images (`harnessed-claude`, `harnessed-omp`) via `FROM harnessed-base + one harness CLI + config-baking`.
- [ ] **IMG-03**: `harnessed-<stack>` derived image: `FROM harnessed-<agent>` + recipe Dockerfile bodies concatenated by the assembler; one image per stack, built by the host via `podman build`.

### Recipe Model

- [ ] **RCP2-01**: A recipe is a **directory** containing `Dockerfile` + `recipe.yaml`. The Dockerfile runs the framework's own installer, parameterized by `--host ${HARNESS}`, pinned to a tag or SHA (no floating branches). `recipe.yaml` declares `harnesses:`, `mcp:` (optional), `expect:` (optional).
- [ ] **RCP2-02**: `harnesses:` field declares which harnesses the recipe's installer supports; assembler refuses unsupported compositions with a clean human-readable error.
- [ ] **RCP2-03**: `expect:` is a smoke-check subset (stable entries confirming install landed), not a completeness oracle. A framework shipping more than listed is success; fewer is failure.

### Assembler

- [ ] **ASM-01**: Harness-compatibility check: assembler validates `recipe.harnesses` vs `stack.harness` before emitting any Dockerfile. Incompatible compositions are a validation error (not a build error).
- [ ] **ASM-02**: Pin validation: floating refs (`--branch main`, `--branch master`, unversioned `latest`) in a recipe Dockerfile are a validation error. Only pinned refs accepted.
- [ ] **ASM-03**: Assembler emits `profiles/<stack>/Dockerfile.harnessed-<stack>` with `ARG HARNESS=<agent>` and concatenated recipe bodies. Host runs `podman build --build-arg HARNESS=<agent>`. Assembler emits files only — does not invoke `podman build`.

### Profile Mount

- [x] **MNT2-01**: Surgical config-file mount — launcher mounts individual config files (`.mcp.json`, `settings.json`; per-harness equivalents for omp/opencode/etc.), not the whole `~/.claude/` dir. Image-baked skills survive (no dir-replace).
- [x] **MNT2-02**: Path mirroring — container working directory set to the **identical absolute host path** of the project (`--workdir $HOST_PWD`). Ensures Claude project slug, omp session slug, and antigravity `workspace` key all match the host; embedded transcript paths are host-coherent; DooD `-v $PWD:$PWD` requires no translation.
- [x] **MNT2-03**: Claude Code history surfacing — for claude stacks: rw-mount `projects/<slug>/`, `file-history/`, `tasks/`, `session-env/`, `todos/`. `history.jsonl` surfaced via guarded teardown merge (ships disabled). Config dirs never mounted.
- [x] **MNT2-04**: omp history surfacing — rw-mount `agent/sessions/<project-slug>/` and optionally `agent/blobs/`. `history.db` via guarded teardown export by `cwd` (ships disabled). `agent.db` **never** mounted (co-locates `auth_credentials`).
- [x] **MNT2-05**: antigravity history surfacing — rw-mount `antigravity-cli/conversations/`, `antigravity-cli/brain/`, `antigravity-cli/implicit/` (UUID-named, collision-free). `history.jsonl` + `cache/projects.json` + `cache/last_conversations.json` via guarded teardown merge (ships disabled). `antigravity-oauth-token` and `~/.gemini/` proper never mounted.
- [x] **MNT2-06**: Data-driven mount manifests — the mount/teardown set for each harness is defined in a structured per-harness config, not inline `-v` flags.
- [ ] **MNT2-07**: opencode and codex history layouts are **to be investigated** during their execution phases (see `docs/research/home-folder-harness-history-overview.md`). Each investigation produces a `home-folder-<harness>-requirements.md` and a manifest entry. Gates opencode/codex stack completion but does not block claude/omp/antigravity phases.

### Supply Chain

- [ ] **SC-01**: Assembler pin gate (ASM-02) + post-build osv-scanner V2 image scan of `harnessed-<stack>:latest`. High-severity CVEs fail the build. Credential-free, always-on.
- [ ] **SC-02**: Nightly rescan timer extended to cover `harnessed-<stack>` images. Known limitation documented: vendor `./setup` shelling raw `npm install` bypasses pnpm supply-chain policy — accepted, not blocking.
- [ ] **SC-03**: Snyk container scan on derived image — warn-and-skip when `SNYK_TOKEN` absent; runs `snyk container test harnessed-<stack>:latest --severity-threshold=high` when present. **Never prompts; build stays non-interactive.** Token set via `harnessed auth snyk`.
- [ ] **SC-04**: Socket.dev analysis on derived image — warn-and-skip when `SOCKET_SECURITY_API_KEY` absent; runs when present. **Never prompts.** Token set via `harnessed auth socket`.

### Capability Test

- [ ] **TST2-01**: Structured MCP probe — assert all `mcp.servers` in `hatago.config.json` appear in `hatago /servers`. Deterministic, no model call.
- [ ] **TST2-02**: Un-primed ask-the-agent skills/tools probe with negative control — merged `expect:` entries + one decoy shuffled; agent asked for JSON `{"have":[...],"missing":[...]}` with no enumeration prompt. Decoy in `"have"` → **INVALID** exit (priming detected, distinct from capability failure). Any `expect:` entry in `"missing"` → capability failure.
- [ ] **TST2-03**: Markdown capability report — ✓/✗ per MCP server (TST2-01) and per `expect:` entry (TST2-02); INVALID banner on priming detection; written to `profiles/<stack>/capability-report.md`.

### Documentation

- [x] **DOC2-01**: All narrative docs updated to new architecture (fat base, Dockerfile recipes, 3-layer lineage, surgical mount, supply-chain gate, combined capability test). No "isolated"/"transparent" terminology remains. Each new feature lands with its doc section.

---

## v2 Requirements — Future (Deferred)

Deferred to a future release. Tracked but not in the current roadmap.

### Future

- **TUI-01**: A `textual` TUI (stack picker / live build dashboard) beyond `rich` reports
- **TOOLS-IMG-01**: A prebuilt/published `harnessed-tools` image to cut first-run build latency
- **SEC-05**: Per-stack secret overrides referenced from `stack.yaml`
- **PORT-01**: Multi-project / cross-machine stack portability conventions

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Combine systems via Docker `FROM`-union | `FROM` is linear inheritance + multi-stage `COPY`; no union operator — systems combine at runtime in a pod |
| Dynamic / runtime recipe assembly | Non-reproducible, un-reviewable; assemble ahead of time into committed artifacts |
| More than one harness per stack | Doubles config surface, ambiguous canonical format, conflicting hook dispatch |
| A second canonical config format | Claude Code format is the single source of truth; omp adapts out of it via bridge |
| npm / npx for JS installs | No release-age cooldown, lifecycle scripts run by default — weaker supply-chain posture |
| Assembler unit tests | Couples tests to implementation; behavior verified transitively through the running instance |
| Requiring host Python/node/uv | podman/docker is the only host dependency; logic lives in the containerized tool |
| A GUI / dashboard | Oversized surface for a personal dev tool; CLI + `rich` capability report suffices |
| Baking or committing credentials | Exfiltration risk; auth and secrets are env-only, referenced from host |

## Traceability

Which phase covers which requirement.

| Requirement | Phase | Status |
|-------------|-------|--------|
| ENG-01 | Phase 1 | Complete |
| ENG-02 | Phase 1 | Complete |
| ENG-03 | Phase 1 | Complete |
| MODE-01 | Phase 1 | Complete |
| MODE-02 | Phase 1 | Complete |
| AUTH-01 | Phase 1 | Complete |
| MNT-01 | Phase 1 | Complete |
| MNT-02 | Phase 1 | Complete |
| MNT-03 | Phase 1 | Complete |
| MODE-03 | Phase 2 | Complete |
| AUTH-02 | Phase 2 | Complete |
| RCP-01 | Phase 2 | Complete |
| RCP-02 | Phase 2 | Complete |
| RCP-03 | Phase 2 | Complete |
| RCP-04 | Phase 2 | Complete |
| MCP-01 | Phase 2 | Complete |
| MCP-02 | Phase 2 | Complete |
| MCP-03 | Phase 2 | Complete |
| TST-01 | Phase 2 | Complete |
| TST-02 | Phase 2 | Complete |
| BLD-01 | Phase 3 | Complete |
| BLD-02 | Phase 3 | Complete |
| BLD-03 | Phase 3 | Complete |
| SVC-01 | Phase 4 | Complete |
| SVC-02 | Phase 4 | Complete |
| SVC-03 | Phase 4 | Complete |
| STA-01 | Phase 4 | Complete |
| STA-02 | Phase 4 | Complete |
| CLI-01 | Phase 4 | Complete |
| CLI-02 | Phase 4 | Complete |
| CLI-03 | Phase 4 | Complete |
| HRN-01 | Phase 4 | Complete |
| SEC-01 | Phase 5 | Complete |
| SEC-02 | Phase 5 | Complete |
| SEC-03 | Phase 5 | Complete |
| SEC-04 | Phase 5 | Complete |
| DOC-01 | Phase 5 | Complete |
| DOC-02 | Phase 5 | Complete |
| DOC-03 | Phase 5 | Complete |

**v1.0 Coverage:**

- v1 requirements: 39 total
- Mapped to phases: 39
- Unmapped: 0 ✓

**v2.0 Coverage:**

| Requirement | Phase | Status |
|-------------|-------|--------|
| IMG-01 | Phase 7 | Pending |
| IMG-02 | Phase 7 | Pending |
| IMG-03 | Phase 8 | Pending |
| RCP2-01 | Phase 8 | Pending |
| RCP2-02 | Phase 8 | Pending |
| RCP2-03 | Phase 8 | Pending |
| ASM-01 | Phase 8 | Pending |
| ASM-02 | Phase 8 | Pending |
| ASM-03 | Phase 8 | Pending |
| MNT2-01 | Phase 9 | Complete |
| MNT2-02 | Phase 9 | Complete |
| MNT2-03 | Phase 9 | Complete |
| MNT2-04 | Phase 9 | Complete |
| MNT2-05 | Phase 9 | Complete |
| MNT2-06 | Phase 9 | Complete |
| MNT2-07 | Phase 10 | Pending |
| SC-01 | Phase 8 | Pending |
| SC-02 | Phase 8 | Pending |
| SC-03 | Phase 8 | Pending |
| SC-04 | Phase 8 | Pending |
| TST2-01 | Phase 10 | Pending |
| TST2-02 | Phase 10 | Pending |
| TST2-03 | Phase 10 | Pending |
| DOC2-01 | Phase 11 | Complete |

- v2.0 requirements: 24 total
- Mapped to phases: 24
- Unmapped: 0 ✓

---
*Requirements defined: 2026-06-14*
*Last updated: 2026-06-23 — v2.0 milestone requirements added (24 requirements across 7 categories); phase assignments populated (Phases 7–11)*
