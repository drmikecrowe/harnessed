"""`harnessed scan` and `harnessed rescan` must delegate to an interpreter that can import
`harnessed.cli` (#493).

The same defect #460 fixed for `harnessed test`, in the two commands PR #491 did not touch. Both
reach the online archive scan through `_scan_image`, which picked its child by NAME —
`uv run --no-project --quiet --with ruamel.yaml python` — under an environment whose `PYTHONPATH`
was synthesized as `<root>/src`. That is a repository checkout layout. An installed harnessed keeps
the package in the tool's site-packages, so every installed copy failed here:

    Error while finding module specification for 'harnessed.cli'
    (ModuleNotFoundError: No module named 'harnessed')

`rescan` is what the systemd timer fires, so on an installed machine the nightly online scan was
failing rather than finding nothing — the one failure mode `scan.py`'s Pitfall 6 calls out.

Same fix, same shape of proof: delegate to `sys.executable`, and assert the property by RUNNING the
import in a real child under the captured environment. The argv- and env-shaped assertions beside it
are subordinate; they pin what was deliberate and do not substitute for the import.
"""

from __future__ import annotations

import subprocess
import sys

import pytest
from typer.testing import CliRunner

from harnessed import launcher

# ONE implementation of the virtualenv scrub, deliberately shared rather than copied. Its docstring
# explains what it does and does not constrain, and a second copy is how one of the two silently
# loses its teeth. `pythonpath = ["tests"]` in pyproject.toml is what makes this import resolve.
from test_launcher_test_command import _interpreter_invocation, _without_an_active_virtualenv

runner = CliRunner()


@pytest.fixture(params=["scan", "rescan"])
def delegated(request, monkeypatch, tmp_path):
    """Drive one of the two commands with a root that has NO `src/`, and capture the online scan.

    Parametrized over both, because they carry the defect independently: two separate `run_env`
    lines building the same broken environment for the same helper. A fix to one is not evidence
    about the other.

    Returns a dict the tests read: `cmd`, `env`, `root`, `spawn`, `invoke`.
    """
    root = tmp_path / "installed-root"
    root.mkdir()
    assert not (root / "src").exists(), "the fixture's premise: an installed layout has no src/"

    captured: dict = {}
    # The real `subprocess.run`, kept before anything below can reach it — the import probe must
    # start an actual child rather than a fake that reports success having run nothing.
    captured["spawn"] = subprocess.run

    def fake_bounded(cmd, **kwargs):
        # `_bounded` serves three callers here: the image-exists probe, the image listing, and the
        # online scan. Only the last is under test; the others just have to answer plausibly.
        if "scan-image-online" in cmd:
            captured["cmd"] = list(cmd)
            captured["env"] = dict(kwargs["env"])
        return subprocess.CompletedProcess(list(cmd), 0, stdout="", stderr="")

    # An installed user's plain shell exports no PYTHONPATH, so neither does the environment these
    # tests start from. Left in, an ambient one reaches the child through `**os.environ` and can
    # make `harnessed` importable on its own — the probe would then pass on code that resolves its
    # interpreter by name and supplies nothing, which is the regression this file exists to catch.
    # The two tests that care about PYTHONPATH set it themselves.
    monkeypatch.delenv("PYTHONPATH", raising=False)
    monkeypatch.setattr(launcher, "_harnessed_dir", lambda: root)
    monkeypatch.setattr(launcher, "_runtime", lambda: "podman")
    monkeypatch.setattr(launcher, "_bounded", fake_bounded)
    # The credentialed in-image pass is a real container run and a separate concern; `_scan_image`
    # only ANDs its result into the verdict.
    monkeypatch.setattr(launcher, "_scan_image_in_container", lambda rt, image: True)
    # `podman save` — the tarball's contents are irrelevant, only the path handed to the child.
    monkeypatch.setattr(launcher, "_run", lambda *a, **k: subprocess.CompletedProcess([], 0))

    if request.param == "scan":
        stack_dir = tmp_path / "stacks" / "demo"
        stack_dir.mkdir(parents=True)
        (stack_dir / "stack.yaml").write_text("name: demo\n")
        monkeypatch.setattr(launcher.paths, "find_in_catalog", lambda kind, name: stack_dir)
        monkeypatch.setattr(launcher, "is_built", lambda stack, harness: True)
        argv = ["scan", "demo", "claude"]
    else:
        argv = ["rescan", "localhost/harnessed-demo:latest"]

    captured["root"] = root
    captured["invoke"] = lambda: runner.invoke(launcher.app, argv)
    return captured


class TestDelegatedInterpreter:
    """The promise: whatever the online scan delegates to can import `harnessed.cli`."""

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
            f"the child the online scan delegates to cannot import harnessed.cli\n"
            f"interpreter: {_interpreter_invocation(delegated['cmd'])}\n"
            f"PYTHONPATH:  {delegated['env'].get('PYTHONPATH', '<unset>')}\n"
            f"stderr:\n{probe.stderr}"
        )

    def test_the_delegated_interpreter_is_the_one_already_running(self, delegated):
        delegated["invoke"]()
        assert delegated["cmd"][0] == sys.executable

    def test_it_runs_the_cli_module_against_the_saved_tarball(self, delegated):
        delegated["invoke"]()
        cmd = delegated["cmd"]
        assert cmd[:4] == [sys.executable, "-m", "harnessed.cli", "scan-image-online"]
        assert cmd[4].endswith(".tar"), f"no tarball path handed to the scan: {cmd}"
        assert len(cmd) == 5

    def test_no_dependency_is_installed_on_the_fly(self, delegated):
        """`--with ruamel.yaml` existed to patch up an interpreter that was not this one.

        `ruamel.yaml` is a declared runtime dependency in `pyproject.toml`, so the interpreter
        running this process already has it. Re-requesting it also made the scan depend on `uv`
        being installed and on the network resolving a package, on a path whose whole job is to
        report vulnerabilities.
        """
        delegated["invoke"]()
        assert "--with" not in delegated["cmd"]
        assert "uv" not in delegated["cmd"]


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

    def test_the_runtime_is_passed_through(self, delegated):
        """`CONTAINER_RUNTIME` is the one thing the child genuinely needs from here, and it is what
        a careless "drop the synthesized env" would have taken with it."""
        delegated["invoke"]()
        assert delegated["env"]["CONTAINER_RUNTIME"] == "podman"
