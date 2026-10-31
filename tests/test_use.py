"""GH-649 S2.4 and S3: `harnessed use` enables a stack as a Claude Code plugin."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import typer
from typer.testing import CliRunner

from harnessed import hosthome, launcher, plugin

FIX = Path(__file__).parent / "fixtures"
STACK = "plugin-stack"
PLUGIN_HOOK = """sh -c 'exec node "${CLAUDE_PLUGIN_ROOT}/x/hooks/a.js"'"""
runner = CliRunner()

_FAKE = f"""#!{sys.executable}
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_CLAUDE_LOG"], "a") as f:
    f.write(json.dumps({{"argv": args, "cwd": os.getcwd()}}) + "\\n")
if args[:3] == ["plugin", "marketplace", "list"]:
    print(os.environ.get("FAKE_CLAUDE_MARKETPLACES", "[]"))
elif args[:2] == ["plugin", "enable"] and os.environ.get("FAKE_CLAUDE_ENABLE_FAIL"):
    print("boom", file=sys.stderr)
    sys.exit(1)
"""


def _snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    return {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Temp HOME and XDG tree, the fixture stacks in the overlay, and a recording fake `claude`."""
    for var, sub in (("HOME", "home"), ("XDG_DATA_HOME", "data"), ("XDG_CONFIG_HOME", "config"),
                     ("XDG_CACHE_HOME", "cache")):
        (tmp_path / sub).mkdir()
        monkeypatch.setenv(var, str(tmp_path / sub))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    catalog = tmp_path / "config" / "harnessed" / "catalog"
    shutil.copytree(FIX / "stacks" / STACK, catalog / "stacks" / STACK)
    shutil.copytree(FIX / "recipes" / "plugin-recipe", catalog / "recipes" / "plugin-recipe")
    (catalog / "stacks" / "B").mkdir()
    (catalog / "stacks" / "B" / "stack.yaml").write_text("name: B\nrecipes: [plugin-recipe]\n")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "claude").write_text(_FAKE)
    (bindir / "claude").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    log = tmp_path / "claude.log"
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    proj = tmp_path / "proj"
    proj.mkdir()
    home_claude = tmp_path / "home" / ".claude"
    home_claude.mkdir()
    (home_claude / "settings.json").write_text('{"theme": "dark"}\n')

    def boom(*a, **k):
        raise AssertionError("use must never materialize a host home")

    monkeypatch.setattr(hosthome, "_materialize_host_home", boom)
    monkeypatch.setattr(launcher, "_materialize_host_home", boom)

    def calls() -> list[dict]:
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def local(enabled: dict) -> None:
        (proj / ".claude").mkdir(exist_ok=True)
        (proj / ".claude" / "settings.local.json").write_text(json.dumps({"enabledPlugins": enabled}))

    return SimpleNamespace(tmp=tmp_path, proj=proj, catalog=catalog, home_claude=home_claude,
                           calls=calls, local=local, bindir=bindir)


def use(*args: str):
    return runner.invoke(launcher.app, ["use", *args])


def argvs(env) -> list[list[str]]:
    return [c["argv"] for c in env.calls()]


