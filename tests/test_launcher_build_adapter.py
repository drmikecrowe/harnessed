"""GH-571 AC-6 — `build <stack> claude` offers to install the pinned claude-agent-acp adapter.

The adapter is what `host-acp claude` runs. Its pin lives in `catalog/agents/claude/agent.yaml`
(`build_args.CLAUDE_AGENT_ACP_VERSION`), and "installed" means the `claude-agent-acp` on PATH
prints that version for `--version` (SPEC revision 5). The fake adapter is a real executable, so
the detection runs for real; only the install command and the image build are stubbed.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from harnessed import launcher
from support import patch_all

runner = CliRunner()

# Read from the catalog as the code reads it: a pin bump must never fail these tests (#595 failed
# six of them on a literal 0.85.1).
_PACKAGE, _PIN = launcher._acp_adapter_pin()
# GH-604: pnpm is the default; mise's own command when mise owns the adapter on PATH.
_PNPM = ["pnpm", "add", "-g", f"{_PACKAGE}@{_PIN}"]
_MISE = ["mise", "use", "-g", f"npm:{_PACKAGE}@{_PIN}"]
_INSTALL = " ".join(_PNPM)
_MISE_INSTALL = " ".join(_MISE)
_QUESTION = f"I need to install `{_INSTALL}` to support ACP -- is that OK? (y/n/c)"
_MISE_BIN = Path("installs/npm-agentclientprotocol-claude-agent-acp/0.85.1/bin")


def _stub(bindir: Path, version: str) -> Path:
    """A `claude-agent-acp` as pnpm and mise install it: a wrapper script that answers --version."""
    bindir.mkdir(parents=True, exist_ok=True)
    entry = bindir / "claude-agent-acp"
    entry.write_text(f'#!/bin/sh\n[ "$1" = --version ] && echo {version}\nexit 0\n')
    entry.chmod(0o755)
    return bindir


def _adapter(tmp: Path, version: str) -> Path:
    return _stub(tmp / "npm" / "bin", version)


def _pnpm(bindir: Path, prints: Path, rc: int = 0, log: Path | None = None) -> Path:
    """A `pnpm` whose `pnpm bin -g` prints `prints` and exits `rc`; `log` records each call."""
    bindir.mkdir(parents=True, exist_ok=True)
    entry = bindir / "pnpm"
    record = f'echo "$@" >> {log}\n' if log else ""
    entry.write_text(f'#!/bin/sh\n{record}[ "$1 $2" = "bin -g" ] && echo {prints}\nexit {rc}\n')
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
    monkeypatch.setenv("MISE_DATA_DIR", str(tmp_path / "mise"))
    ran: list = []
    state: dict = {"rc": 0, "calls": [], "on_install": None}
    real_run = subprocess.run

    def fake_run(cmd, *a, **k):
        state["calls"].append(list(cmd))
        # The detection asks the fake adapter, and the fake pnpm, for real.
        if cmd[1:] in (["--version"], ["bin", "-g"]):
            return real_run(cmd, *a, **k)
        ran.append(cmd)
        if state["rc"] == 0 and state["on_install"]:
            state["on_install"]()
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

    def test_s6_2_yes_runs_the_install(self, build_env):
        ran, _ = build_env
        result = runner.invoke(launcher.app, ["build", "s", "claude"], input="y\n")
        assert result.exit_code == 0, result.output
        assert ran == [_PNPM]

    def test_s6_3_c_runs_the_typed_command_through_bash(self, build_env):
        ran, _ = build_env
        typed = f"pnpm add -g {_PACKAGE}@{_PIN}"
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
        monkeypatch.setenv("PATH", str(_adapter(tmp_path, _PIN)))
        result = runner.invoke(launcher.app, ["build", "s", "claude"], input="")
        assert result.exit_code == 0, result.output
        assert "to support ACP" not in result.output
        assert ran == []

    def test_s6_6_a_failed_install_warns_and_builds_on(self, build_env):
        _, state = build_env
        state["rc"] = 7
        result = runner.invoke(launcher.app, ["build", "s", "claude"], input="y\n")
        assert result.exit_code == 0, result.output
        assert _INSTALL in result.output
        assert "warning" in result.output.lower()

    def test_s6_7_no_terminal_asks_nothing_and_names_the_command(self, build_env, monkeypatch):
        ran, _ = build_env
        monkeypatch.setattr(launcher, "_can_prompt", lambda: False)
        result = runner.invoke(launcher.app, ["build", "s", "claude"], input="")
        assert result.exit_code == 0, result.output
        assert "is that OK?" not in result.output
        assert _INSTALL in result.output
        assert ran == []

    def test_s6_9_omp_never_checks_the_adapter(self, build_env, monkeypatch):
        monkeypatch.setattr(
            launcher, "_installed_acp_adapter", lambda *a: pytest.fail("omp has no adapter")
        )
        result = runner.invoke(launcher.app, ["build", "s", "omp"], input="")
        assert result.exit_code == 0, result.output
        assert "to support ACP" not in result.output


# GH-604 — the offer names the install command of the tool that owns the adapter on PATH.


def _setup(kind: str, tmp: Path, monkeypatch) -> tuple[list[str], Path | None]:
    """Put the adapter where `kind` says, first on PATH; return the expected command and the stub dir."""
    if kind == "mise":
        bindir = _stub(tmp / "mise" / _MISE_BIN, "0.85.1")
    elif kind == "shim":
        bindir = _stub(tmp / "mise" / "shims", "0.85.1")
    elif kind == "pnpm":
        bindir = _pnpm(_stub(tmp / "pnpm" / "bin", "0.85.1"), tmp / "pnpm" / "bin")
    elif kind == "other":
        bindir = _adapter(tmp, "0.85.1")
    else:
        return (_PNPM, None)
    monkeypatch.setenv("PATH", str(bindir))
    return (_MISE if kind in ("mise", "shim") else _PNPM), bindir


def _no_npm(text: str) -> bool:
    """S2.3: the words `npm`/`npx` appear nowhere except as the `npm:` prefix of the mise command's
    spec. Whole words: `pnpm` is the required command, not a mention of npm."""
    rest = text.replace(f"npm:{_PACKAGE}", "")
    return re.search(r"\bnp[mx]\b", rest) is None


class TestS1MiseGetsTheMiseCommand:
    def test_s1_1_a_mise_install_dir_gets_mise_use(self, build_env, monkeypatch, tmp_path):
        ran, _ = build_env
        _setup("mise", tmp_path, monkeypatch)
        result = runner.invoke(launcher.app, ["build", "s", "claude"], input="y\n")
        assert result.exit_code == 0, result.output
        assert f"`{_MISE_INSTALL}`" in result.output
        assert "npm i -g" not in result.output
        assert ran == [_MISE]

    def test_s1_3_a_mise_shim_gets_mise_use(self, build_env, monkeypatch, tmp_path):
        _setup("shim", tmp_path, monkeypatch)
        result = runner.invoke(launcher.app, ["build", "s", "claude"], input="n\n")
        assert result.exit_code == 0, result.output
        assert f"`{_MISE_INSTALL}`" in result.output

    def test_s1_4_mise_data_dir_defaults_under_xdg_data_home(self, build_env, monkeypatch, tmp_path):
        monkeypatch.delenv("MISE_DATA_DIR")
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setenv("PATH", str(_stub(tmp_path / "data" / "mise" / _MISE_BIN, "0.85.1")))
        result = runner.invoke(launcher.app, ["build", "s", "claude"], input="n\n")
        assert result.exit_code == 0, result.output
        assert f"`{_MISE_INSTALL}`" in result.output

    def test_s1_5_no_terminal_names_mise_use_and_runs_nothing(self, build_env, monkeypatch, tmp_path):
        ran, _ = build_env
        monkeypatch.setattr(launcher, "_can_prompt", lambda: False)
        _setup("mise", tmp_path, monkeypatch)
        result = runner.invoke(launcher.app, ["build", "s", "claude"], input="")
        assert result.exit_code == 0, result.output
        assert _MISE_INSTALL in result.output
        assert ran == []


class TestS2NoAdapterGetsPnpm:
    def test_s2_1_no_adapter_gets_pnpm_add(self, build_env):
        ran, _ = build_env
        result = runner.invoke(launcher.app, ["build", "s", "claude"], input="y\n")
        assert result.exit_code == 0, result.output
        assert f"`{_INSTALL}`" in result.output
        assert ran == [_PNPM]

    @pytest.mark.parametrize("kind", ["mise", "shim", "none", "pnpm", "other"])
    @pytest.mark.parametrize("terminal", [True, False])
    def test_s2_3_no_message_names_raw_npm(self, build_env, monkeypatch, tmp_path, kind, terminal):
        monkeypatch.setattr(launcher, "_can_prompt", lambda: terminal)
        _setup(kind, tmp_path, monkeypatch)
        result = runner.invoke(launcher.app, ["build", "s", "claude"], input="n\n")
        assert result.exit_code == 0, result.output
        assert _no_npm(result.output), result.output

    @pytest.mark.parametrize("kind", ["mise", "shim", "none", "pnpm", "other"])
    def test_s2_3_no_install_runs_npm_or_npx(self, build_env, monkeypatch, tmp_path, kind):
        ran, _ = build_env
        _setup(kind, tmp_path, monkeypatch)
        result = runner.invoke(launcher.app, ["build", "s", "claude"], input="y\n")
        assert result.exit_code == 0, result.output
        assert ran and all(cmd[0] not in ("npm", "npx") for cmd in ran)


class TestS3PnpmGetsPnpm:
    def test_s3_1_a_pnpm_global_bin_gets_pnpm_add(self, build_env, monkeypatch, tmp_path):
        _, bindir = _setup("pnpm", tmp_path, monkeypatch)
        assert bindir is not None
        result = runner.invoke(launcher.app, ["build", "s", "claude"], input="n\n")
        assert result.exit_code == 0, result.output
        assert f"`{_INSTALL}`" in result.output
        assert "mise" not in result.output and "npm i -g" not in result.output
        assert launcher._acp_adapter_owner(str(bindir / "claude-agent-acp")) == "pnpm"

    def test_s3_2_no_pnpm_on_path_is_unrecognised(self, build_env, monkeypatch, tmp_path):
        bindir = _stub(tmp_path / "pnpm" / "bin", "0.85.1")
        monkeypatch.setenv("PATH", str(bindir))
        result = runner.invoke(launcher.app, ["build", "s", "claude"], input="n\n")
        assert result.exit_code == 0, result.output
        assert f"`{_INSTALL}`" in result.output
        assert launcher._acp_adapter_owner(str(bindir / "claude-agent-acp")) == "other"

    def test_s3_3_a_failing_pnpm_bin_is_unrecognised(self, build_env, monkeypatch, tmp_path):
        bindir = _pnpm(_stub(tmp_path / "pnpm" / "bin", "0.85.1"), tmp_path / "pnpm" / "bin", rc=1)
        monkeypatch.setenv("PATH", str(bindir))
        result = runner.invoke(launcher.app, ["build", "s", "claude"], input="n\n")
        assert result.exit_code == 0, result.output
        assert f"`{_INSTALL}`" in result.output
        assert launcher._acp_adapter_owner(str(bindir / "claude-agent-acp")) == "other"

    def test_s3_3_b_notice_lines_around_the_dir_still_classify_pnpm(self, monkeypatch, tmp_path):
        bindir = _stub(tmp_path / "pnpm" / "bin", "0.85.1")
        noisy = bindir / "pnpm"
        noisy.write_text(f'#!/bin/sh\necho "Update available!"\necho {bindir}\necho "Run pnpm add -g pnpm"\n')
        noisy.chmod(0o755)
        monkeypatch.setenv("PATH", str(bindir))
        monkeypatch.setenv("MISE_DATA_DIR", str(tmp_path / "mise"))
        assert launcher._acp_adapter_owner(str(bindir / "claude-agent-acp")) == "pnpm"

    @pytest.mark.parametrize("kind", ["mise", "none"])
    def test_s3_4_mise_and_no_adapter_never_ask_pnpm(self, build_env, monkeypatch, tmp_path, kind):
        log = tmp_path / "pnpm-calls.log"
        pnpm_dir = _pnpm(tmp_path / "pnpm-only", tmp_path / "pnpm-only", log=log)
        _, bindir = _setup(kind, tmp_path, monkeypatch)
        path = f"{bindir}:{pnpm_dir}" if bindir else str(pnpm_dir)
        monkeypatch.setenv("PATH", path)
        result = runner.invoke(launcher.app, ["build", "s", "claude"], input="n\n")
        assert result.exit_code == 0, result.output
        assert not log.exists()


class TestS4UnrecognisedFallsBackToPnpm:
    def test_s4_1_an_unrecognised_dir_gets_pnpm_add(self, build_env, monkeypatch, tmp_path):
        _setup("other", tmp_path, monkeypatch)
        result = runner.invoke(launcher.app, ["build", "s", "claude"], input="n\n")
        assert result.exit_code == 0, result.output
        assert f"`{_INSTALL}`" in result.output


class TestS5TheVersionIsCheckedAgain:
    @pytest.mark.parametrize("kind", ["none", "pnpm", "other"])
    def test_s5_1_a_working_install_ends_the_offer(self, build_env, monkeypatch, tmp_path, kind):
        ran, state = build_env
        _, bindir = _setup(kind, tmp_path, monkeypatch)
        target = bindir or tmp_path / "empty-bin"
        state["on_install"] = lambda: _stub(target, _PIN)
        result = runner.invoke(launcher.app, ["build", "s", "claude"], input="y\n")
        assert result.exit_code == 0, result.output
        assert "warning" not in result.output.lower()
        again = runner.invoke(launcher.app, ["build", "s", "claude"], input="")
        assert again.exit_code == 0, again.output
        assert "to support ACP" not in again.output
        assert len(ran) == 1

    def test_s5_2_a_shadowing_copy_is_named_with_its_version(self, build_env, monkeypatch, tmp_path):
        bindir = _adapter(tmp_path, "0.80.0")
        monkeypatch.setenv("PATH", str(bindir))
        result = runner.invoke(launcher.app, ["build", "s", "claude"], input="y\n")
        assert result.exit_code == 0, result.output
        assert str(bindir / "claude-agent-acp") in result.output
        assert result.output.count("0.80.0") >= 1
        assert result.output.lower().count("warning") == 1

    def test_s5_3_the_mise_command_is_not_checked_again(self, build_env, monkeypatch, tmp_path):
        ran, state = build_env
        _setup("mise", tmp_path, monkeypatch)
        result = runner.invoke(launcher.app, ["build", "s", "claude"], input="y\n")
        assert result.exit_code == 0, result.output
        assert state["calls"][-1] == _MISE
        assert "warning" not in result.output.lower()
        pinned = tmp_path / "mise" / "installs" / "npm-agentclientprotocol-claude-agent-acp" / _PIN / "bin"
        monkeypatch.setenv("PATH", str(_stub(pinned, _PIN)))
        again = runner.invoke(launcher.app, ["build", "s", "claude"], input="")
        assert again.exit_code == 0, again.output
        assert "to support ACP" not in again.output
        assert ran == [_MISE]

    def test_s5_4_a_typed_command_is_checked_again(self, build_env, monkeypatch, tmp_path):
        bindir = _adapter(tmp_path, "0.85.1")
        monkeypatch.setenv("PATH", str(bindir))
        result = runner.invoke(launcher.app, ["build", "s", "claude"], input="c\ntrue\n")
        assert result.exit_code == 0, result.output
        assert str(bindir / "claude-agent-acp") in result.output
        assert result.output.lower().count("warning") == 1

    def test_s5_5_a_failed_install_is_not_checked_again(self, build_env, monkeypatch, tmp_path):
        _, state = build_env
        state["rc"] = 7
        bindir = _adapter(tmp_path, "0.85.1")
        monkeypatch.setenv("PATH", str(bindir))
        result = runner.invoke(launcher.app, ["build", "s", "claude"], input="y\n")
        assert result.exit_code == 0, result.output
        assert "the ACP adapter install failed (exit 7)" in result.output
        assert str(bindir / "claude-agent-acp") not in result.output
        assert result.output.lower().count("warning") == 1

    def test_s5_6_an_install_that_lands_off_path_says_so(self, build_env):
        result = runner.invoke(launcher.app, ["build", "s", "claude"], input="y\n")
        assert result.exit_code == 0, result.output
        assert "not on PATH" in result.output
        assert result.output.lower().count("warning") == 1
