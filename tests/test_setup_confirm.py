"""`setup.confirm` — executable setup that changes the USER'S repo asks first.

Executable setup normally runs unattended on every launch whose `condition` is unsatisfied. That is
right for a tool writing to its own dirs and wrong for `bd init`, which in team placement creates
and COMMITS 18 files into a shared checkout. Keeping it manual was the old answer; it left users
stopped at a notice telling them to type a command (observed 2026-07-26). `confirm` automates the
step without deciding it for them.

The invariants worth pinning are the ones a future edit would quietly break: no TTY means no run,
declining is not remembered as a dismissal, and the prompt does not fire when there is nothing to do.
"""

from __future__ import annotations

import pytest

from harnessed import launcher
from harnessed.schema import PersistSpec, Recipe, SchemaError, SetupSpec, load_recipe
from harnessed.paths import harnessed_home
from support import patch_all

TEAM = harnessed_home() / "catalog" / "recipes" / "beads" / "team"


def _recipe(*, confirm: str | None, condition: str | None = None) -> Recipe:
    return Recipe(
        name="beads-team",
        setup=SetupSpec(
            summary="s", reference="https://example.invalid",
            script="setup.sh", condition=condition, confirm=confirm,
        ),
        persist=PersistSpec(),
    )


class TestSchema:
    def test_confirm_parses(self, tmp_path):
        d = tmp_path / "r"
        d.mkdir()
        (d / "recipe.yaml").write_text(
            "name: r\nsetup:\n  summary: s\n  reference: https://x.invalid\n"
            "  script: setup.sh\n  confirm: this will commit files\n"
        )
        (d / "setup.sh").write_text("#!/usr/bin/env bash\n")
        assert load_recipe(d).setup.confirm == "this will commit files"

    def test_confirm_without_anything_to_gate_is_rejected(self, tmp_path):
        """A confirm with no `run`/`script` promises a gate that guards nothing."""
        d = tmp_path / "r"
        d.mkdir()
        (d / "recipe.yaml").write_text(
            "name: r\nsetup:\n  summary: s\n  reference: https://x.invalid\n  confirm: hi\n"
        )
        with pytest.raises(SchemaError, match="means nothing without"):
            load_recipe(d)


class TestGate:
    """`launcher._confirm_setup` — the one decision point both modes route through."""

    def test_no_confirm_declared_runs_unchanged(self, tmp_path, monkeypatch):
        monkeypatch.setattr(launcher.sys.stdin, "isatty", lambda: False)
        r = Recipe(name="plain", setup=None, persist=PersistSpec())
        assert launcher._confirm_setup(r, "s", tmp_path, harness="claude") is True

    def test_no_tty_skips_rather_than_assuming_yes(self, tmp_path, monkeypatch, capsys):
        """CI, the capability test and any scripted launch land here. Nobody objected is not
        consent for a commit into someone's repo."""
        monkeypatch.setattr(launcher.sys.stdin, "isatty", lambda: False)
        assert launcher._confirm_setup(
            _recipe(confirm="commits files"), "s", tmp_path, harness="claude"
        ) is False
        assert "needs confirmation" in capsys.readouterr().err

    def test_yes_runs_it(self, tmp_path, monkeypatch):
        monkeypatch.setattr(launcher.sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(launcher.typer, "confirm", lambda *a, **k: True)
        assert launcher._confirm_setup(
            _recipe(confirm="commits files"), "s", tmp_path, harness="claude"
        ) is True

    def test_no_skips_it(self, tmp_path, monkeypatch):
        monkeypatch.setattr(launcher.sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(launcher.typer, "confirm", lambda *a, **k: False)
        assert launcher._confirm_setup(
            _recipe(confirm="commits files"), "s", tmp_path, harness="claude"
        ) is False

    def test_the_warning_text_is_shown_verbatim(self, tmp_path, monkeypatch, capsys):
        """Author prose goes through escape(): rich silently DROPS any `[word]` as a style tag, and
        this text is the entire basis on which the user is consenting."""
        monkeypatch.setattr(launcher.sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(launcher.typer, "confirm", lambda *a, **k: False)
        launcher._confirm_setup(
            _recipe(confirm="creates .claude/settings.json and [18 files]"),
            "s", tmp_path, harness="claude",
        )
        assert "[18 files]" in capsys.readouterr().out

    @pytest.fixture
    def _no_stack_lookup(self, monkeypatch):
        """`condition` runs with the folder-env contract, which resolves the stack's services. The
        gate's behaviour is what is under test, not catalog resolution."""
        patch_all(monkeypatch, "harnessed_env", lambda *a, **k: {})

    def test_a_satisfied_condition_asks_nothing(self, tmp_path, monkeypatch, _no_stack_lookup):
        """`setup.script` runs every launch by contract, so without this the user would authorize a
        repo-changing step on EVERY launch — including the ones where it is already done."""
        monkeypatch.setattr(launcher.sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(launcher.typer, "confirm", lambda *a, **k: pytest.fail("prompted"))
        assert launcher._confirm_setup(
            _recipe(confirm="commits files", condition="false"),  # false == already done
            "s", tmp_path, harness="claude",
        ) is False

    def test_an_unsatisfied_condition_does_ask(self, tmp_path, monkeypatch, _no_stack_lookup):
        monkeypatch.setattr(launcher.sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(launcher.typer, "confirm", lambda *a, **k: True)
        assert launcher._confirm_setup(
            _recipe(confirm="commits files", condition="true"),  # true == still needed
            "s", tmp_path, harness="claude",
        ) is True


