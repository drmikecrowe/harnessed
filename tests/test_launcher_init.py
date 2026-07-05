"""Tests for the `init:` recipe mechanism — marker check, one-shot exec, no-secrets guarantee.

Convention follows test_launcher_install.py: no real podman, subprocess.run monkeypatched.
"""

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import typer

from harnessed import launcher, paths
from harnessed.schema import InitMarker, InitSpec, PersistSpec, Recipe


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _recipe(name: str, init: "InitSpec | None" = None) -> Recipe:
    return Recipe(name=name, init=init, persist=PersistSpec())


def _init_spec(*, scope: str = "project", location: str = "host", name: str = ".beads",
               file: "str | None" = None, run: str = "bd init --quiet --stealth") -> InitSpec:
    return InitSpec(marker=InitMarker(scope=scope, location=location, name=name, file=file), run=run)


def _stub_stack(monkeypatch, tmp_path, recipes: list[Recipe]) -> None:
    """Make load_stack_with_recipes return a minimal stack + the given recipes."""
    from harnessed.schema import Stack
    stk = Stack(name="test_stack", harness="claude", recipes=[r.name for r in recipes])
    monkeypatch.setattr(launcher, "load_stack_with_recipes", lambda root, stack: (stk, recipes))
    monkeypatch.setattr(launcher, "load_stack", lambda d: stk)
    monkeypatch.setattr(launcher, "_derived_image", lambda s: "harnessed-test_stack:latest")
    # _persist_mounts also calls load_stack_with_recipes; stub it to return []
    monkeypatch.setattr(launcher, "_persist_mounts", lambda stack, project_path: [])
    # _init_mount_args probes git for the common dir; default to "not a worktree" so the global
    # subprocess.run stub (which returns no .stdout) is never reached. Tests that want the
    # worktree case override this.
    monkeypatch.setattr(paths, "git_common_dir", lambda p: None)


