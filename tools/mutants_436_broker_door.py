#!/usr/bin/env python3
"""Mutation check for the loopback broker door in egress-firewall.sh (Issue #436).

Run: tools/mutants_436_broker_door.py

mutmut mutates Python, and the logic this issue adds lives in a shell script, so the mutation
layer for #436 is this hand-written set instead. Each mutant is a real bug a future edit could
plausibly introduce to a one-line firewall rule: the wrong address, the wrong verdict, a widened
CIDR, a best-effort call where a required one belongs, the rule placed before the flush, and an
IPv6 counterpart that does nothing. The suite must FAIL on every one of them.

Restores every file it touches (even on error) and verifies the tree came back clean.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_FIREWALL = _ROOT / "catalog" / "base" / "egress-firewall.sh"
_SUITE = "tests/test_egress_firewall_broker_door.py"

_DOOR = "require iptables -A OUTPUT -d 169.254.1.1 -j ACCEPT"
_FLUSH = "require iptables -F OUTPUT"
_IP6_DNS = "    ip6tables -A OUTPUT -p tcp --dport 53 -j ACCEPT"


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=_ROOT, text=True)


def _dirty() -> bool:
    # status --porcelain, not `diff`: `diff` alone ignores STAGED changes, so a staged edit to a
    # target file would pass the clean-tree gate and then be silently reverted by _restore.
    return bool(_git("status", "--porcelain").strip())


def _run_suite() -> bool:
    """Return True if the test suite reports at least one failure."""
    result = subprocess.run(
        [str(_ROOT / "tools" / "run-tests.sh"), _SUITE],
        cwd=_ROOT,
        capture_output=True,
        text=True,
    )
    return result.returncode != 0


def _restore(path: Path) -> None:
    subprocess.check_call(["git", "checkout", "--", str(path.relative_to(_ROOT))], cwd=_ROOT)


# (description, [(old_text, new_text), ...], file)
MUTANTS: list[tuple[str, list[tuple[str, str]], Path]] = [
    (
        "M1: best-effort instead of required (the #429 silence)",
        [(_DOOR, "iptables -A OUTPUT -d 169.254.1.1 -j ACCEPT")],
        _FIREWALL,
    ),
    (
        "M2: wrong address — podman's gateway instead of the broker door",
        [(_DOOR, "require iptables -A OUTPUT -d 169.254.1.2 -j ACCEPT")],
        _FIREWALL,
    ),
    (
        "M3: widened to the whole link-local range",
        [(_DOOR, "require iptables -A OUTPUT -d 169.254.0.0/16 -j ACCEPT")],
        _FIREWALL,
    ),
    (
        "M4: wrong verdict — DROP instead of ACCEPT",
        [(_DOOR, "require iptables -A OUTPUT -d 169.254.1.1 -j DROP")],
        _FIREWALL,
    ),
    (
        "M5: rule placed before the flush, so `-F OUTPUT` discards it",
        [(_DOOR + "\n\n", ""), (_FLUSH, _DOOR + "\n" + _FLUSH)],
        _FIREWALL,
    ),
    (
        "M6: a meaningless ip6tables counterpart for an IPv4 link-local address",
        [(_IP6_DNS, _IP6_DNS + "\n    ip6tables -A OUTPUT -d 169.254.1.1 -j ACCEPT")],
        _FIREWALL,
    ),
]


def main() -> int:
    if _dirty():
        print("ERROR: working tree is dirty — run on a clean tree", file=sys.stderr)
        return 1

    # Baseline gate: a suite that ALREADY fails reports every mutant as killed, which is the
    # fail-open mode that makes a mutation score worthless. Prove the suite is green first.
    print("  BASE   verifying the suite passes before any mutation")
    if _run_suite():
        print("ERROR: target suite fails BEFORE mutation — every mutant would report killed",
              file=sys.stderr)
        return 1

    killed = 0
    survivors: list[str] = []

    for desc, edits, path in MUTANTS:
        src = path.read_text(encoding="utf-8")
        mutated = src
        for old, new in edits:
            if old not in mutated:
                print(f"  ERROR  {desc} — old text not found in {path.name}", file=sys.stderr)
                return 1
            mutated = mutated.replace(old, new, 1)

        print(f"  APPLY  {desc}")
        path.write_text(mutated, encoding="utf-8")

        try:
            failed = _run_suite()
        finally:
            # finally, not a bare call: if _run_suite raises, an un-restored mutation is left
            # sitting in a source file the caller believes is clean.
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

    print(f"\n  {killed}/{len(MUTANTS)} killed"
          + (f"  SURVIVORS: {survivors}" if survivors else ""))
    return 0 if not survivors else 1


if __name__ == "__main__":
    sys.exit(main())
