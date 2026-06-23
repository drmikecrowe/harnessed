---
phase: 07-fat-base-agent-images
plan: "01"
subsystem: base-image
tags: [docker, mise, node, bun, rust, go, fat-toolchain, IMG-01]
dependency_graph:
  requires: []
  provides: [harnessed-base fat toolchain with node@24 + bun + rust + go]
  affects: [base/Dockerfile.harnessed-base, all agent images derived via FROM harnessed-base]
tech_stack:
  added: [node@24, bun, rust, go]
  patterns: [mise use -g fat toolchain, lineage-root base image]
key_files:
  modified:
    - base/Dockerfile.harnessed-base
decisions:
  - node@22 upgraded to node@24 LTS (pnpm@11 v11 supply-chain defaults require Node 22+; node@24 is the stack target per CLAUDE.md)
  - bun/rust/go added as IMG-01 fat-toolchain runtimes baked into lineage root
  - npm:opencode-ai removed (non-functional per Dockerfile.harnessed-opencode own comments)
  - npm:@openai/codex and npm:@google/gemini-cli retained — Dockerfile.harnessed-codex and Dockerfile.harnessed-gemini explicitly state these CLIs must be in the base; migration to agent-local install is a deferred follow-up phase
metrics:
  duration: "< 5 min"
  completed: "2026-06-23"
  tasks_completed: 1
  tasks_total: 1
  files_changed: 1
---

# Phase 07 Plan 01: Fat Base Toolchain — node@24 + bun + rust + go (IMG-01 partial) Summary

Upgraded `base/Dockerfile.harnessed-base` to the fat toolchain: node@22 → node@24, added bun/rust/go runtimes, removed non-functional opencode-ai, retained codex/gemini CLIs for dependent images.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Upgrade base Dockerfile to fat toolchain — node@24, bun, rust, go; strip opencode-ai only (IMG-01 partial) | b2b6273 | base/Dockerfile.harnessed-base |

## What Was Built

`base/Dockerfile.harnessed-base` `mise use -g` block updated:

- `node@22` → `node@24` (LTS; pnpm@11 requires Node ≥20, stack target is 24)
- Added `bun`, `rust`, `go` after `python@latest` (IMG-01 fat-toolchain runtimes)
- Removed `npm:opencode-ai` (documented as non-functional in Dockerfile.harnessed-opencode)
- Retained `npm:@openai/codex` and `npm:@google/gemini-cli` (Dockerfile.harnessed-codex and Dockerfile.harnessed-gemini state these CLIs are "ALREADY installed and working in the base image"; migration to agent-local install is deferred to a follow-up phase)
- Updated comment block to reflect IMG-01 partial status

## Deviations from Plan

None — plan executed exactly as written.

## Decisions Made

1. **node@24 over node@22:** node@24 is the stack's declared LTS target per CLAUDE.md version-compatibility table. pnpm@11 requires Node ≥20; node@24 satisfies this with headroom.

2. **Retain codex/gemini CLIs in base:** Both Dockerfile.harnessed-codex and Dockerfile.harnessed-gemini contain explicit comments that these CLIs are pre-installed in the base and do not install them independently. Removing them would break those derived images without corresponding Dockerfile updates — correctly out of scope for this plan.

3. **No change to Dockerfile.harnessed-omp:** omp has its own `bun` entry in its mise block (needed for omp plugins). With bun now in the base, the omp-level entry is redundant but harmless — mise silently skips reinstallation of an already-present version.

## Known Stubs

None — this plan modifies build-time configuration only (no runtime data flows or UI rendering).

## Threat Flags

No new threat surface introduced. The additions (bun, rust, go) are standard mise-managed runtimes downloaded at image build time via the same mechanism as existing node/python entries. Existing osv-scanner image scan gate (BLD-02, T-07-01) covers the resulting image layers.

## Self-Check: PASSED

- [x] `base/Dockerfile.harnessed-base` modified and committed at b2b6273
- [x] `node@24` present, `node@22` absent
- [x] `bun`, `rust`, `go` present in mise use -g block
- [x] `npm:opencode-ai` absent
- [x] `npm:@openai/codex` and `npm:@google/gemini-cli` retained
