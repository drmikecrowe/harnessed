"""Mirror harnessed launches into Agent of Empires (`aoe`) for users who run it.

aoe is an OPTIONAL tmux session coordinator. harnessed neither requires nor installs it; this
module is the one-way bridge that keeps aoe's dashboard in sync for the users who do have it.
Nothing here may ever fail a launch — aoe being absent, broken, slow, or a version that renamed a
flag must all degrade to silence. Hence: every subprocess call is timeout-bounded, `check=False`,
and wrapped; every public entry point swallows.

REGISTER-ONLY, deliberately. harnessed still owns the process: `launch` ends in an `os.execvp` that
hands YOUR terminal to the agent (via `podman exec -it` on the container backend, directly on the
host backend). We record a session so it appears in the dashboard and can be re-started or attached
from there later — we never hand the launch over to aoe. That is also why sessions must stay in
aoe's terminal (raw tmux/PTY) view: its structured view drives an agent over ACP rather than through
a PTY, which cannot reach through a `podman exec` attach. `aoe add` already defaults to the terminal
view, so we pass NOTHING for it — an explicit opt-out flag would be an unknown argument (see below).

PASS ONLY FLAGS `aoe add` ACCEPTS. It is a clap CLI: an unrecognised flag is not ignored, it exits 2
before adding anything. On the background path that is invisible — the detached writer dies and the
dashboard just stays empty. Verified against aoe 1.13.2; `--no-cockpit` was such a flag, and it
silently cost every registration until `--create-aoe-only` surfaced it.

Session identity is (project path, stack, harness) — NOT (project path, stack). A stack has a
separately assembled profile per harness (`profiles/<stack>/<harness>/`), so the claude and omp
variants of one recipe set are two different things to run and two different rows. All three
components are encoded in the recorded command, which is what we match on; titles stay purely
cosmetic so a user renaming a row cannot break identity.

READS ARE SYNCHRONOUS, WRITES ARE NOT. Measured against aoe on 2026-08-01: `list --json`,
`group list` and `profile list` all return in ~0.01s, but `aoe add` takes ~12s (it brings the
daemon up). Blocking a launch for twelve seconds to populate a dashboard is not a trade worth
making, so the reads that decide *whether* to write happen inline and the writes are fired into a
detached process that outlives the `os.execvp`. The one exception is `--create-aoe-only`, where
registering IS the command the user ran and they are entitled to its exit status.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess

from pathlib import Path

from . import paths

# The dedicated aoe workspace. Everything this module does is scoped to it, so a user's own
# sessions in `default` are never touched, reordered, or removed.
PROFILE = "harnessed"

# aoe's own config lives here. Its presence is the second half of the "user actually runs aoe"
# test: `aoe` on PATH alone can mean a stray binary that was never set up.
_CONFIG_DIRNAME = "agent-of-empires"

# `default` is the baseline every dynamic stack extends. It is not a thing the user composed, so a
# row for it is noise in a dashboard whose whole point is showing the stacks they built.
_SKIP_STACKS = frozenset({"default"})

# Reads are ~0.01s; this only has to be long enough that a cold page-in is not mistaken for a hang.
_READ_TIMEOUT = 10

# Writes are ~12s when aoe has to start its daemon. Only ever used on the blocking
# `--create-aoe-only` path, where the user is explicitly waiting for the write.
_WRITE_TIMEOUT = 120

# `• name (3 sessions)` — aoe renders groups as a bullet list with no --json equivalent.
_GROUP_LINE = re.compile(r"^\s*[•*-]\s+(\S+)\s+\(")


def _bin() -> str | None:
    """Path to a usable `aoe`, or None when the integration must stay silent.

    `HARNESSED_NO_AOE` is the escape hatch for someone who has aoe installed but does not want
    harnessed touching it.
    """
    if os.environ.get("HARNESSED_NO_AOE", "").strip():
        return None
    exe = shutil.which("aoe")
    if exe is None:
        return None
    if not (paths.xdg_config_home() / _CONFIG_DIRNAME).is_dir():
        return None
    return exe


def _run(exe: str, args: list[str], *, timeout: int = _READ_TIMEOUT) -> subprocess.CompletedProcess[str] | None:
    """Run one aoe subcommand and wait. Returns None if it could not be run at all."""
    try:
        return subprocess.run(
            [exe, *args], capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _spawn(exe: str, batch: list[list[str]]) -> bool:
    """Fire a sequence of aoe writes into a detached process and return immediately.

    `start_new_session` puts the child in its own session so it survives the `os.execvp` that
    replaces harnessed moments later — without it, the slow `aoe add` would be killed mid-write.
    Sequenced through one `sh -c` because the writes are ordered: the profile must exist before the
    group, and the group before the session. Output goes nowhere; a detached child has no terminal
    to write to and its failures are not the launch's problem.

    JOINED WITH `;`, NOT `&&` — deliberately, and it looks like a bug until you check the exit
    codes. Both `aoe profile create` and `aoe group create` exit 1 when the thing already exists
    (verified 2026-08-01). The reads that build this batch are not atomic with it, so two launches
    starting together can both observe a missing profile and both try to create it. Under `&&` the
    loser's chain aborts on that benign "already exists" and its session is never added; under `;`
    it proceeds and registers correctly. The failure mode `&&` would guard against — aoe being
    down — already produces no row either way.
    """
    if not batch:
        return True
    script = "; ".join(shlex.join([exe, *args]) for args in batch)
    try:
        subprocess.Popen(
            ["sh", "-c", script],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def _apply(exe: str, batch: list[list[str]], *, background: bool) -> bool:
    """Execute a write batch, detached or blocking. True when every write is believed to have run."""
    if background:
        return _spawn(exe, batch)
    for args in batch:
        result = _run(exe, args, timeout=_WRITE_TIMEOUT)
        if result is None or result.returncode != 0:
            return False
    return True


def command_for(verb: str, stack: str, harness: str, project_path: Path) -> str:
    """The harnessed invocation recorded on the session — both the identity key and what aoe runs.

    Always the RESOLVED stack name and an absolute path, never the user's original argv. A dynamic
    stack is minted into the generated catalog root before this is called, so `harnessed launch
    <derived-name>` replays it exactly and keeps one canonical form for every verb that reaches
    here.

    TERMINATED WITH `--`, which is not cosmetic. aoe's `auto_resume_on_restart` appends the recorded
    tool's resume flags to this string when a stopped session is restarted — for `tool = claude`,
    `--resume <id>` / `--fork-session --session-id <uuid>`. `--cmd-override` replaces the binary but
    does NOT change the recorded tool, so those claude flags get appended to OUR command and
    harnessed's Click CLI rejects them outright: `No such option: --session-id`. It bites on restart
    only, which is why the first launch of a row looks fine. The trailing `--` puts them past
    harnessed's own option parsing (`launcher._extract_passthrough`), which forwards everything after
    it to the agent — the process they were meant for. Verified against aoe 1.13.2.
    """
    return shlex.join(["harnessed", verb, stack, harness, str(project_path), "--"])


def title_for(verb: str, stack: str, harness: str, project_path: Path) -> str:
    """The dashboard label — and, unavoidably, half of aoe's own uniqueness key.

    aoe deduplicates an `add` on (title, path): a second session with both the same is refused with
    "Session already exists with same title and path" and exit status ZERO, so a collision does not
    surface as an error, it surfaces as a row that never appeared. The title must therefore be
    injective over everything WE treat as identity, which includes the backend — a stack running
    host-native and the same stack in a container are two different sessions that share a path,
    stack and harness, and differ only in the verb.

    Observed against aoe 2026-08-01: with the backend omitted, `host-run` registrations silently
    vanished behind their `launch` twin.
    """
    backend = "host" if verb == "host-run" else "container"
    return f"{project_path.name} [{harness}/{backend}] {stack}"


def _group_for(project_path: Path) -> str:
    """The git repo the project belongs to — the group name.

    Keyed on the git COMMON dir, so every worktree of one checkout lands in the same group rather
    than each spawning a group of its own. `<repo>/.git` and a bare `<repo>/.bare` both yield
    `<repo>`. Falls back to the folder name when the path is not in a git repo at all.
    """
    common = paths.git_common_dir(project_path)
    return common.parent.name if common is not None else project_path.name


def _has_profile(exe: str) -> bool:
    result = _run(exe, ["profile", "list"])
    if result is None:
        return False
    return bool(re.search(rf"^\s*\*?\s*{re.escape(PROFILE)}\b", result.stdout, re.M))


def _has_group(exe: str, group: str) -> bool:
    result = _run(exe, ["group", "list", "-p", PROFILE])
    if result is None:
        return False
    return group in {m.group(1) for m in (_GROUP_LINE.match(ln) for ln in result.stdout.splitlines()) if m}


def _sessions(exe: str) -> list[dict]:
    """Every session in the harnessed profile. Empty on any parse or transport failure.

    aoe prints a human "No sessions found" line rather than `[]` for an empty profile, so a decode
    failure is an ordinary outcome here, not an anomaly.
    """
    result = _run(exe, ["list", "--json", "-p", PROFILE])
    if result is None or result.returncode != 0:
        return []
    try:
        data = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return []
    return [s for s in data if isinstance(s, dict)] if isinstance(data, list) else []


def _registered(exe: str, command: str, project_path: Path) -> bool:
    """Whether this exact (path, stack, harness, verb) already has a row."""
    for session in _sessions(exe):
        if session.get("command") != command:
            continue
        recorded = session.get("path")
        # Compare resolved paths, not strings: aoe stores whatever it was given, and a session
        # added through a symlinked route would otherwise register a second time.
        if recorded and Path(recorded).resolve() == project_path:
            return True
    return False


def sync_session(
    verb: str, stack: str, harness: str, project_path: Path, *, background: bool = True
) -> bool:
    """Register this launch with aoe, creating the profile and repo group on the way.

    Idempotent by (path, command): relaunching the same stack+harness in the same folder finds the
    existing row instead of stacking duplicates. Never raises.

    Returns True when the row exists or its creation was dispatched, False when aoe is unavailable
    or a blocking write failed. Callers on the passive mirror path ignore this; `--create-aoe-only`
    reports it.
    """
    try:
        if stack in _SKIP_STACKS:
            return False
        exe = _bin()
        if exe is None:
            return False

        # Canonicalize once: the resolved path is both what we record and what we compare against,
        # so two routes to the same directory cannot register two rows.
        project_path = Path(project_path).resolve()
        command = command_for(verb, stack, harness, project_path)
        if _registered(exe, command, project_path):
            return True

        batch: list[list[str]] = []
        if not _has_profile(exe):
            batch.append(["profile", "create", PROFILE])
        group = _group_for(project_path)
        if not _has_group(exe, group):
            batch.append(["group", "create", group, "-p", PROFILE])
        batch.append([
            "add", str(project_path),
            "-p", PROFILE,
            "-g", group,
            "-t", title_for(verb, stack, harness, project_path),
            # `--cmd-override`, NOT `--cmd`. `--cmd` is validated against aoe's own tool list and
            # SILENTLY substitutes the configured default for anything it does not recognise, so a
            # harnessed invocation came back stored as `claude-with-env` — losing both the replay
            # and the identity key. `--cmd-override` stores the string verbatim, and also accepts
            # harnesses aoe has no notion of, like `omp`. Verified against aoe 2026-08-01.
            "--cmd-override", command,
            # No view flag: `aoe add` already defaults to the terminal (raw tmux/PTY) view, which is
            # the one we need — `--structured-view` would drive the agent over ACP, which cannot
            # reach through a `podman exec` attach. There is no flag to request the default, and an
            # invented one (`--no-cockpit`) exits 2 and loses the whole registration.
        ])
        return _apply(exe, batch, background=background)
    except Exception:  # noqa: BLE001 — an optional dashboard must never break a launch.
        return False


def forget_stack(verb: str, stack: str, *, background: bool = True) -> None:
    """Drop the sessions for a stack after its instances are torn down. Never raises.

    Scoped to ONE verb because `harnessed rm` is container-scoped: it removes every container
    instance of a stack across harnesses and projects, and leaves host-native sessions — which own
    no container — alone. Removing by session id, not title, so a user-renamed row still matches.
    """
    try:
        exe = _bin()
        if exe is None:
            return
        prefix = ["harnessed", verb, stack]
        batch: list[list[str]] = []
        for session in _sessions(exe):
            try:
                tokens = shlex.split(session.get("command") or "")
            except ValueError:
                continue
            if tokens[:3] != prefix:
                continue
            sid = session.get("id")
            if sid:
                batch.append(["remove", str(sid), "-p", PROFILE])
        _apply(exe, batch, background=background)
    except Exception:  # noqa: BLE001 — cleanup is best-effort, same as registration.
        return
