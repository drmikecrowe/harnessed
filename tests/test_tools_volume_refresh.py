"""A rebuilt image must reach an EXISTING tools volume.

Copy-up seeds `~/.local` once, and the harness binary lives there, so before this the agent kept
running the harness from its first launch: image 2.1.284, running claude 2.1.223.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from harnessed import paths, volumes

_TOOLS_VOL = "harnessed-tools-claude-s"


def _drive(monkeypatch, *, volume_exists: bool, fingerprint_moved: bool, cp_rc: int = 0):
    """Run `_ensure_stack_volumes` with every runtime call recorded, in order."""
    events: list = []
    said: list[str] = []

    def fake_run(cmd, *a, **k):
        cmd = list(cmd)
        events.append(cmd)
        rc = 0
        if cmd[1:3] == ["volume", "inspect"]:
            rc = 0 if volume_exists else 1
        elif "cp" in cmd:
            rc = cp_rc
        return subprocess.CompletedProcess(cmd, rc, stdout="", stderr="cp: boom" if rc else "")

    monkeypatch.setattr(volumes, "_run", fake_run)
    monkeypatch.setattr(volumes, "_say", said.append)
    monkeypatch.setattr(volumes, "_ensure_config_volume", lambda *a, **k: "cfgvol")
    monkeypatch.setattr(volumes, "_run_container_installs",
                        lambda *a, **k: events.append("INSTALLS"))
    monkeypatch.setattr(volumes, "_container_stack_fingerprint", lambda *a, **k: "fp")
    monkeypatch.setattr(volumes, "_volume_read",
                        lambda *a, **k: "stale" if fingerprint_moved else "fp")

    # `prof` only reaches `_ensure_config_volume`, which is stubbed above.
    volumes._ensure_stack_volumes("docker", "s", "claude", Path("prof"), "img", [])
    refreshes = [e for e in events if isinstance(e, list) and "cp" in e]
    return events, refreshes, said


def test_an_existing_volume_is_refreshed_from_the_image_before_the_installs(monkeypatch):
    events, refreshes, _ = _drive(monkeypatch, volume_exists=True, fingerprint_moved=True)

    assert len(refreshes) == 1, "a moved fingerprint on an existing volume must refresh it once"
    cmd = refreshes[0]
    # The volume sits beside ~/.local, never on it: mounted AT ~/.local it would hide the source.
    assert f"{_TOOLS_VOL}:{volumes._CTR_TOOLS_REFRESH_DIR}" in cmd
    # `--entrypoint cp <image> <args>`: the image comes between the entrypoint and its arguments.
    ep = cmd.index("--entrypoint")
    assert cmd[ep + 1:ep + 3] == ["cp", "img"], "must copy out of the stack's own image"
    assert cmd[ep + 3:] == [
        "-au", f"{volumes._CONTAINER_HOME_STR}/.local/.", f"{volumes._CTR_TOOLS_REFRESH_DIR}/",
    ]
    # Same identity as every other writer into the volume, or the agent cannot rewrite the files.
    for arg in [*paths.userns_args("docker"), *paths.container_user_args("docker")]:
        assert arg in cmd
    assert events.index(refreshes[0]) < events.index("INSTALLS"), \
        "installs must run against the refreshed tools, not the stale ones"


def test_a_volume_created_by_this_call_is_not_refreshed(monkeypatch):
    # Copy-up has just seeded it from this very image; a second copy is pure cost.
    _, refreshes, _ = _drive(monkeypatch, volume_exists=False, fingerprint_moved=True)
    assert refreshes == []


def test_an_unchanged_stack_is_not_refreshed(monkeypatch):
    # The fingerprint carries the image ID, so "unchanged" already means "same image".
    _, refreshes, _ = _drive(monkeypatch, volume_exists=True, fingerprint_moved=False)
    assert refreshes == []


@pytest.mark.parametrize("cp_rc, warned", [(0, False), (1, True)])
def test_a_failed_refresh_is_reported_not_silent(monkeypatch, cp_rc, warned):
    events, _, said = _drive(monkeypatch, volume_exists=True, fingerprint_moved=True, cp_rc=cp_rc)
    hits = [m for m in said if _TOOLS_VOL in m and "older harness" in m]
    assert bool(hits) is warned
    if warned:
        assert "cp: boom" in hits[0], "the runtime's own error must reach the user"
    assert "INSTALLS" in events, "a failed refresh must not abort the launch"
