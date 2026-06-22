# Testing

> How `harnessed` is tested, as of 2026-06-22. Grounded in the actual test
> sources (`tools/uat/`, `tools/test-fixtures/`, `tools/harnessed/capability.py`)
> and the design contract.

`harnessed` tests **integration-only, by explicit policy.** There is no unit-test
framework in the repo: no `pytest`, no `test_*.py`, no `conftest.py`, no `bats`,
no `Makefile`/`justfile`. `CLAUDE.md` §18 states the rule, and the planning docs
repeat it verbatim — *"assembler unit tests are out of scope per
REQUIREMENTS.md"*; *"integration-only, behavior asserted through the running
instance against the stack manifest as oracle."*

Two mechanisms carry the load:

1. **`harnessed test <stack>`** — a Python **capability test** that launches a
   stack `--fresh headless` and asserts the live pod exposes exactly what the
   manifest declares (design §18).
2. **UAT suites** (`tools/uat/phase-*.sh`) — dependency-free bash, driving the
   real `harnessed` CLI through Arrange→Act→Assert.

Both run **locally on the operator's host** (they need rootless podman + built
images). Neither is wired into CI today.

---

## 1. The capability test — `harnessed test <stack>`

This is the primary correctness gate. It lives in
`tools/harnessed/capability.py` (+ `report.py`, + the `test` subcommand in
`cli.py`) and is invoked by the bash launcher.

### 1.1 The flow (design §18 / D-10, D-11)

```
manifest oracle ──▶ launch pod --fresh headless ──▶ wait hatago port
   (expected)              (02-02 launcher)              (readiness)
        │                                                        │
        └───────────────────── diff ◀──────────── introspect ◀──┘
                                  │                   (live)
                          CapabilityReport ──▶ markdown table (rich)
                                  │           └─▶ --json (CI)
                                  └─▶ exit code (0 green / 1 any missing)
```

The single structured `CapabilityReport` drives **both** the human report and the
process exit code — one mechanism, two audiences (`tools/harnessed/report.py`
docstring).

### 1.2 The oracle — pure, no podman

`expected_capabilities(root, stack_name)` (`capability.py`) reuses
`schema.expected_capabilities(stack, recipes)` to derive the *expected* MCP
servers / skills / commands purely from the manifests. This is the test contract:
if the live instance doesn't match the manifest, the test is red. The pure
functions are explicitly marked *"unit-testable"* — but no unit tests are
shipped for them; they are exercised transitively through the live run.

### 1.3 Live introspection — primary + backstop

`introspect(instance, harness)` gathers what the running pod actually exposes,
with a deliberate **primary → backstop** ordering so the result never depends on
an LLM unless necessary:

| Capability | Primary source | Backstop |
|-----------|----------------|----------|
| MCP servers | hatago `hatago://servers` resource over Streamable HTTP (`_mcp_from_hatago`) | ask the harness headless (`claude -p … --output-format json` / `omp -p --mode json`, harness-aware via `_llm_cmd`) |
| Skills / commands | mounted-profile filesystem listing (`_fileext_from_filesystem`) | headless JSON array from the harness (`_skills_from_llm`) |

The primary checks are **harness-independent** (hatago resource + filesystem);
only the LLM backstop command branches on `stack.harness` (plan 04-03 / HRN-01).
`build_report()` diffs expected vs live into a `CapabilityReport` of
`CapabilityResult`s.

### 1.4 Lifecycle — `--fresh`, headless, teardown

`run_capability_test(root, stack_name, *, project_path=None, keep=False)` owns
the full lifecycle:

```python
expected = expected_capabilities(root, stack_name)
harness = _harness_of(root, stack_name)
own_project = project_path is None
if own_project:
    project_path = tempfile.mkdtemp(prefix=f"harnessed-test-{stack_name}-")
try:
    instance = launch_headless(root, stack_name, project_path=project_path, ...)
    try:
        wait_ready(instance)
        live = introspect(instance, harness)
    finally:
        if not keep:
            teardown(instance, ...)
finally:
    if own_project and not keep:
        shutil.rmtree(project_path, ignore_errors=True)
return build_report(stack_name, expected, live)
```

