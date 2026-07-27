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

import inspect
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

from harnessed import launcher
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


class TestCredentialedScanReportWins:
    """bd harnessed-de7. A real build printed '0 critical · 4 high across 5 source(s)' and then
    '✓ supply-chain: no high/critical advisories'. Both cannot be true.

    _scan_image_in_container is the ONLY path on which snyk and socket run — the build-time layer is
    deliberately credential-free. It used to run with `--rm`, so its report died with the container,
    and _surface_scan_report then copied the image-baked (credential-free) report out and printed the
    verdict from that. A build with high findings and a clean build produced the same green line.
    """

    def _report(self, path, crit, high, source="socket · node globals"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "advisory": True, "gating": 0,
            "totals": {"critical": crit, "high": high},
            "sources": [{"source": source, "critical": crit, "high": high}],
        }))

    def test_credentialed_report_is_not_clobbered_by_the_baked_one(self, tmp_path, capsys):
        prof = tmp_path / "prof"
        dest = prof / "scan-report.json"
        self._report(dest, 0, 4)  # what the credentialed re-scan found

        launcher._surface_scan_report("podman", "img", prof, keep_existing=True)
        assert json.loads(dest.read_text())["totals"]["high"] == 4
        out = capsys.readouterr().out
        assert "4 high" in out
        assert "no high/critical" not in out, "the false all-clear is the whole bug"

    def test_without_a_credentialed_report_the_baked_one_is_still_used(self, tmp_path, monkeypatch):
        """keep_existing=False must preserve the old behaviour — a build with scans disabled still
        surfaces whatever the image baked."""
        prof = tmp_path / "prof"
        copied = []
        monkeypatch.setattr(
            launcher, "_with_image_container",
            lambda rt, image, fn: (copied.append(image), True)[1],
        )
        launcher._surface_scan_report("podman", "img", prof, keep_existing=False)
        assert copied == ["img"], "the baked report must still be extracted when there is no re-scan"

    def test_the_scan_container_survives_long_enough_to_copy_its_report(self):
        src = inspect.getsource(launcher._scan_image_in_container)
        # The QUOTED form — an argv element. The prose above it explains why --rm is absent, so a
        # bare substring check matches the comment and passes for the wrong reason.
        assert '"--rm"' not in src, "a removed container takes the credentialed report with it"
        assert '"--cidfile"' in src and '"cp"' in src

    def test_return_value_still_means_the_scan_ran_not_that_a_report_landed(self):
        """`_scan_image` calls this with NO report_dest for `harnessed rescan`. Overloading the
        return to mean "a report was persisted" made that caller always see failure — caught by
        tests/test_rescan_credentialed.py, which asserts a clean run returns True."""
        src = inspect.getsource(launcher._scan_image_in_container)
        assert "return res.returncode == 0" in src

    def test_a_stale_report_from_a_previous_build_is_not_mistaken_for_this_scans(self):
        """The build decides `keep_existing` by whether the file exists, so a leftover report from
        an earlier build would be treated as authoritative for a scan that never wrote one."""
        src = inspect.getsource(launcher._build_stack)
        assert "scan_report.unlink(missing_ok=True)" in src
        assert src.index("scan_report.unlink") < src.index("_scan_image_in_container(")


@podman
def test_merge_baked_settings_reads_the_VOLUME_not_the_image(tmp_path):
    """bd harnessed-8px.21.7 — the regression this exists to stop.

    `install:` used to run at build, so the installer-written settings.json lived in the IMAGE and
    `_merge_baked_settings` read it from there. bd harnessed-8px.21.4 moved installs to a per-stack
    volume. Reading the image would now find nothing, keep the assemble-time floor, and silently
    drop every install-written key — which is precisely harnessed-8px.19 ("ccstatusline statusLine
    gone on every restart"), a P1 this epic already fixed once and closed.

    The image here is deliberately BARE: if the volume were ignored, the floor would stand and the
    assertion below would fail. That is what makes this test fail without the fix.
    """
    tag = "harnessed-test-settings-volume:latest"
    vol = "harnessed-test-settings-vol"
    rt = _build_image_with(tmp_path, tag, None)
    installed = {"statusLine": {"type": "command", "command": "ccstatusline"}}
    prof = tmp_path / "profile"
    prof.mkdir()
    (prof / "settings.json").write_text(json.dumps(_FLOOR))
    try:
        subprocess.run([rt, "volume", "rm", "-f", vol], capture_output=True)
        # Write the installer's settings.json INTO the volume, as a real install would.
        # Written with the SAME userns the reader uses. A volume populated under a different
        # mapping is unreadable by the agent (bd harnessed-8px.21.1), so mirroring harnessed here
        # is part of what the test asserts, not incidental setup.
        subprocess.run(
            [rt, "run", "--rm", "-i", "--userns=keep-id",
             "-v", f"{vol}:{CONTAINER_HOME}/.claude", tag,
             "sh", "-c", f"cat > {CONTAINER_HOME}/.claude/settings.json"],
            input=json.dumps(installed), text=True, check=True, capture_output=True,
        )
        _merge_baked_settings(rt, tag, prof, volume=vol)
        merged = json.loads((prof / "settings.json").read_text())
    finally:
        subprocess.run([rt, "rmi", "-f", tag], capture_output=True)
        subprocess.run([rt, "volume", "rm", "-f", vol], capture_output=True)

    assert merged.get("statusLine") == installed["statusLine"], (
        "install-written settings key lost — _merge_baked_settings read the image, not the volume"
    )
    assert "mcp__hatago" in merged["permissions"]["allow"], "required grant not re-applied"
