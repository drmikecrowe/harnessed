# Testing

**Analysis Date:** 2026-06-22

## Philosophy: two test layers, both behavior-through-the-instance — no unit suite

harnessed has **no unit-test suite, no pytest config, no bats config** in the product
tree, and that is by design (design §18). What it ships instead are **two complementary
behavioral layers** — both black-box, both driving the real `harnessed` CLI / running
instance, neither coupled to internals:

1. **The capability test** (`harnessed test <stack>`) — one stack at a time, manifest
   oracle vs live `--fresh` introspection. The narrow, declarative contract: *"the
   instance exposes exactly the MCP servers / skills / commands its stack declares."*
2. **The UAT suites** (`tools/uat/phase-04.sh`, `phase-05.sh`) — phase-scoped,
   pure-bash suites that drive the full CLI surface (svc, new, install, build,
   rescan, docs) with AAA-structured tests + assertions.

The rationale, stated in `docs/harnessed-design.md` and grounded in the project's `tdd`
skill, is that **the public interface is the running instance**. Testing the
assembler's internals (`vendor`/`sync-links`/merge) directly would couple to
*implementation* and break on every refactor — the exact anti-pattern the TDD skill
warns against. Instead the assembler is covered **transitively**: wire the wrong thing
and the capability test fails. From the design spec:

> **No assembler unit tests.** Testing `vendor`/`sync-links`/merge internals couples to
> implementation and breaks on refactor. The assembler is covered *transitively*: wire
> the wrong thing and the capability test fails.

**The honest tradeoff** (also from §18): an assembler bug surfaces as a *capability
failure*, not a pinpointed unit failure — coarser to debug. The mitigation is **clear,
fail-fast assembler errors** (the `CollisionError` that names both source paths, the
`RecipeLintError` that names the pnpm equivalent) so a failed build says *what* it
couldn't wire. See `docs/codebase/CONVENTIONS.md` → "Fail-fast validation".

There is a third, lighter layer — **static parse gates** (`bash -n`, `python ast.parse`,
`yaml.safe_load`) — documented at the end. They are not a shipped test runner; they are
the one-liner sanity checks used in the GSD phase-verification workflow and as a manual
"does it parse?" guard before a heavier behavioral run.

---

## Layer 1 — the capability test is the oracle

The stack manifest (`stacks/<stack>/stack.yaml` + its recipes) is the **test oracle**.
Expected capabilities are **derived** from it — never hardcoded. The test then launches
the stack, introspects the live pod, and diffs actual-vs-expected into one structured
result. The canonical flow (design §18, implemented in `capability.py`):

```
manifest  →  expected set  →  launch --fresh HEADLESS  →  introspect  →  diff  →  report
 (oracle)     (pure)            (podman)                  (podman)       (pure)    (exit)
```

It reads like a spec: *"`tracer-time` exposes MCP `time` and skill `time-helper`."*
Declare the capability in the manifest and the assertion exists; there is no separate
test code to write.

The full orchestration lives in one function — `run_capability_test`
(`tools/harnessed/capability.py:537`):

```python
# tools/harnessed/capability.py:537-573
def run_capability_test(
    root: Path | str,
    stack_name: str,
    *,
    project_path: str | None = None,
    harnessed_bin: str | None = None,
    keep: bool = False,
) -> CapabilityReport:
    """Full test: manifest oracle → launch --fresh headless → introspect → diff → teardown.

    Returns the single structured `CapabilityReport` that drives both the report and the exit code.
    """
    expected = expected_capabilities(root, stack_name)
    harness = _harness_of(root, stack_name)

    # Own the scratch project dir for the WHOLE test: it is the pod's project bind-mount and must
    # outlive launch→introspect→teardown (deleting it mid-run breaks `podman exec`).
    own_project = project_path is None
    if own_project:
        project_path = tempfile.mkdtemp(prefix=f"harnessed-test-{stack_name}-")
    try:
        instance = launch_headless(
            root, stack_name, project_path=project_path, harnessed_bin=harnessed_bin
        )
        try:
            wait_ready(instance)
            live = introspect(instance, harness)
        finally:
            if not keep:
                teardown(instance, harnessed_bin=harnessed_bin)
    finally:
        if own_project and not keep:
            shutil.rmtree(project_path, ignore_errors=True)
    return build_report(stack_name, expected, live)
```

Note the shape: **pure** (`expected_capabilities`, `build_report`) on the ends,
**podman-touching** (`launch_headless`, `wait_ready`, `introspect`, `teardown`) in the
middle, with `try/finally` guaranteeing teardown of both the pod and the scratch dir.

### The oracle: manifest → expected (pure)

`expected_capabilities` reuses the schema API (`schema.py`) to derive the expected
MCP servers, skills, and commands from the manifest. It touches no container runtime:

