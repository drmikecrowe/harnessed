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

Session identity is (project path, harness). The recorded command is `mise run <harness>` — the
project's own launch task (see `mise_command`) — so a project gets one row per harness, and which
STACK that row starts is whatever `[tasks.<harness>]` in its `mise.local.toml` currently says.
Relaunching claude against a different stack rewrites that task, and the row follows. Harness stays
part of identity because a stack has a separately assembled profile per harness
(`profiles/<stack>/<harness>/`), so claude and omp are two different things to run. Titles stay
purely cosmetic, so a user renaming a row cannot break identity.

UNLESS THE USER NAMES THE ROW. `--aoe-group` and `--aoe-title` (see `sync_session`) override the
derived group and title, and supplying BOTH also replaces the identity key: the row is matched on
(group, title) instead of the recorded command. That is the only way to adopt a row harnessed did
not write — a hand-placed or hand-edited one whose command carries flags `command_for` does not
emit, which under command matching is invisible and gets a duplicate added beside it. Both are
required because either alone is far too coarse to be an identity: every session in a group shares
its group, and a title is unique only within one. Neither alone changes matching.

TWO DIFFERENT KEYS, WHICH IS A HAZARD AND NOT A DESIGN. We decide whether to write by matching the
recorded command and path; aoe decides whether to accept by matching TITLE and path, and refuses a
duplicate at exit status ZERO. A row that agrees on aoe's key but not ours is invisible to the
check and silently eats the `add` — forever, since the write is detached and unexamined. So every
registration that is about to add scans for those rows first (`_drifted_rows`) and reports every
one of them. A row is repaired only when its stored command is one this module emits (`_is_ours`),
and a single row we may not touch blocks the registration outright — it keeps the key whatever we
do to its neighbours.

REPAIR IS A RENAME, WHICH LOOKS INDIRECT UNTIL YOU TRY THE OBVIOUS THING. aoe 1.13.2 cannot rewrite
a session's command, so the obvious repair is remove-then-add — and it does not work: `aoe remove`
only moves the row to the TRASH, a trashed row is still returned by `aoe list --json`, and it still
holds the (title, path) key, so the replacement `add` is refused at exit 0 exactly like the first
one. The row would be lost and nothing written in its place. `aoe session rename` frees the key
without destroying anything, so the stale row survives beside the corrected one, keeping its id,
resume target and flags. `--purge` would also work and is rejected on purpose: it is irreversible
and this runs unattended on a launch. All verified against aoe 1.13.2. See bd harnessed-cn9.

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

from collections.abc import Callable
from pathlib import Path

from ruamel.yaml import YAML

from . import paths
from .schema import HARNESS_CONFIG_DIR

# The dedicated aoe workspace. Everything this module does is scoped to it, so a user's own
# sessions in `default` are never touched, reordered, or removed.
PROFILE = "harnessed"

# aoe's own config lives here. Its presence is the second half of the "user actually runs aoe"
# test: `aoe` on PATH alone can mean a stray binary that was never set up.
_CONFIG_DIRNAME = "agent-of-empires"

# `default` is the baseline every dynamic stack extends. It is not a thing the user composed, so a
# row for it is noise in a dashboard whose whole point is showing the stacks they built. A guess
# about what the user wants, though — so `--aoe-group`/`--aoe-title` overrule it (see
# `sync_session`), since naming a row is stating that this one is wanted.
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

# How much of a launcher script `_replays_stack` will read. The exec line is line 3 or 4 of a file we
# wrote, but a row can point at ANY path, and `harnessed rm` is unattended — so the read is bounded
# rather than trusting the target to be small.
_SCRIPT_READ_LIMIT = 64 * 1024

# The two overrides, recorded on the command so a restart from the dashboard re-asserts them. Left
# off it, a restarted row would sync itself back under the DERIVED group and title and add a second
# row beside the one the user placed — the exact duplicate the flags exist to prevent.
_GROUP_FLAG = "--aoe-group"
_TITLE_FLAG = "--aoe-title"

# The one LAUNCH flag that changes what the agent gets and therefore has to be replayed. `--rm`,
# `--fresh` and the pod flags describe THIS invocation's lifecycle, not the session's shape; a
# restart from the dashboard is a fresh launch and re-deciding them is correct. `--strict-mcp-config`
# is different: dropped, claude also loads the project's `.mcp.json` and the user's config, so a row
# that forgets it comes back with a different MCP surface than the one the user registered.
_NO_STRICT_MCP_FLAG = "--no-strict-mcp-config"

