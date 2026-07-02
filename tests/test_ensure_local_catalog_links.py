"""Tests for _ensure_local_catalog_links (symlink DX helper run on every `harnessed build`)."""

from pathlib import Path

import pytest
import typer

from harnessed import launcher


_KINDS = ("agents", "recipes", "services", "stacks")


def _setup_xdg(monkeypatch, tmp_path):
    """Isolate XDG_CONFIG_HOME so user_catalog() never touches the real ~/.config/harnessed."""
    xdg = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    return xdg / "harnessed" / "catalog"


class TestEnsureLocalCatalogLinks:
    def test_no_catalog_dir_creates_overlay_dirs_only(self, monkeypatch, tmp_path):
        """cwd has no catalog/ → overlay dirs are still created; no symlinks are made."""
        user_catalog = _setup_xdg(monkeypatch, tmp_path)
        cwd = tmp_path / "not_a_repo"
        cwd.mkdir()
        monkeypatch.chdir(cwd)

        launcher._ensure_local_catalog_links()

        for kind in _KINDS:
            assert (user_catalog / kind).is_dir(), f"user_catalog/{kind} should exist"
        assert not (cwd / "catalog").exists()

    def test_creates_symlinks_when_catalog_dir_exists(self, monkeypatch, tmp_path):
        """cwd has catalog/ → overlay dirs created and each <kind>.local symlink points at them."""
        user_catalog = _setup_xdg(monkeypatch, tmp_path)
        cwd = tmp_path / "repo"
        (cwd / "catalog").mkdir(parents=True)
        monkeypatch.chdir(cwd)

        launcher._ensure_local_catalog_links()

        for kind in _KINDS:
            link = cwd / "catalog" / f"{kind}.local"
            assert link.is_symlink(), f"{link} should be a symlink"
            assert link.resolve() == (user_catalog / kind).resolve()

    def test_idempotent_correct_symlink(self, monkeypatch, tmp_path):
        """Already-correct symlinks → second call is a no-op with no error."""
        user_catalog = _setup_xdg(monkeypatch, tmp_path)
        cwd = tmp_path / "repo"
        (cwd / "catalog").mkdir(parents=True)
        monkeypatch.chdir(cwd)

        launcher._ensure_local_catalog_links()
        launcher._ensure_local_catalog_links()  # must not raise

        for kind in _KINDS:
            link = cwd / "catalog" / f"{kind}.local"
            assert link.is_symlink()
            assert link.resolve() == (user_catalog / kind).resolve()

    def test_conflict_plain_dir_raises_error(self, monkeypatch, tmp_path):
        """catalog/agents.local is a plain directory → raises typer.Exit(1)."""
        _setup_xdg(monkeypatch, tmp_path)
        cwd = tmp_path / "repo"
        conflict = cwd / "catalog" / "agents.local"
        conflict.mkdir(parents=True)
        monkeypatch.chdir(cwd)

        with pytest.raises(typer.Exit) as exc:
            launcher._ensure_local_catalog_links()

        assert exc.value.exit_code == 1
