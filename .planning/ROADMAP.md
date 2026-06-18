# Roadmap: harnessed

## Overview

harnessed grows from this repo's `container` tool into a launcher for isolated, composable harness
stacks. The journey starts at the foundation (a host bash bootstrap/launcher + host `podman build`,
and the `transparent` stack that re-delivers `container` with zero regression), proves the
core value on one thin isolated tracer-bullet stack (assemble → run → assert green), hardens the
build with a supply-chain gate, then adds shared services, recipe breadth, and the full operable CLI,
and finishes with opt-in secrets and the gated documentation surface. Each phase delivers an
observable end-to-end capability (vertical-MVP mode).

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

- [x] **Phase 1: Containerized Engine + Transparent Stack** - Host bash bootstrap/launcher + host `podman build`; `harnessed transparent`/`container` re-delivers the host-mirror sandbox (completed 2026-06-15)
- [x] **Phase 2: Isolated Tracer-Bullet Stack** - One harness + one MCP server + one skill, isolated and reproducible, asserted green by the capability test (completed 2026-06-15)
- [x] **Phase 3: Supply-Chain Gate + pnpm-Everywhere** - `harnessed build` vets every dependency before it is committed or baked (completed 2026-06-15)
- [x] **Phase 4: Shared Services + Recipe Breadth + Full CLI** - Concurrent service sidecars, more recipes, and the full operable command/lifecycle surface (completed 2026-06-16)
- [x] **Phase 5: Secrets, Hardening + Docs Completeness** - Opt-in varlock/1Password secrets, token-gated scanners, nightly re-scan, and the gated doc set (completed 2026-06-18)

## Phase Details

### Phase 1: Containerized Engine + Transparent Stack

