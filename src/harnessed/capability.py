"""Per-stack capability test — manifest oracle vs live --fresh introspection (design §18).

The stack manifest is the **oracle**: the expected MCP servers / skills / commands are derived
from `stacks/<stack>/stack.yaml` + its recipes (reusing `schema.py`, plan 02-01) — never hardcoded.
The test then launches the stack `--fresh` HEADLESS via the 02-02 isolated launcher
(`HARNESSED_HEADLESS=true harnessed <stack> <project> --fresh`), introspects the LIVE pod, compares
ACTUAL vs expected into a single structured result, and tears the instance down (`--fresh` + remove
→ no state bleed, threat T-02-08).

Introspection prefers **machine-readable** sources (D-10), LLM prompt as the behavioral backstop:
  - MCP servers — hatago's `hatago://servers` resource (the connected child servers behind the hub)
    and/or `claude mcp list`; an `claude -p … --output-format json` prompt is the fallback.
  - Skills / commands — the mounted profile filesystem (`~/.claude/skills`, `~/.claude/commands`)
    diffed against the manifest; a headless JSON listing is the fallback.

One structured result (`CapabilityReport`) drives BOTH the rich report (report.py) and the CI exit
code (one mechanism, two audiences — design §18 / D-11). The report carries capability NAMES +
STATUS only, never config values/secrets (threat T-02-07).

The pure manifest→expected mapping (`schema.expected_capabilities`), the pure expected-vs-live diff
(`build_report`), and the pure recipe-test discovery + exit-code folding (`discover_recipe_tests`,
`fold_test_result`) take no podman and are unit-testable; the live-introspection functions
(`launch_headless`, `introspect`, `run_recipe_tests`, `teardown`, `run_capability_test`) are the
only podman-touching code and are guarded behind the launch.
"""

from __future__ import annotations

import json
import shlex
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Collection
from dataclasses import dataclass, field
from pathlib import Path

from . import paths, schema

# Capability kinds (stable strings — used by report.py + --json consumers).
MCP = "mcp"
SKILL = "skill"
COMMAND = "command"
PLUGIN = "plugin"
# TEST — a recipe-authored bash script (catalog/recipes/<name>/tests/*.sh) run against the live
# instance; present iff the script exits 0. Behavioral/arbitrary-kind supplement to expect: (main-c98).
TEST = "test"

# Where a recipe's tests/ dir is copied INSIDE the live instance (podman cp target), and the default
# per-script wall-clock budget (mirrors _exec's default). Kept small + explicit so scripts get a
# stable, documented location (HARNESSED_TEST_DIR points at their own recipe subdir).
REMOTE_TESTS_ROOT = "/tmp/harnessed-tests"  # noqa: S108 — container-side fixed test root, contract path
DEFAULT_TEST_TIMEOUT = 120
# Cap on the failure detail folded into the report — never echo a full script transcript (a stray
# secret could ride along, threat T-02-07); one truncated tail line is enough to see *why* it failed.
_TEST_DETAIL_MAX = 120

# hatago's single Streamable-HTTP endpoint inside the shared pod netns (design D-04). Single
# source: `paths.hatago_endpoint()` (honors the `HATAGO_PORT` env override).
HATAGO_ENDPOINT = paths.hatago_endpoint()
# The hub's connected-servers resource (the JSON snapshot of child servers behind hatago).
HATAGO_SERVERS_URI = "hatago://servers"
# In-container harness home → the mounted profile lives at $CONTAINER_HOME/.claude (launcher §4b).
CONTAINER_HOME = os.environ.get("CONTAINER_HOME", "/home/harnessed")
# hatago's HTTP port inside the pod (the readiness signal: bound ⇒ children connected).
HATAGO_PORT = paths.hatago_port()

# Where the hub writes its log INSIDE the instance (the redirect in `catalog/base/harnessed-start`).
#
# harnessed POINTS AT this file and never reads it. T-02-07: the report carries capability names and
# status only, never config values or secrets. hatago's children are MCP servers that take
# credentials from the environment, so a crashing child prints exactly the thing this report must
# not carry — and `--json` feeds that report to a public CI log. An earlier version of this module
# copied a 200-line tail of it into `CapabilityReport`; that was a T-02-07 violation added ~60 lines
# below the constant (`_TEST_DETAIL_MAX`) that exists to prevent the same mistake for recipe tests.
#
# The cost is real and accepted: a runner-only MCP failure is not self-diagnosing from the CI log.
# The remediation below is what makes it reachable in one step instead.
#
# The suppression below is for ruff S108 (insecure /tmp usage): that rule is about CREATING
# predictable temp files on a shared HOST filesystem. This is a container-internal path harnessed
# only ever names. (Do not spell the directive token in prose — ruff reads it as a real directive.)
_HATAGO_LOG_PATH = "/tmp/hatago.log"  # noqa: S108
MCP_MISS_REMEDIATION = (
    f"re-run with --keep, then `podman exec <instance> cat {_HATAGO_LOG_PATH}`"
)

