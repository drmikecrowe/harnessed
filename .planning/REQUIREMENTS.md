# Requirements: harnessed

**Defined:** 2026-06-14
**Core Value:** Compose a named stack (one harness + chosen recipes) and launch an isolated, authenticated instance that exposes exactly the skills/commands/MCP/services it declares — nothing from the host config — reproducibly, with podman as the only host dependency.

## v1 Requirements

Requirements for the initial release. Each maps to exactly one roadmap phase.

### Engine

- [ ] **ENG-01**: A dependency-free `harnessed` bash bootstrap detects podman/docker and builds required images on first run (`--build` to force)
- [ ] **ENG-02**: harnessed builds images via host `podman build` and launches stacks via a generated host-bash launcher using host `podman` — no daemon-in-container (no Docker-out-of-Docker); the only host dependency is podman/docker
- [ ] **ENG-03**: The final interactive harness attach runs host-natively for a clean TTY

### Modes

- [ ] **MODE-01**: `harnessed transparent [path]` launches a host-mirror instance (host `~/.claude` + `.codex`/`.config/opencode`/`.gemini` mounted live)
- [ ] **MODE-02**: `container` invokes `harnessed transparent` as a thin alias with the same behavior as today
- [ ] **MODE-03**: `harnessed <stack> [path]` (isolated) mounts only the assembled profile — no host config layer

### Auth

- [ ] **AUTH-01**: Transparent instances are authenticated via the live-mounted host config (no re-login)
- [ ] **AUTH-02**: Isolated instances authenticate by mounting `~/.claude/.credentials.json` read-only plus a generated `.claude.json` stub that boots headlessly with no onboarding/login prompt

### Mounts

- [ ] **MNT-01**: Every stack mounts the host-integration layer (1Password SSH agent, GPG/YubiKey signing, `~/.ssh` ro, git config ro, `/etc/machine-id` ro)
- [ ] **MNT-02**: Every stack mounts the project at a stable in-container path and applies the egress firewall
- [ ] **MNT-03**: `~/.claude.json` is never rw-bind-mounted; transparent mode gets a writable per-instance copy (copy-on-start or `CLAUDE_CONFIG_DIR`)

### Recipes

- [ ] **RCP-01**: A recipe (`recipes/<name>/recipe.yaml`) declares an MCP layer and/or a Claude-canonical file-extension layer
- [ ] **RCP-02**: A stack manifest (`stacks/<name>/stack.yaml`) composes a harness plus a chosen set of recipes (and optional services/permissions/state)
- [ ] **RCP-03**: `harnessed build <stack>` runs the assembler in the `harnessed-tools` container, which emits a `Dockerfile` (+ build context) + a committed `profiles/<stack>/` tree + a generated launcher; the host then runs `podman build` to produce baked images — nothing is assembled at container start
- [ ] **RCP-04**: The assembler fans plugin skills/commands into harness-native paths and fails fast on name collisions

### MCP

- [ ] **MCP-01**: A running isolated stack is a podman pod (harness container + hatago) on `harnessed-net`
- [ ] **MCP-02**: hatago aggregates the stack's MCP servers behind one Streamable-HTTP endpoint that the harness `.mcp.json` points at
- [ ] **MCP-03**: Light stdio MCP servers run as hatago children (stdio→HTTP), baked into the hatago image

### Testing

- [ ] **TST-01**: A per-stack capability test asserts a live `--fresh` headless instance exposes exactly the MCP servers/skills/commands its manifest declares
- [ ] **TST-02**: The capability check renders a markdown capability report (per-capability status table)

### Build

- [ ] **BLD-01**: All JavaScript installs (global, per-recipe, hatago servers) use pnpm with managed supply-chain config (`minimumReleaseAge`, lifecycle default-deny, store integrity)
- [ ] **BLD-02**: `harnessed build` runs osv-scanner + pip-audit (credential-free) and fails on high-severity findings
- [ ] **BLD-03**: Recipe validation flags any raw `npm`/`npx` usage and points at the pnpm equivalent

### Services

- [ ] **SVC-01**: A shared service sidecar (e.g. hindsight, openbrain) runs as its own image/container with a service-scoped volume
- [ ] **SVC-02**: Multiple instances attach concurrently to one running shared service over `harnessed-net`
- [ ] **SVC-03**: `harnessed svc up|down|list` manages shared services independently of any instance

