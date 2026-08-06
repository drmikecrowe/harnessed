"""Test helpers that do not depend on WHERE a symbol currently lives."""

from __future__ import annotations

import os
import sys

from typing import Any

import pytest


# THE ONE DEFINITION OF THE PODMAN GATE (bd harnessed-3x1). Four test modules used to declare this
# themselves, identically, which is how the accounting in conftest.py came to match on skip REASON
# strings — there was no single thing to point at.
PODMAN_REQUESTED = os.environ.get("HARNESSED_PODMAN") == "1"


def podman(func):
    """Gate a test on `HARNESSED_PODMAN=1` and mark it as one the gate governs.

    The `live_podman` marker is what lets the run's accounting be honest. `conftest.py` asks a
    precise question — "did the tests this gate governs actually run?" — and a marker answers it
    where a skip reason cannot. The first version of that guard matched reasons and missed the
    image-precondition skips (`"<image> not built"`), which fire only when the gate is OPEN: a run
    could ask for live verification, skip them, and exit green. Broadening the pattern instead
    would have failed runs on unrelated skips. The marker has neither failure mode, and it travels
    with the test whichever decorator ends up doing the skipping — verified against pytest: a test
    skipped by a SECOND `skipif` stacked above still reports this marker.
    """
    gated = pytest.mark.skipif(
        not PODMAN_REQUESTED, reason="set HARNESSED_PODMAN=1 for live podman tests"
    )(func)
    return pytest.mark.live_podman(gated)


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

    DO NOT USE IT FOR A NAME WHOSE DEFINING MODULE ALSO CALLS IT INTERNALLY, unless you mean to
    replace those internal calls too. "Every module" includes the definition site. `assemble()` calls
    `load_stack_with_recipes` itself, so patch_all'ing that name hands assemble the test's fake stack
    instead of letting it do a real load — which is how a fake `Recipe` (whose `root` defaults to
    `.`) reached `validate_no_raw_npm` and made it scan every vendored package.json under the CWD.

    That one is worth remembering for how it FAILED: only a checkout containing the gitignored trees
    sees it, so it passed in a task worktree and broke on main. When a test wants to fake what ONE
    caller loads, patch that caller's module directly.
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
