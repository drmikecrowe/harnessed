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
#
# These are matched against `catalog/stacks/<name>`, so they must be BARE stack names. They were
# written in an older `claude_<recipe>` scheme under which no stack has been named for some time —
# every entry in both sets silently matched nothing, so the exclusions they document were not in
# force. `openbrain-example` is the one that still exists, and its own stack.yaml says it is
# "intentionally excluded from the live capability sweep". `hindsight` has no stack at all
# (bd harnessed-5wm).
NO_LIVE_CONNECT = {"openbrain-example"}

# CLI-only recipes with no skill/command/mcp/plugin surface at all, by design — the agent shells
# out to the binary directly and there is no `expect:` kind for "a binary is on PATH" (see e.g.
# catalog/recipes/rtk/PLAN.md "Risks / checks", or the beads recipes' recipe.yaml headers). The
# assembler-driven oracle is
# structurally empty for these; verified manually, not by this fast sweep.
#
# The four `claude_beads-team` / `claude_beads-stealth` / `claude_rtk` / `claude_solidspec` entries
# that used to sit here are gone for the reason given above NO_LIVE_CONNECT: they are stack names
# in a scheme this catalog no longer uses, so they excluded nothing. No stack is named for those
# recipes today. Dropping them changes no test outcome — it only stops the set from claiming a
# coverage decision that was never in effect.
NO_CAPABILITY_ORACLE = {
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
    for name in names:
        load_recipe(recipes_dir / paths.catalog_relpath(name), strict=True)  # raises on unknown field


def test_context_mode_hooks_are_skipped_on_omp_only():
    """The real catalog recipe, not a fixture (bd main-4fx / main-wyh).

    context-mode's capability is delivered NATIVELY on omp (its own omp extension, installed by the
    recipe's install.sh: session_start / tool_call / tool_result / session_before_compact). Replaying
    the same hook bodies through omp-claude-hooks-bridge would double-write the session DB and spawn
    a node CLI per tool call whose output the bridge discards. Every other harness must be unchanged.

    The skip is declared PER ENTRY, not recipe-wide. Same observable outcome on omp, but the reasons
    differ per event and only ONE is structural: PreToolUse additionalContext is undeliverable on omp
    at any bridge version (omp's tool_call result has no context field). The other three DO bridge —
    SessionStart and PostToolUse since 0.4.0, PreCompact since 0.5.0 — and are skipped only because
    the native extension already covers them, so two writers would duplicate the SQLite session
    store. Asserting per-entry keeps that distinction testable, so a later change that un-skips the
    bridgeable events cannot silently un-skip the structural one too.
    """
    recipe = load_recipe(ROOT / "catalog" / "recipes" / "context-mode", strict=True)
    # Deliberately empty: the recipe-wide key is all-or-nothing and cannot say "native here,
    # bridged there" per event.
    assert recipe.hooks_skip_harnesses == []
    assert set(recipe.hooks) == {"PreToolUse", "SessionStart", "PostToolUse", "PreCompact"}
    for event, entries in recipe.hooks.items():
        assert entries, event
        for entry in entries:
            assert entry.skip_harnesses == ["omp"], f"{event}: {entry.command}"

    assert "hooks" not in required_settings([], [recipe], harness="omp")
    for harness in ("claude", "opencode", "codex", "antigravity"):
        hooks = required_settings([], [recipe], harness=harness).get("hooks", {})
        assert set(hooks) == {"PreToolUse", "SessionStart", "PostToolUse", "PreCompact"}, harness


def test_context_mode_ctx_routing_rule_is_omp_only():
    """The rule and the PreToolUse skip are one decision, so assert them together.

    context-mode skips its PreToolUse hook on omp because omp's tool_call result has no context
    field, and ships rules/ctx-routing to carry that steering instead. On every other harness the
    hook fires and injects the same instruction, so shipping the rule there too would repeat it
    always-on, every session. If a future change drops one side without the other, this fails.
    """
    recipe = load_recipe(ROOT / "catalog" / "recipes" / "context-mode", strict=True)
    [rule] = recipe.rules
    assert rule.path == "rules/ctx-routing"
    assert rule.only_harnesses == ["omp"]

    # The complement: the hook this rule stands in for is skipped on exactly that harness.
    pre = recipe.hooks["PreToolUse"]
    assert all(e.skip_harnesses == ["omp"] for e in pre)

    assert rule.ships_to("omp")
    for harness in ("claude", "opencode", "codex", "antigravity"):
        assert not rule.ships_to(harness), harness


def test_codebase_memory_mcp_hooks_reach_settings():
    """The real catalog recipe: an MCP server that is present but never reached is the failure.

    `install.sh` deliberately refuses to run cbm's own installer, and that installer is also what
    upstream uses to configure these three hooks — so declaring them in recipe.yaml is the ONLY
    thing standing between the binary being on PATH and the agent actually consulting the graph.
    Asserted here rather than via `expect:`, which has no hooks kind (Expect = skills/commands/
    plugins/mcp), so nothing else in the suite would notice them silently disappearing.

    No `skip_harnesses`: unlike context-mode, cbm has no native delivery on any harness.
    """
    recipe = load_recipe(ROOT / "catalog" / "recipes" / "codebase-memory-mcp", strict=True)
    assert recipe.hooks_skip_harnesses == []

    for harness in ("claude", "opencode", "codex", "antigravity", "omp"):
        hooks = required_settings([], [recipe], harness=harness).get("hooks", {})
        assert set(hooks) == {"PreToolUse", "SessionStart", "SubagentStart"}, harness

    hooks = required_settings([], [recipe], harness="claude")["hooks"]
    # Graph-augments text search only — anchored to the tool names, since a matcher that stopped
    # covering Grep would leave the hook installed and permanently silent.
    [pre] = hooks["PreToolUse"]
    assert pre["matcher"] == "Grep|Glob"
    assert "hook-augment" in pre["hooks"][0]["command"]
    # `command -v` + `exit 0`: a PreToolUse hook that errors is noise on every single Grep.
    assert "command -v codebase-memory-mcp" in pre["hooks"][0]["command"]

    # No matcher → fires on every SessionStart source (startup/resume/clear/compact).
    [sess] = hooks["SessionStart"]
    assert "matcher" not in sess

    # The reminder heredoc must close before the indexing shell below it, or the whole tail is
    # swallowed as heredoc body and the hook silently degrades to "print some text".
    sess_body = sess["hooks"][0]["command"]
    reminder_end = sess_body.index("\nCBM_REMINDER\n")
    assert reminder_end < sess_body.index("if cbm_root=")
    # The binary guard must come BEFORE the reminder, not just before the index. An unguarded
    # reminder on a stack where the tool install failed injects "ALWAYS use codebase-memory-mcp tools
    # FIRST" while the MCP server is absent, aiming the agent at tools that do not exist.
    guard = "command -v codebase-memory-mcp >/dev/null 2>&1 || exit 0"
    assert guard in sess_body
    assert sess_body.index(guard) < sess_body.index("cat <<'CBM_REMINDER'")

    # Indexes the current checkout, because cbm ships `auto_index = false` — without this every
    # git worktree opens graph-blind while the reminder above insists the graph tools come first.
    assert "cli index_repository" in sess_body
    # Keyed to the git toplevel, NOT $PWD: a worktree must get its own branch-accurate graph, and a
    # non-git cwd must get nothing. `--repo-path "$PWD"` would index a subdirectory as a project.
    assert "--repo-path \"$cbm_root\"" in sess_body
    assert "git rev-parse --show-toplevel" in sess_body
    # Unconditional — NOT guarded on the project already existing. A re-index is 1.6s against 2.1s
    # for a first index, so such a guard buys ~0.5s and pays with a permanently stale graph. If
    # someone reintroduces one, this is the assertion that should stop them.
    assert "cli list_projects" not in sess_body
    # Detached and fully redirected on BOTH streams: a SessionStart hook's stdout is injected into
    # the agent as context, so a stray progress line would read as instructions, and a foreground
    # index would stall every session start behind a full walk.
    #
    # Asserted against the whole index invocation, NOT a bare `">/dev/null 2>&1 &" in sess_body` —
    # that substring is also present in the `command -v ... >/dev/null 2>&1 &&` guard above, so it
    # passes even when the index call is left in the foreground, unredirected. Verified by mutation:
    # this form fails when the trailing `>/dev/null 2>&1 & )` is stripped; the bare form did not.
    assert (
        'cli index_repository --repo-path "$cbm_root" >/dev/null 2>&1 & )' in sess_body
    )

    # SubagentStart injects via JSON additionalContext, NOT plain stdout — a malformed body is
    # dropped silently by the hook runner, so parse it rather than substring-matching.
    [sub] = hooks["SubagentStart"]
    assert sub["matcher"] == "*"
    body = sub["hooks"][0]["command"]
    # splitlines(), not rsplit("\n"): the YAML block scalar ends with a newline that survives only
    # until _parse_hooks' `.strip()`, and this assertion should not be coupled to that staying true.
    # splitlines() yields the same three lines either way, and pins the terminator besides — an
    # unterminated heredoc would make the hook emit nothing at all.
    _, payload_line, terminator = body.splitlines()
    assert terminator == "CBM_SUBAGENT"
    payload = json.loads(payload_line)
    assert payload["hookSpecificOutput"]["hookEventName"] == "SubagentStart"
    assert "search_graph" in payload["hookSpecificOutput"]["additionalContext"]


# --- Layer 2: live container check (podman-gated) -------------------------------------------------

from support import podman  # the one gate definition
_HARNESSED_BIN = Path(sys.executable).parent / "harnessed"


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
    # `claude` explicitly, matching the fast layer's `assemble(..., "claude")` above. Since 980d06c
    # both verbs REQUIRE a harness, and no catalog stack declares a `harnesses:` list, so the bare
    # two-word form these calls used to take is a usage error that fails before podman does any
    # work at all (bd harnessed-lxw).
    build = _run_cli("build", stack, "claude")
    assert build.returncode == 0, f"{stack}: build failed\n{build.stderr}"
    result = _run_cli("test", stack, "claude", "--json")
    assert result.returncode == 0, (
        f"{stack}: capability test exited non-zero\n{result.stdout}\n{result.stderr}"
    )
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
    # The failing capability's own `detail` carries the remediation pointer (T-02-07: the report
    # never quotes container output — see capability.MCP_MISS_REMEDIATION). Surface the details of
    # the missing capabilities so a CI reader gets the pointer without a second round trip.
    details = [f"{r['kind']}/{r['name']}: {r['detail']}" for r in report["results"] if not r["present"]]
    assert not missing, (
        f"{stack}: capabilities missing from the container: {missing}\n  "
        + "\n  ".join(details)
    )


# --- Layer 2b: settings.json post-build merge (podman-gated) ---------------------------------------
#
# The pure merge logic (emit.merge_settings / read_baked_settings) is exhaustively unit-tested in
# test_emit.py. These tests cover the part units can't: the real `podman create` + `cp` extraction
# of an image-baked ~/.claude/settings.json and the overwrite of the profile floor. We bake a
# throwaway image rather than a catalog fixture because no catalog recipe writes settings.json yet.

from harnessed import launcher
from harnessed.launcher import _merge_baked_settings, _runtime
from harnessed.paths import CONTAINER_HOME
from support import patch_all

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
            [rt, "run", "--rm", "-i", paths.USERNS_ARG,
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


@podman
def test_the_per_launch_profile_copy_does_not_stomp_install_written_settings(tmp_path):
    """bd harnessed-8px.19, arriving by a new route.

    `_ensure_config_volume` composes on EVERY launch; `_run_container_installs` runs only when the
    fingerprint moved. So the profile's settings.json copy and the install-written one are no longer
    produced by the same launch: ccstatusline's `statusLine` lands in the volume once, and a `cp -a`
    of the profile over it deleted the key on every relaunch thereafter — no status line, exactly the
    P1 this epic already closed once.

    The profile here deliberately carries NO statusLine (it never can — install.sh writes to the
    volume, not the profile), so if the copy still overwrote, the key would be gone and the first
    assertion fails. The second pins the other half: the profile must still WIN on keys it defines.
    """
    tag = "harnessed-test-settings-stomp:latest"
    rt = _build_image_with(tmp_path, tag, None)
    stack, harness = "harnessed-test-stomp-stack", "claude"
    vol = launcher._stack_config_volume(stack, harness)
    installed = {
        "statusLine": {"type": "command", "command": "ccstatusline"},
        "permissions": {"defaultMode": "bypassPermissions"},
    }
    prof = tmp_path / "profile"
    (prof / ".claude").mkdir(parents=True)
    (prof / "settings.json").write_text(json.dumps(_FLOOR))
    try:
        subprocess.run([rt, "volume", "rm", "-f", vol], capture_output=True)
        # What a real install.sh writes, under the SAME userns harnessed uses (bd harnessed-8px.21.1).
        subprocess.run(
            [rt, "run", "--rm", "-i", paths.USERNS_ARG,
             "-v", f"{vol}:{CONTAINER_HOME}/.claude", tag,
             "sh", "-c", f"cat > {CONTAINER_HOME}/.claude/settings.json"],
            input=json.dumps(installed), text=True, check=True, capture_output=True,
        )
        # fresh=False — the unchanged-stack relaunch, where installs are skipped.
        launcher._ensure_config_volume(rt, stack, harness, prof, tag, fresh=False)
        out = subprocess.run(
            [rt, "run", "--rm", paths.USERNS_ARG, "-v", f"{vol}:{CONTAINER_HOME}/.claude", tag,
             "sh", "-c", f"cat {CONTAINER_HOME}/.claude/settings.json"],
            capture_output=True, text=True, check=True,
        )
        final = json.loads(out.stdout)
    finally:
        subprocess.run([rt, "rmi", "-f", tag], capture_output=True)
        subprocess.run([rt, "volume", "rm", "-f", vol], capture_output=True)

    assert final.get("statusLine") == installed["statusLine"], (
        "install-written settings key lost — the profile copy stomped the volume's settings.json"
    )
    assert final["permissions"]["defaultMode"] == _FLOOR["permissions"]["defaultMode"], (
        "the profile must still win on the keys it defines"
    )
    assert final["permissions"]["allow"] == _FLOOR["permissions"]["allow"]


@podman
def test_a_removed_recipes_content_does_not_linger_in_the_volume(tmp_path):
    """bd harnessed-8px.21.8 — the container mirror of `_materialize_host_home`'s wipe.

    Composition is purely additive: copy-up, then `cp -a` of the profile, then installs. Nothing
    removes. So a recipe dropped from a stack would leave its skills in the volume forever, while
    the same stack on the host loses them immediately — `_materialize_host_home` rmtree's the home
    every launch precisely "so a removed recipe's files never linger".

    Asserts the wipe by putting a marker in the volume and confirming a fingerprint change clears
    it, which is what a removed recipe's content is from the volume's point of view.
    """
    tag = "harnessed-test-stale:latest"
    rt = _build_image_with(tmp_path, tag, None)
    stack, harness = "harnessed-test-stale-stack", "claude"
    vol = launcher._stack_config_volume(stack, harness)
    prof = tmp_path / "profile"
    (prof / ".claude").mkdir(parents=True)
    try:
        subprocess.run([rt, "volume", "rm", "-f", vol], capture_output=True)
        # Content from a recipe that is about to be dropped from the stack.
        subprocess.run(
            [rt, "run", "--rm", paths.USERNS_ARG, "-v", f"{vol}:{CONTAINER_HOME}/.claude", tag,
             "sh", "-c", f"mkdir -p {CONTAINER_HOME}/.claude/skills/departed && "
                         f"touch {CONTAINER_HOME}/.claude/skills/departed/SKILL.md"],
            check=True, capture_output=True,
        )
        launcher._ensure_config_volume(rt, stack, harness, prof, tag, fresh=True)
        out = subprocess.run(
            [rt, "run", "--rm", paths.USERNS_ARG, "-v", f"{vol}:{CONTAINER_HOME}/.claude", tag,
             "sh", "-c", f"ls {CONTAINER_HOME}/.claude/skills 2>/dev/null | wc -l"],
            capture_output=True, text=True,
        )
    finally:
        subprocess.run([rt, "rmi", "-f", tag], capture_output=True)
        subprocess.run([rt, "volume", "rm", "-f", vol], capture_output=True)

    assert out.stdout.strip() == "0", (
        f"the dropped recipe's content survived the wipe: {out.stdout!r}"
    )


@podman
def test_a_hung_scan_is_killed_and_its_container_reclaimed(tmp_path, monkeypatch):
    """bd harnessed-8px.28.

    A scan container ran for 71 HOURS at 0% CPU, having written nothing, because
    `_scan_image_in_container` called `subprocess.run` with no timeout. `harnessed build` would have
    waited on it forever. The container also ignored SIGTERM, so reclaiming it needs `rm -f`.

    Uses a real hanging container rather than a mocked subprocess: the failure was never in the
    Python, it was in the container surviving. A mock would assert the code path and still leave the
    bug reachable.
    """
    tag = "harnessed-test-hang:latest"
    ctx = tmp_path / "img"
    ctx.mkdir()
    # `harnessed-scan` here just blocks, standing in for the wedged `socket` call.
    (ctx / "Dockerfile").write_text(
        f"FROM {_TEST_BASE}\n"
        "RUN printf '#!/bin/sh\\nsleep 3600\\n' > /usr/local/bin/harnessed-scan "
        "&& chmod +x /usr/local/bin/harnessed-scan\n"
    )
    rt = _runtime()
    assert subprocess.run([rt, "build", "-t", tag, str(ctx)],
                          capture_output=True).returncode == 0

    monkeypatch.setattr(launcher, "_SCAN_CONTAINER_TIMEOUT", 5)
    patch_all(monkeypatch, "_resolve_launch_secrets", lambda project_path=None: ([], []))
    try:
        ok = launcher._scan_image_in_container(rt, tag)
        # Nothing from this image may still be running: the whole point is that a hang is reclaimed.
        running = subprocess.run(
            [rt, "ps", "--filter", f"ancestor={tag}", "--format", "{{.Names}}"],
            capture_output=True, text=True,
        ).stdout.strip()
    finally:
        subprocess.run([rt, "rmi", "-f", tag], capture_output=True)

    assert ok is False, "a timed-out scan must not report success"
    assert not running, f"the hung scan container survived the timeout: {running!r}"
