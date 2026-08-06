"""Tests for _ensure_local_catalog_links (symlink DX helper run on every `harnessed build`).

Two invariants:
  * Keyed to harnessed's OWN source checkout (paths.source_checkout), never the CWD — so
    `harnessed build` works from any directory and never scribbles into an unrelated project.
  * The symlinks live in `catalog-local/`, OUTSIDE the shipped `catalog/` — see paths.local_links_dir.
    They point at the user's private overlay, and setuptools follows symlinks into the wheel.
"""

import os

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


class TestStaleLinkIsRepointed:
    """bd harnessed-ng5 — a link left behind by a DIFFERENT `$XDG_CONFIG_HOME` is stale, not foreign.

    `catalog-local/<kind>` is an artifact harnessed creates and owns. Aborting the build because it
    points at another `.../harnessed/catalog/<kind>` told the user to hand-fix a link harnessed had
    written itself, and made the podman-gated suite unrunnable: every test gets a fresh tmp
    `$XDG_CONFIG_HOME` (conftest `_isolated_user_catalog`), and the live tests shell out to the real
    `harnessed build` in the real checkout — so the first one poisoned all the rest, and the leftover
    links (pointing into a deleted tmp tree) poisoned every later RUN.

    Re-pointing is confined to destinations shaped like a harnessed overlay. Anything else still
    aborts, because then the link is not ours to move.
    """

    def _link(self, repo, kind, dest):
        links = repo / "catalog-local"
        links.mkdir(parents=True, exist_ok=True)
        (links / kind).symlink_to(dest)
        return links / kind

    def test_repoints_a_link_left_by_another_xdg_root(self, monkeypatch, tmp_path):
        repo = _fake_checkout(monkeypatch, tmp_path)
        other = tmp_path / "other-xdg" / "harnessed" / "catalog"
        (other / "agents").mkdir(parents=True)
        self._link(repo, "agents", other / "agents")

        user_catalog = _setup_xdg(monkeypatch, tmp_path)
        launcher._ensure_local_catalog_links()

        for kind in _KINDS:
            link = repo / "catalog-local" / kind
            assert link.is_symlink()
            assert Path(os.readlink(link)) == user_catalog / kind

    def test_two_calls_under_different_xdg_roots(self, monkeypatch, tmp_path):
        """The bead's 'two live tests in one session', at unit speed."""
        repo = _fake_checkout(monkeypatch, tmp_path)

        _setup_xdg(monkeypatch, tmp_path / "first")
        launcher._ensure_local_catalog_links()
        second = _setup_xdg(monkeypatch, tmp_path / "second")
        launcher._ensure_local_catalog_links()  # must not raise

        for kind in _KINDS:
            assert Path(os.readlink(repo / "catalog-local" / kind)) == second / kind

    def test_repoints_a_dangling_link_from_a_deleted_run(self, monkeypatch, tmp_path):
        """The cross-RUN case: the previous run's tmp XDG tree no longer exists at all."""
        repo = _fake_checkout(monkeypatch, tmp_path)
        gone = tmp_path / "pytest-of-x" / "pytest-24" / "xdg0" / "harnessed" / "catalog"
        link = self._link(repo, "recipes", gone / "recipes")
        assert not link.exists(), "precondition: the link is dangling"

        user_catalog = _setup_xdg(monkeypatch, tmp_path)
        launcher._ensure_local_catalog_links()

        assert Path(os.readlink(link)) == user_catalog / "recipes"

    def test_a_foreign_symlink_still_aborts_and_is_left_alone(self, monkeypatch, tmp_path):
        """A link into something that is NOT a harnessed overlay is the user's, not ours to move."""
        repo = _fake_checkout(monkeypatch, tmp_path)
        mine = tmp_path / "my-own-recipes"
        mine.mkdir()
        link = self._link(repo, "recipes", mine)

        _setup_xdg(monkeypatch, tmp_path)
        with pytest.raises(typer.Exit) as exc:
            launcher._ensure_local_catalog_links()

        assert exc.value.exit_code == 1
        assert Path(os.readlink(link)) == mine, "the user's own link must survive the abort"

    def test_a_relative_link_is_not_ours(self, monkeypatch, tmp_path):
        """`../../harnessed/catalog/agents` has our SHAPE but we only ever write absolute links.

        Adversarial review, finding A2: matching on the last three path components alone accepts a
        relative target, which by construction cannot be one of ours.
        """
        repo = _fake_checkout(monkeypatch, tmp_path)
        link = self._link(repo, "agents", Path("../../harnessed/catalog/agents"))

        _setup_xdg(monkeypatch, tmp_path)
        with pytest.raises(typer.Exit) as exc:
            launcher._ensure_local_catalog_links()

        assert exc.value.exit_code == 1
        assert os.readlink(link) == "../../harnessed/catalog/agents"

    def test_another_checkouts_shipped_catalog_is_not_ours(self, monkeypatch, tmp_path):
        """The NEAR MISS: a second clone in a dir named `harnessed` has exactly our shape.

        Adversarial review, finding A1: `<x>/harnessed/catalog/agents` is the shipped catalog of any
        checkout whose directory is called `harnessed` — the common case for a clone — not an
        overlay. Told apart by the `pyproject.toml` a checkout has and an XDG root does not.
        """
        repo = _fake_checkout(monkeypatch, tmp_path)
        other = tmp_path / "second-clone" / "harnessed"
        (other / "catalog" / "agents").mkdir(parents=True)
        (other / "pyproject.toml").write_text("[project]\nname = 'harnessed'\n")
        (other / "src" / "harnessed").mkdir(parents=True)
        link = self._link(repo, "agents", other / "catalog" / "agents")

        _setup_xdg(monkeypatch, tmp_path)
        with pytest.raises(typer.Exit) as exc:
            launcher._ensure_local_catalog_links()

        assert exc.value.exit_code == 1
        assert Path(os.readlink(link)) == other / "catalog" / "agents"

    def test_a_stray_pyproject_alone_does_not_make_it_a_checkout(self, monkeypatch, tmp_path):
        """"Is a checkout" must mean what `paths.source_checkout` means: BOTH markers, not one.

        Adversarial review round 2, findings 2 and 6: keying only on `pyproject.toml` makes any XDG
        root that happens to contain one look like a checkout, and the build goes back to aborting —
        the original P1 shape. `source_checkout()` requires `pyproject.toml` AND `src/harnessed`, and
        so must this.
        """
        repo = _fake_checkout(monkeypatch, tmp_path)
        stale = tmp_path / "old-xdg" / "harnessed"
        (stale / "catalog" / "agents").mkdir(parents=True)
        (stale / "pyproject.toml").write_text("[project]\nname = 'something-else'\n")
        link = self._link(repo, "agents", stale / "catalog" / "agents")

        user_catalog = _setup_xdg(monkeypatch, tmp_path)
        launcher._ensure_local_catalog_links()  # must not raise

        assert Path(os.readlink(link)) == user_catalog / "agents"

    def test_a_link_that_vanishes_mid_check_does_not_crash_the_build(self, monkeypatch, tmp_path):
        """`readlink` can fail too, and it sat OUTSIDE the guard that promises not to traceback.

        Adversarial review round 3, finding A1: a concurrent `harnessed build` in the same checkout
        can remove the link between `is_symlink()` and `readlink()`. The build died with a raw
        `FileNotFoundError` — precisely the outcome this function's contract rules out. A failed
        `readlink` means the link is gone or unreadable, so we cannot claim it as ours: fall through
        to the ordinary abort, which is a message rather than a stack trace.
        """
        repo = _fake_checkout(monkeypatch, tmp_path)
        other = tmp_path / "other-xdg" / "harnessed" / "catalog"
        (other / "agents").mkdir(parents=True)
        self._link(repo, "agents", other / "agents")

        real_readlink = os.readlink

        def vanishing_readlink(path, *a, **kw):
            if str(path).endswith("catalog-local/agents"):
                raise FileNotFoundError(2, "No such file or directory", str(path))
            return real_readlink(path, *a, **kw)

        monkeypatch.setattr(os, "readlink", vanishing_readlink)
        _setup_xdg(monkeypatch, tmp_path)

        with pytest.raises(typer.Exit) as exc:  # NOT FileNotFoundError
            launcher._ensure_local_catalog_links()
        assert exc.value.exit_code == 1

    @pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
    def test_an_unreadable_target_tree_does_not_crash_the_build(self, monkeypatch, tmp_path):
        """`is_file()` raises PermissionError on a mode-000 ancestor; a build must not traceback.

        Adversarial review round 2, finding 1. Undecidable resolves to "ours": we cannot read the
        markers, and re-pointing costs at most one convenience symlink, while the alternative is the
        hard abort this whole change exists to remove. Nothing is deleted either way — only a
        symlink is ever unlinked.
        """
        repo = _fake_checkout(monkeypatch, tmp_path)
        walled = tmp_path / "walled"
        (walled / "harnessed" / "catalog" / "agents").mkdir(parents=True)
        link = self._link(repo, "agents", walled / "harnessed" / "catalog" / "agents")

        user_catalog = _setup_xdg(monkeypatch, tmp_path)
        walled.chmod(0o000)
        try:
            launcher._ensure_local_catalog_links()  # must not raise PermissionError
            assert Path(os.readlink(link)) == user_catalog / "agents"
        finally:
            walled.chmod(0o755)

    def test_a_correct_link_is_left_untouched(self, monkeypatch, tmp_path):
        """Idempotence is a NO-OP, not an unlink-and-recreate: same inode, same ctime."""
        _setup_xdg(monkeypatch, tmp_path)
        repo = _fake_checkout(monkeypatch, tmp_path)
        launcher._ensure_local_catalog_links()
        link = repo / "catalog-local" / "agents"
        before = os.lstat(link)

        launcher._ensure_local_catalog_links()

        after = os.lstat(link)
        assert (after.st_ino, after.st_ctime_ns) == (before.st_ino, before.st_ctime_ns)


