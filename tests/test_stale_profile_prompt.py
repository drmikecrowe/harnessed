"""`container-run` offers to rebuild a stale profile instead of only telling you to.

A stale stamp means the stack/recipe sources changed since assembly — something `harnessed build`
fixes. The guard still has to fail closed: the whole reason it exists is that launching a stale
profile silently runs an outdated image. So the three outcomes pinned here are consent (rebuild,
then launch), refusal (exit 1, no build) and no tty (exit 1, no prompt at all).

A missing/renamed recipe (SchemaError) stays a hard error — no rebuild can resolve it.
"""
from __future__ import annotations

import sys

import typer

from typer.testing import CliRunner

from harnessed import console, launcher, staleness
from harnessed.schema import SchemaError
from support import patch_all


class _Stdin:
    """Real stdin with `isatty()` forced — patching the object CliRunner installs is not enough."""

    def __init__(self, isatty: bool) -> None:
        self._isatty = isatty

    def isatty(self) -> bool:
        return self._isatty

    def __getattr__(self, name):
        return getattr(sys.stdin, name)


class _Sys:
    """`launcher.sys` with only `stdin` swapped.

    CliRunner replaces `sys.stdin` for the duration of `invoke`, AFTER any monkeypatch on the
    original object — and `sys.stdin.isatty()` resolves at call time, so it reads the runner's
    non-tty stream and the prompt branch is unreachable. Substituting the module reference the
    launcher itself holds is what survives that.
    """

    def __init__(self, isatty: bool) -> None:
        self.stdin = _Stdin(isatty)

    def __getattr__(self, name):
        return getattr(sys, name)


def _run(monkeypatch, tmp_path, *, isatty: bool, confirm: bool = True, exc: Exception | None = None):
    """Invoke `container-run` with the staleness guard tripped; return (result, builds, prompts)."""
    builds: list[tuple] = []
    prompts: list[str] = []

    (tmp_path / "stack.yaml").write_text("name: s\n")
    monkeypatch.setattr(launcher.paths, "find_in_catalog", lambda *a: tmp_path)
    # Otherwise the git-identity confirm just above the guard fires first and pollutes `prompts`.
    monkeypatch.setattr(launcher.paths, "git_common_dir", lambda *a: tmp_path / ".git")
    patch_all(monkeypatch, "_runtime", lambda: "podman")
    monkeypatch.setattr(launcher, "is_built", lambda *a: True)

    def _stale(*a, **k):
        raise exc or staleness.StaleProfileError("profile for 's' (claude) is stale")

    monkeypatch.setattr(launcher.staleness, "check_profile_fresh", _stale)
    monkeypatch.setattr(launcher, "_build_stack", lambda *a, **k: builds.append(a))
    # BOTH modules: the prompt guard `_can_prompt` reads `console.sys.stdin` (#450), while the
    # remaining tty checks in launcher.py read its own. Patching one leaves the other on the
    # runner's non-tty stream, and the branch under test stays unreachable.
    monkeypatch.setattr(launcher, "sys", _Sys(isatty))
    monkeypatch.setattr(console, "sys", _Sys(isatty))
    monkeypatch.setattr(typer, "confirm", lambda msg, **k: (prompts.append(msg), confirm)[1])
    # --create-aoe-only exits through the register hook; stub the bridge so a machine without `aoe`
    # installed does not turn "got past the guard" into exit 1.
    monkeypatch.setattr(launcher.aoe, "sync_session", lambda *a, **k: True)

    project = tmp_path / "proj"
    project.mkdir()
    result = CliRunner().invoke(
        launcher.app,
        ["container-run", "claude", str(project), "--stack", "s", "--create-aoe-only"],
    )
    return result, builds, prompts


def test_consent_rebuilds_and_continues(monkeypatch, tmp_path):
    result, builds, prompts = _run(monkeypatch, tmp_path, isatty=True, confirm=True)
    assert builds == [("podman", "s", "claude")]
    assert len(prompts) == 1
    # --create-aoe-only exits 0 from the register hook, which sits AFTER the guard: reaching it is
    # the proof that consent let the launch proceed rather than merely suppressing the error.
    assert result.exit_code == 0, result.output


def test_refusal_aborts_without_building(monkeypatch, tmp_path):
    result, builds, prompts = _run(monkeypatch, tmp_path, isatty=True, confirm=False)
    assert builds == []
    assert len(prompts) == 1
    assert result.exit_code == 1
    assert "cannot launch a stale profile" in result.output


def test_no_tty_aborts_without_prompting(monkeypatch, tmp_path):
    result, builds, prompts = _run(monkeypatch, tmp_path, isatty=False)
    assert builds == []
    assert prompts == []
    assert result.exit_code == 1
    assert "cannot launch a stale profile" in result.output


def test_a_missing_recipe_is_still_a_hard_error(monkeypatch, tmp_path):
    result, builds, prompts = _run(
        monkeypatch, tmp_path, isatty=True, confirm=True, exc=SchemaError("no recipe 'gone'")
    )
    assert builds == []
    assert prompts == []
    assert result.exit_code == 1
