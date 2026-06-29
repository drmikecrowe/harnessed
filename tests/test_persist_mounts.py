"""T6 — persist mount emission (fast) + round-trip / isolation (podman-gated).

Two layers, mirroring tests/test_recipes_integration.py:

1. FAST (no podman): the `_persist_mounts` glue — the `-v` args harnessed emits, the
   per-(recipe, project) isolation invariant at the mount level, and the global allowlist
   gate. Runs in default CI.
2. PODMAN-gated (HARNESSED_PODMAN=1): the invariant persist exists to guarantee — a
   project-scoped folder survives a `--fresh` relaunch, and project A's data never reaches
   project B. Reuses the capability headless launcher. The sentinel is written via
   `podman exec` (auth-free — never drives the agent), keeping the oracle's auth-free property.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from harnessed import launcher, paths
from harnessed.persist import PersistNotAllowlistedError
from harnessed.schema import PersistSpec, Recipe


def _recipe(name: str, project=None, global_dirs=None) -> Recipe:
    return Recipe(name=name, persist=PersistSpec(project=project or [], global_dirs=global_dirs or []))


def _patch_recipes(monkeypatch, recipes) -> None:
    monkeypatch.setattr(launcher, "load_stack_with_recipes", lambda root, stack: (None, recipes))


# --- Layer 1: mount emission (fast, no podman) ----------------------------------------------------


class TestPersistMountsProject:
    def test_project_entry_emits_rw_mount_and_creates_dir(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        _patch_recipes(monkeypatch, [_recipe("context-mode", project=[".context-mode"])])
        args = launcher._persist_mounts("claude_context-mode", Path("/home/user/proj"))
        host = paths.persist_project_dir("context-mode", "/home/user/proj", ".context-mode")
        assert args == ["-v", f"{host}:/home/harnessed/.context-mode:rw"]
        assert host.is_dir()  # harnessed created it

    def test_two_projects_isolated_at_mount_level(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        _patch_recipes(monkeypatch, [_recipe("context-mode", project=[".context-mode"])])
        a_src = launcher._persist_mounts("s", Path("/home/user/proj-a"))[1].split(":")[0]
        _patch_recipes(monkeypatch, [_recipe("context-mode", project=[".context-mode"])])
        b_src = launcher._persist_mounts("s", Path("/home/user/proj-b"))[1].split(":")[0]
        assert a_src != b_src, "two projects must map to different host persist dirs"

    def test_two_recipes_same_name_dont_collide(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        _patch_recipes(monkeypatch, [_recipe("rcp-a", project=["cache"]), _recipe("rcp-b", project=["cache"])])
        srcs = [a.split(":")[0] for a in launcher._persist_mounts("s", Path("/home/user/proj")) if a != "-v"]
        assert len(srcs) == 2 and srcs[0] != srcs[1]


class TestPersistMountsGlobal:
    def test_unlisted_global_is_denied(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))  # no allowlist file → default-deny
        target = tmp_path / "brain"
        target.mkdir()
        _patch_recipes(monkeypatch, [_recipe("brain", global_dirs=[str(target)])])
        with pytest.raises(PersistNotAllowlistedError):
            launcher._persist_mounts("s", Path("/home/user/proj"))

    def test_allowlisted_global_mounts_path_preserving(self, monkeypatch, tmp_path):
        cfg = tmp_path / "cfg"
        (cfg / "harnessed").mkdir(parents=True)
        target = tmp_path / "brain"
        target.mkdir()
        monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
        (cfg / "harnessed" / "persist-allowlist").write_text(f"{target}\n")
        _patch_recipes(monkeypatch, [_recipe("brain", global_dirs=[str(target)])])
        args = launcher._persist_mounts("s", Path("/home/user/proj"))
        real = os.path.realpath(target)
        assert args == ["-v", f"{real}:{real}:rw"], "global mounts path-preserving (host==container)"


# --- Layer 2: live round-trip + isolation (podman-gated) ------------------------------------------

_PODMAN = os.environ.get("HARNESSED_PODMAN") == "1"
podman = pytest.mark.skipif(not _PODMAN, reason="set HARNESSED_PODMAN=1 for live persist round-trip")
_ROOT = Path(__file__).resolve().parents[1]
_STACK = "claude_context-mode"


def _build_context_mode() -> None:
    bin_path = Path(sys.executable).parent / "harnessed"
    r = subprocess.run(
        [str(bin_path), "build", _STACK], cwd=str(_ROOT), capture_output=True, text=True, timeout=600
    )
    assert r.returncode == 0, f"build {_STACK} failed:\n{r.stderr}"


@podman
def test_live_sentinel_survives_fresh_relaunch(tmp_path):
    """A marker the tool writes to ~/.context-mode survives a `--fresh` relaunch of the SAME project."""
    from harnessed import capability

    _build_context_mode()
    proj = tmp_path / "projA"
    proj.mkdir()

    inst = capability.launch_headless(_ROOT, _STACK, project_path=str(proj))
    try:
        capability._exec(inst, "mkdir -p ~/.context-mode && echo SENTINEL-T6 > ~/.context-mode/marker")
    finally:
        capability.teardown(inst)

    inst2 = capability.launch_headless(_ROOT, _STACK, project_path=str(proj))  # --fresh, same project hash
    try:
        out = capability._exec(inst2, "cat ~/.context-mode/marker 2>/dev/null")
    finally:
        capability.teardown(inst2)
    assert "SENTINEL-T6" in out, "persisted marker did not survive the --fresh relaunch"


@podman
def test_live_data_does_not_bleed_across_projects(tmp_path):
    """A marker written in project A must NOT be visible to project B (per-project isolation)."""
    from harnessed import capability

    _build_context_mode()
    proj_a = tmp_path / "projA"
    proj_a.mkdir()
    proj_b = tmp_path / "projB"
    proj_b.mkdir()

    inst_a = capability.launch_headless(_ROOT, _STACK, project_path=str(proj_a))
    try:
        capability._exec(inst_a, "mkdir -p ~/.context-mode && echo ONLY-A > ~/.context-mode/marker")
    finally:
        capability.teardown(inst_a)

    inst_b = capability.launch_headless(_ROOT, _STACK, project_path=str(proj_b))
    try:
        out = capability._exec(inst_b, "cat ~/.context-mode/marker 2>/dev/null || echo ABSENT")
    finally:
        capability.teardown(inst_b)
    assert "ONLY-A" not in out, "project A's persisted data bled into project B"
