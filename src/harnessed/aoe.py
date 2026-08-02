"""Mirror harnessed launches into Agent of Empires (`aoe`) for users who run it.

aoe is an OPTIONAL tmux session coordinator. harnessed neither requires nor installs it; this
module is the one-way bridge that keeps aoe's dashboard in sync for the users who do have it.
Nothing here may ever fail a launch — aoe being absent, broken, slow, or a version that renamed a
flag must all degrade to silence. Hence: every subprocess call is timeout-bounded, `check=False`,
and wrapped; every public entry point swallows.

REGISTER-ONLY, deliberately. harnessed still owns the process: a run verb ends in an `os.execvp` that
hands YOUR terminal to the agent (via `podman exec -it` on the container backend, directly on the
host backend). We record a session so it appears in the dashboard and can be re-started or attached
from there later — we never hand the launch over to aoe. That is also why sessions must stay in
aoe's terminal (raw tmux/PTY) view: its structured view drives an agent over ACP rather than through
a PTY, which cannot reach through a `podman exec` attach. `aoe add` already defaults to the terminal
view, so we pass NOTHING for it — an explicit opt-out flag would be an unknown argument (see below).

PASS ONLY FLAGS `aoe add` ACCEPTS. It is a clap CLI: an unrecognised flag is not ignored, it exits 2
before adding anything. On the background path that is invisible — the detached writer dies and the
dashboard just stays empty. Verified against aoe 1.13.2; `--no-cockpit` was such a flag, and it
silently cost every registration until `--create-aoe-only` surfaced it. The one deliberate exception
is `--tool`, whose VALUE aoe validates and may reject; it is issued with a plain retry behind it so a
rejection costs the label rather than the row. See `sync_session`.

Session identity is (project path, stack, harness) — NOT (project path, stack). A stack has a
separately assembled profile per harness (`profiles/<stack>/<harness>/`), so the claude and omp
variants of one recipe set are two different things to run and two different rows. All three
components are encoded in the recorded command, which is what we match on; titles stay purely
cosmetic so a user renaming a row cannot break identity.

UNLESS THE USER NAMES THE ROW. `--aoe-group` and `--aoe-title` (see `sync_session`) override the
derived group and title, and supplying BOTH also replaces the identity key: the row is matched on
(group, title) instead of the recorded command. That is the only way to adopt a row harnessed did
not write — a hand-placed or hand-edited one whose command carries flags `command_for` does not
emit, which under command matching is invisible and gets a duplicate added beside it. Both are
required because either alone is far too coarse to be an identity: every session in a group shares
its group, and a title is unique only within one. Neither alone changes matching.

READS ARE SYNCHRONOUS, WRITES ARE NOT. Measured against aoe on 2026-08-01: `list --json`,
`group list` and `profile list` all return in ~0.01s, but `aoe add` takes ~12s (it brings the
daemon up). Blocking a launch for twelve seconds to populate a dashboard is not a trade worth
making, so the reads that decide *whether* to write happen inline and the writes are fired into a
detached process that outlives the `os.execvp`. The one exception is `--create-aoe-only`, where
registering IS the command the user ran and they are entitled to its exit status.
"""
from __future__ import annotations

import itertools
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

# How the recorded command names its stack. Both run verbs take `--stack`, never a positional, so
# the stack sits at a keyword rather than a fixed index — `command_for` writes it and
# `forget_stack` reads it back, and they must not drift.
_STACK_FLAG = ["--stack"]

# The two overrides, recorded on the command so a restart from the dashboard re-asserts them. Left
# off it, a restarted row would sync itself back under the DERIVED group and title and add a second
# row beside the one the user placed — the exact duplicate the flags exist to prevent.
_GROUP_FLAG = "--aoe-group"
_TITLE_FLAG = "--aoe-title"


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


def _apply(
    exe: str, batch: list[list[str]], *, background: bool, optional: frozenset[int] = frozenset()
) -> bool:
    """Execute a write batch, detached or blocking. True when every write is believed to have run.

    `optional` holds indices whose non-zero exit is an expected outcome rather than a failure, so a
    blocking caller does not report an error for one. Used for the tool-labelled `add`, which aoe
    rejects whenever it does not recognise the agent and which is always followed by a plain retry.
    The detached path needs no equivalent: `_spawn` joins with `;`, which is already tolerant.
    """
    if background:
        return _spawn(exe, batch)
    for i, args in enumerate(batch):
        result = _run(exe, args, timeout=_WRITE_TIMEOUT)
        if result is None or (result.returncode != 0 and i not in optional):
            return False
    return True


