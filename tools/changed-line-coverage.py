#!/usr/bin/env python3
"""Changed-line coverage: every line this branch ADDED to src/ must be executed by a test.

Global coverage % is vanity. The constraint is the changed lines.
Usage: .old-coder/changed_line_coverage.py <cov.json> [base-ref]
"""
from __future__ import annotations

import json
import re
import subprocess
import sys

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HUNK = re.compile(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@")


def added_lines(base: str) -> dict[str, set[int]]:
    out = subprocess.run(
        ["git", "diff", f"{base}...HEAD", "--unified=0", "--", "src/"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
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
    cov = json.loads(Path(sys.argv[1]).read_text())
    base = sys.argv[2] if len(sys.argv) > 2 else "main"
    files = cov["files"]

    total_missed = 0
    for path, lines in sorted(added_lines(base).items()):
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
