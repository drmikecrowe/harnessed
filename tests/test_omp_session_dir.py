"""Tests for omp's pinned session dir.

omp keys a folder's session dir off the cwd *relative to $HOME*. The pod's $HOME is /home/harnessed
while the agent's cwd is the mirrored HOST path, so omp escaped the key and wrote sessions the host
never reads ("No sessions in current folder" in `/resume`). The launcher recomputes the key against
the HOST home and pins it with `--session-dir`. Only omp is affected.
"""

from pathlib import Path

import pytest

from harnessed import launcher, paths
from harnessed.schema import Stack
from support import patch_all

CONTAINER_HOME = launcher._CONTAINER_HOME_STR


class TestOmpAttachCmd:
    def test_session_dir_is_keyed_off_the_host_home(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: Path("/home/u"))
        cmd = launcher._omp_attach_cmd(Path("/home/u/Programming/Personal/proj"))
        assert cmd == (
            f"omp --session-dir '{CONTAINER_HOME}/.omp/agent/sessions/"
            "-Programming-Personal-proj'"
        )

    def test_start_dir_outside_the_host_home_keeps_the_full_path(self, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: Path("/home/u"))
        cmd = launcher._omp_attach_cmd(Path("/srv/proj"))
        assert f"{CONTAINER_HOME}/.omp/agent/sessions/-srv-proj'" in cmd

    def test_start_dir_at_the_host_home_is_left_alone(self, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: Path("/home/u"))
        assert launcher._omp_attach_cmd(Path("/home/u")) == "omp"


class TestAttachShell:
    """The attach shell execs omp with the pinned dir; other harnesses are untouched."""

    def _shell_cmd(self, monkeypatch, tmp_path, harness: str) -> str:
        stk = Stack(name="s", recipes=[])
        patch_all(monkeypatch, "load_stack_with_recipes", lambda root, stack: (stk, []))
        monkeypatch.setattr(paths, "git_common_dir", lambda p: None)

        captured: dict = {}

        def fake_execvp(rt, argv):
            captured["argv"] = argv
            raise SystemExit(0)

        monkeypatch.setattr(launcher.os, "execvp", fake_execvp)
        monkeypatch.setattr(launcher, "_touch_attach_marker", lambda inst: None)

        proj = tmp_path / "proj"
        proj.mkdir()
        with pytest.raises(SystemExit):
            launcher._attach("podman", harness, "inst", proj,
                             stack="s", mount_path=tmp_path, shell=False, start_dir=proj)
        return captured["argv"][-1]

    def test_omp_attach_pins_the_session_dir(self, tmp_path, monkeypatch):
        shell_cmd = self._shell_cmd(monkeypatch, tmp_path, "omp")
        assert f"omp --session-dir '{CONTAINER_HOME}/.omp/agent/sessions/" in shell_cmd

    def test_claude_attach_has_no_session_dir(self, tmp_path, monkeypatch):
        shell_cmd = self._shell_cmd(monkeypatch, tmp_path, "claude")
        assert "--session-dir" not in shell_cmd
