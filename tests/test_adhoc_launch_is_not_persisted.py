"""An ad-hoc launch leaves nothing behind: no launcher script, no aoe row.

Two kinds of stack are ad-hoc. A MINTED one (`--recipe`/`--service` composition) is recognised by
its location under the generated catalog root, which is the rule `dynstack.mint` writes into every
manifest it produces. A TEST one is recognised by name, `test` or `test.*`, because a test stack is
authored like any other and has no location to read.

Both are one-offs. Persisting a `<harness>-<stack>-<verb>` script into the user's repo for one
leaves a file naming a stack they were trying out, and a dashboard row for one is the same noise
`aoe._SKIP_STACKS` already suppresses for the `default` baseline.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from harnessed import console, dynstack, launcher, paths
from support import patch_all

runner = CliRunner()


def _overlay_stack(tmp_path: Path, name: str, body: str) -> Path:
    """Author `name` in the user overlay and return its directory."""
    stack_dir = tmp_path / "config" / "harnessed" / "catalog" / "stacks" / name
    stack_dir.mkdir(parents=True)
    (stack_dir / "stack.yaml").write_text(body, encoding="utf-8")
    return stack_dir


def _generated_stack(tmp_path: Path, name: str) -> Path:
    """Put a manifest where `mint` would put it, without running a launch."""
    stack_dir = tmp_path / "data" / "harnessed" / "generated" / "stacks" / name
    stack_dir.mkdir(parents=True)
    (stack_dir / "stack.yaml").write_text(f"name: {name}\nrecipes: []\nservices: []\n", encoding="utf-8")
    return stack_dir


def _names(text: str, output: str) -> bool:
    """Whether `output` names `text`, read past rich's hard wrap.

    rich wraps console output to the terminal width and breaks a long path mid-word, so where a
    name lands depends on the temp path's length (CI failed on `.../bin/h\narnessed-...`). Names and
    paths hold no whitespace, so dropping every whitespace character recovers them whole.
    """
    return "".join(text.split()) in "".join(output.split())


class TestIsAdhocReadsTheLocation:
    """A minted stack is known by WHERE it resolves, never by who minted it."""

    def test_a_stack_under_the_generated_root_is_adhoc(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        _generated_stack(tmp_path, "default.serena-55bfd6ac")
        assert dynstack.is_adhoc("default.serena-55bfd6ac") is True

    def test_an_authored_stack_is_not_adhoc(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        _overlay_stack(tmp_path, "mine", "name: mine\nrecipes: []\nservices: []\n")
        assert dynstack.is_adhoc("mine") is False

    def test_an_authored_stack_shadowing_a_generated_name_is_not_adhoc(self, tmp_path, monkeypatch):
        """Resolution decides which manifest is meant, and the authored one wins. Answering "ad-hoc"
        here would suppress the script and row for a stack the user authored and launches by name."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        _generated_stack(tmp_path, "collides")
        _overlay_stack(tmp_path, "collides", "name: collides\nrecipes: []\nservices: []\n")
        assert paths.find_in_catalog("stacks", "collides") == (
            tmp_path / "config" / "harnessed" / "catalog" / "stacks" / "collides"
        ), "precondition: the overlay must win resolution"
        assert dynstack.is_adhoc("collides") is False

    def test_a_name_that_resolves_nowhere_is_not_adhoc(self, tmp_path, monkeypatch):
        """`find_in_catalog` falls back to the HIGHEST-precedence root, which is never the generated
        one. Nothing launches under such a name anyway; this pins that the fallback cannot read as
        ad-hoc by accident."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        assert dynstack.is_adhoc("nothing-authored-this") is False

    def test_the_second_launch_of_one_recipe_set_is_still_adhoc(self, tmp_path, monkeypatch):
        """The regression this location rule exists for. `mint` is idempotent, so the caller's
        `minted_dir` is None on every launch after the first — reading THAT would persist a script
        and a row for a dynamic stack, just one launch late."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        first_name, first_dir = dynstack.mint(["greet"], "default")
        second_name, second_dir = dynstack.mint(["greet"], "default")
        assert (second_name, second_dir) == (first_name, first_dir), "precondition: mint is idempotent"
        assert dynstack.is_adhoc(second_name) is True


