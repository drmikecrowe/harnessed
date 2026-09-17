"""`harnessed test` must delegate to an interpreter that can import `harnessed.cli` (#460).

The command runs the capability suite in a child process. It used to pick that child by NAME
— `uv run --no-project`, falling back to `python3` — and then try to make `harnessed`
importable by setting `PYTHONPATH` to `<root>/src`. `<root>/src` is a repository checkout
layout. An installed harnessed keeps the package in the tool's site-packages, so every
installed copy failed here before it ever reached a container:

    Error while finding module specification for 'harnessed.cli'
    (ModuleNotFoundError: No module named 'harnessed')

The fix delegates to `sys.executable`, the interpreter already running the parent command.
That one can import `harnessed.cli` by construction, because `harnessed.launcher` is running
in it, and it carries the declared runtime dependencies with it.

`TestDelegatedInterpreter` asserts that property by RUNNING the import in a real child under
the captured environment. The argv- and env-shaped assertions beside it are subordinate: they
pin which behaviour was deliberate, and they do not substitute for the import.
"""

from __future__ import annotations

import os
import subprocess
import sys

from pathlib import Path

import pytest
from typer.testing import CliRunner

from harnessed import launcher

runner = CliRunner()


@pytest.fixture
def delegated(monkeypatch, tmp_path):
    """Drive `harnessed test` with a root that has NO `src/` and capture the delegated call.

    Returns a dict the tests read: `cmd`, `env`, `root`. `subprocess.run` is replaced, so no
    capability suite and no container runs — the point of interest is the call itself.
    """
    root = tmp_path / "installed-root"
    root.mkdir()
    assert not (root / "src").exists(), "the fixture's premise: an installed layout has no src/"

    captured: dict = {}

    # The real `subprocess.run`, kept before the patch below replaces it. `launcher.subprocess`
    # IS the subprocess module, so patching through it replaces the function for this whole
    # process — the import probe would otherwise call the fake and report success without ever
    # starting a child.
    captured["spawn"] = subprocess.run

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        captured["env"] = dict(kwargs["env"])
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(launcher, "_harnessed_dir", lambda: root)
    monkeypatch.setattr(launcher, "_runtime", lambda: "podman")
    monkeypatch.setattr(launcher, "is_built", lambda stack, harness: True)
    monkeypatch.setattr(launcher.staleness, "check_profile_fresh", lambda *a, **k: None)
    monkeypatch.setattr(launcher.subprocess, "run", fake_run)

    captured["root"] = root
    captured["invoke"] = lambda *args: runner.invoke(launcher.app, ["test", "demo", "claude", *args])
    return captured


def _without_an_active_virtualenv(env: dict[str, str]) -> dict[str, str]:
    """`env` as an installed user's plain shell would have it: no virtualenv in scope.

    This scrub is what makes the import assertion mean anything, and it is also the answer to
    why the defect survived to release. `uv run --no-project` resolves `python` through the
    caller's environment, so an activated virtualenv — `VIRTUAL_ENV`, or its `bin` directory
    sitting on `PATH` — silently supplied `harnessed` to the child. Every developer working on
    this repository has one active. Nobody who installs the tool does. Leave either in place
    and this assertion passes on the broken code, measuring the test runner's shell instead of
    what the command chose.

    A `PATH` entry is a virtualenv's `bin` when `pyvenv.cfg` sits beside it. Entries that are
    not are kept, so `uv` itself stays resolvable and a failure here is an import failure
    rather than a missing binary.
    """
    scrubbed = {k: v for k, v in env.items() if k != "VIRTUAL_ENV"}
    outside_a_venv = [
        entry
        for entry in scrubbed.get("PATH", "").split(os.pathsep)
        if entry and not (Path(entry).parent / "pyvenv.cfg").exists()
    ]
    scrubbed["PATH"] = os.pathsep.join(outside_a_venv)
    return scrubbed


def _interpreter_invocation(cmd: list[str]) -> list[str]:
    """The part of the delegated command that names the interpreter, before `-m <module>`.

    Written to work on either shape of the command, so the import assertion below fails on
    behaviour rather than on an index error when the command is wrong.
    """
    assert "-m" in cmd, f"delegated command runs no module: {cmd}"
    return cmd[: cmd.index("-m")]


