"""Run a subprocess, and say what is happening while parallel builds are interleaving output.

`_say` tags each line with the build it belongs to, because several stack builds run concurrently
and untagged output from three builds at once is unreadable. `_run`, `_run_tagged` and `_bounded`
are the three subprocess shapes the rest of the CLI needs: one that inherits the terminal, one that
folds its output into the tagged stream, and one that refuses to wait forever.

Shared by launcher.py and by every module extracted out of it, which is why it cannot live in
launcher.py — a module importing it from there would invert the dependency.
"""
from __future__ import annotations

import subprocess
import threading

from contextvars import ContextVar, copy_context

from rich.markup import escape

from .console import _err, _out

# --- parallel build logging -----------------------------------------------------------------
# When several stacks build concurrently their podman output interleaves into mush, so each build
# runs under a TAG — a (label, colour) pair set by the worker thread. `_run` and `_say` prefix every
# line with it, which is what makes N concurrent build logs readable in one terminal. Unset (the
# default) means a serial build: output streams through untouched, exactly as before.
_BUILD_TAG: ContextVar[tuple[str, str] | None] = ContextVar("_BUILD_TAG", default=None)


def _say(msg: str) -> None:
    """Print a build message, prefixed with the current build's tag when one is set.

    highlight=False on the tagged path: rich's auto-highlighter styles things that merely LOOK like
    code, and it reads a tag like `mystack(omp)` as a function call — splitting it into differently
    styled fragments mid-word. It does the same to podman's build output (paths, numbers, brackets).
    A build log should come out the way podman wrote it.
    """
    tag = _BUILD_TAG.get()
    if tag is None:
        _out.print(msg)
        return
    label, color = tag
    _out.print(f"[{color}]{label:>34}[/{color}] [dim]│[/dim] {msg}", highlight=False)


# A hung child reports the code GNU `timeout(1)` uses, because every call site that needs a deadline
# already branches on "non-zero means it did not work" — and a wedged podman IS a failed podman.
# Routing a hang into the branch that exists beats inventing a second failure path per site.
_TIMEOUT_RC = 124


def _bounded(
    cmd: list[str], *, timeout: float, warn: bool = True, **kwargs
) -> subprocess.CompletedProcess:
    """Run `cmd` with a deadline, and NEVER raise `TimeoutExpired` (bd harnessed-1ao).

    On expiry the child is killed and a `CompletedProcess` comes back with `returncode`
    `_TIMEOUT_RC` and empty output — `""` or `b""`, matching what the caller asked for, because
    callers do both `res.stdout.strip()` and `res.stdout.decode(...)` and `None` would crash the
    very path meant to degrade.

    Not raising is the point. These calls sit in `finally:` teardowns and in poll loops, where an
    escaping exception would replace the failure already in flight with a complaint about the
    cleanup. The cost is that a command which genuinely exits 124 is indistinguishable by return
    code alone; podman does not, and the warning below is what tells the two apart in a log.
    """
    try:
        return subprocess.run(cmd, timeout=timeout, **kwargs)
    except subprocess.TimeoutExpired:
        if warn:
            # "warning:" is deliberate: console._WARN_MARKER matches it, so _acknowledge_warnings
            # surfaces this before the TTY handoff, where it would otherwise vanish behind the
            # agent's fullscreen renderer.
            _err.print(
                f"[bold red]warning:[/bold red] `{escape(' '.join(cmd))}` did not respond within "
                f"{timeout}s and was killed — treating it as a failure."
            )
        # text=/encoding=/universal_newlines= are the three ways a caller asks for str.
        wants_str = bool(
            kwargs.get("text") or kwargs.get("encoding") or kwargs.get("universal_newlines")
        )
        empty: str | bytes = "" if wants_str else b""
        return subprocess.CompletedProcess(cmd, _TIMEOUT_RC, empty, empty)


