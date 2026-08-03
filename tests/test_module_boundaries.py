"""The direction rule for the launcher.py split (bd harnessed-4l8), enforced in one place.

Pure, derivable logic lives in focused modules; launcher.py keeps the Typer surface and podman
orchestration; dependencies point INTO the modules and never back out. The moment one of them
reaches back into launcher, the direction reverses and every later extraction inherits an import
cycle — which is why the `run` COMMAND stays in launcher.py: it needs `_build_stack`, `_runtime`,
`launch` and `_err`, so a module holding it could only work through a cycle.

Generalizing the per-module form (tests/test_dynstack.py::TestModuleBoundary and its copies in
test_launchenv.py / test_credmounts.py, which are left in place): a convention with no enforcement
erodes at the third extraction, and there are now eight modules to hold to it rather than one.
"""

from __future__ import annotations

import ast

from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src" / "harnessed"

# Extracted out of launcher.py. Add every new one here — that is the whole cost of the rule.
EXTRACTED = [
    "console.py",
    "credmounts.py",
    "ctrquery.py",
    "dynstack.py",
    "hosthome.py",
    "jsonmerge.py",
    "launchenv.py",
    "svcstate.py",
]


def _imported_names(path: Path) -> list[str]:
    """Every name imported by the module, at ANY nesting depth.

    Checked over parsed imports rather than raw text, because prose legitimately names launcher:
    `credmounts._gnupg_mounts` explains what the old BASH launcher used to mount and why that was
    wrong, and a pure move must not reword the docstring it moves.

    `ast.walk` descends into function bodies, so a function-local `import launcher` — which keeps
    the coupling while looking clean at the top of the file, including on a branch no test happens
    to take — is caught too.
    """
    names: list[str] = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names += [node.module or ""] + [a.name for a in node.names]
    return names


@pytest.mark.parametrize("module", EXTRACTED)
def test_extracted_module_does_not_import_launcher(module):
    offenders = [n for n in _imported_names(SRC / module) if "launcher" in n]
    assert not offenders, (
        f"{module} imports {offenders} — the dependency points INTO modules, never back out "
        f"(bd harnessed-4l8)"
    )


def test_the_ledger_lists_every_extracted_module():
    """A module missing from EXTRACTED is unenforced, which is indistinguishable from compliant.

    Anything importing `harnessed.console` was carved out of launcher.py — that module exists only
    so an extracted module can report on launcher's console instead of building a second one.
    """
    def imports_harnessed_console(path: Path) -> bool:
        # The relative `from .console import ...` specifically — `rich.console` is a different
        # module that several untouched files import.
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module == "console" and node.level > 0:
                return True
            if isinstance(node, ast.ImportFrom) and node.module == "harnessed.console":
                return True
        return False

    users_of_console = sorted(
        p.name for p in SRC.glob("*.py")
        if p.name not in ("console.py", "launcher.py") and imports_harnessed_console(p)
    )
    unlisted = sorted(set(users_of_console) - set(EXTRACTED))
    assert not unlisted, f"extracted but not held to the boundary rule: {unlisted}"
