"""Integrations: `--register-<name>-only` runs `catalog/integrations/<name>/register` (GH-569).

An integration is an executable file in a catalog root, overlay first. The launcher builds the
stack when its profile is missing or stale, runs the file with the `HARNESSED_*` contract in the
project, and exits with its status. A launch with no register flag registers nothing.

The scenario ids (S1.1 …) are the SPEC's, in spec-evidence/2026-10-27-GH-569/SPEC.md.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from harnessed import integrations, launcher, launchscript, paths, staleness

REPO_CATALOG = Path(__file__).resolve().parents[1] / "catalog"
STACK = "gortex-ghissues"
CONTRACT = {
    "HARNESSED_INTEGRATION", "HARNESSED_HARNESS", "HARNESSED_STACK", "HARNESSED_BACKEND",
    "HARNESSED_VERB", "HARNESSED_LAUNCHER", "HARNESSED_RUN_LAUNCHER", "HARNESSED_ACP_LAUNCHER",
    "HARNESSED_PROJECT", "HARNESSED_PYTHON",
}
OPTIONAL = {
    "HARNESSED_NO_STRICT_MCP", "HARNESSED_AOE_GROUP", "HARNESSED_AOE_TITLE",
    "HARNESSED_AOE_MANAGED_WORKTREE",
}


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    """A throwaway home. XDG_CONFIG_HOME and XDG_DATA_HOME sit at their defaults inside it, so the
    editors' settings paths and the overlay agree on one tree."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    for name in CONTRACT | OPTIONAL:
        monkeypatch.delenv(name, raising=False)
    return home


@pytest.fixture
def project(tmp_path, monkeypatch) -> Path:
    p = tmp_path / "proj"
    p.mkdir()
    monkeypatch.chdir(p)
    return p


@pytest.fixture
def current(monkeypatch) -> list:
    """A current profile: `needs_build` says no, and any build is recorded."""
    builds: list = []
    monkeypatch.setattr(launcher.integrations, "needs_build", lambda stack, harness: False)
    monkeypatch.setattr(launcher, "_build_stack", lambda *a, **k: builds.append(a))
    monkeypatch.setattr(launcher, "_assemble_host", lambda *a, **k: builds.append(a))
    return builds


def run(monkeypatch, *argv: str) -> int:
    """`harnessed <argv>` through `main`, where the register flag is read. Returns the exit status."""
    monkeypatch.setattr(sys, "argv", ["harnessed", *argv])
    try:
        launcher.main()
    except SystemExit as exc:
        return 0 if exc.code is None else exc.code if isinstance(exc.code, int) else 1
    return 0


def overlay(name: str, body: str, *, mode: int = 0o755, root: Path | None = None) -> Path:
    d = (root or paths.user_catalog()) / "integrations" / name
    d.mkdir(parents=True, exist_ok=True)
    f = d / "register"
    f.write_text(body)
    f.chmod(mode)
    return f


# A register file that dumps its environment and cwd as JSON. Python, not sh: a shell adds names
# of its own (PWD, SHLVL, _), and S5.8 compares the environment name by name.
DUMP = f"""#!{sys.executable}
import json, os
json.dump({{"env": dict(os.environ), "cwd": os.getcwd()}}, open(os.environ["DUMP"], "w"))
"""


def launcher_path(home: Path, verb: str, harness: str = "claude", stack: str = STACK) -> str:
    return str(home / ".local" / "bin" / launchscript.global_name(verb, stack, harness))


# --- S5. Lookup and the runner -------------------------------------------------------------------