**Goal**: Stand up the dependency-free `harnessed` bash bootstrap, build the base/claude images via host `podman build`, and deliver the `transparent` stack (= today's `container`, host-mirror) as a host launcher with the `.claude.json` safety fix and zero behavioral regression. (No daemon-in-container — the `harnessed-tools` assembler arrives in Phase 2.)
**Mode:** mvp
**Depends on**: Nothing (first phase)
**Requirements**: ENG-01, ENG-02, ENG-03, MODE-01, MODE-02, AUTH-01, MNT-01, MNT-02, MNT-03
**Success Criteria** (what must be TRUE):

  1. Running `harnessed transparent` (and `container`) in a project opens an interactive harness with the host config mounted live and the project mounted
  2. The instance has a working SSH agent, GPG/YubiKey commit signing, and the egress firewall (the shared host-integration layer)
  3. On a machine with only podman installed, the first run builds the images and launches — no host Python/node/uv required
  4. A run never corrupts the host `~/.claude.json` (per-instance copy or `CLAUDE_CONFIG_DIR` relocation, verified)

**Plans**: 3 plans

Plans:

- [x] 01-01: `harnessed` bash bootstrap (detect runtime, ensure images) + base/claude image lineage (`/home/harnessed` home) built via host `podman build`
- [x] 01-02: §4a host-integration mount layer (auth/SSH/GPG/YubiKey/git/machine-id) + project mount + egress firewall (host launcher building blocks)
- [x] 01-03: `transparent` host launcher (live host config) + `container` alias + `~/.claude.json` copy-on-start safety

### Phase 2: Isolated Tracer-Bullet Stack

**Goal**: Prove the core value on the smallest end-to-end isolated slice — one harness + one MCP server + one skill — via recipe/stack schema, the build-time assembler, isolated auth seeding, runtime pod composition with hatago, and the capability test/report.
**Mode:** mvp
**Depends on**: Phase 1
**Requirements**: MODE-03, AUTH-02, RCP-01, RCP-02, RCP-03, RCP-04, MCP-01, MCP-02, MCP-03, TST-01, TST-02
**Success Criteria** (what must be TRUE):

  1. `harnessed build <stack>` assembles a one-harness/one-MCP-server/one-skill recipe into a committed `profiles/<stack>/` tree + baked images, failing fast on a name collision
  2. `harnessed <stack> --fresh` launches an isolated pod (harness + hatago) that boots headlessly with no onboarding/login prompt
  3. The instance exposes exactly the declared MCP server and skill, reached through hatago's single Streamable-HTTP endpoint
  4. The per-stack capability test passes and renders a markdown report showing the declared capabilities present

**Plans**: 3 plans
Plans:
**Wave 1**

- [x] 02-01: Recipe + stack schema and the build-time assembler (vendor + sync-links fan with fail-fast collisions + hook wiring + hatago config merge)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 02-02: Isolated auth seeding (`.credentials.json` ro + generated `.claude.json` stub, headless no-prompt test) + runtime pod composition (harness + hatago on harnessed-net)

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 02-03: Per-stack capability test + `rich` markdown capability report

### Phase 3: Supply-Chain Gate + pnpm-Everywhere

**Goal**: As a stack author, I want to build stacks knowing `harnessed build` enforces pnpm-everywhere managed config and a credential-free HIGH-severity scan gate, so that no dependency with a high-severity vulnerability is committed or baked into an image.
**Mode:** mvp
**Depends on**: Phase 2
**Requirements**: BLD-01, BLD-02, BLD-03
**Success Criteria** (what must be TRUE):

  1. `harnessed build` fails when a vendored dependency has a high-severity vulnerability (osv-scanner / pip-audit)
  2. All JavaScript installs go through pnpm with the managed supply-chain config (`minimumReleaseAge`, lifecycle default-deny, store integrity) active
  3. A recipe using raw `npm`/`npx` is flagged by validation with the pnpm equivalent

**Plans**: 2 plans

Plans:

- [x] 03-01: pnpm-everywhere managed config (BLD-01) — ship lib/pnpm/config.yaml, pin pnpm@11, route mise through pnpm, COPY config into base/hatago/tools/legacy images; correct design §7 + CLAUDE.md stale claims
- [x] 03-02: credential-free scan gate (BLD-02) + raw npm/npx recipe lint (BLD-03) — osv-scanner offline DB + pip-audit with a CVSS>=HIGH Python gate wired into build_stack (scoped source scan + host image scan); validate_no_raw_npm in the assembler fail-fast path

### Phase 4: Shared Services + Recipe Breadth + Full CLI

**Goal**: As a stack operator, I want to run concurrent harness instances that share service-scoped sidecars and operate the full stack, instance, and session lifecycle through the `harnessed` CLI, so that multiple instances can run together over a shared network, I can add more recipes to a stack, and every lifecycle action works predictably by name with default persistence and clean-room `--fresh` runs.
**Mode:** mvp
**Depends on**: Phase 3
**Requirements**: SVC-01, SVC-02, SVC-03, STA-01, STA-02, CLI-01, CLI-02, CLI-03, HRN-01
**Success Criteria** (what must be TRUE):

  1. `harnessed svc up <service>` starts a service-scoped shared sidecar that two concurrent instances attach to over `harnessed-net`
  2. A second recipe added to a stack is exposed by the running instance and verified by its own capability test
  3. `harnessed list|stop|rm`, `new`, and `install`/`uninstall` shims operate stacks and instances by name
  4. Stacks persist by default and `--fresh` yields a clean-room run; harness session history persists host-side with a legible slug
  5. An `omp` stack runs the same Claude-canonical recipes via `claude-hooks-bridge` + pi-adapter

**Plans**: 4 plans (3 planned + 1 gap-closure)

Plans:

- [x] 04-01: Shared service sidecars (image/volume/lifecycle) + `svc up/down/list` + concurrent attach over harnessed-net
- [x] 04-02: State persistence + `--fresh` + full CLI (`list`/`stop`/`rm`/`new`/`install`/`uninstall` shims)
- [x] 04-03: omp harness support via bridge + a second recipe with its own capability test
- [x] 04-04: UAT gap closure — bare `harnessed` shows help (gap 6B) + legible path-based state-dir slug (gap 6)

### Phase 5: Secrets, Hardening + Docs Completeness

**Goal**: Land the perimeter/policy and the gated documentation surface — opt-in varlock/1Password secrets, token-gated scanners, the auth command, a nightly re-scan timer, and the full doc set.
**Mode:** mvp
**Depends on**: Phase 4
**Requirements**: SEC-01, SEC-02, SEC-03, SEC-04, DOC-01, DOC-02, DOC-03
**Success Criteria** (what must be TRUE):

  1. With a `.env.schema` present, secrets resolve from 1Password and reach the build/instance as env only; absent, varlock is never invoked
  2. `harnessed build` runs token-gated scanners (snyk/Socket.dev) when a token is present and warns-and-skips otherwise without prompting
  3. `harnessed auth snyk|socket` persists a token to host config (never an image layer), and a nightly timer re-scans installed images for new CVEs
  4. README + recipe/stack guides + secrets/service/troubleshooting docs exist and match shipped behavior

**Plans**: 4 plans
Plans:
**Wave 1**

- [x] 05-01-PLAN.md — Scanner CLIs baked into tools image (Node+varlock+op+snyk+socket) + token-gated snyk/socket invokers in scan.py + build_stack token forwarding (SEC-02)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 05-02-PLAN.md — Opt-in varlock/1Password secrets (resolve_secret_env + --env-file to pod) + `harnessed auth snyk|socket` + docs/guides/secrets.md (SEC-01, SEC-03, DOC-03)

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 05-03-PLAN.md — Nightly re-scan timer: scan-image-online + `harnessed rescan` + systemd user-timer units (SEC-04)

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 05-04-PLAN.md — Documentation surface: README + recipe-authoring/stacks/service-authoring/troubleshooting guides + AGENTS.md reconciliation (DOC-01, DOC-02, DOC-03)

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Containerized Engine + Transparent Stack | 3/3 | Complete   | 2026-06-15 |
| 2. Isolated Tracer-Bullet Stack | 3/3 | Complete    | 2026-06-15 |
| 3. Supply-Chain Gate + pnpm-Everywhere | 2/2 | Complete    | 2026-06-16 |
| 4. Shared Services + Recipe Breadth + Full CLI | 4/4 | Complete   | 2026-06-17 |
| 5. Secrets, Hardening + Docs Completeness | 4/4 | Complete   | 2026-06-18 |
