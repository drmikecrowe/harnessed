---
phase: 09-surgical-profile-mount-history-surfacing
plan: "02"
subsystem: assembler
tags: [refactor, emit, assemble, profile-mount, fan-out-removal]
dependency_graph:
  requires: []
  provides: [emit.write_mcp_json(profile_dir), emit.write_settings_json(profile_dir)]
  affects: [tools/harnessed/emit.py, tools/harnessed/assemble.py]
tech_stack:
  added: []
  patterns: [profile-root-emission, no-fan-out]
key_files:
  modified:
    - tools/harnessed/emit.py
    - tools/harnessed/assemble.py
decisions:
  - "write_mcp_json and write_settings_json emit to profile root (not .claude/ subdir)"
  - "LinkSyncer import reduced to CollisionError-only; CollisionError kept for _merge_servers"
  - "field import removed from dataclasses since skills/commands fields were deleted"
metrics:
  duration: "~8 minutes"
  completed: "2026-06-24T13:20:00Z"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 2
---

# Phase 9 Plan 02: Assembler Fan-Out Removal Summary

Refactored emit.py and assemble.py so build output targets `profiles/<stack>/` root instead of `profiles/<stack>/.claude/`, and removed the fan-out step that wrote skills/commands/agents/hooks/rules into the `.claude/` subdirectory tree.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Refactor emit.py — redirect targets, delete dead code | 514d987 | tools/harnessed/emit.py |
| 2 | Refactor assemble.py — remove fan-out, redirect emit calls | 2ef4eaa | tools/harnessed/assemble.py |

## What Changed

**emit.py (Task 1):**
- Deleted `PROFILE_SUBDIRS` constant (the tuple of subdir names)
- Deleted `ensure_profile_tree(harness_dir)` function
- Renamed `harness_dir` parameter to `profile_dir` in `write_mcp_json` — body already wrote `path / ".mcp.json"` so behavior is correct at profile root
- Renamed `harness_dir` parameter to `profile_dir` in `write_settings_json` — `settings.json` now emits to profile root
- All other functions (`reset_profile`, `_write_json`, `write_hatago_config`, `write_baked_manifest`, `write_derived_dockerfile`) unchanged

**assemble.py (Task 2):**
- Removed `LinkSyncer` from synclinks import (kept `CollisionError` — still used in `_merge_servers`)
- Removed `field` from dataclasses import (only used by the now-deleted `skills`/`commands` fields)
- Removed `skills: list[str]` and `commands: list[str]` fields from `AssembleResult` dataclass
- Removed `syncer = LinkSyncer()` instantiation and `syncer.add_recipe(recipe)` loop
- Removed `harness_dir = profile_dir / stack.harness_config_dir` variable
- Removed `emit.ensure_profile_tree(harness_dir)` call
- Removed `syncer.fan(harness_dir)` call
- Changed `emit.write_mcp_json(harness_dir)` to `emit.write_mcp_json(profile_dir)`
- Changed `emit.write_settings_json(harness_dir, servers)` to `emit.write_settings_json(profile_dir, servers)`
- Updated `return AssembleResult(...)` to remove `skills=` and `commands=` arguments

## Verification Results

All acceptance criteria passed:
- `python -c "import harnessed.emit; import harnessed.assemble; print('OK')"` exits 0
- `rg 'syncer|LinkSyncer|harness_dir|ensure_profile_tree|PROFILE_SUBDIRS' tools/harnessed/assemble.py tools/harnessed/emit.py` returns 0 matches
- `rg 'write_mcp_json\(profile_dir\)' tools/harnessed/assemble.py` returns 1 match
- `rg 'write_settings_json\(profile_dir' tools/harnessed/assemble.py` returns 1 match
- `AssembleResult` dataclass contains no `skills` or `commands` fields

## Deviations from Plan

None — plan executed exactly as written.

One minor additional cleanup applied as part of Task 2 (Rule 1): removed `field` from `from dataclasses import dataclass, field` since it was only used by the deleted `skills`/`commands` fields. This prevents an unused-import warning and is a direct consequence of the task's deletion.

## Known Stubs

None.

## Threat Flags

None. No new network endpoints, auth paths, or schema changes introduced. Threat mitigations T-09-A01 and T-09-A02 confirmed applied:
- T-09-A01: `write_mcp_json(profile_dir)` confirmed in assemble.py (1 match)
- T-09-A02: `reset_profile()` unchanged — still wipes and recreates profile_dir on every build

## Self-Check: PASSED
