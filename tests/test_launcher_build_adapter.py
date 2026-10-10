"""GH-571 AC-6 — `build <stack> claude` offers to install the pinned claude-agent-acp adapter.

The adapter is what `host-acp claude` runs. Its pin lives in `catalog/agents/claude/agent.yaml`
(`build_args.CLAUDE_AGENT_ACP_VERSION`), and "installed" means the `claude-agent-acp` on PATH
prints that version for `--version` (SPEC revision 5). The fake adapter is a real executable, so
the detection runs for real; only the install command and the image build are stubbed.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from harnessed import launcher
from support import patch_all

runner = CliRunner()

_QUESTION = (
    "I need to install `npm i -g @agentclientprotocol/claude-agent-acp@0.85.1` to support ACP "
    "-- is that OK? (y/n/c)"
)
_NPM = ["npm", "i", "-g", "@agentclientprotocol/claude-agent-acp@0.85.1"]


def _adapter(tmp: Path, version: str) -> Path:
    """A `claude-agent-acp` as pnpm and mise install it: a wrapper script that answers --version."""
    bindir = tmp / "npm" / "bin"
    bindir.mkdir(parents=True)
    entry = bindir / "claude-agent-acp"
    entry.write_text(f'#!/bin/sh\n[ "$1" = --version ] && echo {version}\nexit 0\n')
    entry.chmod(0o755)
    return bindir


@pytest.fixture
def build_env(monkeypatch, tmp_path):
    """`build` with the image build stubbed, a terminal on stdin, and every command recorded."""
    monkeypatch.setattr(launcher, "_build_stack", lambda *a, **k: None)
    monkeypatch.setattr(launcher, "_ensure_local_catalog_links", lambda: None)
    monkeypatch.setattr(launcher, "_ensure_docs_wiki_clone", lambda: None)
    monkeypatch.setattr(launcher, "_write_global_launchers", lambda *a, **k: True)
    patch_all(monkeypatch, "_runtime", lambda: "podman")
    monkeypatch.setattr(launcher, "_can_prompt", lambda: True)
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    ran: list = []
    state = {"rc": 0}
    real_run = subprocess.run

    def fake_run(cmd, *a, **k):
        if cmd[1:] == ["--version"]:  # the detection asks the fake adapter for real
            return real_run(cmd, *a, **k)
        ran.append(cmd)
        return subprocess.CompletedProcess(cmd, state["rc"])

    monkeypatch.setattr(launcher.subprocess, "run", fake_run)
    return ran, state


class TestTheOffer:
    @pytest.mark.parametrize("installed", [None, "0.84.0"])
    def test_s6_1_a_missing_or_other_version_asks_exactly(self, build_env, monkeypatch, tmp_path, installed):
        if installed:
            monkeypatch.setenv("PATH", str(_adapter(tmp_path, installed)))
        result = runner.invoke(launcher.app, ["build", "s", "claude"], input="n\n")
        assert result.exit_code == 0, result.output
        assert _QUESTION in result.output

    def test_s6_2_yes_runs_the_npm_install(self, build_env):
        ran, _ = build_env
        result = runner.invoke(launcher.app, ["build", "s", "claude"], input="y\n")
        assert result.exit_code == 0, result.output
        assert ran == [_NPM]

    def test_s6_3_c_runs_the_typed_command_through_bash(self, build_env):
        ran, _ = build_env
        typed = "pnpm add -g @agentclientprotocol/claude-agent-acp@0.85.1"
        result = runner.invoke(launcher.app, ["build", "s", "claude"], input=f"c\n{typed}\n")
        assert result.exit_code == 0, result.output
        assert ran == [["bash", "-c", typed]]

    def test_s6_4_no_runs_nothing_and_builds_on(self, build_env):
        ran, _ = build_env
        result = runner.invoke(launcher.app, ["build", "s", "claude"], input="n\n")
        assert result.exit_code == 0, result.output
        assert ran == []

    def test_s6_5_the_pinned_version_asks_nothing(self, build_env, monkeypatch, tmp_path):
        ran, _ = build_env
        monkeypatch.setenv("PATH", str(_adapter(tmp_path, "0.85.1")))
        result = runner.invoke(launcher.app, ["build", "s", "claude"], input="")
        assert result.exit_code == 0, result.output
        assert "to support ACP" not in result.output
        assert ran == []

    def test_s6_6_a_failed_install_warns_and_builds_on(self, build_env):
        _, state = build_env
        state["rc"] = 7
        result = runner.invoke(launcher.app, ["build", "s", "claude"], input="y\n")
        assert result.exit_code == 0, result.output
        assert "npm i -g @agentclientprotocol/claude-agent-acp@0.85.1" in result.output
        assert "warning" in result.output.lower()

    def test_s6_7_no_terminal_asks_nothing_and_names_the_command(self, build_env, monkeypatch):
        ran, _ = build_env
        monkeypatch.setattr(launcher, "_can_prompt", lambda: False)
        result = runner.invoke(launcher.app, ["build", "s", "claude"], input="")
        assert result.exit_code == 0, result.output
        assert "is that OK?" not in result.output
        assert "npm i -g @agentclientprotocol/claude-agent-acp@0.85.1" in result.output
        assert ran == []

    def test_s6_9_omp_never_checks_the_adapter(self, build_env, monkeypatch):
        monkeypatch.setattr(
            launcher, "_installed_acp_adapter", lambda *a: pytest.fail("omp has no adapter")
        )
        result = runner.invoke(launcher.app, ["build", "s", "omp"], input="")
        assert result.exit_code == 0, result.output
        assert "to support ACP" not in result.output
