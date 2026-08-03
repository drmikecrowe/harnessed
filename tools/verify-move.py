"""Prove an extraction was VERBATIM: every moved top-level def/class has byte-identical source.

Why this exists: the test suite cannot prove it. The suite monkeypatches `launcher.<symbol>`, so it
is coupled to where code LIVES, not to what it does — when `_host_os` moved, eleven tests kept
passing while patching an attribute nothing read. A green suite is therefore consistent with both a
correct move and a silently broken one.

This compares the source text of each top-level definition at a base revision against wherever it
lives now, across the whole package. Identical text = no behavior drift, by construction.

    tools/verify-move.py [base-rev]        # default: main
"""

from __future__ import annotations

import ast
import subprocess
import sys

from pathlib import Path

SRC = Path("src/harnessed")


def _defs(source: str, origin: str) -> dict[str, tuple[str, str]]:
    """{name: (source_text, origin)} for every top-level def/class, DECORATORS INCLUDED.

    `ast.get_source_segment` starts at the `def`/`class` line, so decorators sit outside the segment
    it returns. Comparing only that segment would call a definition byte-identical after its
    decorator changed or vanished — and the 20 `@app.command(...)` decorators are what wire the CLI
    together, so exactly the change that would silently unregister a command is the one it would
    miss. Slice from the first decorator instead.
    """
    lines = source.splitlines(keepends=True)
    out: dict[str, tuple[str, str]] = {}
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = node.decorator_list[0].lineno - 1 if node.decorator_list else node.lineno - 1
            assert node.end_lineno is not None
            out[node.name] = ("".join(lines[start:node.end_lineno]).rstrip("\n"), origin)
    return out


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else "main"

    before_text = subprocess.run(
        ["git", "show", f"{base}:src/harnessed/launcher.py"],
        capture_output=True, text=True, check=True,
    ).stdout
    before = _defs(before_text, f"{base}:launcher.py")

    # Only launcher.py and modules that did not exist at `base` are extraction targets. Every other
    # module is pre-existing and may legitimately define an unrelated function of the same name
    # (`_run`, `main`), which is not a collision this check is about.
    at_base = set(subprocess.run(
        ["git", "ls-tree", "--name-only", f"{base}", "src/harnessed/"],
        capture_output=True, text=True, check=True,
    ).stdout.split())
    targets = [
        p for p in sorted(SRC.glob("*.py"))
        if p.name == "launcher.py" or f"src/harnessed/{p.name}" not in at_base
    ]

    after: dict[str, tuple[str, str]] = {}
    collisions: list[str] = []
    for path in targets:
        for name, (text, origin) in _defs(path.read_text(), path.name).items():
            if name in after:
                collisions.append(f"{name}: {after[name][1]} and {origin}")
            after[name] = (text, origin)

    missing, drifted = [], []
    for name, (text, _) in sorted(before.items()):
        if name not in after:
            missing.append(name)
        elif after[name][0] != text:
            drifted.append(f"{name} (now in {after[name][1]})")

    moved = sum(1 for n in before if n in after and not after[n][1].startswith("launcher"))
    print(f"base={base}  definitions checked={len(before)}  moved out of launcher.py={moved}")

    for label, items in (
        ("DISAPPEARED (no longer defined anywhere)", missing),
        ("DRIFTED (source text changed — not a verbatim move)", drifted),
        ("DEFINED TWICE (a stale duplicate was left behind)", collisions),
    ):
        if items:
            print(f"\n{label}:")
            for item in items:
                print(f"  {item}")

    if missing or drifted or collisions:
        return 1
    print("OK — every definition is byte-identical and defined exactly once.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