class TestRunner:
    def test_s5_1_the_contract_reaches_the_integration(self, monkeypatch, home, project, current, tmp_path):
        overlay("zellij", DUMP)
        monkeypatch.setenv("DUMP", str(tmp_path / "dump.json"))
        assert run(monkeypatch, "host-run", "claude", "--stack", STACK, "--register-zellij-only") == 0
        seen = json.loads((tmp_path / "dump.json").read_text())
        env = seen["env"]
        assert env["HARNESSED_INTEGRATION"] == "zellij"
        assert env["HARNESSED_HARNESS"] == "claude"
        assert env["HARNESSED_STACK"] == STACK
        assert env["HARNESSED_BACKEND"] == "host"
        assert env["HARNESSED_VERB"] == "host-run"
        assert env["HARNESSED_LAUNCHER"] == launcher_path(home, "host-run")
        assert env["HARNESSED_RUN_LAUNCHER"] == launcher_path(home, "host-run")
        assert env["HARNESSED_ACP_LAUNCHER"] == launcher_path(home, "host-acp")
        assert env["HARNESSED_PROJECT"] == str(project)
        assert env["HARNESSED_PYTHON"] == sys.executable
        assert seen["cwd"] == str(project)
        assert current == [], "a current profile is not rebuilt"

    def test_s5_1_the_global_launchers_are_written_first(self, monkeypatch, home, project, current, tmp_path):
        overlay("zellij", DUMP)
        monkeypatch.setenv("DUMP", str(tmp_path / "dump.json"))
        assert run(monkeypatch, "host-run", "claude", "--stack", STACK, "--register-zellij-only") == 0
        assert Path(launcher_path(home, "host-run")).is_file()
        assert Path(launcher_path(home, "host-acp")).is_file()

    def test_s5_1_the_container_backend_names_its_own_launchers(self, monkeypatch, home, project, current, tmp_path):
        overlay("zellij", DUMP)
        monkeypatch.setenv("DUMP", str(tmp_path / "dump.json"))
        monkeypatch.setattr(launcher.claude_imports, "ask", lambda *a: None)
        assert run(monkeypatch, "container-run", "claude", "--stack", STACK, "--register-zellij-only") == 0
        env = json.loads((tmp_path / "dump.json").read_text())["env"]
        assert env["HARNESSED_BACKEND"] == "container"
        assert env["HARNESSED_LAUNCHER"] == launcher_path(home, "container-run")
        assert env["HARNESSED_ACP_LAUNCHER"] == launcher_path(home, "container-acp")

    def test_s5_1_a_harness_with_no_acp_mode_gets_an_empty_acp_launcher(self, monkeypatch, home, project, current, tmp_path):
        overlay("zellij", DUMP)
        monkeypatch.setenv("DUMP", str(tmp_path / "dump.json"))
        assert run(monkeypatch, "container-run", "codex", "--stack", STACK, "--register-zellij-only") == 0
        assert json.loads((tmp_path / "dump.json").read_text())["env"]["HARNESSED_ACP_LAUNCHER"] == ""

    def test_s5_2_the_overlay_wins_over_the_repo_catalog(self, monkeypatch, home, project, current, tmp_path):
        repo = tmp_path / "repo-catalog"
        overlay("zellij", f'#!/bin/sh\ntouch "{tmp_path}/overlay"\n')
        overlay("zellij", f'#!/bin/sh\ntouch "{tmp_path}/repo"\n', root=repo)
        monkeypatch.setattr(paths, "catalog_roots", lambda: [paths.user_catalog(), repo])
        assert run(monkeypatch, "host-run", "claude", "--stack", STACK, "--register-zellij-only") == 0
        assert (tmp_path / "overlay").exists()
        assert not (tmp_path / "repo").exists()

    def test_s5_3_an_unknown_name_lists_every_root_and_builds_nothing(self, monkeypatch, home, project, current, capfd):
        overlay("zellij", "#!/bin/sh\n")
        assert run(monkeypatch, "host-run", "claude", "--stack", STACK, "--register-nosuch-only") == 2
        err = capfd.readouterr().err
        assert "nosuch" in err
        assert "aoe, atlas, vscode, zed, zellij" in err
        assert current == []
        assert not Path(launcher_path(home, "host-run")).exists(), "nothing is written"

    def test_s5_3_no_build_runs_even_when_the_profile_is_missing(self, monkeypatch, home, project):
        builds: list = []
        monkeypatch.setattr(launcher, "_build_stack", lambda *a, **k: builds.append(a))
        monkeypatch.setattr(launcher, "_assemble_host", lambda *a, **k: builds.append(a))
        assert run(monkeypatch, "host-run", "claude", "--stack", STACK, "--register-nosuch-only") == 2
        assert builds == []

    def test_s5_4_a_register_file_that_is_not_executable_is_refused(self, monkeypatch, home, project, current, capfd):
        f = overlay("zellij", "#!/bin/sh\n", mode=0o644)
        assert run(monkeypatch, "host-run", "claude", "--stack", STACK, "--register-zellij-only") == 2
        err = capfd.readouterr().err
        assert str(f) in err.replace("\n", "")
        assert "not executable" in err

    def test_s5_5_the_launcher_exits_with_the_integrations_status(self, monkeypatch, home, project, current):
        overlay("zellij", "#!/bin/sh\nexit 3\n")
        assert run(monkeypatch, "host-run", "claude", "--stack", STACK, "--register-zellij-only") == 3

    def test_s5_5_a_signal_death_is_128_plus_the_signal(self, monkeypatch, home, project, current):
        overlay("zellij", "#!/bin/sh\nkill -TERM $$\n")
        assert run(monkeypatch, "host-run", "claude", "--stack", STACK, "--register-zellij-only") == 143

    def test_s5_6_two_register_flags_are_refused(self, monkeypatch, home, project, current, capfd, tmp_path):
        overlay("zellij", f'#!/bin/sh\ntouch "{tmp_path}/ran"\n')
        code = run(
            monkeypatch, "host-run", "claude", "--stack", STACK,
            "--register-zellij-only", "--register-zed-only",
        )
        assert code == 2
        assert "only one --register-<name>-only flag is allowed per command" in capfd.readouterr().err
        assert not (tmp_path / "ran").exists()

    def test_s5_7_a_flag_after_double_dash_is_passthrough(self, monkeypatch, home, project, current, tmp_path):
        overlay("zellij", f'#!/bin/sh\ntouch "{tmp_path}/ran"\n')
        seen: dict = {}
        monkeypatch.setattr(launcher.claude_imports, "ask", lambda *a: None)
        monkeypatch.setattr(launcher, "_launch_host", lambda *a, **k: seen.update(k))
        assert run(monkeypatch, "host-run", "claude", "--stack", STACK, "--", "--register-zellij-only") == 0
        assert seen["extra"] == ["--register-zellij-only"]
        assert not (tmp_path / "ran").exists()

    def test_s5_8_the_environment_is_the_parents_plus_the_contract(self, monkeypatch, home, project, current, tmp_path):
        overlay("zellij", DUMP)
        monkeypatch.setenv("DUMP", str(tmp_path / "dump.json"))
        monkeypatch.setenv("SOME_TOKEN", "parent-value")
        parent = dict(os.environ)
        assert run(monkeypatch, "host-run", "claude", "--stack", STACK, "--register-zellij-only") == 0
        child = json.loads((tmp_path / "dump.json").read_text())["env"]
        assert set(child) - set(parent) == CONTRACT
        assert {k: child[k] for k in parent} == parent, "a name the parent set was changed"
        assert child["HARNESSED_PYTHON"] == sys.executable
        for name in CONTRACT - {"HARNESSED_PYTHON"}:
            value = child[name]
            assert value == "" or "\n" not in value

    def test_s5_8_the_optional_names_carry_what_the_user_typed(self, monkeypatch, home, project, current, tmp_path):
        overlay("zellij", DUMP)
        monkeypatch.setenv("DUMP", str(tmp_path / "dump.json"))
        code = run(
            monkeypatch, "host-run", "claude", "--stack", STACK, "--register-zellij-only",
            "--no-strict-mcp-config", "--aoe-group", "G", "--aoe-title", "T", "--aoe-managed-worktree",
        )
        assert code == 0
        env = json.loads((tmp_path / "dump.json").read_text())["env"]
        assert {k: env[k] for k in OPTIONAL} == {
            "HARNESSED_NO_STRICT_MCP": "1", "HARNESSED_AOE_GROUP": "G",
            "HARNESSED_AOE_TITLE": "T", "HARNESSED_AOE_MANAGED_WORKTREE": "1",
        }

    def test_s5_8_a_stale_optional_name_in_the_parent_does_not_leak(self, monkeypatch, home, project, current, tmp_path):
        """An optional name is set ONLY when the launch was given its flag. One left in the parent by
        an outer launch would otherwise read as this launch's `--aoe-group`."""
        overlay("zellij", DUMP)
        monkeypatch.setenv("DUMP", str(tmp_path / "dump.json"))
        monkeypatch.setenv("HARNESSED_AOE_GROUP", "stale")
        assert run(monkeypatch, "host-run", "claude", "--stack", STACK, "--register-zellij-only") == 0
        assert "HARNESSED_AOE_GROUP" not in json.loads((tmp_path / "dump.json").read_text())["env"]

    def test_the_flag_is_read_only_on_a_global_verb(self, monkeypatch, home, project, current):
        """`harnessed build` runs no integration: the flag is an unknown option there."""
        assert run(monkeypatch, "build", STACK, "claude", "--register-zed-only") == 2

    def test_a_missing_project_directory_is_refused(self, monkeypatch, home, project, current, tmp_path):
        overlay("zellij", "#!/bin/sh\n")
        code = run(
            monkeypatch, "host-run", "claude", str(tmp_path / "gone"), "--stack", STACK,
            "--register-zellij-only",
        )
        assert code == 1

    def test_a_register_file_that_cannot_be_run_fails(self, monkeypatch, home, project, current, capfd):
        overlay("zellij", "no shebang here\x00")
        assert run(monkeypatch, "host-run", "claude", "--stack", STACK, "--register-zellij-only") == 1
        assert "cannot run" in capfd.readouterr().err


