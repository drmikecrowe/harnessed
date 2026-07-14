"""Tests for launcher._staged_build_context — the throwaway podman build context.

harnessed builds from a STAGED COPY of catalog/, not from harnessed_home() directly, because home is
not a scratch dir: in a wheel it is site-packages (writing there mutates the installed package and
fails on a read-only install), and in a checkout it is the repo root (podman would receive .git,
.venv, web/ and node_modules as context on every build).
"""

from pathlib import Path

from harnessed import launcher


def _fake_home(monkeypatch, tmp_path, *, checkout: bool = False):
    """A harnessed home with a catalog/ laid out like the real one."""
    home = tmp_path / ("repo" if checkout else "site-packages/harnessed")
    base = home / "catalog" / "base"
    base.mkdir(parents=True)
    (base / "Dockerfile.harnessed-base").write_text("FROM scratch\n")
    (base / "extra-tools.default.txt").write_text("# seed\n")
    (home / "catalog" / "recipes" / "demo").mkdir(parents=True)
    (home / "catalog" / "recipes" / "demo" / "recipe.yaml").write_text("name: demo\n")
    if checkout:
        (home / "src" / "harnessed").mkdir(parents=True)
        (home / "pyproject.toml").write_text("[project]\nname = 'harnessed'\n")
        # Repo cruft that must NOT be shipped to podman as build context.
        (home / ".git").mkdir()
        (home / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
        (home / "node_modules" / "junk").mkdir(parents=True)
    monkeypatch.setenv("HARNESSED_DIR", str(home))
    return home


def _user_extra_tools(monkeypatch, tmp_path, content):
    xdg = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    f = xdg / "harnessed" / "extra-tools.txt"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content)
    return f


class TestStagedBuildContext:
    def test_context_contains_catalog_at_its_root(self, monkeypatch, tmp_path):
        """The Dockerfiles' COPY paths are context-relative (`COPY catalog/base/...`)."""
        _fake_home(monkeypatch, tmp_path)
        _user_extra_tools(monkeypatch, tmp_path, "ripgrep\n")

        with launcher._staged_build_context() as ctx:
            root = Path(ctx)
            assert (root / "catalog" / "base" / "Dockerfile.harnessed-base").is_file()
            assert (root / "catalog" / "recipes" / "demo" / "recipe.yaml").is_file()

    def test_stages_resolved_extra_tools_into_the_context(self, monkeypatch, tmp_path):
        """Dockerfile.harnessed-base does `COPY catalog/base/extra-tools.txt`."""
        _fake_home(monkeypatch, tmp_path)
        _user_extra_tools(monkeypatch, tmp_path, "ripgrep\nfd\n")

        with launcher._staged_build_context() as ctx:
            staged = Path(ctx) / "catalog" / "base" / "extra-tools.txt"
            assert staged.read_text() == "ripgrep\nfd\n"

    def test_never_writes_into_the_shipped_catalog(self, monkeypatch, tmp_path):
        """THE POINT: in a wheel this dir is site-packages. It must come out untouched."""
        home = _fake_home(monkeypatch, tmp_path)
        _user_extra_tools(monkeypatch, tmp_path, "ripgrep\n")

        before = sorted(p.relative_to(home).as_posix() for p in home.rglob("*"))
        with launcher._staged_build_context():
            pass
        after = sorted(p.relative_to(home).as_posix() for p in home.rglob("*"))

        assert before == after, "the staged context must not mutate harnessed_home()"
        assert not (home / "catalog" / "base" / "extra-tools.txt").exists()

    def test_context_excludes_repo_cruft(self, monkeypatch, tmp_path):
        """In a checkout, home is the repo root — only catalog/ should reach podman."""
        _fake_home(monkeypatch, tmp_path, checkout=True)
        _user_extra_tools(monkeypatch, tmp_path, "ripgrep\n")

        with launcher._staged_build_context() as ctx:
            entries = {p.name for p in Path(ctx).iterdir()}

        assert entries == {"catalog"}, f"context should hold only catalog/, got {entries}"

    def test_seeds_user_extra_tools_from_the_shipped_default(self, monkeypatch, tmp_path):
        """No ~/.config/harnessed/extra-tools.txt yet → seed it, so a fresh install just builds."""
        _fake_home(monkeypatch, tmp_path)
        xdg = tmp_path / "config"
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
        user_file = xdg / "harnessed" / "extra-tools.txt"
        assert not user_file.exists()

        with launcher._staged_build_context() as ctx:
            assert (Path(ctx) / "catalog" / "base" / "extra-tools.txt").read_text() == "# seed\n"

        assert user_file.read_text() == "# seed\n", "user config should have been seeded"

    def test_context_is_cleaned_up(self, monkeypatch, tmp_path):
        _fake_home(monkeypatch, tmp_path)
        _user_extra_tools(monkeypatch, tmp_path, "ripgrep\n")

        with launcher._staged_build_context() as ctx:
            assert Path(ctx).is_dir()
        assert not Path(ctx).exists(), "temp context must be removed on exit"

    def test_stale_local_symlinks_never_enter_the_context(self, monkeypatch, tmp_path):
        """An un-migrated checkout still has catalog/<kind>.local → must not be copied/followed."""
        home = _fake_home(monkeypatch, tmp_path, checkout=True)
        _user_extra_tools(monkeypatch, tmp_path, "ripgrep\n")
        overlay = tmp_path / "private"
        overlay.mkdir()
        (overlay / "secret-recipe.yaml").write_text("name: secret\n")
        (home / "catalog" / "recipes.local").symlink_to(overlay)

        with launcher._staged_build_context() as ctx:
            copied = [p.as_posix() for p in Path(ctx).rglob("*")]

        assert not any("recipes.local" in p for p in copied)
        assert not any("secret-recipe" in p for p in copied)
