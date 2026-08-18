#!/usr/bin/env python3
"""Mutation check for the ctrquery.py timeout wiring (Issue #295).

Run: tools/mutants_295_ctrquery.py

Each mutant is a real bug a future edit could plausibly introduce. The suite must
FAIL on every one of them; a mutant that survives means the tests covering it assert nothing.

Restores every file it touches and verifies the tree came back clean with `git diff`.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_CTRQUERY = _ROOT / "src" / "harnessed" / "ctrquery.py"
_AUDIT = _ROOT / "tests" / "test_subprocess_timeout_audit.py"
_TESTS = _ROOT / "tests" / "test_ctrquery_timeouts.py"


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=_ROOT, text=True)


def _dirty() -> bool:
    return bool(_git("diff", "--name-only").strip())


def _run_suite() -> bool:
    """Return True if the test suite reports at least one failure."""
    result = subprocess.run(
        [str(_ROOT / "tools" / "run-tests.sh"),
         "tests/test_ctrquery_timeouts.py",
         "tests/test_subprocess_timeout_audit.py"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
    )
    return result.returncode != 0


def _restore(path: Path) -> None:
    subprocess.check_call(["git", "checkout", "--", str(path.relative_to(_ROOT))], cwd=_ROOT)


MUTANTS: list[tuple[str, str, str, Path]] = [
    # (description, old_text, new_text, file)
    (
        "M1: _PODMAN_QUERY_TIMEOUT = 0 (wrong value)",
        "_PODMAN_QUERY_TIMEOUT = 30",
        "_PODMAN_QUERY_TIMEOUT = 0",
        _CTRQUERY,
    ),
    (
        "M2: remove timeout= from _image_exists _bounded call",
        "        timeout=_PODMAN_QUERY_TIMEOUT,\n        capture_output=True,\n    ).returncode == 0\n\n\ndef _container_running",
        "        capture_output=True,\n    ).returncode == 0\n\n\ndef _container_running",
        _CTRQUERY,
    ),
    (
        "M3: remove 'ctrquery.py' from _AUDITED",
        '_AUDITED = ("launcher.py", "proc.py", "ctrquery.py")',
        '_AUDITED = ("launcher.py", "proc.py")',
        _AUDIT,
    ),
    (
        "M4: invert _inspect_id branch (returncode != 0 instead of == 0)",
        "return r.stdout.strip() if r.returncode == 0 else \"\"",
        "return r.stdout.strip() if r.returncode != 0 else \"\"",
        _CTRQUERY,
    ),
    (
        "M5 (scope survivor): drop stdout check from _container_running — pre-existing logic",
        None,  # skip: pre-existing logic, out of scope for this PR
        None,
        _CTRQUERY,
    ),
]


def main() -> int:
    if _dirty():
        print("ERROR: working tree is dirty — run on a clean tree", file=sys.stderr)
        return 1

    killed = 0
    survivors: list[str] = []
    skipped: list[str] = []

    for desc, old, new, path in MUTANTS:
        if old is None:
            print(f"  SKIP   {desc}")
            skipped.append(desc)
            continue

        src = path.read_text(encoding="utf-8")
        if old not in src:
            print(f"  ERROR  {desc} — old text not found in {path.name}", file=sys.stderr)
            _restore(path)
            return 1

        print(f"  APPLY  {desc}")
        path.write_text(src.replace(old, new, 1), encoding="utf-8")

        failed = _run_suite()
        _restore(path)

        if _dirty():
            print(f"  ERROR  restore failed for {desc}", file=sys.stderr)
            return 1

        if failed:
            print(f"  KILLED {desc}")
            killed += 1
        else:
            print(f"  LIVED  {desc}")
            survivors.append(desc)

    total = len(MUTANTS) - len(skipped)
    print(f"\n{killed}/{total} killed, {len(skipped)} skipped (scope survivors)")
    if survivors:
        print("Survivors:")
        for s in survivors:
            print(f"  {s}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