def command_for(
    verb: str, stack: str, harness: str, project_path: Path,
    *, group: str | None = None, title: str | None = None,
) -> str:
    """The harnessed invocation recorded on the session — both the identity key and what aoe runs.

    Always the RESOLVED stack name and an absolute path, never the user's original argv. A dynamic
    stack is minted into the generated catalog root before this is called, so `--stack
    <derived-name>` replays it exactly and keeps one canonical form for every verb that reaches
    here — a row records the same shape whether the user typed `--stack` or a `--recipe` set.

    TERMINATED WITH `--`, which is not cosmetic. aoe's `auto_resume_on_restart` appends the recorded
    tool's resume flags to this string when a stopped session is restarted — for `tool = claude`,
    `--resume <id>` / `--fork-session --session-id <uuid>`. `--cmd-override` replaces the binary but
    does NOT change the recorded tool, so those claude flags get appended to OUR command and
    harnessed's Click CLI rejects them outright: `No such option: --session-id`. It bites on restart
    only, which is why the first launch of a row looks fine. The trailing `--` puts them past
    harnessed's own option parsing (`launcher._extract_passthrough`), which forwards everything after
    it to the agent — the process they were meant for. Verified against aoe 1.13.2.

    Half of a pair: this delivers the flags to the agent, and the `--tool` label in `sync_session`
    decides WHICH agent's flags aoe generates. Without that label they are always claude's, and
    forwarding them to a non-claude agent kills the pane on every restart.

    `group`/`title` are echoed back as `--aoe-group`/`--aoe-title` so the placement the user asked
    for survives a restart from the dashboard; see those flags' note above.
    """
    args = ["harnessed", verb, harness, str(project_path), *_STACK_FLAG, stack]
    if group is not None:
        args += [_GROUP_FLAG, group]
    if title is not None:
        args += [_TITLE_FLAG, title]
    return shlex.join([*args, "--"])


def title_for(
    verb: str, stack: str, harness: str, project_path: Path, *, title: str | None = None
) -> str:
    """The dashboard label — and, unavoidably, half of aoe's own uniqueness key.

    aoe deduplicates an `add` on (title, path): a second session with both the same is refused with
    "Session already exists with same title and path" and exit status ZERO, so a collision does not
    surface as an error, it surfaces as a row that never appeared. The title must therefore be
    injective over everything WE treat as identity, which includes the backend — a stack running
    host-native and the same stack in a container are two different sessions that share a path,
    stack and harness, and differ only in the verb.

    Observed against aoe 2026-08-01: with the backend omitted, `host-run` registrations silently
    vanished behind their `launch` twin.

    An explicit `title` is returned verbatim — the caller owns the collision risk described above.
    """
    if title is not None:
        return title
    backend = "host" if verb == "host-run" else "container"
    return f"{project_path.name} [{harness}/{backend}] {stack}"


def group_for(project_path: Path, *, group: str | None = None) -> str:
    """The group a row belongs in: the user's `--aoe-group` when given, else the derived one."""
    return group if group is not None else _group_for(project_path)


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


def _registered(
    exe: str, command: str, project_path: Path,
    *, group: str | None = None, title: str | None = None,
) -> bool:
    """Whether this exact (path, stack, harness, verb) already has a row.

    With BOTH `group` and `title` supplied the user has named the row, and (group, title) becomes
    the key instead — the only match that can find a row harnessed did not write, whose command
    therefore need not be one `command_for` could produce. Either flag alone is ignored here: a
    group holds many sessions and a title is unique only inside one, so neither identifies a row.

    Matched against `group`, which is what `aoe list --json` calls the field it stores on disk as
    `group_path`; both names are accepted so a rename upstream degrades to the command match (a
    duplicate row) rather than to an exception.
    """
    sessions = _sessions(exe)
    if group is not None and title is not None:
        return any(
            (s.get("group") or s.get("group_path")) == group and s.get("title") == title
            for s in sessions
        )
    for session in sessions:
        if session.get("command") != command:
            continue
        recorded = session.get("path")
        # Compare resolved paths, not strings: aoe stores whatever it was given, and a session
        # added through a symlinked route would otherwise register a second time.
        if recorded and Path(recorded).resolve() == project_path:
            return True
    return False


