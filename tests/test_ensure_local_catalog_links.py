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


def _shipped_default_recipe(repo):
    """The shipped baseline recipe the seed copies from."""
    d = repo / "catalog" / "recipes" / "default"
    (d / "skills" / "harnessed-catalog").mkdir(parents=True)
    (d / "recipe.yaml").write_text("name: default\nskills:\n  - path: skills/harnessed-catalog\n")
    (d / "skills" / "harnessed-catalog" / "SKILL.md").write_text("---\nname: x\n---\n")
    return d


class TestSeedUserDefaultRecipe:
    """`default` is what every dynamic stack inherits, so it is the recipe a user most wants to
    edit — and the hardest one to start from a blank overlay dir."""

    def test_seeds_a_real_copy_on_first_run(self, monkeypatch, tmp_path):
        user_catalog = _setup_xdg(monkeypatch, tmp_path)
        repo = _fake_checkout(monkeypatch, tmp_path)
        _shipped_default_recipe(repo)

        launcher._ensure_local_catalog_links()

        seeded = user_catalog / "recipes" / "default"
        assert (seeded / "recipe.yaml").is_file()
        assert (seeded / "skills" / "harnessed-catalog" / "SKILL.md").is_file()
        assert not (seeded / "skills").is_symlink(), (
            "the seed must dereference — a link into an installation the user later replaces "
            "leaves a dangling baseline"
        )

    def test_the_copy_says_it_shadows_the_shipped_one(self, monkeypatch, tmp_path):
        user_catalog = _setup_xdg(monkeypatch, tmp_path)
        repo = _fake_checkout(monkeypatch, tmp_path)
        _shipped_default_recipe(repo)

        launcher._ensure_local_catalog_links()

        text = (user_catalog / "recipes" / "default" / "recipe.yaml").read_text()
        assert "SEEDED BY HARNESSED" in text
        assert "name: default" in text, "the banner must PREPEND, never replace, the manifest"

    def test_never_overwrites_an_existing_default(self, monkeypatch, tmp_path):
        """Idempotent AND non-destructive: the whole value of the seed is that it is the user's."""
        user_catalog = _setup_xdg(monkeypatch, tmp_path)
        repo = _fake_checkout(monkeypatch, tmp_path)
        _shipped_default_recipe(repo)
        mine = user_catalog / "recipes" / "default"
        mine.mkdir(parents=True)
        (mine / "recipe.yaml").write_text("name: default\n# hand-authored\n")

        launcher._ensure_local_catalog_links()
        launcher._ensure_local_catalog_links()

        assert (mine / "recipe.yaml").read_text() == "name: default\n# hand-authored\n"

    def test_no_shipped_default_is_not_an_error(self, monkeypatch, tmp_path):
        """A catalog root without the baseline (a fixture tree, an old install) must still run."""
        user_catalog = _setup_xdg(monkeypatch, tmp_path)
        _fake_checkout(monkeypatch, tmp_path)

        launcher._ensure_local_catalog_links()

        assert not (user_catalog / "recipes" / "default").exists()

    def test_leaves_no_partial_dir_behind(self, monkeypatch, tmp_path):
        """Seeding stages under a temp name and renames, so a crash cannot leave a half copy at
        the real name — where the exists() guard would treat it as complete forever."""
        user_catalog = _setup_xdg(monkeypatch, tmp_path)
        repo = _fake_checkout(monkeypatch, tmp_path)
        _shipped_default_recipe(repo)
        monkeypatch.setattr(
            launcher.shutil, "copytree", lambda *a, **k: (_ for _ in ()).throw(OSError("boom"))
        )

        with pytest.raises(OSError):
            launcher._ensure_local_catalog_links()

        assert not (user_catalog / "recipes" / "default").exists()
        assert list((user_catalog / "recipes").iterdir()) == []
