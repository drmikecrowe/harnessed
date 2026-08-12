# recipes.backlog — parked, unusable by design

Recipes here are **not tested** and are **not resolvable**. `paths.find_in_catalog` only ever looks
under `catalog/<kind>/`, so a `recipes: [gbrain]` in a stack will not find `recipes.backlog/gbrain`
— it fails as an unknown recipe. They are also excluded from the wheel (`pyproject.toml`
`exclude-package-data`), so an installed `harnessed` carries none of them.

This is deliberate: a recipe nobody has verified must not be one `recipes:` line away from
running in someone's agent.

## Trade-off: parked means unlinted

The recipe guards glob `catalog/recipes/*/recipe.yaml` — pin validation, strict field validation,
and the install-migration checks in `tests/test_install_migration_*.py`. Nothing here is covered by
any of them, so these manifests **will drift** out of schema as the schema moves. Expect to fix
that drift as part of promoting one, not before.

## Why each one is parked

| Recipe | State |
| --- | --- |
| `gbrain` | Has an `expect:` oracle; never exercised. Pairs with the still-shipped `catalog/services/gbrain` service. |
| `headroom` | No `expect:` oracle at all. |
| `hindsight` | No `expect:` oracle at all. |

`solidspec` and `tokensave` were considered and deliberately **left in place**: they are subjects of
the install-migration epic and are named directly by its tests (`CONTENT_RECIPES` in
`tests/test_install_migration_content.py`, `ROOT_ONLY` in
`tests/test_install_migration_system.py`). They are unexercised at runtime but heavily covered
statically, so parking them would delete coverage rather than quarantine risk.

`hyperpowers` was the third of that set. It is **deleted outright** rather than parked, by decision
of the repo owner during #329 Phase 3 — so neither branch of the trade-off above applies to it any
more. Note what its removal did NOT resolve: it was one of two recipes acquiring upstream by
`git fetch <remote> <ref>`, and `gstack` is the other. See #329 for the pin gate that shape needed.

PR #130 parked all three on `main` while this epic was in flight, and merging `main` in here
deliberately reverts that for the two that remain — `gbrain`/`headroom`/`hindsight` stay parked, as
both branches agreed. This is a deferral, not a disagreement about their fitness: the moment the
migration epic lands, `ROOT_ONLY` and `CONTENT_RECIPES` must be repointed and the rest parked for
real. Do that as its own change, so the test edits are a decision rather than merge fallout.

## Promoting one back

1. Give it an `expect:` block if it has none — without one the capability test has nothing to probe.
2. Compose it into a stack under `catalog/stacks/`. None of these appeared in any shipped stack,
   which is *why* they went untested: nothing ever built them.
3. `git mv catalog/recipes.backlog/<name> catalog/recipes/<name>`.
4. Run the suite — the recipe guards apply again the moment it lands back, and will surface any
   schema drift accumulated while parked.