# How long to wait for hatago's stdio CHILDREN after its own port is up, and how often to re-ask.
# `wait_ready` covers the port; these cover the gap between the port binding and the children
# finishing their connect (measured at 0.3s on a warm box, unbounded on a cold one — bd
# harnessed-rv2.2). Only paid by stacks that actually declare MCP servers.
MCP_CONNECT_TIMEOUT = 60
MCP_POLL_INTERVAL = 1.0


class CapabilityError(Exception):
    """The capability test could not be run (launch failed, instance not found, etc.)."""


# --- Structured result (the single source for report + CI exit, design §18) ----------------------


@dataclass
class CapabilityResult:
    """One expected capability and whether the live instance actually exposed it."""

    name: str
    kind: str  # MCP | SKILL | COMMAND
    present: bool
    detail: str = ""  # short status reason (NEVER a config value / token — threat T-02-07)

    def to_dict(self) -> dict:
        return {"name": self.name, "kind": self.kind, "present": self.present, "detail": self.detail}


@dataclass
class CapabilityReport:
    """The structured test result: per-capability status + an overall pass/fail."""

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

    def to_dict(self) -> dict:
        # names + status ONLY (T-02-07). Do not add a field here that carries container output.
        return {
            "stack": self.stack,
            "ok": self.ok,
            "results": [r.to_dict() for r in self.results],
        }


@dataclass
class LiveCapabilities:
    """What introspection actually observed in the running instance."""

    mcp: dict[str, str] = field(default_factory=dict)  # connected child server -> source label
    skills: set[str] = field(default_factory=set)
    commands: set[str] = field(default_factory=set)
    plugins: set[str] = field(default_factory=set)
    mcp_source: str = ""
    skills_source: str = ""


# --- Pure: expected-vs-live diff (oracle; no podman, unit-testable) ------------------------------
#
# The manifest→expected mapping itself lives in `schema.expected_capabilities` (reused directly by
# `run_capability_test`); `build_report` is the pure expected-vs-live diff.


def build_report(
    stack_name: str, expected: schema.Capabilities, live: LiveCapabilities
) -> CapabilityReport:
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
            # Names where to look; never quotes what is there (T-02-07, bd harnessed-rv2.2).
            detail = f"not connected (checked {checked}) — {MCP_MISS_REMEDIATION}"
        results.append(CapabilityResult(name=name, kind=MCP, present=present, detail=detail))

    for name in expected.skills:
        present = name in live.skills
        detail = (live.skills_source or "profile") if present else "skill not visible in instance"
        results.append(CapabilityResult(name=name, kind=SKILL, present=present, detail=detail))

    for name in expected.commands:
        present = name in live.commands
        detail = (live.skills_source or "profile") if present else "command not visible in instance"
        results.append(CapabilityResult(name=name, kind=COMMAND, present=present, detail=detail))

    for name in expected.plugins:
        present = name in live.plugins
        detail = "profile" if present else "plugin not visible in instance"
        results.append(CapabilityResult(name=name, kind=PLUGIN, present=present, detail=detail))

    return CapabilityReport(stack=stack_name, results=results)


# --- Pure: recipe-authored bash tests (discovery + exit-code folding; no podman) ------------------


@dataclass
class RecipeTest:
    """One discovered recipe test script (host-side; podman only touches it at run time).

    A recipe ships plain bash under `catalog/recipes/<recipe>/tests/*.sh`; exit 0 == pass. This is a
    SUPPLEMENT to `expect:` — it covers arbitrary kinds (a baked binary, a hook firing) and behavior
    (invoke + assert) that the presence-only oracle structurally cannot (main-c98).
    """

    recipe: str
    tests_dir: Path  # host path to the recipe's tests/ dir (copied whole into the instance)
    script: str  # script filename, e.g. "rtk-runs.sh"

    @property
    def name(self) -> str:
        """Stable capability name folded into the report: `<recipe>/<script>`."""
        return f"{self.recipe}/{self.script}"


