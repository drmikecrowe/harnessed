"""Passthrough suffix: args after a standalone `--` are appended to the launched harness command.

`harnessed launch <stack> claude -- --chrome` runs `claude … --chrome`, and the same for `host-run`.
Click treats `--` only as end-of-options and would otherwise bind the first suffix token to the
optional `path` positional, so the launcher splits it off argv before Typer parses (`main`).
"""

import shlex

import pytest

from harnessed import launcher
from support import patch_all


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
    """`main` strips the passthrough and rebuilds sys.argv — and now does NOTHING else.

    It used to prepend `launch` for any leading token that was not in the hand-maintained
    `_COMMANDS` set, so `harnessed <stack> …` meant `harnessed launch <stack> …`. With the stack
    named by `--stack`, a leading bare token is a subcommand and the shorthand is gone.
    """

    @pytest.fixture(autouse=True)
    def _stub_app(self, monkeypatch):
        monkeypatch.setattr(launcher, "app", lambda: None)

    def test_argv_passes_through_untouched_but_for_the_suffix(self, monkeypatch):
        monkeypatch.setattr(
            launcher.sys, "argv",
            ["harnessed", "container-run", "claude", "-s", "mystack", "--", "--chrome"],
        )
        launcher.main()
        assert launcher.sys.argv == ["harnessed", "container-run", "claude", "-s", "mystack"]
        assert launcher._passthrough == ["--chrome"]

    def test_an_unknown_leading_token_is_not_rewritten(self, monkeypatch):
        """It reaches Typer as a subcommand and fails there, rather than being read as a stack."""
        monkeypatch.setattr(launcher.sys, "argv", ["harnessed", "mystack", "claude"])
        launcher.main()
        assert launcher.sys.argv == ["harnessed", "mystack", "claude"]

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
        self._run(["--chrome"], shell=True)  # noqa: S604 — shell=True is a flag to the launcher under test, not subprocess
        assert captured["argv"][-1].endswith("exec bash -l")