```python
# tools/harnessed/capability.py:115-121
def expected_capabilities(root: Path | str, stack_name: str) -> schema.Capabilities:
    """Derive the EXPECTED capabilities from the manifest oracle (reuses 02-01's schema API).

    Pure: reads `stacks/<stack>/stack.yaml` + its recipes under `root`; touches no container runtime.
    """
    stack, recipes = schema.load_stack_with_recipes(Path(root), stack_name)
    return schema.expected_capabilities(stack, recipes)
```

The derivation itself is a fold over each recipe's declared servers/skills/commands
(`tools/harnessed/schema.py:356`):

```python
def expected_capabilities(stack: Stack, recipes: list[Recipe]) -> Capabilities:
    mcp: list[str] = []
    skills: list[str] = []
    commands: list[str] = []
    for recipe in recipes:
        mcp.extend(s.name for s in recipe.servers)
        skills.extend(s.name for s in recipe.skills)
        commands.extend(c.name for c in recipe.commands)
    return Capabilities(mcp_servers=mcp, skills=skills, commands=commands)
```

So the expected set is simply *every MCP server, skill, and command name declared by
the stack's recipes*. Add a capability to a recipe and it is asserted automatically.

### How a test runs: the two-layer path

The test is invoked as a host command but executed by host-native Python. Two layers:

#### Layer 1 — host bash: `harnessed test <stack>`

`harnessed` parses the `test` subcommand, ensures the stack is built (assembling +
building hatago + the matching harness image if needed), resolves a Python interpreter,
and hands off to the CLI's `test` subcommand. The exit code propagates as the process
exit:

```bash
# harnessed:335-378 (condensed)
if [ "$TEST" = true ]; then
    ... # validate stacks/$TEST_STACK/stack.yaml exists; build_stack if profile/hatago missing
    ensure_images
    # Ensure the stack's harness image up front (one grep per harness; HRN-01..HRN-05):
    grep -q '^harness:[[:space:]]*omp' .../stack.yaml && ensure_omp_image
    grep -q '^harness:[[:space:]]*opencode' .../stack.yaml && ensure_opencode_image
    ... # gemini / antigravity / codex
    # Resolve an interpreter with ruamel.yaml + rich (host dep surface stays at "podman only"):
    #   HARNESSED_PYTHON > uv run --with … > a host python3 that already imports them.
    test_rc=0
    run_env=(PYTHONPATH="$HARNESSED_DIR/tools" CONTAINER_RUNTIME="$CONTAINER_RUNTIME" HARNESSED_DIR="$HARNESSED_DIR")
    if [ -n "${HARNESSED_PYTHON:-}" ]; then
        env "${run_env[@]}" "$HARNESSED_PYTHON" -m harnessed.cli test "${TEST_ARGS[@]}" --root "$HARNESSED_DIR" || test_rc=$?
    elif command -v uv >/dev/null 2>&1; then
        env "${run_env[@]}" uv run --no-project --quiet --with ruamel.yaml --with rich \
            python -m harnessed.cli test "${TEST_ARGS[@]}" --root "$HARNESSED_DIR" || test_rc=$?
    ...
    exit "$test_rc"
fi
```

Two things to notice:
- **The capability test is host-native Python, NOT the tools image.** It drives host
  podman (`launch` + `podman exec` introspection + teardown), so it cannot run inside
  the emit-only assembler image (no daemon-in-container — design §15).
- **The exit code is captured (`|| test_rc=$?`) and re-exited** so a red result
  propagates under `set -e` rather than aborting the launcher mid-parse.

#### Layer 2 — Python CLI: the `test` subcommand

`_run_test` (`tools/harnessed/cli.py:130`) calls `run_capability_test` and renders the
report; the **same** structured result drives both the rendered output and the exit
code:

```python
# tools/harnessed/cli.py:130-148
def _run_test(args: argparse.Namespace, out: Console, err: Console) -> int:
    """Run the per-stack capability test, render the report, return the test status as exit code.

    The SAME structured result drives the report and the exit code (design §18 / D-11): non-zero
    propagates so `harnessed test` (and CI) goes red when a declared capability is missing.
    """
    root = Path(args.root) if args.root else Path.cwd()
    try:
        report_result = run_capability_test(
            root, args.stack,
            project_path=args.project, harnessed_bin=args.harnessed_bin, keep=args.keep,
        )
    except (CapabilityError, SchemaError) as exc:
        err.print(f"[bold red]capability test failed:[/bold red] {exc}", highlight=False)
        return 1
    return report.emit(report_result, as_json=args.as_json, console=out)
```

