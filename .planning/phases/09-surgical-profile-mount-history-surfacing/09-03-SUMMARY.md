---
phase: 09-surgical-profile-mount-history-surfacing
plan: "03"
subsystem: launcher
tags: [mount, profile, mcp, workdir, path-mirroring]
dependency_graph:
  requires: [09-01]
  provides: [wired-isolated-launcher]
  affects: [lib/harnessed-isolated.sh]
tech_stack:
  added: []
  patterns: [manifest-driven-mounts, path-mirroring-workdir, surgical-profile-mount]
key_files:
  modified:
    - lib/harnessed-isolated.sh
decisions:
  - "Replace whole-dir .claude copy-and-mount with single harnessed_manifest_mounts call (MNT2-01)"
  - "Guard updated to check .mcp.json at profile root (D-10) — stale .claude/-only profiles now force rebuild"
  - "All exec -w flags changed to $project_path for consistent path mirroring (MNT2-02)"
  - "mcp_cfg changed to $CONTAINER_HOME/.mcp.json (Pitfall 1) — .mcp.json is now at container HOME root"
metrics:
  duration: "8 minutes"
  completed: "2026-06-24"
---

# Phase 09 Plan 03: Wire Isolated Launcher to Manifest-Driven Mounts Summary

Six targeted changes applied to `lib/harnessed-isolated.sh` to wire the manifest-driven mount system, eliminate the whole-directory `.claude/` copy-and-mount block, update the is-built guard, and fix workdir and MCP config path for path mirroring.

## Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| 1 | Source manifest-mounts helper, update is-built guard, replace copy-mount block | 6f1f6be |
| 2 | Fix workdir flags (both exec blocks) and mcp_cfg path | 640d063 |

## Changes Applied

**Change A — Source new helper (D-01):**
Added `. "$HARNESSED_DIR/lib/harnessed-manifest-mounts.sh"` after the existing source block (after `harnessed-services.sh`).

**Change B — Is-built guard (D-10):**
Changed `[ -d "$profile_dir/.claude" ]` to `[ -f "$profile_dir/.mcp.json" ]`. Stale profiles with `.claude/` but no `.mcp.json` at root now force `harnessed build $stack`.

**Change C — Replace copy-mount block (MNT2-01):**
Removed the 8-line block (declare `state_project`, declare `run_claude`, `mkdir -p`, conditional `rm -rf` + `cp -a`, `MOUNT_ARGS+=`) and its preceding descriptive comment. Replaced with one line:
`harnessed_manifest_mounts "$harness" "$profile_dir" "$project_path" "$relpath"`

**Change D — mcp_cfg path (Pitfall 1):**
Changed `local mcp_cfg="$CONTAINER_HOME/.claude/.mcp.json"` to `local mcp_cfg="$CONTAINER_HOME/.mcp.json"`. The `.mcp.json` is now mounted at container HOME root by the manifest helper (not inside `.claude/`).

**Change E — Workdir in re-attach exec block (MNT2-02):**
Changed all 6 `-w "$CONTAINER_HOME/$relpath"` occurrences in the re-attach block to `-w "$project_path"`.

**Change F — Workdir in new-pod exec block (MNT2-02):**
Changed all 6 `-w "$CONTAINER_HOME/$relpath"` occurrences in the new-pod exec block to `-w "$project_path"`.

## Verification Results

All checks pass:
- `bash -n lib/harnessed-isolated.sh` exits 0
- `harnessed-manifest-mounts.sh` sourced: 1 match
- Old `[ -d profile_dir/.claude ]` guard: 0 matches
- New `[ -f profile_dir/.mcp.json ]` guard: 1 match
- `cp -a` removed: 0 matches
- `harnessed_manifest_mounts` call: 1 match
- `-w "$CONTAINER_HOME/$relpath"` removed: 0 matches
- `$CONTAINER_HOME/.claude/.mcp.json` removed: 0 matches
- `$CONTAINER_HOME/.mcp.json` present: 1 match
- `-w "$project_path"` in exec blocks: 12 matches (6 re-attach + 6 new-pod)

## Deviations from Plan

None — plan executed exactly as written.

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced. The changes reduce exposure by replacing whole-dir `.claude/` mounts with surgical per-file ro mounts (T-09-B01 mitigated). mcp_cfg now points to a ro-mounted file (T-09-B02 mitigated). Guard update forces rebuild of stale profiles (T-09-B04 mitigated).

## Self-Check: PASSED

- `lib/harnessed-isolated.sh` exists and passes `bash -n`
- Commits 6f1f6be and 640d063 present in git log
