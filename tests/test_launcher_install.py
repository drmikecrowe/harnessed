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
