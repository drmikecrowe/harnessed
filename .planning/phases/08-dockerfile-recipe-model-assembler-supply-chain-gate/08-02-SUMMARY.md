---
phase: 08-dockerfile-recipe-model-assembler-supply-chain-gate
plan: "02"
subsystem: recipe-fixtures
tags: [recipes, stacks, test-fixtures, phase-8, validation-gates]
dependency_graph:
  requires: []
  provides: [gstack-recipe, gstack-time-stack, floating-recipe-fixture, omp-gstack-test-fixture]
  affects: [assembler-validation-tests, phase-8-uat]
tech_stack:
  added: []
  patterns: [dockerfile-recipe-model, harness-compat-gate, pin-validation-gate]
key_files:
  created:
    - recipes/gstack/recipe.yaml
    - recipes/gstack/Dockerfile
    - stacks/gstack-time/stack.yaml
    - recipes/floating-recipe/recipe.yaml
    - recipes/floating-recipe/Dockerfile
    - stacks/floating-test/stack.yaml
    - stacks/omp-gstack-test/stack.yaml
  modified: []
decisions:
  - "gstack Dockerfile uses pnpm dlx @gstack/install --version 1.2.3 (pinned, no --branch, no :latest)"
  - "floating-recipe Dockerfile uses example.com/fake-repo.git (unreachable URL) to prevent accidental real execution"
  - "ARG HARNESS=claude placed first in each Dockerfile (stripped by assembler, retained for standalone build reference)"
  - "No FROM line in recipe Dockerfiles — assembler provides the canonical FROM header"
metrics:
  duration: "8 minutes"
  completed: "2026-06-23"
  tasks_completed: 2
  tasks_total: 2
  files_created: 7
  files_modified: 0
---

# Phase 08 Plan 02: Recipe Artifacts and Test Fixtures Summary

Seven YAML and Dockerfile fixtures that provide Phase 8 success-criteria verification (gstack-time stack) and assembler rejection tests (floating-ref ASM-02 and harness-compat ASM-01).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | gstack recipe + gstack-time stack | 359fb0a | recipes/gstack/recipe.yaml, recipes/gstack/Dockerfile, stacks/gstack-time/stack.yaml |
| 2 | Rejection test fixtures | 807a7b7 | recipes/floating-recipe/recipe.yaml, recipes/floating-recipe/Dockerfile, stacks/floating-test/stack.yaml, stacks/omp-gstack-test/stack.yaml |

## What Was Built

**gstack recipe** (`recipes/gstack/`): A minimal claude-only recipe that exercises the Phase 8 Dockerfile recipe model. Declares `harnesses: [claude]` and `expect: [gstack-skill]`. Its Dockerfile uses `pnpm dlx @gstack/install --version 1.2.3` (pinned, no FROM line, no floating refs).

**gstack-time stack** (`stacks/gstack-time/`): Combines the gstack and time recipes under harness claude. This is the Phase 8 success-criteria stack — `harnessed build gstack-time` must succeed end-to-end.

**floating-recipe fixture** (`recipes/floating-recipe/`): A recipe whose Dockerfile contains `git clone --branch main https://example.com/fake-repo.git` — the floating `--branch main` ref that `validate_pin()` must catch and raise `PinValidationError` before any image build. The URL is intentionally unreachable.

**floating-test stack** (`stacks/floating-test/`): References floating-recipe; used by `test_pin_validation_rejects_floating` UAT test to assert ASM-02 gate behavior.

**omp-gstack-test stack** (`stacks/omp-gstack-test/`): Declares `harness: omp` with `recipes: [gstack]`. Since gstack declares `harnesses: [claude]`, the assembler's `validate_harness_compat()` raises `HarnessCompatError` at assembly time. Used by `test_harness_compat_rejected` UAT test.

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — all files are complete fixtures with no wired data dependencies.

## Threat Flags

No new threat surface introduced. All fixtures are data files (YAML + Dockerfile) with no network endpoints, auth paths, or schema changes. The floating-recipe Dockerfile uses `example.com/fake-repo.git` (RFC 2606 reserved, unreachable) to prevent accidental real execution.

## Self-Check: PASSED

- recipes/gstack/recipe.yaml: FOUND (contains harnesses: [claude], expect: [gstack-skill])
- recipes/gstack/Dockerfile: FOUND (contains pnpm dlx, no FROM, no --branch)
- stacks/gstack-time/stack.yaml: FOUND (contains gstack, harness: claude)
- recipes/floating-recipe/Dockerfile: FOUND (contains --branch main)
- stacks/floating-test/stack.yaml: FOUND (contains floating-recipe)
- stacks/omp-gstack-test/stack.yaml: FOUND (harness: omp, recipes: [gstack])
- Task 1 commit 359fb0a: verified
- Task 2 commit 807a7b7: verified
