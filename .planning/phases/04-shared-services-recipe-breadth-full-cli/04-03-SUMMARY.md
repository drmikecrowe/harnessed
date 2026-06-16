---
phase: 04-shared-services-recipe-breadth-full-cli
plan: 03
subsystem: infra
tags: [omp, oh-my-pi, claude-hooks-bridge, recipe-breadth, multi-harness, mise, bun]

requires:
  - phase: 02-isolated-tracer-bullet-stack
    provides: the isolated pod model + the capability test harness
  - phase: 04-shared-services-recipe-breadth-full-cli (plan 02)
    provides: the full CLI (new/install) + the stable launcher
provides:
  - base/Dockerfile.harnessed-omp — the omp (Oh My Pi) harness image (base + omp + bun + bridge)
  - schema omp mapping — HARNESS_CONFIG_DIR["omp"]=".claude" (Claude-canonical profile, single source of truth)
  - harness-aware launcher dispatch — omp stacks use harnessed-omp + omp attach; claude unchanged
  - harness-aware capability test — _harness_of/_llm_cmd branch the LLM backstop per harness
  - recipes/greet + stacks/claude-multi — recipe breadth proof (two recipes, both asserted)
  - stacks/omp-time — the omp proof stack (same Claude-canonical recipe via the bridge)
affects: [multi-harness, omp, recipe-breadth, capability-testing]

tech-stack:
  added: [omp/16.0.1 (github:can1357/oh-my-pi), bun@1.3.14 (mise), @drmikecrowe/omp-claude-hooks-bridge@0.2.2]
  patterns:
  - "One Claude-canonical profile (.claude/) serves BOTH harnesses — omp consumes it at runtime via the claude-hooks-bridge (no re-authoring, design §8)"
  - "HARNESS_CONFIG_DIR maps every harness to .claude (single source of truth); the difference is the image + attach command, not the profile"
  - "Capability test's PRIMARY checks (hatago hatago://servers + filesystem skills) are harness-independent; only the LLM backstop command branches (omp -p vs claude -p)"
  - "omp plugins are Bun-based — the omp image must install bun (via mise) before `omp plugin install` works"

key-files:
  created:
  - base/Dockerfile.harnessed-omp
  - recipes/omp/recipe.yaml
  - recipes/greet/recipe.yaml
  - recipes/greet/skills/greet-helper/SKILL.md
  - stacks/claude-multi/stack.yaml
  - stacks/omp-time/stack.yaml
  modified:
  - tools/harnessed/schema.py
  - tools/harnessed/capability.py
  - lib/harnessed-isolated.sh
  - lib/harnessed-common.sh
  - harnessed

key-decisions:
  - "The profile is Claude-canonical (.claude/) for BOTH harnesses — HARNESS_CONFIG_DIR['omp']='.claude'. omp reads the same skills/hooks/commands via the bridge. Single source of truth (design §8)."
  - "The capability test stays harness-agnostic for its PRIMARY checks (hatago MCP resource + filesystem skills); only the LLM backstop branches (omp -p --mode json vs claude -p --output-format json). This minimized the test change while covering omp."
  - "omp plugins are Bun/TypeScript — the omp image installs bun via mise before `omp plugin install`. Without bun, the bridge install fails ('Executable not found: bun')."

patterns-established:
  - "Adding a harness = a new image (FROM base + install harness + bridge) + a HARNESS_CONFIG_DIR entry + a launcher attach branch + a capability-test backstop branch. The profile, assembler, and hatago are unchanged."
  - "Recipe breadth is exercised by claude-multi (recipes: [time, greet]) — two recipes, two capability kinds (mcp + skill), both asserted by one capability test"

requirements-completed: [HRN-01]

duration: ~75min
completed: 2026-06-16
---

# Phase 4 Plan 03: omp Harness + Recipe Breadth Summary

**A second harness — omp (Oh My Pi) — consuming the same Claude-canonical profile via the pre-installed claude-hooks-ridge (no re-authoring), plus recipe breadth proven by a two-recipe claude stack. An omp stack assembles, launches headless, and exposes its declared capabilities (time connected, skill present).**

## Performance
- **Duration:** ~75 min (executor auto-tasks + omp image build + bun fix + omp capability test)
- **Tasks:** 4 auto + 1 human-verify checkpoint (approved via podman: omp image build + claude-multi + omp-time tests)
- **Files:** 11 (6 created + 5 modified)

