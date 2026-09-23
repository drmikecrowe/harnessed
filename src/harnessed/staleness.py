"""Build-staleness detection for assembled stack profiles.

A profile under `$XDG_DATA_HOME/harnessed/profiles/<stack>/` is a pure function of its catalog
inputs: the stack.yaml plus every recipe directory it references (recipe.yaml, Dockerfile, fanned
skills/commands, …). `paths.is_built()` only checks that a profile *exists* — it never checks that
the profile still matches those inputs. So a recipe rename/removal (or an edit) silently orphans an
already-built stack: `harnessed launch` keeps using the stale profile/image.

This module closes that gap with two checks (see `check_profile_fresh`):

  1. **Existence (always on, cheap):** re-resolve the stack's recipes; a missing recipe/stack raises
     `SchemaError` — the exact failure a fresh `harnessed build` would hit.
  2. **Edit detection (hash stamp):** at assemble time we stamp the profile with a hash of its
     inputs (`.build-stamp`); a mismatch on launch means the sources changed since it was built.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import paths
from .schema import Recipe, SchemaError, Stack, load_stack_with_recipes

# File written into each profile dir holding the input hash.
STAMP_FILE = ".build-stamp"
# Bump when the hashing scheme below changes, to force every existing stamp to read as stale.
_STAMP_SCHEME = 1


class StaleProfileError(Exception):
    """A built profile no longer matches the catalog inputs that produced it."""


def _feed_dir(h: "hashlib._Hash", root: Path) -> None:
    """Feed every file under `root` (sorted by relative path; path + bytes) into hash `h`."""
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.is_symlink():
            h.update(p.relative_to(root).as_posix().encode())
            h.update(b"\0")
            h.update(p.read_bytes())
            h.update(b"\0")


def _stack_yaml(root: Path | None, stack_name: str) -> Path:
    """Resolve the stack.yaml the same way the loader/assembler does (single root vs catalog roots)."""
    stack_dir = (root / "stacks" / stack_name) if root is not None else paths.find_in_catalog("stacks", stack_name)
    return stack_dir / "stack.yaml"


def compute_stamp(root: Path | None, stack: Stack, recipes: list[Recipe]) -> str:
    """Deterministic hash of the inputs that produce this stack's profile.

    Covers: the harnessed version + hashing scheme, the stack.yaml bytes, and every referenced
    recipe directory (recursively). Recipes are hashed in name order so the result is
    resolution-order-independent.
    """
    from . import __version__

    h = hashlib.sha256()
    h.update(f"scheme:{_STAMP_SCHEME}\0harnessed:{__version__}\0".encode())
    h.update(b"stack\0")
    h.update(_stack_yaml(root, stack.name).read_bytes())
    h.update(b"\0")
    for recipe in sorted(recipes, key=lambda r: r.name):
        h.update(f"recipe:{recipe.name}\0".encode())
        _feed_dir(h, recipe.root)
    return h.hexdigest()


def write_stamp(profile_dir: Path, stamp: str) -> None:
    """Persist `stamp` into the profile so a later launch can detect staleness."""
    (profile_dir / STAMP_FILE).write_text(json.dumps({"stamp": stamp}) + "\n", encoding="utf-8")


def read_stamp(profile_dir: Path) -> str | None:
    """Return the stored stamp, or None if absent/unreadable (→ treated as stale)."""
    f = profile_dir / STAMP_FILE
    if not f.is_file():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8")).get("stamp")
    except (ValueError, OSError):
        return None


def stack_resolves(root: Path | None, stack_name: str) -> bool:
    """True if `stack_name` still resolves to a stack.yaml AND every recipe it references.

    Check 1 of `check_profile_fresh` (existence), asked as a question instead of an exception. False
    means a fresh `harnessed build` of that stack would fail and `container_run` would refuse to
    launch it — the strongest "this stack is gone" signal the catalog offers, and the only one that
    does not depend on a profile dir (nothing ever deletes those).
    """
    try:
        load_stack_with_recipes(root, stack_name)
    except SchemaError:
        return False
    return True


def check_profile_fresh(root: Path | None, stack_name: str, harness: str, *, strict: bool = False) -> None:
    """Raise if the built profile for `stack_name`/`harness` no longer matches the current catalog.

    Raises `SchemaError` when a referenced recipe/stack no longer resolves (existence check), or
    `StaleProfileError` when the inputs changed since assembly (stamp missing or mismatched). Returns
    None when the profile is fresh. Assumes a profile already exists (call after `paths.is_built`).
    """
    stack, recipes = load_stack_with_recipes(root, stack_name, strict=strict)  # existence check
    stored = read_stamp(paths.profile_dir(stack_name, harness))
    if stored is None:
        raise StaleProfileError(
            f"profile for '{stack_name}' ({harness}) predates staleness tracking (no {STAMP_FILE}) — rebuild to verify it"
        )
    if stored != compute_stamp(root, stack, recipes):
        raise StaleProfileError(
            f"profile for '{stack_name}' ({harness}) is stale: its stack/recipe sources changed since it was built"
        )
