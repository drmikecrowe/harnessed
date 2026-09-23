"""`_service_refs` must union recipe-declared services with the stack's own.

Before harnessed-7rx.1 a service with no MCP surface (beads-server speaks MySQL) could only be
attached by a STACK, so a bare recipe list could not describe a working stack.
"""
from __future__ import annotations

import textwrap

from harnessed.launcher import _service_refs


def _catalog(tmp_path, *, recipe_services: str, stack_services: str):
    root = tmp_path / "catalog"
    rd = root / "recipes" / "r1"
    rd.mkdir(parents=True)
    (rd / "recipe.yaml").write_text(f"name: r1\n{recipe_services}")
    sd = root / "stacks" / "s1"
    sd.mkdir(parents=True)
    (sd / "stack.yaml").write_text(textwrap.dedent(f"""\
        name: s1
        recipes: [r1]
        {stack_services}
        """))
    return root


def test_recipe_declared_service_is_collected(tmp_path, monkeypatch):
    root = _catalog(tmp_path, recipe_services="services: [beads-server]\n", stack_services="services: []")
    monkeypatch.setattr("harnessed.paths.catalog_roots", lambda: [root])
    assert _service_refs("s1") == ["beads-server"]


def test_stack_and_recipe_services_are_unioned_without_duplicates(tmp_path, monkeypatch):
    root = _catalog(
        tmp_path,
        recipe_services="services: [beads-server]\n",
        stack_services="services: [beads-server, other-svc]",
    )
    monkeypatch.setattr("harnessed.paths.catalog_roots", lambda: [root])
    assert _service_refs("s1") == ["beads-server", "other-svc"]


def test_stack_only_services_still_work(tmp_path, monkeypatch):
    """Regression guard: existing stacks that declare services themselves must be unaffected."""
    root = _catalog(tmp_path, recipe_services="", stack_services="services: [beads-server]")
    monkeypatch.setattr("harnessed.paths.catalog_roots", lambda: [root])
    assert _service_refs("s1") == ["beads-server"]