The test subcommand's flags (`tools/harnessed/cli.py`): `--root` (alternate
stacks/+recipes/ root), `--project` (scratch project path; default a temp dir),
`--harnessed-bin` (explicit launcher path), `--keep` (don't tear down — for debugging),
`--json` (structured result for CI instead of the rich table).

### Introspection: machine-readable primary, LLM backstop

Design §18 / D-10 mandates **deterministic, machine-readable** introspection with the
LLM prompt as a *behavioral backstop only*. `introspect()` gathers three capability
kinds, each with a primary source and a fallback:

```python
# tools/harnessed/capability.py:511-534
def introspect(instance: str, harness: str = "claude") -> LiveCapabilities:
    """Gather the live instance's actual capabilities (MCP + skills + commands).

    `harness` only routes the LLM fallback; the primary checks — hatago's
    `hatago://servers` resource and the mounted-profile filesystem listing — are
    harness-independent (plan 04-03).
    """
    mcp, mcp_source = introspect_mcp(instance, harness)

    skills = _fileext_from_filesystem(instance, "skills")
    skills_source = "mounted profile filesystem"
    if not skills:
        skills = _skills_from_llm(instance, harness)
        skills_source = f"{harness} -p (llm backstop)"

    commands = _fileext_from_filesystem(instance, "commands")

    return LiveCapabilities(mcp=mcp, skills=skills, commands=commands,
                            mcp_source=mcp_source, skills_source=skills_source)
```

#### MCP servers — the `hatago://servers` resource (primary)

The authoritative MCP source is **hatago itself**, not the harness. `_mcp_from_hatago`
(`capability.py:388`) performs a Streamable-HTTP `initialize` → `notifications/initialized`
→ `resources/read` handshake against hatago's single endpoint
(`http://localhost:3535/mcp`) and reads the `hatago://servers` resource — a JSON
snapshot of the connected child servers behind the hub. This is **harness-independent**
and auth-free:

```python
# tools/harnessed/capability.py:472-486
def introspect_mcp(instance: str, harness: str = "claude") -> tuple[dict[str, str], str]:
    """Return ({connected server -> status}, source-label), preferring machine-readable sources.

    hatago's `hatago://servers` resource is the machine-readable primary (auth-free; lists the
    connected child servers) and is harness-INDEPENDENT. ... The harness-specific headless LLM
    probe (`_mcp_from_llm`) is the backstop; `harness` only routes that fallback.
    """
    servers = _mcp_from_hatago(instance)
    if servers:
        return servers, HATAGO_SERVERS_URI
    servers = _mcp_from_llm(instance, harness)
    if servers:
        return servers, f"{harness} -p (strict isolated config)"
    return {}, HATAGO_SERVERS_URI
```

`_mcp_from_llm` is the harness-aware backstop, routed by `_harness_of`
(`capability.py:289`) and `_llm_cmd` (`capability.py:303-328`) — the **one** place the
test branches on harness: omp uses `omp -p --mode json`, opencode `opencode run …
--format json`, gemini `gemini -p … --output-format json`, antigravity `agy -p …`,
codex `codex exec …`, claude `claude -p … --output-format json`. The primary
`hatago://servers` check is shared by all six.

#### Skills / commands — the mounted profile filesystem (primary)

Skills and commands are read by listing the mounted profile's dirs inside the live
member (`_fileext_from_filesystem`), which is also harness-independent:

```python
# tools/harnessed/capability.py:492-498
def _fileext_from_filesystem(instance: str, subdir: str) -> set[str]:
    """List visible extension dirs (skills/commands) from the mounted profile filesystem."""
    raw = _exec(
        instance,
        f'ls -1 {CONTAINER_HOME}/.claude/{subdir} 2>/dev/null || true',
    )
    return {line.strip() for line in raw.splitlines() if line.strip()}
```

The LLM backstop (`_skills_from_llm`) asks the harness, headless, to emit the skills it
sees as a JSON array — used only when the filesystem listing comes back empty.

### Readiness: `wait_ready`

hatago needs a few seconds to boot and connect its stdio children before it binds its
port; introspecting too early yields false negatives. `wait_ready` polls a TCP connect
to `127.0.0.1:<port>` *from inside the pod* until it succeeds (or times out at 60s):

```python
# tools/harnessed/capability.py:257-278
def wait_ready(instance: str, *, port: int = HATAGO_PORT, timeout: int = 60) -> bool:
    """Poll until the harness member is exec-ready AND hatago's HTTP port is bound.

    ... introspecting before then yields false negatives (the MCP probe finds nothing
    and the filesystem skill probe can race a not-yet-exec-ready member).
    """
    deadline = time.monotonic() + timeout
    probe = f'timeout 2 bash -c "echo > /dev/tcp/127.0.0.1/{port}" 2>/dev/null'
    while time.monotonic() < deadline:
        try:
            proc = subprocess.run(
                [_runtime(), "exec", instance, "bash", "-lc", probe],
                capture_output=True, text=True, timeout=10,
            )
        except (subprocess.SubprocessError, OSError):
            proc = None
        if proc is not None and proc.returncode == 0:
            return True
        time.sleep(1)
    return False
```

### The diff + the report (pure, one mechanism two audiences)

`build_report` (`tools/harnessed/capability.py:124`) produces one `CapabilityResult`
per *expected* capability — present iff the live instance exposed it. The detail field
is a short status reason only, **never a config value or token** (threat T-02-07):

```python
# tools/harnessed/capability.py:124-153
def build_report(stack_name, expected, live) -> CapabilityReport:
    """Pure expected-vs-live diff → the structured result. No podman; unit-testable.

    One `CapabilityResult` per *expected* capability (the manifest is the oracle): present iff the
    live instance exposed it. Detail is a short status reason only — never a config value.
    """
    results: list[CapabilityResult] = []
    for name in expected.mcp_servers:
        present = name in live.mcp
        if present:
            detail = live.mcp.get(name) or live.mcp_source or "connected"
        else:
            checked = live.mcp_source or f"{HATAGO_SERVERS_URI} / claude mcp list"
            detail = f"not connected (checked {checked})"
        results.append(CapabilityResult(name=name, kind=MCP, present=present, detail=detail))
    for name in expected.skills:
        ...
    for name in expected.commands:
        ...
    return CapabilityReport(stack=stack_name, results=results)
```

The `CapabilityReport` derives its pass/fail and exit code from the **same** result:

```python
# tools/harnessed/capability.py:76-98
@dataclass
class CapabilityReport:
    stack: str
    results: list[CapabilityResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Green only when every expected capability is present/connected."""
        return all(r.present for r in self.results)

    @property
    def exit_code(self) -> int:
        """The CI/process exit code derived from the SAME result (0 green, 1 any missing)."""
        return 0 if self.ok else 1
