# Testing

**Analysis Date:** 2026-06-16

## Philosophy: integration-only, behavior through the instance

harnessed has **exactly one kind of test**: the per-stack **capability test**. There
is no unit-test suite, no pytest config, no vitest config in this repo, and that is
by design (design §18).

The rationale, stated in `docs/harnessed-design.md:537-545` and grounded in the
project's `tdd` skill, is that **the public interface is the running instance**, and
the behavior under test is narrow and declarative:

> the behavior is "the instance exposes exactly the MCP servers / skills / commands
> its stack declares."

Testing the assembler's internals (`vendor`/`sync-links`/merge) directly would couple
to *implementation* and break on every refactor — the exact anti-pattern the TDD skill
warns against. Instead the assembler is covered **transitively**: wire the wrong thing
and the capability test fails. From the design spec:

> **No assembler unit tests.** Testing `vendor`/`sync-links`/merge internals couples to
> implementation and breaks on refactor — the anti-pattern the TDD skill warns against.
> The assembler is covered *transitively*: wire the wrong thing and the capability test
> fails.

**The honest tradeoff** (also from §18): an assembler bug surfaces as a *capability
failure*, not a pinpointed unit failure — coarser to debug. The mitigation is
**clear, fail-fast assembler errors** (the `CollisionError` that names both source
paths, the `RecipeLintError` that names the pnpm equivalent) so a failed build says
*what* it couldn't wire. See `docs/codebase/CONVENTIONS.md` → "Fail-fast validation".

---

## The capability test is the oracle

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
(`tools/harnessed/capability.py:518`):

```python
# tools/harnessed/capability.py:518-554
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

---

## The oracle: manifest → expected (pure)

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
(`tools/harnessed/schema.py:339`):

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

---

## How a test runs: the two-layer path

The test is invoked as a host command but executed by host-native Python. Two layers:

### Layer 1 — host bash: `harnessed test <stack>`

`harnessed` parses the `test` subcommand, ensures the stack is built (assembling +
building hatago if needed), resolves a Python interpreter, and hands off to the CLI's
`test` subcommand. The exit code propagates as the process exit:

```bash
# harnessed:287-326 (condensed)
if [ "$TEST" = true ]; then
    ... # ensure stacks/$TEST_STACK/stack.yaml exists; build_stack if profile/hatago missing
    ensure_images
    grep -q '^harness:[[:space:]]*omp' .../stack.yaml && ensure_omp_image   # omp-aware
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

### Layer 2 — Python CLI: the `test` subcommand

`_run_test` (`tools/harnessed/cli.py:126`) calls `run_capability_test` and renders the
report; the **same** structured result drives both the rendered output and the exit
code:

```python
# tools/harnessed/cli.py:126-144
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

The test subcommand's flags (`tools/harnessed/cli.py:51-82`): `--root` (alternate
stacks/+recipes/ root), `--project` (scratch project path; default a temp dir),
`--harnessed-bin` (explicit launcher path), `--keep` (don't tear down — for debugging),
`--json` (structured result for CI instead of the rich table).

---

## Introspection: machine-readable primary, LLM backstop

Design §18 / D-10 mandates **deterministic, machine-readable** introspection with the
LLM prompt as a *behavioral backstop only*. `introspect()` gathers three capability
kinds, each with a primary source and a fallback:

```python
# tools/harnessed/capability.py:492-515
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

### MCP servers — the `hatago://servers` resource (primary)

The authoritative MCP source is **hatago itself**, not the harness. `_mcp_from_hatago`
performs a Streamable-HTTP `initialize` → `notifications/initialized` →
`resources/read` handshake against hatago's single endpoint
(`http://localhost:3535/mcp`) and reads the `hatago://servers` resource — a JSON
snapshot of the connected child servers behind the hub. This is **harness-independent**
and auth-free:

