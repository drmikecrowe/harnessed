---
phase: 02-isolated-tracer-bullet-stack
plan: 03
subsystem: testing
tags: [capability-test, rich, hatago, mcp, introspection, ci, markdown-report]

# Dependency graph
requires:
  - phase: 02-01
    provides: schema.load_stack_with_recipes + schema.expected_capabilities (the manifest oracle), Capabilities/McpServer/Recipe/Stack, cli.py assemble subparser
  - phase: 02-02
    provides: lib/harnessed-isolated.sh headless launcher (HARNESSED_HEADLESS=true, harnessed <stack> --fresh), pod naming harnessed-<stack>-<projhash>, hatago member + endpoint, --fresh teardown
provides:
  - tools/harnessed/capability.py — per-stack capability test (manifest oracle → launch --fresh headless → live introspection → structured CapabilityReport)
  - tools/harnessed/report.py — rich markdown capability table; same structured result drives the process exit code; --json for CI
  - harnessed test <stack> — capability-test entrypoint (ensure-built → headless launch → report → propagated exit)
affects: [phase-03, phase-04, future recipes/stacks gated by their own red→green capability test]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Manifest is the test oracle: expected capabilities derived from schema.expected_capabilities, never hardcoded"
    - "One structured result (CapabilityReport) drives BOTH the rich report and the CI exit code (design §18 / D-11)"
    - "Machine-readable introspection first (hatago://servers → claude mcp list → filesystem skills), LLM prompt as backstop (D-10)"
    - "Pure manifest→expected + expected-vs-live diff are unit-testable; podman-touching launch/introspect/teardown guarded behind the launch"

key-files:
  created:
    - tools/harnessed/capability.py
    - tools/harnessed/report.py
  modified:
    - tools/harnessed/cli.py
    - harnessed

key-decisions:
  - "Capability test runs host-native python (drives host podman: launch --fresh headless + podman exec introspection + teardown) — NOT the emit-only tools image (no daemon-in-container)"
  - "Instance name parsed from the launcher's 'Isolated pod running headless: <instance>' line rather than re-deriving the projhash in Python"
  - "Teardown via `podman pod rm -f <instance>` (removes harness + hatago members); --fresh on next run also guarantees no state bleed (T-02-08)"

patterns-established:
  - "Capability kinds are stable strings (mcp|skill|command) shared by capability.py + report.py + --json consumers"
  - "Report status cells are names+status only (✓ connected / ✓ present / ✗ missing (<reason>)) — no config values/tokens (T-02-07)"

requirements-completed: [TST-01, TST-02]

# Metrics
duration: ~35min
completed: 2026-06-15
---

# Phase 02-03: Per-stack capability test + rich markdown report Summary