def _run(cmd: list[str], check: bool = True, **kwargs) -> subprocess.CompletedProcess:
    """Run `cmd`, streaming to the terminal (or into the tagged build log when a tag is set).

    Imposes no deadline of its own — a `podman build` is dominated by network and layer cache, and
    a wrong number here breaks working builds. Callers opt in with `timeout=`, which reaches
    `subprocess.run` and `_run_tagged` alike.
    """
    tag = _BUILD_TAG.get()
    # Only the plain streaming case can be tagged: a caller that captures output (capture_output /
    # explicit stdout=) wants the bytes back, not printed, so leave those exactly as they were.
    streamable = tag is not None and not kwargs.get("capture_output") and "stdout" not in kwargs
    if streamable:
        return _run_tagged(cmd, check=check, **kwargs)
    try:
        # unbounded: by design — see the docstring. `timeout=` arrives via kwargs when a caller
        # wants one, so this is a policy-free passthrough, not an unguarded call.
        return subprocess.run(cmd, check=check, **kwargs)
    except subprocess.CalledProcessError as exc:
        # Captured output is otherwise swallowed — surface it so failures read as an error,
        # not a bare traceback (e.g. "name already in use: pod already exists").
        for label, stream in (("stdout", exc.stdout), ("stderr", exc.stderr)):
            text = stream.decode(errors="replace") if isinstance(stream, (bytes, bytearray)) else (stream or "")
            if text.strip():
                _err.print(f"[bold red]{label}:[/bold red] {text.strip()}")
        raise


def _run_tagged(
    cmd: list[str], check: bool = True, timeout: float | None = None, **kwargs
) -> subprocess.CompletedProcess:
    """Run `cmd`, printing each output line prefixed with the current build tag.

    stderr is folded into stdout so a build's diagnostics stay in ITS lane rather than racing to the
    terminal unprefixed. rich's Console holds an internal lock, so concurrent workers never tear a
    line. Output is `escape`d: podman prints things like `[1/2] STEP` that rich would otherwise eat
    as markup.

    `timeout` exists so `_run(cmd, timeout=…)` means the same thing on both paths. It cannot be
    forwarded to `Popen`, which has no such parameter — before bd harnessed-1ao that call raised
    TypeError, so whether a deadline worked depended on whether a parallel build tag happened to be
    set. It is enforced by `wait(timeout=…)` instead (see below), and the `TimeoutExpired` that
    escapes is the stdlib's own, keeping the two shapes interchangeable for callers.
    """
    # unbounded: `Popen` HAS no timeout parameter — starting a process does not block. This call's
    # deadline is enforced on the `wait(timeout=…)` below, which is the only part that waits.
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, errors="replace", bufsize=1, **kwargs,
    )
    # NO WATCHDOG TIMER. The obvious design — a threading.Timer that kills the child — cannot be made
    # correct here, and a first attempt at it shipped the bug: whatever flag the timer and this
    # thread share, there is a window between `wait()` returning and this thread claiming that flag
    # in which the timer fires, decides the child is late, and reports a timeout for a build that
    # SUCCEEDED. Narrowing the window with a lock does not close it; it just makes the false timeout
    # rarer and harder to reproduce, which is worse.
    #
    # So the deadline goes where the stdlib already implements it correctly: `wait(timeout=…)`. That
    # needs the pipe drained by someone else, because a full pipe blocks the child and `wait` would
    # deadlock — hence the pump thread. `copy_context()` carries `_BUILD_TAG` across the thread
    # boundary; a ContextVar is NOT inherited by a bare `threading.Thread`, and without this every
    # line of a parallel build would lose its tag and come out unprefixed.
    assert proc.stdout is not None  # noqa: S101 — narrows for the checker; Popen was given stdout=PIPE just above
    stdout = proc.stdout

    def _pump() -> None:
        for line in stdout:
            _say(escape(line.rstrip()))

    pump = threading.Thread(target=copy_context().run, args=(_pump,), daemon=True)
    pump.start()
    try:
        returncode = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()          # closes the pipe, which ends the pump
        proc.wait()          # reap, so no zombie outlives the call
        pump.join(timeout=5)
        raise
    pump.join(timeout=5)     # let the tail of the output land before the caller moves on
    if check and returncode != 0:
        raise subprocess.CalledProcessError(returncode, cmd)
    return subprocess.CompletedProcess(cmd, returncode)
