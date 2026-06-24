---
phase: 11-architecture-documentation
plan: "04"
subsystem: docs
tags: [documentation, terminology, stack-centric]
dependency_graph:
  requires: []
  provides: [DOC2-01]
  affects: [docs/guides/troubleshooting.md, docs/guides/service-authoring.md, docs/guides/secrets.md]
tech_stack:
  added: []
  patterns: []
key_files:
  modified:
    - docs/guides/troubleshooting.md
    - docs/guides/service-authoring.md
    - docs/guides/secrets.md
decisions:
  - "Preserve config: isolated YAML field value in service-authoring.md code block as a technical identifier (actual field in stack.yaml)"
  - "Preserve lib/harnessed-isolated.sh file path references in troubleshooting.md unchanged"
  - "Rephrase 'Transparent mode never rw-mounts' to describe behavior directly without the mode name"
  - "Remove (isolated)/(transparent) mode-name annotations from secrets.md env-file spread description"
metrics:
  duration: "~4 minutes"
  completed: "2026-06-24"
  tasks_completed: 2
  tasks_total: 2
  files_changed: 3
---

# Phase 11 Plan 04: De-narrative guide docs — remove isolated/transparent terminology Summary

Surgical removal of narrative uses of "isolated" and "transparent" from three guide docs, replacing with stack-centric terminology ("stack instance", "stack", "harnessed stack") per DOC2-01.

## Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| 1 | De-narrative troubleshooting.md — replace isolated/transparent with stack terminology | bfbd7ac |
| 2 | De-narrative service-authoring.md + secrets.md | 7fd5b8f |

## Changes Made

### troubleshooting.md (6 narrative replacements)

- "Isolated mode — the harness container..." → "The harness stack — the harness container..."
- "Running an unbuilt isolated stack" → "Running an unbuilt stack"
- "An isolated instance authenticates" → "A stack instance authenticates"
- "in an isolated instance" → "in a stack instance"
- "Transparent mode never rw-mounts..." → "When running with host config mounted live..." (behavioral description)
- "By default an isolated instance persists" → "By default a stack instance persists"
- Preserved: `lib/harnessed-isolated.sh` file path link (technical reference, line 108)

### service-authoring.md (1 narrative replacement)

- "by default isolated stacks use rootless (pasta) networking" → "by default stacks use rootless (pasta) networking"
- Preserved: `config: isolated` in YAML code block (actual config field value from stack.yaml)
- Preserved: `# ← the isolated launcher runs ensure_service_up(ping) on launch` comment (code component reference in code block)

### secrets.md (2 narrative replacements)

- "# 3. Launch any isolated stack." → "# 3. Launch any stack."
- "both pod members (isolated), the instance (transparent), the sidecar" → "both pod members, the sidecar" (mode-name annotations removed)

## Verification

Final check across all three files:
- `rg -n "isolated|transparent" docs/guides/troubleshooting.md` → 1 match: `lib/harnessed-isolated.sh` file path (technical)
- `rg -n "isolated|transparent" docs/guides/service-authoring.md` → 2 matches: both inside fenced code block (technical config values)
- `rg -n "isolated|transparent" docs/guides/secrets.md` → 0 matches

`rg -n "stack instance" docs/guides/troubleshooting.md` → 3 matches (replacements confirmed).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing coverage] Fixed additional narrative uses in secrets.md lines 54-55**
- **Found during:** Task 2 verification
- **Issue:** Worktree copy of secrets.md had `(isolated)` and `(transparent)` mode-name annotations at lines 54-55 that the plan did not specifically call out (the plan cited only line 29). These are narrative uses not present in the shared-checkout version.
- **Fix:** Removed the mode-name parenthetical annotations, leaving the functional description intact: "both pod members, the sidecar (svc up), and the scan step (harnessed build)"
- **Files modified:** docs/guides/secrets.md
- **Commit:** 7fd5b8f

**2. [Rule 2 - Missing coverage] Fixed additional narrative use in troubleshooting.md lines 100-102**
- **Found during:** Task 1 — worktree copy had a bullet not present in shared-checkout
- **Issue:** "Transparent mode never rw-mounts the host `.claude.json`" — uses "Transparent mode" as a narrative mode name
- **Fix:** Rephrased to describe behavior directly: "When running with host config mounted live, the host `.claude.json` is never rw-mounted"
- **Files modified:** docs/guides/troubleshooting.md
- **Commit:** bfbd7ac

## Known Stubs

None — documentation-only plan, no code stubs.

## Threat Flags

None — documentation-only changes; no new network endpoints, auth paths, file access patterns, or schema changes.

## Self-Check: PASSED

- [x] docs/guides/troubleshooting.md modified (bfbd7ac)
- [x] docs/guides/service-authoring.md modified (7fd5b8f)
- [x] docs/guides/secrets.md modified (7fd5b8f)
- [x] Zero narrative uses of isolated/transparent remain in target files
- [x] Technical file path references preserved unchanged
