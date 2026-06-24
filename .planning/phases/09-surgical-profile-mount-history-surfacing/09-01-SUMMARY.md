---
phase: 09-surgical-profile-mount-history-surfacing
plan: "01"
subsystem: mount-manifests
tags: [bash, yaml, mounts, history-surfacing, profile-mount]
dependency_graph:
  requires: []
  provides:
    - lib/manifests/claude.yaml
    - lib/manifests/omp.yaml
    - lib/manifests/antigravity.yaml
    - lib/manifests/opencode.yaml
    - lib/manifests/gemini.yaml
    - lib/manifests/codex.yaml
    - lib/harnessed-manifest-mounts.sh
  affects:
    - lib/harnessed-isolated.sh (will source harnessed-manifest-mounts.sh in Phase 9 Plan 02)
tech_stack:
  added: []
  patterns:
    - YAML manifest per harness parsed with yq at launch time
    - MOUNT_ARGS append pattern (caller-owns-array convention from harnessed-mounts.sh)
    - mkdir -p before every history dir bind (DooD pitfall guard)
    - omp slug derived from HOST relpath (not CONTAINER_HOME-relative)
key_files:
  created:
    - lib/manifests/claude.yaml
    - lib/manifests/omp.yaml
    - lib/manifests/antigravity.yaml
    - lib/manifests/opencode.yaml
    - lib/manifests/gemini.yaml
    - lib/manifests/codex.yaml
    - lib/harnessed-manifest-mounts.sh
  modified: []
decisions:
  - "Profile file target paths are harness-aware in the bash function (not encoded in YAML) per D-03: claude/omp/opencode mount to ~/.claude/<f>; gemini/antigravity/codex skip (config baked in image)"
  - "omp history_dirs is empty in YAML — per-slug bind lives in bash function to avoid mounting all sessions (Pitfall 2)"
  - "antigravity history mounts .gemini/antigravity-cli/{conversations,brain,implicit} only — never parent .gemini/ (Pitfall 6)"
  - "Path mirroring bind (-v project_path:project_path) appended for all harnesses in harnessed_manifest_mounts"
metrics:
  duration: "~8 minutes"
  completed: "2026-06-24T13:14:00Z"
  tasks_completed: 2
  tasks_total: 2
  files_created: 7
  files_modified: 0
---

# Phase 09 Plan 01: Per-Harness YAML Mount Manifests + harnessed_manifest_mounts Summary

Six per-harness YAML mount manifests in `lib/manifests/` and `lib/harnessed-manifest-mounts.sh` bash helper that reads them at launch time to append surgical profile-file ro-mounts and history-dir rw-mounts to MOUNT_ARGS.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create six per-harness YAML manifests in lib/manifests/ | ca432e9 | lib/manifests/claude.yaml, omp.yaml, antigravity.yaml, opencode.yaml, gemini.yaml, codex.yaml |
| 2 | Create lib/harnessed-manifest-mounts.sh | a7083a6 | lib/harnessed-manifest-mounts.sh |

## What Was Built

### Six Per-Harness YAML Manifests (MNT2-06)

Each manifest has exactly two top-level keys per D-02:

- **`profile_files`**: filenames (`[.mcp.json, settings.json]`) to mount ro from `profiles/<stack>/` into the container. All six manifests list both files; the bash function branches on harness to determine the container target path (D-03).
- **`history_dirs`**: `$HOME`-relative paths to rw-mount for history surfacing.

Manifest contents:
- **claude.yaml**: 5 history_dirs — `.claude/projects`, `.claude/file-history`, `.claude/tasks`, `.claude/session-env`, `.claude/todos` (all MNT2-03 dirs, D-05)
- **omp.yaml**: empty `history_dirs` — per-slug bind is in the bash function to avoid exposing all projects (Pitfall 2)
- **antigravity.yaml**: 3 history_dirs — `.gemini/antigravity-cli/conversations`, `.gemini/antigravity-cli/brain`, `.gemini/antigravity-cli/implicit` (MNT2-05; never parent `.gemini/`, Pitfall 6)
- **opencode.yaml**: empty history_dirs, history deferred to Phase 10 / MNT2-07
- **gemini.yaml**: empty history_dirs, history deferred to Phase 10 / MNT2-07
- **codex.yaml**: empty history_dirs, history deferred to Phase 10 / MNT2-07

No manifest contains: `agent.db`, `antigravity-oauth-token`, `.credentials.json`, or any parent directory containing auth credentials alongside history.

### lib/harnessed-manifest-mounts.sh

Function `harnessed_manifest_mounts harness profile_dir project_path relpath`:

1. **Guard**: if manifest missing, calls `print_warning` and returns 0 (safe default — no mount is safer than wrong mount, T-09-04)
2. **Profile files loop**: yq-reads `profile_files[]`, derives harness-aware container target (claude/omp/opencode to `~/.claude/<f>`; gemini/antigravity/codex skip per Pitfall 4)
3. **History dirs loop**: yq-reads `history_dirs[]`, calls `mkdir -p` before each bind (DooD pitfall guard), appends `$HOME/<d>:$CONTAINER_HOME/<d>:rw`
4. **omp slug block**: `if [ "$harness" = "omp" ]` computes `omp_slug="-${relpath//\//'-'}"` from HOST relpath (not container HOME-relative), `mkdir -p` + bind per Pitfall 2
5. **Path mirroring**: appends `-v "$project_path:$project_path"` for all harnesses (MNT2-02)

Does not declare `MOUNT_ARGS=()` (caller owns the array). Uses `print_warning` (not `echo`) for non-fatal conditions. Uses `if [ "$harness" = "X" ]` style matching codebase convention.

## Verification Results

- `bash -n lib/harnessed-manifest-mounts.sh` exits 0
- All 6 manifests parse cleanly under `yq`
- `yq '.history_dirs[]' lib/manifests/claude.yaml` emits 5 lines starting with `.claude/`
- `yq '.history_dirs[]' lib/manifests/antigravity.yaml` emits 3 lines starting with `.gemini/antigravity-cli/`
- `yq '.history_dirs[]' lib/manifests/omp.yaml` emits 0 lines (empty)
- No auth credential paths in any manifest's data sections (terms appear only in `# NEVER list` comment lines)

## Deviations from Plan

None — plan executed exactly as written. The PATTERNS.md function shape was followed directly.

## Known Stubs

None — all files are complete per plan scope. History surfacing for opencode/gemini/codex is explicitly deferred to Phase 10 / MNT2-07 by design, not a stub.

## Threat Flags

No new threat surface beyond what was analyzed in the plan's threat model. All T-09-01 through T-09-03 mitigations are implemented:
- T-09-01: Manifests list specific named subdirs only; auth files explicitly excluded
- T-09-02: omp slug from HOST relpath + mkdir -p before bind
- T-09-03: Only `.gemini/antigravity-cli/{conversations,brain,implicit}` mounted, never `.gemini/` proper

## Self-Check: PASSED

All 7 created files verified present on disk. Commits ca432e9 and a7083a6 confirmed in git log.
