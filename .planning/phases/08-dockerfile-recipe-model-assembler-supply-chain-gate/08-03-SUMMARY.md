---
phase: 08-dockerfile-recipe-model-assembler-supply-chain-gate
plan: "03"
subsystem: build-pipeline
tags: [bash, uat, supply-chain, derived-image, img-03, sc-01, sc-03, sc-04]
dependency_graph:
  requires: [08-01, 08-02]
  provides: [IMG-03-derived-image-build, SC-01-image-scan, SC-03-snyk-container, SC-04-doc, phase-08-uat]
  affects: [harnessed-build-pipeline, phase-8-uat-suite]
tech_stack:
  added: []
  patterns:
    - "Derived image block guarded by if [ -f derived_dockerfile ] for backward-compat"
    - "ARG HARNESS extracted from emitted Dockerfile via sed (no yq on host — pure bash)"
    - "safe-exit-capture || rc=$? pattern for osv-scanner under set -euo pipefail"
    - "TOKEN_ARGS reuse for SC-03 snyk container scan (token forwarded as env, never written to disk)"
    - "Phase UAT suite: 4 fast (manifest) + 4 heavy (container) with --quick guard"
key_files:
  created:
    - tools/uat/phase-08.sh
  modified:
    - lib/harnessed-common.sh
decisions:
  - "derived_image set inside the guard so print_success expansion only shows it when a Dockerfile was emitted"
  - "SC-04 documented via comment — socket CLI has no container-image mode; BLD-02a source scan is the satisfying artifact"
  - "Heavy UAT tests self-skip under --quick so fast CI runs remain zero-container"
metrics:
  duration: "25 minutes"
  completed: "2026-06-23"
  tasks_completed: 2
  tasks_total: 2
  files_created: 1
  files_modified: 1
---

# Phase 08 Plan 03: build_stack() Pipeline Extension + Phase 8 UAT Suite Summary

`build_stack()` extended with IMG-03 derived image build, SC-01 osv-scanner image scan, SC-03 snyk container test (warn-and-skip), and SC-04 documentation; Phase 8 UAT suite with 4 fast + 4 heavy tests covering all eleven Phase 8 requirements.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | build_stack() extension — IMG-03 + SC-01 + SC-03 + SC-04 | bd18bad | lib/harnessed-common.sh |
| 2 | Phase 8 UAT suite | 2bce3cc | tools/uat/phase-08.sh |

## What Was Built

**`lib/harnessed-common.sh` extension:** A new block inserted at the end of `build_stack()`, replacing the old `print_success` line. The block is guarded by `if [ -f "$derived_dockerfile" ]` so stacks without a recipe Dockerfile (backward-compat) skip the derived image build silently.

Inside the guard:
- **IMG-03:** Extracts `ARG HARNESS=<value>` from the emitted Dockerfile via `sed -n 's/^ARG HARNESS=//p'` (no yq on host), then runs `$CONTAINER_RUNTIME build --build-arg "HARNESS=${stack_harness}" -t harnessed-${stack}:latest -f <derived_dockerfile> $ROOT`.
- **SC-01:** Mirrors the existing BLD-02b hatago image scan — `mktemp` tar → `podman save` → `scan-image` in tools container using `|| derived_img_rc=$?` safe-exit capture (avoids `set -euo pipefail` abort on osv-scanner exit 1).
- **SC-03:** Invokes `scan-snyk-container <derived_image>` in the tools container, passing `TOKEN_ARGS` (already constructed for BLD-02a source scan). Warn-and-skip when `SNYK_TOKEN` absent — never aborts on missing token.
- **SC-04 comment:** Documents that `socket scan create` has no container-image mode; SC-04 is satisfied by the existing BLD-02a source scan covering recipe directories.

The updated `print_success` uses `${derived_image:+ + $derived_image}` to conditionally append the derived image name.

**`tools/uat/phase-08.sh`:** Phase 8 UAT suite following the `phase-06.sh` pattern (AAA markers, `needs_container` guard, `uat_run_phase` entrypoint). Eight tests: four fast (always run, no container) + four heavy (self-skip under `--quick`).

Fast tests:
- `recipe_structure` — RCP2-01/02/03: asserts gstack recipe.yaml has `harnesses:`, `expect:`, `claude`; Dockerfile uses `pnpm dlx`; stack.yaml references gstack.
- `fixtures_exist` — ASM-01/02: asserts floating-recipe Dockerfile ships with `--branch main`; omp-gstack-test declares `omp` harness.
- `rescan_filter_coverage` — SC-02: asserts `harnessed-gstack-time:latest` matches `^harnessed-` regex; rescan script ships and uses `harnessed-*` filter.
- `socket_source_scan_coverage` — SC-04: asserts SC-04 comment in `harnessed-common.sh`, `SOCKET_SECURITY_API_KEY` in `scan.py`, and `socket` reference in `build_stack()`.

Heavy tests (self-skip under --quick): `derived_image_build`, `snyk_container_skip`, `pin_validation_rejection`, `harness_compat_rejection`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Worktree sparse index caused accidental deletion of 26 files**
- **Found during:** Task 1 commit (post-commit deletion check)
- **Issue:** The worktree was initialized with a sparse index (277 files vs 303 in the base commit). When Task 1 was committed with `git add lib/harnessed-common.sh`, the commit captured only the 277 indexed files, dropping 26 files including all Phase 08-01/08-02 artifacts (`recipes/gstack/`, `recipes/floating-recipe/`, `stacks/*`, `agents/`, `.planning/` files).
- **Fix:** Used `git checkout 3036c99 -- <files>` to restore all 26 missing files into the index, then amended the commit. End state: 303 files in HEAD, 0 unexpected deletions.
- **Files affected:** 26 files restored (recipes/gstack, recipes/floating-recipe, stacks/floating-test, stacks/gstack-time, stacks/omp-gstack-test, agents/, .planning/ additions)
- **Commit:** bd18bad (amended)

## Threat Flags

No new threat surface introduced. `build_stack()` passes the derived image name as a string argument to `scan-snyk-container` (not executed). The image name is machine-generated from the stack name (no user input injection path). `TOKEN_ARGS` reuse is intentional and documented in T-08-07 (accepted).

## Self-Check: PASSED

- lib/harnessed-common.sh: contains scan-snyk-container, derived_dockerfile, derived_img_rc=0, SC-04, --build-arg "HARNESS=, if [ -f "$derived_dockerfile" ]
- tools/uat/phase-08.sh: contains uat_run_phase, 8 run_test calls, needs_container guard
- bash -n lib/harnessed-common.sh: syntax ok
- bash -n tools/uat/phase-08.sh: syntax ok
- tools/uat/run-uat.sh 08 --quick: 4 passed, 0 failed, 4 skipped
- Task 1 commit bd18bad: verified (303 files, 0 deletions vs base)
- Task 2 commit 2bce3cc: verified