class TestExtract:
    @pytest.mark.parametrize(
        ("argv", "want"),
        [
            (["host-run", "claude", "--register-zed-only"], (["host-run", "claude"], "zed")),
            (["host-acp", "claude", "--register-a-b-only", "-s", "x"], (["host-acp", "claude", "-s", "x"], "a-b")),
            (["container-acp", "claude", "--register-zed-only"], (["container-acp", "claude"], "zed")),
            (["container-run", "c", "--", "--register-zed-only"], (["container-run", "c", "--", "--register-zed-only"], None)),
            (["build", "--register-zed-only"], (["build", "--register-zed-only"], None)),
            (["host-run", "--register--only"], (["host-run", "--register--only"], None)),
            (["host-run", "--register-Zed-only"], (["host-run", "--register-Zed-only"], None)),
            ([], ([], None)),
        ],
    )
    def test_one_flag_is_split_off_before_double_dash(self, argv, want):
        assert integrations.extract(argv) == want

    def test_two_flags_are_a_usage_error(self):
        with pytest.raises(integrations.IntegrationError) as exc:
            integrations.extract(["host-run", "--register-a-only", "x", "--register-b-only"])
        assert exc.value.code == 2


# --- S7. Build first -----------------------------------------------------------------------------


class TestBuildFirst:
    def test_s7_1_a_missing_profile_needs_a_build(self, monkeypatch):
        monkeypatch.setattr(integrations.paths, "is_built", lambda s, h: False)
        assert integrations.needs_build(STACK, "claude") is True

    def test_s7_2_a_stale_stamp_needs_a_build(self, monkeypatch):
        monkeypatch.setattr(integrations.paths, "is_built", lambda s, h: True)

        def stale(*_a, **_k):
            raise staleness.StaleProfileError("stale")

        monkeypatch.setattr(integrations.staleness, "check_profile_fresh", stale)
        assert integrations.needs_build(STACK, "claude") is True

    def test_s7_2_a_recipe_that_no_longer_resolves_needs_a_build(self, monkeypatch):
        monkeypatch.setattr(integrations.paths, "is_built", lambda s, h: True)

        def gone(*_a, **_k):
            raise integrations.SchemaError("recipe 'x' does not resolve")

        monkeypatch.setattr(integrations.staleness, "check_profile_fresh", gone)
        assert integrations.needs_build(STACK, "claude") is True

    def test_s7_3_a_current_profile_needs_no_build(self, monkeypatch):
        monkeypatch.setattr(integrations.paths, "is_built", lambda s, h: True)
        monkeypatch.setattr(integrations.staleness, "check_profile_fresh", lambda *a, **k: None)
        assert integrations.needs_build(STACK, "claude") is False

    def test_s7_3_the_real_stamp_check_reads_a_current_profile(self, home):
        """`needs_build` against a real profile and stamp, not stubs: fresh, then stale on an edit."""
        stack, recipes = staleness.load_stack_with_recipes(None, "hostmcp")
        prof = paths.profile_dir("hostmcp", "claude")
        prof.mkdir(parents=True)
        (prof / ".mcp.json").write_text("{}")
        staleness.write_stamp(prof, staleness.compute_stamp(None, stack, recipes))
        assert integrations.needs_build("hostmcp", "claude") is False
        staleness.write_stamp(prof, "not-the-stamp")
        assert integrations.needs_build("hostmcp", "claude") is True

    def test_s7_1_the_build_runs_before_the_integration(self, monkeypatch, home, project, tmp_path):
        marker = tmp_path / "ran"
        overlay("zellij", f'#!/bin/sh\ntouch "{marker}"\n')
        order: list = []
        monkeypatch.setattr(launcher.integrations, "needs_build", lambda s, h: True)
        # A host verb builds by assembling in-process (PR #645); the container verb is pinned below.
        monkeypatch.setattr(
            launcher, "_assemble_host", lambda s, h: order.append((s, h, marker.exists()))
        )
        assert run(monkeypatch, "host-run", "claude", "--stack", STACK, "--register-zellij-only") == 0
        assert order == [(STACK, "claude", False)]
        assert marker.exists()

    def test_s7_4_a_failed_build_runs_no_integration(self, monkeypatch, home, project, tmp_path, capfd):
        marker = tmp_path / "ran"
        overlay("zellij", f'#!/bin/sh\ntouch "{marker}"\n')
        monkeypatch.setattr(launcher.integrations, "needs_build", lambda s, h: True)
        monkeypatch.setattr(launcher, "_runtime", lambda: "podman")

        def fail(*_a):
            launcher._err.print("[bold red]error:[/bold red] assembling stack failed: boom")
            raise typer.Exit(1)

        monkeypatch.setattr(launcher, "_assemble_host", fail)
        assert run(monkeypatch, "host-run", "claude", "--stack", STACK, "--register-zellij-only") == 1
        assert "boom" in capfd.readouterr().err
        assert not marker.exists()
        assert not Path(launcher_path(home, "host-run")).exists(), "nothing is written"


# --- S2, S3, S4. The editor integrations ---------------------------------------------------------


def zed_file(home: Path) -> Path:
    return home / ".config" / "zed" / "settings.json"


def atlas_file(home: Path) -> Path:
    return home / ".local" / "share" / "dev.atlas.ide" / "external-agents" / "installed.json"


def vscode_file(home: Path) -> Path:
    return home / ".config" / "Code" / "User" / "settings.json"


