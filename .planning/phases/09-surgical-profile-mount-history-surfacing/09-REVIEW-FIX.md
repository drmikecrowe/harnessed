---
phase: "09"
status: partial
findings_in_scope: 7
fixed: 6
skipped: 1
iteration: 1
fix_scope: critical_warning
---

# Phase 09 — Code Review Fix Report

## Fixed findings

### CR-01 — yq stderr suppressed, exit unchecked (commit 897692a)
**File:** `lib/harnessed-manifest-mounts.sh`

Captured yq output into a variable with exit-code check; propagates failure as a
warning + `return 1` instead of silently proceeding with zero mounts. Removed
`2>/dev/null` suppression from both yq calls.

### WR-01 — yq emits literal "null" for absent keys (commit 897692a)
**File:** `lib/harnessed-manifest-mounts.sh`

Added `|| [ "$f" = "null" ]` and `|| [ "$d" = "null" ]` guards so yq's literal
`"null"` output for absent YAML keys is skipped alongside the empty-string guard.

### CR-02 — test_path_mirroring asserts wrong values (commit ee76bd8)
**File:** `tools/uat/phase-09.sh`

Replaced the broken assertion (UAT cwd vs container default WORKDIR) with two
correct checks: `test -d '$proj'` inside the container verifies the bind mount
exists, and `exec -w "$proj" pwd` verifies the working directory is set correctly.

### WR-02 — needs_container() semantically inverted (commit ee76bd8)
**File:** `tools/uat/phase-09.sh`

Renamed `needs_container()` → `skip_if_quick()` and updated all 4 call sites so
the intent reads correctly without logic inversion.

### WR-03 — omp slug computation diverges from production (commit ee76bd8)
**File:** `tools/uat/phase-09.sh`

Replaced `realpath --relative-to="$HOME"` with the exact `project_relpath()` logic
(basename fallback for paths outside `$HOME`) so the omp slug matches production.

### WR-04 — ARG HARNESS filter too broad in emit.py (commit 00e9aa5)
**File:** `tools/harnessed/emit.py`

Compiled `_ARG_HARNESS_RE = re.compile(r'^ARG\s+HARNESS\s*$', re.IGNORECASE)` to
match only the exact `ARG HARNESS` token. Replaced the `startswith("ARG HARNESS")`
check so `ARG HARNESS_PROXY_URL` and similar recipe ARGs are no longer silently stripped.

## Skipped findings

### CR-03 — hatago readiness loop falls through silently (harnessed-isolated.sh:207-210)
**Reason:** Pre-existing infrastructure predating Phase 09. The hatago readiness loop
is cross-harness shared code; fixing it carries integration risk beyond the Phase 09
scope. Should be addressed as a standalone fix with full integration testing.

## Remaining issues

- **CR-03** requires a targeted fix in `lib/harnessed-isolated.sh` hatago readiness
  loop to emit an error after the 30s timeout instead of silently attaching to a dead
  MCP connection.
