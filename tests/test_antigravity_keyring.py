"""Tests for the antigravity in-pod keyring (bd main-ec5).

agy persists its Google-OAuth token to the Secret Service keyring, but the isolated container has no
keyring daemon. The launcher (1) starts dbus + gnome-keyring in the attach shell so agy inherits the
keyring env, (2) persists the keyring store via a per-instance rw host mount so the token survives
recreates, and (3) wipes that store on --fresh so a fresh login is forced. All three are
antigravity-gated; every other harness is unaffected.
"""

from pathlib import Path

import pytest

from harnessed import launcher, paths
from harnessed.schema import Stack
from support import patch_all

CONTAINER_HOME = launcher._CONTAINER_HOME_STR


def _state_home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


class TestKeyringInitPrefix:
    """The attach shell that execs the harness carries the keyring-init prefix for antigravity only."""

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
                             stack="s", mount_path=tmp_path, shell=False)
        return captured["argv"][-1]

    def test_antigravity_attach_has_keyring_init(self, tmp_path, monkeypatch):
        shell_cmd = self._shell_cmd(monkeypatch, tmp_path, "antigravity")
        assert "dbus-launch" in shell_cmd
        assert "gnome-keyring-daemon" in shell_cmd
        # Keyring init runs BEFORE the agy exec, so agy inherits the keyring env.
        assert shell_cmd.index("gnome-keyring-daemon") < shell_cmd.index("agy")

    def test_claude_attach_has_no_keyring_init(self, tmp_path, monkeypatch):
        shell_cmd = self._shell_cmd(monkeypatch, tmp_path, "claude")
        assert "dbus-launch" not in shell_cmd
        assert "gnome-keyring-daemon" not in shell_cmd

    def test_codex_attach_has_no_keyring_init(self, tmp_path, monkeypatch):
        shell_cmd = self._shell_cmd(monkeypatch, tmp_path, "codex")
        assert "gnome-keyring-daemon" not in shell_cmd


class TestKeyringStateMount:
    """The keyring store is a per-instance rw host mount, emitted for antigravity only."""

    def test_antigravity_mount_is_rw_per_instance(self, monkeypatch, tmp_path):
        _state_home(monkeypatch, tmp_path)
        mount = launcher._keyring_state_mount("antigravity", "inst-a")
        assert mount[0] == "-v"
        assert mount[1].endswith(f":{CONTAINER_HOME}/.local/share/keyrings:rw")
        expected = tmp_path / "state" / "harnessed" / "inst-a" / "keyrings"
        assert mount[1].split(":")[0] == str(expected)
        assert expected.is_dir()  # created so the bind mount has a source

    def test_non_antigravity_gets_no_mount(self, monkeypatch, tmp_path):
        _state_home(monkeypatch, tmp_path)
        assert launcher._keyring_state_mount("claude", "inst-b") == []
        assert launcher._keyring_state_mount("codex", "inst-b") == []


class TestKeyringFreshWipe:
    """--fresh removes the persisted keyring dir (antigravity only); a normal recreate keeps it."""

    def test_fresh_removes_antigravity_keyring_dir(self, monkeypatch, tmp_path):
        _state_home(monkeypatch, tmp_path)
        kdir = tmp_path / "state" / "harnessed" / "inst-c" / "keyrings"
        kdir.mkdir(parents=True)
        (kdir / "login.keyring").write_text("token")
        launcher._keyring_fresh_wipe("antigravity", "inst-c")
        assert not kdir.exists()

    def test_fresh_noop_for_non_antigravity(self, monkeypatch, tmp_path):
        _state_home(monkeypatch, tmp_path)
        kdir = tmp_path / "state" / "harnessed" / "inst-d" / "keyrings"
        kdir.mkdir(parents=True)
        launcher._keyring_fresh_wipe("claude", "inst-d")
        assert kdir.exists()  # untouched

    def test_fresh_missing_dir_is_safe(self, monkeypatch, tmp_path):
        _state_home(monkeypatch, tmp_path)
        # No dir created — ignore_errors means this must not raise.
        launcher._keyring_fresh_wipe("antigravity", "inst-none")
