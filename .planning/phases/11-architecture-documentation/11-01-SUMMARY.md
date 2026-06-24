---
phase: 11-architecture-documentation
plan: "01"
subsystem: documentation
tags: [docs, readme, architecture, image-lineage, terminology]
dependency_graph:
  requires: []
  provides: [updated-readme, updated-claude-md, updated-agents-md]
  affects: [README.md, CLAUDE.md, AGENTS.md]
tech_stack:
  added: []
  patterns: []
key_files:
  modified:
    - README.md
    - CLAUDE.md
    - AGENTS.md
decisions:
  - "Removed narrative 'isolated'/'transparent' mode labels from all three files; only backtick code spans and the Trail of Bits comparison row retained"
  - "Added 3-layer image lineage (harnessed-base → harnessed-<harness> → harnessed-<stack>) to README First-run build section"
  - "Added harnessed test tracer-time capability test step to README quickstart"
  - "CLAUDE.md product description updated from 'isolated, composable harness stacks' to 'containerized, composable harness stacks'"
metrics:
  duration: "~15 minutes"
  completed: "2026-06-24T16:11:42Z"
  tasks_completed: 2
  tasks_total: 2
  files_changed: 3
---

# Phase 11 Plan 01: README/CLAUDE.md/AGENTS.md Architecture Documentation Summary

Update README.md with 3-layer image lineage (base → agent → stack), quickstart capability test, and removal of narrative "isolated"/"transparent" terminology from README.md, CLAUDE.md, and AGENTS.md.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Update README.md — 3-layer image lineage + quickstart + de-narrative | 807bb48 | README.md |
| 2 | Update CLAUDE.md + AGENTS.md — remove narrative isolated/transparent | 079a2b6 | CLAUDE.md, AGENTS.md |

## What Was Built

**README.md changes:**
- Header subtitle: "Isolated, composable harness stacks" → "Composable harness stacks"
- Forked-from note: "composable isolated stacks" → "composable harness stacks"
- Lead paragraph: removed two narrative "isolated" adjectives from stack/instance descriptions
- First-run build section: replaced 2-layer lineage with explicit 3-layer description (Layer 1: `harnessed-base`, Layer 2: `harnessed-<harness>`, Layer 3: `harnessed-<stack>`)
- Quickstart: added `harnessed test tracer-time` step with note about capability report output
- Comparison use-case paragraph: simplified to remove "(transparent)" and "(isolated)" mode references

**CLAUDE.md changes:**
- Product description: "isolated, composable harness stacks" → "containerized, composable harness stacks"; removed transparent/isolated mode origin narrative
- Core Value: "launch an isolated, authenticated instance" → "launch an authenticated instance"
- What NOT to Use table: removed transparent/isolated mode labels from the `.claude.json` row

**AGENTS.md changes:**
- Description: removed "the two config modes (transparent / isolated)" phrase
- Important callout: removed transparent/isolated mode descriptions from "do not run" note
- Setup step 3 comment: "assemble an isolated stack" → "assemble a stack"
- Setup step 4: removed `harnessed transparent` option; kept only `harnessed tracer-time`
- Harness permissions: "inside a transparent instance" → "inside a stack instance"

## Verification

```
rg "Layer 1|Layer 2|Layer 3" README.md  → 3 matches (lines 80-82)
rg "harnessed test tracer-time" README.md  → 1 match (line 122)
rg "isolated|transparent" CLAUDE.md  → 0 matches
rg "isolated|transparent" AGENTS.md  → 0 matches
rg "isolated|transparent" README.md  → only backtick code spans, code blocks, and Trail of Bits "Fully isolated" row
```

## Deviations from Plan

**1. [Rule 1 - Context] Worktree contains older file versions**
- **Found during:** Task 1
- **Issue:** The worktree was based on an older commit (686833b) that still contained the transparent/isolated two-mode architecture in README.md and more extensive transparent/isolated references in CLAUDE.md and AGENTS.md
- **Fix:** Applied all plan changes to the worktree's older file state — removed all narrative isolated/transparent mode descriptions while preserving the existing two-mode table structure (which uses backtick code spans for mode identifiers, exempted per plan rules)
- **Impact:** Slightly more changes than the plan anticipated for the main-checkout line numbers, but all plan success criteria satisfied

## Known Stubs

None.

## Threat Flags

None. Documentation-only changes, no code execution or new attack surface.

## Self-Check: PASSED

- README.md exists and contains `harnessed-<stack>` (line 82) and `harnessed test tracer-time` (line 122)
- CLAUDE.md has zero matches for `isolated|transparent`
- AGENTS.md has zero matches for `isolated|transparent`
- Commits 807bb48 and 079a2b6 exist in git log