### State

- [ ] **STA-01**: Stacks are persistent by default; `--fresh` starts with empty throwaway state volumes
- [ ] **STA-02**: Harness session state (`projects/` + `history.jsonl`) persists host-side with a legible Claude session slug

### CLI

- [ ] **CLI-01**: `harnessed list|stop|rm` manage stacks and running instances
- [ ] **CLI-02**: `harnessed new <stack> --harness <h> --recipes a,b,c` scaffolds a stack manifest
- [ ] **CLI-03**: `harnessed install|uninstall <stack>` writes/removes a `~/.local/bin/<stack>` launcher shim

### Harness

- [ ] **HRN-01**: A stack targets exactly one harness (`claude` or `omp`); omp consumes Claude-canonical extensions via `claude-hooks-bridge` + pi-adapter

### Secrets & Hardening

- [ ] **SEC-01**: varlock + 1Password secrets are opt-in via `.env.schema` (inert when absent) and injected as env only — never baked or committed
- [ ] **SEC-02**: Token-gated scanners (snyk/Socket.dev) run when a token is present and warn-and-skip otherwise, keeping `harnessed build` non-interactive
- [ ] **SEC-03**: `harnessed auth snyk|socket` sets a scanner token once, persisted to host config (never an image layer)
- [ ] **SEC-04**: A nightly re-scan timer re-runs osv-scanner against installed images to catch post-build CVEs

### Documentation

- [ ] **DOC-01**: README documents what harnessed is, the two modes, install, first-run build, and a quickstart
- [ ] **DOC-02**: Recipe-authoring and stack guides document writing recipes/stacks with a worked example
- [ ] **DOC-03**: Secrets-setup, service-authoring, and troubleshooting/ops docs exist

## v2 Requirements

Deferred to a future release. Tracked but not in the current roadmap.

### Future

- **TUI-01**: A `textual` TUI (stack picker / live build dashboard) beyond `rich` reports
- **IMG-01**: A prebuilt/published `harnessed-tools` image to cut first-run build latency
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
| ENG-01 | Phase 1 | Pending |
| ENG-02 | Phase 1 | Pending |
| ENG-03 | Phase 1 | Pending |
| MODE-01 | Phase 1 | Pending |
| MODE-02 | Phase 1 | Pending |
| AUTH-01 | Phase 1 | Pending |
| MNT-01 | Phase 1 | Pending |
| MNT-02 | Phase 1 | Pending |
| MNT-03 | Phase 1 | Pending |
| MODE-03 | Phase 2 | Pending |
| AUTH-02 | Phase 2 | Pending |
| RCP-01 | Phase 2 | Pending |
| RCP-02 | Phase 2 | Pending |
| RCP-03 | Phase 2 | Pending |
| RCP-04 | Phase 2 | Pending |
| MCP-01 | Phase 2 | Pending |
| MCP-02 | Phase 2 | Pending |
| MCP-03 | Phase 2 | Pending |
| TST-01 | Phase 2 | Pending |
| TST-02 | Phase 2 | Pending |
| BLD-01 | Phase 3 | Pending |
| BLD-02 | Phase 3 | Pending |
| BLD-03 | Phase 3 | Pending |
| SVC-01 | Phase 4 | Pending |
| SVC-02 | Phase 4 | Pending |
| SVC-03 | Phase 4 | Pending |
| STA-01 | Phase 4 | Pending |
| STA-02 | Phase 4 | Pending |
| CLI-01 | Phase 4 | Pending |
| CLI-02 | Phase 4 | Pending |
| CLI-03 | Phase 4 | Pending |
| HRN-01 | Phase 4 | Pending |
| SEC-01 | Phase 5 | Pending |
| SEC-02 | Phase 5 | Pending |
| SEC-03 | Phase 5 | Pending |
| SEC-04 | Phase 5 | Pending |
| DOC-01 | Phase 5 | Pending |
| DOC-02 | Phase 5 | Pending |
| DOC-03 | Phase 5 | Pending |

**Coverage:**
- v1 requirements: 39 total
- Mapped to phases: 39
- Unmapped: 0 ✓

---
*Requirements defined: 2026-06-14*
*Last updated: 2026-06-14 after initial definition*
