---
status: complete
phase: 04-shared-services-recipe-breadth-full-cli
source: [04-01-SUMMARY.md, 04-02-SUMMARY.md, 04-03-SUMMARY.md, 04-04-SUMMARY.md]
started: 2026-06-17T09:51:23Z
updated: 2026-06-17T21:20:44Z
mode: mvp
method: automated
suite: tools/uat/phase-04.sh
user_story: "As a stack operator, I want to run concurrent harness instances that share service-scoped sidecars and operate the full stack, instance, and session lifecycle through the `harnessed` CLI, so that multiple instances can run together over a shared network, I can add more recipes to a stack, and every lifecycle action works predictably by name with default persistence and clean-room `--fresh` runs."
---

## Methodology

Phase 4 is validated by an **automated AAA (Arrange-Act-Assert) UAT suite**, not a manual
conversation. The suite drives the real `harnessed` CLI + podman, asserts on exit codes / output /
container state, and reports pass/fail per test.

- **Runner:** `./tools/uat/run-uat.sh 4` (full) · `… 4 --quick` (no heavy launches) · `… 4 <test_id>` (one test)
- **Harness:** `tools/uat/uat-common.sh` (pure-bash asserts, no bats/grep)
- **Suite:** `tools/uat/phase-04.sh` (16 AAA tests)
- **Last run:** 2026-06-17 — **16/16 tests pass, 50/50 checks, exit 0** (both gaps closed)

## Current Test

[automated — all green; run `./tools/uat/run-uat.sh 4`]

## Tests

| # | Test (AAA) | What it asserts | Result |
|---|------------|-----------------|--------|
| 1 | `svc_up` | svc up publishes 0.0.0.0:8080, healthy, listed | pass |
| 2 | `svc_up_idempotent` | second svc up is a no-op; exactly 1 container | pass |
| 3 | `svc_down_retains_volume` | svc down keeps the ping-data volume | pass |
| 4 | `svc_down_purge` | svc down --purge destroys the volume | pass |
| 5 | `shared_single_across_instance` | `harnessed test ping-time` passes; shared ping service stays singular (SVC-02 invariant) | pass |
| 6 | `recipe_breadth` | `harnessed test claude-multi` asserts time + greet (SC-2) | pass |
| 7 | `omp_bridge` | `harnessed test omp-time` asserts time via the bridge (SC-5) | pass |
| 8 | `no_args_help` | bare `harnessed` shows Usage, exits 0 | pass (gap 6B **closed** by 04-04) |
| 9 | `list_surface` | `harnessed list` shows stacks + instances | pass |
| 10 | `new_scaffold_refuse` | `new` scaffolds a manifest; refuses overwrite | pass |
| 11 | `new_bad_harness` | `new` rejects an unknown harness | pass |
| 12 | `install_uninstall` | install writes an executable §13 shim; uninstall removes it | pass |
| 13 | `legacy_flags` | legacy `--list` still works (instance-only back-compat) | pass |
| 14 | `state_persists` | marker survives a non-`--fresh` recreate (STA-01) | pass |
| 15 | `fresh_wipes` | `--fresh` wipes accumulated state (clean-room) | pass |
| 16 | `legible_slug` | state-dir slug is a legible path, not an opaque hash | pass (gap 6 **closed** by 04-04) |

### Cold-start note
A full from-scratch cold start (all images wiped → rebuild → boot) is implicitly covered
— the suite rebuilds profiles/images when absent (claude-multi, omp-time were assembled
during the run). A destructive zero-image cold start remains a one-off manual check, not
part of the repeatable suite.

## Summary

total: 16
passed: 16
issues: 0
pending: 0
skipped: 0
blocked: 0
checks: 50 passed, 0 failed

## Gaps

Both gaps surfaced during UAT were closed by plan 04-04 (see 04-04-PLAN.md / 04-04-SUMMARY.md),
verified by the red UAT tests flipping green with zero regressions.

- truth: "Running `./harnessed` with no arguments shows usage/help (not a silent transparent launch)"
  status: closed
  severity: major
  test: no_args_help
  closed_by: "04-04 Task 1 — `[ $# -eq 0 ] && { usage; exit 0; }` guard in harnessed before the parse loop"

- truth: "The host-side state dir uses a legible, path-based slug (e.g. a flattened project path), not an opaque hash"
  status: closed
  severity: minor
  test: legible_slug
  closed_by: "04-04 Task 2 — state dir keyed by flattened project_relpath + stack in lib/harnessed-isolated.sh (decoupled from the hash container name)"