def _home_in(monkeypatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    return home


# ---------------------------------------------------------------------------
# TestResolveMarkerHostPath
# ---------------------------------------------------------------------------


class TestResolveMarkerHostPath:
    """`_resolve_marker_host_path` turns a marker into a host Path using the persist helpers."""

    def test_workspace_host_points_at_persist_workspace_dir(self, tmp_path, monkeypatch):
        project = tmp_path / "proj"
        project.mkdir()
        monkeypatch.setattr(paths, "persist_workspace_dir",
                            lambda recipe, pp, n: tmp_path / "ws" / n)
        spec = _init_spec(scope="workspace", location="host", name=".ctx")
        p = launcher._resolve_marker_host_path("ctx", spec, project)
        assert p == tmp_path / "ws" / ".ctx"

    def test_project_host_points_at_persist_project_dir(self, tmp_path, monkeypatch):
        project = tmp_path / "proj"
        project.mkdir()
        monkeypatch.setattr(paths, "persist_project_dir",
                            lambda recipe, pp, n: tmp_path / "prj" / n)
        spec = _init_spec(scope="project", location="host", name=".beads")
        p = launcher._resolve_marker_host_path("beads", spec, project)
        assert p == tmp_path / "prj" / ".beads"

    def test_in_repo_resolves_under_project(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        spec = _init_spec(scope="workspace", location="in_repo", name=".mydir")
        p = launcher._resolve_marker_host_path("myrcp", spec, project)
        assert p == project / ".mydir"

    def test_optional_file_appended(self, tmp_path, monkeypatch):
        project = tmp_path / "proj"
        project.mkdir()
        monkeypatch.setattr(paths, "persist_project_dir",
                            lambda recipe, pp, n: tmp_path / "prj" / n)
        spec = _init_spec(scope="project", location="host", name=".ctx", file="config")
        p = launcher._resolve_marker_host_path("ctx", spec, project)
        assert p == tmp_path / "prj" / ".ctx" / "config"


# ---------------------------------------------------------------------------
# TestRunInitForStack
# ---------------------------------------------------------------------------


class TestRunInitForStack:
    """`_run_init_for_stack` skips initialized recipes, runs missing ones, fails hard on error."""

    def _stub_marker(self, monkeypatch, exists: bool, marker_path: Path) -> None:
        """Patch _resolve_marker_host_path to return a known path; create it if exists=True."""
        if exists:
            marker_path.mkdir(parents=True)
        monkeypatch.setattr(launcher, "_resolve_marker_host_path",
                            lambda name, spec, pp: marker_path)

    def test_no_init_recipes_runs_nothing(self, tmp_path, monkeypatch):
        """A stack with no init: blocks issues zero subprocess calls."""
        _stub_stack(monkeypatch, tmp_path, [_recipe("ping")])
        project = tmp_path / "proj"
        project.mkdir()
        calls = []
        monkeypatch.setattr(launcher.subprocess, "run",
                            lambda *a, **k: (calls.append(a[0]), SimpleNamespace(returncode=0))[1])
        launcher._run_init_for_stack("podman", "test_stack", project)
        assert calls == []

    def test_marker_present_skips_run(self, tmp_path, monkeypatch):
        """If the marker dir already exists, no subprocess is spawned."""
        spec = _init_spec()
        _stub_stack(monkeypatch, tmp_path, [_recipe("beads", spec)])
        project = tmp_path / "proj"
        project.mkdir()
        marker = tmp_path / "marker"
        self._stub_marker(monkeypatch, exists=True, marker_path=marker)
        calls = []
        monkeypatch.setattr(launcher.subprocess, "run",
                            lambda *a, **k: (calls.append(a[0]), SimpleNamespace(returncode=0))[1])
        launcher._run_init_for_stack("podman", "test_stack", project)
        assert calls == []

    def test_marker_absent_runs_one_shot_command(self, tmp_path, monkeypatch):
        """If the marker is absent, a `podman run --rm` is issued with the init command."""
        spec = _init_spec(run="bd init --quiet --stealth")
        _stub_stack(monkeypatch, tmp_path, [_recipe("beads", spec)])
        project = tmp_path / "proj"
        project.mkdir()
        marker = tmp_path / "marker"
        self._stub_marker(monkeypatch, exists=False, marker_path=marker)
        calls = []
        monkeypatch.setattr(
            launcher.subprocess, "run",
            lambda *a, **k: (calls.append(list(a[0])), SimpleNamespace(returncode=0))[1],
        )
        launcher._run_init_for_stack("podman", "test_stack", project)
        assert len(calls) == 1
        cmd = calls[0]
        assert cmd[0] == "podman"
        assert "--rm" in cmd
        assert "bash" in cmd
        assert "bd init --quiet --stealth" in cmd
        # Never involves varlock or secrets
        assert "varlock" not in " ".join(cmd)
        assert "--secret" not in cmd

    def test_linked_worktree_common_dir_is_mounted(self, tmp_path, monkeypatch):
        """In a bare+worktree layout, the git common dir (outside the project) is bind-mounted too,
        so a git-dependent init command can resolve the repo."""
        spec = _init_spec(run="bd init")
        _stub_stack(monkeypatch, tmp_path, [_recipe("beads", spec)])
        project = tmp_path / "harnessed" / "main"
        project.mkdir(parents=True)
        common = tmp_path / "harnessed" / ".bare"
        common.mkdir()
        # Override the _stub_stack default (None) to simulate a linked worktree.
        monkeypatch.setattr(paths, "git_common_dir", lambda p: common)
        self._stub_marker(monkeypatch, exists=False, marker_path=tmp_path / "marker")
        calls = []
        monkeypatch.setattr(
            launcher.subprocess, "run",
            lambda *a, **k: (calls.append(list(a[0])), SimpleNamespace(returncode=0))[1],
        )
        launcher._run_init_for_stack("podman", "test_stack", project)
        cmd = calls[0]
        assert f"{project}:{project}:rw" in cmd
        assert f"{common}:{common}:rw" in cmd  # the common dir is mounted so git works

    def test_mount_folder_covers_common_dir_no_duplicate_mount(self, tmp_path, monkeypatch):
        """When --mount-folder already exposes a parent containing the git common dir, only the
        single wider mount is emitted (no redundant common-dir bind)."""
        spec = _init_spec(run="bd init")
        _stub_stack(monkeypatch, tmp_path, [_recipe("beads", spec)])
        parent = tmp_path / "harnessed"
        project = parent / "main"
        project.mkdir(parents=True)
        common = parent / ".bare"
        common.mkdir()
        monkeypatch.setattr(paths, "git_common_dir", lambda p: common)
        self._stub_marker(monkeypatch, exists=False, marker_path=tmp_path / "marker")
        calls = []
        monkeypatch.setattr(
            launcher.subprocess, "run",
            lambda *a, **k: (calls.append(list(a[0])), SimpleNamespace(returncode=0))[1],
        )
        launcher._run_init_for_stack("podman", "test_stack", project, mount_path=parent)
        cmd = calls[0]
        assert f"{parent}:{parent}:rw" in cmd
        # No separate .bare mount — it's already under the parent bind.
        assert f"{common}:{common}:rw" not in cmd

    def test_nonzero_exit_raises_exit(self, tmp_path, monkeypatch):
        """A failing init command raises typer.Exit(1) rather than silently continuing."""
        spec = _init_spec()
        _stub_stack(monkeypatch, tmp_path, [_recipe("beads", spec)])
        project = tmp_path / "proj"
        project.mkdir()
        marker = tmp_path / "marker"
        self._stub_marker(monkeypatch, exists=False, marker_path=marker)

        def boom(cmd, check=True, **kwargs):
            if check:
                raise subprocess.CalledProcessError(1, cmd)
            return SimpleNamespace(returncode=1)

        monkeypatch.setattr(launcher.subprocess, "run", boom)
        with pytest.raises(typer.Exit) as exc:
            launcher._run_init_for_stack("podman", "test_stack", project)
        assert exc.value.exit_code == 1

    def test_no_secrets_in_init_command(self, tmp_path, monkeypatch):
        """Init command must never reference varlock, --secret, or env-file resolution."""
        spec = _init_spec()
        _stub_stack(monkeypatch, tmp_path, [_recipe("beads", spec)])
        project = tmp_path / "proj"
        project.mkdir()
        marker = tmp_path / "marker"
        self._stub_marker(monkeypatch, exists=False, marker_path=marker)
        seen_commands = []
        monkeypatch.setattr(
            launcher.subprocess, "run",
            lambda *a, **k: (seen_commands.append(list(a[0])), SimpleNamespace(returncode=0))[1],
        )
        launcher._run_init_for_stack("podman", "test_stack", project)
        for cmd in seen_commands:
            flat = " ".join(str(t) for t in cmd)
            assert "varlock" not in flat
            assert "--secret" not in flat
            assert "env-file" not in flat


# ---------------------------------------------------------------------------
# TestInitSubcommand
# ---------------------------------------------------------------------------


class TestInitSubcommand:
    """`harnessed init <stack>` subcommand — dispatch, build-check, success path."""

    def _stub_built(self, monkeypatch, built: bool) -> None:
        monkeypatch.setattr(launcher, "is_built", lambda stack: built)

    def test_unbuilt_stack_exits_nonzero(self, tmp_path, monkeypatch):
        self._stub_built(monkeypatch, built=False)
        with pytest.raises(typer.Exit) as exc:
            launcher.init_stack("test_stack", str(tmp_path))
        assert exc.value.exit_code == 1

    def test_missing_project_dir_exits_nonzero(self, tmp_path, monkeypatch):
        self._stub_built(monkeypatch, built=True)
        with pytest.raises(typer.Exit) as exc:
            launcher.init_stack("test_stack", str(tmp_path / "nope"))
        assert exc.value.exit_code == 1

    def test_success_calls_run_init_for_stack(self, tmp_path, monkeypatch):
        self._stub_built(monkeypatch, built=True)
        project = tmp_path / "proj"
        project.mkdir()
        calls = []
        monkeypatch.setattr(launcher, "_run_init_for_stack",
                            lambda rt, stack, pp: calls.append((stack, pp)))
        monkeypatch.setattr(launcher, "_runtime", lambda: "podman")
        launcher.init_stack("test_stack", str(project))
        assert len(calls) == 1
        assert calls[0] == ("test_stack", project)
