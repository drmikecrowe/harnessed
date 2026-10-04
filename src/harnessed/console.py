"""The two process-wide Consoles harnessed's CLI prints through.

They live here rather than in `launcher` so that a module extracted OUT of launcher can report an
error on the SAME console instance instead of constructing a second one. Two consoles would mean two
warning counters, and `_acknowledge_warnings` reads one of them — a warning printed through the copy
would be silently dropped from the count. The dependency direction is the one the split requires:
launcher and its extracted modules both import from here, and this module imports neither.
"""
from __future__ import annotations

import os
import re
import sys
from typing import Optional

from rich.console import Console

# Warnings printed during a launch are hidden the moment os.execvp hands the terminal over: Claude
# Code's fullscreen renderer draws on the ALTERNATE screen buffer, so everything harnessed printed
# is out of view for the whole session. Count warnings here rather than at the ~7 call sites, which
# use three different markers ("[WARNING]", "warning:", "WARNING") and whose exact output several
# tests assert on — this leaves every message byte-identical. _acknowledge_warnings() reads the
# counter just before the handoff.
_WARN_MARKER = re.compile(r"\bWARNING\b|\bwarning:", re.IGNORECASE)


class _WarnCountingConsole(Console):
    """A Console that remembers how many warnings it has printed."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.warnings = 0

    def print(self, *args, **kwargs) -> None:  # type: ignore[override]
        if args and isinstance(args[0], str) and _WARN_MARKER.search(args[0]):
            self.warnings += 1
        super().print(*args, **kwargs)


_out = _WarnCountingConsole()
_err = _WarnCountingConsole(stderr=True)


_EXEC_MODE = False
"""Set for the run of a `host-exec` / `container-exec` invocation (#450). See `_can_prompt`."""


def set_exec_mode(on: bool) -> None:
    """Declare whether this invocation has anyone at the keyboard. Called once, by the run verb.

    Here rather than in `launcher` for the same reason the consoles are: `setupenv._confirm_setup`
    has to read it, and importing launcher from there is the cycle this module exists to avoid.
    """
    global _EXEC_MODE
    _EXEC_MODE = on


def in_exec_mode() -> bool:
    """Whether this is an `-exec` invocation. Read it, never the global — `set_exec_mode` rebinds
    the module attribute, so a `from … import _EXEC_MODE` would freeze the launch's first answer."""
    return _EXEC_MODE


_ACP_STDOUT: Optional[int] = None
"""The real fd 1, saved while a `container-acp` launch has stdout pointed at stderr (#529)."""


def set_acp_mode(on: bool) -> None:
    """Point fd 1 at stderr for the rest of the launch, or put it back.

    Under `container-acp` stdout IS the JSON-RPC channel, so one stray `[INFO]` line corrupts it for
    the client. An fd swap rather than retargeting `_out`: podman build, pod create and every other
    child inherit fd 1, and a console swap would miss all of them. `restore_acp_stdout` hands the
    real fd back just before the harness takes it over.
    """
    global _ACP_STDOUT
    sys.stdout.flush()
    if on and _ACP_STDOUT is None:
        _ACP_STDOUT = os.dup(1)
        os.dup2(2, 1)
    elif not on and _ACP_STDOUT is not None:
        os.dup2(_ACP_STDOUT, 1)
        os.close(_ACP_STDOUT)
        _ACP_STDOUT = None


def in_acp_mode() -> bool:
    """Whether this is a `container-acp` invocation. Read it, never the global; see `in_exec_mode`."""
    return _ACP_STDOUT is not None


def acp_stdout() -> Optional[int]:
    """The saved real stdout under `container-acp`, else None (inherit). For a child that must speak
    on the client's channel without un-swapping the parent: the `--rm` attach still prints after it."""
    return _ACP_STDOUT


def restore_acp_stdout() -> None:
    """Give fd 1 back to the client's channel. Call immediately before the exec handoff."""
    set_acp_mode(False)


def _can_prompt() -> bool:
    """Whether harnessed may BLOCK this launch on a question the operator has to answer.

    `sys.stdin.isatty()` was the whole test, and it is still the right one for CI and for a piped
    launch. It is wrong for the `-exec` verbs: those run from a real terminal, with a real TTY, and
    still have nobody at the keyboard — the operator handed over a prompt and is waiting for an exit
    code. A `typer.prompt` there does not ask a question, it hangs a script.

    Every caller already has a correct non-interactive branch, because the non-TTY case was designed
    for. This makes `-exec` take that same branch rather than inventing a second policy per site.
    """
    return sys.stdin.isatty() and not _EXEC_MODE
