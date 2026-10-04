"""#529 — `container-acp`: an `-exec` launch whose stdout is an ACP client's JSON-RPC channel.

Every byte on stdout has to parse as JSON-RPC, so the contract has three halves: harnessed's own
launch output goes to stderr (an fd swap, so children that inherit fd 1 are covered too), the attach
shell's prologue goes to stderr, and the harness alone gets the real stdout. The command that starts
the harness as an ACP agent is chosen per harness, and only omp has one.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest
from typer.testing import CliRunner

from harnessed import attachcmd, console, launcher


@pytest.fixture(autouse=True)
def _reset_modes(monkeypatch):
    """Both modes are per-invocation module state. The ACP one also holds a real fd: put it back."""
    monkeypatch.setattr(console, "_EXEC_MODE", False)
    yield
    console.set_acp_mode(False)


class TestTheVerb:
    def test_it_is_the_container_run_function(self):
        # Not a wrapper, for the same reason as `container-exec`: a second signature drifts.
        by_name = {c.name: c.callback for c in launcher.app.registered_commands}
        assert by_name["container-acp"] is by_name["container-run"]

    def test_a_harness_without_acp_is_refused_before_any_work(self, monkeypatch):
        monkeypatch.setattr(
            launcher, "_resolve_stack", lambda *a, **k: pytest.fail("must refuse before resolving")
        )
        result = CliRunner().invoke(launcher.app, ["container-acp", "claude"])
        assert result.exit_code == 2
        assert "no ACP mode" in result.output

    def test_it_is_exec_mode_too(self, monkeypatch):
        # ACP implies exec: no pty, no prompts, and `--shell` refused.
        result = CliRunner().invoke(launcher.app, ["container-acp", "omp", "--shell"])
        assert result.exit_code == 2
        assert console.in_exec_mode()
        assert "--shell is interactive" in result.output

    def test_it_captions_the_container_run_script(self, monkeypatch):
        monkeypatch.setattr(launcher, "_invocation", ["container-acp", "omp"])
        assert launcher._typed_invocation("container-run") == ["harnessed", "container-acp", "omp"]
        assert launcher._typed_invocation("host-run") is None


class TestTheAcpCommand:
    def test_omp_keeps_its_session_dir(self, monkeypatch, tmp_path):
        monkeypatch.setattr(attachcmd.Path, "home", lambda: tmp_path)
        start = tmp_path / "Prog" / "x"
        cmd = attachcmd._acp_attach_cmd("omp", start)
        assert cmd == attachcmd._omp_attach_cmd(start) + " acp"
        assert "--session-dir" in cmd and cmd.endswith(" acp")

    def test_omp_at_home_is_bare_omp_acp(self, monkeypatch, tmp_path):
        monkeypatch.setattr(attachcmd.Path, "home", lambda: tmp_path)
        assert attachcmd._acp_attach_cmd("omp", tmp_path) == "omp acp"

    @pytest.mark.parametrize("harness", ["claude", "opencode", "antigravity", "codex"])
    def test_every_other_harness_has_none(self, harness, tmp_path):
        assert harness not in attachcmd._ACP_HARNESSES
        with pytest.raises(ValueError):
            attachcmd._acp_attach_cmd(harness, tmp_path)


class TestHostStdoutIsSwapped:
    def test_fd1_goes_to_stderr_and_comes_back(self, capfd):
        console.set_acp_mode(True)
        assert console.in_acp_mode()
        os.write(1, b"launch-noise\n")
        console.restore_acp_stdout()
        assert not console.in_acp_mode()
        os.write(1, b"harness-json\n")
        out, err = capfd.readouterr()
        assert out == "harness-json\n"
        assert "launch-noise" in err

    def test_a_child_that_inherits_fd1_writes_to_stderr(self, capfd):
        # The reason for an fd swap rather than retargeting `_out`: podman build and friends.
        console.set_acp_mode(True)
        subprocess.run([sys.executable, "-c", "print('child-noise')"], check=True)
        console.restore_acp_stdout()
        out, err = capfd.readouterr()
        assert out == ""
        assert "child-noise" in err

    def test_off_is_a_no_op_when_never_on(self, capfd):
        console.set_acp_mode(False)
        os.write(1, b"x")
        assert capfd.readouterr().out == "x"


class _Execed(Exception):
    """Stands in for `os.execvp` replacing the process image."""


def _attach_argv(monkeypatch, tmp_path, *, prologue: str = "true", ephemeral: bool = False):
    """Run `_attach` in ACP mode for omp and return (argv, state seen at the handoff)."""
    seen: dict = {}
    monkeypatch.setattr(console, "_EXEC_MODE", True)
    monkeypatch.setattr(launcher, "_touch_attach_marker", lambda _i: None)
    monkeypatch.setattr(launcher, "_acknowledge_warnings", lambda: None)
    monkeypatch.setattr(launcher, "_init_shell_prologue", lambda *a, **k: prologue)
    monkeypatch.setattr(launcher, "_keyring_init", lambda _h: "")
    monkeypatch.setattr(launcher, "_pod_teardown", lambda *a: None)
    monkeypatch.setattr(launcher, "_attach_marker", lambda _i: tmp_path / "marker")

    def _execvp(_f, argv):
        seen.update(argv=argv, acp_at_handoff=console.in_acp_mode())
        raise _Execed

    def _run(argv, **kw):
        seen.update(argv=argv, stdout=kw.get("stdout"), saved=console.acp_stdout())

    monkeypatch.setattr(launcher.os, "execvp", _execvp)
    if ephemeral:
        # Only here: `launcher.subprocess` IS the subprocess module, and a test runs bash after this.
        monkeypatch.setattr(launcher.subprocess, "run", _run)
    console.set_acp_mode(True)
    try:
        launcher._attach(
            "podman", "omp", "inst", tmp_path, stack="s", mount_path=tmp_path,
            ephemeral=ephemeral,
        )
    except _Execed:
        pass
    return seen["argv"], seen


class TestContainerStdoutIsClean:
    def test_the_harness_is_omp_acp_with_no_pty(self, monkeypatch, tmp_path):
        argv, _ = _attach_argv(monkeypatch, tmp_path)
        assert "-t" not in argv and "-i" in argv
        assert argv[-1].endswith(attachcmd._acp_attach_cmd("omp", tmp_path))

    def test_everything_before_the_harness_goes_to_stderr(self, monkeypatch, tmp_path):
        argv, _ = _attach_argv(monkeypatch, tmp_path)
        shell_cmd = argv[-1]
        prefix, _, tail = shell_cmd.rpartition("; } >&2 && ")
        assert prefix.startswith("{ source ~/.bashrc")
        assert tail == attachcmd._acp_attach_cmd("omp", tmp_path)

    def test_stdout_is_restored_before_the_exec(self, monkeypatch, tmp_path):
        _, seen = _attach_argv(monkeypatch, tmp_path)
        assert seen["acp_at_handoff"] is False

    def test_the_rm_child_gets_the_clients_channel(self, monkeypatch, tmp_path):
        # The parent keeps stderr, because it still prints the teardown line after the session.
        _, seen = _attach_argv(monkeypatch, tmp_path, ephemeral=True)
        assert seen["stdout"] is not None and seen["stdout"] == seen["saved"]

    def test_the_composed_shell_keeps_stdout_to_the_harness(self, monkeypatch, tmp_path):
        """The real shell semantics, run through bash: noise to stderr, exports still reach the tail."""
        home = tmp_path / "home"
        (home / "bin").mkdir(parents=True)
        (home / ".bashrc").write_text("echo bashrc-noise\n")
        mise = home / "bin" / "mise"
        mise.write_text("#!/bin/sh\necho mise-noise\n")
        mise.chmod(0o755)
        monkeypatch.setattr(
            launcher, "_acp_attach_cmd", lambda *_a: "echo \"{\\\"v\\\":\\\"$FOO\\\"}\""
        )
        argv, _ = _attach_argv(
            monkeypatch, tmp_path, prologue="export FOO=bar; echo prologue-noise"
        )
        env = {**os.environ, "HOME": str(home), "PATH": f"{home / 'bin'}:{os.environ['PATH']}"}
        proc = subprocess.run(
            ["bash", "-c", argv[-1]], capture_output=True, text=True, env=env, check=False
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout == '{"v":"bar"}\n'
        assert "bashrc-noise" in proc.stderr and "prologue-noise" in proc.stderr

    def test_the_interactive_attach_is_unchanged(self, monkeypatch, tmp_path):
        monkeypatch.setattr(launcher, "_touch_attach_marker", lambda _i: None)
        monkeypatch.setattr(launcher, "_acknowledge_warnings", lambda: None)
        monkeypatch.setattr(launcher, "_init_shell_prologue", lambda *a, **k: "true")
        monkeypatch.setattr(launcher, "_keyring_init", lambda _h: "")
        captured: list = []

        def _execvp(_f, argv):
            captured.append(argv)
            raise _Execed

        monkeypatch.setattr(launcher.os, "execvp", _execvp)
        with pytest.raises(_Execed):
            launcher._attach("podman", "omp", "inst", tmp_path, stack="s", mount_path=tmp_path)
        assert ">&2" not in captured[0][-1]
        assert not captured[0][-1].endswith(" acp")


def test_no_path_reaches_the_attach_unswapped():
    """Guard the ordering: the swap is set before the first line of container_run that can print."""
    import inspect

    src = inspect.getsource(launcher.container_run)
    assert src.index("set_acp_mode(acp_mode)") < src.index("_resolve_stack(")
