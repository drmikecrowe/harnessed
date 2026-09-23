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

from typer.testing import CliRunner

from harnessed import dynstack, launcher, paths

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
    (stack_dir / "stack.yaml").write_text(
        f"name: {name}\nrecipes: []\nservices: []\n", encoding="utf-8"
    )
    return stack_dir


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
        assert (second_name, second_dir) == (first_name, first_dir), (
            "precondition: mint is idempotent"
        )
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
        _overlay_stack(
            tmp_path, "contrast-test.foo", "name: contrast-test.foo\nrecipes: []\nservices: []\n"
        )
        assert dynstack.is_adhoc("contrast-test.foo") is False

    def test_a_name_beginning_with_test_but_not_the_component_is_not_adhoc(
        self, tmp_path, monkeypatch
    ):
        """`testing` starts with `test` as a STRING and is not a test stack. The dot is what makes
        it a component boundary; without this the rule would eat every name starting with those
        four letters."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        _overlay_stack(tmp_path, "testing", "name: testing\nrecipes: []\nservices: []\n")
        assert dynstack.is_adhoc("testing") is False


class TestThePersistGate:
    """`_persist_this_launch` answers once for BOTH surfaces — script and row, together."""

    def _gate(self, monkeypatch, *, adhoc: bool, **kwargs) -> bool:
        monkeypatch.setattr(launcher.dynstack, "is_adhoc", lambda _s: adhoc)
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
        assert paths.is_built("test.hostspike", "claude"), (
            "the profile assembled and the agent exec'd"
        )

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

        result = runner.invoke(
            launcher.app, ["host-run", "claude", str(project), "--stack", "hostspike"]
        )
        assert result.exit_code == 0, result.output
        assert [p.name for p in project.iterdir()] == ["claude-hostspike-host"]
        assert len(rows) == 1
