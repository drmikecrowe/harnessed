"""The `harnessed update` command surface (bd harnessed-tfm).

The module (`harnessed.update`) owns classification and rewriting; this covers what the USER sees
and the exit codes CI depends on:

  * a stale pin is listed with recipe / file / current -> latest, which is the acceptance criterion
  * accept rewrites, skip does not
  * `--check` exits non-zero and writes nothing
  * held pins are shown as held, never prompted for
  * unresolved pins are shown — never silently dropped
"""

import re

import pytest
from typer.testing import CliRunner

from harnessed import launcher, update

runner = CliRunner()

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    """A throwaway catalog with one stale pin, one held pin, and one opaque pin."""
    root = tmp_path / "catalog" / "recipes"
    (root / "stale").mkdir(parents=True)
    (root / "stale" / "recipe.yaml").write_text("name: stale\ntools:\n  - npm:x@1.0.0\n")
    (root / "frozen").mkdir(parents=True)
    (root / "frozen" / "recipe.yaml").write_text(
        "name: frozen\ntools:\n  - spec: npm:y@1.0.0\n    hold: 'deliberately frozen'\n"
    )
    (root / "opaque").mkdir(parents=True)
    (root / "opaque" / "recipe.yaml").write_text(
        "name: opaque\ninstall:\n  script: install.sh\n  cache: 'abc1234'\n"
    )
    (root / "opaque" / "install.sh").write_text("true\n")

    monkeypatch.setattr(launcher.paths, "catalog_roots", lambda: [tmp_path / "catalog"])
    monkeypatch.setattr(
        update, "resolve_latest",
        lambda backend, name, **kw: {"x": "1.5.0", "y": "9.9.9"}.get(name),
    )
    return root


class TestCommandIsReachableFromArgv:
    """`harnessed <token>` prepends `launch` unless <token> is a KNOWN subcommand, and that set is
    hand-maintained. A command missing from it is invisible to the real binary while every
    CliRunner test still passes — the CLI parses `harnessed update --check` as
    `harnessed launch update --check` and dies on an unknown option. Found exactly that way."""

    def test_update_is_a_known_subcommand(self):
        assert "update" in launcher._COMMANDS

    def test_every_registered_command_is_in_the_argv_allowlist(self):
        """The general guard, so the NEXT command cannot land with the same hole."""
        registered = {c.name for c in launcher.app.registered_commands if c.name}
        missing = registered - launcher._COMMANDS
        assert not missing, (
            f"commands {sorted(missing)} are registered with typer but absent from _COMMANDS, so "
            "`harnessed <name>` would be parsed as a stack name and routed to launch"
        )


class TestCheckMode:
    def test_check_lists_the_stale_pin_with_recipe_file_and_versions(self, catalog):
        result = runner.invoke(launcher.app, ["update", "--check"])
        out = _plain(result.output)
        assert "stale" in out
        assert "recipe.yaml" in out
        assert "1.0.0" in out and "1.5.0" in out

    def test_check_exits_non_zero_when_a_stale_pin_exists(self, catalog):
        assert runner.invoke(launcher.app, ["update", "--check"]).exit_code != 0

    def test_check_writes_nothing(self, catalog):
        before = (catalog / "stale" / "recipe.yaml").read_bytes()
        runner.invoke(launcher.app, ["update", "--check"])
        assert (catalog / "stale" / "recipe.yaml").read_bytes() == before

    def test_check_exits_zero_when_nothing_is_stale(self, catalog, monkeypatch):
        monkeypatch.setattr(update, "resolve_latest", lambda backend, name, **kw: {
            "x": "1.0.0", "y": "9.9.9",
        }.get(name))
        result = runner.invoke(launcher.app, ["update", "--check"])
        assert result.exit_code == 0

    def test_a_held_pin_alone_never_fails_check(self, catalog, monkeypatch):
        """`frozen` is 8 majors behind on purpose. CI must stay green."""
        monkeypatch.setattr(update, "resolve_latest", lambda backend, name, **kw: {
            "x": "1.0.0", "y": "9.9.9",
        }.get(name))
        result = runner.invoke(launcher.app, ["update", "--check"])
        assert result.exit_code == 0
        assert "frozen" in _plain(result.output), "a held pin is still LISTED, just not fatal"


class TestReporting:
    def test_held_pins_are_shown_with_their_reason(self, catalog):
        out = _plain(runner.invoke(launcher.app, ["update", "--check"]).output)
        assert "deliberately frozen" in out, (
            "the hold reason exists to tell the human WHY — printing the hold without it is useless"
        )

    def test_unresolved_pins_are_reported_not_dropped(self, catalog):
        """The bead's hard requirement. An install.cache the tool cannot resolve must appear."""
        out = _plain(runner.invoke(launcher.app, ["update", "--check"]).output)
        assert "opaque" in out and "abc1234" in out

    def test_a_resolver_failure_surfaces_as_unresolved(self, catalog, monkeypatch):
        def boom(backend, name, **kw):
            raise update.ResolveError("network unreachable")
        monkeypatch.setattr(update, "resolve_latest", boom)
        result = runner.invoke(launcher.app, ["update", "--check"])
        out = _plain(result.output)
        assert "network unreachable" in out
        assert result.exit_code == 0, "an unreachable registry is not a stale pin"


class TestInteractive:
    def test_accepting_rewrites_the_pin(self, catalog):
        result = runner.invoke(launcher.app, ["update"], input="y\n")
        assert result.exit_code == 0
        assert "npm:x@1.5.0" in (catalog / "stale" / "recipe.yaml").read_text()

    def test_skipping_leaves_the_pin_alone(self, catalog):
        before = (catalog / "stale" / "recipe.yaml").read_text()
        runner.invoke(launcher.app, ["update"], input="n\n")
        assert (catalog / "stale" / "recipe.yaml").read_text() == before

    def test_held_pins_are_never_prompted_for(self, catalog):
        """Answering 'y' to everything must still not bump a held pin — the hold is not a default,
        it is a rule."""
        runner.invoke(launcher.app, ["update"], input="y\ny\ny\n")
        assert "npm:y@1.0.0" in (catalog / "frozen" / "recipe.yaml").read_text()

    def test_yes_flag_bumps_without_prompting(self, catalog):
        result = runner.invoke(launcher.app, ["update", "--yes"])
        assert result.exit_code == 0
        assert "npm:x@1.5.0" in (catalog / "stale" / "recipe.yaml").read_text()
        assert "npm:y@1.0.0" in (catalog / "frozen" / "recipe.yaml").read_text()

    def test_nothing_stale_says_so_and_exits_clean(self, catalog, monkeypatch):
        monkeypatch.setattr(update, "resolve_latest", lambda backend, name, **kw: {
            "x": "1.0.0", "y": "9.9.9",
        }.get(name))
        result = runner.invoke(launcher.app, ["update"])
        assert result.exit_code == 0
        assert "up to date" in _plain(result.output).lower()
