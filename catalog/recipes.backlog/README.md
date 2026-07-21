# recipes.backlog — parked, unusable by design

Recipes here are **not tested** and are **not resolvable**. `paths.find_in_catalog` only ever looks
under `catalog/<kind>/`, so a `recipes: [gbrain]` in a stack will not find `recipes.backlog/gbrain`
— it fails as an unknown recipe. They are also excluded from the wheel (`pyproject.toml`
`exclude-package-data`), so an installed `harnessed` carries none of them.

This is deliberate: a recipe nobody has verified should not be one `recipes:` line away from
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
| `hyperpowers` | Has an `expect:` oracle and an `install.sh`; never exercised. |
| `tokensave` | Has an `expect:` oracle. Container-only by declaration (`install.system` — root-level binary install). |
| `headroom` | No `expect:` oracle at all. |
| `hindsight` | No `expect:` oracle at all. |
| `solidspec` | No `expect:` oracle. Container-only by declaration (`install.system` — apt `cmake`/`pkg-config` for libgit2). |

## Promoting one back

1. Give it an `expect:` block if it has none — without one the capability test has nothing to probe.
2. Compose it into a stack under `catalog/stacks/`. None of these appeared in any shipped stack,
   which is *why* they went untested: nothing ever built them.
3. `git mv catalog/recipes.backlog/<name> catalog/recipes/<name>`.
4. Run the suite — the recipe guards apply again the moment it lands back, and will surface any
   schema drift accumulated while parked.