# What a drifted row is renamed to. Carries the row id so the new title cannot collide with
# anything — including a second `(stale)` row from an earlier repair. A rename that collides would
# fail on the detached path, silently, which is the exact failure class this whole change exists to
# remove.
_STALE_SUFFIX = "(stale {sid})"

# An aoe session id as `session list-trash` prints it. Fixed-width hex, which is what
# makes it findable on a line whose title is arbitrary free text.
_TRASH_ID = re.compile(r"\b[0-9a-f]{16}\b")

# Separator between composed recipes in a derived title. See `title_for` for why it is
# not `-`.
_RECIPE_JOIN = "+"


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


def replay_command(verb: str, harness: str, project_path: Path) -> str:
    """What the row runs: the launcher script that launch left in the project folder.

    The flags live in the script, not in this string, so this stays STABLE across launches — the
    identity property the old `mise run <harness> --` had, and the reason a flag added to
    `command_for` is free rather than re-keying every existing row. See `command_for`'s note on
    identity.

    Replaced `--last` and its `lastrun` state file, which in turn replaced the mise task
    (bd harnessed-7mt). Each step removed an indirection; this one also makes the record READABLE —
    the user can `cat claude-host` instead of reconstructing a launch from shell history.

    NOT `--stack <name>`: naming the stack would put a launch flag back in the identity key.

    ABSOLUTE, not `./claude-host`. Whether aoe runs a row's command with the working directory set
    to the row's path is aoe's business and not ours to depend on; an absolute path is correct under
    either behavior and is equally stable as an identity key.

    TERMINATED WITH `--`, and that separator belongs HERE rather than inside the script. aoe appends
    the recorded tool's resume flags on restart and they must sail past harnessed's own option
    parsing to reach the agent (see `command_for`). The script ends with `"$@"`, so the separator
    arrives as the script's own argument and lands in exactly the right place — while a human's
    `./claude-host --fresh`, with no separator, still reaches harnessed. Put the `--` in the file and
    the human's flag goes to the agent instead; see `launchscript`.
    """
    # Imported HERE, not at module scope: `launchscript` needs `command_for` from this module, so a
    # top-level import either way is a cycle. It resolves today by luck of ordering — both sides
    # only touch each other at call time — and would stop resolving the moment either module used
    # the other during import. A local import states the dependency direction instead of relying on
    # that.
    from . import launchscript

    script = Path(project_path) / launchscript.script_name(verb, harness)
    return shlex.join([str(script), "--"])


def command_for(
    verb: str, stack: str, harness: str, project_path: Path,
    *, group: str | None = None, title: str | None = None, no_strict_mcp: bool = False,
) -> str:
    """The harnessed invocation — the `run` line of the project's `mise run <harness>` task, which
    is what a row invokes (see `mise_command`). Still the string a restart ultimately executes.

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
    for survives a restart from the dashboard; see those flags' note above. `no_strict_mcp` is
    echoed back for the same reason and one more: it changes the MCP surface the agent comes up
    with, so a row that dropped it would restart as a DIFFERENT session than the one registered.

    NOT the identity key — `mise_command` is, and it names only the harness. Adding a flag here is
    therefore free where it once re-keyed every existing row. The flip side: a flag added here and
    nowhere else changes what a row DOES without changing which row it is, so anything a user must
    be able to tell two launches apart by still has to reach the title. See `title_for`.
    """
    args = ["harnessed", verb, harness, str(project_path), *_STACK_FLAG, stack]
    if no_strict_mcp:
        args.append(_NO_STRICT_MCP_FLAG)
    if group is not None:
        args += [_GROUP_FLAG, group]
    if title is not None:
        args += [_TITLE_FLAG, title]
    return shlex.join([*args, "--"])


