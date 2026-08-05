#!/usr/bin/env python3
"""Mutation check for aoe command-drift detection and repair (bd harnessed-cn9).

Run: tools/mutants_aoe_drift.py

Each mutant is a real bug a future edit could plausibly introduce. The suite must FAIL on every one
of them; a mutant that survives means the tests covering it assert nothing.

This file exists because several tests in `TestCommandDrift` PASSED before the feature was written
— they assert that something bad does NOT happen (no row rewritten, no extra read, no exception),
which is trivially true of code that does nothing at all. A green suite is not evidence for that
shape of test. These mutants are.

Several target the ownership gate specifically: `_is_ours` is the only thing standing between a
drifted row and harnessed rewriting a row it does not own. One mutant guards the repair verb
itself — reverting `session rename` to `remove` looks like a simplification and silently breaks
the repair, because a trashed row keeps aoe's dedupe key.

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
     "        for stale in _drifted_rows(sessions, command, project_path, row_title):",
     "        for stale in []:"),

    # Repairing only the first row leaves the second holding aoe's key, so the add is still
    # refused at exit 0 -- the same silence, one row further along.
    ("only the first drifted row is repaired", AOE,
     "        for stale in _drifted_rows(sessions, command, project_path, row_title):",
     "        for stale in _drifted_rows(sessions, command, project_path, row_title)[:1]:"),

    # The report: a launch that repairs silently is half the defect (the hours were lost to
    # silence, not to the stale row).
    ("drift is repaired but never reported", AOE,
     "            _report(\n                on_drift,\n                _drift_message(stale, command, renamed_to=stale_title),\n                repairing=repairing,\n            )",
     "            pass"),

    # The launcher branch the adversarial review found: a repair whose rename lands and whose
    # re-add fails must not be reported as "left the existing row as it is".
    ("failed repair reported as if the row were untouched", "src/harnessed/launcher.py",
     "        if any(drift):",
     "        if False:"),

    # THE OWNERSHIP GATE. Loosened, a row harnessed never wrote gets rewritten on a launch.
    ("ownership gate always true (rewrites foreign rows)", AOE,
     '    if tokens[:1] == ["harnessed"]:',
     "    if True:"),

    # The gate's precise half: `mise run` alone is the prefix of EVERY mise task anyone wrote, so
    # dropping the harness check licenses rewriting a user's own `mise run dev` row.
    ("ownership gate stops checking the harness registry", AOE,
     '    return tokens[:2] == ["mise", "run"] and len(tokens) > 2 and tokens[2] in HARNESS_CONFIG_DIR',
     '    return tokens[:2] == ["mise", "run"]'),

    # Off-by-one on the same gate: matching `mise` alone stops excluding `mise-en-place`.
    ("ownership gate compares only the first token", AOE,
     '    return tokens[:2] == ["mise", "run"] and len(tokens) > 2 and tokens[2] in HARNESS_CONFIG_DIR',
     '    return tokens[:1] == ["mise"]'),

    # Wrong row renamed: the id is what scopes the edit to the row we matched.
    ("repair renames a row that was not the matched one", AOE,
     '                    ["session", "rename", str(sid), "-t", stale_title or "", "-p", PROFILE]',
     '                    ["session", "rename", "0", "-t", stale_title or "", "-p", PROFILE]'),

    # THE REGRESSION GUARD for what real execution found: `remove` trashes the row, and a trashed
    # row still holds aoe's (title, path) key, so the replacement add is refused at exit 0 too.
    # Reverting to remove loses the row AND fails to replace it.
    ("repair reverts to `remove` (row trashed, replacement refused)", AOE,
     '                    ["session", "rename", str(sid), "-t", stale_title or "", "-p", PROFILE]',
     '                    ["remove", str(sid), "-p", PROFILE]'),

    # The stale title must stay unique, or a second repair at the same path collides and the
    # rename fails silently on the detached path.
    ("stale title drops the row id, so repairs can collide", AOE,
     '_STALE_SUFFIX = "(stale {sid})"',
     '_STALE_SUFFIX = "(stale)"'),

    # Unrepairable drift must BLOCK the write, so `--create-aoe-only` fails and the user is not
    # told a registration happened that aoe silently threw away.
    ("unrepairable drift falls through and adds anyway", AOE,
     "        if blocked:\n            return False",
     "        if False:\n            return False"),

    # aoe trims a title's ends before deduping (verified 1.13.2: ' Row A' collides with 'Row A',
    # 'row a' and 'Row  A' do not). Comparing exactly lets exactly the rows aoe refuses slip past.
    ("title compare stops matching aoe's trimming", AOE,
     '    return (a or "").strip() == (b or "").strip()',
     '    return a == b'),

    # Title is half of aoe's dedupe key. Drop it from the match and every row at the path looks
    # drifted — including the ones for other harnesses that are legitimately distinct.
    ("drift matches on path alone, ignoring the title", AOE,
     '        if not _same_title(session.get("title"), title) or session.get("command") == command:',
     '        if session.get("command") == command:'),

    # The one read the scan is allowed to cost. A second `_sessions` call is a second subprocess
    # on every launch — the reason `_registered` takes the list instead of the exe.
    ("scan re-reads the session list instead of reusing it", AOE,
     "        for stale in _drifted_rows(sessions, command, project_path, row_title):",
     "        for stale in _drifted_rows(_sessions(exe), command, project_path, row_title):"),
]


def run_suite() -> int:
    return subprocess.run(
        ["tools/run-tests.sh", "tests/test_aoe.py", "-x", "-q"],
        cwd=ROOT, capture_output=True, text=True,
    ).returncode


def main() -> int:
    dirty = subprocess.run(
        # --porcelain, not `diff --name-only`: the latter sees only UNSTAGED changes, so a staged
        # edit to the file under mutation slips past the guard and past the restore check.
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=ROOT, capture_output=True, text=True,
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
        # --porcelain, not `diff --name-only`: the latter sees only UNSTAGED changes, so a staged
        # edit to the file under mutation slips past the guard and past the restore check.
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=ROOT, capture_output=True, text=True,
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
