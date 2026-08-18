#!/usr/bin/env python3
"""Mutation check for the svcstate.py timeout wiring (Issue #391).

Run: tools/mutants_391_svcstate.py

Each mutant is a real bug a future edit could plausibly introduce. The suite must
FAIL on every one of them; a mutant that survives means the tests covering it assert nothing.

Restores every file it touches and verifies the tree came back clean with `git diff`.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SVCSTATE = _ROOT / "src" / "harnessed" / "svcstate.py"
_AUDIT = _ROOT / "tests" / "test_subprocess_timeout_audit.py"


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=_ROOT, text=True)


def _dirty() -> bool:
    return bool(_git("diff", "--name-only").strip())


def _run_suite() -> bool:
    """Return True if the test suite reports at least one failure."""
    result = subprocess.run(
        [str(_ROOT / "tools" / "run-tests.sh"),
         "tests/test_svcstate_timeouts.py",
         "tests/test_subprocess_timeout_audit.py"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
    )
    return result.returncode != 0


def _restore(path: Path) -> None:
    subprocess.check_call(["git", "checkout", "--", str(path.relative_to(_ROOT))], cwd=_ROOT)


# (description, old_text, new_text, file)
MUTANTS: list[tuple[str, str | None, str | None, Path]] = [
    (
        "M1: _PODMAN_QUERY_TIMEOUT = 0 (wrong value)",
        "_PODMAN_QUERY_TIMEOUT = 30",
        "_PODMAN_QUERY_TIMEOUT = 0",
        _SVCSTATE,
    ),
    (
        "M2: remove timeout= from _svc_published_port _bounded call",
        "        timeout=_PODMAN_QUERY_TIMEOUT,\n        capture_output=True, text=True, check=False,\n    )",
        "        capture_output=True, text=True, check=False,\n    )",
        _SVCSTATE,
    ),
    (
        "M3: invert _svc_published_port returncode branch (returns port on failure, 0 on success)",
        "    if result.returncode != 0:\n        return 0",
        "    if result.returncode == 0:\n        return 0",
        _SVCSTATE,
    ),
    (
        "M4: remove 'svcstate.py' from _AUDITED",
        '_AUDITED = ("launcher.py", "proc.py", "ctrquery.py", "svcstate.py")',
        '_AUDITED = ("launcher.py", "proc.py", "ctrquery.py")',
        _AUDIT,
    ),
    (
        "M5: remove timeout= from _repo_project_hashes _bounded call",
        '        timeout=_PODMAN_QUERY_TIMEOUT,\n        capture_output=True, text=True,\n    )\n    if result.returncode != 0:\n        return hashes',
        '        capture_output=True, text=True,\n    )\n    if result.returncode != 0:\n        return hashes',
        _SVCSTATE,
    ),
    (
        "M6: remove timeout= from _svc_stacks_from_instances _bounded call",
        '        timeout=_PODMAN_QUERY_TIMEOUT,\n        capture_output=True, text=True,\n    )\n    if result.returncode != 0:\n        return []',
        '        capture_output=True, text=True,\n    )\n    if result.returncode != 0:\n        return []',
        _SVCSTATE,
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
        if old is None or new is None:
            print(f"  SKIP   {desc}")
            skipped.append(desc)
            continue

        src = path.read_text(encoding="utf-8")
        if old not in src:
            print(f"  ERROR  {desc} — old text not found in {path.name}", file=sys.stderr)
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

    total = killed + len(survivors) + len(skipped)
    print(f"\n  {killed}/{total - len(skipped)} killed"
          f"  ({len(skipped)} skipped)"
          + (f"  SURVIVORS: {survivors}" if survivors else ""))
    return 0 if not survivors else 1


if __name__ == "__main__":
    sys.exit(main())