```

`report.py` renders that one result two ways — a `rich` markdown table for the
operator, or `--json` (the raw `to_dict()`) for CI. One mechanism, two audiences:

```markdown
## tracer-time — capability report
| capability   | kind   | status         |
|--------------|--------|----------------|
| time         | mcp    | ✓ connected    |
| time-helper  | skill  | ✓ present      |
```

### Running a capability test

```bash
# The normal way — host launcher resolves the interpreter + builds if needed:
harnessed test tracer-time

# Structured JSON for CI (exit 0 green, 1 any missing):
harnessed test tracer-time --json

# Debugging: keep the pod up after the test so you can `podman exec` into it:
harnessed test tracer-time --keep

# Force a specific interpreter (skips the uv/host-python3 resolution):
HARNESSED_PYTHON=/usr/bin/python3.12 harnessed test tracer-time
```

What `harnessed test <stack>` does, end to end:
1. Validates `stacks/<stack>/stack.yaml` exists.
2. Ensures the stack is built — assembles the profile + builds the hatago image if
   either is missing (`build_stack`); ensures the harness/base images; for a non-claude
   stack, ensures the matching harness image up front (one `ensure_*` per harness).
3. Runs host-native `python -m harnessed.cli test <stack> --root <repo>`, which:
   derives the expected set, launches the stack `--fresh` **headless**
   (`HARNESSED_HEADLESS=true` → pod composed + started, no interactive harness
   attach — members stay up on `sleep infinity` for `podman exec`), waits for hatago's
   port, introspects, diffs, tears down, and renders the report.
4. Exits with the test's exit code (0 green / 1 any missing capability).

Prerequisites on the host: **podman** (or docker), and either **uv** or a **python3
with `ruamel.yaml` + `rich`**. The launcher prints a clear error if none is found
(`harnessed:374-376`).

### What runs where — do not get this wrong

| Code | Runs inside the `harnessed-tools` image? | Runs host-native? |
|---|---|---|
| `assemble.py`, `emit.py`, `schema.py`, `synclinks.py`, `scan.py` (emit + source/image scan) | **Yes** (emit-only; mounted build dir) | No |
| `capability.py`, `report.py`, `scan.py` (the `gate`/CVSS pure logic) | No | **Yes** (`harnessed test` → host python) |
| `harnessed` + `lib/*.sh` | No | **Yes** (host podman) |

The capability test is the one place Python touches podman — and it is deliberately
kept out of the emit-only image.

---

## Layer 2 — the UAT suites (`tools/uat/`)

The capability test covers *one stack's declared wiring*. The **UAT suites** cover the
**rest of the CLI surface and the cross-cutting behaviors** the capability test cannot
reach: `svc up/down/list`, `new`/`install`/`uninstall`, `auth`, `rescan`, the systemd
timer units, state persistence, the legible state-dir slug, the legacy flags, and
documentation completeness. They are **pure bash** (no bats, no pytest) and drive the
real `harnessed` launcher end to end.

### Layout

```
tools/uat/
├── run-uat.sh        # driver: parses <phase> [--quick] [test_id], sources the phase suite, runs it
├── uat-common.sh     # the harness: AAA markers, assertions, run_test driver, summary
├── phase-04.sh       # Phase 4: shared services + recipe breadth + full CLI + state persistence
└── phase-05.sh       # Phase 5: secrets/hardening (SEC-01..04) + docs completeness (DOC-01..03)
```

### The driver: `run-uat.sh`

`run-uat.sh` resolves `HARNESSED_DIR` + the launcher, normalizes the phase number
(`4` / `04` / `phase-04` → `04`), sources the matching `phase-NN.sh`, and either runs
one named test or the whole phase via its `uat_run_phase` entrypoint:

```bash
# tools/uat/run-uat.sh:55-74 (condensed)
HARNESSED_DIR="$(cd "$HERE/../.." && pwd)"; export HARNESSED_DIR
export HARNESSED="$HARNESSED_DIR/harnessed"
# shellcheck source=tools/uat/phase-04.sh
. "$SUITE"
if [ -n "$TEST_ONLY" ]; then
    run_test "$TEST_ONLY" "$TEST_ONLY"     # one test: ./run-uat.sh 4 svc_up
else
    uat_run_phase                          # whole phase: ./run-uat.sh 4
fi
uat_summary                              # prints totals; exit code 1 if any failed
```

### The harness: `uat-common.sh`

A UAT test is a function named `test_<id>`, driven by `run_test <id> "<label>"`.
Inside a test, structure the work with the three **AAA markers** (purely visual — the
discipline, not machinery) and assert with the helpers. **No external deps** — pattern
matching uses bash's `[[ =~ ]]` / `[[ == *..* ]]`, matching the project's
dependency-free ethos.

```bash
# tools/uat/uat-common.sh:35-37 — the AAA section markers
arrange() { echo "  ▸ Arrange"; }
act()     { echo "  ▸ Act"; }
assert()  { echo "  ▸ Assert"; }
```

The assertions all **record pass/fail into shared counters and never abort** — a failing
assertion sets `UAT_TEST_FAIL=1` but the test keeps running, so one run surfaces every
problem, not just the first:

```bash
# tools/uat/uat-common.sh:46-73 — the assertion vocabulary
assert_exit_zero()    { if [ "$1" -eq 0 ]; then _uat_pass "$2"; else _uat_fail "$2" "exit=$1"; fi; }
assert_exit_nonzero() { if [ "$1" -ne 0 ]; then _uat_pass "$2"; else _uat_fail "$2" "exit=0 (expected non-zero)"; fi; }
assert_eq()           { if [ "$1" = "$2" ]; then _uat_pass "$3"; else _uat_fail "$3" "expected=[$2] actual=[$1]"; fi; }
assert_match()        { if [[ $2 =~ $1 ]]; then _uat_pass "$3"; else _uat_fail "$3" "no match /$1/ in: ${2:0:160}"; fi; }
assert_contains()     { if [[ $2 == *"$1"* ]]; then _uat_pass "$3"; else _uat_fail "$3" "missing [$1]"; fi; }
assert_not_contains() { if [[ $2 != *"$1"* ]]; then _uat_pass "$3"; else _uat_fail "$3" "unexpected [$1]"; fi; }
assert_exists()       { if [ -e "$1" ]; then _uat_pass "$2"; else _uat_fail "$2" "not found: $1"; fi; }
assert_file_contains(){ if [ -r "$1" ] && [[ $(cat "$1") == *"$2"* ]]; then _uat_pass "$3"; else _uat_fail "$3" "[$2] not in $1"; fi; }
assert_executable()   { if [ -x "$1" ]; then _uat_pass "$2"; else _uat_fail "$2" "not executable: $1"; fi; }
# Boolean: LAST arg is the label; preceding args are the command to run.
assert_true()  { local _lbl="${!#}"; local _cmd=("${@:1:$#-1}"); if "${_cmd[@]}" >/dev/null 2>&1; then _uat_pass "$_lbl"; else _uat_fail "$_lbl" "condition false"; fi; }
assert_false() { ... pass if cmd exits non-zero ... }
```

Commands are run through `uat_run` / `uat_run_env`, which capture `UAT_OUT` / `UAT_RC`
for the assertions:

```bash
# tools/uat/uat-common.sh:85-95
uat_run()      { echo "    ▸ $*"; UAT_OUT=$("$@" 2>&1); UAT_RC=$?; }            # stdout+stderr merged
uat_run_env()  { local envs="$1"; shift; UAT_OUT=$(env $envs "$@" 2>&1); UAT_RC=$?; }  # +env (e.g. HARNESSED_HEADLESS=true)
```

### `phase-04.sh` — shared services, recipe breadth, full CLI, state

Every test follows AAA. The service tests are the canonical shape — and they encode the
**host-gateway networking contract** (a service publishes its port to `0.0.0.0`, not a
bridge):

```bash
# tools/uat/phase-04.sh:55-67
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

The phase's 15 tests, grouped (`phase-04.sh:288-309`):

| Section | Tests | What they assert |
|---|---|---|
| A: shared services | `svc_up`, `svc_up_idempotent`, `svc_down_retains_volume`, `svc_down_purge`, `shared_single_across_instance` | publish-to-0.0.0.0, idempotency, volume survives `down` / destroyed by `--purge`, one shared container across an instance attach |
| B: recipe breadth + bridge | `recipe_breadth`, `omp_bridge` | a second recipe is asserted; an omp stack exposes the time capability via the bridge |
| C: CLI surface | `no_args_help`, `list_surface`, `new_scaffold_refuse`, `new_bad_harness`, `install_uninstall`, `legacy_flags` | bare invocation shows help; `list` shows stacks+instances; `new` scaffolds + refuses overwrite + rejects a bad harness; install/uninstall shim round-trip; legacy `--list` back-compat |
| D: state persistence + slug | `state_persists`, `fresh_wipes`, `legible_slug` | state survives a normal recreate; `--fresh` wipes it (clean-room); the state-dir slug is a legible path, not a hash |

Two tests encode **known gaps as red regression checks** (go green when the fix lands):
`no_args_help` (bare `harnessed` should show usage, not launch transparent) and
`legible_slug` (state dir should be legible). Heavy tests (container launches)
**self-skip under `--quick`** via `needs_container`:

```bash
# tools/uat/phase-04.sh:39
needs_container() { [ "$UAT_QUICK" = "true" ]; }   # true ⇒ this test should skip
# used as:
test_shared_single_across_instance() {
    needs_container && { skip_test "skipped (--quick)"; return; }
    ...
}
```

### `phase-05.sh` — secrets, hardening, docs

Covers SEC-01..04 + DOC-01..03 by driving the real CLI. The live legs that need a
1Password desktop app / interactive browser / an overnight timer fire are tracked as
manual-only (`05-HUMAN-UAT.md`, HV-1..HV-4); the suite exercises the **scriptable**
behaviors. The secrets tests point `HARNESSED_SCHEMA` at a guaranteed-absent path so
they exercise the inert/no-token paths without touching the operator's real config:

```bash
# tools/uat/phase-05.sh:32-43 — SEC-01 inertness + SEC-02 warn-and-skip in one build
test_secrets_inert_and_skip() {
    needs_container && { skip_test "skipped (--quick) — runs the tools container"; return; }
    arrange; act
    uat_run_env "HARNESSED_SCHEMA=$UAT_NO_SCHEMA" "$HARNESSED" build tracer-time
    assert
    assert_exit_zero "$UAT_RC" "build is non-interactive + green with no schema/token"
    assert_not_contains "Resolving secrets via varlock" "$UAT_OUT" "SEC-01: varlock inert when no schema"
    assert_contains "snyk skipped (no SNYK_TOKEN)" "$UAT_OUT" "SEC-02: snyk warns-and-skips without a token"
}
```

Its 8 tests (`phase-05.sh:156-170`): `secrets_inert_and_skip`, `scanner_token_invoked`
(a present token is forwarded → snyk invoked, not skipped, build still green),
`auth_dispatch` (accepts only `snyk|socket`), `rescan_online` (SEC-04 online image
scan), `rescan_timer_units` (the systemd USER units carry `OnCalendar=daily`,
`Persistent=true`, the `enable-linger` prerequisite), and `doc_readme` /
`doc_authoring_guides` / `doc_ops_guides` (the shipped docs exist + cite real examples +
describe the host-side secrets model).

### Running the UAT suites

```bash
# Whole phase 4 (heavy tests run if a runtime is present):
./tools/uat/run-uat.sh 4

# Fast pass only — skip every container-launch/build/scan test:
./tools/uat/run-uat.sh 4 --quick

# One named test (the test_<id> suffix):
./tools/uat/run-uat.sh 4 svc_up
./tools/uat/run-uat.sh 05 rescan_timer_units

# Phase number is normalized: 4 / 04 / phase-04 all resolve to phase-04.sh
```

Exit code is non-zero if any test failed (`uat_summary` returns 1 on failure). With no
container runtime on PATH, the heavy tests skip and the suite reports the skip count;
the CLI/docs/static tests still run.

---

## The supply-chain scan gate (BLD-02)

The scan gate is **not** a test suite you run directly in normal dev — it fires
*inside* `harnessed build <stack>` (twice: a source/Python scan, then an image scan) and
inside `harnessed rescan` (online, nightly). Its pure logic is testable in principle and
its behavioral anchors are the fixture pair under `tools/test-fixtures/`.

The crux (RESEARCH Pattern 2 / Pitfall 3): **osv-scanner `scan` exits 1 on ANY finding
with no severity flag**, so the HIGH threshold is pure Python over `--format json`,
never the scanner exit code. The single decision point is `gate()` in
`tools/harnessed/scan.py`:

```python
# tools/harnessed/scan.py:31, 49-59, 119-132
HIGH = 7.0    # CVSS HIGH threshold — the build ABORTS at >= HIGH; below is a warning.

class ScanError(Exception):
    """A supply-chain scan found a HIGH+ finding (CVSS >= HIGH) — the build must abort."""

@dataclass
class ScanResult:
    scope: str
    highs: list[str] = field(default_factory=list)       # HIGH ids drive the abort
    warnings: list[str] = field(default_factory=list)    # low/medium — rendered, never fail

def gate(osv_json: dict) -> list[str]:
    """Return HIGH+ finding ids (CVSS >= HIGH); empty list ⇒ pass. The ONLY HIGH decision point.

    Reads the parsed severity score — NEVER the scanner exit code (Pitfall 3): osv-scanner exits 1
    on *any* finding, so the exit code cannot decide HIGH.
    """
    highs: list[str] = []
    for result in osv_json.get("results", []):
        for pkg in result.get("packages", []):
            for vuln in pkg.get("vulnerabilities", []):
                if _max_cvss(vuln) >= HIGH:
                    highs.append(vuln.get("id", "?"))
    return highs
```

`_max_cvss` (`scan.py:101`) parses a CVSS v3 **vector string** (osv-scanner's
`severity[].score` is a vector, not a number — RESEARCH A3) and falls back to a
qualitative label band when no vector is parseable. The three CLI entrypoints map to
the launcher's call sites: `run_source_scan` (emit-compatible; runs in the tools image),
`run_image_scan` (host-driven over a `podman save` archive), `run_image_scan_online`
(SEC-04 nightly; drops the build-time `--offline` flags).

### The scan fixtures (the behavioral anchors)

Test fixtures live under `tools/test-fixtures/` and mirror the real repo layout
(`stacks/`, `recipes/`, `services/`, `profiles/`). They exercise the assembler and the
scan gate against controlled inputs, driven via `--root`/`--build-dir` so they never
pollute the real `stacks/` + `recipes/` (PORT-01 / BLOCKER-2(b)).

```
tools/test-fixtures/
├── stacks/
│   ├── svc-stack/stack.yaml        # references svc-recipe + the svc-test service
│   ├── low-stack/                  # a low-severity vuln fixture (scan must PASS)
│   ├── vuln-stack/                 # a HIGH+ vuln fixture (scan must ABORT)
│   └── npm-stack/                  # a raw-npm fixture (RecipeLintError at assemble)
├── recipes/
│   ├── svc-recipe/recipe.yaml      # service-referencing recipe (assembler resolution)
│   ├── low-recipe/  vuln-recipe/  npm-recipe/
├── services/
│   └── svc-test/service.yaml       # minimal service sidecar definition
└── profiles/                       # emitted outputs from prior fixture builds
```

The shared-service fixture pair is the canonical "recipe references a service" shape:

```yaml
# tools/test-fixtures/stacks/svc-stack/stack.yaml
name: svc-stack
config: isolated
harness: claude
recipes: [svc-recipe]
services: [svc-test]
```
```yaml
# tools/test-fixtures/recipes/svc-recipe/recipe.yaml
name: svc-recipe
description: Fixture recipe referencing a shared service (assembler-resolution test, plan 04-01).
mcp:
  servers:
    - name: svc-test
      service: svc-test
      transport: http
```

The scan fixtures encode the **CVSS >= HIGH gate**: `low-stack` must pass clean (finding
below threshold → warning only); `vuln-stack` must abort the build (`ScanError`);
`npm-stack` must fail at assemble with a `RecipeLintError`. These are the behavioral
anchors for the supply-chain gate. Drive them against the real assembler/scan path with
`--root`:

```bash
# Exercise the assembler against a fixture root (no podman; emit-only):
PYTHONPATH=tools python -m harnessed.cli assemble svc-stack --root tools/test-fixtures --build-dir /tmp/bd-svc

# Exercise the source scan against a fixture root:
PYTHONPATH=tools python -m harnessed.cli scan vuln-stack --root tools/test-fixtures --build-dir tools/test-fixtures
```

---

## Static parse gates — the one-liner sanity checks

There is **no CI test runner config** in this repo (no `pytest.ini`, no `tox.ini`, no
GitHub Actions workflow that runs a test matrix). The "does it parse?" guard is a set of
**manual one-liners**, used pervasively in the GSD phase-verification workflow
(`.planning/phases/*/…-PLAN.md` `<verify><automated>` blocks and `…-VERIFICATION.md`
checklists) and as a quick pre-commit sanity check. They are deliberately dependency-free:

```bash
# Bash syntax — every executable + sourced lib parses (set -euo pipefail-safe):
bash -n harnessed lib/harnessed-common.sh lib/harnessed-isolated.sh lib/harnessed-services.sh \
    lib/harnessed-runtime.sh lib/harnessed-mounts.sh lib/harnessed-cli.sh lib/harnessed-secrets.sh \
    lib/harnessed-transparent.sh

