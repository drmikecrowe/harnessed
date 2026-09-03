"""The two process-wide Consoles harnessed's CLI prints through.

They live here rather than in `launcher` so that a module extracted OUT of launcher can report an
error on the SAME console instance instead of constructing a second one. Two consoles would mean two
warning counters, and `_acknowledge_warnings` reads one of them — a warning printed through the copy
would be silently dropped from the count. The dependency direction is the one the split requires:
launcher and its extracted modules both import from here, and this module imports neither.
"""
from __future__ import annotations

import re
import sys

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


def exec_mode() -> bool:
    """Whether this is an `-exec` invocation. Read it, never the global — `set_exec_mode` rebinds
    the module attribute, so a `from … import _EXEC_MODE` would freeze the launch's first answer."""
    return _EXEC_MODE


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
