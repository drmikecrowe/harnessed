"""Tests for paths.harnessed_home / paths.source_checkout — the CWD-free anchor for catalog
lookup and the podman build context.

`harnessed build <stack>` must resolve the catalog identically from any working directory, and an
INSTALLED (wheel) harnessed must find the catalog shipped inside the package rather than groping
around the filesystem for a repo that isn't there.
"""

import pytest

from harnessed import paths


class TestHarnessedHome:
    def test_honors_harnessed_dir_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HARNESSED_DIR", str(tmp_path))
        assert paths.harnessed_home() == tmp_path

    def test_is_independent_of_cwd(self, monkeypatch, tmp_path):
        """The whole point: the same home from any directory, including one holding a catalog/."""
        monkeypatch.delenv("HARNESSED_DIR", raising=False)
        home = paths.harnessed_home()

        decoy = tmp_path / "decoy"
        (decoy / "catalog" / "stacks").mkdir(parents=True)
        monkeypatch.chdir(decoy)

        assert paths.harnessed_home() == home, "home must not follow the CWD"

    def test_home_really_contains_a_real_catalog(self, monkeypatch):
        """Home is the podman build context root, so catalog/ must be a REAL dir there.

        podman rejects a context symlink that escapes the context, so resolving through the dev
        `src/harnessed/catalog` symlink (rather than returning the package dir verbatim) matters.
        """
        monkeypatch.delenv("HARNESSED_DIR", raising=False)
        catalog = paths.harnessed_home() / "catalog"

        assert catalog.is_dir()
        assert not catalog.is_symlink(), "build context must contain a real catalog/, not a symlink"
        assert (catalog / "stacks").is_dir()
        assert (catalog / "base").is_dir()

    def test_catalog_roots_end_at_home(self, monkeypatch, tmp_path):
        """Home catalog is the last authored root; the generated root follows only when it exists.

        Monkeypatch XDG_DATA_HOME to an empty tmp dir so the generated root is always absent here,
        making the assertion stable on any machine regardless of prior `harnessed run` invocations.
        """
        monkeypatch.delenv("HARNESSED_DIR", raising=False)
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        roots = paths.catalog_roots()
        home_catalog = paths.harnessed_home() / "catalog"
        assert home_catalog in roots, "harnessed_home/catalog must appear in catalog_roots()"
        assert roots[-1] == home_catalog, (
            "when no generated root exists, harnessed_home/catalog must be the last root"
        )

    def test_raises_when_no_catalog_is_findable(self, monkeypatch, tmp_path):
        """No catalog beside the package → a named error, not a bogus 'unknown stack <x>'."""
        monkeypatch.delenv("HARNESSED_DIR", raising=False)
        monkeypatch.setattr(paths, "__file__", str(tmp_path / "harnessed" / "paths.py"))

        with pytest.raises(paths.HomeNotFoundError, match="cannot locate harnessed's catalog"):
            paths.harnessed_home()


class TestSourceCheckout:
    def test_detects_a_checkout(self, monkeypatch, tmp_path):
        repo = tmp_path / "repo"
        (repo / "src" / "harnessed").mkdir(parents=True)
        (repo / "pyproject.toml").write_text("[project]\nname = 'harnessed'\n")
        monkeypatch.setenv("HARNESSED_DIR", str(repo))

        assert paths.source_checkout() == repo

    def test_installed_layout_is_not_a_checkout(self, monkeypatch, tmp_path):
        """site-packages/harnessed/ has a catalog/ but no pyproject.toml + src/ → not a checkout.

        This is what keeps the dev-only helpers from writing into an installed package.
        """
        installed = tmp_path / "site-packages" / "harnessed"
        (installed / "catalog").mkdir(parents=True)
        monkeypatch.setenv("HARNESSED_DIR", str(installed))

        assert paths.source_checkout() is None

    def test_real_repo_is_a_checkout(self, monkeypatch):
        """Running the suite from the repo, home IS the checkout."""
        monkeypatch.delenv("HARNESSED_DIR", raising=False)
        assert paths.source_checkout() == paths.harnessed_home()