def _shipped_default_recipe(repo):
    """The shipped baseline recipe the seed copies from.

    The skill dir is a SYMLINK, mirroring the real catalog (`catalog/recipes/default/skills/...`
    is the one copy `.agents/skills/` links to, and an overlay recipe may link at content the user
    edits elsewhere). Without that, a seed using `symlinks=True` would satisfy every assertion.
    """
    d = repo / "catalog" / "recipes" / "default"
    d.mkdir(parents=True)
    real = repo / "elsewhere" / "harnessed-catalog"
    real.mkdir(parents=True)
    (real / "SKILL.md").write_text("---\nname: x\n---\n")
    (d / "skills").mkdir()
    (d / "skills" / "harnessed-catalog").symlink_to(real, target_is_directory=True)
    (d / "recipe.yaml").write_text("name: default\nskills:\n  - path: skills/harnessed-catalog\n")
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

    def test_a_dangling_symlink_at_the_destination_is_left_alone(self, monkeypatch, tmp_path):
        """`exists()` RESOLVES, so a broken link reads as absent — and renaming onto it raises
        NotADirectoryError, taking the launch down with it. A link the user put there is theirs."""
        user_catalog = _setup_xdg(monkeypatch, tmp_path)
        repo = _fake_checkout(monkeypatch, tmp_path)
        _shipped_default_recipe(repo)
        (user_catalog / "recipes").mkdir(parents=True)
        dangling = user_catalog / "recipes" / "default"
        dangling.symlink_to(tmp_path / "gone")

        launcher._ensure_local_catalog_links()

        assert dangling.is_symlink()
        assert not dangling.exists(), "still dangling — we neither followed nor replaced it"

    def test_losing_a_concurrent_seed_race_is_not_an_error(self, monkeypatch, tmp_path):
        """Two first launches at once must not fail each other. Staging is per-process, and a
        rename that loses to a complete `recipes/default` is a success, not an exception."""
        user_catalog = _setup_xdg(monkeypatch, tmp_path)
        repo = _fake_checkout(monkeypatch, tmp_path)
        _shipped_default_recipe(repo)
        dest = user_catalog / "recipes" / "default"

        real_rename = launcher.Path.rename

        def rename_after_a_rival_finished(self, target):
            """The rival process wins between our exists() check and our rename."""
            if str(target) == str(dest) and not dest.exists():
                dest.mkdir(parents=True)
                (dest / "recipe.yaml").write_text("name: default\n# by the other process\n")
            return real_rename(self, target)

        monkeypatch.setattr(launcher.Path, "rename", rename_after_a_rival_finished)

        launcher._ensure_local_catalog_links()  # must not raise

        assert (dest / "recipe.yaml").read_text().endswith("# by the other process\n")
        leftovers = [p.name for p in (user_catalog / "recipes").iterdir() if p.name != "default"]
        assert leftovers == [], f"staging dirs left behind: {leftovers}"

    def test_a_real_seeding_failure_still_raises(self, monkeypatch, tmp_path):
        """The race tolerance must not swallow a genuine failure — no space, no permission —
        which would otherwise seed nothing and say nothing."""
        _setup_xdg(monkeypatch, tmp_path)
        repo = _fake_checkout(monkeypatch, tmp_path)
        _shipped_default_recipe(repo)
        monkeypatch.setattr(
            launcher.shutil, "copytree", lambda *a, **k: (_ for _ in ()).throw(OSError("no space"))
        )

        with pytest.raises(OSError, match="no space"):
            launcher._ensure_local_catalog_links()
