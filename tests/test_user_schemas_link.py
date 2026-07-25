"""Tests for _ensure_user_schemas_link (run on every `harnessed build`).

A manifest's `# yaml-language-server: $schema=../../../schemas/<kind>.schema.json` is relative to the
manifest, so an overlay stack at ~/.config/harnessed/catalog/stacks/<name>/stack.yaml looks for
~/.config/harnessed/schemas/ — a dir nothing used to create. The link is editor ergonomics only, so
every failure mode here degrades to a warning rather than aborting a build.
"""

import pytest

from harnessed import launcher, paths


def _setup(monkeypatch, tmp_path, *, with_schemas: bool = True):
    """Isolated XDG config home + a HARNESSED_DIR that ships (or doesn't ship) schemas/."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    home = tmp_path / "harnessed_home"
    (home / "catalog").mkdir(parents=True)
    if with_schemas:
        (home / "schemas").mkdir()
        (home / "schemas" / "stack.schema.json").write_text("{}")
    monkeypatch.setenv("HARNESSED_DIR", str(home))
    return home


class TestEnsureUserSchemasLink:
    def test_creates_the_link(self, monkeypatch, tmp_path):
        home = _setup(monkeypatch, tmp_path)

        launcher._ensure_user_schemas_link()

        dest = paths.user_schemas_dir()
        assert dest.is_symlink()
        assert dest.resolve() == (home / "schemas").resolve()

    def test_overlay_manifest_schema_ref_resolves(self, monkeypatch, tmp_path):
        """The actual bug: `../../../schemas/stack.schema.json` from an overlay stack.yaml."""
        _setup(monkeypatch, tmp_path)
        stack_dir = paths.user_catalog() / "stacks" / "mine"
        stack_dir.mkdir(parents=True)
        manifest = stack_dir / "stack.yaml"

        launcher._ensure_user_schemas_link()

        ref = (manifest.parent / "../../../schemas/stack.schema.json").resolve()
        assert ref.is_file(), f"{ref} must exist for the editor to load the schema"

    def test_idempotent(self, monkeypatch, tmp_path):
        _setup(monkeypatch, tmp_path)

        launcher._ensure_user_schemas_link()
        launcher._ensure_user_schemas_link()  # must not raise

        assert paths.user_schemas_dir().is_symlink()

    def test_retargets_a_stale_link(self, monkeypatch, tmp_path):
        """A wheel upgrade moves site-packages; the old link is ours to repoint."""
        home = _setup(monkeypatch, tmp_path)
        dest = paths.user_schemas_dir()
        dest.parent.mkdir(parents=True)
        dest.symlink_to(tmp_path / "gone" / "schemas")

        launcher._ensure_user_schemas_link()

        assert dest.resolve() == (home / "schemas").resolve()

    def test_leaves_real_content_alone(self, monkeypatch, tmp_path, capsys):
        """A real dir there is the user's; warn, never clobber, never fail."""
        _setup(monkeypatch, tmp_path)
        dest = paths.user_schemas_dir()
        dest.mkdir(parents=True)
        (dest / "mine.json").write_text("{}")

        launcher._ensure_user_schemas_link()

        assert not dest.is_symlink()
        assert (dest / "mine.json").is_file()
        assert "not a symlink" in capsys.readouterr().err

    def test_missing_source_warns_without_failing(self, monkeypatch, tmp_path, capsys):
        _setup(monkeypatch, tmp_path, with_schemas=False)

        launcher._ensure_user_schemas_link()

        assert not paths.user_schemas_dir().exists()
        assert "no schemas dir" in capsys.readouterr().err


class TestShippedSchemasAreDiscoverable:
    @pytest.mark.parametrize(
        "kind", ["agent", "recipe", "service", "stack"]
    )
    def test_every_kind_ships_a_schema(self, kind):
        """paths.schemas_dir() must resolve in this checkout — and in a wheel (see
        tests/test_wheel_packaging.py), which is what makes the overlay link non-dangling."""
        assert (paths.schemas_dir() / f"{kind}.schema.json").is_file()