## Accomplishments
- `base/Dockerfile.harnessed-omp` — FROM harnessed-base + omp 16.0.1 (mise) + bun (mise) + the pre-installed `@drmikecrowe/omp-claude-hooks-bridge@0.2.2`. Lazy-built (`ensure_omp_image`) so claude-only users never build omp. (HRN-01)
- Schema omp mapping — `HARNESS_CONFIG_DIR["omp"] = ".claude"` (the profile is Claude-canonical for both harnesses; single source of truth). `stack.harness_config_dir` no longer raises for omp.
- Harness-aware launcher dispatch — `harnessed_isolated` reads `stack.harness`; omp stacks run the harness member from `harnessed-omp` and attach via `omp --profile <instance>`; claude unchanged. The hatago/pod plumbing is shared.
- Harness-aware capability test — `_harness_of`/`_llm_cmd` branch the LLM backstop (omp -p --mode json vs claude -p). The PRIMARY checks (hatago `hatago://servers` + filesystem skills) are harness-independent and unchanged.
- Recipe breadth — `recipes/greet` (skill-only) + `stacks/claude-multi` (recipes: [time, greet]). `harnessed test claude-multi` → time ✓ + time-helper ✓ + greet-helper ✓ (success criterion 2).
- omp proof — `stacks/omp-time` (harness: omp, recipes: [time, omp]). `harnessed test omp-time` → time ✓ connected + time-helper ✓ present (success criterion 5; the §14 unknowns resolved: omp boots headless, reaches hatago, exposes the recipe).

## Task Commits
1. **harnessed-omp image + omp base recipe + lazy build** — `c9f4d99` (feat)
2. **schema omp mapping + harness-aware launcher dispatch** — `76d377a` (feat); complementary test-path ensure — `af8c8bf` (feat)
3. **greet skill recipe + claude-multi stack (recipe breadth)** — `0e0673d` (feat)
4. **harness-aware capability test + omp-time stack** — `c92e9e6` (feat)

Checkpoint fix:
5. **install bun in omp image (omp plugin install needs it)** — `7ce6589` (fix)

## Files Created/Modified
- `base/Dockerfile.harnessed-omp` (NEW) — the omp image (base + omp + bun + bridge).
- `recipes/omp/recipe.yaml` (NEW) — the omp base recipe (declares the bridge extension).
- `recipes/greet/{recipe.yaml,skills/greet-helper/SKILL.md}` (NEW) — the skill-only recipe.
- `stacks/claude-multi/stack.yaml`, `stacks/omp-time/stack.yaml` (NEW).
- `tools/harnessed/schema.py` — HARNESS_CONFIG_DIR omp entry.
- `tools/harnessed/capability.py` — _harness_of/_llm_cmd (harness-aware backstop).
- `lib/harnessed-isolated.sh` — omp harness dispatch (image + attach).
- `lib/harnessed-common.sh`, `harnessed` — ensure_omp_image + the test-path omp ensure.

## Decisions Made
- See key-decisions — Claude-canonical profile for both; minimal harness-aware test change; bun required for omp plugins.

## Deviations from Plan

### Auto-fixed Issues

**1. omp image missing bun (plugin install failed)**
- **Found during:** Task 5 checkpoint (omp image build: `omp plugin install ... → Executable not found in $PATH: bun`).
- **Issue:** omp plugins are Bun/TypeScript (the bridge ships bun.lock + a TS entry); `omp plugin install` invokes bun, which the base image lacks.
- **Fix:** the omp Dockerfile installs bun via mise (`mise use -g ... bun`) before `omp plugin install`.
- **Files modified:** base/Dockerfile.harnessed-omp.
- **Verification:** rebuild succeeds; `omp plugin list` shows `@drmikecrowe/omp-claude-hooks-bridge@0.2.2`.
- **Committed in:** `7ce6589`.

---

**Total deviations:** 1 auto-fixed (at the checkpoint — a missing build dependency the plan/RESEARCH couldn't know without building the omp image).
**Impact on plan:** One missing package (bun). The omp harness model (single canonical profile + bridge + harness dispatch) landed exactly as planned.

## Issues Encountered
- The §14 "to verify" unknowns (P-04-10 skill discovery, P-04-11 MCP wiring, P-04-12 headless auth) all resolved cleanly: omp boots headless (no auth prompt), reaches hatago at localhost:3535 (time connected), and the skill is present. No omp-specific code changes beyond the launcher dispatch + the bun fix were needed.

## Self-Check: PASSED
- [x] omp image: omp/16.0.1 + bun + bridge installed; lazy-built (claude-only users unaffected).
- [x] recipe breadth: `test claude-multi` → time ✓ + time-helper ✓ + greet-helper ✓.
- [x] omp stack: `test omp-time` → time ✓ connected + time-helper ✓ present.
- [x] schema: HARNESS_CONFIG_DIR == {claude: .claude, omp: .claude}; omp-time loads; unknown harness still raises.
- [x] the capability test's PRIMARY checks are harness-independent (the backstop branches only).

## Next Phase Readiness
- Two harnesses (claude + omp) share one canonical profile — the multi-harness model is proven.
- Recipe breadth (multiple recipes compose + assert) works for both harnesses.
- Phase 4 is complete: shared services (04-01) + state/CLI (04-02) + omp/recipe-breadth (04-03).

---
*Phase: 04-shared-services-recipe-breadth-full-cli*
*Completed: 2026-06-16*