class TestUse:
    def test_s3_1_registers_then_enables_locally_in_the_project(self, env):
        result = use("claude", str(env.proj), "--stack", STACK)
        assert result.exit_code == 0, result.output
        calls = [c for c in env.calls() if c["argv"][:3] != ["plugin", "marketplace", "list"]]
        assert [c["argv"] for c in calls] == [
            ["plugin", "marketplace", "add", str(plugin.marketplace_dir())],
            ["plugin", "enable", f"{STACK}@harnessed", "--scope", "local"],
        ]
        assert calls[1]["cwd"] == str(env.proj)

    def test_s3_2_a_registered_marketplace_is_not_added_again(self, env, monkeypatch):
        monkeypatch.setenv("FAKE_CLAUDE_MARKETPLACES", json.dumps(
            [{"name": "harnessed", "source": "directory", "path": str(plugin.marketplace_dir())}]))
        result = use("claude", str(env.proj), "--stack", STACK)
        assert result.exit_code == 0, result.output
        assert not any(a[:3] == ["plugin", "marketplace", "add"] for a in argvs(env))

    def test_s3_3_enables_the_target_then_disables_only_other_harnessed_plugins(self, env):
        env.local({"B@harnessed": True, "other@vendor": True, "C@harnessed": False})
        result = use("claude", str(env.proj), "--stack", STACK)
        assert result.exit_code == 0, result.output
        toggles = [a for a in argvs(env) if a[1] in ("enable", "disable")]
        assert toggles == [
            ["plugin", "enable", f"{STACK}@harnessed", "--scope", "local"],
            ["plugin", "disable", "B@harnessed", "--scope", "local"],
        ]

    def test_s3_3_from_a_subdirectory_reads_the_git_root_enablement(self, env):
        """Adversary round 2, confirmed against claude 2.1.314: `--scope local` run in a git
        subdirectory writes `<git root>/.claude/settings.local.json`."""
        subprocess.run(["git", "init", "-q", str(env.proj)], check=True)
        sub = env.proj / "sub"
        sub.mkdir()
        env.local({"B@harnessed": True})
        result = use("claude", str(sub), "--stack", STACK)
        assert result.exit_code == 0, result.output
        assert ["plugin", "disable", "B@harnessed", "--scope", "local"] in argvs(env)

    def test_s3_4_global_acts_at_user_scope_only(self, env):
        (env.home_claude / "settings.json").write_text(json.dumps({"enabledPlugins": {"B@harnessed": True}}))
        env.local({"B@harnessed": True})
        result = use("claude", "--global", "--stack", STACK)
        assert result.exit_code == 0, result.output
        toggles = [a for a in argvs(env) if a[1] in ("enable", "disable")]
        assert toggles == [
            ["plugin", "enable", f"{STACK}@harnessed", "--scope", "user"],
            ["plugin", "disable", "B@harnessed", "--scope", "user"],
        ]

    def test_s3_5_off_disables_every_harnessed_plugin_and_nothing_else(self, env):
        mkt = plugin.marketplace_dir()
        mkt.mkdir(parents=True)
        (mkt / "keep").write_text("x")
        before = _snapshot(mkt)
        env.local({f"{STACK}@harnessed": True, "other@vendor": True})
        result = use("claude", str(env.proj), "--off")
        assert result.exit_code == 0, result.output
        assert argvs(env) == [["plugin", "disable", f"{STACK}@harnessed", "--scope", "local"]]
        assert _snapshot(mkt) == before

    def test_s3_6_a_stack_with_services_is_refused(self, env):
        (env.catalog / "stacks" / "svc").mkdir()
        (env.catalog / "stacks" / "svc" / "stack.yaml").write_text(
            "name: svc\nrecipes: [plugin-recipe]\nservices: [ping]\n")
        result = use("claude", str(env.proj), "--stack", "svc")
        assert result.exit_code != 0
        assert "ping" in result.stderr and "does not support services" in result.stderr
        assert env.calls() == []
        assert not (plugin.marketplace_dir() / "plugins" / "svc").exists()

    def test_s3_7_only_claude_is_supported(self, env):
        result = use("codex", "--stack", STACK)
        assert result.exit_code != 0
        assert "supports only claude" in result.stderr
        assert env.calls() == []

    def test_s3_8_settings_a_plugin_cannot_carry_are_warned(self, env):
        (env.catalog / "stacks" / "set").mkdir()
        (env.catalog / "stacks" / "set" / "stack.yaml").write_text(
            "name: set\nrecipes: [plugin-recipe]\npermissions: auto\n"
            "settings:\n  env: x\n  defaultMode: plan\n  statusLine: s\n")
        result = use("claude", str(env.proj), "--stack", "set")
        assert result.exit_code == 0, result.output
        for key in ("permissions", "env", "defaultMode", "statusLine"):
            lines = [ln for ln in result.stderr.splitlines() if f"'{key}'" in ln]
            assert len(lines) == 1 and "not delivered by a plugin" in lines[0], (key, result.stderr)

    def test_s3_9_a_missing_claude_binary_is_named(self, env, monkeypatch):
        monkeypatch.setenv("PATH", "/nonexistent")
        result = use("claude", str(env.proj), "--stack", STACK)
        assert result.exit_code != 0
        assert "claude" in result.stderr and "PATH" in result.stderr
        assert not plugin.marketplace_dir().exists()

    def test_s3_10_a_failed_enable_leaves_the_previous_stack_on(self, env, monkeypatch):
        env.local({"B@harnessed": True})
        monkeypatch.setenv("FAKE_CLAUDE_ENABLE_FAIL", "1")
        result = use("claude", str(env.proj), "--stack", STACK)
        assert result.exit_code != 0
        assert "boom" in result.stderr
        assert not any(a[1] == "disable" for a in argvs(env))

    def test_s3_12_and_s3_13_installs_land_in_the_plugin_and_home_claude_is_untouched(self, env):
        before = _snapshot(env.home_claude)
        result = use("claude", str(env.proj), "--stack", STACK)
        assert result.exit_code == 0, result.output
        assert (plugin.marketplace_dir() / "plugins" / STACK / "x" / "marker").is_file()
        assert _snapshot(env.home_claude) == before

    def test_s3_12_a_failed_reinstall_keeps_the_previous_plugin(self, env, monkeypatch):
        """Adversary round 1: a rebuild whose install fails must not leave the enabled plugin
        without the files its hooks point at."""
        assert use("claude", str(env.proj), "--stack", STACK).exit_code == 0
        out = plugin.marketplace_dir() / "plugins" / STACK
        before = {str(p.relative_to(out)): p.read_bytes() for p in out.rglob("*") if p.is_file()}
        monkeypatch.setenv("GH649_FAIL_INSTALL", "1")
        result = use("claude", str(env.proj), "--stack", STACK)
        assert result.exit_code != 0
        assert {str(p.relative_to(out)): p.read_bytes() for p in out.rglob("*") if p.is_file()} == before
        assert not (plugin.marketplace_dir() / ".prev").exists()

    def test_s3_13_a_malformed_settings_file_stops_before_any_write(self, env):
        """Adversary round 1: unreadable settings stop `use` with a message, before the plugin is
        written or the CLI is called."""
        (env.proj / ".claude").mkdir()
        (env.proj / ".claude" / "settings.local.json").write_text("{not json")
        result = use("claude", str(env.proj), "--stack", STACK)
        assert result.exit_code == 1
        assert "settings.local.json" in result.stderr
        assert env.calls() == []
        assert not plugin.marketplace_dir().exists()

    def test_s3_13_off_leaves_home_claude_untouched(self, env):
        before = _snapshot(env.home_claude)
        env.local({f"{STACK}@harnessed": True})
        assert use("claude", str(env.proj), "--off").exit_code == 0
        assert _snapshot(env.home_claude) == before

    def test_s3_14_no_path_means_the_cwd(self, env, monkeypatch):
        monkeypatch.chdir(env.proj)
        result = use("claude", "--stack", STACK)
        assert result.exit_code == 0, result.output
        enable = [c for c in env.calls() if c["argv"][1] == "enable"]
        assert [c["cwd"] for c in enable] == [str(env.proj)]

    def test_s3_15_the_stack_resolves_as_host_run_resolves_it(self, env, monkeypatch):
        seen = []

        def spy(*args):
            seen.append(args)
            raise typer.Exit(3)

        monkeypatch.setattr(launcher, "_resolve_stack", spy)
        result = use("claude", str(env.proj), "--recipe", "plugin-recipe", "--extends", "x", "--no-extends")
        assert result.exit_code == 3
        assert seen == [(None, ["plugin-recipe"], "x", True, [])]

    def test_s3_15_help_line(self):
        result = runner.invoke(launcher.app, ["use", "--help"])
        assert "Enable a stack as a Claude Code plugin for a project or globally." in result.output


