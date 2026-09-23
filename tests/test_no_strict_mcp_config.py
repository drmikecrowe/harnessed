"""`--no-strict-mcp-config`: let claude read its own MCP sources on top of the stack's.

Default is strict — `claude --mcp-config <stack file> --strict-mcp-config` makes the stack's file the
ONLY MCP source, so a project's `.mcp.json` sitting in the cwd is ignored. This flag drops the strict
switch (the `--mcp-config` file is still passed), which is what lets the project file load again.
Both backends are covered: the container attach command and the host-native argv.
"""

import inspect
import shlex
from pathlib import Path

import pytest
from typer.testing import CliRunner

from harnessed import launcher, paths
from support import patch_all

runner = CliRunner()


def test_both_verbs_expose_the_flag():
    """Asserted on the registered params, not on --help text, which wraps at terminal width."""
    for fn in (launcher.host_run, launcher.container_run):
        param = inspect.signature(fn).parameters["no_strict_mcp_config"]
        assert "--no-strict-mcp-config" in param.default.param_decls


class TestContainerAttach:
    @pytest.fixture
    def captured(self, monkeypatch):
        calls: dict = {}
        patch_all(monkeypatch, "_init_shell_prologue", lambda *a, **k: "")
        patch_all(monkeypatch, "_keyring_init", lambda *a, **k: "")
        monkeypatch.setattr(launcher, "_touch_attach_marker", lambda *a, **k: None)
        monkeypatch.setattr(launcher, "_acknowledge_warnings", lambda *a, **k: None)
        monkeypatch.setattr(launcher.paths, "container_mcp_config", lambda: "/mcp.json")

        def fake_execvp(rt, argv):
            calls["argv"] = argv
            raise SystemExit(0)

        monkeypatch.setattr(launcher.os, "execvp", fake_execvp)
        return calls

    def _run(self, no_strict_mcp, extra=None):
        with pytest.raises(SystemExit):
            launcher._attach(
                "podman", "claude", "inst", Path("/proj"),
                stack="s", mount_path=Path("/proj"),
                extra=extra, no_strict_mcp=no_strict_mcp,
            )

    def test_default_keeps_strict(self, captured):
        self._run(False)
        assert captured["argv"][-1].endswith("claude --mcp-config '/mcp.json' --strict-mcp-config")

    def test_flag_drops_strict_but_keeps_the_config_file(self, captured):
        self._run(True)
        assert captured["argv"][-1].endswith("claude --mcp-config '/mcp.json'")

    def test_passthrough_still_appends_after_the_flag(self, captured):
        """The `-- <suffix>` tail is independent of strictness and must survive its removal."""
        self._run(True, extra=["--resume", "a b"])
        assert captured["argv"][-1].endswith(
            "claude --mcp-config '/mcp.json' --resume " + shlex.quote("a b")
        )


class TestHostRun:
    @pytest.fixture
    def captured(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-host-src"))
        calls: dict = {}

        def fake_execvpe(file, argv, env):
            calls.update(file=file, argv=argv)
            raise SystemExit(0)  # execvpe would replace the process; halt cleanly instead

        monkeypatch.setattr(launcher.os, "execvpe", fake_execvpe)
        monkeypatch.setattr(launcher.os, "chdir", lambda *_a: None)
        return calls

    def _invoke(self, tmp_path, *flags):
        return runner.invoke(
            launcher.app,
            ["host-run", "claude", str(tmp_path), "--stack", "hostspike", *flags],
        )

    def test_default_keeps_strict(self, captured, tmp_path):
        result = self._invoke(tmp_path)
        assert result.exit_code == 0, result.output
        assert "--strict-mcp-config" in captured["argv"]

    def test_flag_drops_strict_but_keeps_the_config_file(self, captured, tmp_path):
        result = self._invoke(tmp_path, "--no-strict-mcp-config")
        assert result.exit_code == 0, result.output
        argv = captured["argv"]
        assert "--strict-mcp-config" not in argv
        mcp_path = paths.host_home("hostspike", "claude") / ".mcp.json"
        assert argv[:3] == ["claude", "--mcp-config", str(mcp_path)]
