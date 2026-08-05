"""Which recipe primitives each execution backend can actually honor (BACKENDS.md §4).

A stack runs on any backend; it does not follow that every declaration in it is HONORED there. When
one is not, nothing breaks — the launch succeeds and the primitive is simply inert. Silence is the
failure mode, so naming the gap is the whole feature.

WHY THIS IS A TABLE AND NOT AN `if`. Exactly one cell is DEGRADED today, which is not much of a
matrix. It is a table because BACKENDS.md §4 — the prose version of this — went stale without
anyone noticing: it still records `service sidecars — host: ✗ (yet)` long after
`HostBackend.wire_services` started calling `_ensure_services`. A table no test reads rots. The
conformance tests over `MATRIX` and `PRIMITIVES` are the mechanism that stops this one rotting, and
they are what make a new backend (bwrap, devcontainer) fill in its column deliberately rather than
inherit silence.

WHAT THIS DELIBERATELY DOES NOT COVER:

  * The container-only half of `install:`. That already has a better mechanism — `install.system`,
    an author-written reason that `schema.validate_container_only_declared` REFUSES to let a recipe
    omit, and that the host launcher prints verbatim. A generic "this backend cannot do that"
    warning would say strictly less and fire alongside it, which trains people to ignore both.
  * `services:` on host. SUPPORTED — see above; §4 is the stale one.

This module imports nothing from `launcher` and never will (tests/test_module_boundaries.py): the
backends live there, so the dependency points INTO this table, not back out.
"""
from __future__ import annotations

from dataclasses import dataclass

#: The backend honors the declaration.
SUPPORTED = "supported"
#: The launch succeeds and the declaration is INERT. This is the case worth a warning.
DEGRADED = "degraded"

#: Recipe primitives whose support could differ by backend. Every one must have a cell in every
#: column — `PRIMITIVES` is the row axis the conformance tests iterate, so adding one here without
#: filling its cells is a test failure, not a silent default.
PRIMITIVES = ("skills", "tools", "install", "setup_script", "servers", "services", "egress")

#: backend name (as declared by `ExecutionBackend.name`) → primitive → support level.
MATRIX: dict[str, dict[str, str]] = {
    "host": {
        "skills": SUPPORTED,        # materialized into the host CLAUDE_CONFIG_DIR
        "tools": SUPPORTED,         # stack bin dir + mise shims on PATH
        "install": SUPPORTED,       # _host_run_installs; the container-only half is install.system's job
        "setup_script": SUPPORTED,  # one cross-backend mechanism since bd harnessed-0tk.9
        "servers": SUPPORTED,       # native .mcp.json, no hub
        "services": SUPPORTED,      # HostBackend.wire_services -> _ensure_services (bd harnessed-2sm)
        "egress": DEGRADED,         # HostBackend.isolation is `none`; apply_isolation does nothing
    },
    "container": {
        "skills": SUPPORTED,
        "tools": SUPPORTED,
        "install": SUPPORTED,
        "setup_script": SUPPORTED,
        "servers": SUPPORTED,       # fronted by the hatago hub
        "services": SUPPORTED,      # pod sidecars
        "egress": SUPPORTED,        # _apply_firewall, default-DROP with the recipe's allowlist
    },
}

#: What a DEGRADED cell means in the user's terms. Keyed by (backend, primitive) so each gap can say
#: something specific — "unsupported" alone tells a reader nothing about what they lose.
_DETAIL: dict[tuple[str, str], str] = {
    ("host", "egress"): (
        "the declared egress allowlist is NOT enforced on the host backend — it has no network "
        "boundary to apply it to (isolation: none). The agent can reach anything this machine can. "
        "Run this stack in a container to get the allowlist enforced."
    ),
}


@dataclass(frozen=True)
class Gap:
    """One recipe declaration this backend will not honor."""

    recipe: str
    primitive: str
    detail: str


def declared_primitives(recipe) -> set[str]:
    """Which of `PRIMITIVES` this recipe actually declares.

    Emptiness matters: a recipe that declares nothing can have no gaps, whatever the backend.
    """
    declared = set()
    if recipe.skills:
        declared.add("skills")
    if recipe.tools:
        declared.add("tools")
    if recipe.install:
        declared.add("install")
    if recipe.setup is not None and recipe.setup.script:
        declared.add("setup_script")
    if recipe.servers:
        declared.add("servers")
    # TWO sources, matching `svcstate._service_refs`, which is the authority on what a stack
    # actually needs started: an MCP `service:` ref requires the sidecar just as surely as a bare
    # `services:` entry does, and `catalog/recipes/ping` declares one that way and nothing else.
    # Checking only `recipe.services` would disagree with the launcher about the same recipe.
    # (_service_refs has a third source — the STACK's own `services:` — which is out of reach here
    # by signature: this function is per-recipe. Noted so the omission is not mistaken for the bug
    # above.)
    if recipe.services or any(getattr(s, "service", None) for s in recipe.servers):
        declared.add("services")
    if recipe.egress:
        declared.add("egress")
    return declared


def gaps(backend: str, recipes) -> list[Gap]:
    """Every declaration in `recipes` that `backend` will not honor, in recipe order.

    Raises KeyError for an unknown backend rather than returning `[]`. An empty result must mean
    "checked, nothing to report" — returning it for a name nobody has a column for would report
    silence about a backend that was never examined, which is the exact failure this table exists
    to prevent.
    """
    try:
        column = MATRIX[backend]
    except KeyError:
        raise KeyError(
            f"no capability column for backend {backend!r} "
            f"(known: {', '.join(sorted(MATRIX))})"
        ) from None
    found = []
    for recipe in recipes:
        for primitive in sorted(declared_primitives(recipe)):
            if column.get(primitive) == DEGRADED:
                found.append(Gap(
                    recipe=recipe.name,
                    primitive=primitive,
                    # `.get`, not `[...]`. A DEGRADED cell whose detail nobody wrote is a developer
                    # error, and `test_every_degraded_cell_has_a_detail` fails the build for it —
                    # but it must not raise HERE. This is a diagnostic: aborting someone's launch
                    # because the warning about their launch is incomplete would be a strictly
                    # worse outcome than the gap it was trying to describe.
                    detail=_DETAIL.get(
                        (backend, primitive),
                        f"{primitive!r} is not honored on the {backend} backend",
                    ),
                ))
    return found
