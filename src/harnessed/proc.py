"""Run a subprocess, and say what is happening while parallel builds are interleaving output.

`_say` tags each line with the build it belongs to, because several stack builds run concurrently
and untagged output from three builds at once is unreadable. `_run` and `_run_tagged` are the two
subprocess shapes the rest of the CLI needs: one that inherits the terminal, one that folds its
output into the tagged stream.

Shared by launcher.py and by every module extracted out of it, which is why it cannot live in
launcher.py — a module importing it from there would invert the dependency.
"""
from __future__ import annotations

import subprocess

from contextvars import ContextVar

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


def _run(cmd: list[str], check: bool = True, **kwargs) -> subprocess.CompletedProcess:
    tag = _BUILD_TAG.get()
    # Only the plain streaming case can be tagged: a caller that captures output (capture_output /
    # explicit stdout=) wants the bytes back, not printed, so leave those exactly as they were.
    streamable = tag is not None and not kwargs.get("capture_output") and "stdout" not in kwargs
    if streamable:
        return _run_tagged(cmd, check=check, **kwargs)
    try:
        return subprocess.run(cmd, check=check, **kwargs)
    except subprocess.CalledProcessError as exc:
        # Captured output is otherwise swallowed — surface it so failures read as an error,
        # not a bare traceback (e.g. "name already in use: pod already exists").
        for label, stream in (("stdout", exc.stdout), ("stderr", exc.stderr)):
            text = stream.decode(errors="replace") if isinstance(stream, (bytes, bytearray)) else (stream or "")
            if text.strip():
                _err.print(f"[bold red]{label}:[/bold red] {text.strip()}")
        raise


def _run_tagged(cmd: list[str], check: bool = True, **kwargs) -> subprocess.CompletedProcess:
    """Run `cmd`, printing each output line prefixed with the current build tag.

    stderr is folded into stdout so a build's diagnostics stay in ITS lane rather than racing to the
    terminal unprefixed. rich's Console holds an internal lock, so concurrent workers never tear a
    line. Output is `escape`d: podman prints things like `[1/2] STEP` that rich would otherwise eat
    as markup.
    """
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, errors="replace", bufsize=1, **kwargs,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        _say(escape(line.rstrip()))
    returncode = proc.wait()
    if check and returncode != 0:
        raise subprocess.CalledProcessError(returncode, cmd)
    return subprocess.CompletedProcess(cmd, returncode)