class TestDuplicateHooks:
    def test_s2_4_a_user_hook_equal_to_a_plugin_hook_is_warned(self, env):
        (env.home_claude / "settings.json").write_text(json.dumps({"hooks": {"SessionStart": [
            {"hooks": [{"type": "command", "command": PLUGIN_HOOK}]}]}}))
        result = use("claude", str(env.proj), "--stack", STACK)
        assert result.exit_code == 0, result.output
        # warn_duplicate_hooks names the command by its repr.
        assert "event='SessionStart'" in result.stderr and repr(PLUGIN_HOOK) in result.stderr

    def test_s2_4_no_overlap_prints_nothing(self, env):
        result = use("claude", str(env.proj), "--stack", STACK)
        assert result.exit_code == 0, result.output
        assert "duplicate hook" not in result.stderr


@pytest.mark.skipif(shutil.which("claude") is None, reason="claude not on PATH")
def test_s3_11_a_full_cycle_leaves_user_settings_as_they_were(env, monkeypatch):
    real = shutil.which("claude", path=os.environ["PATH"].split(os.pathsep, 1)[1])
    if real is None:
        pytest.skip("claude not on PATH")
    (env.bindir / "claude").unlink()
    (env.bindir / "claude").symlink_to(real)
    cfg = env.tmp / "claude-cfg"
    cfg.mkdir()
    (cfg / "settings.json").write_text(json.dumps({"theme": "dark", "cleanupPeriodDays": 30}))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    first = json.loads((cfg / "settings.json").read_text())
    for args in (("--stack", STACK), ("--stack", "B"), ("--off",)):
        result = use("claude", str(env.proj), *args)
        assert result.exit_code == 0, result.output
    final = json.loads((cfg / "settings.json").read_text())
    for data in (first, final):
        data.pop("enabledPlugins", None)
        data.pop("extraKnownMarketplaces", None)
    assert final == first
