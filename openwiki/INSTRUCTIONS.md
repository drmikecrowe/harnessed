Document `harnessed`: a host-native Python CLI that assembles and launches containerized coding-agent
stacks with podman. Write for an agent that has to change this code correctly on the first attempt.

## Scope

Ground every page in `src/harnessed/` and `tests/`. `catalog/` is authored content, not code: describe
its schema and how the build consumes it, not each recipe.

Priorities, highest first:

1. **The build and launch pipeline.** How a stack plus a harness becomes a profile, an image, and a
   running pod. Name the modules that own each stage and the order they run in.
2. **Credential handling.** Where secrets enter, what resolves them, and what is deliberately never
   written to disk or into an image layer. Say which paths run on the host only, and why.
3. **The container/host split.** Two launch paths exist and they are not symmetric. Document what
   differs and which invariants must hold in both.
4. **Precedence rules.** Layered env files, recipe versus harnessed-owned values, global versus
   project overrides. These are the source of the subtlest bugs, so state the winner explicitly.
5. **The verification ladder.** What each gate proves and what it does not: the pytest suite, the
   live tests behind `HARNESSED_PODMAN=1`, the lint layers, and the pin check.

## Emphasis

Prefer the non-obvious. This codebase carries many deliberate deviations that read like defects, and
each one already explains itself in a comment naming the issue it fixes. Surface those as invariants a
reader must not "clean up". A page that restates a function signature adds nothing.

Where an ordering, a timeout, or a defensive check is load-bearing, say what breaks without it.

## Out of scope

Do not document the developer's machine, personal paths, vault item names, or any account identity.
Do not reproduce credential values or `op://` references.

Do not restate `AGENTS.md`, `CLAUDE.md`, or `CONTRIBUTING.md`. Link to them.

Leave the retired subsystems retired. Where `.gitignore` or a comment says a feature was removed but
its state may persist on disk, that fact belongs in one sentence, not a page.
