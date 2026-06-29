"""Tests for `harnessed install` shim generation.

The shim must bake in an ABSOLUTE path to the `harnessed` binary so it works even when
`harnessed` itself is not on PATH (e.g. a dev .venv) — the item-3 PATH-shim fix.
"""

from pathlib import Path

import pytest
import typer

from harnessed import launcher, paths


def _stub_catalog(monkeypatch, tmp_path, *, exists: bool):
    """Point find_in_catalog at a tmp stacks dir; create stack.yaml iff exists."""
    stack_dir = tmp_path / "catalog" / "stacks" / "claude_time"
    if exists:
        stack_dir.mkdir(parents=True)
        (stack_dir / "stack.yaml").write_text(
            "name: claude_time\nharness: claude\nrecipes: [time]\nservices: []\n"
        )
    monkeypatch.setattr(paths, "find_in_catalog", lambda kind, name: stack_dir)


def _home_in(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    return home


class TestInstallShim:
    def test_bakes_absolute_harnessed_path_from_which(self, monkeypatch, tmp_path):
        _stub_catalog(monkeypatch, tmp_path, exists=True)
        home = _home_in(monkeypatch, tmp_path)
        monkeypatch.setattr(launcher.shutil, "which", lambda _: "/opt/bin/harnessed")

        launcher.install_stack("claude_time")

        shim = home / ".local" / "bin" / "claude_time"
        content = shim.read_text()
        assert shim.exists()
        assert shim.stat().st_mode & 0o111  # executable
        # Absolute path baked in — NOT a bare `harnessed`.
        assert "exec /opt/bin/harnessed claude_time \"$@\"" in content
        assert "exec harnessed " not in content

    def test_falls_back_to_running_binary_when_not_on_path(self, monkeypatch, tmp_path):
        _stub_catalog(monkeypatch, tmp_path, exists=True)
        home = _home_in(monkeypatch, tmp_path)
        monkeypatch.setattr(launcher.shutil, "which", lambda _: None)
        monkeypatch.setattr(launcher.sys, "argv", ["/dev/venv/bin/harnessed", "install", "claude_time"])

        launcher.install_stack("claude_time")

        content = (home / ".local" / "bin" / "claude_time").read_text()
        assert "/dev/venv/bin/harnessed claude_time" in content

    def test_unknown_stack_exits_nonzero_and_writes_no_shim(self, monkeypatch, tmp_path):
        _stub_catalog(monkeypatch, tmp_path, exists=False)
        home = _home_in(monkeypatch, tmp_path)

        with pytest.raises(typer.Exit) as exc:
            launcher.install_stack("claude_time")

        assert exc.value.exit_code == 1
        assert not (home / ".local" / "bin" / "claude_time").exists()


class TestImageStaleness:
    """`_img_differs` decides whether a running container is on an older image build."""

    def test_different_ids_are_stale(self):
        assert launcher._img_differs("aaa111", "bbb222") is True

    def test_same_ids_not_stale(self):
        assert launcher._img_differs("aaa111", "aaa111") is False

    def test_sha256_prefix_normalized(self):
        # image inspect may yield a bare hash; container inspect a sha256:-prefixed one.
        assert launcher._img_differs("sha256:aaa111", "aaa111") is False

    def test_missing_id_is_not_stale(self):
        # inspect failure on either side → can't tell → don't nag / don't recreate.
        assert launcher._img_differs("", "aaa111") is False
        assert launcher._img_differs("aaa111", "") is False




class TestStoppedLeftover:
    """`_stopped_leftover` decides whether launch() must recreate a stopped instance before
    `pod create` (a same-name pod otherwise 125s "already in use")."""

    def _set(self, monkeypatch, *, running, exists, podman, pod_exists):
        monkeypatch.setattr(launcher, "_container_running", lambda rt, inst: running)
        monkeypatch.setattr(launcher, "_container_exists", lambda rt, inst: exists)
        monkeypatch.setattr(launcher, "_rt_uses_pods", lambda rt: podman)
        monkeypatch.setattr(launcher, "_pod_exists", lambda rt, pod: pod_exists)

    def test_running_instance_is_never_a_leftover(self, monkeypatch):
        self._set(monkeypatch, running=True, exists=True, podman=True, pod_exists=True)
        assert launcher._stopped_leftover("podman", "inst", "inst") is False

    def test_stopped_container_is_a_leftover(self, monkeypatch):
        self._set(monkeypatch, running=False, exists=True, podman=True, pod_exists=True)
        assert launcher._stopped_leftover("podman", "inst", "inst") is True

    def test_partial_create_pod_only_is_a_leftover(self, monkeypatch):
        # Pod created but harness container never started (crash between create + run).
        self._set(monkeypatch, running=False, exists=False, podman=True, pod_exists=True)
        assert launcher._stopped_leftover("podman", "inst", "inst") is True

    def test_nothing_present_is_not_a_leftover(self, monkeypatch):
        self._set(monkeypatch, running=False, exists=False, podman=True, pod_exists=False)
        assert launcher._stopped_leftover("podman", "inst", "inst") is False

    def test_docker_has_no_pod_concept(self, monkeypatch):
        # _rt_uses_pods False → pod check skipped; only the container check matters.
        self._set(monkeypatch, running=False, exists=False, podman=False, pod_exists=True)
        assert launcher._stopped_leftover("docker", "inst", "inst") is False


class TestResolveStartDir:
    """`_resolve_start_dir` resolves the agent's working directory for --agent-start-folder."""

    def test_none_returns_project_root(self, tmp_path):
        assert launcher._resolve_start_dir(tmp_path, None) == tmp_path

    def test_relative_subfolder_resolves_under_project(self, tmp_path):
        sub = tmp_path / "packages" / "web"
        sub.mkdir(parents=True)
        assert launcher._resolve_start_dir(tmp_path, "packages/web") == sub

    def test_absolute_subfolder_under_project(self, tmp_path):
        sub = tmp_path / "svc"
        sub.mkdir()
        assert launcher._resolve_start_dir(tmp_path, str(sub)) == sub

    def test_nonexistent_folder_exits(self, tmp_path):
        with pytest.raises(typer.Exit):
            launcher._resolve_start_dir(tmp_path, "nope/missing")

    def test_file_not_directory_exits(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("x")
        with pytest.raises(typer.Exit):
            launcher._resolve_start_dir(tmp_path, "file.txt")

    def test_outside_project_exits(self, tmp_path):
        # A dir that exists on the host but is not under the mounted project tree.
        outside = tmp_path.parent / "elsewhere_check"
        outside.mkdir(exist_ok=True)
        try:
            with pytest.raises(typer.Exit):
                launcher._resolve_start_dir(tmp_path, str(outside))
        finally:
            outside.rmdir()