# Python parse — every module compiles (catches syntax errors + stray tabs; no execution):
python -m compileall -q tools/harnessed
# or, per-module (what the GSD phase verify uses):
python -c "import ast; [ast.parse(open(f).read()) for f in __import__('glob').glob('tools/harnessed/*.py')]; print('parse OK')"

# YAML well-formedness — every manifest loads (catches a hand-edit indentation error before a build):
python -c "import yaml, glob; [yaml.safe_load(open(f)) for f in glob.glob('**/*.yaml', recursive=True)]; print('yaml OK')"
# scoped to the authored manifests:
python -c "import yaml; [yaml.safe_load(open(f)) for f in ['recipes/time/recipe.yaml','stacks/tracer-time/stack.yaml','services/ping/service.yaml']]; print('manifests parse OK')"

# Import smoke — the package imports (catches a broken relative import / missing dep):
PYTHONPATH=tools python -c "import harnessed.capability, harnessed.report, harnessed.scan, harnessed.assemble, harnessed.schema, harnessed.cli"
```

These are the gate between "I edited a file" and "I'll run the heavier capability/UAT
suite." They are cheap, they need only `python3` + `bash` + `pyyaml` (or `uv run
--with pyyaml`), and they catch the class of error (typo, bad indent, broken import)
that would otherwise surface as a confusing mid-build failure. **They do not assert
behavior** — always follow a green parse gate with at least one behavioral run
(`harnessed test <stack>` or `./tools/uat/run-uat.sh <phase>`).

---

## "No unit tests by design" — and how bugs surface instead

Because there is no unit layer, an assembler regression surfaces as a **capability
failure** in the integration test, not a pinpointed unit failure. Concretely:

| Assembler bug | How it surfaces in the capability test / UAT |
|---|---|
| A skill collision should have fired but didn't | a later recipe's skill silently overwrites → the *expected* skill is missing in the live instance → `✗ missing` |
| A stdio MCP server isn't baked into the hatago image | hatago can't spawn it → `time` not in `hatago://servers` → `✗ not connected` |
| A `service:` server isn't resolved to a hatago URL-proxy | the proxy entry is absent → service never connects → `✗ not connected` |
| `validate_no_raw_npm` regresses | (surfaces at *assemble* time, before the test — `RecipeLintError` aborts `build_stack`) |
| A harness attach command is wrong | the headless launch's success line isn't found → `CapabilityError: headless launch did not report a running instance` |
| A service publishes to a bridge instead of 0.0.0.0 | UAT `test_svc_up` → `assert_match '0\.0\.0\.0:8080'` fails |

