"""T6 — persist mount emission (fast) + round-trip / isolation (podman-gated).

Two layers:

1. FAST (no podman): the `_persist_mounts` glue — the `-v` args harnessed emits, per-scope
   isolation invariants at the mount level, and the global allowlist gate. Runs in default CI.
2. PODMAN-gated (HARNESSED_PODMAN=1): the invariant persist exists to guarantee — a
   workspace-scoped folder survives a `--fresh` relaunch, and project A's data never reaches
   project B. Reuses the capability headless launcher.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from harnessed import launcher, paths
from harnessed.persist import PersistNotAllowlistedError
from harnessed.schema import PersistEntry, PersistSpec, Recipe


def _entry(**kw) -> PersistEntry:
    return PersistEntry(
        scope=kw.get("scope", "workspace"),
        location=kw.get("location", "host"),
        name=kw.get("name", None),
        path=kw.get("path", None),
        vcs=kw.get("vcs", None),
    )


def _recipe(name: str, entries=None) -> Recipe:
    return Recipe(name=name, persist=PersistSpec(entries=entries or []))


def _patch_recipes(monkeypatch, recipes) -> None:
    monkeypatch.setattr(launcher, "load_stack_with_recipes", lambda root, stack: (None, recipes))


# --- Layer 1: mount emission (fast, no podman) -----------------------------------------------


class TestPersistMountsWorkspaceHost:
    def test_workspace_entry_emits_rw_mount_and_creates_dir(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        _patch_recipes(monkeypatch, [_recipe("ctx", [_entry(scope="workspace", name=".ctx", location="host")])])
        args = launcher._persist_mounts("s", Path("/home/user/proj"))
        host = paths.persist_workspace_dir("ctx", "/home/user/proj", ".ctx")
        assert args == ["-v", f"{host}:/home/harnessed/.ctx:rw"]
        assert host.is_dir()

    def test_two_workspace_paths_isolated(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        e = _entry(scope="workspace", name=".ctx", location="host")
        _patch_recipes(monkeypatch, [_recipe("ctx", [e])])
        a = launcher._persist_mounts("s", Path("/home/user/proj-a"))[1].split(":")[0]
        _patch_recipes(monkeypatch, [_recipe("ctx", [e])])
        b = launcher._persist_mounts("s", Path("/home/user/proj-b"))[1].split(":")[0]
        assert a != b, "two workspace paths must map to different host persist dirs"

    def test_two_recipes_same_name_dont_collide(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        e = _entry(scope="workspace", name="cache", location="host")
        _patch_recipes(monkeypatch, [_recipe("rcp-a", [e]), _recipe("rcp-b", [e])])
        srcs = [a.split(":")[0] for a in launcher._persist_mounts("s", Path("/p")) if a != "-v"]
        assert len(srcs) == 2 and srcs[0] != srcs[1]


class TestPersistMountsProjectHost:
    def test_project_entry_uses_git_common_dir_hash(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        e = _entry(scope="project", name=".beads", location="host")
        _patch_recipes(monkeypatch, [_recipe("beads", [e])])
        fake_gcd = tmp_path / "fake_git_common"
        fake_gcd.mkdir()
        with patch.object(paths, "git_common_dir", return_value=fake_gcd):
            args = launcher._persist_mounts("s", Path("/home/user/proj"))
        host = paths.persist_workspace_dir("beads", str(fake_gcd), ".beads")
        assert args == ["-v", f"{host}:/home/harnessed/.beads:rw"]
        assert host.is_dir()

    def test_project_entry_same_key_across_two_worktrees(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        e = _entry(scope="project", name=".beads", location="host")
        fake_gcd = tmp_path / "git_common"
        fake_gcd.mkdir()
        _patch_recipes(monkeypatch, [_recipe("beads", [e])])
        with patch.object(paths, "git_common_dir", return_value=fake_gcd):
            a = launcher._persist_mounts("s", Path("/home/user/proj/main"))[1].split(":")[0]
        _patch_recipes(monkeypatch, [_recipe("beads", [e])])
        with patch.object(paths, "git_common_dir", return_value=fake_gcd):
            b = launcher._persist_mounts("s", Path("/home/user/proj/feature"))[1].split(":")[0]
        assert a == b, "project scope must produce the same host dir across all worktrees"

    def test_project_entry_falls_back_to_workspace_when_not_in_git(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        e = _entry(scope="project", name=".beads", location="host")
        _patch_recipes(monkeypatch, [_recipe("beads", [e])])
        proj = Path("/home/user/proj")
        with patch.object(paths, "git_common_dir", return_value=None):
            args = launcher._persist_mounts("s", proj)
        # Falls back to workspace hash
        host = paths.persist_workspace_dir("beads", str(proj), ".beads")
        assert args == ["-v", f"{host}:/home/harnessed/.beads:rw"]


class TestPersistMountsGlobal:
    def test_unlisted_global_is_denied(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        target = tmp_path / "brain"
        target.mkdir()
        _patch_recipes(monkeypatch, [_recipe("brain", [_entry(scope="global", path=str(target), location=None)])])
        with pytest.raises(PersistNotAllowlistedError):
            launcher._persist_mounts("s", Path("/home/user/proj"))

    def test_allowlisted_global_mounts_path_preserving(self, monkeypatch, tmp_path):
        cfg = tmp_path / "cfg"
        (cfg / "harnessed").mkdir(parents=True)
        target = tmp_path / "brain"
        target.mkdir()
        monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
        (cfg / "harnessed" / "persist-allowlist").write_text(f"{target}\n")
        _patch_recipes(monkeypatch, [_recipe("brain", [_entry(scope="global", path=str(target), location=None)])])
        args = launcher._persist_mounts("s", Path("/home/user/proj"))
        real = os.path.realpath(target)
        assert args == ["-v", f"{real}:{real}:rw"]


class TestPersistMountsInRepo:
    def test_in_repo_tracked_produces_no_mount_args(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        e = _entry(scope="workspace", name="notes.md", location="in_repo", vcs="tracked")
        _patch_recipes(monkeypatch, [_recipe("notes", [e])])
        args = launcher._persist_mounts("s", Path("/home/user/proj"))
        assert args == []

    def test_in_repo_ignored_appends_gitignore(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        proj = tmp_path / "myproj"
        proj.mkdir()
        e = _entry(scope="workspace", name=".scratch", location="in_repo", vcs="ignored")
        _patch_recipes(monkeypatch, [_recipe("tool", [e])])
        # Simulate being inside a git repo
        with patch.object(paths, "git_common_dir", return_value=tmp_path / ".git"):
            launcher._persist_mounts("s", proj)
        gitignore = proj / ".gitignore"
        assert gitignore.exists()
        assert ".scratch" in gitignore.read_text()

    def test_in_repo_ignored_gitignore_idempotent(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        proj = tmp_path / "myproj"
        proj.mkdir()
        (proj / ".gitignore").write_text(".scratch\n")
        e = _entry(scope="workspace", name=".scratch", location="in_repo", vcs="ignored")
        _patch_recipes(monkeypatch, [_recipe("tool", [e])])
        with patch.object(paths, "git_common_dir", return_value=tmp_path / ".git"):
            launcher._persist_mounts("s", proj)
        # Should appear exactly once
        lines = (proj / ".gitignore").read_text().splitlines()
        assert lines.count(".scratch") == 1

    def test_in_repo_ignored_skips_gitignore_when_not_git(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        proj = tmp_path / "myproj"
        proj.mkdir()
        e = _entry(scope="workspace", name=".scratch", location="in_repo", vcs="ignored")
        _patch_recipes(monkeypatch, [_recipe("tool", [e])])
        with patch.object(paths, "git_common_dir", return_value=None):
            launcher._persist_mounts("s", proj)
        assert not (proj / ".gitignore").exists()


# --- Layer 2: live round-trip + isolation (podman-gated) -------------------------------------

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

    inst2 = capability.launch_headless(_ROOT, _STACK, project_path=str(proj))
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
