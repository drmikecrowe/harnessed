#!/usr/bin/env python3
"""Changed-line coverage: every line this branch ADDED to src/ must be executed by a test.

Global coverage % is vanity. The constraint is the changed lines.
Usage: tools/changed-line-coverage.py <cov.json> [base-ref]

FAILS CLOSED. This script is the instrument a reader trusts instead of reading the diff, so it
must never confuse "checked, found nothing missing" with "checked nothing". If the diff names
source files and the parse yields none of them, that is a FAILURE, not a pass: an empty result
would otherwise sail through the loop below, count zero misses and print PASS while measuring
nothing at all. Same reason the git invocation pins the options that shape its output — a user's
`diff.noprefix` or an external differ silently changes the format this parses.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HUNK = re.compile(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@")


def _git(*args: str) -> str:
    """Run git with the output-shaping config pinned, so what we parse is what git produces.

    `diff.noprefix`, `diff.external`, `diff.mnemonicPrefix` and colour are all user settings that
    change the diff's SHAPE. Left unpinned, a developer with any of them set gets a parse that
    silently matches nothing — and an empty parse used to read as full coverage.
    """
    return subprocess.run(
        ["git", "-c", "diff.noprefix=false", "-c", "diff.mnemonicPrefix=false",
         "-c", "color.diff=never", "-c", "diff.external=", *args],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout


def added_lines(base: str) -> dict[str, set[int]]:
    # `--` terminates revision parsing: a base ref is a CLI argument, and without the terminator a
    # value beginning with `-` is read as an option rather than a ref.
    out = _git("diff", "--no-ext-diff", "--unified=0", f"{base}...HEAD", "--", "src/")
    result: dict[str, set[int]] = {}
    path, lineno = None, 0
    for line in out.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:]
            result.setdefault(path, set())
        elif m := HUNK.match(line):
            lineno = int(m.group(1))
        elif line.startswith("+") and not line.startswith("+++"):
            if path:
                result[path].add(lineno)
            lineno += 1
    return result


def main() -> int:
    if not 2 <= len(sys.argv) <= 3:
        print(__doc__.splitlines()[2] if __doc__ else "", file=sys.stderr)
        print("usage: tools/changed-line-coverage.py <cov.json> [base-ref]", file=sys.stderr)
        return 2

    cov = json.loads(Path(sys.argv[1]).read_text())
    base = sys.argv[2] if len(sys.argv) > 2 else "main"
    # Resolve the ref before it reaches `git diff`, so an unknown or option-shaped value fails
    # here with a clear message instead of being interpreted further down.
    try:
        _git("rev-parse", "--verify", "--quiet", f"{base}^{{commit}}")
    except subprocess.CalledProcessError:
        print(f"not a commit: {base!r}", file=sys.stderr)
        return 2
    files = cov["files"]

    changed = added_lines(base)
    # FAIL CLOSED: the diff named source files but the parse produced none of them, so the loop
    # below would check nothing and report success. Measuring nothing is not a pass.
    if not changed and _git("diff", "--name-only", f"{base}...HEAD", "--", "src/").strip():
        print("PARSE PRODUCED NOTHING while the diff touches src/ -- refusing to report a result.")
        print("CHANGED-LINE COVERAGE: FAIL (measured nothing)")
        return 1

    total_missed = 0
    for path, lines in sorted(changed.items()):
        if not lines:
            continue
        entry = files.get(path)
        if entry is None:
            print(f"{path}: NOT IN COVERAGE REPORT ({len(lines)} added lines)")
            total_missed += len(lines)
            continue
        executed = set(entry["executed_lines"])
        excluded = set(entry.get("excluded_lines", []))
        # Lines with no statement (blank, comment, docstring continuation) are not in either set.
        statements = set(entry["executed_lines"]) | set(entry["missing_lines"])
        relevant = lines & statements
        missed = sorted(relevant - executed - excluded)
        print(f"{path}: {len(relevant & executed)}/{len(relevant)} added statements executed"
              f"{'' if not missed else f' -- MISSING {missed}'}")
        total_missed += len(missed)

    print("\nCHANGED-LINE COVERAGE:", "PASS" if total_missed == 0 else f"FAIL ({total_missed} lines)")
    return 0 if total_missed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
