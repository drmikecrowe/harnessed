---
status: partial
phase: 08-dockerfile-recipe-model-assembler-supply-chain-gate
source: [08-VERIFICATION.md]
started: 2026-06-23T00:00:00Z
updated: 2026-06-23T00:00:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. End-to-end gstack-time build
expected: `harnessed build gstack-time` produces `profiles/gstack-time/Dockerfile.harnessed-gstack-time` with `ARG HARNESS=claude`, builds `harnessed-gstack-time:latest`, runs osv-scanner on the derived image, and warns-and-skips snyk without `SNYK_TOKEN`
result: [pending]

### 2. Pin-validation rejection (floating-recipe)
expected: `harnessed build floating-test` exits nonzero with an error message containing "floating ref" (or similar); no `Dockerfile.harnessed-floating-test` is emitted
result: [pending]

### 3. Harness-compat rejection (omp-gstack-test)
expected: `harnessed build omp-gstack-test` exits nonzero, error names the incompatible recipe (gstack) and the harness (omp); no Dockerfile emitted, no image build attempted
result: [pending]

### 4. Full UAT suite (all 8 tests)
expected: `tools/uat/run-uat.sh 08` (without `--quick`) passes all 8 tests — 4 fast + 4 heavy (requires built tools image and container runtime)
result: [pending]

## Summary

total: 4
passed: 0
issues: 0
pending: 4
skipped: 0
blocked: 0

## Gaps
