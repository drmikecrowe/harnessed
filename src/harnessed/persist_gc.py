"""Persist directory lifecycle management — list and prune (GC).

Persist dirs under persist_root() accumulate indefinitely; this module provides
the list/prune surface for `harnessed persist-list` and `harnessed persist-prune`.

Since project_hash is a one-way SHA1[:8] digest, orphan auto-detection is not
supported. Explicit prune requires the original project path so the hash can be
re-derived and the correct dir targeted — no guessing about what the hash once
represented.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from . import paths


@dataclass(frozen=True)
class PersistEntry:
    """One row in the persist listing: recipe / project_hash / name triplet + host dir."""

    recipe: str
    project_hash: str
    name: str
    host_dir: Path

    @property
    def size_bytes(self) -> int:
        """Disk usage of all files under this persist dir."""
        return _dir_size(self.host_dir)


def list_entries() -> list[PersistEntry]:
    """Return all persist entries currently on disk under persist_root().

    Walks the three-level tree: persist/<recipe>/<project_hash>/<name>.
    Returns an empty list if persist_root() does not exist yet.
    """
    root = paths.persist_root()
    if not root.is_dir():
        return []
    entries: list[PersistEntry] = []
    for recipe_dir in sorted(root.iterdir()):
        if not recipe_dir.is_dir():
            continue
        for hash_dir in sorted(recipe_dir.iterdir()):
            if not hash_dir.is_dir():
                continue
            for name_dir in sorted(hash_dir.iterdir()):
                if not name_dir.is_dir():
                    continue
                entries.append(
                    PersistEntry(
                        recipe=recipe_dir.name,
                        project_hash=hash_dir.name,
                        name=name_dir.name,
                        host_dir=name_dir,
                    )
                )
    return entries


def prune_project(recipe: str, project_path: str | Path, name: str | None = None) -> list[Path]:
    """Remove persist dir(s) for a specific recipe + project.  Returns removed dirs.

    Derives the project hash from the given path (same one-way digest used at launch) so
    the caller need not know the hash.

    If `name` is given, removes only that single entry under the recipe/hash dir.
    If `name` is None, removes ALL entries for this recipe + project combination.

    Empty parent dirs (the hash-level and recipe-level dirs) are cleaned up automatically
    after removal so persist_root() does not accumulate empty skeleton dirs.

    Returns the list of host dirs that were actually removed (may be empty if the
    target did not exist).
    """
    ph = paths.project_hash(project_path)
    hash_dir = paths.persist_root() / recipe / ph
    if not hash_dir.is_dir():
        return []

    removed: list[Path] = []
    if name is not None:
        target = hash_dir / name
        if target.is_dir():
            shutil.rmtree(target)
            removed.append(target)
    else:
        for d in sorted(hash_dir.iterdir()):
            if d.is_dir():
                shutil.rmtree(d)
                removed.append(d)

    # Clean up empty skeleton dirs left behind (hash-level, then recipe-level).
    _prune_empty_parents(hash_dir, stop=paths.persist_root())
    return removed


def _dir_size(path: Path) -> int:
    """Total size in bytes of all files (recursively) under path."""
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


def _prune_empty_parents(d: Path, stop: Path) -> None:
    """Remove d and its ancestors up to (not including) stop while they are empty dirs."""
    while d != stop and d.is_dir():
        try:
            d.rmdir()  # succeeds only when the dir is empty
        except OSError:
            break
        d = d.parent


def _fmt_size(n: int) -> str:
    """Human-readable byte count (KiB / MiB / GiB), rounded to one decimal place."""
    for unit, threshold in (("GiB", 1 << 30), ("MiB", 1 << 20), ("KiB", 1 << 10)):
        if n >= threshold:
            return f"{n / threshold:.1f} {unit}"
    return f"{n} B"
