---
phase: 11-architecture-documentation
plan: "03"
subsystem: docs
tags: [documentation, recipe-authoring, dockerfile-recipe, phase-8]
dependency_graph:
  requires: []
  provides: [DOC2-01]
  affects: [docs/guides/recipe-authoring.md]
tech_stack:
  added: []
  patterns: [dockerfile-recipe-model, harness-compat-validation, pin-discipline, capability-oracle]
key_files:
  created: []
  modified:
    - docs/guides/recipe-authoring.md
decisions:
  - "Modeled Worked example 3 on recipes/gstack/ (canonical Phase 8 Dockerfile recipe test artifact)"
  - "Added harnesses:/expect: fields inline in schema block with comment-style explanations to match existing schema style"
  - "Placed Dockerfile note after schema Notes section, before existing worked examples"
  - "Placed Worked example 3 between Worked example 2 and the Transports section (matches plan instruction)"
metrics:
  duration: "~8 minutes"
  completed: "2026-06-24"
  tasks_completed: 2
  tasks_total: 2
  files_changed: 1
---

# Phase 11 Plan 03: Recipe Authoring Guide — Dockerfile Recipe Model Summary

Updated `docs/guides/recipe-authoring.md` to document the Phase 8 Dockerfile recipe model alongside the existing typed-YAML model, covering `harnesses:`, `expect:`, the "run the framework's own installer" principle, and pin discipline.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Update recipe.yaml schema — harnesses:, expect:, Dockerfile body note | de4d839 | docs/guides/recipe-authoring.md |
| 2 | Add Worked example 3 — Dockerfile recipe with pinned install | 9808d5c | docs/guides/recipe-authoring.md |

## What Was Done

**Task 1** updated two sections of `docs/guides/recipe-authoring.md`:

- "What a recipe is": extended from two layers (MCP + file-extension) to three (added Dockerfile body), explaining that the assembler concatenates Dockerfile bodies in recipe order to build the derived image.
- "The recipe.yaml schema": added `harnesses:` and `expect:` fields to the YAML block with inline comments, and added a prose note directing readers to Worked example 3 for the Dockerfile pattern.

**Task 2** appended a new "Worked example 3: a Dockerfile recipe (installs a framework CLI)" section between Worked example 2 and the Transports section, covering:
- `recipe.yaml` with `harnesses: [claude]` and `expect: [gstack-skill]`, with explanations of both fields
- `Dockerfile` with no `FROM` line, `ARG HARNESS=claude`, and a pinned `pnpm dlx @gstack/install@1.2.3 --host ${HARNESS}` install step
- "Run the framework's own installer" principle: delegates install to the framework's own installer, using `--host ${HARNESS}` for harness-aware configuration
- Pin discipline: `ARG` declarations for version pins, `PinValidationError` on floating refs (`@latest`, `--branch main`)
- Full lifecycle: `harnessed build gstack-time` / `harnessed gstack-time` / `harnessed test gstack-time`

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None.

## Threat Flags

None — documentation-only changes, no new code or network surface.

## Self-Check: PASSED

- `docs/guides/recipe-authoring.md` exists and contains all required content
- `rg "harnesses:" docs/guides/recipe-authoring.md` — 4 matches (schema block + worked example)
- `rg "expect:" docs/guides/recipe-authoring.md` — 4 matches (schema block + worked example)
- `rg "ARG HARNESS" docs/guides/recipe-authoring.md` — 2 matches (Dockerfile block + rules list)
- `rg "Worked example 3" docs/guides/recipe-authoring.md` — 2 matches (cross-ref + section header)
- `rg "harnessed test gstack-time" docs/guides/recipe-authoring.md` — 1 match (lifecycle block)
- `rg "floating" docs/guides/recipe-authoring.md` — 2 matches (pin discipline sections)
- Commits de4d839 and 9808d5c exist in git log
