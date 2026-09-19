"""The launcher script a launch leaves in the project folder, and its git exclude entry.

Replaces `lastrun` and `--last` (bd harnessed-7mt superseded). That record held the same facts and
held them INVISIBLY: nothing printed it, so "what did I launch here" meant reading shell history.
The replacement is a file you can `cat`, run, and extend — `./claude-serena-container --fresh`.

THE TRAILING `--` DOES NOT LIVE IN THIS FILE, and that is the whole design. `aoe.command_for` ends
with a separator so aoe's appended `--resume <id>` sails past harnessed's own option parsing to the
agent (see that function's note; it cost a respawn loop to learn). Put that separator in the script
and every flag a human adds — `./claude-serena-container --fresh` — lands past the parser too and
reaches the agent instead of harnessed. So the script ends with `"$@"` and the aoe ROW ends with `--`:
the row invokes `<script> --`, the separator arrives as the script's own argument, and both the
human flag and the agent flag reach the process they were meant for.

QUOTING IS `command_for`'S, NEVER OURS. The exec line is that function's output with the separator
removed, so a hostile `--aoe-title` is escaped by the same `shlex.join` the aoe row already relies
on. Re-quoting here would be a second implementation of an escaping rule, which is the shape that
drifts.

NEVER FATAL. Inherited from the record this replaces: a launch that got this far has already done
the useful work, and losing the shortcut is not worth killing it. Every failure path returns None.
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Optional

from . import aoe, paths
from .schema import HARNESS_CONFIG_DIR

# Line 2 of every script we write, and the licence to overwrite one. A file without it belongs to
# somebody else — see `write`.
SENTINEL = "# harnessed:launcher v1"

_SHEBANG = "#!/bin/sh"
_TYPED = "# as typed: "

# The provenance comment is the one place user argv reaches a file, and argv is bounded only by
# ARG_MAX (~2MB on Linux). A megabyte-long comment line is not a security problem — it is display
# only and never executed — but it is an unbounded write into somebody's repo, so it is capped and
# marked when it is cut. Long enough for any real launch: the longest plausible one is a dozen
# `--recipe` names.
_TYPED_LIMIT = 2048
_TRUNCATED = " ... (truncated)"

# How much of an EXISTING file `write` reads to check for the sentinel. Only the first two lines
# matter (~40 bytes for a file we wrote), but the file in the way can be anything at all — the read
# is bounded so that a huge one cannot raise `MemoryError`, which `write`'s `except OSError` does not
# catch and which would therefore break this module's "every failure path returns None" contract.
# `aoe._replays_stack` bounds the same call for the same reason; this site did not, until an
# adversarial review noticed the asymmetry.
_SENTINEL_READ_LIMIT = 4096

# The same bound for `info/exclude`. A real one is a few kilobytes; the cap exists because the
# "never raises" contract is unconditional and `MemoryError` is not an `OSError`. Past the cap the
# membership check cannot be trusted, and appending blind would add a duplicate line on EVERY
# launch — so the entry is skipped instead. Losing one entry costs an un-ignored file; a duplicate
# per launch corrupts a file that every worktree of the checkout shares.
_EXCLUDE_READ_LIMIT = 1024 * 1024

# `host-run` -> `claude-serena-host`. The verb AND the stack sit in the FILENAME rather than in
# flags, so neither two backends nor two stacks can collide in one folder, and an aoe row cannot
# restart something it does not name.
_VERB_SUFFIX = {"host-run": "host", "container-run": "container"}

# The closed set the LAST field of a name is checked against. Derived from `_VERB_SUFFIX` rather
# than spelled out again, so a third backend cannot arrive in one and be missing from the other.
_BACKENDS = frozenset(_VERB_SUFFIX.values())

_GIT_TIMEOUT = 5


def script_name(verb: str, stack: str, harness: str) -> str:
    """`claude-serena-host` / `claude-serena-container`.

    THREE FIELDS, and the order is not cosmetic. The harness leads, because `codex-serena-host` is a
    different launcher rather than a variant of this one. The stack follows, because within one
    harness it is what the reader is choosing between. The backend is last and is a closed set,
    which is what lets `parse_script_name` read the name from both ends.

    THE STACK WAS ADDED AFTER THE VERB, and it closes the same class of bug one level down. While
    the name omitted it, one project plus one harness plus one backend meant ONE file: a second
    stack overwrote the first, and the aoe row pointing at that file went on replaying the newcomer
    under the older stack's label. Only the FLAG was ever deliberately kept out of the identity key
    (see `aoe.replay_command`); the collapse it caused was not.

    Argument order follows this module's convention, `(verb, stack, harness, ...)`, rather than the
    order the fields appear in the result. `write`, `aoe.command_for` and `aoe.title_for` all take
    it that way.
    """
    return f"{harness}-{stack}-{_VERB_SUFFIX[verb]}"


def parse_script_name(name: str) -> Optional[tuple[str, str, str]]:
    """The inverse of `script_name`: `(harness, stack, backend)`, or None when `name` is not ours.

    HERE, BESIDE `script_name`, deliberately. This grammar used to be written twice — once to build
    a name, and once inside `aoe._is_launcher_script` to take one apart — and the second copy called
    nothing in the first. No call edge joined them, so no tool could find them together and a change
    to either was invisible from the other. One grammar, one place.

    READ FROM BOTH ENDS, which is what makes a stack name containing `-` or `.` unambiguous:

      * the harness is the field before the FIRST `-`, and no harness name contains one;
      * the backend is the field after the LAST `-`, and neither `host` nor `container` does;
      * the stack is everything between, and it must not be empty.

    Both outer fields are checked against their closed sets, never merely required to be present —
    the same narrowness `_is_launcher_script` already applied, for the same reason: a user's own
    `./run-dev` must never read as ours.

    RETURNS NONE FOR THE LEGACY TWO-PART NAME (`claude-host`), whose stack field comes back empty.
    This function reads the THREE-part grammar only; `parse_legacy_script_name` reads the other one,
    and `aoe._is_launcher_script` accepts either.

    AN EARLIER REVISION JUSTIFIED THAT SPLIT WRONGLY, and the wrong reason is worth recording because
    it is the plausible one. It read: the old name carries no stack, so nothing can attribute it to
    one. That is false. Attribution never came from the filename — `aoe._replays_stack` reads the
    `--stack` value out of the script's exec line, so a legacy-named file is perfectly attributable.
    Acting on the wrong reason made every pre-rename row un-removable by `harnessed rm`, which
    adversarial review caught. The split is a grammar boundary, not an attribution rule.
    """
    harness, _, rest = name.partition("-")
    stack, _, backend = rest.rpartition("-")
    if harness not in HARNESS_CONFIG_DIR or backend not in _BACKENDS or not stack:
        return None
    return harness, stack, backend


def parse_legacy_script_name(name: str) -> Optional[tuple[str, str]]:
    """The RETIRED two-part name — `(harness, backend)` for `claude-host`, else None.

    NOTHING WRITES THIS SHAPE, and it is still read. That is the same rule `aoe._is_ours` already
    applies to the `mise run <harness> --` shape it retired before this one, and it exists for the
    same reason: drift against a row we do not recognise is only ever REPORTED, so forgetting a
    shape we once wrote strands every row carrying it. A stranded row is worse than a stale one,
    because one foreign row at the (title, path) key blocks the whole registration — the user
    relaunches and gets no row at all, plus a warning that harnessed did not write their own row.
    Retiring a shape means we stop WRITING it, never that we forget we wrote it.

    HERE RATHER THAN IN `aoe`, so that all three name grammars — build, read, and read-the-old-one —
    sit together and cannot drift apart. The previous arrangement kept the reader in `aoe` with no
    call edge to the builder, which is exactly the coupling this module now refuses to repeat.

    SEPARATE FROM `parse_script_name` AS A GRAMMAR, not as a policy. Two shapes, two readers, so that
    neither has to branch. Callers decide what to do with each: `aoe._is_launcher_script` accepts
    either, because both a repair and a teardown reach a launcher row the same way, and the stack
    comes from the script's exec line in both cases.

    An earlier revision made this a POLICY boundary — legacy names readable for repair and refused
    for teardown — on the reasoning that a name with no stack cannot be attributed to one. The
    reasoning was wrong (see `parse_script_name`) and the effect was pre-rename rows that
    `harnessed rm` could never clean up.
    """
    harness, _, backend = name.rpartition("-")
    if harness not in HARNESS_CONFIG_DIR or backend not in _BACKENDS:
        return None
    return harness, backend


def script_backend(name: str) -> Optional[str]:
    """The backend field of EITHER launcher-name shape, or None when the name is not one of ours.

    The one question both aoe callers actually ask. `_is_launcher_script` asks "is this a launcher
    row at all" (is this not None), and `_replays_stack` asks "does it name the backend I am tearing
    down" (does this equal the verb's suffix). Neither needs the harness or the stack.

    ONE FUNCTION BECAUSE TWO LEFT DEAD CODE. Written as a branch inside `_replays_stack` — try the
    three-part parse, else the legacy one, else bail — the final bail was unreachable: its caller had
    already accepted one of the two grammars, so the third case could not happen. Changed-line
    coverage caught it as one uncovered line. Returning None here instead means an unrecognised name
    simply fails the equality check at the call site, with no branch to leave untested.
    """
    parsed = parse_script_name(name)
    if parsed is not None:
        return parsed[2]
    legacy = parse_legacy_script_name(name)
    return legacy[1] if legacy is not None else None


def _git(project_path: Path, *args: str) -> Optional[subprocess.CompletedProcess[str]]:
    """Run git in the project, or None if git is absent or the call did not complete."""
    try:
        return subprocess.run(
            ["git", "-C", str(project_path), *args],
            capture_output=True, text=True, timeout=_GIT_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _is_tracked(project_path: Path, name: str) -> bool:
    """Whether git tracks this path. A tracked file belongs to the repo, not to us."""
    result = _git(project_path, "ls-files", "--error-unmatch", "--", name)
    return result is not None and result.returncode == 0


def _read_as_the_shell_does(path: Path, limit: Optional[int] = None) -> str:
    """Read a shell script exactly as `/bin/sh` will see it.

    TWO things Python does by default disagree with the shell about where a line ends, and both bite
    only when a flag VALUE carries an odd character — so both survive every ordinary test:

      1. `newline=None` (the default) is universal-newline mode: a lone `\r` inside a quoted value
         is TRANSLATED to `\n` on read. The file on disk is fine; the reader invents a line break
         the shell will never act on. Found by a property test at `title='\r'`.
      2. `str.splitlines()` additionally breaks on `\x0b \x0c \x1c \x1d \x1e \x85 \u2028
         \u2029`. `/bin/sh` breaks on `\n` alone.

    So: `newline=""` here, and `split("\n")` at every call site. Callers that get this wrong read a
    different script than the one that runs — a shifted sentinel check in `write`, an unattributable
    aoe row in `aoe._replays_stack`.
    """
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        return handle.read() if limit is None else handle.read(limit)


def _sanitize(text: str) -> str:
    """Strip anything that could end the comment line or drive the reader's terminal.

    A newline here would let an argv value close the comment and have the next line executed, which
    is the one way a display-only field becomes code.
    """
    return "".join(ch for ch in text if ch.isprintable() or ch == "\t")


def _body(
    verb: str, stack: str, harness: str, project_path: Path,
    *, group: Optional[str], title: Optional[str], no_strict_mcp: bool, argv: Optional[list[str]],
) -> str:
    command = aoe.command_for(
        verb, stack, harness, project_path,
        group=group, title=title, no_strict_mcp=no_strict_mcp,
    )
    args = shlex.split(command)
    # The separator `command_for` appends for the aoe row. It moves to the ROW, not the file — see
    # the module docstring. Popped defensively rather than assumed, so a future change there cannot
    # silently leave a separator in the script.
    if args and args[-1] == "--":
        args.pop()

    lines = [_SHEBANG, SENTINEL]
    if argv:
        typed = _sanitize(shlex.join(argv))
        if len(typed) > _TYPED_LIMIT:
            typed = typed[:_TYPED_LIMIT - len(_TRUNCATED)] + _TRUNCATED
        lines.append(_TYPED + typed)
    lines.append(f"exec {shlex.join(args)} \"$@\"")
    return "\n".join(lines) + "\n"


def write(
    verb: str, stack: str, harness: str, project_path: Path,
    *, group: Optional[str] = None, title: Optional[str] = None, no_strict_mcp: bool = False,
    argv: Optional[list[str]] = None,
) -> Optional[Path]:
    """Write `<project>/<harness>-<stack>-<verb>` and ensure its git exclude entry. Never raises.

    Returns the path written, or None when nothing was written — a foreign file in the way, a
    read-only folder, any OSError. None is not an error the caller should act on; the launch
    proceeds either way.
    """
    try:
        project_path = Path(project_path).resolve()

        # ONE PATH COMPONENT, or nothing is written. The stack name reaches a filesystem path here
        # and nowhere else in this module, and `write` is a plain function taking a `str`.
        #
        # An earlier revision of this change argued that no check was needed, because `script_name`
        # always prefixes `{harness}-` so the result can never be absolute and the join can never be
        # replaced. Both halves are true and neither is containment: a RELATIVE traversal needs no
        # absolute path. Adversarial review demonstrated it — with `<project>/claude-x` present, a
        # stack of `x/../../evil` writes `<project>/claude-x/../../evil-host`, which resolves ABOVE
        # the project folder. Reachability upstream (`paths.catalog_relpath` refuses `.`, `..` and a
        # third component) is a reason the bug is not live today, never a reason this is correct.
        #
        # Returns None like every other refusal here: never fatal, and a launch that cannot get a
        # safe filename is better off without the shortcut.
        if not stack or stack in (".", "..") or stack != Path(stack).name:
            return None

        target = project_path / script_name(verb, stack, harness)

        if target.exists():
            # NOT A REGULAR FILE: refuse before touching it. A FIFO passes `exists()` and BLOCKS on
            # open until a writer appears, so reading it to check the sentinel hangs the launch
            # forever — and `except OSError` cannot catch a hang. Refusing also means we never
            # clobber a directory or a socket somebody put here on purpose.
            #
            # Seventh instance of one class in this change, and the same guard `_ensure_excluded`
            # applies seventy lines below. Every path that arrives from outside gets checked for
            # WHAT IT IS before it is read.
            if not target.is_file():
                return None
            # Two separate refusals, and the tracked one applies EVEN to a file carrying our
            # sentinel: committing a generated launcher is a choice a repo is allowed to make, and
            # rewriting it on every launch would produce a dirty tree nobody asked for.
            try:
                head = _read_as_the_shell_does(target, _SENTINEL_READ_LIMIT).split("\n")[:2]
            except OSError:
                return None
            if SENTINEL not in head:
                return None
            if _is_tracked(project_path, target.name):
                return None

        target.write_text(
            _body(
                verb, stack, harness, project_path,
                group=group, title=title, no_strict_mcp=no_strict_mcp, argv=argv,
            ),
            encoding="utf-8",
        )
        target.chmod(0o755)
        _ensure_excluded(project_path, target)
        return target
    except OSError:
        return None


def _exclude_pattern(project_path: Path, target: Path) -> Optional[str]:
    """The root-anchored pattern for this script, or None when it cannot be derived.

    ANCHORED FROM THE WORKTREE ROOT, not from the common dir's parent. `info/exclude` lives in the
    COMMON dir — one file shared by every worktree — but git matches its patterns against the top of
    whichever working tree it is processing. So `/claude-host` written from one worktree correctly
    covers the same-named file at every sibling worktree's root, which is what we want, while
    `.bare/.claude/worktrees/<name>/claude-host` (what the common dir's parent would produce in a
    bare + linked-worktree layout) would match in none of them.

    Fails CLOSED: no pattern rather than a wrong one, because a wrong pattern in a file shared by
    every worktree is worse than no entry at all.
    """
    result = _git(project_path, "rev-parse", "--path-format=absolute", "--show-toplevel")
    if result is None or result.returncode != 0:
        return None
    toplevel = Path(result.stdout.strip())
    if not toplevel.name:
        return None
    try:
        relative = target.resolve().relative_to(toplevel.resolve())
    except ValueError:
        return None
    return "/" + relative.as_posix()


def _ensure_excluded(project_path: Path, target: Path) -> None:
    """Append the script's pattern to the common dir's `info/exclude`, once. Never raises.

    Idempotent by exact-line match: ten launches leave one line. A non-git folder has no exclude
    file and gets no warning — there is nothing there to exclude from.
    """
    common = paths.git_common_dir(project_path)
    if common is None:
        return
    pattern = _exclude_pattern(project_path, target)
    if pattern is None:
        return
    exclude = common / "info" / "exclude"
    try:
        # `is_file()`, not `exists()`: a FIFO at this path passes `exists()`, and reading it would
        # block the launch until something else wrote to it.
        if exclude.exists() and not exclude.is_file():
            return
        # Same `newline=""` reason as the script reader: git's exclude grammar is newline
        # separated, and a translated `\r` would make an existing pattern look absent and be
        # appended a second time on every launch. BOUNDED for the reason at `_EXCLUDE_READ_LIMIT`;
        # reading one byte past the cap is how we detect that we are past it.
        existing = (
            _read_as_the_shell_does(exclude, _EXCLUDE_READ_LIMIT + 1) if exclude.is_file() else ""
        )
        if len(existing) > _EXCLUDE_READ_LIMIT:
            return
        # `split("\n")` for the reason given in `write`: git's exclude grammar is newline
        # separated, and `splitlines()` would treat several other characters as separators too.
        if pattern in existing.split("\n"):
            return
        exclude.parent.mkdir(parents=True, exist_ok=True)
        # Guard the newline rather than assume one: git reads `*.log/claude-host` as a single
        # pattern and silently stops excluding both.
        prefix = "" if (existing == "" or existing.endswith("\n")) else "\n"
        # `newline=""` for symmetry with every other reader and writer of newline-delimited content
        # here. It is a no-op on Linux, where os.linesep is already "\n" — stated so the next reader
        # does not have to work out why this one site is the exception.
        with exclude.open("a", encoding="utf-8", newline="") as handle:
            handle.write(f"{prefix}{pattern}\n")
    except OSError:
        return