Key invariants (read them from the code's own docstrings):

- **`--fresh`** — the pod is torn down and recreated, so no state bleeds between
  runs (T-02-08).
- **Headless** — `HARNESSED_HEADLESS=true` makes the launcher compose + start the
  pod *without* the interactive attach; members stay up (`sleep infinity`) for
  `podman exec` introspection.
- **Readiness wait** — `wait_ready()` polls a TCP connect to `127.0.0.1:$HATAGO_PORT`
  from inside the pod until hatago boots and binds; introspecting too early yields
  false negatives.
- **Scratch project lifetime** — the temp project dir is the pod's bind-mount and
  MUST outlive launch→introspect→teardown (deleting it mid-run breaks
  `podman exec` with a crun `getcwd EPERM`). `run_capability_test` manages cleanup
  in `finally`; `--keep` skips teardown for debugging.
- **Fail-fast** — launch/introspection failures raise `CapabilityError`, which
  `cli._run_test` renders as a clean exit-non-zero.

### 1.5 Output — markdown for humans, JSON for CI

- Default: a `rich`-rendered markdown table (`| capability | kind | status |`)
  via `report.print_report`.
- `--json`: `report.report_json` prints the structured `CapabilityReport.to_dict`
  (capability **names + status only — never config values or tokens**, threat
  T-02-07) as clean stdout for CI consumption.
- The exit code is `report.exit_code` (0 all-green, 1 any missing) — propagated
  by the launcher.

### 1.6 How `harnessed test` resolves its Python deps on the host

The capability test runs **host-native Python** (it drives host podman), not the
emit-only tools image. The launcher resolves `ruamel.yaml` + `rich` in a
three-step fallback (`harnessed:358-377`), keeping the host dependency surface at
"podman only":

1. `HARNESSED_PYTHON` — an interpreter the operator guarantees has the deps.
2. `uv run --no-project --with ruamel.yaml --with rich` (ephemeral; no host-python pollution) — **preferred**.
3. A host `python3` that already imports both.

If none is available, it prints a clear install hint and exits 1.

---

## 2. The UAT suites — `tools/uat/`

The UAT layer is **pure bash with zero test dependencies** — by design. The
common harness (`tools/uat/uat-common.sh`) says it plainly: *"No external deps
(no bats, no grep) — matches the project's dependency-free ethos; pattern
matching uses bash's `[[ =~ ]]` / `[[ == *..* ]]"*.

### 2.1 Running a suite

```bash
./tools/uat/run-uat.sh <phase>              # full phase suite
./tools/uat/run-uat.sh <phase> --quick      # fast tests only (skip container launches)
./tools/uat/run-uat.sh 4 svc_up             # one test by id
```

`run-uat.sh` normalizes the phase id (`4` / `04` / `phase-04` → `04`), sources
`uat-common.sh` then `phase-<NN>.sh`, and calls `uat_run_phase` (or a single
`run_test`). It exports `HARNESSED_DIR` + `HARNESSED` (the real launcher path) so
suites invoke the actual CLI.

Three suites exist today:

| Suite | Phase | Focus |
|-------|-------|-------|
| `tools/uat/phase-04.sh` | Shared services + recipe breadth + full CLI | `svc up/down/list`, recipe breadth, omp bridge, `list`/`new`/`install`, state persistence, `--fresh` wipe, legible slug |
| `tools/uat/phase-05.sh` | Secrets, hardening + docs | SEC-01 inertness, SEC-02 warn-and-skip, SEC-03 `auth` dispatch, SEC-04 rescan + timer units, DOC completeness |
| `tools/uat/phase-06.sh` | Harness matrix | one `<harness>-time` proof stack per harness; the cross-runtime regression gate |

### 2.2 Test structure — Arrange → Act → Assert (AAA)

Every test is a `test_<id>` function and follows the AAA discipline with explicit
(but purely visual) section markers from `uat-common.sh`:

```bash
test_svc_up() {
    arrange
    "$HARNESSED" svc down ping --purge >/dev/null 2>&1 || true
    act
    uat_run "$HARNESSED" svc up ping
    assert
    assert_exit_zero "$UAT_RC" "svc up ping exits 0"
    assert_contains "is up" "$UAT_OUT" "reports the service is up"
    assert_match '0\.0\.0\.0:8080' "$("$RT" ps --filter 'name=ping' --format '{{.Ports}}' 2>/dev/null)" "publishes its port to 0.0.0.0"
    uat_run "$HARNESSED" svc list
    assert_contains "ping" "$UAT_OUT" "svc list shows the ping service"
    "$HARNESSED" svc down ping --purge >/dev/null 2>&1 || true
}
```

- **`arrange` / `act` / `assert`** print a section marker (AAA is the discipline,
  not machinery).
- **`uat_run <cmd…>`** runs the command, echoing it, and captures stdout+stderr
  into `UAT_OUT` and the exit into `UAT_RC`. **`uat_run_env "ENV=val" <cmd…>`** is
  the variant for setting env (e.g. `HARNESSED_HEADLESS=true`,
  `HARNESSED_SCHEMA=/nonexistent/…`).
- **Arrange cleanup** (the trailing `svc down --purge || true`) is part of every
  stateful test — tests leave the world as they found it.

### 2.3 Assertions — pure bash, never abort

`uat-common.sh:46-82` defines the assertion set. They **record pass/fail and
continue** — they never abort the suite (that is why `run-uat.sh` uses
`set -uo pipefail`, not `set -e`):

| Helper | Meaning |
|--------|---------|
| `assert_exit_zero RC LABEL` / `assert_exit_nonzero RC LABEL` | exit-code check |
| `assert_eq A E LABEL` / `assert_ne A U LABEL` | (in)equality |
| `assert_match REGEX ACTUAL LABEL` / `assert_not_match` | `[[ =~ ]]` regex |
| `assert_contains SUB ACTUAL LABEL` / `assert_not_contains` | `[[ == *"*"* ]]` substring |
| `assert_exists PATH LABEL` / `assert_not_exists` | file existence |
| `assert_file_contains PATH SUB LABEL` | file content substring |
| `assert_executable PATH LABEL` | `-x` |
| `assert_true CMD… LABEL` / `assert_false CMD… LABEL` | last arg is label; preceding args are the command (exit 0 / non-zero) |

Each pass prints `    ✓ <label>`; each fail prints `    ✗ <label> :: <detail>`
and sets the per-test fail flag. `skip_test "<reason>"` marks the current test
skipped (call it, then `return`).

### 2.4 Heavy vs fast tests — `--quick` and `needs_container`

Container-launching tests are expensive. Each heavy test self-skips under
`--quick` via the one-liner convention:

```bash
needs_container() { [ "$UAT_QUICK" = "true" ]; }   # true ⇒ this test should skip

test_omp_bridge() {
    needs_container && { skip_test "skipped (--quick)"; return; }
    ...
}
```

Fast tests (manifest validation, CLI arg parsing, dispatch) **always run**, so a
`--quick` pass still covers the cheap surface. The matrix suite's
`test_matrix_manifests` is the canonical example: it validates the whole
harness matrix without a container.

### 2.5 Known-gap regression checks

The suites encode **known bugs as red tests that go green when fixed** — a
discipline called out in each suite header. `phase-04.sh`:

```bash
test_no_args_help() {
    # Desired (gap 6B): bare invocation shows usage and exits 0. Today it launches
    # transparent (interactive) — bounded by `timeout` so it cannot hang the suite.
    UAT_OUT=$(timeout 12 "$HARNESSED" 2>&1); UAT_RC=$?
    assert_exit_zero "$UAT_RC" "bare harnessed exits 0"
    assert_contains "Usage" "$UAT_OUT" "shows usage/help (not a silent transparent launch)"
}
```

`test_legible_slug` (gap 6) is the other example. When adding a test for a known
defect, mark it this way and bound any interactive risk with `timeout`.

### 2.6 Summary

`uat_summary` (called once at the end of `run-uat.sh`) prints the cumulative
pass/fail/skip tallies and the failed/skipped test ids, and returns non-zero if
any test failed.

---

## 3. Test fixtures — `tools/test-fixtures/`

Fixtures are **real manifests in the resolver layout**, not mocks. They exist to
exercise the supply-chain scan/lint gates (BLD-02/BLD-03) and the service-URL
resolution (SVC-01) **without polluting the real `stacks/`/`recipes/`**.

```
tools/test-fixtures/
  recipes/   npm-recipe/  vuln-recipe/  low-recipe/  svc-recipe/
  stacks/    npm-stack/   vuln-stack/   low-stack/   svc-stack/
  services/                                                  svc-test/
  profiles/                                                   (gitignored — emitted output)
```

| Fixture | Recipe | Asserts |
|---------|--------|---------|
| `npm-stack` | `npm-recipe` (`command: npx`) | the assembler's `validate_no_raw_npm()` **aborts before emit**, naming `pnpm dlx` (BLD-03) |
| `vuln-stack` | `vuln-recipe` (`requests==2.19.0`, CVE-2018-18074, CVSS 7.5) | the source scan **aborts** on a HIGH+ finding (BLD-02) |
| `low-stack` | `low-recipe` (`mistune==0.7.4`, max CVSS 6.1 < 7.0) | sub-HIGH findings render as **warnings, build green** — proves the gate is severity-driven, not exit-1-on-any-finding |
| `svc-stack` | `svc-recipe` (`service: svc-test`) | the assembler resolves a `service:`-referenced server to a hatago URL-proxy entry and excludes it from `baked-servers.json` (SVC-01) |

### 3.1 The `--root` override — how fixtures are exercised

Fixtures are resolved by passing an alternate stacks/+recipes/ root to the
launcher and assembler:

```bash
./harnessed build vuln-stack --root tools/test-fixtures     # → exit 1, GHSA-x84v-xcm2-53pg
./harnessed build low-stack  --root tools/test-fixtures     # → exit 0, warnings only
./harnessed build npm-stack  --root tools/test-fixtures     # → exit 1, "Use the pnpm equivalent 'pnpm dlx'"
```

`build_stack` reads `ROOT=${HARNESSED_ROOT:-$HARNESSED_DIR}`; the launcher's
`--root <dir>` exports `HARNESSED_ROOT` (`harnessed:207-251`). The resolver
(`schema.load_stack_with_recipes`) reads `<root>/stacks/<stack>` +
`<root>/recipes/<name>`, so the sibling `recipes/`+`stacks/` layout under
`tools/test-fixtures` works with no code changes. Emitted profiles land under
`tools/test-fixtures/profiles/`, which is **gitignored** (`.gitignore:18-20`).

The scan is **scoped** to the one stack's recipe dirs + emitted profile — never
the whole repo — so a committed fixture cannot red-line an unrelated build
(BLD-02a, `lib/harnessed-common.sh` `build_stack`).

---

## 4. Mocking — none, by policy

**There are no mocks.** This is a hard rule, restated in the project's own
engineering principles. Tests drive the **real** `harnessed` CLI against **real**
containers and **real** manifests:

- The capability test launches a real pod, `podman exec`s into it, and reads the
  real hatago resource / real filesystem.
- UAT suites call `$HARNESSED` (the real launcher) end to end.
- Fixtures are real `recipe.yaml`/`stack.yaml`/`service.yaml`, not stubs.

Where a test must avoid touching the operator's real environment, it points a
config path at a **nonexistent** location to exercise the inert/no-token path —
not a mock:

```bash
# tools/uat/phase-05.sh — forces the inert secrets path without touching real ~/.config
UAT_NO_SCHEMA="/nonexistent/harnessed-uat-$$/.env.schema"
uat_run_env "HARNESSED_SCHEMA=$UAT_NO_SCHEMA" "$HARNESSED" build tracer-time
assert_not_contains "Resolving secrets via varlock" "$UAT_OUT" "SEC-01: varlock inert when no schema"
```

The `low-recipe`/`vuln-recipe` split (a real vulnerable pin vs a real sub-HIGH
pin) is the substitute for a mocked scanner: it proves the **severity gate**
behaves differently on real, stable advisories.

---

## 5. Coverage — integration-only, oracle-driven

There is **no coverage tooling** and no coverage target. The test contract is the
**manifest oracle**: `expected_capabilities` (what the stack *declares*) is the
spec, and the live instance is asserted against it. Coverage is therefore
behavioral, not line-based — a green capability run proves the assemble→launch→
introspect→report path works for that stack's declared surface.

The pure helper functions (`gate()`, `expected_capabilities()`, `build_report()`,
CVSS math in `scan.py`) are written to be unit-testable and are marked as such in
comments, but **no unit tests exercise them in isolation** — they are covered
transitively by the live runs and the fixtures.

---

## 6. CI — web deploy only; no test pipeline

The only GitHub Actions workflow is `.github/workflows/deploy-web.yml`, which
builds the Astro site (`web/`) and deploys it to GitHub Pages on a push to `main`
that touches `web/**`. **No workflow runs the capability test or the UAT suites.**

Both test mechanisms are designed to be CI-consumable but are **operator-run
locally** today, because they require rootless podman, built harnessed images, and
(in the case of live capability runs) Claude auth. Specifically:

- `harnessed test --json` emits a clean structured result + a 0/1 exit code
  suitable for a CI step — but no workflow wires it up.
- `run-uat.sh` returns non-zero on any failed test — CI-ready, but not wired.

If you add CI, the natural shape is: `run-uat.sh <phase> --quick` (fast,
container-free) as a required gate, and `harnessed test <stack> --json` per
proof-stack as the heavier integration job.

---

## 7. Provider portability — a known limit of the heavy tests

The heavy (container-launching) tests exercise the **isolated** path, which is
podman-pod-based. The matrix suite (`phase-06.sh`) calls this out explicitly:

> On Docker / Apple `container` these heavy tests will fail until the runtime
> layer is provider-agnostic — the matrix is the regression gate that will prove
> that port when it lands.

The runtime abstraction (`lib/harnessed-runtime.sh`) is the work in progress that
will make `harnessed test` and the UAT heavy legs pass on docker/apple. Until
then, run heavy tests on podman.

---

## 8. Quick reference — what to run

| You want to… | Run |
|--------------|-----|
| Prove a stack's declared capabilities are live | `harnessed test <stack>` (add `--json` for CI, `--keep` to inspect the pod) |
| Run the fast CLI/manifest surface | `./tools/uat/run-uat.sh 4 --quick` |
| Run a full phase (needs podman) | `./tools/uat/run-uat.sh 4` |
| Run one UAT test | `./tools/uat/run-uat.sh 4 svc_up` |
| Prove the supply-chain gate aborts on HIGH | `./harnessed build vuln-stack --root tools/test-fixtures` (expect exit 1) |
| Prove sub-HIGH builds green | `./harnessed build low-stack --root tools/test-fixtures` (expect exit 0) |
| Prove raw-npm recipes are rejected | `./harnessed build npm-stack --root tools/test-fixtures` (expect exit 1, `pnpm dlx`) |
| Exercise the whole harness matrix | `./tools/uat/run-uat.sh 6` |
