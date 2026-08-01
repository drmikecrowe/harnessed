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


def _table(table, name):
    """Look a version up and wrap it as a year-old Release, so the cooldown never interferes."""
    version = table.get(name)
    return [] if version is None else [_old(version)]


def _old(version):
    """A resolver result old enough that the release-age cooldown never interferes."""
    from datetime import datetime, timedelta, timezone
    return update.Release(
        version=version, published=datetime.now(timezone.utc) - timedelta(days=365)
    )


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
        update, "resolve_releases",
        lambda backend, name, **kw: _table({"x": "1.5.0", "y": "9.9.9"}, name),
    )
    return root


class TestCommandIsReachableFromArgv:
    """`harnessed update` must reach the update command, not be reinterpreted on the way.

    It once could not: `main()` prepended `launch` to any leading token outside a hand-maintained
    `_COMMANDS` set, so the real binary parsed `harnessed update --check` as `harnessed launch
    update --check` and died on an unknown option — while every CliRunner test, which invokes `app`
    directly, still passed. That whole mechanism is gone (the stack is named by `--stack` now), so
    this asserts the property rather than the bookkeeping that used to protect it.
    """

    def test_argv_reaches_the_command_unrewritten(self, monkeypatch):
        seen: list = []
        monkeypatch.setattr(launcher, "app", lambda: seen.append(list(launcher.sys.argv)))
        monkeypatch.setattr(launcher.sys, "argv", ["harnessed", "update", "--check"])
        launcher.main()
        assert seen == [["harnessed", "update", "--check"]]


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
        monkeypatch.setattr(update, "resolve_releases", lambda backend, name, **kw: _table({"x": "1.0.0", "y": "9.9.9"}, name))
        result = runner.invoke(launcher.app, ["update", "--check"])
        assert result.exit_code == 0

    def test_a_held_pin_alone_never_fails_check(self, catalog, monkeypatch):
        """`frozen` is 8 majors behind on purpose. CI must stay green."""
        monkeypatch.setattr(update, "resolve_releases", lambda backend, name, **kw: _table({"x": "1.0.0", "y": "9.9.9"}, name))
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
        monkeypatch.setattr(update, "resolve_releases", boom)
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
        monkeypatch.setattr(update, "resolve_releases", lambda backend, name, **kw: _table({"x": "1.0.0", "y": "9.9.9"}, name))
        result = runner.invoke(launcher.app, ["update"])
        assert result.exit_code == 0
        assert "up to date" in _plain(result.output).lower()


class TestCooldownSurface:
    """bd harnessed-7zb — a too-fresh release is shown, not offered, and never fails CI."""

    @pytest.fixture
    def fresh(self, catalog, monkeypatch):
        from datetime import datetime, timedelta, timezone
        monkeypatch.setattr(update, "resolve_releases", lambda backend, name, **kw: (
            [update.Release(
                version={"x": "1.5.0", "y": "9.9.9"}[name],
                published=datetime.now(timezone.utc) - timedelta(days=2),
            )] if name in ("x", "y") else []
        ))
        return catalog

    def test_a_fresh_release_is_not_bumped_even_with_yes(self, fresh):
        runner.invoke(launcher.app, ["update", "--yes"])
        assert "npm:x@1.0.0" in (fresh / "stale" / "recipe.yaml").read_text(), (
            "a release published 2 days ago must not be written, --yes or not"
        )

    def test_a_fresh_release_is_still_listed_with_its_age(self, fresh):
        out = _plain(runner.invoke(launcher.app, ["update", "--check"]).output)
        assert "cooldown" in out.lower()
        assert "1.5.0" in out and "days ago" in out

    def test_a_fresh_release_does_not_fail_check(self, fresh):
        assert runner.invoke(launcher.app, ["update", "--check"]).exit_code == 0

    def test_the_window_can_be_overridden_on_the_command_line(self, fresh):
        """`--cooldown-days 0` opts out — for someone who has read the release themselves."""
        runner.invoke(launcher.app, ["update", "--yes", "--minimum-release-age", "0"])
        assert "npm:x@1.5.0" in (fresh / "stale" / "recipe.yaml").read_text()


class TestPostBumpGuidance:
    """bd harnessed-czo — name the stacks and print the commands, rather than saying 'the affected
    stacks' and leaving the user to work out which those are."""

    @pytest.fixture
    def with_stacks(self, catalog, tmp_path):
        stacks = tmp_path / "catalog" / "stacks"
        (stacks / "alpha").mkdir(parents=True)
        (stacks / "alpha" / "stack.yaml").write_text(
            "name: alpha\nrecipes: [stale]\nharnesses: [claude]\n"
        )
        return catalog

    def test_the_bumped_recipe_and_its_stacks_are_named(self, with_stacks):
        out = _plain(runner.invoke(launcher.app, ["update", "--yes"]).output)
        assert "Bumped: stale" in out
        assert "alpha" in out

    def test_the_literal_verify_commands_are_printed(self, with_stacks):
        out = _plain(runner.invoke(launcher.app, ["update", "--yes"]).output)
        assert "harnessed build alpha claude && harnessed test alpha claude" in out

    def test_a_recipe_in_no_stack_says_so_instead_of_an_empty_list(self, catalog):
        out = _plain(runner.invoke(launcher.app, ["update", "--yes"]).output)
        assert "nothing to rebuild" in out.lower()
