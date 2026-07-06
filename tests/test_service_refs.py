"""Unit tests for launcher._service_refs (T8).

`_service_refs(stack)` returns the distinct service names a stack's recipes reference via
`service:` MCP servers — the set the launcher must spin up as host-published sidecars. These
tests document that contract: de-dupe across recipes, preserve first-seen order, and ignore
servers that carry no `service:`. The catalog resolution behind it (`load_stack_with_recipes`)
is exercised elsewhere; here we monkeypatch it to keep the test unit-pure.
"""

from __future__ import annotations

from pathlib import Path

from harnessed import launcher
from harnessed.schema import McpServer, Recipe, Stack


def _recipe(name: str, *servers: McpServer) -> Recipe:
    return Recipe(name=name, servers=list(servers), root=Path("/tmp/fake-recipe"))


def _patch_recipes(monkeypatch, recipes: list[Recipe]) -> None:
    """Make _service_refs see exactly `recipes`, regardless of the stack name passed."""
    monkeypatch.setattr(launcher, "load_stack_with_recipes", lambda _root, _stack: (None, recipes))


def _patch(monkeypatch, stack: Stack, recipes: list[Recipe]) -> None:
    """Make _service_refs see exactly `stack` + `recipes`, regardless of the name passed."""
    monkeypatch.setattr(launcher, "load_stack_with_recipes", lambda _root, _stack: (stack, recipes))


def test_collects_referenced_service_names(monkeypatch):
    recipes = [
        _recipe("a", McpServer(name="s1", service="hindsight", transport="http")),
        _recipe("b", McpServer(name="s2", service="gbrain", transport="http")),
    ]
    _patch_recipes(monkeypatch, recipes)
    assert launcher._service_refs("any-stack") == ["hindsight", "gbrain"]


def test_dedupes_across_recipes_preserving_order(monkeypatch):
    # `hindsight` appears first, is referenced again later, and must not be repeated;
    # the distinct list keeps first-seen order.
    recipes = [
        _recipe(
            "a",
            McpServer(name="s1", service="hindsight", transport="http"),
            McpServer(name="s2", service="gbrain", transport="http"),
        ),
        _recipe("b", McpServer(name="s3", service="hindsight", transport="http")),
        _recipe("c", McpServer(name="s4", service="time", transport="http")),
    ]
    _patch_recipes(monkeypatch, recipes)
    assert launcher._service_refs("any-stack") == ["hindsight", "gbrain", "time"]


def test_recipe_without_service_servers_contributes_nothing(monkeypatch):
    # A recipe whose servers are all `command:`-based (no `service:`) adds no names; a recipe
    # with no servers at all adds none either.
    recipes = [
        _recipe("cmd-only", McpServer(name="s1", command="pnpm", args=["dlx", "hatago"])),
        _recipe("empty"),
        _recipe("svc", McpServer(name="s2", service="hindsight", transport="http")),
    ]
    _patch_recipes(monkeypatch, recipes)
    assert launcher._service_refs("any-stack") == ["hindsight"]


def test_no_services_returns_empty(monkeypatch):
    _patch_recipes(monkeypatch, [_recipe("cmd-only", McpServer(name="s1", command="pnpm"))])
    assert launcher._service_refs("any-stack") == []


def test_stack_level_services_are_included(monkeypatch):
    # A stack can attach a sidecar with NO MCP surface via its own `services:` list (e.g. a shared
    # `dolt sql-server`, MySQL-wire not MCP). Those must be started even when no recipe references
    # them through an MCP `service:` ref.
    stack = Stack(name="claude_beads-shared", harness="claude", recipes=["beads-shared"],
                  services=["beads-server"])
    _patch(monkeypatch, stack, [_recipe("beads-shared")])
    assert launcher._service_refs("any-stack") == ["beads-server"]


def test_stack_and_recipe_services_dedupe_recipe_first(monkeypatch):
    # Recipe MCP-ref services come first; a stack `services:` entry already covered by a recipe ref
    # is not repeated, and a new stack-only entry is appended after.
    stack = Stack(name="s", harness="claude", recipes=["a"], services=["gbrain", "beads-server"])
    recipes = [_recipe("a", McpServer(name="s1", service="gbrain", transport="http"))]
    _patch(monkeypatch, stack, recipes)
    assert launcher._service_refs("any-stack") == ["gbrain", "beads-server"]
