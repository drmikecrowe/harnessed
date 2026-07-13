"""Host-side, user-facing recipe `setup:` notices (launcher._collect/_prompt_setup_notices).

Setup notices are shown host-side at attach time and never baked into an agent identity file.
Conditional notices follow their `setup.condition` (exit 0 = still needed = show) every launch;
unconditional ones show once per project until the user dismisses them (paths.setup_dismissed_flag).
"""

import pytest
import typer

from harnessed import launcher, paths
from harnessed.schema import Recipe, SetupSpec


def _r(name, *, condition=None):
    return Recipe(
        name=name,
        setup=SetupSpec(summary=f"do {name}", reference="https://example/x", condition=condition),
    )


class _Stdin:
    def __init__(self, tty):
        self._tty = tty

    def isatty(self):
        return self._tty


@pytest.fixture
def state(monkeypatch, tmp_path):
    """Isolate the dismiss-flag store under a tmp XDG_STATE_HOME."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    return tmp_path


def _dismiss(stack, proj):
    flag = paths.setup_dismissed_flag(stack, "claude", proj)
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("", encoding="utf-8")


class TestCollectSetupNotices:
    def test_unconditional_shown_then_gated_by_flag(self, state):
        recipes = [_r("caveman")]
        assert [r.name for r in launcher._collect_setup_notices(recipes, state, "s", "claude")] == ["caveman"]
        _dismiss("s", state)
        assert launcher._collect_setup_notices(recipes, state, "s", "claude") == []

    def test_conditional_polarity(self, state):
        # exit 0 = manual step STILL needed = show; non-zero = satisfied = suppress.
        show = launcher._collect_setup_notices([_r("needs", condition="true")], state, "s", "claude")
        hide = launcher._collect_setup_notices([_r("done", condition="false")], state, "s", "claude")
        assert [r.name for r in show] == ["needs"]
        assert hide == []

    def test_flag_does_not_gate_conditional(self, state):
        _dismiss("s", state)
        recipes = [_r("cond", condition="true"), _r("uncond")]
        # dismiss silences only the unconditional notice; the conditional still shows.
        assert [r.name for r in launcher._collect_setup_notices(recipes, state, "s", "claude")] == ["cond"]

    def test_no_setup_skipped_order_preserved(self, state):
        recipes = [Recipe(name="plain"), _r("b"), _r("a")]
        assert [r.name for r in launcher._collect_setup_notices(recipes, state, "s", "claude")] == ["b", "a"]

    def test_flag_is_per_stack_and_project(self, state, tmp_path):
        _dismiss("s1", state)
        # a different stack (same project) is not dismissed
        assert [r.name for r in launcher._collect_setup_notices([_r("x")], state, "s2", "claude")] == ["x"]
        # a different project (same stack) is not dismissed
        other = tmp_path / "other"
        other.mkdir()
        assert [r.name for r in launcher._collect_setup_notices([_r("x")], other, "s1", "claude")] == ["x"]


class TestPromptSetupNotices:
    def _prompt(self, monkeypatch, answer, *, tty=True):
        monkeypatch.setattr(launcher.sys, "stdin", _Stdin(tty))
        calls = []

        def fake_prompt(*args, **kwargs):
            calls.append(kwargs.get("default"))
            return answer

        monkeypatch.setattr(launcher.typer, "prompt", fake_prompt)
        return calls

    def test_noop_when_no_notices(self, state, monkeypatch):
        calls = self._prompt(monkeypatch, "O")
        launcher._prompt_setup_notices([Recipe(name="plain")], state, "s", "claude")
        assert calls == []  # never prompted

    def test_noop_when_not_tty(self, state, monkeypatch):
        calls = self._prompt(monkeypatch, "O", tty=False)
        launcher._prompt_setup_notices([_r("caveman")], state, "s", "claude")
        assert calls == []
        assert not paths.setup_dismissed_flag("s", "claude", state).exists()

    def test_ok_default_proceeds_without_flag(self, state, monkeypatch):
        self._prompt(monkeypatch, "O")
        launcher._prompt_setup_notices([_r("caveman")], state, "s", "claude")
        assert not paths.setup_dismissed_flag("s", "claude", state).exists()

    def test_dismiss_writes_flag(self, state, monkeypatch):
        self._prompt(monkeypatch, "d")  # case-insensitive
        launcher._prompt_setup_notices([_r("caveman")], state, "s", "claude")
        assert paths.setup_dismissed_flag("s", "claude", state).exists()

    def test_terminal_requests_shell(self, state, monkeypatch):
        self._prompt(monkeypatch, "t")
        assert launcher._prompt_setup_notices([_r("caveman")], state, "s", "claude") is True
        assert not paths.setup_dismissed_flag("s", "claude", state).exists()

    def test_non_terminal_choices_do_not_request_shell(self, state, monkeypatch):
        for answer in ("O", "d"):
            self._prompt(monkeypatch, answer)
            assert launcher._prompt_setup_notices([_r("caveman")], state, "s", "claude") is False

    def test_quit_aborts_exit_zero(self, state, monkeypatch):
        self._prompt(monkeypatch, "Q")
        with pytest.raises(typer.Exit) as exc:
            launcher._prompt_setup_notices([_r("caveman")], state, "s", "claude")
        assert exc.value.exit_code == 0
        assert not paths.setup_dismissed_flag("s", "claude", state).exists()
