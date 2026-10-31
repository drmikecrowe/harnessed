"""GH-649 S1 and S2: a stack emitted as a Claude Code plugin in harnessed's local marketplace."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from hypothesis import given
from hypothesis import strategies as st

from harnessed import hostrun, paths, plugin
from harnessed.assemble import assemble

FIX = Path(__file__).parent / "fixtures"
STACK = "plugin-stack"
CONFIG_HOOK = """sh -c 'exec node "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/x/hooks/a.js"'"""
PLUGIN_HOOK = """sh -c 'exec node "${CLAUDE_PLUGIN_ROOT}/x/hooks/a.js"'"""
CONTEXT_HOOK = 'cat "${CLAUDE_PLUGIN_ROOT}/context.md"'


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A temp HOME and XDG tree, with the fixture stack in the user overlay catalog."""
    for var, sub in (("HOME", "home"), ("XDG_DATA_HOME", "data"), ("XDG_CONFIG_HOME", "config"),
                     ("XDG_CACHE_HOME", "cache")):
        (tmp_path / sub).mkdir()
        monkeypatch.setenv(var, str(tmp_path / sub))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    catalog = tmp_path / "config" / "harnessed" / "catalog"
    shutil.copytree(FIX / "stacks" / STACK, catalog / "stacks" / STACK)
    shutil.copytree(FIX / "recipes" / "plugin-recipe", catalog / "recipes" / "plugin-recipe")
    monkeypatch.setattr(hostrun, "_host_tool_bin_dirs", lambda stack: [])
    return SimpleNamespace(tmp=tmp_path, catalog=catalog, home=tmp_path / "home")


def build(stack: str = STACK) -> Path:
    assemble(None, stack, paths.profiles_root().parent, "claude", strict=True, shared_identity=False)
    return paths.profile_dir(stack, "claude")


def author(catalog: Path, stack: str, recipe: str, recipe_yaml: str, stack_extra: str = "") -> None:
    """Write an overlay recipe and a one-recipe stack that uses it."""
    (catalog / "recipes" / recipe).mkdir(parents=True)
    (catalog / "recipes" / recipe / "recipe.yaml").write_text(f"name: {recipe}\n{recipe_yaml}")
    (catalog / "stacks" / stack).mkdir(parents=True)
    (catalog / "stacks" / stack / "stack.yaml").write_text(f"name: {stack}\nrecipes: [{recipe}]\n{stack_extra}")


def hook_commands(plugin_root: Path) -> list[str]:
    data = json.loads((plugin_root / "hooks" / "hooks.json").read_text())
    return [h["command"] for groups in data["hooks"].values() for g in groups for h in g["hooks"]]


