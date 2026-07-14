"""Tests for _ensure_local_catalog_links (symlink DX helper run on every `harnessed build`).

Two invariants:
  * Keyed to harnessed's OWN source checkout (paths.source_checkout), never the CWD — so
    `harnessed build` works from any directory and never scribbles into an unrelated project.
  * The symlinks live in `catalog-local/`, OUTSIDE the shipped `catalog/` — see paths.local_links_dir.
    They point at the user's private overlay, and setuptools follows symlinks into the wheel.
"""

import pytest
import typer

from harnessed import launcher


_KINDS = ("agents", "recipes", "services", "stacks")


def _setup_xdg(monkeypatch, tmp_path):
    """Isolate XDG_CONFIG_HOME so user_catalog() never touches the real ~/.config/harnessed."""
    xdg = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    return xdg / "harnessed" / "catalog"


def _fake_checkout(monkeypatch, tmp_path):
    """A directory that looks like the harnessed source checkout, pointed at by HARNESSED_DIR."""
    repo = tmp_path / "harnessed_src"
    (repo / "src" / "harnessed").mkdir(parents=True)
    (repo / "catalog").mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname = 'harnessed'\n")
    monkeypatch.setenv("HARNESSED_DIR", str(repo))
    return repo


class TestEnsureLocalCatalogLinks:
    def test_creates_symlinks_outside_catalog(self, monkeypatch, tmp_path):
        """Links land in catalog-local/<kind>, and NOT inside catalog/."""
        user_catalog = _setup_xdg(monkeypatch, tmp_path)
        repo = _fake_checkout(monkeypatch, tmp_path)

        launcher._ensure_local_catalog_links()

        for kind in _KINDS:
            link = repo / "catalog-local" / kind
            assert link.is_symlink(), f"{link} should be a symlink"
            assert link.resolve() == (user_catalog / kind).resolve()
            assert not (repo / "catalog" / f"{kind}.local").exists(), (
                "must not create links inside the shipped catalog/"
            )

    def test_overlay_dirs_created_even_without_a_checkout(self, monkeypatch, tmp_path):
        """A wheel install → overlay dirs still created, but no symlinks anywhere."""
        user_catalog = _setup_xdg(monkeypatch, tmp_path)
        installed = tmp_path / "site-packages" / "harnessed"
        (installed / "catalog").mkdir(parents=True)
        monkeypatch.setenv("HARNESSED_DIR", str(installed))

        launcher._ensure_local_catalog_links()

        for kind in _KINDS:
            assert (user_catalog / kind).is_dir()
        assert not (installed / "catalog-local").exists()
        assert list((installed / "catalog").iterdir()) == [], (
            "must not write into an installed (non-checkout) catalog"
        )

    def test_idempotent(self, monkeypatch, tmp_path):
        user_catalog = _setup_xdg(monkeypatch, tmp_path)
        repo = _fake_checkout(monkeypatch, tmp_path)

        launcher._ensure_local_catalog_links()
        launcher._ensure_local_catalog_links()  # must not raise

        for kind in _KINDS:
            link = repo / "catalog-local" / kind
            assert link.is_symlink()
            assert link.resolve() == (user_catalog / kind).resolve()

    def test_conflict_plain_dir_raises_error(self, monkeypatch, tmp_path):
        """catalog-local/agents is a plain directory → raises typer.Exit(1)."""
        _setup_xdg(monkeypatch, tmp_path)
        repo = _fake_checkout(monkeypatch, tmp_path)
        (repo / "catalog-local" / "agents").mkdir(parents=True)

        with pytest.raises(typer.Exit) as exc:
            launcher._ensure_local_catalog_links()

        assert exc.value.exit_code == 1

    def test_migrates_stale_links_out_of_catalog(self, monkeypatch, tmp_path):
        """A checkout that ran the OLD build has catalog/<kind>.local → they are unlinked.

        Left in place they would be swept into the wheel by `package-data = catalog/**/*`, publishing
        the user's private overlay.
        """
        user_catalog = _setup_xdg(monkeypatch, tmp_path)
        repo = _fake_checkout(monkeypatch, tmp_path)
        for kind in _KINDS:
            (user_catalog / kind).mkdir(parents=True, exist_ok=True)
            (repo / "catalog" / f"{kind}.local").symlink_to(user_catalog / kind)

        launcher._ensure_local_catalog_links()

        for kind in _KINDS:
            assert not (repo / "catalog" / f"{kind}.local").exists(), "stale link must be removed"
            assert not (repo / "catalog" / f"{kind}.local").is_symlink()
            assert (repo / "catalog-local" / kind).is_symlink(), "and re-created in the new location"

    def test_migration_never_deletes_real_content(self, monkeypatch, tmp_path):
        """Only symlinks are unlinked — a real directory named <kind>.local is left alone."""
        _setup_xdg(monkeypatch, tmp_path)
        repo = _fake_checkout(monkeypatch, tmp_path)
        real = repo / "catalog" / "recipes.local"
        real.mkdir(parents=True)
        (real / "keep-me.txt").write_text("real content\n")

        launcher._ensure_local_catalog_links()

        assert (real / "keep-me.txt").read_text() == "real content\n"

    def test_ignores_catalog_dir_in_cwd(self, monkeypatch, tmp_path):
        """REGRESSION: an unrelated project in the CWD with a catalog/ is left untouched."""
        _setup_xdg(monkeypatch, tmp_path)
        _fake_checkout(monkeypatch, tmp_path)

        other = tmp_path / "someone_elses_project"
        (other / "catalog").mkdir(parents=True)
        monkeypatch.chdir(other)

        launcher._ensure_local_catalog_links()

        assert list((other / "catalog").iterdir()) == [], (
            "must not create symlinks in an unrelated project's catalog/"
        )
        assert not (other / "catalog-local").exists()
