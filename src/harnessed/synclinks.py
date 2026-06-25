"""Fan recipe skills/commands into harness-native profile paths, fail-fast on collision.

Ported behavior of the host `sync-plugin-links` prior art (design §7, RCP-04, D-13):
each recipe ships standalone skill/command dirs; this fans them into the harness's
canonical layout under the target profile (claude → `.claude/skills/<name>`,
`.claude/commands/<name>`). Two recipes shipping the same skill/command name is a
**fail-fast** error that names BOTH source paths — never a silent last-wins overwrite.

EMIT-ONLY: copies files within the mounted build dir; never touches the daemon.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .schema import FileExt, Recipe


class CollisionError(Exception):
    """Two recipes ship a skill/command with the same harness-native name."""


@dataclass
class LinkSyncer:
    """Accumulate skills/commands across every recipe in a stack, detecting collisions.

    Names are registered (and checked) as recipes are added, so a collision aborts the
    build before any file is copied. `fan()` then materializes the registered tree.
    """

    # name -> (source dir, owning recipe name)
    skills: dict[str, tuple[Path, str]] = field(default_factory=dict)
    commands: dict[str, tuple[Path, str]] = field(default_factory=dict)

    def add_recipe(self, recipe: Recipe) -> None:
        self._register(recipe, recipe.skills, self.skills, "skill")
        self._register(recipe, recipe.commands, self.commands, "command")

    @staticmethod
    def _register(
        recipe: Recipe,
        entries: list[FileExt],
        registry: dict[str, tuple[Path, str]],
        kind: str,
    ) -> None:
        for entry in entries:
            src = (recipe.root / entry.path).resolve()
            if not src.is_dir():
                raise CollisionError(
                    f"recipe '{recipe.name}' declares {kind} '{entry.path}' "
                    f"but the source dir does not exist: {src}"
                )
            name = entry.name
            if name in registry:
                prev_src, prev_recipe = registry[name]
                raise CollisionError(
                    f"{kind} name collision: '{name}' is shipped by two recipes.\n"
                    f"  recipe '{prev_recipe}': {prev_src}\n"
                    f"  recipe '{recipe.name}': {src}\n"
                    f"Rename one of them or drop a recipe from the stack."
                )
            registry[name] = (src, recipe.name)

    def fan(self, harness_config_dir: Path) -> None:
        """Copy every registered skill/command dir into the harness config tree."""
        self._fan_into(harness_config_dir / "skills", self.skills)
        self._fan_into(harness_config_dir / "commands", self.commands)

    @staticmethod
    def _fan_into(dest_root: Path, registry: dict[str, tuple[Path, str]]) -> None:
        dest_root.mkdir(parents=True, exist_ok=True)
        for name, (src, _recipe) in sorted(registry.items()):
            shutil.copytree(src, dest_root / name, dirs_exist_ok=False)
