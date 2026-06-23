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
- [x] **Phase 5: Secrets, Hardening + Docs Completeness** - Opt-in varlock/1Password secrets, token-gated scanners, nightly re-scan, and the gated doc set (completed 2026-06-21; all 7 requirements VERIFIED live — HV-1..HV-4 all PASS, snyk browser auth landed via the --network=host callback fix)
- [x] **Phase 6: Address tech debt: dead harnessed-net code + stale comments + SUMMARY frontmatter hygiene** - Clear post-v1.0 tech debt: remove dead `harnessed-net` (podman network) code, correct stale comments, normalize `*-SUMMARY.md` frontmatter (planned; inserted 2026-06-21) (completed 2026-06-21)

## v2.0 Phases

- [ ] **Phase 7: Fat Base + Agent Images** - Rebuild harnessed-base as a fat toolchain image (no harness CLIs) and create standalone cached agent images for each harness CLI
- [ ] **Phase 8: Dockerfile Recipe Model + Assembler + Supply-Chain Gate** - Replace typed-YAML recipes with Dockerfile-based recipes; update the assembler to emit derived stack images; gate every derived build on pin validation and an osv-scanner image scan
- [ ] **Phase 9: Surgical Profile Mount + History Surfacing** - Stop mounting the whole profile directory; mount only individual config files so image-baked skills survive; surface per-harness project history (claude, omp, antigravity) to the host via data-driven manifests
- [ ] **Phase 10: opencode/codex Investigation + Combined Capability Test** - Investigate opencode and codex history layouts; replace the v1 capability test with the two-oracle approach (structured MCP probe + un-primed ask-the-agent with negative control)
- [ ] **Phase 11: Architecture Documentation** - Update all narrative docs to reflect the new architecture; remove stale terminology

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

### Phase 6: Address tech debt: dead harnessed-net code + stale comments + SUMMARY frontmatter hygiene

**Goal**: Clear accumulated tech debt after the v1.0 milestone — remove dead `harnessed-net` (podman network) code, correct stale comments across code and docs that no longer match shipped behavior, and normalize the `*-SUMMARY.md` frontmatter.
**Mode:** mvp
**Depends on**: Phase 5
**Requirements**: _(pending planning)_
**Success Criteria** (what must be TRUE):

  1. No dead `harnessed-net` code remains — every reference is live and reachable, or removed
  2. Stale comments (code + docs) that contradict shipped behavior are corrected
  3. Every phase `*-SUMMARY.md` carries consistent, well-formed frontmatter

**Plans**: _(pending planning — phase inserted, not yet planned)_

Plans:

- _(to be defined during planning)_

---

## v2.0 Phase Details

### Phase 7: Fat Base + Agent Images

**Goal**: Rebuild `harnessed-base` as a fat toolchain image (all runtimes pre-installed, no harness CLIs) and create the `agents/` directory with standalone cached images for the claude and omp harness CLIs.
**Depends on**: Phase 6 (v1.0 complete)
**Requirements**: IMG-01, IMG-02
**Success Criteria** (what must be TRUE):
  1. `harnessed-base` has bun, rust, go, node@24, python, pnpm@11 on PATH (`podman run harnessed-base mise ls` confirms); does NOT have claude, omp, codex, or gemini CLIs
  2. `harnessed-claude` builds `FROM harnessed-base` and passes `claude --version` inside the container without re-downloading runtimes
  3. `harnessed-omp` builds `FROM harnessed-base` and passes `omp --version` inside the container
  4. `harnessed build` (bare, no stack argument) produces `harnessed-base`, `harnessed-claude`, `harnessed-omp`, and `hatago` without error
**Plans**: 2 plans

Plans:

- [ ] 07-01-PLAN.md — Rebuild Dockerfile.harnessed-base: node@24, bun, rust, go; strip harness CLIs (IMG-01)
- [ ] 07-02-PLAN.md — agents/ directory (claude + omp agent.yaml) + build_images() wiring for bare build (IMG-02)

### Phase 8: Dockerfile Recipe Model + Assembler + Supply-Chain Gate

**Goal**: Replace the typed-YAML recipe model with a Dockerfile-based model where recipes run frameworks' own installers; update the assembler to perform harness-compat checks, pin validation, and Dockerfile body concatenation that emits a derived `harnessed-<stack>` image; gate every derived build on pin validation and an osv-scanner V2 image scan.
**Depends on**: Phase 7
**Requirements**: RCP2-01, RCP2-02, RCP2-03, ASM-01, ASM-02, ASM-03, IMG-03, SC-01, SC-02, SC-03, SC-04
**Success Criteria** (what must be TRUE):
  1. `harnessed build gstack-time` emits `profiles/gstack-time/Dockerfile.harnessed-gstack-time` with `ARG HARNESS=claude` and concatenated recipe bodies, then builds the derived image `harnessed-gstack-time`
  2. Composing a claude-only recipe (e.g. gstack) onto an omp stack produces a clean validation error before any Dockerfile is emitted or build step runs
  3. A recipe Dockerfile with a floating `--branch main` ref is rejected by the assembler with a pin-validation error; a pinned tag/SHA passes cleanly
  4. `harnessed build gstack-time` scans the derived image with osv-scanner V2 and fails the build on HIGH-severity CVEs; the nightly rescan timer covers `harnessed-<stack>` images; snyk/socket container scans run when tokens are present and warn-and-skip (without prompting) when absent
