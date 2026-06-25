"""Per-stack integration tests.

Two layers:

1. **Assembly oracle (fast, no podman):** every catalog stack resolves + assembles, and its
   `expected_capabilities` (the test oracle) matches what its recipes ship + declare. The negative
   fixture stack is rejected by the pin gate.

2. **Live container check (podman-gated):** for each real stack, `harnessed build` + `harnessed test`
   and assert every declared capability is present *in the right place in the running container* —
   skills under ~/.claude/skills, commands under ~/.claude/commands, plugins under ~/.claude/plugins,
   MCP servers connected through hatago. This is the "simple presence" check (a full behavioural e2e
   comes later). Gated behind HARNESSED_PODMAN=1 so the default suite stays fast and hermetic.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from harnessed.assemble import assemble
from harnessed.schema import PinValidationError, expected_capabilities, load_stack_with_recipes

ROOT = Path(__file__).resolve().parents[1]  # repo root (HARNESSED_DIR for catalog resolution)

# Negative fixture handled separately; everything else is built + launched + probed by the live layer.
NEGATIVE_STACK = "claude_floating-recipe"


def _catalog_stacks() -> list[str]:
    stacks_dir = ROOT / "catalog" / "stacks"
    return sorted(
        p.name for p in stacks_dir.iterdir()
        if (p / "stack.yaml").is_file() and p.name != NEGATIVE_STACK
    )


REAL_STACKS = _catalog_stacks()


def _oracle(stack: str):
    """Expected capabilities for a stack, resolved across the catalog roots (None → catalog)."""
    stk, recipes = load_stack_with_recipes(None, stack)
    return stk, expected_capabilities(stk, recipes)


# --- Layer 1: assembly oracle (fast) --------------------------------------------------------------


@pytest.mark.parametrize("stack", REAL_STACKS)
def test_stack_assembles_and_oracle_is_nonempty(stack, tmp_path):
    """Every real stack resolves + assembles, and declares at least one capability to probe."""
    assemble(None, stack, tmp_path)  # emits into tmp; raises on any resolution/validation error
    _stk, caps = _oracle(stack)
    total = len(caps.mcp_servers) + len(caps.skills) + len(caps.commands) + len(caps.plugins)
    assert total > 0, f"{stack}: oracle declares no capabilities"


def test_big_stacks_declare_all_four_recipes():
    """The two target stacks expose the full capability set across gstack/ping/time/greet."""
    for stack in ("claude_gstack_ping_time_greet", "omp_gstack_ping_time_greet"):
        _stk, caps = _oracle(stack)
        assert {"time", "ping"} <= set(caps.mcp_servers), f"{stack}: missing MCP servers"
        assert {"time-helper", "greet-helper", "gstack-skill"} <= set(caps.skills), f"{stack}: skills"
        assert "gstack-cmd" in caps.commands, f"{stack}: missing gstack-cmd command"


def test_floating_pin_is_rejected(tmp_path):
    """The negative fixture stack trips the pin gate before any image layer is written."""
    with pytest.raises(PinValidationError):
        assemble(None, NEGATIVE_STACK, tmp_path)


# --- Layer 2: live container check (podman-gated) -------------------------------------------------

_PODMAN = os.environ.get("HARNESSED_PODMAN") == "1"
_HARNESSED_BIN = Path(sys.executable).parent / "harnessed"
podman = pytest.mark.skipif(not _PODMAN, reason="set HARNESSED_PODMAN=1 for live podman tests")


def _run_cli(*args: str, timeout: int = 600) -> subprocess.CompletedProcess:
    env = {**os.environ, "PATH": f"{_HARNESSED_BIN.parent}:{os.environ.get('PATH', '')}"}
    return subprocess.run(
        [str(_HARNESSED_BIN), *args], cwd=str(ROOT), env=env,
        capture_output=True, text=True, timeout=timeout,
    )


@podman
@pytest.mark.parametrize("stack", REAL_STACKS)
def test_live_capabilities_present_in_container(stack):
    """build + test the stack; every declared skill/command/plugin/mcp is present in the container."""
    assert _run_cli("build", stack).returncode == 0, f"{stack}: build failed"
    result = _run_cli("test", stack, "--json")
    assert result.returncode == 0, f"{stack}: capability test exited non-zero\n{result.stdout}"
    report = json.loads(result.stdout)
    assert report["ok"] is True, f"{stack}: not green → {report}"

    _stk, caps = _oracle(stack)
    present = {(r["kind"], r["name"]) for r in report["results"] if r["present"]}
    expected = (
        {("mcp", n) for n in caps.mcp_servers}
        | {("skill", n) for n in caps.skills}
        | {("command", n) for n in caps.commands}
        | {("plugin", n) for n in caps.plugins}
    )
    missing = expected - present
    assert not missing, f"{stack}: capabilities missing from the container: {missing}"


@podman
def test_live_negative_stack_is_rejected():
    """The pin-gate fixture must fail `harnessed build` cleanly (non-zero, no traceback)."""
    result = _run_cli("build", NEGATIVE_STACK)
    assert result.returncode != 0, "expected the floating-pin build to be rejected"
    assert "Traceback" not in result.stderr, "build crashed instead of rejecting cleanly"