**Per-stack capability test that derives expected capabilities from the manifest oracle, launches the stack --fresh headless, introspects the live pod (hatago://servers / claude mcp list / mounted-profile skills), and renders one structured result as both a rich markdown table and the CI exit code.**

## Performance

- **Duration:** ~35 min
- **Tasks:** 3 (all `type="auto"`)
- **Files modified:** 4 (2 created, 2 edited)

## Accomplishments
- `tools/harnessed/capability.py` — manifest oracle (`schema.expected_capabilities`) vs live `--fresh` headless introspection → structured `CapabilityReport`; machine-readable sources first (hatago `hatago://servers` resource over Streamable HTTP, then `claude mcp list`, then `claude -p --output-format json` backstop for MCP; mounted profile filesystem then headless JSON for skills/commands), with launch + teardown via the 02-02 launcher.
- `tools/harnessed/report.py` — `rich` markdown `capability | kind | status` table; the SAME structured result drives the process exit code (0 all-green, non-zero any missing); `--json` emits the structured result for CI; no config/token values in output.
- `harnessed test <stack>` + `cli.py test <stack> [--json]` — ensure-built → headless capability test → rich report → propagated exit code (`set -euo pipefail` preserved; the test's non-zero status is captured and re-exited, not swallowed).

## Task Commits

Each task was committed atomically:

1. **Task 1: capability test — manifest oracle vs live introspection** - `6a3cbc5` (feat)
2. **Task 2: rich markdown capability report + CI exit code** - `c815c96` (feat)
3. **Task 3: harnessed test subcommand + cli wiring** - `6f0455f` (feat)

**Plan metadata:** this SUMMARY (docs)

## Files Created/Modified
- `tools/harnessed/capability.py` (created) - per-stack capability test: pure oracle (`expected_capabilities`) + pure diff (`build_report`) + podman-touching `launch_headless`/`introspect`/`teardown`/`run_capability_test`.
- `tools/harnessed/report.py` (created) - markdown rendering (`render_markdown`/`print_report`), `report_json`, and `emit` (returns `report.exit_code`).
- `tools/harnessed/cli.py` (modified) - added `test <stack> [--root --project --harnessed-bin --keep --json]` subparser, `_run_test`, and the `test` dispatch in `main`.
- `harnessed` (modified) - added `test` arg parsing (consumes rest of argv verbatim), the capability-test handler (ensure-built via `build_stack`/`ensure_images` → host python `-m harnessed.cli test` → propagated exit), and the `usage()` line.

## Decisions Made
- The capability test is host-native python (it drives host podman); `harnessed test` runs `python3 -m harnessed.cli test` on the host with `PYTHONPATH=$HARNESSED_DIR/tools` (overridable via `HARNESSED_PYTHON`). This keeps the no-DooD invariant: the emit-only tools image never drives the daemon.
- Instance name is parsed from the launcher's headless success line (`Isolated pod running headless: <instance>`) — avoids duplicating the bash `generate_instance_name` projhash logic in Python.
- hatago `hatago://servers` is the primary MCP source because the harness `.mcp.json` only knows the `hatago` hub; the manifest's child server (`time`) is only visible behind the hub. `claude mcp list` and the LLM prompt are secondary/backstop.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- An `edit` op briefly duplicated a `help=` line in `cli.py` (argparse `--root`); caught immediately and removed before any commit. No functional impact.

## User Setup Required
None - no external service configuration required. (Operator verification below needs an existing rootless-podman + Claude-auth host plus a host `python3` with `ruamel.yaml` + `rich`.)

## Self-Check: PASSED

Plan-level `<verification>` (run statically — no live instance launched, per the blocking human-verify gate):
- [x] `PYTHONPATH=tools python -c "import harnessed.capability, harnessed.report"` imports; `bash -n harnessed` parses → both PASS.
- [x] expected capabilities derived from the manifest (reuses `schema.expected_capabilities`, not hardcoded) → `mcp=['time'] skills=['time-helper']` for tracer-time.
- [x] MCP asserted via `hatago://servers` / `claude mcp list`; skills via mounted-profile filesystem (`~/.claude/skills`) with headless-JSON backstop → all present in source.
- [x] markdown `capability | kind | status` report renders via rich; the SAME structured result drives the exit code (missing sample → `✗` + exit 1; all-present sample → `✓` + exit 0); `--json` emits the structured result with NO token/config values.
- [x] `harnessed test <stack>` dispatches, runs the test, propagates the exit code (error paths `harnessed test` / `harnessed test bogus-stack` both exit 1 without invoking podman); `cli.py` exposes `test <stack>`.
- [ ] `harnessed test tracer-time` passes green on a podman host → **operator checkpoint (PENDING — see below).**
- [x] key-files exist on disk; `git log --oneline --grep=02-03` returns the 3 task commits (`6a3cbc5`, `c815c96`, `6f0455f`).

No podman/docker, `harnessed build`, or `harnessed test <valid-stack>` was executed by the agent (the static checks exercised imports, the manifest-oracle dry-run, the report+exit-code logic on sample results, and the dispatch error paths only).

## Operator Verification (PENDING)

This is the Phase-2 success-criteria gate (`checkpoint:human-verify`, gate="blocking"). It REQUIRES a host with rootless podman + real Claude credentials (and a host `python3` with `ruamel.yaml` + `rich`) — the agent cannot run it.

**Exact command:**
```
./harnessed test tracer-time
```

**Confirm:**
1. It builds the stack if needed (assembles `profiles/tracer-time/` + the `harnessed-hatago` image), then launches the stack `--fresh` HEADLESS and renders the markdown capability table.
2. The `time` MCP server shows `✓ connected` and the `time-helper` skill shows `✓ present`.
3. The command exits `0`.
4. (Negative) Rename the recipe's skill (e.g. `recipes/time/skills/time-helper` → a different leaf) and re-run: the report marks the missing capability `✗` and the command exits non-zero. Restore the skill afterward.

Resume signal: type "approved" once the capability test passes green (time connected, time-helper present) and the report renders, or describe the failure.

## Next Phase Readiness
- The tracer-bullet slice is code-complete end to end (assemble → run → assert); the only outstanding item is the operator's live green run (above).
- Phase 3 (supply-chain scan + pnpm managed config + plugin-vendoring-with-deps) and later recipes plug into the same `harnessed test <stack>` gate — each new recipe gets its own red→green capability test, no test code changes needed.

---
*Phase: 02-isolated-tracer-bullet-stack*
*Completed: 2026-06-15*
