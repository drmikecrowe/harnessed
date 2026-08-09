"""AC-1 — one pin, one place. Executable, over the real catalog.

Spec: `.agents/plans/2026-08-08-recipe-rtk-pattern.md` §3 AC-1 — *"Every upstream version/ref string
appears exactly once across `recipe.yaml` + `install.sh` + `Dockerfile` for a given recipe."*

The criterion existed from the start and nothing enforced it, which is how three recipes came to
declare a `tools:` pin in `recipe.yaml` and then repeat the same version as a shell literal in
`install.sh`, kept in sync by a comment saying "keep these in lockstep". Two of the three literals
were never referenced at all — dead weight that had already drifted once (#323).

Scoped deliberately to the ONE duplication shape this phase removes: a literal in `install.sh`
whose value equals a version the same recipe's `tools:` already pins. AC-1's full reach (Dockerfile
ARGs, install.refs, cross-file ref strings) is not asserted here; claiming it would be the
fabricated-coverage failure the plan warns about. What IS asserted cannot regress.
"""

import re

import pytest

from harnessed import paths
from harnessed.schema import SchemaError, load_recipe

# A recipe may repeat a `tools:` version ONLY with a stated reason and a way out. Each entry is a
# debt, not a policy — remove it when the recipe stops needing the second copy.
_KNOWN_DUPLICATES = {
    "context-mode": (
        "CONTEXT_MODE_VERSION feeds `omp plugin install context-mode@$VER`, a SECOND install "
        "channel that mise's `tools:` pin cannot reach. Deleting it would break the omp extension "
        "rather than de-duplicate anything. Needs a mechanism that hands a `tools:` version to the "
        "install env — tracked as Phase 1b, not fixable by deletion."
    ),
}

_ASSIGN_RE = re.compile(r'^\s*([A-Z][A-Z0-9_]*)=["\']?([^"\'\s#]+)')


def _recipe_dirs():
    root = paths.harnessed_home() / "catalog" / "recipes"
    return sorted(d for d in root.rglob("*") if (d / "recipe.yaml").is_file())


def _duplicated_tool_versions(recipe_dir):
    """(var, value) pairs in install.sh whose value equals a version this recipe's `tools:` pins."""
    try:
        recipe = load_recipe(recipe_dir)
    except (SchemaError, OSError):
        return []
    pinned = {spec.rpartition("@")[2] for spec in recipe.tools if "@" in spec}
    script = recipe_dir / "install.sh"
    if not pinned or not script.is_file():
        return []
    body = script.read_text(encoding="utf-8", errors="replace")
    out = []
    for line in body.splitlines():
        m = _ASSIGN_RE.match(line)
        if m and m.group(2) in pinned:
            out.append((m.group(1), m.group(2)))
    return out


@pytest.mark.parametrize("recipe_dir", _recipe_dirs(), ids=lambda d: d.name)
def test_no_install_script_repeats_a_tools_pin(recipe_dir):
    """The pin lives in `tools:`. A shell literal holding the same string is a second source of
    truth that only a comment keeps aligned — and comments do not fail builds."""
    duplicates = _duplicated_tool_versions(recipe_dir)
    if recipe_dir.name in _KNOWN_DUPLICATES:
        pytest.skip(f"known duplication: {_KNOWN_DUPLICATES[recipe_dir.name]}")
    assert not duplicates, (
        f"{recipe_dir.name}/install.sh declares {duplicates}, which its recipe.yaml `tools:` "
        f"already pins. Delete the literal, or add a reasoned entry to _KNOWN_DUPLICATES."
    )


def test_the_allowlist_names_only_recipes_that_still_duplicate():
    """An allowlist that outlives its reason is how a lint stops meaning anything.

    Every entry must still be a real duplication; when the recipe is fixed, the entry must go with
    it. This is the half of an exemption mechanism that usually gets left out.
    """
    stale = []
    for recipe_dir in _recipe_dirs():
        if recipe_dir.name in _KNOWN_DUPLICATES and not _duplicated_tool_versions(recipe_dir):
            stale.append(recipe_dir.name)
    assert not stale, f"{stale} no longer duplicate a tools: pin — remove them from _KNOWN_DUPLICATES"


def test_the_allowlist_names_only_recipes_that_exist():
    names = {d.name for d in _recipe_dirs()}
    assert set(_KNOWN_DUPLICATES) <= names, (
        f"{set(_KNOWN_DUPLICATES) - names} are not recipes — a stale exemption silently widens "
        f"the lint's blind spot"
    )


def test_the_lint_actually_detects_the_shape_it_claims_to(tmp_path):
    """The detector itself, proven against a constructed duplicate.

    Without this, deleting the last real duplicate would leave a lint that passes because it finds
    nothing anywhere — indistinguishable from one that works.
    """
    d = tmp_path / "dup"
    d.mkdir()
    (d / "recipe.yaml").write_text("name: dup\ntools:\n  - npm:thing@1.2.3\ninstall:\n  script: install.sh\n")
    (d / "install.sh").write_text('#!/usr/bin/env bash\nTHING_VERSION="1.2.3"\necho "$THING_VERSION"\n')
    assert _duplicated_tool_versions(d) == [("THING_VERSION", "1.2.3")]

    (d / "install.sh").write_text('#!/usr/bin/env bash\nTHING_VERSION="9.9.9"\n')
    assert _duplicated_tool_versions(d) == [], "a DIFFERENT version is not a duplicate of the pin"
