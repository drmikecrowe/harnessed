"""Tests for build-staleness detection (staleness.py + launch/test integration).

A profile is a function of its catalog inputs; `check_profile_fresh` must flag both a removed/renamed
recipe (existence → SchemaError) and an edited source (stamp mismatch → StaleProfileError).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harnessed import paths, staleness
from harnessed.assemble import assemble
from harnessed.schema import SchemaError


def _make_catalog(root: Path) -> None:
    """A minimal single-recipe stack on disk."""
    sd = root / "stacks" / "claude_x"
    sd.mkdir(parents=True)
    (sd / "stack.yaml").write_text("name: claude_x\nrecipes: [foo]\n", encoding="utf-8")
    rd = root / "recipes" / "foo"
    rd.mkdir(parents=True)
    (rd / "recipe.yaml").write_text("name: foo\ndescription: test recipe\n", encoding="utf-8")


@pytest.fixture()
def built(tmp_path, monkeypatch):
    """Assemble claude_x into a tmp XDG profiles root; return (catalog_root, recipe_dir)."""
    catalog = tmp_path / "catalog"
    _make_catalog(catalog)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    # assemble emits into <build-dir>/profiles/<stack>; profiles_root() = XDG/harnessed/profiles.
    assemble(catalog, "claude_x", paths.profiles_root().parent, "claude")
    assert paths.is_built("claude_x", "claude")
    return catalog, catalog / "recipes" / "foo"


def test_fresh_profile_passes(built):
    catalog, _ = built
    # No exception → fresh.
    staleness.check_profile_fresh(catalog, "claude_x", "claude")


def test_stamp_is_written_and_readable(built):
    _, _ = built
    prof = paths.profile_dir("claude_x", "claude")
    assert (prof / staleness.STAMP_FILE).is_file()
    assert staleness.read_stamp(prof)  # non-empty


def test_edited_recipe_is_stale(built):
    catalog, recipe_dir = built
    (recipe_dir / "recipe.yaml").write_text(
        "name: foo\ndescription: EDITED\n", encoding="utf-8"
    )
    with pytest.raises(staleness.StaleProfileError):
        staleness.check_profile_fresh(catalog, "claude_x", "claude")


def test_new_file_in_recipe_is_stale(built):
    catalog, recipe_dir = built
    (recipe_dir / "extra.md").write_text("new file", encoding="utf-8")
    with pytest.raises(staleness.StaleProfileError):
        staleness.check_profile_fresh(catalog, "claude_x", "claude")


def test_removed_recipe_raises_schema_error(built):
    catalog, recipe_dir = built
    # Rename the recipe out from under the stack (the exact bug this feature guards).
    recipe_dir.rename(recipe_dir.parent / "foo-renamed")
    with pytest.raises(SchemaError):
        staleness.check_profile_fresh(catalog, "claude_x", "claude")


def test_stack_resolves_true_for_a_live_stack(built):
    catalog, _ = built
    assert staleness.stack_resolves(catalog, "claude_x")


def test_stack_resolves_false_when_the_recipe_is_gone(built):
    """Same condition `check_profile_fresh` raises SchemaError for, asked as a question."""
    catalog, recipe_dir = built
    recipe_dir.rename(recipe_dir.parent / "foo-renamed")
    assert not staleness.stack_resolves(catalog, "claude_x")


def test_stack_resolves_false_for_an_unknown_stack(built):
    catalog, _ = built
    assert not staleness.stack_resolves(catalog, "never-existed")


def test_stack_resolves_is_independent_of_the_profile(built):
    """A stack stays resolvable with no profile at all — this asks about the CATALOG, not the build.

    Load-bearing for the omp block prune: nothing ever deletes a profile dir, so profile existence
    is useless as a liveness signal and the catalog is the only thing that can say a stack is gone.
    """
    catalog, _ = built
    import shutil

    shutil.rmtree(paths.profile_dir("claude_x", "claude"))
    assert not paths.is_built("claude_x", "claude")
    assert staleness.stack_resolves(catalog, "claude_x")


def test_missing_stamp_is_stale(built):
    catalog, _ = built
    (paths.profile_dir("claude_x", "claude") / staleness.STAMP_FILE).unlink()
    with pytest.raises(staleness.StaleProfileError):
        staleness.check_profile_fresh(catalog, "claude_x", "claude")


def test_stamp_deterministic(built):
    catalog, _ = built
    from harnessed.schema import load_stack_with_recipes

    stack, recipes = load_stack_with_recipes(catalog, "claude_x")
    a = staleness.compute_stamp(catalog, stack, recipes)
    b = staleness.compute_stamp(catalog, stack, recipes)
    assert a == b
