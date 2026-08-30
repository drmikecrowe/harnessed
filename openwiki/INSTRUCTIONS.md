Document `harnessed`: a host-native Python CLI that assembles and launches containerized coding-agent
stacks with podman. Write for an agent that has to change this code correctly on the first attempt.

## Scope

Ground every page in `src/harnessed/`. `catalog/` is authored content, not code: describe its schema
and how the build consumes it, not each recipe.

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

## Write for synthesis, not restatement

The highest-value page collects a rule that is **scattered across many files** and states it once.
The lowest-value page paraphrases one comment that was already clearer in place.

`concepts/precedence.md` is the template to imitate: one row per conflict, naming the conflict, the
winner, and the production failure the loser once produced. That table spans eight modules, so it is
worth far more than the sum of the comments it draws on. Prefer that shape wherever a rule has no
single home in the source.

## Carry the reference

Where a source comment cites an issue, a `bd` id, a PR number, or a dated measurement, **carry that
reference into the page.** It is what makes the claim checkable, and it is the one thing a reader
cannot reconstruct from the code.

A stated limitation with a tracking issue is more valuable than the behavior it limits. When a
comment says a mechanism is incomplete, or must be revisited when some other work lands, that
sentence belongs in the wiki with its issue number attached.

Never invent a reference. Cite the one in the source or cite nothing.

## Emphasis

Prefer the non-obvious. This codebase carries many deliberate deviations that read like defects, and
each one already explains itself in a comment naming the issue it fixes. Surface those as invariants
a reader must not "clean up". A page that restates a function signature adds nothing.

Where an ordering, a timeout, or a defensive check is load-bearing, say what breaks without it.

## Required page: the credential proxy model

Add a page covering the credential-proxy migration, because the vocabulary it introduces appears in
open work and is documented nowhere else in the wiki. It must state:

- The four classification modes and what each means for whether a secret reaches the agent, the
  upstream, or neither.
- `_schema_declares_proxy`'s cheap text gate: why it matches annotation forms rather than the bare
  word, and what a resolving subprocess would otherwise cost.
- Its stated limitation — it reads the entry schema only — and the issue that tracks revisiting it.
- What `_warn_unproxied_secrets` reports, and why it is value-blind.

`src/harnessed/launchenv.py` is the source of record. Follow its own issue references.

## Out of scope

Do not document the developer's machine, personal paths, vault item names, or any account identity.
Do not reproduce credential values or `op://` references.

Do not restate `AGENTS.md`, `CLAUDE.md`, or `CONTRIBUTING.md`. Link to them.

Leave the retired subsystems retired. Where `.gitignore` or a comment says a feature was removed but
its state may persist on disk, that fact belongs in one sentence, not a page.