class TestIsAdhocReadsTheName:
    """A test stack is authored, so only its name can say what it is."""

    def test_the_bare_name_test_is_adhoc(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        _overlay_stack(tmp_path, "test", "name: test\nrecipes: []\nservices: []\n")
        assert dynstack.is_adhoc("test") is True

    def test_a_dotted_test_name_is_adhoc(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        _overlay_stack(tmp_path, "test.serena", "name: test.serena\nrecipes: []\nservices: []\n")
        assert dynstack.is_adhoc("test.serena") is True

    def test_a_deeper_test_name_is_adhoc(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        assert dynstack.is_adhoc("test.serena.two") is True

    def test_a_name_merely_containing_test_is_not_adhoc(self, tmp_path, monkeypatch):
        """`-test.` is not a prefix. A stack called `contrast-test.foo` is somebody's real stack."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        _overlay_stack(tmp_path, "contrast-test.foo", "name: contrast-test.foo\nrecipes: []\nservices: []\n")
        assert dynstack.is_adhoc("contrast-test.foo") is False

    def test_a_name_beginning_with_test_but_not_the_component_is_not_adhoc(self, tmp_path, monkeypatch):
        """`testing` starts with `test` as a STRING and is not a test stack. The dot is what makes
        it a component boundary; without this the rule would eat every name starting with those
        four letters."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        _overlay_stack(tmp_path, "testing", "name: testing\nrecipes: []\nservices: []\n")
        assert dynstack.is_adhoc("testing") is False


class TestThePersistGate:
    """`_persist_this_launch` answers once for BOTH surfaces — script and row, together."""

    def _gate(self, monkeypatch, *, adhoc: bool, aoe_bin: str | None = "/usr/bin/aoe", **kwargs) -> bool:
        monkeypatch.setattr(launcher.dynstack, "is_adhoc", lambda _s: adhoc)
        # GH-565 Decide 3: persistence needs a usable aoe. Usable unless a test says otherwise.
        monkeypatch.setattr(launcher.aoe, "_bin", lambda: aoe_bin)
        kwargs.setdefault("group", None)
        kwargs.setdefault("title", None)
        kwargs.setdefault("only", False)
        return launcher._persist_this_launch("whatever", **kwargs)

    def test_an_ordinary_stack_persists(self, monkeypatch):
        assert self._gate(monkeypatch, adhoc=False) is True

    def test_an_adhoc_stack_does_not(self, monkeypatch):
        assert self._gate(monkeypatch, adhoc=True) is False

    def test_an_aoe_group_overrules_the_skip(self, monkeypatch):
        """Same hatch `_SKIP_STACKS` grants for `default`: naming a row is asking for one."""
        assert self._gate(monkeypatch, adhoc=True, group="scratch") is True

    def test_an_aoe_title_overrules_the_skip(self, monkeypatch):
        assert self._gate(monkeypatch, adhoc=True, title="scratch") is True

    def test_create_aoe_only_overrules_the_skip(self, monkeypatch):
        """Registering IS the command the user typed, so it cannot be the thing that is skipped."""
        assert self._gate(monkeypatch, adhoc=True, only=True) is True

    def test_s2_3_without_a_usable_aoe_nothing_persists(self, monkeypatch):
        """GH-565 Decide 3: no aoe row can be registered, so no local launcher is written."""
        assert self._gate(monkeypatch, adhoc=False, aoe_bin=None) is False

    def test_an_aoe_title_without_a_usable_aoe_persists_nothing(self, monkeypatch):
        assert self._gate(monkeypatch, adhoc=False, aoe_bin=None, title="t") is False

    def test_create_aoe_only_without_aoe_still_reaches_the_register_error(self, monkeypatch):
        """`--create-aoe-only` must reach `_aoe_register`, which reports that aoe is missing and
        exits nonzero. Skipping it would turn the command into a plain launch."""
        assert self._gate(monkeypatch, adhoc=False, aoe_bin=None, only=True) is True


class TestHostRunLeavesNothingBehind:
    """The gate at the real call site, driven through the CLI.

    `test.hostspike` is authored in the overlay as a copy of `hostspike`, the content-only tracer
    stack: it assembles in-process with no podman and no MCP surface, so a real `host-run` reaches
    the launcher-script/aoe block and stops at a stubbed `execvpe`.
    """

    BODY = (
        "name: test.hostspike\n"
        "instructions: >-\n"
        "  You are the hostspike tracer agent.\n"
        "recipes: [greet]\n"
        "services: []\n"
    )

    def _launch(self, tmp_path, monkeypatch, *extra: str):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-host-src"))
        _overlay_stack(tmp_path, "test.hostspike", self.BODY)
        project = tmp_path / "project"
        project.mkdir()

        rows: list = []
        monkeypatch.setattr(
            launcher.aoe, "sync_session", lambda *a, **k: rows.append((a, k)) or True
        )
        monkeypatch.setattr(launcher.aoe, "_bin", lambda: "/usr/bin/aoe")  # GH-565 Decide 3
        monkeypatch.setattr(
            launcher.os, "execvpe", lambda *_a: (_ for _ in ()).throw(SystemExit(0))
        )
        monkeypatch.setattr(launcher.os, "chdir", lambda *_a: None)

        result = runner.invoke(
            launcher.app,
            ["host-run", "claude", str(project), "--stack", "test.hostspike", *extra],
        )
        return result, project, rows

    def test_no_launcher_script_is_written(self, tmp_path, monkeypatch):
        result, project, _rows = self._launch(tmp_path, monkeypatch)
        assert result.exit_code == 0, result.output
        assert list(project.iterdir()) == [], "an ad-hoc launch may not drop a file in the repo"

    def test_no_aoe_row_is_registered(self, tmp_path, monkeypatch):
        result, _project, rows = self._launch(tmp_path, monkeypatch)
        assert result.exit_code == 0, result.output
        assert rows == []

    def test_the_launch_itself_still_happens(self, tmp_path, monkeypatch):
        """The point is that nothing PERSISTS, not that nothing runs. Without this, deleting the
        whole block below the gate would pass both tests above."""
        result, _project, _rows = self._launch(tmp_path, monkeypatch)
        assert result.exit_code == 0, result.output
        assert paths.is_built("test.hostspike", "claude"), "the profile assembled and the agent exec'd"

    def test_an_aoe_title_brings_both_back(self, tmp_path, monkeypatch):
        """The hatch, at the call site: the row is asked for by name, so the script it points at
        must be written too — a row whose command names a missing file is dead on arrival."""
        result, project, rows = self._launch(tmp_path, monkeypatch, "--aoe-title", "scratch")
        assert result.exit_code == 0, result.output
        assert [p.name for p in project.iterdir()] == ["claude-test.hostspike-host"]
        assert len(rows) == 1

    def test_an_ordinary_stack_still_persists(self, tmp_path, monkeypatch):
        """The control. Same path, same stubs, a name that is not ad-hoc."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-host-src"))
        project = tmp_path / "project"
        project.mkdir()
        rows: list = []
        monkeypatch.setattr(
            launcher.aoe, "sync_session", lambda *a, **k: rows.append((a, k)) or True
        )
        monkeypatch.setattr(
            launcher.os, "execvpe", lambda *_a: (_ for _ in ()).throw(SystemExit(0))
        )
        monkeypatch.setattr(launcher.os, "chdir", lambda *_a: None)
        monkeypatch.setattr(launcher.aoe, "_bin", lambda: "/usr/bin/aoe")  # GH-565: aoe is usable

        result = runner.invoke(
            launcher.app, ["host-run", "claude", str(project), "--stack", "hostspike"]
        )
        assert result.exit_code == 0, result.output
        assert [p.name for p in project.iterdir()] == ["claude-hostspike-host"]
        assert len(rows) == 1


_HOSTSPIKE_LAUNCHERS = [
    "harnessed-claude-hostspike-acp", "harnessed-claude-hostspike-container",
    "harnessed-claude-hostspike-host",
]


class TestGlobalLaunchersAtLaunch:
    """GH-565 — every launch writes the global launchers; the local one needs a usable aoe."""

    @pytest.fixture(autouse=True)
    def _reset_modes(self, monkeypatch):
        """`container-acp` sets process-wide ACP and exec modes, and these launches stop before
        anything resets them. Same reset `test_acp_verb.py` uses."""
        monkeypatch.setattr(console, "_EXEC_MODE", False)
        yield
        console.set_acp_mode(False)

    def _host_run(self, tmp_path, monkeypatch, stack: str, *, aoe_bin, home=None):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-host-src"))
        home = home or tmp_path / "home"
        home.mkdir(exist_ok=True)
        monkeypatch.setattr(Path, "home", lambda: home)
        project = tmp_path / "project"
        project.mkdir()
        rows: list = []
        seen_at_exec: list = []
        monkeypatch.setattr(
            launcher.aoe, "sync_session", lambda *a, **k: rows.append((a, k)) or True
        )
        monkeypatch.setattr(launcher.aoe, "_bin", lambda: aoe_bin)

        def _exec(*_a):
            bin_dir = home / ".local" / "bin"
            seen_at_exec.append(sorted(p.name for p in bin_dir.iterdir()) if bin_dir.is_dir() else [])
            raise SystemExit(0)

        monkeypatch.setattr(launcher.os, "execvpe", _exec)
        monkeypatch.setattr(launcher.os, "chdir", lambda *_a: None)
        result = runner.invoke(
            launcher.app, ["host-run", "claude", str(project), "--stack", stack]
        )
        return result, home / ".local" / "bin", project, rows, seen_at_exec

    def test_s1_5_host_run_writes_them_before_the_harness_starts(self, tmp_path, monkeypatch):
        result, bin_dir, _p, _rows, seen = self._host_run(
            tmp_path, monkeypatch, "hostspike", aoe_bin="/usr/bin/aoe"
        )
        assert result.exit_code == 0, result.output
        assert seen == [_HOSTSPIKE_LAUNCHERS]
        assert str(tmp_path / "project") not in (bin_dir / _HOSTSPIKE_LAUNCHERS[1]).read_text()

    def test_s1_9_an_adhoc_stack_gets_none(self, tmp_path, monkeypatch):
        _overlay_stack(tmp_path, "test.hostspike", TestHostRunLeavesNothingBehind.BODY)
        result, bin_dir, _p, _rows, _seen = self._host_run(
            tmp_path, monkeypatch, "test.hostspike", aoe_bin="/usr/bin/aoe"
        )
        assert result.exit_code == 0, result.output
        assert not bin_dir.exists() or list(bin_dir.iterdir()) == []

    def test_s1_11_an_unwritable_bin_dir_warns_and_launches(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        (home / ".local").mkdir(parents=True)
        (home / ".local" / "bin").write_text("a file, not a directory", encoding="utf-8")
        result, _bin_dir, _p, _rows, seen = self._host_run(
            tmp_path, monkeypatch, "hostspike", aoe_bin="/usr/bin/aoe", home=home
        )
        assert result.exit_code == 0, result.output
        assert _names("harnessed-claude-hostspike-host", result.output)
        assert seen == [[]], "the launch reached the harness exec"

    def test_s2_3_no_usable_aoe_leaves_nothing_in_the_project(self, tmp_path, monkeypatch):
        result, bin_dir, project, rows, _seen = self._host_run(
            tmp_path, monkeypatch, "hostspike", aoe_bin=None
        )
        assert result.exit_code == 0, result.output
        assert list(project.iterdir()) == []
        assert rows == []
        assert sorted(p.name for p in bin_dir.iterdir()) == _HOSTSPIKE_LAUNCHERS, "global launchers still land"

    # --- container-run, stopped right after the launcher/aoe block -------------------------------

    def _container(self, tmp_path, monkeypatch, verb: str, *argv: str, aoe_bin="/usr/bin/aoe"):
        home = tmp_path / "home"
        home.mkdir(exist_ok=True)
        monkeypatch.setattr(Path, "home", lambda: home)
        rows: list = []
        monkeypatch.setattr(
            launcher.aoe, "sync_session", lambda *a, **k: rows.append((a, k)) or True
        )
        monkeypatch.setattr(launcher.aoe, "_bin", lambda: aoe_bin)
        catalog = tmp_path / "s"
        catalog.mkdir(exist_ok=True)
        (catalog / "stack.yaml").write_text("name: s\n")
        monkeypatch.setattr(launcher.paths, "find_in_catalog", lambda *a: catalog)
        patch_all(monkeypatch, "_runtime", lambda: "podman")
        monkeypatch.setattr(launcher, "is_built", lambda *a: True)
        monkeypatch.setattr(launcher.staleness, "check_profile_fresh", lambda *a: None)

        def _no_build(*_a, **_k):
            raise AssertionError("an up-to-date stack must not be rebuilt")

        monkeypatch.setattr(launcher, "_build_stack", _no_build)
        monkeypatch.setattr(
            launcher, "_derived_image", lambda *a: (_ for _ in ()).throw(SystemExit(0))
        )
        project = tmp_path / "proj"
        project.mkdir(exist_ok=True)
        result = runner.invoke(launcher.app, [verb, "claude", str(project), "--stack", "s", *argv])
        return result, home / ".local" / "bin", project, rows

    def test_s1_6_container_run_writes_them_without_a_build(self, tmp_path, monkeypatch):
        result, bin_dir, _project, _rows = self._container(tmp_path, monkeypatch, "container-run")
        assert result.exit_code == 0, result.output
        assert sorted(p.name for p in bin_dir.iterdir()) == [
            "harnessed-claude-s-acp", "harnessed-claude-s-container", "harnessed-claude-s-host",
        ]

    def test_s1_8_a_foreign_launcher_is_kept_and_named(self, tmp_path, monkeypatch):
        bin_dir = tmp_path / "home" / ".local" / "bin"
        bin_dir.mkdir(parents=True)
        foreign = bin_dir / "harnessed-claude-s-container"
        foreign.write_bytes(b"#!/bin/sh\necho mine\n")
        result, _b, _project, _rows = self._container(tmp_path, monkeypatch, "container-run")
        assert result.exit_code == 0, result.output
        assert foreign.read_bytes() == b"#!/bin/sh\necho mine\n"
        assert _names("harnessed-claude-s-container", result.output)
        assert (bin_dir / "harnessed-claude-s-host").is_file(), "the launch went on"

    def test_s3_1_the_local_launcher_execs_the_global_one(self, tmp_path, monkeypatch):
        result, _b, project, rows = self._container(
            tmp_path, monkeypatch, "container-run", "--no-strict-mcp-config"
        )
        assert result.exit_code == 0, result.output
        local = project / "claude-s-container"
        lines = local.read_text(encoding="utf-8").split("\n")
        assert [ln for ln in lines if ln.startswith("exec ")] == [
            'exec harnessed-claude-s-container --no-strict-mcp-config "$@"'
        ]
        assert len(rows) == 1

    def test_s3_3_container_acp_writes_no_local_launcher(self, tmp_path, monkeypatch):
        result, bin_dir, project, rows = self._container(tmp_path, monkeypatch, "container-acp")
        assert result.exit_code == 0, result.output
        assert list(project.iterdir()) == []
        assert rows == []
        assert (bin_dir / "harnessed-claude-s-acp").is_file(), "the global launchers still land"
