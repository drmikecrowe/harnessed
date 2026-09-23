"""Print each surviving mutant as a diff against the original, without re-invoking mutmut.

`mutmut show` rebuilds the package per call, which is ~40 seconds x 44 survivors. Everything it
needs is already on disk: mutmut writes each mutant as its own `x_<fn>__mutmut_<n>` function beside
an `x_<fn>__mutmut_orig` in `mutants/src/harnessed/<module>.py`. This diffs the two.

Read-only. Reports a survivor it cannot locate rather than skipping it -- a classifier that quietly
drops what it cannot parse produces a short list that looks like progress.

Usage: python3 tools/show-survivors-456.py <file-of-mutant-names>
"""

from __future__ import annotations

import ast
import difflib
import pathlib
import sys


def _funcs(path: pathlib.Path) -> dict[str, str]:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    lines = src.splitlines(keepends=True)
    return {
        node.name: "".join(lines[node.lineno - 1 : node.end_lineno])
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }


def main() -> int:
    names = [
        ln.strip()
        for ln in pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    cache: dict[str, dict[str, str]] = {}
    missing = 0

    for full in names:
        _, module, mutant = full.split(".", 2)
        path = pathlib.Path("mutants/src/harnessed") / f"{module}.py"
        # REPORTED, not raised. `_funcs` opens the file, so a mutants tree that does not carry this
        # module (a deleted tree, a selector naming a module mutmut never mutated) killed the whole
        # walk with FileNotFoundError before a single survivor was printed -- the tool that exists
        # to enumerate survivors failing closed on the first one it cannot resolve. Raised on
        # PR #461 review. `missing` is already the counter the verdict reads.
        if not path.is_file():
            print(f"### {full}: NO MUTANTS FILE at {path}")
            missing += 1
            continue
        if module not in cache:
            cache[module] = _funcs(path)
        funcs = cache[module]
        orig_name = mutant.rsplit("__mutmut_", 1)[0] + "__mutmut_orig"
        if mutant not in funcs or orig_name not in funcs:
            print(f"### {full}: NOT FOUND in {path} (orig={orig_name})")
            missing += 1
            continue
        diff = difflib.unified_diff(
            funcs[orig_name].splitlines(), funcs[mutant].splitlines(),
            lineterm="", n=0,
        )
        body = [ln for ln in diff if ln.startswith(("+", "-")) and not ln.startswith(("+++", "---"))]
        print(f"### {full}")
        for ln in body:
            print(f"    {ln}")

    if missing:
        print(f"\n{missing} survivor(s) could not be located -- classification is INCOMPLETE")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
