"""The overlay-shadow recipe warning: a recipe that resolves from the user overlay and shadows a
repo-catalog copy of the same name must warn, exactly once.

`paths.catalog_roots()` puts the user overlay ($XDG_CONFIG_HOME/harnessed/catalog) AHEAD of the
repo catalog, and the overlay wins on a name clash. Sessions have quietly assembled stale overlay
recipes while the newer repo copy sat unread. `load_stack_with_recipes` therefore warns — on the
production path only (`root is None`), for recipes only, never for `default` (a documented,
blessed override), and at most once per name per process.
"""

import pytest

from harnessed import paths, schema


def _install(monkeypatch, tmp_path, *, overlay=(), repo=(), stack_recipes=()):
    """Install tmp catalog roots and return (xdg, home).

    `overlay` names land in the user overlay, `repo` names in a fake repo catalog pointed at by
    HARNESSED_DIR, and a stack `s` naming `stack_recipes` lands in the repo catalog. Re-setting
    XDG_CONFIG_HOME here overrides the suite-wide `_isolated_user_catalog` blank — the exact
    override its docstring blesses. XDG_DATA_HOME is blanked so the machine-generated stacks root
    on the developer's real home can never answer a lookup.
    """
    xdg, home = tmp_path / "xdg", tmp_path / "home"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("HARNESSED_DIR", str(home))
    for names, base in ((overlay, xdg / "harnessed" / "catalog"), (repo, home / "catalog")):
        for name in names:
            d = base / "recipes" / name
            d.mkdir(parents=True, exist_ok=True)
            (d / "recipe.yaml").write_text(f"name: {name}\n")
    sd = home / "catalog" / "stacks" / "s"
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "stack.yaml").write_text(f"name: s\nrecipes: [{', '.join(stack_recipes)}]\n")
    return xdg, home


@pytest.fixture(autouse=True)
def _clean_warning_state():
    """The warned-once guard and the console's warning counter are process-wide; reset per test."""
    schema._reset_overlay_shadow_warnings()
    schema._err.warnings = 0
    yield
    schema._reset_overlay_shadow_warnings()
    schema._err.warnings = 0


@pytest.fixture(autouse=True)
def _wide_console(monkeypatch):
    """Rich wraps at console width; a wrapped path line would break exact-output asserts."""
    monkeypatch.setattr(schema._err, "width", 400)


class TestOverlayShadowWarning:
    def test_overlay_only_recipe_does_not_warn(self, monkeypatch, tmp_path, capsys):
        _install(monkeypatch, tmp_path, overlay=["only-overlay"], stack_recipes=["only-overlay"])
        schema.load_stack_with_recipes(None, "s")
        assert capsys.readouterr().err == ""
        assert schema._err.warnings == 0

    def test_repo_only_recipe_does_not_warn(self, monkeypatch, tmp_path, capsys):
        _install(monkeypatch, tmp_path, repo=["only-repo"], stack_recipes=["only-repo"])
        schema.load_stack_with_recipes(None, "s")
        assert capsys.readouterr().err == ""
        assert schema._err.warnings == 0

    def test_shadowed_recipe_warns_once_with_both_paths(self, monkeypatch, tmp_path, capsys):
        xdg, home = _install(
            monkeypatch, tmp_path, overlay=["stale"], repo=["stale"], stack_recipes=["stale"]
        )
        schema.load_stack_with_recipes(None, "s")
        assert capsys.readouterr().err == (
            "warning: recipe 'stale' comes from your user overlay, not the repo catalog.\n"
            f"  using:    {xdg}/harnessed/catalog/recipes/stale\n"
            f"  shadowed: {home}/catalog/recipes/stale\n"
            "  The overlay wins. Re-sync it or the repo copy stays unused.\n"
        )
        assert schema._err.warnings == 1

    def test_shadowed_default_does_not_warn(self, monkeypatch, tmp_path, capsys):
        _install(monkeypatch, tmp_path, overlay=["default"], repo=["default"],
                 stack_recipes=["default"])
        schema.load_stack_with_recipes(None, "s")
        assert capsys.readouterr().err == ""
        assert schema._err.warnings == 0

    def test_second_resolve_of_same_name_does_not_rewarn(self, monkeypatch, tmp_path, capsys):
        _install(monkeypatch, tmp_path, overlay=["stale"], repo=["stale"],
                 stack_recipes=["stale"])
        schema.load_stack_with_recipes(None, "s")
        schema.load_stack_with_recipes(None, "s")
        assert capsys.readouterr().err.count("warning: recipe 'stale'") == 1

    def test_explicit_root_fixture_tree_does_not_warn(self, monkeypatch, tmp_path, capsys):
        """The shadow pair exists in both real roots, yet an explicit root is a fixture tree."""
        _install(monkeypatch, tmp_path, overlay=["stale"], repo=["stale"])
        fixture = tmp_path / "fixture"
        d = fixture / "recipes" / "stale"
        d.mkdir(parents=True)
        (d / "recipe.yaml").write_text("name: stale\n")
        sd = fixture / "stacks" / "s"
        sd.mkdir(parents=True)
        (sd / "stack.yaml").write_text("name: s\nrecipes: [stale]\n")
        schema.load_stack_with_recipes(fixture, "s")
        assert capsys.readouterr().err == ""
        assert schema._err.warnings == 0


class TestOverlayShadowedRepoPath:
    """The paths-level helper, including the variety-ref case (see paths.catalog_relpath)."""

    def test_shadowed_variety_ref_returns_the_variety_repo_path(self, monkeypatch, tmp_path):
        _, home = _install(monkeypatch, tmp_path, overlay=["fam/vary"], repo=["fam/vary"])
        assert paths.overlay_shadowed_repo_path("recipes", "fam/vary") == (
            home / "catalog" / "recipes" / "fam" / "vary"
        )

    def test_overlay_only_returns_none(self, monkeypatch, tmp_path):
        _install(monkeypatch, tmp_path, overlay=["only-overlay"])
        assert paths.overlay_shadowed_repo_path("recipes", "only-overlay") is None

    def test_repo_only_returns_none(self, monkeypatch, tmp_path):
        _install(monkeypatch, tmp_path, repo=["only-repo"])
        assert paths.overlay_shadowed_repo_path("recipes", "only-repo") is None