def tree(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


class TestEmitter:
    def test_s1_1_skills_commands_and_manifest_are_copied(self, env):
        profile = build()
        # A recipe ships a command as a directory (decisions.md fact 13), so the SPEC's flat
        # `.claude/commands/bar.md` is placed in the profile directly, beside the recipe's dir.
        (profile / ".claude" / "commands" / "bar.md").write_text("---\ndescription: flat\n---\nflat bar\n")
        out = plugin.emit_plugin(STACK)
        assert out == plugin.marketplace_dir() / "plugins" / STACK
        for rel in ("skills/foo/SKILL.md", "commands/bar.md", "commands/bar/bar.md"):
            assert (out / rel).read_bytes() == (profile / ".claude" / rel).read_bytes()
        manifest = json.loads((out / ".claude-plugin" / "plugin.json").read_text())
        assert isinstance(manifest, dict) and manifest["name"] == STACK

    def test_s1_2_config_dir_hook_paths_point_at_the_plugin(self, env):
        build()
        out = plugin.emit_plugin(STACK)
        commands = hook_commands(out)
        assert PLUGIN_HOOK in commands
        assert not any("CLAUDE_CONFIG_DIR" in c for c in commands)

    def test_s1_3_user_hooks_and_permissions_never_enter_the_plugin(self, env):
        (env.home / ".claude").mkdir()
        (env.home / ".claude" / "settings.json").write_text(json.dumps({
            "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "echo user-hook"}]}]},
            "permissions": {"allow": ["Bash(ls:*)"]},
        }))
        build()
        out = plugin.emit_plugin(STACK)
        for rel, data in tree(out).items():
            assert b"user-hook" not in data, rel
            assert b'"permissions"' not in data, rel

    def test_s1_4_entry_skipped_for_claude_is_absent(self, env):
        author(env.catalog, "skip-stack", "skipper",
               "description: d\nhooks:\n  SessionStart:\n"
               "    - command: echo kept\n"
               "    - command: echo skipped\n      skip_harnesses: [claude]\n")
        build("skip-stack")
        commands = hook_commands(plugin.emit_plugin("skip-stack"))
        assert "echo kept" in commands
        assert "echo skipped" not in commands

    def test_s1_5_mcp_servers_resolve_tools_and_keep_urls(self, env, monkeypatch):
        bindir = env.tmp / "tools" / "bin"
        bindir.mkdir(parents=True)
        (bindir / "srv").write_text("#!/bin/sh\n")
        (bindir / "srv").chmod(0o755)
        monkeypatch.setattr(hostrun, "_host_tool_bin_dirs", lambda stack: [bindir])
        author(env.catalog, "mcp-stack", "mcps",
               "description: d\nmcp:\n  servers:\n"
               "    - name: srv\n      command: srv\n      transport: stdio\n"
               "    - name: web\n      url: https://example.invalid/mcp\n      transport: http\n"
               "      headers:\n        Authorization: Bearer ${TOKEN}\n"
               "    - name: svc\n      service: ping\n      transport: http\n")
        build("mcp-stack")
        servers = json.loads((plugin.emit_plugin("mcp-stack") / ".mcp.json").read_text())["mcpServers"]
        assert servers["srv"]["command"] == str(bindir / "srv")
        assert servers["web"]["url"] == "https://example.invalid/mcp"
        assert servers["web"]["headers"] == {"Authorization": "Bearer ${TOKEN}"}
        assert "svc" not in servers

    def test_s1_6_tool_bin_dirs_prefix_every_recipe_hook(self, env, monkeypatch):
        d1, d2 = env.tmp / "D1", env.tmp / "D2"
        monkeypatch.setattr(hostrun, "_host_tool_bin_dirs", lambda stack: [d1, d2])
        build()
        commands = [c for c in hook_commands(plugin.emit_plugin(STACK)) if c != CONTEXT_HOOK]
        assert commands == [f'PATH="{d1}:{d2}:$PATH" {PLUGIN_HOOK}']

    def test_s1_6_no_tools_means_no_prefix(self, env):
        build()
        commands = [c for c in hook_commands(plugin.emit_plugin(STACK)) if c != CONTEXT_HOOK]
        assert commands == [PLUGIN_HOOK]

    def test_s1_7_marketplace_lists_every_stack_and_a_rebuild_touches_only_its_own(self, env):
        author(env.catalog, "other-stack", "other", "description: d\nskills:\n  - path: skills/o\n")
        (env.catalog / "recipes" / "other" / "skills" / "o").mkdir(parents=True)
        (env.catalog / "recipes" / "other" / "skills" / "o" / "SKILL.md").write_text("---\nname: o\ndescription: o\n---\n")
        profile = build()
        build("other-stack")
        plugin.emit_plugin(STACK)
        plugin.emit_plugin("other-stack")
        other_before = tree(plugin.marketplace_dir() / "plugins" / "other-stack")
        (profile / ".claude" / "commands" / "bar" / "bar.md").unlink()
        plugin.emit_plugin(STACK)
        mkt = json.loads((plugin.marketplace_dir() / ".claude-plugin" / "marketplace.json").read_text())
        assert mkt["name"] == "harnessed"
        assert sorted((p["name"], p["source"]) for p in mkt["plugins"]) == [
            ("other-stack", "./plugins/other-stack"), (STACK, f"./plugins/{STACK}"),
        ]
        assert tree(plugin.marketplace_dir() / "plugins" / "other-stack") == other_before
        assert not (plugin.marketplace_dir() / "plugins" / STACK / "commands" / "bar" / "bar.md").exists()

    def test_s1_8_empty_stack_gets_only_a_manifest(self, env):
        author(env.catalog, "bare-stack", "bare", "description: d\n")
        build("bare-stack")
        out = plugin.emit_plugin("bare-stack")
        assert (out / ".claude-plugin" / "plugin.json").is_file()
        assert not (out / "hooks" / "hooks.json").exists()
        assert not (out / ".mcp.json").exists()

    @pytest.mark.skipif(shutil.which("claude") is None, reason="claude not on PATH")
    def test_s1_9_claude_validates_each_fixture_plugin(self, env):
        author(env.catalog, "bare-stack", "bare", "description: d\n")
        for stack in (STACK, "bare-stack"):
            build(stack)
            out = plugin.emit_plugin(stack)
            proc = subprocess.run(
                ["claude", "plugin", "validate", "--strict", str(out)], capture_output=True, text=True,
                env={**os.environ, "CLAUDE_CONFIG_DIR": str(env.tmp / "claude-cfg")}, timeout=120,
            )
            assert proc.returncode == 0, proc.stdout + proc.stderr

    def test_s1_10_credentials_are_neither_copied_nor_linked(self, env):
        (env.home / ".claude").mkdir()
        creds = env.home / ".claude" / ".credentials.json"
        creds.write_text('{"token": "GH649-SECRET-CREDS"}')
        claude_json = env.home / ".claude.json"
        claude_json.write_text('{"oauthAccount": "GH649-SECRET-ACCOUNT"}')
        build()
        plugin.emit_plugin(STACK)
        secrets = {creds.read_bytes(), claude_json.read_bytes()}
        for p in plugin.marketplace_dir().rglob("*"):
            if p.is_symlink():
                assert p.resolve() not in {creds.resolve(), claude_json.resolve()}, p
            if p.is_file():
                assert p.read_bytes() not in secrets, p


class TestMutationGaps:
    """Each test here kills mutmut survivors of plugin.py that the scenario tests above let live."""

    def test_s3_14_no_git_binary_falls_back_to_the_path(self, tmp_path, monkeypatch):
        """PR #650 review: with no `git` on PATH, local scope reads the path itself."""
        monkeypatch.setenv("PATH", str(tmp_path / "empty"))
        assert plugin.scope_settings_path("local", tmp_path) == tmp_path / ".claude" / "settings.local.json"

    def test_marketplace_is_under_xdg_data_home(self, env):
        assert plugin.marketplace_dir() == env.tmp / "data" / "harnessed" / "marketplace"

    def test_bare_config_dir_becomes_the_plugin_root(self):
        assert plugin.rewrite_hook_command('cat "$CLAUDE_CONFIG_DIR/x"') == 'cat "$CLAUDE_PLUGIN_ROOT/x"'

    def test_s1_7_marketplace_json_is_exact(self, env):
        build()
        plugin.emit_plugin(STACK)
        mkt = json.loads((plugin.marketplace_dir() / ".claude-plugin" / "marketplace.json").read_text())
        assert mkt == {
            "name": "harnessed",
            "owner": {"name": "harnessed"},
            "metadata": {"description": "Stacks built by harnessed"},
            "plugins": [{"name": STACK, "source": f"./plugins/{STACK}"}],
        }

    def test_s1_5_tool_lookup_spans_every_bin_dir(self, env, monkeypatch):
        d1, d2 = env.tmp / "D1", env.tmp / "D2"
        d1.mkdir()
        d2.mkdir()
        (d2 / "srv").write_text("#!/bin/sh\n")
        (d2 / "srv").chmod(0o755)
        monkeypatch.setattr(hostrun, "_host_tool_bin_dirs", lambda stack: [d1, d2])
        build()
        servers = json.loads((plugin.emit_plugin(STACK) / ".mcp.json").read_text())["mcpServers"]
        assert servers["srv"]["command"] == str(d2 / "srv")

    def test_s1_10_a_symlink_in_the_profile_arrives_as_bytes(self, env, tmp_path):
        profile = build()
        target = tmp_path / "outside.md"
        target.write_text("linked\n")
        (profile / ".claude" / "skills" / "foo" / "link.md").symlink_to(target)
        out = plugin.emit_plugin(STACK)
        copied = out / "skills" / "foo" / "link.md"
        assert not copied.is_symlink() and copied.read_text() == "linked\n"

    def test_s2_1_rules_sort_by_relative_path_text_and_keep_trailing_spaces(self, env):
        author(env.catalog, "rules-stack", "rulesonly",
               "description: d\nrules:\n  - path: rules/a\n  - path: rules/a-b.md\n")
        rules = env.catalog / "recipes" / "rulesonly" / "rules"
        (rules / "a").mkdir(parents=True)
        (rules / "a" / "RULE.md").write_text("AX\n")
        (rules / "a-b.md").write_text("AB \n")
        build("rules-stack")
        out = plugin.emit_plugin("rules-stack")
        # "a-b.md" sorts before "a/RULE.md" as text, since "-" < "/".
        assert (out / "context.md").read_text() == "AB \n\nAX\n"
        hooks = json.loads((out / "hooks" / "hooks.json").read_text())["hooks"]
        assert hooks == {"SessionStart": [{"hooks": [{"type": "command", "command": CONTEXT_HOOK}]}]}


class TestContextHook:
    def test_s2_1_instructions_then_sorted_rules_with_a_last_sessionstart_hook(self, env):
        build()
        out = plugin.emit_plugin(STACK)
        assert (out / "context.md").read_text() == "I\n\nA\n\nB\n"
        groups = json.loads((out / "hooks" / "hooks.json").read_text())["hooks"]["SessionStart"]
        assert groups[-1] == {"hooks": [{"type": "command", "command": CONTEXT_HOOK}]}

    def test_s2_2_no_instructions_or_rules_means_no_context(self, env):
        author(env.catalog, "hookonly-stack", "hookonly",
               "description: d\nhooks:\n  SessionStart:\n    - command: echo hi\n")
        build("hookonly-stack")
        out = plugin.emit_plugin("hookonly-stack")
        assert not (out / "context.md").exists()
        assert not any("context.md" in c for c in hook_commands(out))

    def test_s2_3_the_hook_prints_context_md(self, env):
        build()
        out = plugin.emit_plugin(STACK)
        proc = subprocess.run(["sh", "-c", CONTEXT_HOOK], capture_output=True,
                              env={**os.environ, "CLAUDE_PLUGIN_ROOT": str(out)})
        assert proc.returncode == 0
        assert proc.stdout == (out / "context.md").read_bytes()


# Module-level, not methods: hypothesis fails a method run from more than one executor (mutmut).
@given(st.text())
def test_a_command_without_the_config_dir_is_unchanged(cmd):
    if "CLAUDE_CONFIG_DIR" not in cmd:
        assert plugin.rewrite_hook_command(cmd) == cmd

@given(st.lists(st.sampled_from([
    "CLAUDE_CONFIG_DIR", "${CLAUDE_CONFIG_DIR:-$HOME/.claude}", "${CLAUDE_CONFIG_DIR}", "$CLAUDE_CONFIG_DIR",
    "${CLAUDE_CONFIG_DIR:-", "}", "/x", " ", "CLAUDE_", "CONFIG_DIR", "$", "{", "-",
])).map("".join) | st.text())
def test_no_rewritten_command_contains_the_config_dir(cmd):
    assert "CLAUDE_CONFIG_DIR" not in plugin.rewrite_hook_command(cmd)
