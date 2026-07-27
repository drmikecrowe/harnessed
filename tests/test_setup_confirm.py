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
        monkeypatch.setattr(launcher, "harnessed_env", lambda *a, **k: {})

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


class TestBeadsTeamWiring:
    def test_team_gates_its_init_behind_a_confirm(self):
        r = load_recipe(TEAM, strict=True)
        assert r.setup is not None and r.setup.script, "team now automates bd init"
        assert r.setup.confirm, "…and must never do it without asking — it COMMITS to a shared repo"

    def test_the_confirm_names_the_actual_side_effect(self):
        """'Proceed?' with no stated consequence is not informed consent. The one fact a user needs
        is that this commits files into a repo their teammates share."""
        confirm = load_recipe(TEAM, strict=True).setup.confirm.lower()
        assert "commit" in confirm
        assert "repository" in confirm or "repo" in confirm

    def test_the_script_never_reaches_bds_shared_server(self):
        """The 2026-07-19 incident (BEADS.md §10) in one line: no --external, auto-start live,
        pointed at the global ~/.beads/shared-server."""
        body = (TEAM / "setup.sh").read_text()
        assert "--shared-server" not in body
        assert "--external" in body

    def test_the_script_self_gates(self):
        """A `setup.script` runs on every launch by contract, confirm or not."""
        assert 'metadata.json' in (TEAM / "setup.sh").read_text()
