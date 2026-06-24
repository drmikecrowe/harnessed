---
phase: 09-surgical-profile-mount-history-surfacing
plan: "04"
subsystem: uat
tags: [testing, uat, phase-09, smoke-tests, history-surfacing]
dependency_graph:
  requires: [09-02, 09-03]
  provides: [phase-09-uat-suite]
  affects: [tools/uat/phase-09.sh]
tech_stack:
  added: []
  patterns: [AAA-uat-pattern, needs_container-guard, uat_run_phase-entrypoint]
key_files:
  created:
    - tools/uat/phase-09.sh
  modified: []
decisions:
  - "Wrote all 10 tests (6 smoke + 4 integration) in a single pass rather than two separate commits; both tasks target the same file so committing together is equivalent"
  - "Integration tests check for .mcp.json existence before attempting container launch to give actionable skip message"
  - "Used assert_false rg -q for the assembler no-fanout check rather than assert_exit_nonzero on rg exit code"
  - "test_manifest_no_credentials uses cat glob + assert_not_contains (pure bash) rather than rg for credential scanning, consistent with uat-common.sh no-external-deps approach"
metrics:
  duration: "~5 minutes"
  completed: "2026-06-24"
  tasks_completed: 2
  files_created: 1
---

# Phase 09 Plan 04: Phase 9 UAT Suite Summary

Phase 9 UAT suite with 6 smoke tests (no container) and 4 integration tests (skip under --quick) covering surgical profile mount and history surfacing requirements MNT2-01 through MNT2-06.

## What Was Built

`tools/uat/phase-09.sh` — UAT suite sourced by `run-uat.sh`, following the exact pattern of `phase-04.sh` and `phase-08.sh`.

### Smoke Tests (always run, no container required)

| Test | Requirement | What It Checks |
|------|-------------|----------------|
| `test_manifests_exist` | MNT2-01 | All 6 harness manifests ship; claude manifest has `profile_files`/`history_dirs` keys; antigravity manifest references `antigravity-cli` |
| `test_manifest_no_credentials` | MNT2-01 | No `agent.db`, `antigravity-oauth-token`, `.credentials.json` in any manifest |
| `test_manifest_mounts_helper_exists` | MNT2-06 | `lib/harnessed-manifest-mounts.sh` ships, defines `harnessed_manifest_mounts`, passes `bash -n` |
| `test_launcher_uses_manifest_mounts` | MNT2-01/06 | `lib/harnessed-isolated.sh` sources helper, calls function, guards on `profile_dir/.mcp.json` |
| `test_assembler_no_fanout` | MNT2-06 | `assemble.py`/`emit.py` contain no `syncer`, `LinkSyncer`, `harness_dir`, `ensure_profile_tree` |
| `test_profile_shape_after_build` | MNT2-01 | `profiles/gstack-time` has `.mcp.json` at root, no `.claude/` tree; skips if gstack-time not built |

### Integration Tests (skip under UAT_QUICK=true)

| Test | Requirement | What It Checks |
|------|-------------|----------------|
| `test_path_mirroring` | MNT2-02 | Container `pwd` equals host `pwd` after headless gstack-time launch |
| `test_claude_history_surfaced` | MNT2-03 | `~/.claude/projects` exists on host after headless gstack-time session |
| `test_omp_history_surfaced` | MNT2-04 | `~/.omp/agent/sessions/$omp_slug` exists after headless omp-time session |
| `test_antigravity_history_surfaced` | MNT2-05 | `~/.gemini/antigravity-cli/conversations` exists after headless antigravity-time session |

## Verification

- `bash -n tools/uat/phase-09.sh` exits 0 (verified)
- `UAT_QUICK=true` run completes: all 4 integration tests SKIP, suite runs to completion
- `uat_run_phase` function defined and registered all 10 tests

## Deviations from Plan

None — plan executed exactly as written, with Tasks 1 and 2 combined into a single commit (both tasks modify the same file; the commit contains all required content from both tasks).

## Known Stubs

None — the UAT suite is complete. Smoke tests currently fail in the worktree because Wave 1/2 implementation files haven't merged yet; this is correct pre-merge behavior.

## Self-Check: PASSED

- tools/uat/phase-09.sh: created at commit 2c85239
- uat_run_phase defined: confirmed
- All 10 test functions present: confirmed
- bash -n exits 0: verified
- UAT_QUICK=true integration tests SKIP: verified