def put(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def only_inserted(old: str, new: str) -> list[str]:
    """The lines `new` adds to `old`, asserting it adds them in one block and changes no other line."""
    a, b = old.splitlines(), new.splitlines()
    ops = [op for op in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if op[0] != "equal"]
    assert [op[0] for op in ops] == ["insert"], f"lines other than one inserted block changed: {ops}"
    return b[ops[0][3] : ops[0][4]]


def jsonc_value(path: Path):
    from harnessed import jsonc

    return jsonc.parse(path.read_text())


ZED_KEY = f"harnessed claude ({STACK})"

ZED_SETTINGS = """// Zed settings
{
  /* the theme */
  "theme": "One Dark", // a note
  "agent_servers": {
    "other": {
      "type": "custom",
      "command": "/bin/other",
      "args": [],
    },
  },
  "vim_mode": true,
}
"""


class TestZed:
    def register(self, monkeypatch, verb: str = "host-run", harness: str = "claude") -> int:
        monkeypatch.setattr(launcher.claude_imports, "ask", lambda *a: None)
        return run(monkeypatch, verb, harness, "--stack", STACK, "--register-zed-only")

    def test_s2_1_the_entry_runs_the_acp_launcher(self, monkeypatch, home, project, current):
        put(zed_file(home), '{\n  "agent_servers": {}\n}\n')
        assert self.register(monkeypatch) == 0
        assert jsonc_value(zed_file(home))["agent_servers"][ZED_KEY] == {
            "type": "custom", "command": launcher_path(home, "host-acp"), "args": [], "env": {},
        }

    def test_s2_2_a_second_run_changes_no_byte(self, monkeypatch, home, project, current):
        put(zed_file(home), ZED_SETTINGS)
        assert self.register(monkeypatch) == 0
        once = zed_file(home).read_bytes()
        assert self.register(monkeypatch) == 0
        assert zed_file(home).read_bytes() == once

    def test_s2_3_only_the_entrys_lines_change(self, monkeypatch, home, project, current):
        put(zed_file(home), ZED_SETTINGS)
        assert self.register(monkeypatch) == 0
        added = only_inserted(ZED_SETTINGS, zed_file(home).read_text())
        assert added[0].strip() == f'"{ZED_KEY}": {{'
        assert added[-1].strip() == "},"
        assert len(added) == 6

    def test_s2_4_an_existing_entry_keeps_its_other_members(self, monkeypatch, home, project, current):
        put(zed_file(home), (
            '{\n  "agent_servers": {\n'
            f'    "{ZED_KEY}": {{\n'
            '      "type": "stdio",\n'
            '      "command": "/old/launcher",\n'
            '      "args": ["--x"],\n'
            '      "env": {"A": "1"},\n'
            '      "default_config_options": {"mode": "plan"}\n'
            '    }\n  }\n}\n'
        ))
        assert self.register(monkeypatch) == 0
        text = zed_file(home).read_text()
        assert jsonc_value(zed_file(home))["agent_servers"][ZED_KEY] == {
            "type": "custom", "command": launcher_path(home, "host-acp"),
            "args": ["--x"], "env": {"A": "1"}, "default_config_options": {"mode": "plan"},
        }
        assert '      "args": ["--x"],\n      "env": {"A": "1"},\n' in text
        assert '"default_config_options": {"mode": "plan"}\n' in text

    def test_s2_5_a_missing_file_is_created(self, monkeypatch, home, project, current):
        assert self.register(monkeypatch) == 0
        assert ZED_KEY in jsonc_value(zed_file(home))["agent_servers"]

    def test_s2_5_a_file_with_no_agent_servers_gets_one(self, monkeypatch, home, project, current):
        old = '{\n  // mine\n  "theme": "x",\n}\n'
        put(zed_file(home), old)
        assert self.register(monkeypatch) == 0
        assert only_inserted(old, zed_file(home).read_text())[0].strip() == '"agent_servers": {'
        assert jsonc_value(zed_file(home))["theme"] == "x"
        assert ZED_KEY in jsonc_value(zed_file(home))["agent_servers"]

    def test_s2_6_invalid_json_is_refused_and_left_as_it_was(self, monkeypatch, home, project, current, capfd):
        put(zed_file(home), '{\n  "agent_servers": {\n')
        before = zed_file(home).read_bytes()
        assert self.register(monkeypatch) == 1
        err = capfd.readouterr().err
        assert str(zed_file(home)) in err and "line 3" in err
        assert zed_file(home).read_bytes() == before

    def test_s2_7_a_harness_with_no_acp_mode_is_refused(self, monkeypatch, home, project, current, capfd):
        assert self.register(monkeypatch, "container-run", "codex") == 1
        err = capfd.readouterr().err
        assert "Zed needs an ACP harness" in err
        assert "omp, claude" in err
        assert not zed_file(home).exists()

    def test_s2_8_the_container_entry_is_its_own(self, monkeypatch, home, project, current):
        assert self.register(monkeypatch) == 0
        host = jsonc_value(zed_file(home))["agent_servers"][ZED_KEY]
        assert self.register(monkeypatch, "container-run") == 0
        servers = jsonc_value(zed_file(home))["agent_servers"]
        assert servers[f"harnessed claude ({STACK}, container)"]["command"] == launcher_path(
            home, "container-acp"
        )
        assert servers[ZED_KEY] == host


ATLAS_KEY = ZED_KEY


class TestAtlas:
    def register(self, monkeypatch, verb: str = "host-run", harness: str = "claude") -> int:
        monkeypatch.setattr(launcher.claude_imports, "ask", lambda *a: None)
        return run(monkeypatch, verb, harness, "--stack", STACK, "--register-atlas-only")

    def test_s3_1_the_entry_runs_the_acp_launcher(self, monkeypatch, home, project, current):
        put(atlas_file(home), "{}\n")
        assert self.register(monkeypatch) == 0
        assert json.loads(atlas_file(home).read_text()) == {
            ATLAS_KEY: {"type": "custom", "command": launcher_path(home, "host-acp"), "args": []},
        }

    def test_s3_2_other_entries_keep_their_bytes(self, monkeypatch, home, project, current):
        a = '"a": {"type": "custom", "command": "/bin/a", "args": []}'
        b = '"b": {"type": "custom", "command": "/bin/b", "args": ["x"]}'
        put(atlas_file(home), f"{{\n  {a},\n  {b}\n}}\n")
        assert self.register(monkeypatch) == 0
        text = atlas_file(home).read_text()
        assert f"  {a},\n  {b}\n}}\n" in text
        assert ATLAS_KEY in json.loads(text)

    def test_s3_3_the_directory_and_file_are_created(self, monkeypatch, home, project, current):
        assert self.register(monkeypatch) == 0
        assert list(json.loads(atlas_file(home).read_text())) == [ATLAS_KEY]

    def test_s3_4_invalid_json_is_refused(self, monkeypatch, home, project, current, capfd):
        put(atlas_file(home), "{oops}")
        assert self.register(monkeypatch) == 1
        assert str(atlas_file(home)) in capfd.readouterr().err
        assert atlas_file(home).read_text() == "{oops}"

    def test_s3_5_a_harness_with_no_acp_mode_is_refused(self, monkeypatch, home, project, current, capfd):
        assert self.register(monkeypatch, "container-run", "codex") == 1
        err = capfd.readouterr().err
        assert "Atlas needs an ACP harness" in err
        assert "omp, claude" in err
        assert not atlas_file(home).exists()


class TestVscode:
    def register(self, monkeypatch, verb: str = "host-run", harness: str = "claude", stack: str = STACK) -> int:
        monkeypatch.setattr(launcher.claude_imports, "ask", lambda *a: None)
        return run(monkeypatch, verb, harness, "--stack", stack, "--register-vscode-only")

    def test_s4_1_the_wrapper_is_the_claude_launcher(self, monkeypatch, home, project, current):
        put(vscode_file(home), '{\n  "editor.fontSize": 14\n}\n')
        assert self.register(monkeypatch) == 0
        assert jsonc_value(vscode_file(home)) == {
            "claudeCode.claudeProcessWrapper": launcher_path(home, "host-run"),
            "editor.fontSize": 14,
        }

    def test_s4_1_the_acp_launcher_still_registers_the_run_launcher(self, monkeypatch, home, project, current):
        monkeypatch.setattr(launcher, "set_acp_mode", lambda on: None)
        assert self.register(monkeypatch, "host-acp") == 0
        assert jsonc_value(vscode_file(home))["claudeCode.claudeProcessWrapper"] == launcher_path(
            home, "host-run"
        )

    def test_s4_2_a_second_stack_replaces_the_value_on_its_line(self, monkeypatch, home, project, current):
        put(vscode_file(home), '{\n  // mine\n  "editor.fontSize": 14\n}\n')
        assert self.register(monkeypatch) == 0
        before = vscode_file(home).read_text().splitlines()
        assert self.register(monkeypatch, stack="superpowers") == 0
        after = vscode_file(home).read_text().splitlines()
        changed = [i for i, (a, b) in enumerate(zip(before, after, strict=True)) if a != b]
        assert len(changed) == 1
        assert after[changed[0]].strip() == (
            f'"claudeCode.claudeProcessWrapper": "{launcher_path(home, "host-run", stack="superpowers")}",'
        )

    def test_s4_3_a_non_claude_harness_is_refused(self, monkeypatch, home, project, current, capfd):
        put(vscode_file(home), "{}\n")
        assert self.register(monkeypatch, harness="omp") == 1
        assert "supports claude only" in capfd.readouterr().err
        assert vscode_file(home).read_text() == "{}\n"

    def test_s4_5_invalid_json_is_refused(self, monkeypatch, home, project, current, capfd):
        put(vscode_file(home), '{\n  "a": 1\n')
        assert self.register(monkeypatch) == 1
        err = capfd.readouterr().err
        assert str(vscode_file(home)) in err and "line 3" in err
        assert vscode_file(home).read_text() == '{\n  "a": 1\n'

    def test_s4_7_the_container_backend_is_refused(self, monkeypatch, home, project, current, capfd):
        put(vscode_file(home), "{}\n")
        assert self.register(monkeypatch, "container-run") == 1
        assert "supports the host backend only" in capfd.readouterr().err
        assert vscode_file(home).read_text() == "{}\n"


class TestVscodeWrapperArgv:
    """S4.4: the extension runs `<wrapper> <bundled claude> <SDK args>`."""

    @pytest.fixture
    def bundled(self, tmp_path) -> Path:
        claude = tmp_path / "ext" / "claude"
        claude.parent.mkdir()
        claude.write_text(f'#!/bin/sh\ntouch "{tmp_path}/bundled-ran"\n')
        claude.chmod(0o755)
        return claude

    def test_s4_4_the_bundled_claude_is_dropped_and_the_rest_is_passthrough(
        self, monkeypatch, home, project, bundled, tmp_path
    ):
        seen: dict = {}
        monkeypatch.setattr(launcher.claude_imports, "ask", lambda *a: None)
        monkeypatch.setattr(
            launcher, "_launch_host", lambda stack, harness, path, **k: seen.update(path=path, **k)
        )
        sdk = ["--output-format", "stream-json", "--input-format", "stream-json", "--verbose"]
        assert run(monkeypatch, "host-run", "claude", "--stack", STACK, str(bundled), *sdk) == 0
        assert seen["path"] is None, "the project is the cwd"
        assert seen["extra"] == sdk
        assert not (tmp_path / "bundled-ran").exists()

    @pytest.mark.parametrize(
        "argv",
        [
            ["host-run", "claude", "--stack", "s", "/x/claude", "-v"],  # no such file
            ["host-run", "omp", "--stack", "s", "{claude}", "-v"],  # not the claude harness
            ["host-exec", "claude", "--stack", "s", "{claude}", "-v"],  # not a global verb
            ["host-run", "claude", "--stack", "s", "relative/claude", "-v"],
            ["host-run", "claude", "--stack", "s", "--", "{claude}", "-v"],
            ["host-run", "claude", "--stack", "s"],
            ["host-run", "claude", "--stack", "s", "--rm"],
            ["host-run"],
        ],
    )
    def test_any_other_argv_is_left_as_it_is(self, argv, bundled):
        argv = [a.replace("{claude}", str(bundled)) for a in argv]
        assert launcher._vscode_wrapper_argv(list(argv)) == argv

    def test_an_executable_not_named_claude_is_left(self, tmp_path):
        other = tmp_path / "node"
        other.write_text("#!/bin/sh\n")
        other.chmod(0o755)
        argv = ["host-run", "claude", "--stack", "s", str(other)]
        assert launcher._vscode_wrapper_argv(argv) == argv

    def test_a_claude_file_that_is_not_executable_is_left(self, tmp_path):
        claude = tmp_path / "claude"
        claude.write_text("")
        argv = ["host-run", "claude", "--stack", "s", str(claude)]
        assert launcher._vscode_wrapper_argv(argv) == argv

    def test_the_container_verb_and_flags_before_it_are_read(self, bundled):
        argv = ["container-run", "claude", "-s", "s", "--rm", str(bundled), "-p", "--", "x"]
        assert launcher._vscode_wrapper_argv(argv) == [
            "container-run", "claude", "-s", "s", "--rm", "--", "-p", "--", "x",
        ]


# --- S1. aoe -------------------------------------------------------------------------------------

AOE_SCRIPT = REPO_CATALOG / "integrations" / "aoe" / "register"


def aoe_env(home: Path, project: Path, verb: str = "host-run", **extra: str) -> dict:
    backend = "container" if verb.startswith("container") else "host"
    return {
        "HARNESSED_INTEGRATION": "aoe", "HARNESSED_HARNESS": "claude", "HARNESSED_STACK": STACK,
        "HARNESSED_BACKEND": backend, "HARNESSED_VERB": verb,
        "HARNESSED_LAUNCHER": launcher_path(home, verb),
        "HARNESSED_RUN_LAUNCHER": launcher_path(home, f"{backend}-run"),
        "HARNESSED_ACP_LAUNCHER": launcher_path(home, f"{backend}-acp"),
        "HARNESSED_PROJECT": str(project), "HARNESSED_PYTHON": sys.executable, **extra,
    }


class TestAoeScript:
    def test_s1_7_an_acp_launcher_is_refused(self, home, project):
        env = {**os.environ, **aoe_env(home, project, "host-acp")}
        proc = subprocess.run([str(AOE_SCRIPT)], env=env, capture_output=True, text=True, check=False)
        assert proc.returncode == 1
        assert "aoe replays a terminal launcher" in proc.stderr
        assert "harnessed-claude-gortex-ghissues-host" in proc.stderr
        assert proc.stdout == ""

    def test_the_script_hands_over_to_aoe_register(self, home, project, tmp_path):
        fake = tmp_path / "python"
        fake.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{tmp_path}/argv"\n')
        fake.chmod(0o755)
        env = {**os.environ, **aoe_env(home, project), "HARNESSED_PYTHON": str(fake)}
        proc = subprocess.run([str(AOE_SCRIPT)], env=env, capture_output=True, text=True, check=False)
        assert proc.returncode == 0, proc.stderr
        assert (tmp_path / "argv").read_text().split() == ["-m", "harnessed", "aoe-register"]

    @pytest.mark.parametrize("name", ["aoe", "zed", "atlas", "vscode"])
    def test_every_shipped_register_file_is_executable(self, name):
        f = REPO_CATALOG / "integrations" / name / "register"
        assert f.is_file() and os.access(f, os.X_OK)


class TestAoeRegister:
    """The hidden `aoe-register` command the aoe integration execs, driven in-process."""

    def invoke(self, monkeypatch, home, project, *, aoe_bin: str | None = "/usr/bin/aoe", ok: bool = True, **extra):
        seen: dict = {"calls": []}

        def fake_sync(verb, stack, harness, project_path, **kw):
            seen["calls"].append((verb, stack, harness, project_path, kw))
            return ok

        monkeypatch.setattr(launcher.aoe, "_bin", lambda: aoe_bin)
        monkeypatch.setattr(launcher.aoe, "sync_session", fake_sync)
        for k, v in aoe_env(home, project, **extra).items():
            monkeypatch.setenv(k, v)
        result = CliRunner().invoke(launcher.app, ["aoe-register"])
        seen["code"] = result.exit_code
        seen["output"] = result.output
        return seen

    def test_s1_1_one_row_and_the_local_launcher(self, monkeypatch, home, project):
        seen = self.invoke(monkeypatch, home, project)
        assert seen["code"] == 0, seen["output"]
        [(verb, stack, harness, path, kw)] = seen["calls"]
        assert (verb, stack, harness, path) == ("host-run", STACK, "claude", project)
        assert kw["background"] is False
        local = project / f"claude-{STACK}-host"
        assert local.is_file()
        assert f"exec {launcher_path(home, 'host-run')}" in local.read_text() or (
            f"harnessed-claude-{STACK}-host" in local.read_text()
        )
        assert Path(launcher_path(home, "host-run")).is_file()

    def test_s1_5_no_aoe_writes_nothing(self, monkeypatch, home, project):
        seen = self.invoke(monkeypatch, home, project, aoe_bin=None)
        assert seen["code"] == 1
        assert "Agent of Empires" in seen["output"] and "not installed" in seen["output"]
        assert seen["calls"] == []
        assert list(project.iterdir()) == []

    def test_s1_6_group_title_and_worktree_reach_the_row(self, monkeypatch, home, project):
        seen = self.invoke(
            monkeypatch, home, project, HARNESSED_AOE_GROUP="G", HARNESSED_AOE_TITLE="T",
            HARNESSED_AOE_MANAGED_WORKTREE="1", HARNESSED_NO_STRICT_MCP="1",
        )
        assert seen["code"] == 0, seen["output"]
        kw = seen["calls"][0][4]
        assert (kw["group"], kw["title"], kw["managed_worktree"], kw["no_strict_mcp"]) == (
            "G", "T", True, True
        )
        assert kw["background"] is False

    def test_a_failed_write_exits_1(self, monkeypatch, home, project):
        assert self.invoke(monkeypatch, home, project, ok=False)["code"] == 1

    def test_the_command_needs_the_contract(self, monkeypatch, home):
        for name in CONTRACT:
            monkeypatch.delenv(name, raising=False)
        result = CliRunner().invoke(launcher.app, ["aoe-register"])
        assert result.exit_code == 2

    def test_s1_5_end_to_end_without_aoe(self, monkeypatch, home, project, current, capfd):
        """The runner, the shipped script and `aoe-register` in a child process, with aoe turned off."""
        monkeypatch.setenv("HARNESSED_NO_AOE", "1")
        assert run(monkeypatch, "host-run", "claude", "--stack", STACK, "--register-aoe-only") == 1
        assert "Agent of Empires" in capfd.readouterr().err
        assert not (project / f"claude-{STACK}-host").exists()

    def test_s1_8_create_aoe_only_is_an_unknown_option(self, monkeypatch, home, project):
        result = CliRunner().invoke(
            launcher.app, ["host-run", "claude", "--stack", STACK, "--create-aoe-only"]
        )
        assert result.exit_code == 2
        result = CliRunner().invoke(
            launcher.app, ["container-run", "claude", "--stack", STACK, "--create-aoe-only"]
        )
        assert result.exit_code == 2


# --- S6. No automatic registration ---------------------------------------------------------------


class _Stop(Exception):
    pass


class TestNoAutomaticRegistration:
    def test_s6_1_a_normal_launch_registers_nothing(self, monkeypatch, home, project, tmp_path):
        (tmp_path / "stack.yaml").write_text(f"name: {STACK}\n")
        calls: list = []
        monkeypatch.setattr(launcher.paths, "find_in_catalog", lambda *a: tmp_path)
        monkeypatch.setattr(launcher, "assemble", lambda *a, **k: None)
        monkeypatch.setattr(launcher.claude_imports, "ask", lambda *a: None)
        monkeypatch.setattr(launcher.aoe, "_bin", lambda: "/usr/bin/aoe")
        monkeypatch.setattr(launcher.aoe, "sync_session", lambda *a, **k: calls.append(a))

        def stop(*_a, **_k):
            raise _Stop

        # The first step after the persist block: reaching it means the block ran in full.
        monkeypatch.setattr(launcher, "_resolve_launch_env", stop)
        with pytest.raises(_Stop):
            run(monkeypatch, "host-run", "claude", "--stack", STACK)
        assert calls == [], "a normal launch mirrored into aoe"
        assert list(project.iterdir()) == [], "a normal launch wrote a local launcher"
        assert not zed_file(home).exists()
        assert not atlas_file(home).exists()
        assert not vscode_file(home).exists()
        # S6.4: the global launchers are still written on every launch.
        assert Path(launcher_path(home, "host-run")).is_file()

    def test_s6_3_no_aoe_integration_in_any_root_is_an_unknown_name(self, monkeypatch, home, project, current, capfd, tmp_path):
        monkeypatch.setattr(paths, "catalog_roots", lambda: [tmp_path / "empty"])
        assert run(monkeypatch, "host-run", "claude", "--stack", STACK, "--register-aoe-only") == 2
        assert "no integration named 'aoe'; available: none" in capfd.readouterr().err


# --- The ACP channel ------------------------------------------------------------------------------


def test_an_acp_register_run_writes_nothing_to_stdout(home, project, tmp_path):
    """Must NOT: under an ACP verb a register run writes nothing to stdout. A real child process, so
    the fd swap is real: the integration's own stdout lands on stderr."""
    stack, recipes = staleness.load_stack_with_recipes(None, "hostmcp")
    prof = paths.profile_dir("hostmcp", "claude")
    prof.mkdir(parents=True)
    (prof / ".mcp.json").write_text("{}")
    staleness.write_stamp(prof, staleness.compute_stamp(None, stack, recipes))
    overlay("zellij", "#!/bin/sh\necho to-stdout\n")
    proc = subprocess.run(
        [sys.executable, "-m", "harnessed", "host-acp", "claude", "--stack", "hostmcp",
         "--register-zellij-only"],
        cwd=project, env=dict(os.environ), capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""
    assert "to-stdout" in proc.stderr


# --- Pinned by mutation testing ------------------------------------------------------------------


def test_environ_sets_no_optional_name_by_default(home, project):
    env = integrations.environ("x", "host-run", "claude", STACK, project)
    assert not OPTIONAL & set(env)


def test_the_integration_runs_in_the_project_given_not_the_cwd(monkeypatch, home, project, current, tmp_path):
    overlay("zellij", DUMP)
    monkeypatch.setenv("DUMP", str(tmp_path / "dump.json"))
    other = tmp_path / "other"
    other.mkdir()
    code = run(monkeypatch, "host-run", "claude", str(other), "--stack", STACK, "--register-zellij-only")
    assert code == 0
    seen = json.loads((tmp_path / "dump.json").read_text())
    assert seen["cwd"] == str(other)
    assert seen["env"]["HARNESSED_PROJECT"] == str(other)


def test_two_flags_name_the_rule():
    with pytest.raises(integrations.IntegrationError) as exc:
        integrations.extract(["host-run", "--register-a-only", "--register-b-only"])
    assert str(exc.value) == "only one --register-<name>-only flag is allowed per command"


def test_s7_5_after_a_build_and_zed_the_acp_launcher_answers_initialize(monkeypatch, tmp_path):
    """S7.5: S7.1 (no profile, so the register run builds) then S2.1 (the Zed entry), then an ACP
    `initialize` to the launcher the entry names gets a `result`.

    The build is the real in-process assembly a host verb runs, with no podman. The
    `initialize` goes through `host-acp` in a child process with test_host_acp's stub agent, which
    is what the launcher's exec line runs.
    """
    from test_host_acp import _STACK as ACP_STACK
    from test_host_acp import _Host, _pin, _rpc, _stdout_messages

    host = _Host(tmp_path, monkeypatch)
    for name in CONTRACT | OPTIONAL:
        monkeypatch.delenv(name, raising=False)
    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.chdir(project)
    assert not paths.is_built(ACP_STACK, "claude")
    builds: list = []
    real = launcher._assemble_host
    monkeypatch.setattr(launcher, "_assemble_host", lambda s, h: (builds.append((s, h)), real(s, h)))

    assert run(monkeypatch, "host-run", "claude", "--stack", ACP_STACK, "--register-zed-only") == 0
    assert builds == [(ACP_STACK, "claude")]
    assert paths.is_built(ACP_STACK, "claude")

    entry = jsonc_value(Path(os.environ["XDG_CONFIG_HOME"]) / "zed" / "settings.json")["agent_servers"][
        f"harnessed claude ({ACP_STACK})"
    ]
    acp_launcher = Path(entry["command"])
    exec_line = [ln for ln in acp_launcher.read_text().splitlines() if ln.startswith("exec ")]
    assert exec_line and exec_line[0].endswith(f'host-acp claude --stack {ACP_STACK} "$@"')

    proc = host.run("claude", path_prefix=host.adapter(_pin()), msgs=[_rpc(1, "initialize", {"protocolVersion": 1})])
    assert proc.returncode == 0, proc.stderr.decode()
    [reply] = _stdout_messages(proc)
    assert reply["id"] == 1 and "result" in reply


def test_s4_6_the_wrapper_vscode_runs_starts_the_stacks_claude(monkeypatch, tmp_path):
    """S4.6, up to the VS Code UI: after `--register-vscode-only`, the wrapper the setting names,
    called the way the extension calls it (`<wrapper> <bundled claude> <SDK args>`, fact 14), starts
    the stack's claude in the cwd with the SDK args and the stack's config dir. The bundled claude
    does not run. A real child process runs the real launcher file; `claude` on PATH is a recorder.
    """
    from test_host_acp import _STACK as ACP_STACK
    from test_host_acp import _Host

    host = _Host(tmp_path, monkeypatch)
    for name in CONTRACT | OPTIONAL:
        monkeypatch.delenv(name, raising=False)
    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.chdir(project)
    assert run(monkeypatch, "host-run", "claude", "--stack", ACP_STACK, "--register-vscode-only") == 0
    settings = Path(os.environ["XDG_CONFIG_HOME"]) / "Code" / "User" / "settings.json"
    wrapper = jsonc_value(settings)["claudeCode.claudeProcessWrapper"]

    bundled = tmp_path / "ext" / "claude"
    bundled.parent.mkdir()
    bundled.write_text(f'#!/bin/sh\ntouch "{tmp_path}/bundled-ran"\n')
    bundled.chmod(0o755)
    fake = tmp_path / "fakebin"
    fake.mkdir()
    record = tmp_path / "claude-run.json"
    (fake / "claude").write_text(
        f"#!{sys.executable}\nimport json, os, sys\n"
        f"json.dump({{'argv': sys.argv[1:], 'cwd': os.getcwd(), "
        f"'config': os.environ.get('CLAUDE_CONFIG_DIR')}}, open({str(record)!r}, 'w'))\n"
        "print('{\"type\": \"claude-out\"}')\n"
    )
    (fake / "claude").chmod(0o755)
    sdk = ["--output-format", "stream-json", "--input-format", "stream-json", "--verbose"]
    env = {**host.env, "PATH": f"{fake}{os.pathsep}{host.env['PATH']}"}
    proc = subprocess.run(
        [wrapper, str(bundled), *sdk], cwd=project, env=env, stdin=subprocess.DEVNULL,
        capture_output=True, timeout=180, check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode()
    seen = json.loads(record.read_text())
    assert seen["argv"][-len(sdk):] == sdk
    assert str(bundled) not in seen["argv"]
    assert seen["cwd"] == str(project)
    assert seen["config"] == str(paths.host_home(ACP_STACK, "claude"))
    assert not (tmp_path / "bundled-ran").exists()
    # The extension reads the wrapper's stdout as stream-json: claude's own line and nothing else.
    assert proc.stdout == b'{"type": "claude-out"}\n', proc.stdout


def test_a_foreign_file_at_the_launcher_name_registers_nothing(monkeypatch, home, project, current, tmp_path, capfd):
    """PR #645 review: every integration, not only aoe, refuses to register a launcher path that
    holds a file harnessed did not write — the entry would run that file."""
    marker = tmp_path / "ran"
    overlay("zellij", f'#!/bin/sh\ntouch "{marker}"\n')
    foreign = Path(launcher_path(home, "host-run"))
    foreign.parent.mkdir(parents=True)
    foreign.write_text("#!/bin/sh\necho mine\n")
    assert run(monkeypatch, "host-run", "claude", "--stack", STACK, "--register-zellij-only") == 1
    assert "not a harnessed launcher" in capfd.readouterr().err
    assert not marker.exists()
    assert foreign.read_text() == "#!/bin/sh\necho mine\n"


def test_a_failed_container_register_removes_the_manifest_it_minted(monkeypatch, home, project, tmp_path):
    """PR #645 review: `container-run --recipe … --register-x-only` that fails leaves no minted
    stack behind, as a failed `host-run` register and a failed launch do not."""
    monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path / "gen")

    def fail(*_a, **_k):
        raise typer.Exit(3)

    monkeypatch.setattr(launcher, "_register_and_exit", fail)
    code = run(monkeypatch, "container-run", "claude", "--recipe", "serena", "--register-zellij-only")
    assert code == 3
    assert not list((tmp_path / "gen" / "stacks").glob("*/stack.yaml"))


@pytest.mark.parametrize("verb", ["host-run", "container-run", "host-acp", "container-acp"])
def test_help_names_the_register_flag_and_every_integration(monkeypatch, home, capsys, verb):
    """`--help` on a global verb names `--register-<name>-only` and the integrations the catalog
    roots hold, overlay included: the flag is split off before typer, so typer cannot list it."""
    overlay("zellij", "#!/bin/sh\n")
    monkeypatch.setenv("COLUMNS", "400")
    assert run(monkeypatch, verb, "--help") == 0
    # CI renders typer's help with ANSI styling (GITHUB_ACTIONS forces it); match the text, not the paint.
    out = " ".join(re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().out).split())
    assert "--register-<name>-only" in out
    assert "aoe, atlas, vscode, zed, zellij" in out


def test_help_on_another_verb_reads_no_integration(monkeypatch, home, capsys):
    def boom(*_a):
        raise AssertionError("listed integrations for a verb that takes no register flag")

    monkeypatch.setattr(launcher.paths, "list_catalog", boom)
    assert run(monkeypatch, "build", "--help") == 0


# --- Build-first by backend, and `requires` checked before any build (PR #645) -------------------


def _no_build(monkeypatch) -> list:
    """Record both build paths; fail the test if either runs."""
    calls: list = []
    monkeypatch.setattr(launcher.integrations, "needs_build", lambda s, h: True)
    monkeypatch.setattr(launcher, "_runtime", lambda: "podman")
    monkeypatch.setattr(launcher, "_build_stack", lambda *a, **k: calls.append(("image", a)))
    monkeypatch.setattr(launcher, "_assemble_host", lambda *a, **k: calls.append(("host", a)))
    return calls


@pytest.mark.parametrize(
    ("verb", "harness", "integration", "message"),
    [
        ("host-run", "omp", "vscode", "the vscode integration supports claude only (got omp)"),
        ("container-run", "claude", "vscode", "the vscode integration supports the host backend only"),
        ("container-run", "codex", "zed", "Zed needs an ACP harness; codex has no ACP mode"),
        ("container-run", "codex", "atlas", "Atlas needs an ACP harness; codex has no ACP mode"),
    ],
)
def test_a_run_the_integration_rules_out_builds_nothing(monkeypatch, home, project, capfd, verb, harness, integration, message):
    calls = _no_build(monkeypatch)
    monkeypatch.setattr(launcher.claude_imports, "ask", lambda *a: None)
    assert run(monkeypatch, verb, harness, "--stack", STACK, f"--register-{integration}-only") == 1
    assert message in " ".join(capfd.readouterr().err.split())
    assert calls == [], "the integration's requirements are checked before any build"
    assert not Path(launcher_path(home, verb, harness)).exists(), "nothing is written"


def test_a_host_verb_assembles_in_process_and_builds_no_image(monkeypatch, home, project, tmp_path):
    calls = _no_build(monkeypatch)
    overlay("zellij", "#!/bin/sh\n")
    assert run(monkeypatch, "host-run", "claude", "--stack", STACK, "--register-zellij-only") == 0
    assert calls == [("host", (STACK, "claude"))]


def test_a_container_verb_builds_the_image(monkeypatch, home, project):
    calls = _no_build(monkeypatch)
    overlay("zellij", "#!/bin/sh\n")
    monkeypatch.setattr(launcher.claude_imports, "ask", lambda *a: None)
    assert run(monkeypatch, "container-run", "claude", "--stack", STACK, "--register-zellij-only") == 0
    assert calls == [("image", ("podman", STACK, "claude"))]


def test_the_host_assembly_is_real_and_needs_no_runtime(monkeypatch, tmp_path):
    """`_assemble_host` is the in-process assembly `host-run` does: no podman, a stamped profile."""
    from test_host_acp import _STACK as ACP_STACK
    from test_host_acp import _Host

    _Host(tmp_path, monkeypatch)

    def no_runtime():
        raise AssertionError("a host register run needs no container runtime")

    monkeypatch.setattr(launcher, "_runtime", no_runtime)
    assert integrations.needs_build(ACP_STACK, "claude")
    launcher._assemble_host(ACP_STACK, "claude")
    assert not integrations.needs_build(ACP_STACK, "claude")


@pytest.mark.parametrize(
    ("text", "code", "message"),
    [
        ("# comment only\n\n", 0, ""),
        ("harness claude omp  # trailing comment\n", 0, ""),
        ("harness omp\n", 1, "supports omp only (got claude)"),
        ("backend container\n", 1, "supports the container backend only"),
        ("frobnicate yes\n", 2, "unknown requirement 'frobnicate'"),
    ],
)
def test_the_requires_file(home, text, code, message):
    script = overlay("zellij", "#!/bin/sh\n")
    (script.parent / "requires").write_text(text)
    if code == 0:
        integrations.check(script, "claude", "host-run")
        return
    with pytest.raises(integrations.IntegrationError) as exc:
        integrations.check(script, "claude", "host-run")
    assert exc.value.code == code
    assert message in str(exc.value)