The mitigation is not to add unit tests; it is **clear, fail-fast assembler errors**.
The `CollisionError` names both offending source paths; the `RecipeLintError` names the
pnpm equivalent; the `ScanError` names the HIGH+ finding. A failed build says *what* it
couldn't wire, so the coarser integration signal is still debuggable.

---

## How to write a new assertion

### Add a capability (the common case — no test code)

**You usually don't write test code at all.** Capabilities are manifest-declared, so
adding one is an authoring change — the assertion appears automatically:

1. **Add the capability to a recipe.** For an MCP server, add an entry under
   `mcp.servers`; for a skill, add a `skills:` entry pointing at a dir whose leaf name
   is the skill name; likewise `commands:`. Example — adding a `time` MCP server and a
   `time-helper` skill (from `recipes/time/recipe.yaml`):
   ```yaml
   mcp:
     servers:
       - name: time
         command: uvx
         args: [mcp-server-time]
         transport: stdio
   skills:
     - path: skills/time-helper
   ```
2. **Add the recipe to a stack** (`recipes: [time]` in `stacks/<stack>/stack.yaml`).
3. **Rebuild and test**: `harnessed build <stack>` then `harnessed test <stack>`. The
   new `time` (mcp) and `time-helper` (skill) rows appear in the report; green means
   the live instance actually exposes them.