**Plans**: TBD
**UI hint**: no

### Phase 9: Surgical Profile Mount + History Surfacing

**Goal**: Stop mounting the whole `~/.claude/` profile directory; mount only individual config files (`.mcp.json`, `settings.json`, and per-harness equivalents) so image-baked recipe skills survive; surface per-harness project history for claude, omp, and antigravity back to the host via data-driven mount manifests.
**Depends on**: Phase 8
**Requirements**: MNT2-01, MNT2-02, MNT2-03, MNT2-04, MNT2-05, MNT2-06
**Success Criteria** (what must be TRUE):
  1. A running `gstack-time` instance shows gstack skills loaded — recipe-installed skills are visible because the profile dir-mount no longer overwrites the image's `~/.claude/skills/`
  2. `profiles/gstack-time/` contains only `.mcp.json` and `settings.json`; no `.claude/` directory tree is committed to the profile
  3. After a session, new claude project history entries appear on the host at `~/.claude/projects/<slug>/` without modifying the host `~/.claude.json` or credentials
  4. After a session, omp session history appears on the host at `~/.omp/agent/sessions/<slug>/` without touching `agent.db` (which co-locates auth credentials)
  5. After a session, antigravity conversation history appears on the host at `~/.gemini/antigravity-cli/conversations/` without touching the OAuth token or `~/.gemini/` settings proper
  6. Each harness's mount and teardown set is encoded in a structured per-harness manifest file — changing a path is a one-line manifest edit, not a search-and-replace through launcher code
**Plans**: TBD

### Phase 10: opencode/codex Investigation + Combined Capability Test

**Goal**: Investigate opencode and codex home-folder history layouts to produce classified path inventories and mount manifests (unblocking future stack support); replace the v1 capability test with the two-oracle approach — a deterministic structured MCP probe plus an un-primed ask-the-agent probe with a negative control that catches sycophantic priming.
**Depends on**: Phase 9
**Requirements**: MNT2-07, TST2-01, TST2-02, TST2-03
**Success Criteria** (what must be TRUE):
  1. `docs/research/home-folder-opencode-requirements.md` and `docs/research/home-folder-codex-requirements.md` exist with classified path inventories (history / config / cache / auth) and proposed mount manifests following the cross-harness invariants
  2. `harnessed test gstack-time` confirms the `time` MCP server is connected via hatago without making a model call (structured MCP probe passes deterministically)
  3. `harnessed test gstack-time` passes the agent probe: gstack skills confirmed present; the decoy capability is in `"missing"` (agent correctly reports it absent)
  4. A simulated test run where the agent claims the decoy present exits non-zero with status INVALID — distinct from a capability-failure non-zero exit — and the capability report shows the INVALID banner
  5. `profiles/gstack-time/capability-report.md` is written after every test run showing ✓/✗ per MCP server and per `expect:` entry, plus the INVALID banner when priming is detected
**Plans**: TBD

### Phase 11: Architecture Documentation

**Goal**: Update all narrative docs to describe the new architecture — 3-layer image lineage, Dockerfile recipe model, pinned sources, surgical profile mounts, combined capability test — and remove any remaining stale or obsolete terminology.
**Depends on**: Phase 10
**Requirements**: DOC2-01
**Success Criteria** (what must be TRUE):
  1. README describes the 3-layer image lineage (base → agent → stack), the Dockerfile + recipe.yaml recipe model, and a working quickstart that builds a stack and runs the capability test
  2. `docs/harnessed-design.md` §7 describes recipe = Dockerfile (not typed-YAML fields), supply chain = pin sources + scan the derived image (not scan vendored deps); §18 describes the two-oracle capability test with the negative control
  3. The recipe-authoring guide shows a complete worked example: `harnesses:`, `expect:` smoke check, pinned `git clone`, `--host ${HARNESS}`, and the "run the framework's installer" principle
  4. `rg -r "isolated|transparent" docs/ README.md CLAUDE.md AGENTS.md` returns no narrative usage of those terms in the updated docs
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Containerized Engine + Transparent Stack | 3/3 | Complete   | 2026-06-15 |
| 2. Isolated Tracer-Bullet Stack | 3/3 | Complete    | 2026-06-15 |
| 3. Supply-Chain Gate + pnpm-Everywhere | 2/2 | Complete    | 2026-06-16 |
| 4. Shared Services + Recipe Breadth + Full CLI | 4/4 | Complete   | 2026-06-17 |
| 5. Secrets, Hardening + Docs Completeness | 4/4 | Complete   | 2026-06-21 |
| 6. Address tech debt: harnessed-net code, stale comments, SUMMARY frontmatter | 3/3 | Complete    | 2026-06-21 |
| 7. Fat Base + Agent Images | 0/2 | Not started | - |
| 8. Dockerfile Recipe Model + Assembler + Supply-Chain Gate | 0/TBD | Not started | - |
| 9. Surgical Profile Mount + History Surfacing | 0/TBD | Not started | - |
| 10. opencode/codex Investigation + Combined Capability Test | 0/TBD | Not started | - |
| 11. Architecture Documentation | 0/TBD | Not started | - |
