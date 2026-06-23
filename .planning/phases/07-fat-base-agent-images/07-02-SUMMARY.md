---
phase: 07-fat-base-agent-images
plan: "02"
subsystem: image-build
tags: [agents, build, img-02, omp, claude]
dependency_graph:
  requires: []
  provides: [agents/claude/agent.yaml, agents/omp/agent.yaml, build_images-omp-block]
  affects: [lib/harnessed-common.sh, harnessed-build-bare]
tech_stack:
  added: []
  patterns: [agent-descriptor-yaml, four-image-build-sequence]
key_files:
  created:
    - agents/claude/agent.yaml
    - agents/omp/agent.yaml
  modified:
    - lib/harnessed-common.sh
decisions:
  - "build_images() order is base→claude→omp→hatago — omp placed before hatago so all agent images are ready before the hub image that may depend on them at runtime"
  - "ensure_images() checks all four images so first-run auto-build covers omp; ensure_omp_image() kept as lazy fallback for stacks where omp was removed post-build"
metrics:
  duration: "5m"
  completed: "2026-06-23"
  tasks_completed: 2
  files_changed: 3
---

# Phase 7 Plan 02: Agent Descriptors and OMP Build Integration Summary

Agent YAML descriptors created for claude and omp harnesses; `build_images()` updated to produce all four images (base, claude, omp, hatago) on a bare `harnessed build` invocation (IMG-02).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create agents/ directory with claude and omp agent.yaml descriptors | 4495204 | agents/claude/agent.yaml, agents/omp/agent.yaml |
| 2 | Update build_images() to include harnessed-omp in bare build | 3c30d48 | lib/harnessed-common.sh |

## What Was Built

**agents/claude/agent.yaml** — type:agent descriptor for harnessed-claude. Declares harness, image name, Dockerfile path, and description. Static metadata; no execution path.

**agents/omp/agent.yaml** — type:agent descriptor for harnessed-omp. Documents the omp harness (FROM harnessed-base + omp v16 + claude-hooks-bridge). Same schema as claude descriptor.

**lib/harnessed-common.sh (build_images)** — Added omp build block between the claude and hatago blocks. Build order is now: base → claude → omp → hatago. Updated the function comment to match.

**lib/harnessed-common.sh (ensure_images)** — Extended the missing-image condition to also check `HARNESSED_OMP_IMAGE`, so `harnessed build` (bare, no stack arg) on a fresh install triggers a build for all four images.

`ensure_omp_image()` left unchanged — it remains the lazy-build fallback for omp stacks when the image is absent after initial build.

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None.

## Threat Flags

None. The agent.yaml files contain only static structural metadata (image name, dockerfile path, description text) — no secrets, no code execution paths, no new network endpoints.

## Self-Check: PASSED

- agents/claude/agent.yaml: FOUND
- agents/omp/agent.yaml: FOUND
- omp build block in build_images(): FOUND (lines 91-95)
- ensure_images() OMP condition: FOUND
- ensure_omp_image() still present: FOUND (6 occurrences)
- Commits: 4495204 and 3c30d48 verified in git log
