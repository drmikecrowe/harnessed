"""ACP terminal login: `host-acp`/`container-acp … --cli <args>` runs the claude CLI.

claude-agent-acp advertises its logins as ACP `terminal` auth methods with args such as
`["--cli", "auth", "login", "--claudeai"]`, and an editor (Zed) runs the agent's own command with
those appended. Through a launcher that is `harnessed host-acp claude --stack S --cli auth login
--claudeai`, which Typer used to reject with `No such option: --cli` before the login ever ran.

Driven through `main()` in a subprocess, because the split happens there before Typer parses. The
`claude` on PATH is a stub that records its argv and config dir.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from harnessed import launcher

_DRIVER = r"""
import sys
from harnessed import launcher as L
def _never(*a, **k):
    raise SystemExit("assemble must not run")
L.assemble = _never
sys.argv[0] = "harnessed"
L.main()
"""

_STUB_CLAUDE = """#!/bin/sh
python3 -c 'import json, os, sys; json.dump({"argv": sys.argv[1:], "config": os.environ.get("CLAUDE_CONFIG_DIR")}, open(os.environ["LOGIN_RECORD"], "w"))' "$@"
echo LOGIN-OUT
"""


@pytest.fixture
def env(tmp_path) -> dict[str, str]:
    e = dict(os.environ)
    for var, sub in (("HOME", "home"), ("XDG_DATA_HOME", "data"), ("XDG_CONFIG_HOME", "config"),
                     ("XDG_STATE_HOME", "state"), ("XDG_CACHE_HOME", "cache")):
        (tmp_path / sub).mkdir()
        e[var] = str(tmp_path / sub)
    e.pop("HARNESSED_DIR", None)
    # Set as an inherited stack session would set it: container-acp must not log in there.
    e["CLAUDE_CONFIG_DIR"] = str(tmp_path / "parent-stack")
    stacks = tmp_path / "config" / "harnessed" / "catalog" / "stacks"
    for name, extra in (("shared", ""), ("client", "isolated_auth: true\n")):
        (stacks / name).mkdir(parents=True)
        (stacks / name / "stack.yaml").write_text(
            f"name: {name}\ninstructions: login test.\nrecipes: [greet]\nservices: []\n{extra}"
        )
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "claude").write_text(_STUB_CLAUDE)
    (bindir / "claude").chmod(0o755)
    e["PATH"] = f"{bindir}{os.pathsep}{e['PATH']}"
    e["LOGIN_RECORD"] = str(tmp_path / "login.json")
    return e


def _run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", _DRIVER, *args], capture_output=True, env=env, timeout=60,
    )


def _record(env: dict[str, str]) -> dict:
    return json.loads(Path(env["LOGIN_RECORD"]).read_text())


class TestSplit:
    def test_everything_after_cli_is_claudes(self):
        head = launcher._extract_acp_cli(
            ["host-acp", "claude", "--stack", "s", "--cli", "auth", "login", "--", "--x"])
        assert head == ["host-acp", "claude", "--stack", "s"]
        assert launcher._acp_cli == ["auth", "login", "--", "--x"]

    def test_a_bare_cli_is_an_empty_login_argv(self):
        # Not an error: the adapter's `claude-login` method sends exactly `["--cli"]` — an
        # interactive claude in which the user runs /login.
        launcher._extract_acp_cli(["container-acp", "claude", "--stack", "s", "--cli"])
        assert launcher._acp_cli == []

    def test_a_bare_cli_runs_an_interactive_claude(self, env):
        proc = _run(env, "host-acp", "claude", "--stack", "shared", "--cli")
        assert proc.returncode == 0, proc.stderr.decode()
        assert _record(env)["argv"] == []

    def test_a_cli_after_the_passthrough_marker_is_the_agents(self):
        argv = ["container-acp", "claude", "--stack", "s", "--", "--cli", "auth"]
        assert launcher._extract_acp_cli(argv) == argv
        assert launcher._acp_cli is None

    @pytest.mark.parametrize("verb", ["host-run", "container-run", "container-exec"])
    def test_other_verbs_are_untouched(self, verb):
        argv = [verb, "claude", "--", "--cli"]
        assert launcher._extract_acp_cli(argv) == argv
        assert launcher._acp_cli is None


class TestHostAcp:
    def test_runs_claude_with_the_args_against_the_stack_home(self, env):
        proc = _run(env, "host-acp", "claude", "--stack", "shared", "--cli", "auth", "login", "--claudeai")
        assert proc.returncode == 0, proc.stderr.decode()
        rec = _record(env)
        assert rec["argv"] == ["auth", "login", "--claudeai"]
        assert rec["config"] == str(Path(env["XDG_DATA_HOME"]) / "harnessed" / "home" / "shared" / "claude")
        # The editor shows this in a terminal: claude's output is not diverted to stderr.
        assert b"LOGIN-OUT" in proc.stdout

    def test_a_missing_claude_is_an_error_not_a_traceback(self, env, tmp_path):
        (tmp_path / "bin" / "claude").unlink()
        env["PATH"] = str(tmp_path / "bin")
        proc = _run(env, "host-acp", "claude", "--stack", "shared", "--cli", "auth", "login")
        assert proc.returncode == 127
        assert b"cannot run claude" in proc.stderr
        assert b"Traceback" not in proc.stderr

    def test_a_harness_without_the_claude_cli_is_refused(self, env):
        proc = _run(env, "host-acp", "omp", "--stack", "shared", "--cli", "auth", "login")
        assert proc.returncode == 2
        assert b"omp has none" in proc.stderr
        assert not Path(env["LOGIN_RECORD"]).exists()


class TestContainerAcp:
    def test_runs_claude_against_the_users_own_config(self, env):
        proc = _run(env, "container-acp", "claude", "--stack", "shared", "--cli", "auth", "login", "--console")
        assert proc.returncode == 0, proc.stderr.decode()
        rec = _record(env)
        assert rec["argv"] == ["auth", "login", "--console"]
        assert rec["config"] is None, "an inherited stack config dir must not receive the login"

    def test_an_isolated_auth_stack_is_told_where_to_log_in(self, env):
        proc = _run(env, "container-acp", "claude", "--stack", "client", "--cli", "auth", "login")
        assert proc.returncode == 1
        assert b"isolated_auth" in proc.stderr
        assert b"container-run claude <project> --stack client" in proc.stderr
        assert not Path(env["LOGIN_RECORD"]).exists()
