"""The two process-wide Consoles harnessed's CLI prints through.

They live here rather than in `launcher` so that a module extracted OUT of launcher can report an
error on the SAME console instance instead of constructing a second one. Two consoles would mean two
warning counters, and `_acknowledge_warnings` reads one of them — a warning printed through the copy
would be silently dropped from the count. The dependency direction is the one the split requires:
launcher and its extracted modules both import from here, and this module imports neither.
"""
from __future__ import annotations

import re

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
