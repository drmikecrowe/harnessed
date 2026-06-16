---
status: complete
phase: 03-supply-chain-gate-pnpm-everywhere
source: [03-01-SUMMARY.md, 03-02-SUMMARY.md]
started: 2026-06-16T00:46:58Z
updated: 2026-06-16T00:52:25Z
mode: mvp
user_story: "As a stack author, I want to build stacks knowing `harnessed build` enforces pnpm-everywhere managed config and a credential-free HIGH-severity scan gate, so that no dependency with a high-severity vulnerability is committed or baked into an image."
outcome_clause: "no dependency with a high-severity vulnerability is committed or baked into an image"
---

## Current Test

[testing complete]

## Tests

### 1. Cold Start Smoke Test
expected: From a clean image state, rebuild all harnessed images via `./harnessed build` (or `harnessed --build`). Images build without errors; tools image seeds the offline osv-scanner PyPI+npm DBs (log: "Loaded npm local db" + "Loaded PyPI local db"). Then `./harnessed build tracer-time` assembles, scans, and exits 0 with a success message.
section: smoke
result: pass

### 2. Build a clean stack (user flow)
expected: Run `./harnessed build tracer-time`. The build assembles the stack, routes JavaScript installs through pnpm v11 (log: "Done in Xs using pnpm v11"), runs the credential-free source scan + host image scan, and exits 0 with a success message. No HIGH-severity finding aborts the build.
section: user-flow
result: pass

### 3. HIGH-vuln stack aborts before bake (user flow → outcome)
expected: Run `./harnessed build vuln-stack --root tools/test-fixtures` (fixture: requests==2.19.0, CVSS 7.5). The build ABORTS with a non-zero exit BEFORE any image is baked, reporting the HIGH finding (GHSA-x84v-xcm2-53pg / CVE-2018-18074). The vulnerable dependency does NOT reach a baked image.
section: user-flow
result: pass

### 4. Sub-HIGH stack builds green (severity-gate proof)
expected: Run `./harnessed build low-stack --root tools/test-fixtures` (fixture: mistune==0.7.4, max CVSS 6.1 < 7.0). The build completes successfully (exit 0); findings appear as WARNINGS, not blockers. Proves the gate is severity-driven (CVSS>=7.0), not exit-1-on-any-finding.
section: technical
result: pass

### 5. Raw npm/npx recipe rejected with pnpm equivalent
expected: Build/assemble a recipe using raw `npm`/`npx` (`./harnessed build npm-stack --root tools/test-fixtures`, or `harnessed-cli assemble npm-stack --root tools/test-fixtures`). The assembler aborts BEFORE emit, naming the pnpm equivalent (`npx` -> `pnpm dlx`, `npm install` -> `pnpm install`). A benign token like `npmlog` is NOT flagged.
section: technical
result: pass
evidence: "assemble failed: recipe 'npm-recipe': MCP server 'npx-server' uses raw 'npx'. Use the pnpm equivalent 'pnpm dlx'"

### 6. pnpm managed config live in rebuilt images
expected: In a rebuilt harnessed-base or hatago image, `pnpm config list` shows the 5 live controls with no warnings: minimumReleaseAge=1440, minimumReleaseAgeStrict=true, blockExoticSubdeps=true, verifyStoreIntegrity=true, strictDepBuilds=true. `pnpm --version` reports 11.6.0.
section: technical
result: pass
evidence: "pnpm config list shows minimumReleaseAge=1440, minimumReleaseAgeStrict=true, blockExoticSubdeps=true, verifyStoreIntegrity=true, strictDepBuilds=true; userAgent pnpm/11.6.0"

### 7. Scan is credential-free + offline
expected: During `harnessed build`, the scan step uses no API keys/tokens/network — the DB is the pre-seeded offline cache (XDG_CACHE_HOME=/opt/osv-cache). The log shows offline mode ("--offline --offline-vulnerabilities"); the scan works with egress firewalled. Nothing mounts a daemon socket or drives podman from inside the image.
section: technical
result: pass
evidence: "scan.py:169/241 use --offline --offline-vulnerabilities; Dockerfile:37 XDG_CACHE_HOME + build-time DB seed; common.sh:128-133 image scan via podman save tar (ro), no socket mount"

### 8. Outcome coverage (goal-backward)
expected: User-story outcome holds: "no dependency with a high-severity vulnerability is committed or baked into an image." Evidence: a HIGH-vuln dep was blocked before bake (test 3), the gate is severity-correct (test 4), and the built hatago image scans clean. No code path bakes an image before the scan passes.
section: coverage
result: pass
evidence: "HIGH blocked pre-bake (test 3) + sub-HIGH green (test 4) + build_stack gates print_success on both scans passing (common.sh:106-137) — no bypass path"

## Summary

total: 8
passed: 8
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

[none]
