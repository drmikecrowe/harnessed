---
phase: 08-dockerfile-recipe-model-assembler-supply-chain-gate
plan: 01
subsystem: infra
tags: [python, assembler, dockerfile, snyk, schema, validation, supply-chain]

# Dependency graph
requires: []
provides:
  - HarnessCompatError and PinValidationError error classes in schema.py
  - harnesses and expect fields on Recipe dataclass with backward-compat defaults
  - _FLOATING_REF_RE regex for floating ref detection
  - validate_pin() raising PinValidationError on floating Dockerfile refs
  - validate_harness_compat() raising HarnessCompatError for incompatible harness compositions
  - write_derived_dockerfile() emitter producing Dockerfile.harnessed-<stack> artifacts
  - Validation wiring in assemble() — both validators called before any file is emitted
  - run_snyk_container_scan() with warn-and-skip behavior when SNYK_TOKEN absent
  - scan-snyk-container CLI subcommand
affects:
  - 08-dockerfile-recipe-model-assembler-supply-chain-gate
  - future phases using assemble() to build derived Dockerfiles
  - Phase 10 capabilities oracle (expect: field collected here, validated later)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Validation-before-emit: all validators run before first write in assemble()"
    - "Warn-and-skip for token-gated scans: returns ScanResult with warning, never raises on missing token"
    - "ARG HARNESS before/after FROM: parameterized Dockerfile base for multi-harness support"
    - "Recipe FROM stripping: recipe Dockerfiles have FROM and ARG HARNESS lines filtered on concatenation"

key-files:
  created: []
  modified:
    - tools/harnessed/schema.py
    - tools/harnessed/emit.py
    - tools/harnessed/assemble.py
    - tools/harnessed/scan.py
    - tools/harnessed/cli.py

key-decisions:
  - "expect: field is data model only in Phase 8 — runtime capability-coverage check deferred to Phase 10 (RCP2-03 partial scope)"
  - "Negative lookbehind (?<!\\w) before :latest prevents false positives on URL path segments"
  - "snyk container exit code 2 treated as warn (no daemon socket in tools container) not error"
  - "ARG HARNESS re-declared after FROM so recipe RUN instructions can reference ${HARNESS}"

patterns-established:
  - "validate_harness_compat + validate_pin called in same loop as validate_no_raw_npm — all pre-emission gates together"
  - "write_derived_dockerfile called after write_hatago_config as last assembler emit step"

requirements-completed: [RCP2-01, RCP2-02, RCP2-03, ASM-01, ASM-02, ASM-03, SC-03]

# Metrics
duration: ~25min
completed: 2026-06-23
---

# Phase 08 Plan 01: Schema Extensions, Derived Dockerfile Emitter, and Snyk Container Scan Summary

**Recipe schema extended with harnesses/expect fields and pre-emission validators; write_derived_dockerfile() emitter and run_snyk_container_scan() with warn-and-skip behavior wired into assembler and CLI**

## Performance

- **Duration:** ~25 min
- **Completed:** 2026-06-23
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments

- Schema extended with `harnesses:` and `expect:` fields, `HarnessCompatError`, `PinValidationError`, `_FLOATING_REF_RE`, `validate_pin()`, and `validate_harness_compat()` — all threat mitigations T-08-01 and T-08-02 implemented
- `write_derived_dockerfile()` emitter produces `Dockerfile.harnessed-<stack>` with canonical `ARG HARNESS` before/after FROM and concatenated recipe bodies with FROM/ARG HARNESS lines stripped
- `assemble()` validation loop extended: `validate_harness_compat` and `validate_pin` called before any emit; `write_derived_dockerfile` called as final emit step
- `run_snyk_container_scan()` + `scan-snyk-container` CLI subcommand added with warn-and-skip when SNYK_TOKEN absent

## Task Commits

1. **Task 1: Schema extension — harnesses, expect, error classes, validators** - `29031dd` (feat)
2. **Task 2: Emit write_derived_dockerfile + assemble wiring** - `05ec99f` (feat)
3. **Task 3: Snyk container scan function + CLI subcommand (SC-03)** - `8ac974d` (feat)

## Files Created/Modified

- `tools/harnessed/schema.py` - Added HarnessCompatError, PinValidationError, harnesses/expect Recipe fields, _FLOATING_REF_RE, validate_pin(), validate_harness_compat(), extended load_recipe()
- `tools/harnessed/emit.py` - Added Recipe import, write_derived_dockerfile() emitter
- `tools/harnessed/assemble.py` - Extended validation loop and added write_derived_dockerfile() call
- `tools/harnessed/scan.py` - Added _scan_snyk_container_image(), run_snyk_container_scan()
- `tools/harnessed/cli.py` - Added scan-snyk-container subcommand with image_name positional arg

## Decisions Made

- `expect:` field is Phase 8 data model only — stored in Recipe and loaded from recipe.yaml, but runtime capability-coverage validation deferred to Phase 10 when the capabilities oracle exists (RCP2-03 partial scope). No `validate_expect_coverage()` added here.
- Negative lookbehind `(?<!\w)` before `:latest` prevents false positives on URL path segments like `https://example.com/latest/release`.
- snyk container exit code 2 (scan failure / no daemon socket) treated as warning rather than error — tools container may not have the podman socket mounted during scan.
- Bare `ARG HARNESS` re-declared after FROM so recipe RUN instructions referencing `${HARNESS}` resolve correctly within the build stage.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All Phase 08 building blocks are in place: schema validators, derived Dockerfile emitter, and snyk container scan gate
- `assemble()` now validates harness compat and floating refs before any file is written
- `harnessed build` will emit `Dockerfile.harnessed-<stack>` as part of assembly
- Phase 10 can query `recipe.expect` for capabilities oracle validation

---
*Phase: 08-dockerfile-recipe-model-assembler-supply-chain-gate*
*Completed: 2026-06-23*
