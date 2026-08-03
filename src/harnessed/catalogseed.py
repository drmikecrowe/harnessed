"""Seed the user's own catalog and config from what the wheel ships.

First run has an empty `~/.config/harnessed`. These lay down the pieces a user is expected to own
and edit — the overlay catalog links, a starter recipe, the extra-tools list, the docs clone — and
each is idempotent and NON-destructive: an existing user file is never overwritten, because it is
theirs once it exists.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile

from pathlib import Path

import typer

from . import paths
from .layout import _catalog_base, _harnessed_dir
from .proc import _run
from .console import _err, _out


def _ensure_local_catalog_links() -> None:
    """Ensure the user's overlay dirs exist; symlink them into `catalog-local/` in a source checkout.

    The overlay dirs are created unconditionally (they are how `find_in_catalog` sees user content).

    The symlinks are a DEV convenience — browsing/editing your overlay from inside the checkout — and
    they are deliberately parked in `catalog-local/`, NOT inside `catalog/` (paths.local_links_dir):

      * `catalog/` is shipped inside the wheel, and setuptools FOLLOWS symlinks, so a `<kind>.local`
        link inside it would package the user's private overlay into a distributable artifact.
      * They are keyed to harnessed's own checkout, never the CWD — running `harnessed build` from an
        unrelated project that happens to have a `catalog/` must not scribble symlinks into it, and a
        wheel install must not scribble them into site-packages.
    """
    user_catalog_root = paths.user_catalog()
    for kind in ("agents", "recipes", "services", "stacks"):
        (user_catalog_root / kind).mkdir(parents=True, exist_ok=True)

    _seed_user_default_recipe()

    checkout = paths.source_checkout()
    if checkout is None:
        return

    # MIGRATION: drop the pre-move `catalog/<kind>.local` links. Every checkout that has ever run
    # `harnessed build` has them, and they point into the user's private overlay from INSIDE the dir
    # we now ship — leave them and a `uv build` would package that overlay. Only ever unlink a
    # symlink, never real content.
    for kind in ("agents", "recipes", "services", "stacks"):
        stale = checkout / "catalog" / f"{kind}.local"
        if stale.is_symlink():
            stale.unlink()

    links_dir = paths.local_links_dir(checkout)
    links_dir.mkdir(parents=True, exist_ok=True)

    for kind in ("agents", "recipes", "services", "stacks"):
        target = links_dir / kind
        dest = user_catalog_root / kind
        if target.is_symlink():
            if target.resolve() == dest.resolve():
                continue  # already correct — no-op
            _err.print(
                f"[bold red]error:[/bold red] {target} is a symlink pointing at the wrong destination "
                f"(expected -> {dest}). Remove it manually to proceed."
            )
            raise typer.Exit(1)
        elif target.exists():
            _err.print(
                f"[bold red]error:[/bold red] {target} already exists and is not a symlink. "
                f"Remove it manually to proceed."
            )
            raise typer.Exit(1)
        else:
            target.symlink_to(dest)


_SEEDED_DEFAULT_BANNER = """\
# ---------------------------------------------------------------------------------------------
# SEEDED BY HARNESSED on first run — this copy is YOURS. Edit it freely.
#
# The user overlay is searched FIRST and wins on a name clash, so this file now SHADOWS the
# `default` recipe shipped in harnessed's own catalog. That is the point (a baseline you control)
# and also the one cost: improvements to the shipped default recipe will never reach this copy.
# Delete this directory to fall back to the shipped one; harnessed re-seeds it on the next run.
# ---------------------------------------------------------------------------------------------
"""


def _seed_user_default_recipe() -> None:
    """Copy the shipped `default` recipe into the user's overlay, once, on first run.

    `default` is what `--extends` resolves to for every dynamic (`--recipe`) stack, so it is the
    baseline a user is most likely to want to change — and the least discoverable place to start
    from a blank directory. Seeding a working copy turns "author a recipe from nothing" into "edit
    the one that is already in effect".

    First-run only, and never destructive: any existing `recipes/default` (seeded earlier, or
    hand-authored) is left exactly as it is. The copy dereferences symlinks, so the overlay holds
    real content rather than links back into an installation the user may later replace.
    """
    dest = paths.user_catalog() / "recipes" / "default"
    # `is_symlink()` as well as `exists()`: a DANGLING symlink at `recipes/default` reports
    # exists() == False (it resolves the target), and the rename below would then fail with
    # NotADirectoryError and take the whole launch down. A link the user put there is theirs
    # either way — broken or not, it is not ours to replace.
    if dest.exists() or dest.is_symlink():
        return

    src = paths.harnessed_home() / "catalog" / "recipes" / "default"
    if not (src / "recipe.yaml").is_file():
        return  # nothing to seed (a catalog root without the shipped baseline)

    dest.parent.mkdir(parents=True, exist_ok=True)
    # A PRIVATE staging dir per process, not one shared `.default.seeding`. Two first launches
    # racing (two shells, a shell plus an editor task) would otherwise stage into the same path,
    # and the first to finish would rmtree the other's half-written copy out from under it —
    # both launches failing where neither had to. mkdtemp gives each its own, in the same
    # directory so the rename stays atomic within one filesystem.
    tmp = Path(tempfile.mkdtemp(prefix=".default.seeding-", dir=dest.parent))
    try:
        # symlinks=False: dereference. A link into site-packages breaks the moment harnessed is
        # upgraded or removed, and the whole point of the seed is a copy the user owns outright.
        shutil.copytree(src, tmp, symlinks=False, dirs_exist_ok=True)
        manifest = tmp / "recipe.yaml"
        manifest.write_text(_SEEDED_DEFAULT_BANNER + manifest.read_text(), encoding="utf-8")
        # Rename last so an interrupted seed never leaves a half-copied recipe at the real name,
        # where the `dest.exists()` guard above would then treat it as complete forever.
        tmp.rename(dest)
    except OSError:
        # Losing the race is a SUCCESS: the other process seeded the same bytes, and `dest` is
        # now a complete recipe. Only re-raise when the destination really is not there, so a
        # genuine failure (no space, no permission) still surfaces instead of seeding nothing
        # and saying nothing.
        shutil.rmtree(tmp, ignore_errors=True)
        if not (dest / "recipe.yaml").is_file():
            raise


def _ensure_docs_wiki_clone() -> None:
    """Bootstrap docs/ as an unpinned live clone of the repo's GitHub wiki, when missing.

    docs/ is a plain git clone (not a submodule) of <origin>.wiki.git -- no pinned
    commit, no pointer-bump PRs; pull it yourself with `git -C docs pull`. Only runs
    inside the harnessed SOURCE CHECKOUT; leaves an existing docs/ alone.

    Keyed to harnessed's own checkout, never the CWD: keyed to the CWD this would read an unrelated
    project's `origin` and clone THAT repo's wiki into ITS docs/ merely because it happened to have
    a `catalog/` dir — and would be meaningless in a wheel install.
    """
    checkout = paths.source_checkout()
    if checkout is None:
        return
    docs_dir = checkout / "docs"
    if docs_dir.exists():
        return
    try:
        origin_url = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=checkout, capture_output=True, text=True, check=True,
        ).stdout.strip()
    except subprocess.CalledProcessError:
        return
    wiki_url = re.sub(r"\.git$", "", origin_url) + ".wiki.git"
    try:
        _run(["git", "clone", wiki_url, str(docs_dir)])
    except subprocess.CalledProcessError:
        _err.print(f"[yellow]warning:[/yellow] could not clone docs wiki ({wiki_url}); docs/ left missing")


def _ensure_extra_tools() -> None:
    """Seed the USER-owned extra-tools list from the shipped default when it is absent.

    Source of truth is `~/.config/harnessed/extra-tools.txt` (paths.extra_tools_path). Seeding it from
    `catalog/base/extra-tools.default.txt` (migrating a pre-move repo-root `extra-tools.txt` if one is
    still lying around) means a fresh clone, git worktree, or wheel install builds with no hand-copying.

    It is STAGED INTO THE BUILD CONTEXT — never back into `catalog/` — by `_staged_build_context`.
    """
    user_file = paths.extra_tools_path()
    if user_file.exists():
        return
    legacy = _harnessed_dir() / "extra-tools.txt"  # pre-move repo-root location
    seed = legacy if legacy.exists() else _catalog_base("extra-tools.default.txt")
    if seed.exists():
        user_file.parent.mkdir(parents=True, exist_ok=True)
        user_file.write_text(seed.read_text())


def _update_recipe_dirs() -> list[Path]:
    """Every recipe dir across the active catalog roots (user overlay + repo), deduped by ref.

    Enumerated by walking for `recipe.yaml` rather than via `list_catalog`, because a recipe FAMILY
    (`beads/stealth`) nests one level down and `update` wants every manifest, family member or not.
    """
    seen: set[str] = set()
    dirs: list[Path] = []
    for root in paths.catalog_roots():
        recipes = root / "recipes"
        if not recipes.is_dir():
            continue
        for manifest in sorted(recipes.rglob("recipe.yaml")):
            ref = str(manifest.parent.relative_to(recipes))
            if ref in seen:        # user overlay wins, exactly as everywhere else
                continue
            seen.add(ref)
            dirs.append(manifest.parent)
    return dirs
