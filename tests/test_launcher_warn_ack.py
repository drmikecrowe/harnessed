"""Warning acknowledgement before the exec handoff (bd harnessed-92o).

`harnessed launch` prints its feedback and then `os.execvp`s, handing the terminal to the agent.
Claude Code's fullscreen renderer draws on the ALTERNATE screen buffer, so everything harnessed
printed is hidden for the whole session — a warning nobody reads is a warning that did not happen.

`_acknowledge_warnings` holds the terminal until the user acknowledges, but ONLY when a warning
was actually emitted: gating every launch on a keypress would be worse than the problem.
"""

import pytest
import typer

from harnessed import launcher


@pytest.fixture(autouse=True)
def reset_counters():
    """The counters live on module-level Consoles, so they leak between tests."""
    launcher._out.warnings = 0
    launcher._err.warnings = 0
    yield
    launcher._out.warnings = 0
    launcher._err.warnings = 0


@pytest.fixture
def tty(monkeypatch):
    monkeypatch.setattr(launcher.sys.stdin, "isatty", lambda: True)


@pytest.fixture
def prompted(monkeypatch):
    """Record whether typer.prompt was reached, without blocking on stdin."""
    calls = []
    monkeypatch.setattr(launcher.typer, "prompt", lambda *a, **k: calls.append(a) or "")
    return calls


class TestWarningsAreCounted:
    """All three markers in use across the codebase must be recognised."""

    @pytest.mark.parametrize(
        "message",
        [
            "[yellow][WARNING][/yellow] harnessed-base not found. Building base first…",
            "[yellow]warning:[/yellow] could not clone docs wiki",
            "[bold yellow]WARNING[/bold yellow] install (foo): container-only step",
        ],
    )
    def test_each_marker_style_increments(self, message, capsys):
        launcher._err.print(message)
        capsys.readouterr()
        assert launcher._err.warnings == 1

    def test_ordinary_output_does_not_increment(self, capsys):
        launcher._out.print("[blue][INFO][/blue] Creating isolated pod: foo")
        launcher._out.print("[green][SUCCESS][/green] running")
        capsys.readouterr()
        assert launcher._out.warnings == 0

    def test_the_message_itself_is_unchanged(self, capsys):
        """Counting must not alter a single byte of existing output."""
        launcher._out.print("[yellow]warning:[/yellow] service 'x' is running on a stale build")
        assert "warning: service 'x' is running on a stale build" in capsys.readouterr().out


class TestAcknowledgementGating:
    def test_no_warning_never_pauses(self, tty, prompted, capsys):
        launcher._acknowledge_warnings()
        capsys.readouterr()
        assert prompted == []

    def test_a_warning_pauses(self, tty, prompted, capsys):
        launcher._err.warnings = 1
        launcher._acknowledge_warnings()
        capsys.readouterr()
        assert len(prompted) == 1

    def test_non_tty_never_pauses_even_with_warnings(self, monkeypatch, prompted, capsys):
        """Headless / CI / capability-test launches must never block."""
        monkeypatch.setattr(launcher.sys.stdin, "isatty", lambda: False)
        launcher._err.warnings = 3
        launcher._acknowledge_warnings()
        capsys.readouterr()
        assert prompted == []

    def test_warnings_from_both_consoles_are_totalled(self, tty, prompted, capsys):
        launcher._out.warnings = 1
        launcher._err.warnings = 2
        launcher._acknowledge_warnings()
        out = capsys.readouterr().out
        assert len(prompted) == 1
        assert "3 warnings above." in out

    def test_singular_wording_for_one_warning(self, tty, prompted, capsys):
        launcher._err.warnings = 1
        launcher._acknowledge_warnings()
        assert "1 warning above." in capsys.readouterr().out

    def test_ctrl_c_at_the_prompt_aborts_the_launch(self, tty, monkeypatch, capsys):
        def interrupt(*a, **k):
            raise KeyboardInterrupt

        monkeypatch.setattr(launcher.typer, "prompt", interrupt)
        launcher._err.warnings = 1
        with pytest.raises(typer.Exit):
            launcher._acknowledge_warnings()
        capsys.readouterr()


def test_both_exec_paths_acknowledge_before_handing_over_the_terminal():
    """The ordering IS the fix — acknowledging after the exec would never run."""
    src = launcher.__file__
    with open(src, encoding="utf-8") as f:
        lines = f.readlines()

    exec_lines = [i for i, ln in enumerate(lines) if "os.execvp(rt, exec_argv)" in ln
                  or "os.execvpe(argv[0], argv, env)" in ln]
    assert len(exec_lines) == 2, "expected exactly two exec handoff sites"

    for idx in exec_lines:
        preceding = "".join(lines[max(0, idx - 5):idx])
        assert "_acknowledge_warnings()" in preceding, (
            "exec at line %d is not preceded by _acknowledge_warnings()" % (idx + 1)
        )
