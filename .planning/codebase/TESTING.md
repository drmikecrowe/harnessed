# Testing Patterns

**Analysis Date:** 2026-06-24

## Test Framework

**Runner:**
- Custom pure-Bash UAT harness — no external test framework (`tools/uat/uat-common.sh`)
- No bats, no pytest, no Jest — dependency-free by design (matches the project's "podman is the only host dependency" ethos)

**Assertion Library:**
- Pure bash built-ins: `[[ =~ ]]` for regex, `[[ == *..* ]]` for substring, `[ -e ]` / `[ -x ]` for filesystem checks
- All assertions defined in `tools/uat/uat-common.sh`

**Run Commands:**
```bash
./tools/uat/run-uat.sh <phase>           # Run a full phase UAT suite (e.g., 4 or 04)
./tools/uat/run-uat.sh <phase> --quick   # Skip heavy container-launch tests
./tools/uat/run-uat.sh <phase> <test_id> # Run a single named test
```

## Test File Organization

**Location:**
- All UAT suites live in `tools/uat/`
- One suite file per feature phase: `tools/uat/phase-<NN>.sh`

**Naming:**
- Phase suites: `phase-<NN>.sh` (zero-padded phase number)
- Shared harness: `uat-common.sh`
- Driver: `run-uat.sh`

**Structure:**
```
tools/uat/
├── uat-common.sh          # Shared AAA markers, assertion helpers, driver
├── run-uat.sh             # Phase-selection driver (sources uat-common.sh + suite)
├── phase-04.sh            # Phase 4 suite: shared services + full CLI
├── phase-05.sh            # Phase 5 suite: secrets + hardening
├── phase-06.sh            # Phase 6 suite
├── phase-08.sh            # Phase 8 suite
└── phase-09.sh            # Phase 9 suite
```

## Test Structure

**Suite Organization:**

Each phase suite defines `test_<id>()` functions and a `uat_run_phase` entrypoint.
Every test follows the AAA (Arrange → Act → Assert) pattern:

```bash
test_svc_up() {
    arrange
    "$HARNESSED" svc down ping --purge >/dev/null 2>&1 || true   # tolerate absence
    act
    uat_run "$HARNESSED" svc up ping
    assert
    assert_exit_zero "$UAT_RC" "svc up ping exits 0"
    assert_contains "is up" "$UAT_OUT" "reports the service is up"
}
run_test svc_up "svc up publishes port and lists"
```

**Patterns:**
- `arrange` / `act` / `assert` are purely visual markers (they echo section names; no control flow)
- `uat_run` captures both stdout+stderr into `UAT_OUT` and exit code into `UAT_RC`
- Assertions never abort — they accumulate pass/fail counts; `uat_summary` returns non-zero if any failed
- Cleanup in Arrange uses `|| true` to tolerate absent state (idempotent setup)
- Container-heavy tests self-skip via a `needs_container` guard:
  ```bash
  needs_container() { [ "$UAT_QUICK" = "true" ]; }
  test_foo() {
      needs_container && { skip_test "skipped (--quick)"; return; }
      ...
  }
  ```

## Assertion Library

All assertions are defined in `tools/uat/uat-common.sh`. Arguments are positional — label is always last:

```bash
assert_exit_zero    "$UAT_RC"      "label"
assert_exit_nonzero "$UAT_RC"      "label"
assert_eq           "$actual"   "$expected"  "label"
assert_ne           "$actual"   "$unexpected" "label"
assert_match        "regex"     "$actual"    "label"
assert_not_match    "regex"     "$actual"    "label"
assert_contains     "substring" "$actual"    "label"
assert_not_contains "substring" "$actual"    "label"
assert_exists       "/path"      "label"
assert_not_exists   "/path"      "label"
assert_file_contains "/path" "substring" "label"
assert_executable   "/path"      "label"
assert_true         cmd [args...]  "label"   # pass if cmd exits 0
assert_false        cmd [args...]  "label"   # pass if cmd exits non-zero
```

## Mocking

**Framework:** None — no mock library. Tests exercise the REAL `harnessed` CLI binary against the real container runtime.

**Patterns:**
- **Env-var injection** to force inert/alternate paths without touching real credentials:
  ```bash
  uat_run_env "HARNESSED_SCHEMA=/nonexistent/path/.env.schema" "$HARNESSED" build tracer-time
  uat_run_env "SNYK_TOKEN=dummy-uat-token" "$HARNESSED" build tracer-time
  ```
- **Pre-flight cleanup** to establish a known state before acting:
  ```bash
  "$HARNESSED" svc down ping --purge >/dev/null 2>&1 || true
  ```
- **Container self-skip** under `--quick` to skip tests that need a live pod

**What NOT to Mock:**
- The `harnessed` launcher itself — tests drive it as a black box
- The container runtime — container-launch tests use the real podman/docker

## Test Types

**UAT / Integration Tests (primary):**
- Scope: Behavior asserted through the running CLI against the stack manifest as oracle (design §18)
- Drives the real `harnessed` binary
- Asserts CLI exit codes, stdout/stderr content, container/pod/volume state
- The stack manifest (`stack.yaml` + `recipe.yaml`) is the oracle — never hardcoded expectations
- Live container tests require a running podman/docker daemon

**Capability Tests (automated integration, via `harnessed test <stack>`):**
- Scope: Per-stack — launches a `--fresh` headless instance, introspects the live pod, diffs actual vs declared capabilities
- Oracle: `schema.py`'s `expected_capabilities(stack, recipes)` derives expected MCP servers/skills/commands from the manifest
- Python entry: `tools/harnessed/capability.py` → `run_capability_test()`
- Report: rendered by `tools/harnessed/report.py` (rich table or JSON for CI via `--json`)
- CI exit code: non-zero when any declared capability is missing
- Pure functions (`build_report`, `expected_capabilities`) are unit-testable without podman

**UAT Quick Mode:**
- `--quick` flag skips all tests that require a container launch
- Fast (non-container) tests still run: CLI argument parsing, flag validation, schema error paths
- Heavy tests document their skip reason: `skip_test "skipped (--quick) — runs the tools container"`

**Manual-Only Tests:**
- Documented per-phase in `<NN>-HUMAN-UAT.md` files
- Cover: live `op://` secret resolution, 1Password desktop-app auth, overnight nightly timer, browser OAuth flows
- Not scriptable — require interactive input or overnight state

## Fixtures and Factories

**Test Data:**
- Real authored stacks (`stacks/tracer-time/stack.yaml`, `stacks/ping-time/stack.yaml`) double as test fixtures
- No synthetic fixture files — tests reuse the actual repo manifests
- Env override pattern for nonexistent paths:
  ```bash
  UAT_NO_SCHEMA="/nonexistent/harnessed-uat-$$/.env.schema"
  ```

**State isolation:**
- Container-launch tests tear down via `--purge` in Arrange and cleanup in teardown
- `--fresh` flag on instance launches ensures no state bleed between test runs (threat T-02-08)
- `uat_pod_rm` helper force-removes pods by name in cleanup

## Coverage

**Requirements:** No numeric coverage target enforced. Integration coverage is behavior-driven against the manifest oracle.

**Explicit gap tracking:**
- Known gaps are annotated in suite files as inline comments:
  ```bash
  # Two tests encode KNOWN GAPS as red regression checks (go green when the fix lands):
  #   - no_args_help     (UAT gap 6B): bare `harnessed` should show usage
  #   - legible_slug     (UAT gap 6) : state-dir slug should be a legible path
  ```
- Manual-only legs tracked in `<NN>-HUMAN-UAT.md` per phase

**View test output:**
```bash
./tools/uat/run-uat.sh 4              # Full suite with summary
./tools/uat/run-uat.sh 4 --quick      # Fast-only pass
./tools/uat/run-uat.sh 4 svc_up       # Single test by id
```

## Test Output Format

`uat-common.sh` produces structured terminal output:

```
╔══════════════════════════════════════════════════════════════╗
║  UAT SUITE: <title>
╚══════════════════════════════════════════════════════════════╝

━━━ TEST 1: svc up publishes port and lists  (svc_up) ━━━
  ▸ Arrange
  ▸ Act
    ▸ harnessed svc up ping
  ▸ Assert
    ✓ svc up ping exits 0
    ✓ reports the service is up
  → PASS

════════════════════════════════════════════════════════════════
  TESTS:  3 passed, 0 failed, 1 skipped (4 total)
  CHECKS: 8 passed, 0 failed
════════════════════════════════════════════════════════════════
```

Pass/fail counts are cumulative across all assertions within the suite. Exit code from `uat_summary` is non-zero if any test failed.

## Python Unit-Testable Surface

The following Python functions are pure (no subprocess, no podman) and are explicitly designed for unit testing:

- `tools/harnessed/schema.py`: `load_recipe`, `load_stack`, `validate_no_raw_npm`, `validate_pin`, `validate_harness_compat`, `expected_capabilities`
- `tools/harnessed/scan.py`: `_cvss3_base`, `_roundup`, `_severity_score` (CVSS parsing, no subprocess)
- `tools/harnessed/capability.py`: `build_report`, `expected_capabilities` (diff logic, no podman)

No Python unit test files (`*.test.py` / `*.spec.py` / `test_*.py`) are present. Testing relies exclusively on the UAT harness driving the assembled CLI.

---

*Testing analysis: 2026-06-24*