```python
# tools/harnessed/capability.py:453-467
def introspect_mcp(instance: str, harness: str = "claude") -> tuple[dict[str, str], str]:
    """Return ({connected server -> status}, source-label), preferring machine-readable sources.

    hatago's `hatago://servers` resource is the machine-readable primary (auth-free; lists the
    connected child servers) and is harness-INDEPENDENT. `claude mcp list` / `omp` parity is
    intentionally NOT the primary — the hatago resource is authoritative. The harness-specific
    headless LLM probe (`_mcp_from_llm`) is the backstop; `harness` only routes that fallback.
    """
    servers = _mcp_from_hatago(instance)
    if servers:
        return servers, HATAGO_SERVERS_URI
    servers = _mcp_from_llm(instance, harness)
    if servers:
        return servers, f"{harness} -p (strict isolated config)"
    return {}, HATAGO_SERVERS_URI
```

`claude mcp list` / `omp -p --mode json` parity is **intentionally not** the primary —
the hatago resource is authoritative. `_mcp_from_llm` is the harness-aware backstop:
claude uses `--mcp-config <profile> --strict-mcp-config` (so the view matches the real
isolated session); omp is probed via `omp -p --mode json --profile` (the `_llm_cmd`
router in `capability.py:299`).

### Skills / commands — the mounted profile filesystem (primary)

Skills and commands are read by listing the mounted profile's dirs inside the live
member (`_fileext_from_filesystem`), which is also harness-independent:

```python
# tools/harnessed/capability.py:473-479
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
# tools/harnessed/capability.py:253-274
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

---

## The diff + the report (pure, one mechanism two audiences)

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

---

## Running a test

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
   either is missing (`build_stack`); ensures the harness/base images; for an `omp`
   stack, ensures `harnessed-omp` up front.
3. Runs host-native `python -m harnessed.cli test <stack> --root <repo>`, which:
   derives the expected set, launches the stack `--fresh` **headless**
   (`HARNESSED_HEADLESS=true` → pod composed + started, no interactive `claude`
   attach — members stay up on `sleep infinity` for `podman exec`), waits for hatago's
   port, introspects, diffs, tears down, and renders the report.
4. Exits with the test's exit code (0 green / 1 any missing capability).

Prerequisites on the host: **podman** (or docker), and either **uv** or a **python3
with `ruamel.yaml` + `rich`**. The launcher prints a clear error if none is found
(`harnessed:321-325`).

### What runs where — do not get this wrong

| Code | Runs inside the `harnessed-tools` image? | Runs host-native? |
|---|---|---|
| `assemble.py`, `emit.py`, `schema.py`, `synclinks.py`, `scan.py` (emit + scan) | **Yes** (emit-only; mounted build dir) | No |
| `capability.py`, `report.py`, `scan.py` (the `gate`/CVSS pure logic) | No | **Yes** (`harnessed test` → host python) |
| `harnessed` + `lib/*.sh` | No | **Yes** (host podman) |

The capability test is the one place Python touches podman — and it is deliberately
kept out of the emit-only image.

---

## Fixtures

Test fixtures live under `tools/test-fixtures/` and mirror the real repo layout
(`stacks/`, `recipes/`, `services/`, `profiles/`). They exercise the assembler and
the scan gate against controlled inputs, driven via `--root`/`--build-dir` so they
never pollute the real `stacks/` + `recipes/` (PORT-01 / BLOCKER-2(b)).

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

The scan fixtures encode the **CVSS >= HIGH gate** (BLD-02): `low-stack` must pass
clean (finding below threshold → warning only); `vuln-stack` must abort the build
(`ScanError`); `npm-stack` must fail at assemble with a `RecipeLintError`. These are
the behavioral anchors for the supply-chain gate.

---

## "No unit tests by design" — and how bugs surface instead

Because there is no unit layer, an assembler regression surfaces as a **capability
failure** in the integration test, not a pinpointed unit failure. Concretely:

| Assembler bug | How it surfaces in the capability test |
|---|---|
| A skill collision should have fired but didn't | a later recipe's skill silently overwrites → the *expected* skill is missing in the live instance → `✗ missing` |
| A stdio MCP server isn't baked into the hatago image | hatago can't spawn it → `time` not in `hatago://servers` → `✗ not connected` |
| A `service:` server isn't resolved to a hatago URL-proxy | the proxy entry is absent → service never connects → `✗ not connected` |
| `validate_no_raw_npm` regresses | (surfaces at *assemble* time, before the test — `RecipeLintError` aborts `build_stack`) |

The mitigation is not to add unit tests; it is **clear, fail-fast assembler errors**.
The `CollisionError` names both offending source paths; the `RecipeLintError` names the
pnpm equivalent; the `ScanError` names the HIGH+ finding. A failed build says *what* it
couldn't wire, so the coarser integration signal is still debuggable.

---

## How to write a new capability assertion

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

### When you DO need to touch test code

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