class TestDelegatedInterpreter:
    """The promise: whatever `harnessed test` delegates to can import `harnessed.cli`."""

    def test_the_delegated_interpreter_and_env_can_import_harnessed_cli(self, delegated):
        result = delegated["invoke"]()
        assert result.exit_code == 0, result.output

        probe_env = _without_an_active_virtualenv(delegated["env"])
        probe = delegated["spawn"](
            [*_interpreter_invocation(delegated["cmd"]), "-c", "import harnessed.cli"],
            env=probe_env,
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert probe.returncode == 0, (
            f"the child `harnessed test` delegates to cannot import harnessed.cli\n"
            f"interpreter: {_interpreter_invocation(delegated['cmd'])}\n"
            f"PYTHONPATH:  {delegated['env'].get('PYTHONPATH', '<unset>')}\n"
            f"stderr:\n{probe.stderr}"
        )

    def test_the_delegated_interpreter_is_the_one_already_running(self, delegated):
        delegated["invoke"]()
        assert delegated["cmd"][0] == sys.executable

    def test_it_runs_the_cli_module_with_the_stack_the_harness_and_the_root(self, delegated):
        delegated["invoke"]()
        assert delegated["cmd"] == [
            sys.executable, "-m", "harnessed.cli",
            "test", "demo", "claude", "--root", str(delegated["root"]),
        ]


class TestDelegatedEnvironment:
    """No path is synthesized from a checkout layout, and an inherited one is left alone."""

    def test_no_pythonpath_is_synthesized(self, delegated, monkeypatch):
        monkeypatch.delenv("PYTHONPATH", raising=False)
        delegated["invoke"]()
        assert "PYTHONPATH" not in delegated["env"]

    def test_an_inherited_pythonpath_survives(self, delegated, monkeypatch):
        monkeypatch.setenv("PYTHONPATH", "/inherited/path")
        delegated["invoke"]()
        assert delegated["env"]["PYTHONPATH"] == "/inherited/path"

    def test_the_runtime_and_the_root_are_passed_through(self, delegated):
        delegated["invoke"]()
        assert delegated["env"]["CONTAINER_RUNTIME"] == "podman"
        assert delegated["env"]["HARNESSED_DIR"] == str(delegated["root"])


class TestOptionPassThrough:
    """`--project`, `--keep` and `--json` reach the capability suite, and only when asked for."""

    def test_no_options_are_added_when_none_are_given(self, delegated):
        delegated["invoke"]()
        assert "--project" not in delegated["cmd"]
        assert "--keep" not in delegated["cmd"]
        assert "--json" not in delegated["cmd"]

    def test_project_is_passed_with_its_value(self, delegated):
        delegated["invoke"]("--project", "/scratch/proj")
        assert delegated["cmd"][-2:] == ["--project", "/scratch/proj"]

    def test_keep_is_passed(self, delegated):
        delegated["invoke"]("--keep")
        assert "--keep" in delegated["cmd"]

    def test_json_is_passed(self, delegated):
        delegated["invoke"]("--json")
        assert "--json" in delegated["cmd"]

    def test_all_three_are_passed_together(self, delegated):
        delegated["invoke"]("--project", "/scratch/proj", "--keep", "--json")
        assert delegated["cmd"][-4:] == ["--project", "/scratch/proj", "--keep", "--json"]


class TestSurroundingBehaviourIsUnchanged:
    """Regression armor for what the delegation change must not disturb."""

    def test_the_child_exit_code_becomes_the_command_exit_code(self, delegated, monkeypatch):
        monkeypatch.setattr(
            launcher.subprocess, "run",
            lambda cmd, **kw: subprocess.CompletedProcess(cmd, 3),
        )
        assert delegated["invoke"]().exit_code == 3

    def test_an_unsupported_harness_is_rejected_before_anything_is_delegated(self, delegated):
        result = runner.invoke(launcher.app, ["test", "demo", "no-such-harness"])
        assert result.exit_code == 1
        assert "cmd" not in delegated

    def test_a_stack_that_is_not_built_is_assembled_first(self, delegated, monkeypatch):
        built = []
        monkeypatch.setattr(launcher, "is_built", lambda stack, harness: False)
        monkeypatch.setattr(launcher, "_build_stack", lambda rt, s, h: built.append((s, h)))
        delegated["invoke"]()
        assert built == [("demo", "claude")]

    def test_a_stale_profile_is_assembled_first(self, delegated, monkeypatch):
        built = []

        def stale(*a, **k):
            raise launcher.staleness.StaleProfileError("recipe edited")

        monkeypatch.setattr(launcher.staleness, "check_profile_fresh", stale)
        monkeypatch.setattr(launcher, "_build_stack", lambda rt, s, h: built.append((s, h)))
        delegated["invoke"]()
        assert built == [("demo", "claude")]
