"""Test helpers that do not depend on WHERE a symbol currently lives."""

from __future__ import annotations

import sys

from typing import Any


def patch_all(monkeypatch, name: str, value: Any) -> None:
    """Replace `name` in every loaded `harnessed.*` module that binds it.

    Use this instead of `monkeypatch.setattr(launcher, name, value)` for any helper that more than
    one module calls.

    A `from .x import y` import BINDS y into the importing module's globals, and a function resolves
    the names it calls in its OWN module's globals. So patching `launcher._runtime` only affects
    calls made from launcher.py — `svcstate` keeps calling the real one. That distinction is
    invisible at the call site and does not necessarily fail: when launcher.py was split, eleven
    tests kept passing while patching an attribute nothing read, because the real `_host_os()`
    returns "linux" on Linux anyway. They would have taken the macOS branch on a Mac.

    Patching every binding expresses what these tests actually mean — "this helper returns X for the
    duration of this test" — instead of "this helper returns X when called from one particular
    module", and it stays correct when the helper moves again (bd harnessed-4l8 is still splitting
    launcher.py).

    Raises if nothing binds the name, so a typo or a rename fails loudly instead of silently
    patching nothing — which is the exact failure this helper exists to prevent.
    """
    patched = [
        module
        for module in list(sys.modules.values())
        if getattr(module, "__name__", "").startswith("harnessed.") and name in vars(module)
    ]
    if not patched:
        raise AssertionError(
            f"no loaded harnessed module binds {name!r} — it was renamed, or the module that "
            f"defines it has not been imported yet"
        )
    for module in patched:
        monkeypatch.setattr(module, name, value)
