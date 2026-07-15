"""Per-stack integration tests.

Two layers:

1. **Assembly oracle (fast, no podman):** every catalog stack resolves + assembles, and its
   `expected_capabilities` (the test oracle) matches what its recipes ship + declare. A floating
   Dockerfile ref is rejected by the pin gate.

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

from harnessed import paths
from harnessed.assemble import assemble
from harnessed.emit import required_settings
from harnessed.schema import (
    PinValidationError,
    expected_capabilities,
    load_recipe,
    load_stack_with_recipes,
    validate_pin,
)

ROOT = Path(__file__).resolve().parents[1]  # repo root (HARNESSED_DIR for catalog resolution)

# The floating-pin negative case is driven off the `floating-recipe` recipe's Dockerfile directly
# (no catalog stack) — see test_floating_pin_is_rejected.
FLOATING_RECIPE_DOCKERFILE = ROOT / "catalog" / "recipes" / "floating-recipe" / "Dockerfile"

# Illustrative templates that ASSEMBLE but point at a placeholder URL — covered by the fast
# assembly/oracle sweep, but skipped by the live connect test (no real endpoint to reach).
NO_LIVE_CONNECT = {"claude_openbrain-example", "claude_hindsight"}

# CLI-only recipes with no skill/command/mcp/plugin surface at all, by design — the agent shells
# out to the binary directly and there is no `expect:` kind for "a binary is on PATH" (see e.g.
# catalog/recipes/rtk/PLAN.md "Risks / checks", or the beads recipes' recipe.yaml headers). The
# assembler-driven oracle is
# structurally empty for these; verified manually, not by this fast sweep.
NO_CAPABILITY_ORACLE = {
    "claude_beads-team",
    "claude_beads-stealth",
    "claude_rtk",
    "claude_solidspec",
    # host-native beads-daemon tracer stacks (spike): beads is CLI+hook+service only, no oracle surface.
    "hostbeads",
    "hostbeads_stealth",
    # host-provision tracer (spike): installs a uv-tool, no skill/mcp surface.
    "hostprov",
}


def _catalog_stacks() -> list[str]:
    stacks_dir = ROOT / "catalog" / "stacks"
    return sorted(
        p.name for p in stacks_dir.iterdir()
        if (p / "stack.yaml").is_file()
    )


REAL_STACKS = _catalog_stacks()


def _oracle(stack: str):
    """Expected capabilities for a stack, resolved across the catalog roots (None → catalog)."""
    stk, recipes = load_stack_with_recipes(None, stack)
    return stk, expected_capabilities(stk, recipes)


# --- Layer 1: assembly oracle (fast) --------------------------------------------------------------


@pytest.mark.parametrize("stack", [s for s in REAL_STACKS if s not in NO_CAPABILITY_ORACLE])
def test_stack_assembles_and_oracle_is_nonempty(stack, tmp_path):
    """Every real stack resolves + assembles, and declares at least one capability to probe."""
    assemble(None, stack, tmp_path, "claude")  # emits into tmp; raises on any resolution/validation error
    _stk, caps = _oracle(stack)
    total = len(caps.mcp_servers) + len(caps.skills) + len(caps.commands) + len(caps.plugins)
    assert total > 0, f"{stack}: oracle declares no capabilities"


def test_multi_recipe_stack_composes_capabilities():
    """A multi-recipe stack exposes the union of its recipes' capabilities — here the repowise
    MCP server and the gsd-core skills both surface on gsd-core_repowise."""
    _stk, caps = _oracle("gsd-core_repowise")
    assert "repowise" in set(caps.mcp_servers), "missing repowise MCP server"
    assert {"gsd-new-project", "gsd-plan-phase", "gsd-execute-phase"} <= set(caps.skills), (
        "missing gsd-core skills"
    )


def test_floating_pin_is_rejected():
    """The pin gate rejects a floating Dockerfile ref (ASM-02) before any image layer is written.
    Driven off the floating-recipe fixture Dockerfile directly (its `--branch main` clone)."""
    with pytest.raises(PinValidationError):
        validate_pin("floating-recipe", FLOATING_RECIPE_DOCKERFILE.read_text())


def test_all_catalog_recipes_pass_strict():
    """Every shipped recipe must load under `--strict` — no typo'd/unknown top-level field.

    `harnessed build`/`test` run strict by default, so a stray field in the catalog would break the
    authoring path. This guards it in CI (the strict mechanism itself is unit-tested in test_schema).

    Enumerated via `paths.catalog_relpath` so VARIETY refs (`beads/stealth` →
    catalog/recipes/beads/stealth/) are covered too — a plain `iterdir()` would silently skip them.
    """
    recipes_dir = ROOT / "catalog" / "recipes"
    names: list[str] = []
    for entry in sorted(recipes_dir.iterdir()):
        if not entry.is_dir():
            continue
        if (entry / "recipe.yaml").is_file():
            names.append(entry.name)
            continue
        names += [
            f"{entry.name}/{sub.name}"
            for sub in sorted(entry.iterdir())
            if (sub / "recipe.yaml").is_file()
        ]
    assert names, "no catalog recipes found"
    assert "beads/stealth" in names, "variety refs must be enumerated, not skipped"
    for name in names:
        load_recipe(recipes_dir / paths.catalog_relpath(name), strict=True)  # raises on unknown field


def test_context_mode_hooks_are_skipped_on_omp_only():
    """The real catalog recipe, not a fixture (bd main-4fx / main-wyh).

    context-mode's capability is delivered NATIVELY on omp (its own omp extension, installed by the
    recipe's Dockerfile: session_start / tool_call / tool_result / session_before_compact). Replaying
    the same hook bodies through omp-claude-hooks-bridge would double-write the session DB and spawn
    a node CLI per tool call whose output the bridge discards. Every other harness must be unchanged.
    """
    recipe = load_recipe(ROOT / "catalog" / "recipes" / "context-mode", strict=True)
    assert recipe.hooks_skip_harnesses == ["omp"]

    assert "hooks" not in required_settings([], [recipe], harness="omp")
    for harness in ("claude", "opencode", "codex", "antigravity"):
        hooks = required_settings([], [recipe], harness=harness).get("hooks", {})
        assert set(hooks) == {"PreToolUse", "SessionStart", "PostToolUse", "PreCompact"}, harness


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
_FLOOR = {"permissions": {"defaultMode": "acceptEdits", "allow": ["mcp__hatago"]}}  # what emit.write_settings_json emits


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
