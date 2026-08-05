#!/usr/bin/env python3
"""Mutation check for aoe command-drift detection and repair (bd harnessed-cn9).

Run: tools/mutants_aoe_drift.py

Each mutant is a real bug a future edit could plausibly introduce. The suite must FAIL on every one
of them; a mutant that survives means the tests covering it assert nothing.

This file exists because five of the tests in `TestCommandDrift` PASSED before the feature was
written — they assert that something bad does NOT happen (no `remove` issued, no extra read, no
exception), which is trivially true of code that does nothing at all. A green suite is not evidence
for that shape of test. These mutants are.

Two of them (M3, M5) target the destructive half specifically: `_is_ours` is the only thing standing
between a drifted row and `aoe remove`, and `remove` cannot be undone from harnessed's side.

Restores every file it touches and verifies the tree came back clean with `git diff`.
"""
from __future__ import annotations

import subprocess
import sys

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AOE = "src/harnessed/aoe.py"

# (label, file, find, replace)
MUTANTS = [
    # The scan itself: skip it, and we are back to the bug — the add is issued, aoe refuses it at
    # exit 0, the stale row survives unmentioned.
    ("drift scan disabled (the original bug restored)", AOE,
     "        stale = _drifted_row(sessions, command, project_path, row_title)",
     "        stale = None"),

    # The report: a launch that repairs silently is half the defect (the hours were lost to
    # silence, not to the stale row).
    ("drift is repaired but never reported", AOE,
     "            _report(on_drift, _drift_message(stale, command, repairing=repairing))",
     "            pass"),

    # THE DESTRUCTIVE GATE. Loosened, a row harnessed never wrote gets deleted on a launch.
    ("ownership gate always true (deletes foreign rows)", AOE,
     "    return any(tokens[:len(head)] == head for head in _OUR_COMMAND_HEADS)",
     "    return True"),

    # Off-by-one on the same gate: a prefix compare of the wrong width matches `mise` alone, and
    # `mise-en-place`-style neighbours stop being excluded by the second token.
    ("ownership gate compares only the first token", AOE,
     "    return any(tokens[:len(head)] == head for head in _OUR_COMMAND_HEADS)",
     "    return any(tokens[:1] == head[:1] for head in _OUR_COMMAND_HEADS)"),

    # Wrong row removed: the id is what scopes the destruction to the row we matched.
    ("repair removes a row that was not the matched one", AOE,
     '            repair = ["remove", str(sid), "-p", PROFILE]',
     '            repair = ["remove", "0", "-p", PROFILE]'),

    # Unrepairable drift must BLOCK the write, so `--create-aoe-only` fails and the user is not
    # told a registration happened that aoe silently threw away.
    ("unrepairable drift falls through and adds anyway", AOE,
     "            if not repairing:\n                # Issuing the add anyway would be refused at exit 0 — the silence this fixes.\n                return False",
     "            if not repairing:\n                pass"),

    # Title is half of aoe's dedupe key. Drop it from the match and every row at the path looks
    # drifted — including the ones for other harnesses that are legitimately distinct.
    ("drift matches on path alone, ignoring the title", AOE,
     '        if session.get("title") != title or session.get("command") == command:',
     '        if session.get("command") == command:'),

    # The one read the scan is allowed to cost. A second `_sessions` call is a second subprocess
    # on every launch — the reason `_registered` takes the list instead of the exe.
    ("scan re-reads the session list instead of reusing it", AOE,
     "        stale = _drifted_row(sessions, command, project_path, row_title)",
     "        stale = _drifted_row(_sessions(exe), command, project_path, row_title)"),
]


def run_suite() -> int:
    return subprocess.run(
        ["tools/run-tests.sh", "tests/test_aoe.py", "-x", "-q"],
        cwd=ROOT, capture_output=True, text=True,
    ).returncode


def main() -> int:
    dirty = subprocess.run(
        ["git", "diff", "--name-only"], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()
    if dirty:
        print(f"refusing to run with a dirty tree; commit or stash first:\n{dirty}")
        return 2

    survivors: list[str] = []
    for label, rel, find, replace in MUTANTS:
        path = ROOT / rel
        original = path.read_text()
        if find not in original:
            print(f"SKIP  {label}\n      anchor not found in {rel} — the mutant is stale")
            survivors.append(f"{label} (stale anchor)")
            continue
        path.write_text(original.replace(find, replace, 1))
        try:
            killed = run_suite() != 0
        finally:
            path.write_text(original)
        print(f"{'KILL ' if killed else 'ALIVE'} {label}")
        if not killed:
            survivors.append(label)

    restored = subprocess.run(
        ["git", "diff", "--name-only"], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()
    if restored:
        print(f"\nFAILED TO RESTORE — tree is dirty:\n{restored}")
        return 2

    print(f"\n{len(MUTANTS) - len(survivors)}/{len(MUTANTS)} killed; tree restored clean")
    for s in survivors:
        print(f"  SURVIVOR: {s}")
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
