# Concerns & Technical Debt

**Analysis Date:** 2026-06-16

This document catalogues open risks, unresolved design questions, and technical debt in the `harnessed` codebase. It is organized by priority. The project is at 80% (`STATE.md:14`) — Phases 01–03 closed, Phase 04 executed and self-verified but awaiting human UAT on a real podman host, Phase 05 pending. Most HIGH items are not bugs in shipped code; they are **unverified assumptions and environment-dependent behavior that integration-only testing cannot catch** (see §18 tradeoff, `docs/harnessed-design.md:587-589`).

---

## High Priority

### H1 — Phase 04 runtime verification is open (no green UAT on a real podman host)

- **Location:** `.planning/phases/04-shared-services-recipe-breadth-full-cli/04-UAT.md`; `.planning/STATE.md:5-6,28-33`
- **Impact:** `STATE.md` reports `status: ready_to_verify` and "checkpoints passed" — but those were the *executor's* per-plan self-checks. The **human-run** UAT (`status: testing`, `mode: mvp`) is the gating artifact and it shows **0/15 tests passed, 2 issues already surfaced, 13 pending** (`04-UAT.md:100-107`). Nothing in Phase 04 is yet proven against a real operator on a real podman host. The three plan-scoped checkpoint clusters (04-01 services, 04-02 state/CLI, 04-03 omp/recipe-breadth) are the "3 blocking human-verify checkpoints" — none can be closed by the assembler or a unit test; each requires launching pods, services, and harness instances and observing behavior.
- **Fix approach:** Run `/gsd-verify-phase 4` end to end on the target podman host. Resolve the two surfaced defects first (see H1a/H1b below) so Section 1 can proceed (the UAT's MVP rule: "If any [user-flow] step fails, halt — do not run Section 2", `04-UAT.md:28`). Do not treat the executor SUMMARYs as proof of the user-story outcome (`04-UAT.md:96-98`).

### H1a — Bare `harnessed` invocation silently launches `transparent` instead of help (UAT 6B, MAJOR)

- **Location:** `harnessed:75` (`STACK="transparent"` default) + `harnessed:81` (`while [[ $# -gt 0 ]]; do`) — root-cause captured in `04-UAT.md:111-123`
- **Impact:** With zero arguments the parse loop never runs, so dispatch falls through to an interactive `transparent` launch. A first-time operator running `harnessed` to discover the tool gets dropped into a container session instead of usage text. This is the first thing the UAT cold-start surfaced and it blocks the help/front-door contract.
- **Fix approach:** Add an explicit no-args guard *before* the parse loop: `if [ $# -eq 0 ]; then usage; exit 0; fi`. Guard on `$# -eq 0`, not on the `STACK` default — a single bareword that is a project path must still launch `transparent` (the `container` alias and `harnessed /some/path` form depend on it). Reconcile `usage()` at `harnessed:41` ("default stack: transparent") if bare invocation no longer launches.

### H1b — State-dir slug is an opaque hash, not a legible project path (UAT 6, MINOR→MAJOR if unaddressed)

- **Location:** `lib/harnessed-common.sh:180` (`generate_instance_name()` → `harnessed-<stack>-<sha1(project)[:8]>`) consumed by `lib/harnessed-isolated.sh:103` for the state dir; root-cause in `04-UAT.md:124-139`
- **Impact:** `~/.local/state/harnessed/harnessed-ping-time-62b130a8/` is unreadable — an operator tracking instances by project cannot tell which dir belongs to which project. The hash was correctly chosen for the **container/pod name** (DNS-label ≤63-char constraint); the state dir wrongly inherited it. `project_relpath()` (`harnessed-common.sh:194`) already computes the legible host-relative path but is unused for the state slug.
- **Fix approach:** Decouple the two slugs. Keep the compact hash for the container/pod name; use a flattened project path for the state dir (`programming-personal-code-container` or the full `-home-mcrowe-…-code-container` form per the operator's example). Decide the exact form, handle length/collisions for deep paths, and migrate or cleanly ignore pre-existing hash-based state dirs.

### H2 — Rootless-podman bridge is unsupported on the target host (hard environment dependency)

- **Location:** `lib/harnessed-services.sh:99-102` (the published-ports pivot); 04-RESEARCH §2b "⚠ SUPERSEDED" block at `.planning/phases/04-.../04-RESEARCH.md:80-88`; pitfall P-04-01 at `:135`
- **Impact:** Shared service sidecars **hard-require** reaching services from peer pods. The original design assumed a rootless `harnessed-net` bridge (`docs/harnessed-design.md:385`, `:110` of the RESEARCH). The 04-01 checkpoint proved rootless bridges fail on this host: `netavark: create bridge: Operation not supported` for *any* container on *any* user-defined bridge (`04-RESEARCH.md:81-84`). The shipped workaround is **publish-to-`0.0.0.0` + reach via the podman host-gateway `host.containers.internal:<port>`** — no bridge. This is not a graceful fallback; on a host *without* the publish/host-gateway path, **shared services do not work at all**, and the model is now host-specific rather than the portable bridge model the design committed to.
- **Fix approach:** The pivot is implemented and is the correct call for this host. The debt is **documentation + design reconciliation**: `docs/harnessed-design.md` §9/§13 still describe the bridge as the model. Update the design to record the publish+host-gateway model as primary and the bridge as the `HARNESSED_NET` opt-in for hosts that support it (the code already preserves this — `harnessed-services.sh:102`). Document the `169.254.1.2` (`host.containers.internal`) firewall dependency (`lib/egress-firewall.sh:55-63`) and the FastMCP `allowed_hosts` requirement (commit `6f6c1b3`) as operator prerequisites, not implementation details.

### H3 — The omp harness unknowns are still `[INFERENCE]`, not empirically confirmed

- **Location:** 04-RESEARCH §8 "Open questions" at `.planning/phases/04-.../04-RESEARCH.md:254-261`; pitfalls P-04-10/11/12 at `:215-217`; design §14 "Harness config mount points" at `docs/harnessed-design.md:412-413`
- **Impact:** The entire omp-via-`claude-hooks-bridge` integration rests on three assumptions that the executor's checkpoints may have exercised but the **human UAT has not yet confirmed** on the running instance:
  1. **Does omp read `.claude/skills/` natively?** (P-04-10) — if not, the bridge or a symlink/`--skills` glob must resolve it.
  2. **omp MCP config wiring** (P-04-11) — does omp read `.claude/.mcp.json` the way `claude --mcp-config` does, or does it need `--config` / its own `.mcp.json` location? The hatago endpoint (`http://localhost:3535/mcp`) is the same; only *how omp is told about it* differs.
  3. **omp headless auth** (P-04-12) — does `--profile` + the Phase-2 credentials mount boot omp headless without prompts, mirroring Claude's `.claude.json` stub?
  
  These are the §14 "to verify" items for the omp path. The capability test for omp (`04-RESEARCH.md:209-211`) branches on `stack.harness`, but the introspection backstop differs from claude's — so a silent partial failure (skills visible to claude but not omp) would not necessarily fail the build, only the human-read capability report.
- **Fix approach:** UAT Test 7 (`harnessed test omp-time`) is the gating check (`04-UAT.md:62-64`) — run it headless and assert `time ✓ connected + time-helper ✓ present` from *omp*, not just from hatago. If any of the three assumptions is wrong, fix at the bridge/launcher level and record the resolution in design §14 so the `[INFERENCE]` markers can be cleared. Until then treat the omp stack as experimentally shipped, not proven.

---

## Medium Priority

### M1 — Integration-only testing: assembler bugs surface as coarse capability failures

- **Location:** `docs/harnessed-design.md:537-589` (§18, esp. the "Honest tradeoff" at `:587-589`); confirmed by **zero test files** in the repo (no `test_*.py`, `*_test.py`, `conftest.py`, `*.bats`, or `test*.sh` anywhere)
- **Impact:** This is a **deliberate, documented tradeoff**, not an oversight — "integration-only means an assembler bug surfaces as a capability failure, not a pinpointed unit failure — coarser to debug" (`harnessed-design.md:587-589`). The sole test oracle is `tools/harnessed/capability.py`, which launches the *running instance* headless and diffs live capabilities against the stack manifest. Consequence: a recipe-wiring regression (e.g. a sync-plugin-links conflict, an MCP-merge duplicate, a profile-mount path error) presents as "skill X missing" or "MCP Y not connected" in the capability table (`harnessed-design.md:568-576`) rather than a pinpointed assembler assertion. The `tools/test-fixtures/` directory holds *fixtures* (synthetic stacks/recipes/services for the capability path), not unit tests.
- **Fix approach:** Keep the integration-first stance (it matches the project's TDD-via-public-interface philosophy). The mitigation the design itself names is **clear assembler errors** — e.g. `sync-plugin-links`' explicit conflict reporting (`harnessed-design.md:588`) — so a failed build says *what* it could not wire. Audit the emit/merge paths (`tools/harnessed/assemble.py`, `emit.py`) to ensure every failure mode (collision, duplicate MCP name, unresolved service reference, missing recipe) emits a specific, actionable error rather than letting the capability test be the first signal.

### M2 — `CLAUDE_CONFIG_DIR` relocation scope is still unverified (open since Phase 1)

- **Location:** `docs/harnessed-design.md:431-433` (§14); `.planning/STATE.md:73` ("Verify `CLAUDE_CONFIG_DIR` relocates `.claude.json`... choose copy-on-start otherwise"); `docs/codebase` research at `.planning/research/PITFALLS.md:19`
- **Impact:** Whether `CLAUDE_CONFIG_DIR` relocates the top-level `~/.claude.json` (not just the `~/.claude/` directory) was flagged `[INFERENCE — confidence MEDIUM]` in Phase 1 and is the **only Phase-1 blocker still listed in STATE.md**. If it does *not* relocate the top-level file, the `transparent` mode cannot cleanly decouple container state from the host file by pointing at a per-instance dir — it must fall back to copy-on-start (which `lib/harnessed-transparent.sh` already does). The risk is silent state coupling: the container writes to a host-shared `.claude.json`.
- **Fix approach:** Resolve empirically — boot a `transparent` instance with `CLAUDE_CONFIG_DIR` set to a per-instance dir and inspect whether `~/.claude.json` appears inside it or still at the host top level. Record the result in §14 and clear the `[INFERENCE]` marker. If it does not relocate, document copy-on-start as the permanent (not interim) `transparent` strategy.

### M3 — External dependency on the `claude-hooks-bridge` npm package (omp integration)

- **Location:** `base/Dockerfile.harnessed-omp:25` (`RUN omp plugin install @drmikecrowe/omp-claude-hooks-bridge`); pitfall P-04-13 at `04-RESEARCH.md:218`; bridge source described at `04-RESEARCH.md:189-197`
- **Impact:** The omp harness is *entirely* dependent on this one external (owner-authored, but still external) npm package to map Claude hooks/skills/settings into omp's lifecycle (`SessionStart→session_start`, `PreToolUse→tool_call`, etc., per `04-RESEARCH.md:193`). It is pinned implicitly by `omp plugin install` (omp's plugin lock under `~/.omp/plugins`), not by a lockfile the assembler controls. A bridge update that changes event mapping, tool-name translation, or the `permissionDecision`/exit-2 contract (P-04-13) would silently break omp stacks at the next image rebuild. The package is TypeScript/Bun, so the omp image also pulls in Bun (`Dockerfile.harnessed-omp:20`) — a second runtime surface.
- **Fix approach:** Pin the bridge to an explicit version in the Dockerfile (verify `omp plugin install` accepts a version specifier) and add the pinned version to the supply-chain scan gate (Phase 3, `build_stack`'s image-scan path). Add a capability-test assertion that exercises a hook event end-to-end on the omp stack so a bridge regression fails the build, not just the operator.

### M4 — Working-tree noise: 49 unstaged deletions under `.agents/`

- **Location:** `git status` — `D .agents/skills/**` (caveman, diagnose, grill-with-docs, prototype, teach, to-issues, … 49 paths)
- **Impact:** These are **pre-existing, uncommitted working-tree deletions** — not code this phase touched. They are pure noise that obscures real diffs in every `git status`/review and risks an accidental `git add -A` committing a mass deletion the project didn't intend. They appear unrelated to the harness itself (`.agents/` is a host-agent skills tree, not the `harnessed` runtime).
- **Fix approach:** Either restore them (`git checkout -- .agents/`) if they belong, or commit the deletion deliberately with a message explaining why the agent-skill tree is being removed from this repo. Leaving them as permanent unstaged churn is the worst option.

---

## Low Priority

### L1 — HEALTHCHECK readiness gate silently degrades to "container is running"

- **Location:** `lib/harnessed-services.sh:111-122` (the wait loop); schema field `tools/harnessed/schema.py:138,235` (`healthcheck: str = ""`); fixture `tools/test-fixtures/services/svc-test/service.yaml:5`
- **Impact:** `svc_up` waits up to 30s for `.State.Health.Status == healthy`. If the image has **no `HEALTHCHECK`** instruction (none of the repo's own Dockerfiles define one — confirmed across `base/`, `tools/Dockerfile`), the inspect returns `""` and the loop falls back to `container_running "$service"` (`harnessed-services.sh:119`). This is also where the **"HEALTHCHECK not supported on OCI"** podman build/runtime warning originates: OCI images don't carry the Docker `HEALTHCHECK` directive, so podman emits the warning on builds and the readiness signal is weaker than the code assumes. A service that binds its port but isn't actually ready to serve MCP would pass the gate.
- **Fix approach:** For services where readiness matters (the tracer `ping`, hindsight), bake a real `HEALTHCHECK` (or an app-level readiness endpoint) into `services/<name>/Dockerfile` and assert it in the wait loop. Treat the `container_running` fallback as the degraded path it is, not a silent equivalent.

### L2 — The legacy `container` alias decision is still open

- **Location:** `docs/harnessed-design.md:414-415` (§14: "Keep `container` as a thin alias → `harnessed transparent` for muscle memory, or remove... Recommendation: keep — zero cost."); `install.sh:15` (`BINARIES=("harnessed" "container")`); repo `container` shim
- **Impact:** The `container` command is kept as a back-compat symlink to `harnessed transparent`. The design's own recommendation is "keep — zero cost," but it is still listed in §14 as unresolved, and it means *two* entry-point names for the same behavior plus a divergent default (`container` → transparent; bare `harnessed` → transparent too, pending H1a). Minor operator-confusion and docs-maintenance surface.
- **Fix approach:** Accept the §14 recommendation formally: remove the open item from §14, keep `install.sh` symlinking both, and document `container` as a deprecated alias in usage text so operators migrate to `harnessed`.

### L3 — Documentation gaps relative to the §17 doc-as-deliverable plan

- **Location:** `docs/harnessed-design.md:516-535` (§17 — README, recipe-authoring guide, stack guide, secrets setup, service-authoring, troubleshooting/ops)
- **Impact:** §17 declares docs a "gated deliverable, not an afterthought" and lists seven required surfaces that should land *with* their feature. The repo has `docs/harnessed-design.md` (the source-of-truth spec) and a 33KB `CLAUDE.md`, but the operator-facing README, recipe-authoring guide, and service-authoring guide are not yet present as standalone docs. New contributors must reverse-engineer recipe/stack/service conventions from `recipes/time/`, `stacks/tracer-time/`, and the RESEARCH notes.
- **Fix approach:** Land the §17 surfaces incrementally as each area stabilizes — prioritize the recipe-authoring guide and the troubleshooting/ops page (firewall prerequisites, first-run build, `--fresh`, host-persisted sessions) since those are what the Phase-04 UAT operator needs *now*.

---

## TODOs and FIXMEs Found

**No `TODO` / `FIXME` / `HACK` / `XXX` / `WORKAROUND` / `@deprecated` markers exist in the code** (`lib/`, `tools/`, `harnessed`, `base/`, `recipes/`, `stacks/` — all searched). The project deliberately uses a different convention: **`[INFERENCE — verify]` markers in the design/research docs** flag unverified assumptions rather than scattering TODOs in code. This is healthier (assumptions are tracked in one place and resolved empirically) but means "open work" lives in prose, not in grep-able code comments. Known `[INFERENCE]` markers and their status:

| Marker location | Item | Status |
|---|---|---|
| `docs/harnessed-design.md:405-407` | Minimal `.claude.json` stub fields | **RESOLVED** — proven sufficient by the Phase-2 headless no-prompt boot gate (`02-VERIFICATION.md:88`, `STATE.md:74`) |
| `docs/harnessed-design.md:431-433` | `CLAUDE_CONFIG_DIR` relocates `~/.claude.json` (not just `~/.claude/`) | **OPEN** — the lone Phase-1 blocker still in `STATE.md:73` (see M2) |
| `docs/harnessed-design.md:512-514` | In-container 1Password auth mode (app-auth socket vs service-account token) | **DEFERRED** — Phase 5 secrets work, not yet addressed |
| `CLAUDE.md:163,171,178` / `PITFALLS.md:19,42` | mise/npm routing, `.claude.json` stub, `CLAUDE_CONFIG_DIR` | mise routing **RESOLVED** (`harnessed-design.md:426-430`); others per above |
| `04-RESEARCH.md:215` (P-04-10) | omp reads `.claude/skills/` natively | **OPEN** — checkpoint-pending (see H3) |
| `04-RESEARCH.md:216` (P-04-11) | omp MCP config wiring | **OPEN** — checkpoint-pending (see H3) |
| `04-RESEARCH.md:217` (P-04-12) | omp headless auth/profile seeding | **OPEN** — checkpoint-pending (see H3) |

---

## Missing or Weak Areas

- **No unit tests of any kind** (see M1). Every code path — schema parsing, link-sync collision detection, MCP-merge, emit, service-URL resolution — is exercised only transitively through `capability.py`. The `tools/test-fixtures/` stacks (`low-stack`, `npm-stack`, `vuln-stack`, `svc-stack`) are inputs to the capability/integration path, not assertions about assembler internals.
- **No CI lockfile pinning surfaced for the Python deps beyond `pip-audit==2.10.1`** (`tools/pyproject.toml:13`); `ruamel.yaml` and `rich` are ranged (`>=0.18,<0.19`, `>=14,<15`). A reproducible lock (`uv.lock` or equivalent) is not present in the tree.
- **Per-server MCP transport classification** (§14, `harnessed-design.md:408-409`) — which servers are already Streamable-HTTP-native vs need hatago's stdio→HTTP wrapping — is decided per-recipe at author time but not asserted anywhere; a recipe that mis-declares transport fails only at the capability test.
- **Intra-stack collision policy** (§14, `harnessed-design.md:410-411`) — fail-fast (reusing `sync-plugin-links`' conflict exit) is the implemented behavior but is not yet *confirmed as the desired policy* vs last-wins/namespacing. A fail-fast exit is a hard stop; if operators expect last-wins for rapid prototyping, this is a usability cliff.
- **Host-projects scope** (§14, `harnessed-design.md:421-423`) — whether `session_state: host` writes the host's own `~/.claude/projects/` or a harnessed-owned dir. The design recommends harnessed-owned (the current convention, `~/.local/state/harnessed/<instance>/`), but this is not pinned by a test; an accidental write to the host's real `~/.claude/projects/` would pollute the operator's native Claude history.

---

## Appendix — Design §14 "Open / to verify during execution" (full inventory)

Source: `docs/harnessed-design.md:403-433`. These are the architect's own open questions; resolution status as of this analysis:

| §14 item | Location | Status |
|---|---|---|
| Minimal `.claude.json` stub fields | `:405-407` | RESOLVED (Phase 2) |
| Per-server MCP transport | `:408-409` | OPEN — per-recipe, asserted only at capability test |
| Intra-stack collision policy | `:410-411` | OPEN — fail-fast implemented, not confirmed as desired |
| Harness config mount points | `:412-413` | PARTIAL — claude `.claude` mapped; omp path unverified (H3) |
| `container` alias | `:414-415` | OPEN (recommendation: keep) — see L2 |
| hatago placement (in-pod over HTTP) | `:416-417` | RESOLVED by implementation; re-verify on a real stack |
| Editor/tool configs in isolated mode | `:418-420` | OPEN — always-mounted today; no flag to gate for a truly empty env |
| Host-projects scope | `:421-423` | OPEN — harnessed-owned recommended/used; not test-pinned |
| Container home path `/home/harnessed/<relpath>` | `:424-425` | RESOLVED — `Dockerfile.harnessed-base:37-48`, `harnessed-common.sh` |
| pnpm rollout (mise → npm: via pnpm) | `:426-430` | RESOLVED (Phase 3) |
| `CLAUDE_CONFIG_DIR` relocation | `:431-433` | OPEN — see M2 |
