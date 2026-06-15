---
status: partial
phase: 02-isolated-tracer-bullet-stack
source: [02-01-SUMMARY.md, 02-02-SUMMARY.md, 02-03-SUMMARY.md]
started: 2026-06-15T10:40:00Z
updated: 2026-06-15T11:10:00Z
---

## Current Test

[testing paused — 2 items outstanding]

Test 1 (build leg) PASSED after a fix (pnpm global bin dir `$PNPM_HOME/bin` was missing from
PATH in `base/Dockerfile.hatago`). Tests 2 & 3 require **host rootless podman + real Claude OAuth
credentials**, which only the operator can run. Run them on a machine with `claude login` done.

## Tests

### 1. Build leg — `harnessed build tracer-time` (02-01 gate)
expected: |
  Builds the `harnessed-tools` (emit-only) and `harnessed-hatago` images, then emits the
  committed profile. Confirm:
    - `harnessed-tools` and `harnessed-hatago` images build successfully.
    - `profiles/tracer-time/.claude/skills/time-helper/SKILL.md` and
      `profiles/tracer-time/hatago.config.json` exist.
    - `hatago.config.json` lists the `time` server as a stdio child.
  Run: `./harnessed build tracer-time`
result: pass
note: |
  Operator hit "pnpm add -g … exit status 1". Root cause: pnpm 11's global bin dir is
  $PNPM_HOME/bin, but the Dockerfile put $PNPM_HOME on PATH → "global bin directory … is not in
  PATH". Fixed in base/Dockerfile.hatago. Re-validated with real podman: containerized
  `harnessed-tools assemble` (idempotent, committed profile byte-unchanged) + host
  `podman build -f base/Dockerfile.hatago` both exit 0; hatago 0.0.16 + mcp-server-time baked
  and resolvable; `hatago serve` supports --http/-p/--port/-c/--config.

### 2. Run leg — `harnessed tracer-time --fresh` headless no-prompt boot (02-02 gate, RESEARCH Pitfall A)
expected: |
  Launches an isolated podman pod (harness + hatago on harnessed-net) that boots claude with
  NO onboarding/login/theme prompt and the project mounted. Confirm:
    - `./harnessed tracer-time --fresh` drops into claude with ZERO prompts.
    - Headless probe returns JSON (not an onboarding prompt):
      `podman exec harnessed-tracer-time-<projhash> bash -lc 'claude -p "list your connected MCP servers" --output-format json'`
    - `claude mcp list` (or hatago `hatago://servers`) shows the `time` server connected.
    - If the working `.claude.json` stub differs from the candidate set
      (hasCompletedOnboarding, firstStartTime, numStartups, oauthAccount, userID), note the
      exact fields so the snapshot fixture can be pinned.
result: [pending]

### 3. Assert-green leg — `harnessed test tracer-time` (02-03 gate, Phase 2 success criteria)
expected: |
  Builds if needed, launches the stack --fresh headless, and renders a rich markdown
  capability table. Confirm:
    - `time` MCP server shows `✓ connected`; `time-helper` skill shows `✓ present`.
    - The command exits 0.
    - (Negative check) Renaming the recipe's skill forces a mismatch: the report marks it `✗`
      and the command exits non-zero.
  Run: `./harnessed test tracer-time`
result: [pending]

## Summary

total: 3
passed: 1
issues: 0
pending: 2
skipped: 0
blocked: 0

## Gaps

<!-- Populated by /gsd-verify-work if the operator reports an issue. -->