def sync_session(
    verb: str, stack: str, harness: str, project_path: Path, *, background: bool = True,
    group: str | None = None, title: str | None = None,
) -> bool:
    """Register this launch with aoe, creating the profile and repo group on the way.

    Idempotent by (path, command): relaunching the same stack+harness in the same folder finds the
    existing row instead of stacking duplicates. Never raises.

    `group` (--aoe-group) and `title` (--aoe-title) override the derived placement and label. Given
    BOTH, the row is instead matched on (group, title) — how an existing, possibly hand-written row
    is adopted rather than duplicated. See `_registered` and the module note on identity.

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
        command = command_for(verb, stack, harness, project_path, group=group, title=title)
        if _registered(exe, command, project_path, group=group, title=title):
            return True

        batch: list[list[str]] = []
        if not _has_profile(exe):
            batch.append(["profile", "create", PROFILE])
        group_name = group_for(project_path, group=group)
        if not _has_group(exe, group_name):
            batch.append(["group", "create", group_name, "-p", PROFILE])
        add = [
            "add", str(project_path),
            "-p", PROFILE,
            "-g", group_name,
            "-t", title_for(verb, stack, harness, project_path, title=title),
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
        ]
        # WHICH AGENT THIS ROW RUNS, attempted then retried without. `--cmd-override` sets the
        # command but leaves the recorded tool at aoe's default, `claude` — so an omp row was stored
        # as a claude one, and `auto_resume_on_restart` appended CLAUDE's resume flags to it on every
        # restart. Since `command_for` terminates our command with `--`, those flags sail past
        # harnessed's own parser and land on the omp binary, which rejects a claude conversation id
        # outright: `Error: Session "<uuid>" not found.` The pane dies, aoe respawns it, and it loops.
        # `--tool` makes aoe generate the flags of the agent that is actually there.
        #
        # THE RETRY IS LOAD-BEARING. aoe validates `--tool` against its built-in agent list AND the
        # invoking process's PATH — `'codex' is not installed or not on $PATH` exits non-zero and
        # adds NOTHING, silently on the detached path. That gate is the HOST's, but a container
        # harness lives in the pod, and even a host-installed one can be missed: omp resolves through
        # a mise install dir that is on the user's shell PATH and not on a daemon's. Asking aoe is no
        # cheaper than trying: `aoe agents` is ~1.35s, a hundred times the other reads, and it answers
        # for the wrong PATH anyway. So attempt the labelled add and follow it with the plain one,
        # which aoe refuses as a duplicate title+path at exit 0 WITHOUT touching the stored tool when
        # the first won, and which registers the row as before when it did not. Verified, aoe 1.13.2.
        batch.append([*add, "--tool", harness])
        batch.append(add)
        return _apply(exe, batch, background=background, optional=frozenset({len(batch) - 2}))
    except Exception:  # noqa: BLE001 — an optional dashboard must never break a launch.
        return False


def forget_stack(verb: str, stack: str, *, background: bool = True) -> None:
    """Drop the sessions for a stack after its instances are torn down. Never raises.

    Scoped to ONE verb because `harnessed rm` is container-scoped: it removes every container
    instance of a stack across harnesses and projects, and leaves host-native sessions — which own
    no container — alone. Removing by session id, not title, so a user-renamed row still matches.

    Matched on the `--stack <name>` PAIR rather than a token index. The stack used to be the third
    token, which a prefix compare could check; it is now a flag value that sits after the harness
    and path, so its position varies with whether a project path was recorded.
    """
    try:
        exe = _bin()
        if exe is None:
            return
        batch: list[list[str]] = []
        for session in _sessions(exe):
            try:
                tokens = shlex.split(session.get("command") or "")
            except ValueError:
                continue
            if tokens[:2] != ["harnessed", verb]:
                continue
            if not any(
                a == _STACK_FLAG[0] and b == stack for a, b in itertools.pairwise(tokens)
            ):
                continue
            sid = session.get("id")
            if sid:
                batch.append(["remove", str(sid), "-p", PROFILE])
        _apply(exe, batch, background=background)
    except Exception:  # noqa: BLE001 — cleanup is best-effort, same as registration.
        return
