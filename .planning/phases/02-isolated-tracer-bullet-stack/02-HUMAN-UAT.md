---
status: complete
phase: 02-isolated-tracer-bullet-stack
source: [02-01-SUMMARY.md, 02-02-SUMMARY.md, 02-03-SUMMARY.md]
started: 2026-06-15T10:40:00Z
updated: 2026-06-15T11:20:00Z
---

## Current Test

[testing complete]

All three gates passed green on a host with rootless podman + real Claude credentials, after
fixing three real bugs found during verification (pnpm global-bin PATH; rootless pod
networking/userns + profile pollution; capability-test readiness/mount/deps). Commits
`4c9b665`, `1c2efea`, `94793f5`.

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
result: pass
note: |
  Initial failures: `netavark: create bridge: Operation not supported` (rootless can't create the
  custom bridge) then `cannot set user namespace mode when joining pod with infra container`.
  Fixed in lib/harnessed-isolated.sh (1c2efea): default pod network (HARNESSED_NET opt-in),
  pod-level --userns=keep-id stripped from member args, copy-on-start profile. Re-run: headless
  `claude -p` → {"subtype":"success","is_error":false,"result":"READY"} — NO onboarding/login
  prompt; `time` MCP connected via hatago. Candidate stub field set CONFIRMED sufficient
  (hasCompletedOnboarding, firstStartTime, numStartups, oauthAccount, userID).
  FOLLOW-UP (operator interactive use, fixed in 57b13b9): in the interactive `--fresh` session the
  `time` MCP was NOT loaded and `claude mcp list` showed the user's claude.ai account-synced
  servers (isolation leak). Root cause: claude doesn't read `~/.claude/.mcp.json`, and the entry
  lacked `type: http`. Fix: emit `type: http`; launch claude with `--mcp-config <profile .mcp.json>
  --strict-mcp-config` (loads ONLY hatago, ignores account/project/user MCP). Validated: claude in
  the instance CALLS `mcp__hatago__time_get_current_time` → returns the time, is_error=false.

### 3. Assert-green leg — `harnessed test tracer-time` (02-03 gate, Phase 2 success criteria)
expected: |
  Builds if needed, launches the stack --fresh headless, and renders a rich markdown
  capability table. Confirm:
    - `time` MCP server shows `✓ connected`; `time-helper` skill shows `✓ present`.
    - The command exits 0.
    - (Negative check) Renaming the recipe's skill forces a mismatch: the report marks it `✗`
      and the command exits non-zero.
  Run: `./harnessed test tracer-time`
result: pass
note: |
  Initial false-RED (both capabilities missing). Root causes fixed in capability.py + harnessed
  (94793f5): (a) introspected before hatago bound its ~4s child connect → added wait_ready;
  (b) the scratch project mount was deleted right after launch, breaking `podman exec` (crun
  getcwd EPERM) → project dir now persists for the pod lifetime; (c) host deps resolved via uv.
  Re-run: time ✓ connected, time-helper ✓ present, exit 0; negative (skill hidden) → ✗ + exit 1;
  --json clean.

## Summary

total: 3
passed: 3
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

<!-- Populated by /gsd-verify-work if the operator reports an issue. -->