def discover_recipe_tests(recipes) -> list[RecipeTest]:
    """Auto-discover every `*.sh` under each resolved recipe's `tests/` dir (pure; unit-testable).

    Convention over schema (main-c98 MVP): no `tests:` field — any `*.sh` under the dir is a test.
    `recipes` are the already-resolved `schema.Recipe`s (their `.root` points at the recipe dir
    across the catalog roots), so discovery inherits the user-overlay precedence for free.
    """
    found: list[RecipeTest] = []
    for recipe in recipes:
        tests_dir = Path(recipe.root) / "tests"
        if not tests_dir.is_dir():
            continue
        for script in sorted(tests_dir.glob("*.sh")):
            if script.is_file():
                found.append(RecipeTest(recipe=recipe.name, tests_dir=tests_dir, script=script.name))
    return found


def _test_failure_detail(exit_code: int, output: str) -> str:
    """A short, secret-safe failure reason: `exit <n>` + the last non-empty output line, truncated.

    Never echoes the full transcript (threat T-02-07) — one truncated tail line is enough to see why.
    """
    tail = ""
    for line in reversed(output.splitlines()):
        stripped = line.strip()
        if stripped:
            tail = stripped
            break
    detail = f"exit {exit_code}"
    if tail:
        detail = f"{detail}: {tail}"
    if len(detail) > _TEST_DETAIL_MAX:
        detail = detail[: _TEST_DETAIL_MAX - 1] + "…"
    return detail


def fold_test_result(
    test: RecipeTest, exit_code: int, output: str = "", *, timed_out: bool = False
) -> CapabilityResult:
    """Fold one script run into a `CapabilityResult` (kind=TEST) — pure; unit-testable.

    present iff the script exited 0 (and did not time out). A failing script therefore turns the
    whole `CapabilityReport` red through the SAME `.ok`/`.exit_code` a missing skill does — no new
    gating path. detail is a short, truncated reason (never a full transcript).
    """
    if timed_out:
        return CapabilityResult(name=test.name, kind=TEST, present=False, detail="timeout")
    present = exit_code == 0
    detail = "exit 0" if present else _test_failure_detail(exit_code, output)
    return CapabilityResult(name=test.name, kind=TEST, present=present, detail=detail)


# --- Live introspection (podman-touching; guarded behind the headless launch) --------------------


def _runtime() -> str:
    """Container runtime — matches the bash dispatcher's detect_runtime (podman, docker fallback)."""
    return os.environ.get("CONTAINER_RUNTIME") or ("podman" if shutil.which("podman") else "docker")


def _harnessed_bin(explicit: str | None = None) -> str:
    """Resolve the `harnessed` launcher (the 02-02 entry: `harnessed <stack> --fresh`)."""
    if explicit:
        return explicit
    hd = os.environ.get("HARNESSED_DIR")
    if hd:
        candidate = Path(hd) / "harnessed"
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("harnessed")
    if found:
        return found
    raise CapabilityError("cannot locate the `harnessed` launcher (set HARNESSED_DIR or PATH)")