That is the whole loop — the manifest is the spec, the test is the spec's oracle.

### Add a UAT test (a new CLI behavior or cross-cutting invariant)

Add a `test_<id>` function to the relevant phase suite, follow AAA, assert with the
`uat-common.sh` helpers, and register it in `uat_run_phase`:

```bash
# tools/uat/phase-04.sh — a new CLI-behavior test
test_install_overwrite_refuse() {
    arrange
    "$HARNESSED" new uatdemo --harness claude >/dev/null 2>&1 || true
    act
    uat_run "$HARNESSED" install uatdemo
    uat_run "$HARNESSED" install uatdemo          # second time
    assert
    assert_exit_zero   "$UAT_RC" "first install exits 0"
    assert_exit_nonzero "$UAT_RC" "second install is idempotent/no-op or errors clearly"
    rm -rf "$HARNESSED_DIR/stacks/uatdemo"
}
# then in uat_run_phase:
run_test install_overwrite_refuse "install is idempotent"
```

### When you DO need to touch capability-test code

- **A new capability *kind*** (not mcp/skill/command): add the kind constant to
  `capability.py` (`MCP`/`SKILL`/`COMMAND`), extend `schema.Capabilities` +
  `expected_capabilities`, add a live-introspection source in `introspect()`, and a
  column branch in `build_report`. The `report.py` table renders any kind generically,
  so usually only `build_report` needs a new `for name in expected.<kind>` block.
- **A new introspection source** (e.g. a better primary than `hatago://servers`):
  add it in `capability.py` under the live-introspection section, wire it into
  `introspect_mcp` / `introspect` as the new primary, and keep the LLM as the backstop.
  Keep it harness-independent where possible (`_harness_of` routes only the fallback).
- **A new fixture** for a scanner/assembler edge case: add it under
  `tools/test-fixtures/` mirroring the real layout and drive it with
  `--root tools/test-fixtures` so it never touches the real manifests.

In all three, preserve the **pure/podman split**: the expected-set derivation and the
diff stay pure (no container runtime); only `launch_headless`/`wait_ready`/
`introspect`/`teardown`/`run_capability_test` touch podman, and they run host-native.
