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

The pure manifest→expected mapping (`expected_capabilities`) and the pure expected-vs-live diff
(`build_report`) take no podman and are unit-testable; the live-introspection functions
(`launch_headless`, `introspect`, `teardown`, `run_capability_test`) are the only podman-touching
code and are guarded behind the launch.
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
from dataclasses import dataclass, field
from pathlib import Path

from . import paths, schema

# Capability kinds (stable strings — used by report.py + --json consumers).
MCP = "mcp"
SKILL = "skill"
COMMAND = "command"
PLUGIN = "plugin"

# hatago's single Streamable-HTTP endpoint inside the shared pod netns (design D-04). Single
# source: `paths.hatago_endpoint()` (honors the `HATAGO_PORT` env override).
HATAGO_ENDPOINT = paths.hatago_endpoint()
# The hub's connected-servers resource (the JSON snapshot of child servers behind hatago).
HATAGO_SERVERS_URI = "hatago://servers"
# In-container harness home → the mounted profile lives at $CONTAINER_HOME/.claude (launcher §4b).
CONTAINER_HOME = os.environ.get("CONTAINER_HOME", "/home/harnessed")
# hatago's HTTP port inside the pod (the readiness signal: bound ⇒ children connected).
HATAGO_PORT = paths.hatago_port()


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


# --- Pure: manifest -> expected capability set (oracle; no podman, unit-testable) ----------------


def expected_capabilities(root: Path | str, stack_name: str) -> schema.Capabilities:
    """Derive the EXPECTED capabilities from the manifest oracle (reuses 02-01's schema API).

    Resolves the stack + recipes across the catalog roots (repo catalog/ + user overlay; `root`
    selects the repo via HARNESSED_DIR). Touches no container runtime.
    """
    stack, recipes = schema.load_stack_with_recipes(None, stack_name)
    return schema.expected_capabilities(stack, recipes)


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
            detail = f"not connected (checked {checked})"
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


def launch_headless(
    root: Path | str,
    stack_name: str,
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
            [bin_path, stack_name, project_path, "--fresh"],
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
    # stack + resolved project path, the SAME inputs the launcher hashes — so the two can't drift.
    return paths.instance_name(stack_name, Path(project_path).resolve())


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


def _harness_of(root: Path | str, stack_name: str) -> str:
    """Read the stack's harness from its manifest (default 'claude' on any read failure).

    The capability test branches the LLM backstop on this: omp stacks use omp -p --mode json.
    A missing/malformed manifest falls back to claude (the historical default) so the harness-
    independent primary checks still run.
    """
    try:
        stack = schema.load_stack(paths.find_in_catalog("stacks", stack_name))
    except schema.SchemaError:
        return "claude"
    return stack.harness or "claude"


def _llm_cmd(harness: str, prompt: str) -> list[str]:
    """The headless LLM-backstop argv for a harness (plan 04-03 / HRN-02..HRN-05).

    claude      → claude -p <prompt> --output-format json
    omp         → omp    -p <prompt> --mode json
    opencode    → opencode run <prompt> --format json
    gemini      → gemini -p <prompt> --output-format json
    antigravity → agy    -p <prompt>
    codex       → codex exec <prompt>

    The PRIMARY MCP/skill checks do not use this — only the fallback when the machine-readable
    sources are empty. Callers append harness-specific isolation flags (claude: --mcp-config +
    --strict-mcp-config; omp: --profile; opencode/gemini/antigravity/codex: none — each reads its
    own image-baked MCP config) before rendering to a bash snippet for `_exec`.
    """
    if harness == "omp":
        return ["omp", "-p", prompt, "--mode", "json"]
    if harness == "opencode":
        return ["opencode", "run", prompt, "--format", "json"]
    if harness == "gemini":
        return ["gemini", "-p", prompt, "--output-format", "json"]
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
    # opencode/gemini/antigravity/codex: no isolation flags — each reads its own image-baked MCP config.
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


def introspect(instance: str, harness: str = "claude") -> LiveCapabilities:
    """Gather the live instance's actual capabilities (MCP + skills + commands).

    `harness` only routes the LLM fallback (`_mcp_from_llm`/`_skills_from_llm`); the primary
    checks — hatago's `hatago://servers` resource and the mounted-profile filesystem listing —
    are harness-independent (plan 04-03). Defaults to claude so the historical call path is intact.
    """
    mcp, mcp_source = introspect_mcp(instance, harness)

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
    *,
    project_path: str | None = None,
    harnessed_bin: str | None = None,
    keep: bool = False,
) -> CapabilityReport:
    """Full test: manifest oracle → launch --fresh headless → introspect → diff → teardown.

    Returns the single structured `CapabilityReport` that drives both the report and the exit code.
    """
    expected = expected_capabilities(root, stack_name)
    # Harness-aware backstop (plan 04-03): route the LLM fallback on stack.harness. The primary
    # hatago/filesystem checks run unchanged regardless of harness.
    harness = _harness_of(root, stack_name)

    # Own the scratch project dir for the WHOLE test: it is the pod's project bind-mount and must
    # outlive launch→introspect→teardown (deleting it mid-run breaks `podman exec`). A caller-
    # supplied project_path is left untouched.
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