def _exec(instance: str, script: str, *, timeout: int = 60) -> str:
    """Run a bash snippet inside the live harness member via `podman exec`; '' on failure."""
    try:
        proc = subprocess.run(
            [_runtime(), "exec", instance, "bash", "-lc", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.SubprocessError, OSError):
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout


def _cp(src: str, dest: str, *, timeout: int = 120) -> bool:
    """`podman cp <src> <dest>` — the SAME runtime family the launcher already uses to move files in
    and out of a live member (launcher.py `[rt, "cp", ...]`). Returns True on success."""
    try:
        proc = subprocess.run(
            [_runtime(), "cp", src, dest], capture_output=True, text=True, timeout=timeout
        )
    except (subprocess.SubprocessError, OSError):
        return False
    return proc.returncode == 0


def _exec_script(
    instance: str,
    remote_script: str,
    env: dict[str, str],
    *,
    workdir: str | None = None,
    timeout: int = DEFAULT_TEST_TIMEOUT,
) -> tuple[int, str, bool]:
    """Run one already-copied script via `podman exec` (thin shell) → (exit_code, output, timed_out).

    Mirrors `_exec` but preserves the exit code (the whole gate) and combined stdout+stderr (for the
    truncated failure detail). Env is passed with `-e NAME=value`; `-w` sets the working dir to the
    project bind-mount when supplied.
    """
    argv = [_runtime(), "exec"]
    for key, value in env.items():
        argv += ["-e", f"{key}={value}"]
    if workdir:
        argv += ["-w", workdir]
    argv += [instance, "bash", remote_script]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, "", True
    except (subprocess.SubprocessError, OSError) as exc:
        return 1, str(exc), False
    return proc.returncode, (proc.stdout or "") + (proc.stderr or ""), False


def run_recipe_tests(
    instance: str,
    tests: list[RecipeTest],
    *,
    stack: str,
    harness: str = "claude",
    workdir: str | None = None,
    timeout: int = DEFAULT_TEST_TIMEOUT,
) -> list[CapabilityResult]:
    """podman cp each recipe's tests/ into the live instance, exec each script, fold the exit codes.

    The ONLY podman-touching part of the tests feature — discovery (`discover_recipe_tests`) and the
    exit-code→result folding (`fold_test_result`) are pure and unit-tested without a container. Each
    script runs inside the real running instance (mounted profile, PATH, baked binaries, hatago hub),
    with the documented env contract (main-c98): HARNESSED_STACK / HARNESSED_RECIPE / HARNESSED_TEST_DIR
    / HARNESS + HATAGO_ENDPOINT / HATAGO_PORT. No credentials — the primary path stays auth-free.
    """
    results: list[CapabilityResult] = []
    if not tests:
        return results
    _exec(instance, f"mkdir -p {shlex.quote(REMOTE_TESTS_ROOT)}")
    copied: dict[str, bool] = {}
    for test in tests:
        remote_dir = f"{REMOTE_TESTS_ROOT}/{test.recipe}"
        if test.recipe not in copied:
            copied[test.recipe] = _cp(str(test.tests_dir), f"{instance}:{remote_dir}")
        if not copied[test.recipe]:
            results.append(
                CapabilityResult(name=test.name, kind=TEST, present=False, detail="podman cp failed")
            )
            continue
        env = {
            "HARNESSED_STACK": stack,
            "HARNESSED_RECIPE": test.recipe,
            "HARNESSED_TEST_DIR": remote_dir,
            "HARNESS": harness,
            "CONTAINER_HOME": CONTAINER_HOME,
            "HATAGO_ENDPOINT": HATAGO_ENDPOINT,
            "HATAGO_PORT": str(HATAGO_PORT),
        }
        exit_code, output, timed_out = _exec_script(
            instance, f"{remote_dir}/{test.script}", env, workdir=workdir, timeout=timeout
        )
        results.append(fold_test_result(test, exit_code, output, timed_out=timed_out))
    return results


def run_recipe_tests_host(
    tests: list[RecipeTest],
    *,
    env: dict[str, str],
    workdir: str | Path | None = None,
    timeout: int = DEFAULT_TEST_TIMEOUT,
) -> list[CapabilityResult]:
    """Run each discovered script on the HOST, in the environment its install just ran in.

    The host sibling of `run_recipe_tests`, and deliberately NOT a copy of it: there is no `cp`
    (`tests_dir` is already a host path) and no runtime (that is the whole point of AC-6a). `env` is
    passed in rather than rebuilt, so the test sees exactly what the install saw — `emit.install_env`
    is the single authority and a second copy here could drift from it silently.

    Never raises for a failing script: a non-zero exit is a RESULT, folded by `fold_test_result` like
    any other. The install seam decides what a failure means.
    """
    results: list[CapabilityResult] = []
    for test in tests:
        script = test.tests_dir / test.script
        try:
            proc = subprocess.run(
                ["bash", str(script)],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(workdir) if workdir is not None else None,
                env=env,
            )
        except subprocess.TimeoutExpired:
            results.append(fold_test_result(test, 124, "", timed_out=True))
            continue
        except (subprocess.SubprocessError, OSError) as exc:
            # An unreadable or missing script is a FAILED test, not a crashed launch — the recipe
            # is what is broken, and the message has to say which recipe.
            results.append(fold_test_result(test, 1, str(exc)))
            continue
        results.append(
            fold_test_result(test, proc.returncode, (proc.stdout or "") + (proc.stderr or ""))
        )
    return results


def first_failed_test(results: list[CapabilityResult]) -> CapabilityResult | None:
    """The first non-passing result, or None. Both install seams gate on this same answer."""
    for result in results:
        if not result.present:
            return result
    return None


def launch_headless(
    root: Path | str,
    stack_name: str,
    harness: str,
    *,
    project_path: str | None = None,
    harnessed_bin: str | None = None,
) -> str:
    """Launch the stack `--fresh` HEADLESS via the 02-02 launcher; return the live instance name.

    Sets `HARNESSED_HEADLESS=true` so the launcher composes + starts the pod WITHOUT the interactive
    claude attach (members stay up for `podman exec`). The instance/pod name is host-derived via
    `paths.instance_name` — the SAME derivation the launcher uses (stack + sha1[:8] of the resolved
    project path) — so the oracle never depends on scraping the launcher's stdout (T-02 fragility).
    """
    bin_path = _harnessed_bin(harnessed_bin)
    if project_path is None:
        # No caller-supplied project: make a scratch dir. The CALLER owns its lifetime — it is the
        # pod's project bind-mount and MUST persist until teardown. Deleting it while the pod runs
        # breaks `podman exec` (crun getcwd EPERM). run_capability_test manages cleanup after
        # teardown; direct callers must do the same.
        project_path = tempfile.mkdtemp(prefix=f"harnessed-test-{stack_name}-")

    env = {**os.environ, "HARNESSED_HEADLESS": "true"}
    try:
        proc = subprocess.run(
            # `container-run <harness> <path> --stack <name>`, the current grammar. The bare
            # `harnessed <stack> <harness> <path>` form this used to invoke stopped existing when
            # the CLI split into the two run verbs, and typer rejected it as `No such command
            # '<stack>'` — so EVERY container-path `harnessed test` failed, not just the tests
            # that call this directly. Nothing caught it because the only callers are the
            # podman-gated layer that was never running (bd harnessed-1o4, harnessed-3x1).
            [bin_path, "container-run", harness, project_path, "--stack", stack_name, "--fresh"],
            capture_output=True,
            text=True,
            env=env,
            timeout=600,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise CapabilityError(f"headless launch failed to start: {exc}") from exc

    if proc.returncode != 0:
        combined = f"{proc.stdout}\n{proc.stderr}".strip()
        raise CapabilityError(
            "headless launch did not report a running instance "
            f"(exit {proc.returncode}); output:\n{combined}"
        )
    # Host-derive the pod name instead of scraping stdout: instance_name is a pure function of the
    # stack + harness + resolved project path, the SAME inputs the launcher hashes — so the two can't drift.
    return paths.instance_name(stack_name, harness, Path(project_path).resolve())


def teardown(instance: str, *, harnessed_bin: str | None = None) -> None:
    """Tear the instance down after the test (`--fresh` semantics; no state bleed, T-02-08).

    Provider-neutral: podman groups the members in a pod (`pod rm -f` removes the instance);
    docker has no pod, so the single flat container is force-removed directly. After
    hatago-consolidation hatago runs in-container, so there is no separate `<instance>-hatago`.
    """
    runtime = _runtime()
    cmd = (
        [runtime, "pod", "rm", "-f", instance]
        if runtime == "podman"
        else [runtime, "rm", "-f", instance]
    )
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (subprocess.SubprocessError, OSError):
        pass


def wait_ready(instance: str, *, port: int = HATAGO_PORT, timeout: int = 60) -> bool:
    """Poll until the harness member is exec-ready AND hatago's HTTP port is bound.

    hatago needs a few seconds to boot and connect its stdio children before it binds
    :<port>; introspecting before then yields false negatives (the MCP probe finds nothing
    and the filesystem skill probe can race a not-yet-exec-ready member). Returns True once a
    TCP connect to 127.0.0.1:<port> from inside the pod succeeds, False on timeout.
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


# --- Harness-aware backstops (plan 04-03 / HRN-01) ----------------------------------------------
#
# The PRIMARY checks (hatago `hatago://servers` resource + mounted-profile filesystem listing)
# are harness-INDEPENDENT and unchanged. Only the LLM backstop command differs: an omp stack is
# introspected via `omp -p --mode json` instead of `claude -p --output-format json`. The same
# profile (Claude-canonical, design §8) backs both — omp consumes it via the bridge.


def _llm_cmd(harness: str, prompt: str) -> list[str]:
    """The headless LLM-backstop argv for a harness (plan 04-03 / HRN-02..HRN-05).

    claude      → claude -p <prompt> --output-format json
    omp         → omp    -p <prompt> --mode json
    opencode    → opencode run <prompt> --format json
    antigravity → agy    -p <prompt>
    codex       → codex exec <prompt>

    The PRIMARY MCP/skill checks do not use this — only the fallback when the machine-readable
    sources are empty. Callers append harness-specific isolation flags (claude: --mcp-config +
    --strict-mcp-config; omp: --profile; opencode/antigravity/codex: none — each reads its
    own image-baked MCP config) before rendering to a bash snippet for `_exec`.
    """
    if harness == "omp":
        return ["omp", "-p", prompt, "--mode", "json"]
    if harness == "opencode":
        return ["opencode", "run", prompt, "--format", "json"]
    if harness == "antigravity":
        return ["agy", "-p", prompt]
    if harness == "codex":
        return ["codex", "exec", prompt]
    return ["claude", "-p", prompt, "--output-format", "json"]


def _llm_cmd_str(argv: list[str]) -> str:
    """Render an LLM-backstop argv as a single bash-safe snippet for `_exec` (shlex-quoted)."""
    return " ".join(shlex.quote(a) for a in argv)


# --- MCP introspection: hatago resource (primary) → claude mcp list → LLM backstop ---------------


def _sse_to_objects(payload: str):
    """Yield JSON objects from a Streamable-HTTP response (raw JSON or SSE `data:` frames)."""
    payload = payload.strip()
    if not payload:
        return
    saw_frame = False
    for line in payload.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            saw_frame = True
            body = line[len("data:") :].strip()
            if not body or body == "[DONE]":
                continue
            try:
                yield json.loads(body)
            except json.JSONDecodeError:
                continue
    if not saw_frame:
        try:
            yield json.loads(payload)
        except json.JSONDecodeError:
            return


def _collect_server_names(node, out: dict[str, str]) -> None:
    """Walk an arbitrary hatago `servers` payload, collecting `{name: status}` for each entry.

    Tolerant of hatago schema drift: any dict carrying a `name` is treated as a server entry; a
    server counts as connected unless an explicit status/connected field says otherwise.
    """
    if isinstance(node, dict):
        name = node.get("name") or node.get("id")
        if isinstance(name, str) and name:
            status = node.get("status") or node.get("state") or node.get("connectionState")
            connected = node.get("connected")
            ok = True
            if isinstance(connected, bool):
                ok = connected
            elif isinstance(status, str):
                ok = status.lower() in {"connected", "ready", "ok", "running", "active", "online"}
            if ok:
                out[name] = str(status) if isinstance(status, str) and status else "connected"
        for value in node.values():
            _collect_server_names(value, out)
    elif isinstance(node, list):
        for item in node:
            _collect_server_names(item, out)


def _mcp_from_hatago(instance: str) -> dict[str, str]:
    """Primary: read hatago's `hatago://servers` resource over Streamable HTTP (connected children)."""
    script = (
        "set -e; EP=" + HATAGO_ENDPOINT + "; HDRS=$(mktemp); "
        'ACC="application/json, text/event-stream"; '
        'curl -s -D "$HDRS" -H "Content-Type: application/json" -H "Accept: $ACC" '
        '-d \'{"jsonrpc":"2.0","id":1,"method":"initialize","params":'
        '{"protocolVersion":"2025-06-18","capabilities":{},'
        '"clientInfo":{"name":"harnessed-capability-test","version":"0"}}}\' "$EP" >/dev/null; '
        'SID=$(grep -i "^mcp-session-id:" "$HDRS" | sed "s/.*: *//; s/\\r//"); '
        'curl -s -H "Content-Type: application/json" -H "Accept: $ACC" '
        '${SID:+-H "Mcp-Session-Id: $SID"} '
        '-d \'{"jsonrpc":"2.0","method":"notifications/initialized"}\' "$EP" >/dev/null || true; '
        'curl -s -H "Content-Type: application/json" -H "Accept: $ACC" '
        '${SID:+-H "Mcp-Session-Id: $SID"} '
        '-d \'{"jsonrpc":"2.0","id":2,"method":"resources/read","params":'
        '{"uri":"' + HATAGO_SERVERS_URI + '"}}\' "$EP"'
    )
    raw = _exec(instance, script)
    if not raw:
        return {}
    found: dict[str, str] = {}
    for obj in _sse_to_objects(raw):
        result = obj.get("result") if isinstance(obj, dict) else None
        if not isinstance(result, dict):
            continue
        # resources/read → { contents: [ { text: "<json>" }, ... ] }
        for content in result.get("contents", []) or []:
            text = content.get("text") if isinstance(content, dict) else None
            if not isinstance(text, str):
                continue
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                continue
            _collect_server_names(parsed, found)
    return found


def _mcp_from_llm(instance: str, harness: str = "claude") -> dict[str, str]:
    """Backstop: ask the harness (headless, isolated MCP config) for connected MCP servers.

    claude uses the SAME `--mcp-config <profile .mcp.json> --strict-mcp-config` the launcher uses,
    so the view matches the real isolated session (hatago only; no host/project/account-synced
    servers). omp has no `mcp list` parity — it is probed via `omp -p --mode json --profile`.
    opencode reads its baked ~/.config/opencode MCP config (hatago only), so no extra flags. The
    hatago resource is the authoritative MCP source either way; this is the rare fallback.
    """
    prompt = (
        "List the MCP servers currently connected (including any provided through the hatago hub). "
        'Respond with ONLY a JSON array of server name strings, e.g. ["time"]. No prose.'
    )
    argv = _llm_cmd(harness, prompt)
    if harness == "omp":
        argv += ["--profile", instance]
    elif harness == "claude":
        argv += ["--mcp-config", f"{CONTAINER_HOME}/.claude/.mcp.json", "--strict-mcp-config"]
    # opencode/antigravity/codex: no isolation flags — each reads its own image-baked MCP config.
    raw = _exec(instance, _llm_cmd_str(argv), timeout=180)
    names = _names_from_llm_json(raw)
    return {name: "connected (llm backstop)" for name in names}


def _names_from_llm_json(raw: str) -> set[str]:
    """Extract a JSON array of names from a `claude -p --output-format json` envelope."""
    if not raw:
        return set()
    text = raw
    try:
        envelope = json.loads(raw)
        if isinstance(envelope, dict) and isinstance(envelope.get("result"), str):
            text = envelope["result"]
    except json.JSONDecodeError:
        pass
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return set()
    try:
        arr = json.loads(match.group(0))
    except json.JSONDecodeError:
        return set()
    return {str(item) for item in arr if isinstance(item, (str,))}


def introspect_mcp(
    instance: str,
    harness: str = "claude",
    *,
    expect: Collection[str] = (),
    timeout: float = MCP_CONNECT_TIMEOUT,
) -> tuple[dict[str, str], str]:
    """Return ({connected server -> status}, source-label), preferring machine-readable sources.

    hatago's `hatago://servers` resource is the machine-readable primary (auth-free; lists the
    connected child servers) and is harness-INDEPENDENT. `claude mcp list` / `omp` parity is
    intentionally NOT the primary — the hatago resource is authoritative. The harness-specific
    headless LLM probe (`_mcp_from_llm`) is the backstop; `harness` only routes that fallback.

    `expect` is the set of server names the manifest declares, and it turns this from a single-shot
    read into a deadline poll. `wait_ready` returns as soon as hatago's OWN port accepts a
    connection — it does not wait for the stdio children hatago spawns to finish connecting, and
    that gap was measured at 0.3s on a warm box. A single read into that gap reports a perfectly
    healthy server as `not connected`, which is what `live.yml` did for every MCP-bearing stack
    (bd harnessed-rv2.2). Polling until the declared names appear removes the race instead of
    winning it by luck.

    With no `expect` there is nothing to wait FOR, so the read stays single-shot and a stack that
    declares no MCP servers — most of them — pays no latency for this.
    """
    expected = set(expect)
    servers = _mcp_from_hatago(instance)
    # The deadline starts AFTER the first probe, deliberately. `_exec` carries its own subprocess
    # timeout of the same order as this one, so a `podman exec` that hangs would otherwise consume
    # the whole window before the loop is entered even once — zero retries, silently, on exactly the
    # cold/slow runner where the children are also slow to connect (bd harnessed-rv2.2). Bounds the
    # call at roughly 2x `timeout` instead of 1x; across the MCP-declaring stacks that is a few
    # minutes against live.yml's 60, and it is only ever paid on a run that is already failing.
    deadline = time.monotonic() + timeout
    while expected and not expected <= servers.keys():
        # The deadline bounds when a probe may START, not merely when a sleep may end. `_exec` shells
        # into the container with its own subprocess timeout, so a probe begun AT the deadline can run
        # for another 60s entirely outside the caller's budget. Stopping when the next interval would
        # reach the deadline covers both halves at once — no probe after it, and no sleep past it
        # (CodeRabbit, two rounds: the first fix stopped the oversleep but kept the late probe).
        if time.monotonic() + MCP_POLL_INTERVAL >= deadline:
            break
        time.sleep(MCP_POLL_INTERVAL)
        servers = _mcp_from_hatago(instance)
    if servers:
        # Deliberately returned even when INCOMPLETE: `build_report` marks the absent names
        # individually, which says more than discarding a partial answer and asking the LLM.
        return servers, HATAGO_SERVERS_URI
    servers = _mcp_from_llm(instance, harness)
    if servers:
        return servers, f"{harness} -p (strict isolated config)"
    return {}, HATAGO_SERVERS_URI


# --- Skill / command introspection: mounted profile filesystem → headless JSON backstop ----------


def _fileext_from_filesystem(instance: str, subdir: str) -> set[str]:
    """List visible extension names under ~/.claude/<subdir> from the running instance.

    Skills/plugins are directories (name == dir). Commands may be `<name>.md` files OR dirs, so the
    `.md` suffix is stripped to recover the command name the manifest/oracle uses.
    """
    raw = _exec(
        instance,
        f'ls -1 {CONTAINER_HOME}/.claude/{subdir} 2>/dev/null || true',
    )
    names = {line.strip() for line in raw.splitlines() if line.strip()}
    if subdir == "commands":
        names = {n[:-3] if n.endswith(".md") else n for n in names}
    return names


def _skills_from_llm(instance: str, harness: str = "claude") -> set[str]:
    """Backstop: ask the harness, headless, to emit the skills it sees as a JSON array."""
    prompt = (
        "List the skills currently available to you. "
        'Respond with ONLY a JSON array of skill name strings, e.g. ["time-helper"]. No prose.'
    )
    raw = _exec(instance, _llm_cmd_str(_llm_cmd(harness, prompt)), timeout=180)
    return _names_from_llm_json(raw)


def introspect(
    instance: str, harness: str = "claude", *, expect_mcp: Collection[str] = (),
) -> LiveCapabilities:
    """Gather the live instance's actual capabilities (MCP + skills + commands).

    `harness` only routes the LLM fallback (`_mcp_from_llm`/`_skills_from_llm`); the primary
    checks — hatago's `hatago://servers` resource and the mounted-profile filesystem listing —
    are harness-independent (plan 04-03). Defaults to claude so the historical call path is intact.

    `expect_mcp` is the manifest's declared server set, forwarded to `introspect_mcp` so it can wait
    for late-connecting hatago children instead of racing them (bd harnessed-rv2.2).
    """
    mcp, mcp_source = introspect_mcp(instance, harness, expect=expect_mcp)

    skills = _fileext_from_filesystem(instance, "skills")
    skills_source = "mounted profile filesystem"
    if not skills:
        skills = _skills_from_llm(instance, harness)
        skills_source = f"{harness} -p (llm backstop)"

    commands = _fileext_from_filesystem(instance, "commands")
    plugins = _fileext_from_filesystem(instance, "plugins")

    return LiveCapabilities(
        mcp=mcp,
        skills=skills,
        commands=commands,
        plugins=plugins,
        mcp_source=mcp_source,
        skills_source=skills_source,
    )


def run_capability_test(
    root: Path | str,
    stack_name: str,
    harness: str,
    *,
    project_path: str | None = None,
    harnessed_bin: str | None = None,
    keep: bool = False,
    run_tests: bool = True,
) -> CapabilityReport:
    """Full test: manifest oracle → launch --fresh headless → introspect → recipe tests → diff.

    Returns the single structured `CapabilityReport` that drives both the report and the exit code.
    When `run_tests` (default), recipe-authored `tests/*.sh` are copied into the live instance and
    executed after introspection; each exit code folds into the SAME report as a TEST result, so a
    failing script goes red through the existing `.ok`/`.exit_code`. `--no-tests` sets it False.
    """
    stack, recipes = schema.load_stack_with_recipes(None, stack_name)
    expected = schema.expected_capabilities(stack, recipes)

    # Own the scratch project dir for the WHOLE test: it is the pod's project bind-mount and must
    # outlive launch→introspect→teardown (deleting it mid-run breaks `podman exec`). A caller-
    # supplied project_path is left untouched.
    own_project = project_path is None
    if own_project:
        project_path = tempfile.mkdtemp(prefix=f"harnessed-test-{stack_name}-")
    test_results: list[CapabilityResult] = []
    try:
        instance = launch_headless(
            root, stack_name, harness, project_path=project_path, harnessed_bin=harnessed_bin
        )
        try:
            wait_ready(instance)
            live = introspect(instance, harness, expect_mcp=expected.mcp_servers)
            if run_tests:
                test_results = run_recipe_tests(
                    instance,
                    discover_recipe_tests(recipes),
                    stack=stack_name,
                    harness=harness,
                    workdir=project_path,
                )
        finally:
            if not keep:
                teardown(instance, harnessed_bin=harnessed_bin)
    finally:
        if own_project and not keep:
            shutil.rmtree(project_path, ignore_errors=True)
    report = build_report(stack_name, expected, live)
    report.results.extend(test_results)
    return report
