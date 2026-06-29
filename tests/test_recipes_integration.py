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

# Illustrative templates that ASSEMBLE but point at a placeholder URL — covered by the fast
# assembly/oracle sweep, but skipped by the live connect test (no real endpoint to reach).
NO_LIVE_CONNECT = {"claude_openbrain-example"}


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
        # time-helper/greet-helper are fanned skill dirs; `gstack` is the anchor skill the gstack
        # Dockerfile bakes (declared via its expect: block). The rest of gstack's expect: list is a
        # tunable representative set, so we don't pin it here.
        assert {"time-helper", "greet-helper", "gstack"} <= set(caps.skills), f"{stack}: skills"


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
@pytest.mark.parametrize("stack", [s for s in REAL_STACKS if s not in NO_LIVE_CONNECT])
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


# --- Layer 2b: settings.json post-build merge (podman-gated) ---------------------------------------
#
# The pure merge logic (emit.merge_settings / read_baked_settings) is exhaustively unit-tested in
# test_emit.py. These tests cover the part units can't: the real `podman create` + `cp` extraction
# of an image-baked ~/.claude/settings.json and the overwrite of the profile floor. We bake a
# throwaway image rather than a catalog fixture because no catalog recipe writes settings.json yet.

from harnessed.launcher import _merge_baked_settings, _runtime  # noqa: E402
from harnessed.paths import CONTAINER_HOME  # noqa: E402

# Pinned base (project hygiene — no floating tags), small + cached after first pull.
_TEST_BASE = "docker.io/library/alpine:3.20"
_FLOOR = {"permissions": {"allow": ["mcp__hatago"]}}  # what emit.write_settings_json emits


def _build_image_with(tmp: Path, tag: str, settings: dict | None) -> str:
    """Build a throwaway image; bake `settings` at CONTAINER_HOME/.claude/settings.json if given."""
    rt = _runtime()
    ctx = tmp / "img"
    ctx.mkdir()
    if settings is None:
        (ctx / "Dockerfile").write_text(f"FROM {_TEST_BASE}\n")
    else:
        (ctx / "settings.json").write_text(json.dumps(settings))
        # COPY creates the intermediate .claude dir; no shell quoting of JSON needed.
        (ctx / "Dockerfile").write_text(
            f"FROM {_TEST_BASE}\nCOPY settings.json {CONTAINER_HOME}/.claude/settings.json\n"
        )
    assert subprocess.run([rt, "build", "-t", tag, str(ctx)], capture_output=True,
                          text=True).returncode == 0, f"failed to build fixture image {tag}"
    return rt


@podman
def test_merge_baked_settings_unions_grant_and_preserves_baked(tmp_path):
    """Real image bakes settings.json (hook + custom allow + a conflicting deny) → the post-build
    merge preserves the baked content and re-applies harnessed's required grant."""
    tag = "harnessed-test-settings-baked:latest"
    baked = {
        "hooks": {"PreToolUse": [{"matcher": "Bash"}]},
        "permissions": {"allow": ["mcp__custom"], "deny": ["mcp__hatago"]},
    }
    rt = _build_image_with(tmp_path, tag, baked)
    prof = tmp_path / "profile"
    prof.mkdir()
    (prof / "settings.json").write_text(json.dumps(_FLOOR))  # the assemble-time floor
    try:
        _merge_baked_settings(rt, tag, prof)
        merged = json.loads((prof / "settings.json").read_text())
    finally:
        subprocess.run([rt, "rmi", "-f", tag], capture_output=True)

    assert merged["hooks"] == {"PreToolUse": [{"matcher": "Bash"}]}, "baked hook dropped (regression)"
    assert "mcp__hatago" in merged["permissions"]["allow"], "required grant not unioned"
    assert "mcp__custom" in merged["permissions"]["allow"], "baked allow entry lost"
    assert "mcp__hatago" not in merged["permissions"].get("deny", []), "deny conflict not resolved"


@podman
def test_merge_baked_settings_keeps_floor_when_image_has_no_settings(tmp_path):
    """Image bakes no settings.json → `podman cp` fails → the assemble-time floor stub stands."""
    tag = "harnessed-test-settings-bare:latest"
    rt = _build_image_with(tmp_path, tag, None)
    prof = tmp_path / "profile"
    prof.mkdir()
    (prof / "settings.json").write_text(json.dumps(_FLOOR))
    try:
        _merge_baked_settings(rt, tag, prof)
        result = json.loads((prof / "settings.json").read_text())
    finally:
        subprocess.run([rt, "rmi", "-f", tag], capture_output=True)

    assert result == _FLOOR, "floor stub should be untouched when nothing is baked"
