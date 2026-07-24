"""Passthrough suffix: args after a standalone `--` are appended to the launched harness command.

`harnessed launch <stack> claude -- --chrome` runs `claude … --chrome`, and the same for `host-run`.
Click treats `--` only as end-of-options and would otherwise bind the first suffix token to the
optional `path` positional, so the launcher splits it off argv before Typer parses (`main`).
"""

import shlex

import pytest

from harnessed import launcher


class TestExtractPassthrough:
    def test_splits_at_first_double_dash(self):
        head = launcher._extract_passthrough(["S", "claude", "--", "--chrome"])
        assert head == ["S", "claude"]
        assert launcher._passthrough == ["--chrome"]

    def test_multiple_suffix_tokens(self):
        head = launcher._extract_passthrough(["S", "claude", "--", "--resume", "id", "-p"])
        assert head == ["S", "claude"]
        assert launcher._passthrough == ["--resume", "id", "-p"]

    def test_no_double_dash_clears_passthrough(self):
        launcher._passthrough = ["stale"]
        head = launcher._extract_passthrough(["S", "claude", "myproj"])
        assert head == ["S", "claude", "myproj"]
        assert launcher._passthrough == []

    def test_empty_suffix(self):
        head = launcher._extract_passthrough(["S", "claude", "--"])
        assert head == ["S", "claude"]
        assert launcher._passthrough == []


class TestMainArgvRewrite:
    """`main` strips the passthrough and rebuilds sys.argv; it also keeps the implicit-`launch`
    shorthand (`harnessed <stack> …` == `harnessed launch <stack> …`)."""

    @pytest.fixture(autouse=True)
    def _stub_app(self, monkeypatch):
        monkeypatch.setattr(launcher, "app", lambda: None)

    def test_bare_stack_prepends_launch_and_strips_suffix(self, monkeypatch):
        monkeypatch.setattr(launcher.sys, "argv", ["harnessed", "mystack", "claude", "--", "--chrome"])
        launcher.main()
        assert launcher.sys.argv == ["harnessed", "launch", "mystack", "claude"]
        assert launcher._passthrough == ["--chrome"]

    def test_explicit_launch_subcommand_not_double_prefixed(self, monkeypatch):
        monkeypatch.setattr(launcher.sys, "argv", ["harnessed", "launch", "mystack", "claude", "--", "-p", "hi"])
        launcher.main()
        assert launcher.sys.argv == ["harnessed", "launch", "mystack", "claude"]
        assert launcher._passthrough == ["-p", "hi"]

    def test_no_suffix_leaves_args_intact(self, monkeypatch):
        monkeypatch.setattr(launcher.sys, "argv", ["harnessed", "host-run", "mystack"])
        launcher.main()
        assert launcher.sys.argv == ["harnessed", "host-run", "mystack"]
        assert launcher._passthrough == []


class TestAttachAppendsSuffix:
    """The container path appends the (shell-quoted) suffix to the harness `tail` command."""

    @pytest.fixture
    def captured(self, monkeypatch):
        calls = {}
        monkeypatch.setattr(launcher, "_init_shell_prologue", lambda *a, **k: "")
        monkeypatch.setattr(launcher, "_keyring_init", lambda *a, **k: "")
        monkeypatch.setattr(launcher, "_touch_attach_marker", lambda *a, **k: None)
        monkeypatch.setattr(launcher, "_acknowledge_warnings", lambda *a, **k: None)
        monkeypatch.setattr(launcher.paths, "container_mcp_config", lambda: "/mcp.json")

        def fake_execvp(rt, argv):
            calls["argv"] = argv
            raise SystemExit(0)

        monkeypatch.setattr(launcher.os, "execvp", fake_execvp)
        return calls

    def _run(self, extra, shell=False):
        from pathlib import Path

        with pytest.raises(SystemExit):
            launcher._attach(
                "podman", "claude", "inst", Path("/proj"),
                stack="s", mount_path=Path("/proj"), shell=shell, extra=extra,
            )

    def test_suffix_appended_and_quoted(self, captured):
        self._run(["--chrome", "a b"])
        shell_cmd = captured["argv"][-1]  # bash -l -c <shell_cmd>
        assert shell_cmd.endswith("claude --mcp-config '/mcp.json' --strict-mcp-config --chrome " + shlex.quote("a b"))

    def test_no_suffix_leaves_command_unchanged(self, captured):
        self._run(None)
        assert captured["argv"][-1].endswith("claude --mcp-config '/mcp.json' --strict-mcp-config")

    def test_shell_mode_ignores_suffix(self, captured):
        self._run(["--chrome"], shell=True)
        assert captured["argv"][-1].endswith("exec bash -l")
