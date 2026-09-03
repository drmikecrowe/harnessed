"""#450 — `host-exec` / `container-exec`: the run verbs with nobody at the keyboard.

The only way to run a stack headless was to smuggle the flag through the passthrough
(`host-run omp -- -p "…"`), which worked by accident. Both run verbs are built for a human: they
block on pending `setup:` notices, on a stale profile and on an older-build instance, and the
container path allocates a pty. None of that is right when the caller handed over a prompt and is
waiting for an exit code.

These tests state the two halves of the contract. That `-exec` is the SAME FUNCTION under a second
name is the first half — twenty-odd options across the two verbs, and a forwarding wrapper is a
second signature to keep in step and a guaranteed drift. That it takes the non-interactive branch
everywhere is the second.
"""
from __future__ import annotations

import pytest

from harnessed import console, launcher


@pytest.fixture(autouse=True)
def _reset_exec_mode(monkeypatch):
    """`_EXEC_MODE` is per-invocation module state, like `_passthrough`. Never leak it across tests."""
    monkeypatch.setattr(console, "_EXEC_MODE", False)


def _command_names() -> set[str]:
    return {c.name for c in launcher.app.registered_commands}


class TestBothBackendsGetTheVerb:
    def test_the_verbs_are_registered(self):
        assert {"host-exec", "container-exec"} <= _command_names()

    def test_they_are_the_run_verbs_own_function(self):
        # Not a wrapper. A second signature drifts the moment one verb gains an option.
        by_name = {c.name: c.callback for c in launcher.app.registered_commands}
        assert by_name["host-exec"] is by_name["host-run"]
        assert by_name["container-exec"] is by_name["container-run"]


class TestExecModeNeverBlocksOnAQuestion:
    """A `typer.prompt` with nobody to answer it does not ask a question, it hangs a script."""

    def test_a_tty_alone_no_longer_licenses_a_prompt(self, monkeypatch):
        monkeypatch.setattr(console.sys.stdin, "isatty", lambda: True)
        assert console._can_prompt()
        monkeypatch.setattr(console, "_EXEC_MODE", True)
        assert not console._can_prompt(), "exec mode has a real TTY and still nobody at it"

    def test_the_run_verbs_still_prompt(self, monkeypatch):
        # The whole guard is scoped to `-exec`; an interactive launch must be unchanged.
        monkeypatch.setattr(console.sys.stdin, "isatty", lambda: True)
        assert console._can_prompt()

    def test_no_tty_still_never_prompts(self, monkeypatch):
        monkeypatch.setattr(console.sys.stdin, "isatty", lambda: False)
        assert not console._can_prompt()

    def test_the_setup_notice_prompt_is_skipped(self, monkeypatch, tmp_path):
        # It would otherwise stop on `[O]k / [D]ismiss / [Q]uit` with no one to type a letter.
        monkeypatch.setattr(console.sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(console, "_EXEC_MODE", True)
        monkeypatch.setattr(launcher, "_collect_setup_notices", lambda *a, **k: ["a recipe"])
        monkeypatch.setattr(
            launcher.typer, "prompt",
            lambda *a, **k: pytest.fail("exec mode must not prompt"),
        )
        assert launcher._prompt_setup_notices([], tmp_path, "s", "claude") is False

    def test_the_warning_acknowledgement_is_skipped(self, monkeypatch):
        # `_acknowledge_warnings` holds the terminal for a keypress right before the exec handoff.
        monkeypatch.setattr(console.sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(console, "_EXEC_MODE", True)
        monkeypatch.setattr(launcher._out, "warnings", 3)
        monkeypatch.setattr(launcher._err, "warnings", 0)
        monkeypatch.setattr(
            launcher.typer, "prompt",
            lambda *a, **k: pytest.fail("exec mode must not wait for a keypress"),
        )
        launcher._acknowledge_warnings()

    def test_a_confirm_gated_setup_is_skipped_not_asked(self, monkeypatch, tmp_path):
        # `setup.confirm` guards a step that WRITES to the user's repo (bd init commits 18 files).
        # A real TTY with nobody at it is not consent, so exec mode must take the skip branch.
        from harnessed import setupenv
        from harnessed.schema import Recipe, SetupSpec

        monkeypatch.setattr(console.sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(console, "_EXEC_MODE", True)
        monkeypatch.setattr(
            setupenv.typer, "confirm",
            lambda *a, **k: pytest.fail("exec mode must not ask to change the repo"),
        )
        recipe = Recipe(name="r", root=tmp_path)
        recipe.setup = SetupSpec(summary="s", reference="r", confirm="this will commit files")
        assert setupenv._confirm_setup(recipe, "s", tmp_path, harness="claude") is False


class TestTheContainerExecAllocatesNoPty:
    """`podman exec -t` makes the harness draw on the alternate screen buffer.

    The answer the caller asked for is then wiped at exit, and the escape sequences that do survive
    land in whatever they piped the output into. `-i` stays in both modes — a prompt arriving on
    stdin has to reach the agent.
    """

    def _exec_argv(self, monkeypatch, tmp_path, *, exec_mode: bool) -> list[str]:
        captured: list[list[str]] = []
        monkeypatch.setattr(console, "_EXEC_MODE", exec_mode)
        monkeypatch.setattr(launcher, "_touch_attach_marker", lambda _i: None)
        monkeypatch.setattr(launcher, "_acknowledge_warnings", lambda: None)
        monkeypatch.setattr(launcher, "_init_shell_prologue", lambda *a, **k: "true")
        monkeypatch.setattr(launcher, "_keyring_init", lambda _h: "")
        monkeypatch.setattr(launcher.os, "execvp", lambda _f, argv: captured.append(argv))
        launcher._attach(
            "podman", "claude", "inst", tmp_path, stack="s", mount_path=tmp_path,
            extra=["-p", "hi"],
        )
        assert captured, "_attach must have reached the exec handoff"
        return captured[0]

    def test_exec_mode_drops_the_t_flag(self, monkeypatch, tmp_path):
        argv = self._exec_argv(monkeypatch, tmp_path, exec_mode=True)
        assert "-i" in argv and "-t" not in argv and "-it" not in argv

    def test_the_interactive_attach_still_allocates_one(self, monkeypatch, tmp_path):
        argv = self._exec_argv(monkeypatch, tmp_path, exec_mode=False)
        assert "-t" in argv and "-i" in argv

    def test_the_passthrough_still_reaches_the_harness(self, monkeypatch, tmp_path):
        # The verb is useless if the prompt it exists to carry is dropped.
        argv = self._exec_argv(monkeypatch, tmp_path, exec_mode=True)
        assert "-p hi" in argv[-1]


class TestTheLauncherScriptStillNamesTheLaunch:
    """`host-exec` IS the `host-run` launch, so it must still caption the script it writes."""

    def test_an_exec_invocation_captions_its_run_verbs_script(self, monkeypatch):
        monkeypatch.setattr(launcher, "_invocation", ["host-exec", "claude", "-s", "x"])
        assert launcher._typed_invocation("host-run") == [
            "harnessed", "host-exec", "claude", "-s", "x",
        ]

    def test_the_other_backends_exec_verb_is_still_refused(self, monkeypatch):
        # The alias is named, not prefix-matched — a comment naming a different launch is the one
        # thing `_typed_invocation` exists to prevent.
        monkeypatch.setattr(launcher, "_invocation", ["container-exec", "claude"])
        assert launcher._typed_invocation("host-run") is None
