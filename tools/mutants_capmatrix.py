#!/usr/bin/env python3
"""Mutation check for the capability-matrix wiring (bd harnessed-0tk.2).

Run: tools/mutants_capmatrix.py

Each mutant is a real bug a future edit could plausibly introduce. The suite must FAIL on every one
of them; a mutant that survives means the tests covering it assert nothing.

This file exists because the first version of these tests did not catch the first two mutants below.
They matched source TEXT with `inspect.getsource`, so a call site wrapped in `if False:` — the
feature switched off — left the whole file green. A score with no re-runnable command is not
evidence, so the score now has one.

Restores every file it touches and verifies the tree came back clean with `git diff`.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = "src/harnessed/launcher.py"
CAPMATRIX = "src/harnessed/capmatrix.py"
TESTS = "tests/test_capmatrix.py"

HOST_CALL = "    _warn_capability_gaps(HostBackend.name, host_recipes)"
CONTAINER_CALL = "    _warn_capability_gaps(ContainerBackend.name, launch_recipes)"

# (label, file, find, replace)
MUTANTS = [
    ("host call site disabled by a dead-code guard", LAUNCHER, HOST_CALL,
     "    if False:\n    " + HOST_CALL),
    ("container call site disabled by a dead-code guard", LAUNCHER, CONTAINER_CALL,
     "    if False:\n    " + CONTAINER_CALL),
    ("host call site deleted", LAUNCHER, HOST_CALL, "    pass"),
    ("container call site deleted", LAUNCHER, CONTAINER_CALL, "    pass"),
    ("host egress cell flipped to SUPPORTED (feature off)", CAPMATRIX,
     '        "egress": DEGRADED,', '        "egress": SUPPORTED,'),
    ("gap detection inverted", CAPMATRIX,
     "            if column.get(primitive) == DEGRADED:",
     "            if column.get(primitive) == SUPPORTED:"),
    ("only the first gap per recipe reported", CAPMATRIX,
     "        for primitive in sorted(declared_primitives(recipe)):",
     "        for primitive in sorted(declared_primitives(recipe))[:1]:"),
    ("mcp service refs no longer count as declaring services", CAPMATRIX,
     '    if recipe.services or any(getattr(s, "service", None) for s in recipe.servers):',
     "    if recipe.services:"),
    ("unknown backend returns [] instead of raising", CAPMATRIX,
     "        raise KeyError(", "        return []  # noqa\n    if False:\n        raise KeyError("),
]


def run_suite() -> bool:
    """True when the suite passes."""
    proc = subprocess.run(
        ["tools/run-tests.sh", TESTS], cwd=ROOT, capture_output=True, text=True
    )
    return proc.returncode == 0


def restore(rel: str) -> None:
    subprocess.run(["git", "checkout", "--", rel], cwd=ROOT, check=True)


def dirty() -> bool:
    """True when any TRACKED file differs from HEAD, staged or not.

    `git diff --quiet` was the wrong instrument: it compares the worktree to the INDEX, so a staged
    modification reads as clean, and then the "restored clean" line at the end would be a claim
    about nothing. `-uno` keeps untracked files — a stray `.coverage` — from blocking a run they
    cannot corrupt.
    """
    proc = subprocess.run(
        ["git", "status", "--porcelain", "-uno"], cwd=ROOT, capture_output=True, text=True
    )
    return bool(proc.stdout.strip())


def current_branch() -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT, capture_output=True, text=True
    )
    return proc.stdout.strip()


def main() -> int:
    branch = current_branch()
    if branch in ("main", "master"):
        print(
            f"refusing to run on '{branch}': this rewrites tracked files in place, and an "
            "interrupted run would leave the canonical checkout dirty. Run it in a worktree."
        )
        return 2

    if dirty():
        print("refusing to run: tracked files differ from HEAD, so restores would be unverifiable")
        return 2

    print("baseline: ", end="", flush=True)
    if not run_suite():
        print("FAILS — fix the suite before trusting any mutation score")
        return 2
    print("green")

    survivors = []
    for label, rel, find, replace in MUTANTS:
        target = ROOT / rel
        original = target.read_text(encoding="utf-8")
        if original.count(find) != 1:
            print(f"SKIP  {label}: anchor matched {original.count(find)} times, not 1")
            survivors.append(label + " (anchor stale)")
            continue
        target.write_text(original.replace(find, replace), encoding="utf-8")
        # finally, not a plain sequence: a KeyboardInterrupt or a crash inside the suite must not
        # leave a deliberately broken source file behind in someone's checkout.
        try:
            killed = not run_suite()
        finally:
            restore(rel)
            assert target.read_text(encoding="utf-8") == original, f"restore failed for {rel}"
        print(f"{'KILLED' if killed else 'SURVIVED'}  {label}")
        if not killed:
            survivors.append(label)

    if dirty():
        print("ERROR: tree left dirty after restore")
        return 2

    print(f"\n{len(MUTANTS) - len(survivors)}/{len(MUTANTS)} killed, tree restored clean")
    if survivors:
        print("SURVIVORS:")
        for s in survivors:
            print(f"  - {s}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