def title_for(
    verb: str, stack: str, harness: str, project_path: Path,
    *, title: str | None = None, no_strict_mcp: bool = False,
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

    That invariant is why `no_strict_mcp` shows up in a LABEL. It is recorded on the command, which
    makes it part of identity, and identity that the title cannot express is identity aoe throws
    away: the strict and open-MCP variants of one stack would produce the same title, the second
    `add` would be refused at exit 0, and the row would keep replaying the command it was first
    registered with — the flag would appear to be ignored.

    An explicit `title` is returned verbatim — the caller owns the collision risk described above.

    WHAT LEADS IS WHAT VARIES. The harness and backend come first because they are what the reader
    is picking between; the folder follows. The old shape led with the folder and buried the pair in
    brackets, which put the least distinguishing token first in a dashboard already grouped by repo.

    THE FOLDER STAYS, and it is not cosmetic. `_registered` matches on (group, title) with NO path
    check when the caller supplies both `--aoe-group` and `--aoe-title`, and `_group_for` keys on
    the git COMMON dir — so every worktree of one checkout shares a group. Drop the folder and two
    worktrees running the same stack, harness and backend collide on that key: the second launch
    reads as already-registered and never gets a row, silently, because the write is detached.

    THE BASELINE IS NOT SHOWN. A dynamic stack's name is `<base>.<recipe>.<recipe>`, so the old
    title restated `default.` on every row that had one. `_composed_recipes` returns the delta over
    that baseline and the join shows only it. An authored stack has no delta and falls back to its
    own name, which is also what keeps `default` and `isolated` — two baselines, no recipes between
    them — from rendering identically.
    """
    if title is not None:
        return title
    backend = "host" if verb == "host-run" else "container"
    mcp = " +open-mcp" if no_strict_mcp else ""
    recipes = _composed_recipes(stack)
    # `+`, not `-`: recipe names contain `-` themselves (`codebase-memory-mcp`, `gh-issue-tracker`),
    # so a `-` join has no visible seam between two of them.
    composed = _RECIPE_JOIN.join(recipes) if recipes else stack
    return f"{harness}/{backend} {project_path.name} {composed}{mcp}"


def _composed_recipes(stack: str) -> list[str]:
    """The recipes a stack composes ON TOP of its baseline, or [] when it composes nothing.

    THE RAW MANIFEST, never `load_stack`. That resolves the `extends:` chain, which would hand back
    the baseline's recipes merged in — the very thing this exists to leave out.

    THE STACK NAME CANNOT BE PARSED FOR THIS, though it looks like it can. `derive_name` joins on
    `.` after sanitizing each ref, and appends a digest when the join is lossy or over-long: the
    single recipe `beads/team` mints as `default.beads-team-55bfd6ac`. Splitting that on `.` yields
    `beads-team-55bfd6ac`, which is neither the recipe nor recoverable. The manifest carries
    `recipes: [beads/team]` verbatim.

    LOCATION IS WHAT MARKS A STACK MACHINE-MADE — the generated manifest's own header says so, and
    it is why an authored stack returns [] here rather than its `recipes:` key. That key is an
    authored stack's whole content and not a delta at all: `default` lists eight recipes, so
    reading it would produce a title several times longer than the stack name it replaced.

    Guarded like everything else on this path: a missing, unreadable or malformed manifest costs
    the delta and falls back to the stack name, never a failed launch.
    """
    try:
        stack_dir = paths.find_in_catalog("stacks", stack).resolve()
        generated = (paths.generated_catalog_root() / "stacks").resolve()
        if not stack_dir.is_relative_to(generated):
            return []
        yaml = YAML(typ="safe", pure=True)
        with (stack_dir / "stack.yaml").open(encoding="utf-8") as fh:
            raw = yaml.load(fh)
        return [r for r in (raw.get("recipes") or []) if isinstance(r, str)]
    except Exception:  # noqa: BLE001 — an optional dashboard must never break a launch.
        return []


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
    """Every LIVE session in the harnessed profile. Empty on any parse or transport failure.

    aoe prints a human "No sessions found" line rather than `[]` for an empty profile, so a decode
    failure is an ordinary outcome here, not an anomaly.

    TRASHED ROWS ARE SUBTRACTED, and nothing in the JSON says which they are. `aoe list --json`
    returns a trashed session with the same fields and the same shape as a live one — no status, no
    `trashed_at`, nothing to filter on. Verified against aoe 1.14.1.

    Without this, trashing a row makes it permanently un-re-registerable: `_registered` matches the
    trashed row on (command, path), `sync_session` returns early believing the row is there, and no
    `add` is ever issued. The user deletes a row, relaunches to recreate it, and gets told it
    registered fine while the dashboard stays empty. `aoe session list-trash` is the only thing that
    can tell them apart, and it costs the same 0.02s as the list above.
    """
    result = _run(exe, ["list", "--json", "-p", PROFILE])
    if result is None or result.returncode != 0:
        return []
    try:
        data = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    trashed = _trashed_ids(exe)
    return [s for s in data if isinstance(s, dict) and s.get("id") not in trashed]


def _trashed_ids(exe: str) -> frozenset[str]:
    """Ids aoe holds in this profile's trash, or an empty set when it cannot say.

    FAILS OPEN, on purpose. Not knowing means we keep every row `list` returned, which is exactly
    today's behavior: at worst a trashed row suppresses one registration. Failing CLOSED — dropping
    the whole session list because the trash could not be read — would make every launch re-add rows
    that already exist, and duplicates are the failure this module exists to prevent.

    Scraped, because `list-trash` has no `--json`. The id is the one fixed-width hex token on a
    line; titles are free text and can contain anything, so the id is matched rather than the line
    parsed positionally.
    """
    result = _run(exe, ["session", "list-trash", "-p", PROFILE])
    if result is None or result.returncode != 0:
        return frozenset()
    return frozenset(_TRASH_ID.findall(result.stdout))


def _registered(
    sessions: list[dict], command: str, project_path: Path,
    *, group: str | None = None, title: str | None = None,
) -> bool:
    """Whether this (path, harness) already has a row.

    Takes the session list rather than reading it, because the caller also hands it to
    `_drifted_rows` and a launch should pay for one `list --json`, not two.

    With BOTH `group` and `title` supplied the user has named the row, and (group, title) becomes
    the key instead — the only match that can find a row harnessed did not write, whose command
    therefore need not be one `command_for` could produce. Either flag alone is ignored here: a
    group holds many sessions and a title is unique only inside one, so neither identifies a row.

    Matched against `group`, which is what `aoe list --json` calls the field it stores on disk as
    `group_path`; both names are accepted so a rename upstream degrades to the command match (a
    duplicate row) rather than to an exception.
    """
    if group is not None and title is not None:
        return any(
            (s.get("group") or s.get("group_path")) == group and _same_title(s.get("title"), title)
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


def _same_title(a: str | None, b: str | None) -> bool:
    """Compare two titles the way aoe's own dedupe does: trimmed at the ends.

    Verified against aoe 1.13.2. With `Row A` present, adding ` Row A` or `Row A ` is refused as a
    duplicate, while `row a` and `Row  A` are both accepted — the key is case-sensitive and
    inner-whitespace-sensitive, but trimmed. Comparing exactly here would let precisely the rows
    aoe refuses slip past the scan, which is the silent exit-0 failure this module now exists to
    prevent. Reachable in practice through `--aoe-title ' foo '`.
    """
    return (a or "").strip() == (b or "").strip()


def _is_ours(command: str) -> bool:
    """Whether a stored command is a shape THIS module emits — the licence to rewrite the row.

    Every shape harnessed has ever written: the raw invocation `command_for` produces, the
    `harnessed <verb>-run <harness> --last --` replay `replay_command` records now, and the
    `mise run <harness> --` task that preceded it (bd harnessed-7mt). Everything else belongs to
    somebody else and is reported without being touched.

    THE MISE SHAPE IS STILL ACCEPTED THOUGH NOTHING WRITES IT. Rows created before the switch are
    ours, and reading them as foreign would strand every one of them: drift against a foreign row is
    only reported, so a user's existing rows would never be repaired onto the new command and the
    launch would keep warning forever. Retiring the shape means we stop WRITING it, not that we
    forget we wrote it.

    THE THIRD TOKEN IS CHECKED AGAINST THE HARNESS REGISTRY, not merely present. `mise run` alone
    is not our shape — it is the prefix of every mise task anyone has ever written, so a user's own
    `mise run dev --` row would have been eligible for rewriting. Only a task named for a real
    harness can be one of ours.

    Narrow in a way that costs us, on purpose: a row storing an ABSOLUTE path to harnessed
    (`/home/u/.local/bin/harnessed host-run ...`) reads as foreign and is only reported. A missed
    repair is one warning the user can act on; a wrong repair edits a row that was never ours.
    """
    try:
        tokens = shlex.split(command or "")
    except ValueError:  # an unbalanced quote is not a command we wrote
        return False
    if tokens[:1] == ["harnessed"]:
        return True
    if _is_launcher_script(tokens):
        return True
    return tokens[:2] == ["mise", "run"] and len(tokens) > 2 and tokens[2] in HARNESS_CONFIG_DIR


def _is_launcher_script(tokens: list[str]) -> bool:
    """Whether these tokens are a `<path>/<harness>-<verb> --` row — what `replay_command` writes.

    Matched on the BASENAME against the harness registry, never on the path existing. A row whose
    script has been deleted is still ours and still repairable; requiring the file would strand it
    at exactly the moment repair is what the user needs.

    Narrow on purpose. Any single-token command ending in `--` would be far too broad — it would
    make a user's own `./run-dev --` row eligible for rewriting. The basename must name a harness we
    know and one of the two verbs, which no unrelated script does by accident.
    """
    if len(tokens) != 2 or tokens[1] != "--":
        return False
    name = Path(tokens[0]).name
    harness, _, suffix = name.rpartition("-")
    return bool(harness) and harness in HARNESS_CONFIG_DIR and suffix in {"host", "container"}


def _drifted_rows(sessions: list[dict], command: str, project_path: Path, title: str) -> list[dict]:
    """Every row `aoe add` would be silently refused against.

    THE TWO KEYS ARE NOT THE SAME KEY, which is the whole of bd harnessed-cn9. We decide whether to
    write by matching (command, path) in `_registered`; aoe decides whether to accept by matching
    (title, path), and refuses a duplicate with exit status ZERO. So a row that agrees on title and
    path but not on command is invisible to the check, swallows the `add` without an error, and —
    because a launch fires that write detached and never looks — keeps replaying its stored command
    forever. A row titled for one stack launching another, with no signal anywhere.

    ALL of them, not just the first. aoe should hold (title, path) unique, but "should" is not a
    guarantee we get to rely on — an externally edited session store, or an earlier repair that
    half-landed, can leave two. Repair only the first and the second still holds the key, so the
    add is still refused at exit 0: the same silence, one row further along.

    Everything is `.get`-guarded and the path comparison is wrapped: this runs on the launch path,
    and aoe's JSON is not our schema to trust.
    """
    found: list[dict] = []
    for session in sessions:
        if not _same_title(session.get("title"), title) or session.get("command") == command:
            continue
        recorded = session.get("path")
        if not recorded:
            continue
        try:
            if Path(recorded).resolve() != project_path:
                continue
        except (OSError, TypeError, ValueError):
            continue
        found.append(session)
    return found


def _drift_message(row: dict, ours: str, *, renamed_to: str | None, blocked: bool = False) -> str:
    """One report naming the row and both commands. Never silent, whichever way it resolves.

    THREE OUTCOMES, not two. A row can be left alone because it is not ours to touch, or because
    some OTHER row at this key is not ours to touch and the registration cannot land whatever we
    do here. Telling a user their own row "is not a command harnessed writes" when the truth is
    "its neighbour blocked us" sends them to inspect the wrong row.
    """
    sid = row.get("id") or "?"
    lines = [
        f"aoe row {row.get('title') or '?'} ({sid}) records a different command than this launch:",
        f"  stored: {row.get('command') or ''}",
        f"  ours:   {ours}",
    ]
    if blocked:
        return "\n".join([
            *lines,
            "  NOT repaired: another row at this title and path is not one harnessed writes, so",
            "  the registration cannot land whatever we do here. Nothing was changed.",
            f"  fix: aoe session rename {sid} -t '<any other title>' -p {PROFILE}   then relaunch",
        ])
    if renamed_to is not None:
        # PRESENT TENSE, DELIBERATELY. On a launch the batch is fired detached and its outcome is
        # never examined, so claiming the rename HAPPENED would be asserting something this
        # process cannot know. Only `--create-aoe-only` blocks long enough to find out.
        lines += [
            f"  renaming it to {renamed_to} and registering a correct row beside it.",
            "  Nothing is deleted: the old row keeps its id, resume target and flags.",
        ]
    else:
        lines += [
            "  NOT repaired: that is not a command harnessed writes, so the row is left as it is.",
            "  aoe refuses our registration at exit 0, so the dashboard keeps replaying the stored one.",
            # NOT `aoe remove`: that only moves the row to the trash, where it still holds the
            # (title, path) key and still comes back from `aoe list --json`. Relaunching after a
            # bare remove is refused exactly the same way. Verified against aoe 1.13.2.
            f"  fix: aoe session rename {sid} -t '<any other title>' -p {PROFILE}   then relaunch",
        ]
    return "\n".join(lines)


def _report(on_drift: Callable[[str, bool], None] | None, message: str, *, repairing: bool) -> None:
    """Hand the report to the caller. A reporter that explodes is not the launch's problem.

    `repairing` travels with the message because the caller has to describe the outcome of a write
    that has not happened yet: a repair whose rename lands and whose add then fails leaves the row
    RENAMED, and reporting that as "left as it is" would send the user looking for a row under its
    old title.
    """
    if on_drift is None:
        return
    try:
        on_drift(message, repairing)
    except Exception:  # noqa: BLE001 — see the module docstring: never fail a launch.
        return


def sync_session(
    verb: str, stack: str, harness: str, project_path: Path, *, background: bool = True,
    group: str | None = None, title: str | None = None, no_strict_mcp: bool = False,
    on_drift: Callable[[str, bool], None] | None = None,
) -> bool:
    """Register this launch with aoe, creating the profile and repo group on the way.

    Idempotent by (path, command): relaunching the same stack+harness in the same folder finds the
    existing row instead of stacking duplicates. Never raises.

    `group` (--aoe-group) and `title` (--aoe-title) override the derived placement and label. Given
    BOTH, the row is instead matched on (group, title) — how an existing, possibly hand-written row
    is adopted rather than duplicated. See `_registered` and the module note on identity.

    EITHER of them also overrules `_SKIP_STACKS`. That skip suppresses a row the user never asked
    for; asking for one by name is the case it was guarding against being wrong about, and without
    this a `--aoe-group`/`--aoe-title` on the `default` stack was accepted and silently dropped.
    Unlike the identity switch above, one flag is enough: placing a row is not identifying one.

    `no_strict_mcp` (--no-strict-mcp-config) is recorded on the command so a restart brings the
    agent up with the MCP surface this launch had. See `command_for`.

    DRIFT IS REPORTED, NEVER SWALLOWED (bd harnessed-cn9). Finding no row does not mean aoe will
    accept our `add`: it dedupes on (title, path), we match on (command, path), and a row that
    agrees on the first key but not the second silently absorbs the add at exit 0. `_drifted_rows`
    finds every one of them; `on_drift` is handed one message PER ROW, naming it and both commands,
    plus a flag saying whether a repair is being attempted for it. A row whose stored command is a
    shape we write is repaired by RENAMING it aside (`session rename`, never `remove` — a trashed
    row keeps the key) and adding the correct row beside it; everything else is left alone and
    reported, and this returns False so `--create-aoe-only` can fail on it. One row we may not
    touch blocks the whole registration, so nothing is renamed in that case either. `on_drift` is
    called once per drifted row and may raise; the launch does not care.

    Not on the adopt path: with BOTH `group` and `title`, a matched row returns True above and its
    command is never examined, which is the point of adopting one.

    Returns True when the row exists or its creation was dispatched, False when aoe is unavailable,
    a blocking write failed, or unrepairable drift blocked the write. Callers on the passive mirror
    path ignore this; `--create-aoe-only` reports it.
    """
    try:
        if stack in _SKIP_STACKS and group is None and title is None:
            return False
        exe = _bin()
        if exe is None:
            return False

        # Canonicalize once: the resolved path is both what we record and what we compare against,
        # so two routes to the same directory cannot register two rows.
        project_path = Path(project_path).resolve()
        command = replay_command(verb, harness, project_path)
        sessions = _sessions(exe)
        if _registered(sessions, command, project_path, group=group, title=title):
            return True

        row_title = title_for(
            verb, stack, harness, project_path, title=title, no_strict_mcp=no_strict_mcp
        )

        # No row matched, so we are about to `add`. If a row already holds (title, path) with a
        # different command, aoe will refuse that add at exit 0 and the stale row survives — bd
        # harnessed-cn9. Say so either way; rewrite it only if it is a row we wrote.
        # RENAMED, NOT REMOVED. `aoe remove` only trashes the row, and a trashed row still holds
        # the (title, path) key aoe dedupes on — so remove-then-add loses the row AND has its
        # replacement refused at exit 0. Renaming frees the key without destroying anything.
        # Verified against aoe 1.13.2; see bd harnessed-cn9.
        # DECIDE EVERY ROW BEFORE REPORTING ANY OF THEM. One row we may not touch is enough to
        # keep the key, so the add cannot land whatever we do to the others — and that verdict is
        # not known until the last row has been examined. Reporting inside the discovery loop
        # announced a rename for an owned row and then wrote nothing when a later row blocked,
        # which is this bug's own failure mode: a message asserting what did not happen.
        drifted = [
            (stale, stale.get("id"), bool(stale.get("id")) and _is_ours(stale.get("command") or ""))
            for stale in _drifted_rows(sessions, command, project_path, row_title)
        ]
        blocked = any(not repairable for _, _, repairable in drifted)

        repairs: list[list[str]] = []
        for stale, sid, repairable in drifted:
            renaming = repairable and not blocked
            stale_title = f"{row_title} {_STALE_SUFFIX.format(sid=sid)}" if renaming else None
            _report(
                on_drift,
                _drift_message(
                    stale, command, renamed_to=stale_title, blocked=blocked and repairable
                ),
                repairing=renaming,
            )
            if renaming:
                repairs.append(
                    ["session", "rename", str(sid), "-t", stale_title or "", "-p", PROFILE]
                )
        if blocked:
            return False

        batch: list[list[str]] = []
        if not _has_profile(exe):
            batch.append(["profile", "create", PROFILE])
        group_name = group_for(project_path, group=group)
        if not _has_group(exe, group_name):
            batch.append(["group", "create", group_name, "-p", PROFILE])
        # After the group exists, before the re-add: the rows aoe would otherwise refuse against.
        batch.extend(repairs)
        add = [
            "add", str(project_path),
            "-p", PROFILE,
            "-g", group_name,
            "-t", row_title,
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
        # which aoe refuses as a duplicate title+path WITHOUT touching the stored tool when the
        # first won, and which registers the row as before when it did not.
        batch.append([*add, "--tool", harness])
        batch.append(add)
        applied = _apply(exe, batch, background=background, optional=frozenset({len(batch) - 2}))
        if background:
            return applied
        # ASK, DO NOT INFER. The retry above is refused whenever the labelled add won, and what a
        # refusal EXITS WITH is not ours to depend on: aoe 1.13.2 exited 0, aoe 1.14.1 exits 1. Under
        # the exit-code reading, every successfully labelled row on 1.14.1 reported
        # "could not register the session" while sitting in the dashboard — a `--create-aoe-only`
        # that fails loudly having done exactly what was asked.
        #
        # Re-reading settles it against any aoe: the row is there or it is not. Only on the blocking
        # path, where the writes have finished; a detached batch has not necessarily run yet, so
        # there `applied` remains the only answer available.
        return _registered(
            _sessions(exe), command, project_path, group=group, title=title
        ) or applied
    except Exception:  # noqa: BLE001 — an optional dashboard must never break a launch.
        return False


def _replays_stack(tokens: list[str], verb: str, stack: str) -> bool:
    """Whether a launcher-script row would start `stack` — the stack a replay row does not carry.

    Only for the shape `replay_command` writes (`<path>/<harness>-<verb> --`); the caller handles
    the older `--stack <name>` shape itself. Everything is guarded because this runs inside
    `harnessed rm`'s best-effort cleanup, over aoe's JSON, which is not our schema to trust.

    READS THE SCRIPT the row points at, rather than a side record. The script IS the record now, and
    it carries the resolved `--stack <name>` in its exec line — so the file that would run and the
    file we attribute the row by are the same file, and cannot disagree. The `--last` shape this
    replaced had to consult `lastrun` for the same answer.

    Returns False when the script is missing, unreadable, or names another stack — see `forget_stack`
    on why an unattributable row is left alone rather than removed. Bounded read: a row can point
    anywhere, and `harnessed rm` must not stall on a huge or blocking file.
    """
    if not _is_launcher_script(tokens):
        return False
    # Verb agreement is not optional: `rm` is container-scoped, and a `claude-host` row names a
    # backend it must not touch.
    from . import launchscript  # local, for the cycle reason in `replay_command`

    name = Path(tokens[0]).name
    if name != launchscript.script_name(verb, name.rpartition("-")[0]):
        return False
    script = Path(tokens[0])
    try:
        # `is_file()` BEFORE the read, the same guard `launchscript._ensure_excluded` applies to the
        # exclude file. A row's path comes out of aoe's JSON and can point at anything: a FIFO passes
        # `exists()`, and opening one BLOCKS until something writes to it — so `harnessed rm`, which
        # runs unattended, would hang rather than fail. `except OSError` cannot catch a hang.
        if not script.is_file():
            return False
        content = launchscript._read_as_the_shell_does(script, _SCRIPT_READ_LIMIT)
    except OSError:
        return False
    # `split("\n")`, not `splitlines()` — see `launchscript.write`. A flag value carrying \x85 or
    # \u2028 would otherwise split the exec line here but not in the shell, and this row would go
    # unattributed while the container it names is torn down.
    # From `exec ` to the END of the file, not to the end of its first physical line. A flag value
    # may contain a newline — single quotes span lines in sh — so the exec STATEMENT is not always
    # one line, and splitting on lines would hand `shlex` an unterminated quote and lose the row.
    # Two cases rather than one clever index. The single-expression version used -1 to mean "the
    # file opens with `exec `", which is the SAME value `str.find` returns for "not found" — so the
    # not-found guard swallowed that branch and it never ran. A sentinel that collides with a real
    # answer is a bug even when the colliding input is rare.
    if content.startswith("exec "):
        statement = content[len("exec "):]
    else:
        index = content.find("\nexec ")
        if index == -1:
            return False
        statement = content[index + len("\nexec "):]
    try:
        script_tokens = shlex.split(statement)
    except ValueError:
        return False
    return any(
        a == _STACK_FLAG[0] and b == stack for a, b in itertools.pairwise(script_tokens)
    )


def forget_stack(verb: str, stack: str, *, background: bool = True) -> None:
    """Drop the sessions for a stack after its instances are torn down. Never raises.

    Scoped to ONE verb because `harnessed rm` is container-scoped: it removes every container
    instance of a stack across harnesses and projects, and leaves host-native sessions — which own
    no container — alone. Removing by session id, not title, so a user-renamed row still matches.

    TWO ROW SHAPES, because the stack is no longer IN the command (bd harnessed-7mt):

      * `--stack <name>` pair — the raw `command_for` shape. Matched on the PAIR rather than a token
        index: the stack used to be the third token, which a prefix compare could check; it is a
        flag value sitting after the harness and path, so its position varies with whether a project
        path was recorded.
      * `<path>/<harness>-<verb> --` — what `replay_command` writes now. It names NO stack,
        deliberately: putting one back would re-key every row whenever the flag set changed, which
        is the identity property the switch away from `mise run` was protecting. The stack is
        instead read out of the launcher script the row points at — the same file the row runs, so a
        row matches this cleanup exactly when it would have started the stack being removed.

    NOT matched by title. `--aoe-title` overrides the derived title, so a titled row would escape
    cleanup and a coincidentally-titled foreign row could be caught by it.

    A replay row whose record is missing or names another stack is LEFT ALONE. Removing rows we
    cannot positively attribute to this stack is the one failure mode worse than leaving a stale
    one — `harnessed rm` is destructive and unattended.
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
            # Two admissible shapes, and the launcher-script one does NOT start with `harnessed` —
            # it starts with a path. Gating on that prefix alone silently skipped every script row,
            # which is every row written since `--last` was retired: `harnessed rm` would tear the
            # containers down and leave their dashboard rows behind.
            if tokens[:2] != ["harnessed", verb] and not _is_launcher_script(tokens):
                continue
            if not (
                any(a == _STACK_FLAG[0] and b == stack for a, b in itertools.pairwise(tokens))
                or _replays_stack(tokens, verb, stack)
            ):
                continue
            sid = session.get("id")
            if sid:
                batch.append(["remove", str(sid), "-p", PROFILE])
        _apply(exe, batch, background=background)
    except Exception:  # noqa: BLE001 — cleanup is best-effort, same as registration.
        return
