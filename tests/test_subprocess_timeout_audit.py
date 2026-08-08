"""Every `subprocess.run` in the launcher and its seam carries a deadline, or says why not.

This is bd harnessed-1ao's acceptance criterion made executable. The bead exists because an
unresponsive podman — a network partition mid-pull, a runc deadlock — blocks an unbounded
`subprocess.run` forever, and only the user or the OS ends it. A one-off audit fixes the calls
that exist today and does nothing about the call somebody adds next month, so the audit lives
here as a test instead of in a commit message.

The convention it enforces: a call either passes `timeout=`, or the line above it (or its own
first line) starts a `# unbounded:` comment giving the reason. Both halves matter — the exemption
list is asserted exactly, so a new unbounded call cannot be absorbed into it silently.
"""

from __future__ import annotations

import ast

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src" / "harnessed"

# This module asserts against SOURCE TEXT, which makes it one of the repo-asset tests [tool.mutmut]
# warns about. Under `mutmut run` the tree is a rewritten copy where every function has become
# `x_<name>__mutmut_N` variants, so the audit reads dozens of deliberately-broken call sites and
# fails — not as a killed mutant but as a collection-time error that aborts the stats pass and takes
# the whole mutation layer down with it. Standing down there keeps that layer working; the audit
# still runs on every real invocation, which is the tree it is making a claim about.
pytestmark = pytest.mark.skipif(
    _ROOT.name == "mutants",
    reason="source-text audit: the mutants tree is instrumented source, not the source under test",
)

# The files this audit governs: launcher.py is where the bead counted the calls, and proc.py holds
# `_run`/`_run_tagged` — the seam every other module reaches podman through. Auditing the launcher
# while leaving its own chokepoint unexamined would measure the symptom and skip the cause.
_AUDITED = ("launcher.py", "proc.py")

_MARKER = "# unbounded:"

# Every deliberately unbounded call, as (module, enclosing function). Foreground processes whose
# duration is the user's session, not podman's latency — a deadline here kills working sessions.
# Two entries for `aws_sso`: the interactive credential prompt and the foreground server.
_EXPECTED_EXEMPT = {
    ("launcher.py", "_launch_host"),   # the agent itself, host mode (--rm supervise branch)
    ("launcher.py", "_attach"),        # the interactive container session (--rm supervise branch)
    ("launcher.py", "test_stack"),     # capability suite; child enforces DEFAULT_TEST_TIMEOUT
    ("launcher.py", "svc"),            # catalog-authored `sync:`; a DB import is legitimately long
    ("launcher.py", "aws_sso"),        # `aws-sso setup ecs auth` + `aws-sso ecs server`
    ("proc.py", "_run"),               # imposes no policy; callers opt in via timeout=
}

_EXPECTED_EXEMPT_CALL_COUNT = 7  # 6 functions, with aws_sso contributing two


def _enclosing_functions(tree: ast.AST) -> dict[int, str]:
    """line number -> name of the innermost function containing it."""
    owner: dict[int, str] = {}

    def walk(node, name):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for line in range(child.lineno, (child.end_lineno or child.lineno) + 1):
                    owner[line] = child.name
                walk(child, child.name)
            else:
                walk(child, name)

    walk(tree, "<module>")
    return owner


def _is_guarded_call(node: ast.Call) -> bool:
    """True for the call shapes this audit governs: `subprocess.run(...)` and `_bounded(...)`."""
    func = node.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return func.value.id == "subprocess" and func.attr == "run"
    if isinstance(func, ast.Name):
        return func.id == "_bounded"
    return False


def _has_marker(lines: list[str], lineno: int) -> bool:
    """The `# unbounded:` marker sits on the call's own first line, or anywhere in the contiguous
    comment block directly above it — a real reason usually needs more than one line, and the
    marker opens the block rather than closing it. The block is contiguous by design: the search
    stops at the first line that is not a comment, so an unrelated comment further up cannot
    excuse a call.
    """
    if _MARKER in lines[lineno - 1]:
        return True
    for i in range(lineno - 2, -1, -1):
        stripped = lines[i].strip()
        if not stripped.startswith("#"):
            return False
        if stripped.startswith(_MARKER):
            return True
    return False


def _audit(filename: str) -> tuple[list[tuple[str, int, str]], list[tuple[str, str]]]:
    """Return (unjustified, exempt) for one module."""
    src = (_SRC / filename).read_text(encoding="utf-8")
    lines = src.splitlines()
    tree = ast.parse(src)
    owner = _enclosing_functions(tree)

    unjustified: list[tuple[str, int, str]] = []
    exempt: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_guarded_call(node):
            continue
        if any(kw.arg == "timeout" for kw in node.keywords):
            continue
        fn = owner.get(node.lineno, "<module>")
        if _has_marker(lines, node.lineno):
            exempt.append((filename, fn))
        else:
            unjustified.append((filename, node.lineno, fn))
    return unjustified, exempt


class TestEveryCallIsBoundedOrJustified:
    """bd harnessed-1ao: 'Every subprocess.run in launcher.py either passes timeout= or carries a
    comment saying why unbounded is correct.'"""

    @pytest.mark.parametrize("filename", _AUDITED)
    def test_no_unbounded_call_without_a_stated_reason(self, filename):
        unjustified, _ = _audit(filename)
        assert not unjustified, (
            f"{len(unjustified)} call(s) in {filename} block with no deadline and no reason: "
            + ", ".join(f"line {ln} in {fn}()" for _, ln, fn in unjustified)
            + f". Pass timeout=, or put a `{_MARKER} <why>` comment on the line above "
            "(bd harnessed-1ao — an unresponsive podman otherwise hangs forever)."
        )

    def test_the_audit_actually_finds_calls(self):
        """A parse that matches nothing reports zero defects and passes. Guard against the audit
        silently measuring an empty set — the failure mode that makes a green check meaningless."""
        total = 0
        for filename in _AUDITED:
            tree = ast.parse((_SRC / filename).read_text(encoding="utf-8"))
            total += sum(
                1 for n in ast.walk(tree) if isinstance(n, ast.Call) and _is_guarded_call(n)
            )
        assert total >= 30, f"expected the launcher seam to hold 30+ guarded calls, saw {total}"


class TestTheExemptionListIsClosed:
    """An exemption has to be added deliberately. Asserting the set — not just a count — is what
    stops a hung `podman rm` from being waved through under a comment copied from a session call."""

    def test_exemptions_are_exactly_the_reviewed_set(self):
        found = set()
        for filename in _AUDITED:
            _, exempt = _audit(filename)
            found.update(exempt)
        assert found == _EXPECTED_EXEMPT, (
            f"unexpected: {sorted(found - _EXPECTED_EXEMPT)}; "
            f"gone: {sorted(_EXPECTED_EXEMPT - found)}"
        )

    def test_exempt_call_count_is_stable(self):
        """`aws_sso` holds two exempt calls, so the set above cannot catch a second one appearing
        inside an already-exempt function. The count can."""
        total = 0
        for filename in _AUDITED:
            _, exempt = _audit(filename)
            total += len(exempt)
        assert total == _EXPECTED_EXEMPT_CALL_COUNT
