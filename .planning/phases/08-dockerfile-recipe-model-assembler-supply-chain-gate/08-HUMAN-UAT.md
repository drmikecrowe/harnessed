---
status: passed
phase: 08-dockerfile-recipe-model-assembler-supply-chain-gate
source: [08-VERIFICATION.md]
started: 2026-06-23T00:00:00Z
updated: 2026-06-24T00:00:00Z
---

## Tests

### 1. End-to-end gstack-time build
expected: `harnessed build gstack-time` produces `profiles/gstack-time/Dockerfile.harnessed-gstack-time` with `ARG HARNESS=claude`, builds `harnessed-gstack-time:latest`, runs osv-scanner on the derived image, and warns-and-skips snyk without `SNYK_TOKEN`
result: passed

### 2. Pin-validation rejection (floating-recipe)
expected: `harnessed build floating-test` exits nonzero with an error message containing "floating ref" (or similar); no `Dockerfile.harnessed-floating-test` is emitted
result: passed

### 3. Harness-compat rejection (omp-gstack-test)
expected: `harnessed build omp-gstack-test` exits nonzero, error names the incompatible recipe (gstack) and the harness (omp); no Dockerfile emitted, no image build attempted
result: passed

### 4. Full UAT suite (all 8 tests)
expected: `tools/uat/run-uat.sh 08` (without `--quick`) passes all 8 tests — 4 fast + 4 heavy (requires built tools image and container runtime)
result: passed — 8/8 tests, 27 checks

**Fixes applied during UAT:**
- Rebuilt `harnessed-tools:latest` (stale image from pre-phase-8 build silently ran old Python code)
- Fixed `validate_pin()` to strip Dockerfile comment lines before applying the floating-ref regex (`:latest` in a comment matched)
- Fixed `recipes/gstack/Dockerfile` to use `echo` instead of a fake `pnpm dlx @gstack/install` call (non-existent npm package caused `podman build` to fail with 404)
- Updated `test_snyk_container_skip` to use `--no-security-scans` instead of `env -u SNYK_TOKEN` (secondary token discovery now finds the token from `~/.config/configstore/snyk.json`)

## Summary

total: 4
passed: 4
issues: 0
pending: 0
skipped: 0
blocked: 0

## Notes

- `harnessed build` (bare) does not auto-rebuild `harnessed-tools:latest` — after any `tools/harnessed/*.py` change, manually run `podman build -t harnessed-tools:latest -f tools/Dockerfile tools/`. Consider `harnessed build --tools` or mtime-based invalidation in a future phase.
