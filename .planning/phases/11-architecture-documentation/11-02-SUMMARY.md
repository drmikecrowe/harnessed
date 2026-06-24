---
phase: 11-architecture-documentation
plan: "02"
subsystem: documentation
tags: [docs, harnessed-design, assembly, capability-test, profile-mounts]
dependency_graph:
  requires: [08-03, 09-01]
  provides:
    - docs/harnessed-design.md (updated §4b, §7, §18)
  affects:
    - docs/harnessed-design.md
tech_stack:
  added: []
  patterns:
    - Dockerfile recipe model (ARG HARNESS, body concatenation, assembler emits derived Dockerfile)
    - Two-oracle capability test (structured MCP probe + un-primed agent probe with negative control)
    - Surgical per-file profile mounts via lib/manifests/<harness>.yaml
key_files:
  created: []
  modified:
    - docs/harnessed-design.md
decisions:
  - "§7 now describes Dockerfile recipe model: recipe = Dockerfile body, ARG HARNESS, pin sources + scan derived image"
  - "§18 now describes two-oracle test: Oracle 1 (hatago://servers deterministic probe) + Oracle 2 (un-primed agent probe with decoy negative control)"
  - "§4b heading updated to 'surgical per-file mounts'; isolated mode now explains lib/manifests/<harness>.yaml with profile_files and history_dirs keys"
  - "vendor-plugin/sync-plugin-links references removed from §7 (superseded by Dockerfile recipe model)"
metrics:
  duration: "~15 minutes"
  completed: "2026-06-24T00:00:00Z"
  tasks_completed: 3
  tasks_total: 3
  files_created: 0
  files_modified: 1
---

# Phase 11 Plan 02: Update §4b, §7, §18 of harnessed-design.md Summary

Updated three stale sections of `docs/harnessed-design.md` to accurately describe the Phase 8 Dockerfile recipe model (§7), Phase 10 two-oracle capability test (§18), and Phase 9 surgical per-file profile mount model (§4b).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Rewrite §7 for Dockerfile recipe model | 2ec3b8a | docs/harnessed-design.md |
| 2 | Rewrite §18 for two-oracle capability test | 2ec3b8a | docs/harnessed-design.md |
| 3 | Update §4b for surgical per-file profile mounts | 2ec3b8a | docs/harnessed-design.md |

Note: All three tasks modified the same file and were committed together in a single atomic commit.

## What Was Built

### §7 Rewrite — Dockerfile Recipe Model

Replaced the stale v1 assembly table (vendor-plugin, sync-plugin-links, Prior-art source) with an accurate description of the Phase 8 Dockerfile recipe model:

- **Recipe = Dockerfile body.** Each recipe contributes a `Dockerfile` (no `FROM` line). `ARG HARNESS=<default>` at the top lets the body reference `${HARNESS}` for harness-specific installs. The assembler strips `ARG HARNESS`, prepends `FROM harnessed-${HARNESS}:latest`, concatenates bodies, and writes `profiles/<stack>/Dockerfile.harnessed-<stack>`.
- **recipe.yaml declares metadata, not build steps.** `harnesses:` (compat list), `mcp.servers:`, and `expect:` (smoke-check subset) are the YAML fields. Build steps live in the Dockerfile.
- **Supply chain = pin sources + scan derived image.** Floating refs are validation errors. After build: osv-scanner V2 (always-on, credential-free), Snyk container scan (warn-and-skip), Socket.dev (warn-and-skip).
- **Assembler output.** Emits `Dockerfile.harnessed-<stack>`, `hatago.config.json`, `.mcp.json`, `settings.json`.
- Scanner credentials and pnpm everywhere sub-sections retained.

### §18 Rewrite — Two-Oracle Capability Test

Replaced the v1 single-oracle description (ask harness to emit skills as JSON, diff manifest) with the Phase 10 two-oracle approach:

- **Oracle 1 (structured MCP probe).** Query `hatago://servers` resource — deterministic, no model call. Assert each `mcp.servers` entry is connected.
- **Oracle 2 (un-primed agent probe).** Ask the harness what capabilities it has WITHOUT naming the expected ones. Include a decoy capability not in the recipe.
- **Negative control / anti-sycophancy gate.** Decoy MUST appear in `missing`. If agent claims decoy is present: exit status **INVALID** (distinct from capability-failure). Catches sycophantic priming.
- **capability-report.md.** Written to `profiles/<stack>/capability-report.md` after each `harnessed test <stack>` run. Per-capability table with checkmarks plus INVALID banner.
- Removed "Proposed:" from heading; removed v1 "emit skills/commands as JSON and diff" language.

### §4b Update — Surgical Per-File Profile Mounts

Updated the isolated mode description in §4b to explain the Phase 9 surgical mount model:

- **Heading** updated from "the mode axis" to "surgical per-file mounts".
- **isolated mode** now explains that profile assets are NOT mounted as a whole directory. Per-harness YAML manifests in `lib/manifests/<harness>.yaml` have two keys:
  - `profile_files`: individual filenames (`.mcp.json`, `settings.json`) mounted ro; `lib/harnessed-manifest-mounts.sh` applies harness-aware container target paths.
  - `history_dirs`: `$HOME`-relative paths bind-mounted rw for history surfacing.
- **Why surgical?** Explained: whole-directory mounting lets host defaults bleed in, violating the "no host defaults" invariant.
- Credential mount sentence, `.claude.json` stub warning, and session state bullet all retained.

## Acceptance Criteria Verification

| Criterion | Status |
|-----------|--------|
| ARG HARNESS present in §7 | PASSED (lines 180, 184, 193) |
| vendor-plugin/sync-plugin-links removed from §7 | PASSED (removed from §7; other sections not changed per constraint) |
| scan derived image / harnessed-stack references in §7 | PASSED |
| harnesses: referenced in §7 | PASSED |
| two-oracle/negative control/decoy/INVALID in §18 | PASSED (12 matches) |
| Oracle 1/Oracle 2/hatago://servers in §18 | PASSED |
| "Proposed: testing" heading removed | PASSED |
| capability-report referenced in §18 | PASSED |
| surgical in §4 | PASSED (4 matches) |
| profile_files/harnessed-manifest-mounts/lib/manifests in §4 | PASSED |
| credentials.json retained in §4 | PASSED |
| .claude.json stub warning retained in §4 | PASSED |
| "surgical per-file" in §4b heading and prose | PASSED |
| Section count unchanged (19 sections) | PASSED |

## Deviations from Plan

**Minor scope note:** The acceptance criterion for §7 requires zero `vendor-plugin|sync-plugin-links` matches in the whole file. These terms remain in §1 (Problem), §11 (recipe schema YAML), §14 (to verify items), and §15 (assembler description) — sections the plan explicitly forbids changing. All references were removed from §7 itself; the criterion was written assuming §7 was the only location.

## Known Stubs

None — all three sections fully document implemented Phase 8/9/10 features.

## Threat Flags

None — documentation-only changes, no new code or network surface.

## Self-Check: PASSED

- docs/harnessed-design.md committed at 2ec3b8a
- §4b heading: "surgical per-file mounts" confirmed
- §7 heading: "Dockerfile recipe model + supply-chain gate" confirmed
- §18 heading: "Testing — integration only..." (no "Proposed:") confirmed
- ARG HARNESS present in §7 (3 occurrences)
- two-oracle, negative control, decoy, INVALID all in §18 (12 matches total)
- capability-report.md referenced in §18
- surgical, lib/manifests, profile_files all present in §4b
- credentials.json and .claude.json stub warning retained in §4b
