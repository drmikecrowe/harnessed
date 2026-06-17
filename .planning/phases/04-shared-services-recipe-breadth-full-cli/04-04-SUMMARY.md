---
phase: 04-shared-services-recipe-breadth-full-cli
plan: 04
subsystem: infra
tags: [cli, launcher, state-persistence, uat, gap-closure]
gap_closure: true

requires:
  - phase: 04-shared-services-recipe-breadth-full-cli
    provides: the automated UAT suite (tools/uat) whose two red tests define these gaps
provides:
  - bare `harnessed` shows usage/help instead of silently launching transparent
  - a legible, path-based host-side state-dir slug (decoupled from the hash container name)
affects: [cli-discoverability, state-persistence]

key-files:
  modified:
  - harnessed
  - lib/harnessed-isolated.sh
  - tools/uat/phase-04.sh

requirements-completed: []

duration: ~15min
completed: 2026-06-17
---

# Phase 4 Plan 04: UAT Gap Closure Summary

**Two small, fully-diagnosed fixes that close the Phase 4 UAT gaps — proven by the red UAT
tests flipping green with zero regressions (16/16 tests, 50/50 checks).**

## Performance

- **Duration:** ~15 min (apply 2 fixes + update the UAT suite + full re-run)
- **Mode:** inline execution (the workflow's documented fit for verification gaps / bug fixes) — the gaps were tiny and fully diagnosed; a worktree executor would have been disproportionate.
- **Files:** 3 modified.

## Accomplishments
- **Gap 6B (no-args help):** added a `[ $# -eq 0 ] && { usage; exit 0; }` guard in `harnessed` after the arg defaults, before the parse loop. Bare invocation now prints usage and exits 0 instead of silently launching the `transparent` stack. A single bareword (a path) still launches transparent — the guard is on `$# == 0`, not the STACK default.
- **Gap 6 (legible state slug):** decoupled the state-dir location from the hash container name in `lib/harnessed-isolated.sh`. The state dir is now `$XDG_STATE_HOME/harnessed/<flattened-home-relative-project-path>/<stack>/.claude` (reuses the already-computed `project_relpath` value, slashes→dashes). The pod/container name keeps the compact hash slug (DNS-label ≤63-char constraint); only the state dir is legible.
- **UAT suite updated** (`tools/uat/phase-04.sh`): added a `uat_state_dir` helper mirroring the new layout; `test_state_persists`/`test_fresh_wipes`/`test_legible_slug` now compute the dir via the legible path.

## Verification
- **Before:** 14/16 tests pass — `test_no_args_help` and `test_legible_slug` red (the gaps).
- **After:** `./tools/uat/run-uat.sh 4` → **16/16 tests, 50/50 checks, exit 0.** Both gap tests flipped green; the other 14 (incl. the persistence tests on the new path) stayed green.
- Also ran `bash -n` + `shellcheck -x` clean on all touched files.

## Decisions Made
- **Inline execution over a spawned worktree executor.** Two one-line-ish fixes with complete diagnoses and red UAT specs — the worktree/parallel ceremony (and its token cost) was disproportionate. `--interactive`/inline is the workflow's sanctioned mode for exactly this.
- **Home-relative flattened path over full absolute path.** `project_relpath` already produces a home-relative value (`Programming/Personal/code-container`); flattening yields a legible slug without leaking the username or exceeding path limits. (The user's example used the full path; both forms satisfy "legible, not a hash" — home-relative is the cleaner choice.)
- **No migration of pre-existing hash-based state dirs.** They're left in place (unused); new runs create the legible path. Acceptable for a dev tool; flagged in the plan.

## Deviations from Plan
None — the plan was executed as written (it was authored from the diagnosed gaps).

## Self-Check: PASSED
- [x] `test_no_args_help` green: bare `harnessed` → usage, exit 0.
- [x] `test_legible_slug` green: state dir at `…/harnessed/<flattened-project>/<stack>/.claude`.
- [x] `test_state_persists` / `test_fresh_wipes` green on the new path (persistence logic unchanged).
- [x] Full suite 16/16, 50/50 checks, exit 0 — no regressions.

---
*Phase: 04-shared-services-recipe-breadth-full-cli*
*Completed: 2026-06-17*
