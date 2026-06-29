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
from harnessed.schema import McpServer, Recipe


def _recipe(name: str, *servers: McpServer) -> Recipe:
    return Recipe(name=name, servers=list(servers), root=Path("/tmp/fake-recipe"))


def _patch_recipes(monkeypatch, recipes: list[Recipe]) -> None:
    """Make _service_refs see exactly `recipes`, regardless of the stack name passed."""
    monkeypatch.setattr(launcher, "load_stack_with_recipes", lambda _root, _stack: (None, recipes))


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
