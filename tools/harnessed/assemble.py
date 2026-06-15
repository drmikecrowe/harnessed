"""Orchestrate the emit-only assembly of a stack into a committed profile + hatago config.

Flow (design §7/§15, D-04/D-12/D-13):
  read stack + its recipes
    → fan skills/commands into the harness profile (fail-fast on name collision)
    → merge every recipe's mcp.servers into one hatago.config.json (child stdio servers)
    → derive the harness .mcp.json (exactly ONE entry → the hatago endpoint)
    → record which stdio servers the hatago image must bake
    → emit all of the above into the mounted build dir.

EMIT ONLY: nothing here invokes podman/docker or mounts a daemon socket.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import emit
from .schema import McpServer, Recipe, Stack, load_stack_with_recipes
from .synclinks import CollisionError, LinkSyncer


@dataclass
class AssembleResult:
    stack: Stack
    recipes: list[Recipe]
    profile_dir: Path
    servers: list[McpServer]
    baked: list[McpServer]
    skills: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)


def _merge_servers(recipes: list[Recipe]) -> list[McpServer]:
    """Collect every recipe's MCP servers, failing fast on a duplicate server name."""
    servers: list[McpServer] = []
    owner: dict[str, str] = {}
    for recipe in recipes:
        for server in recipe.servers:
            if server.name in owner:
                raise CollisionError(
                    f"mcp server name collision: '{server.name}' is declared by two recipes "
                    f"('{owner[server.name]}' and '{recipe.name}'). Rename one server."
                )
            owner[server.name] = recipe.name
            servers.append(server)
    return servers


def assemble(root: Path, stack_name: str, build_dir: Path) -> AssembleResult:
    root = Path(root)
    build_dir = Path(build_dir)

    stack, recipes = load_stack_with_recipes(root, stack_name)

    # Fan skills/commands (registers + collision-checks before any file is written).
    syncer = LinkSyncer()
    for recipe in recipes:
        syncer.add_recipe(recipe)

    servers = _merge_servers(recipes)

    profile_dir = build_dir / "profiles" / stack.name
    harness_dir = profile_dir / stack.harness_config_dir

    emit.reset_profile(profile_dir)
    emit.ensure_profile_tree(harness_dir)
    syncer.fan(harness_dir)
    emit.write_mcp_json(harness_dir)
    emit.write_hatago_config(profile_dir, servers)

    baked = [s for s in servers if s.is_stdio_child]
    emit.write_baked_manifest(profile_dir, stack, baked)

    return AssembleResult(
        stack=stack,
        recipes=recipes,
        profile_dir=profile_dir,
        servers=servers,
        baked=baked,
        skills=sorted(syncer.skills),
        commands=sorted(syncer.commands),
    )
