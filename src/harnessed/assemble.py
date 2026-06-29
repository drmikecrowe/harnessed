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

import os
from dataclasses import dataclass
from pathlib import Path

from . import emit
from .schema import (
    McpServer,
    Recipe,
    Stack,
    load_service,
    load_stack_with_recipes,
    validate_no_raw_npm,
    validate_pin,
)
from .synclinks import CollisionError, LinkSyncer


@dataclass
class AssembleResult:
    stack: Stack
    recipes: list[Recipe]
    profile_dir: Path
    servers: list[McpServer]
    baked: list[McpServer]


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


def _resolve_service_servers(servers: list[McpServer], root: Path | None) -> list[McpServer]:
    """Resolve ``service:``-referenced MCP servers to network-native URLs (plan 04-01 / SVC-01).

    A recipe declares a service-referenced server with ``service: <name>`` and NO command
    (``is_stdio_child`` is False). The assembler resolves the service name → port by reading
    ``services/<name>/service.yaml`` and sets ``url`` + ``transport`` so ``emit._hatago_entry``
    emits a ``{url, type: http}`` hatago proxy entry. The resolution lives HERE so emit stays
    dumb (it already emits network-native servers as ``{url, type}`` — no emit change needed).
    """
    for server in servers:
        if server.service and not server.is_stdio_child:
            svc = load_service(root, server.service)
            # Rootless model (plan 04-01 fix): no bridge — services publish to 0.0.0.0 and peers
            # reach them via the podman host gateway `host.containers.internal`. A rootless bridge
            # is unsupported on most hosts (netavark "Operation not supported"), so DNS-by-service-
            # name over harnessed-net was replaced with the host-gateway address.
            server.url = f"http://host.containers.internal:{svc.port}/mcp"
            if server.transport == "stdio":
                server.transport = "http"
    return servers


def assemble(
    root: Path | None, stack_name: str, build_dir: Path, *, strict: bool = False
) -> AssembleResult:
    """Assemble a stack into a profile. `root` None → resolve recipes/stacks/services across the
    catalog roots (user overlay first); a Path restricts resolution to that single root.

    `strict` → reject unknown recipe-manifest fields (typo guardrail); `harnessed build` passes it
    on by default, `--no-strict` opts out."""
    root = Path(root) if root is not None else None
    build_dir = Path(build_dir)

    stack, recipes = load_stack_with_recipes(root, stack_name, strict=strict)

    # Fail-fast recipe validation (BLD-03 + ASM-02): reject raw npm/npx and floating Dockerfile refs
    # BEFORE any file is emitted. Recipes are harness-independent (any harness consumes the same
    # Claude-canonical profile; harness-specific needs are handled inside the recipe Dockerfile via
    # ${HARNESS}), so there is no harness-compat gate.
    for recipe in recipes:
        validate_no_raw_npm(recipe)
        dockerfile = recipe.root / "Dockerfile"
        if dockerfile.is_file():
            validate_pin(recipe.name, dockerfile.read_text(encoding="utf-8"))  # ASM-02 (T-08-01)

    servers = _resolve_service_servers(_merge_servers(recipes), root)

    profile_dir = build_dir / "profiles" / stack.name

    emit.reset_profile(profile_dir)
    emit.write_mcp_json(profile_dir)
    emit.write_settings_json(profile_dir, servers)
    emit.write_hatago_config(profile_dir, servers)
    # ASM-03 — derived Dockerfile, with a final supply-chain scan layer (BLD-02) unless the build
    # opted out via --no-security-scans (HARNESSED_NO_SCANS).
    with_scan = os.environ.get("HARNESSED_NO_SCANS") != "true"
    emit.write_derived_dockerfile(profile_dir, stack, recipes, with_scan=with_scan)

    # Fan each recipe's standalone skills/commands into the harness-native profile tree
    # (<profile>/.claude/{skills,commands}). The launcher mounts these dirs into the instance and
    # the capability test reads them back, so the fan-out is what makes a skill recipe observable.
    syncer = LinkSyncer()
    for recipe in recipes:
        syncer.add_recipe(recipe)
    syncer.fan(profile_dir / ".claude")

    # stdio children are baked into the harness/stack image and spawned by the in-container hatago
    # (hatago-consolidation); kept for reporting. No separate baked-servers.json is written.
    baked = [s for s in servers if s.is_stdio_child]

    return AssembleResult(
        stack=stack,
        recipes=recipes,
        profile_dir=profile_dir,
        servers=servers,
        baked=baked,
    )
