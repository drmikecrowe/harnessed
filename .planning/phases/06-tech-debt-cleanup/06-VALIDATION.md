---
phase: 06
slug: tech-debt-cleanup
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-21
---

# Phase 06 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

> **Source:** derived from `06-RESEARCH.md` § Validation Architecture (integration-only, behavior-preserving cleanup phase — no new code paths, no new tests).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | project's integration-only capability test (`tools/harnessed/capability.py`) + the UAT bash suite (`tools/uat/`) — NO unit-test framework exists in the repo by design `[CITED: docs/codebase/CONCERNS.md M1]` |
| **Config file** | none (integration-only; the stack manifest IS the oracle) |
| **Quick run command** | `harnessed test tracer-time` (the no-shared-service stack — fastest) |
| **Full suite command** | `harnessed test ping-time && harnessed test tracer-time && bash tools/uat/run-uat.sh` |
| **Estimated runtime** | ~60–120 seconds (needs rootless podman on the host) |

---

## Sampling Rate

- **After every task commit:** `bash -n` on any touched `lib/*.sh` (syntax — catches comment-edit accidents that break shell parsing); `head -1` YAML-open check on any touched `*-SUMMARY.md`.
- **After every plan wave:** `harnessed test ping-time` + `harnessed test tracer-time` + the UAT suite.
- **Before `/gsd-verify-work`:** Full suite must be green (D-11).
- **Max feedback latency:** 120 seconds (integration suites; doc/comment/static checks are instant).

---

## Per-Task Verification Map

> Populated from PLAN.md task IDs once planning completes. The criterion→test map below is the binding source.

| Success criterion | Behavior | Test type | Automated command | Host-gated? |
|-------------------|----------|-----------|-------------------|-------------|
| 1 (no dead `harnessed-net` code) | `harnessed-net`-using service still connects after any code touch | integration (capability) | `harnessed test ping-time` → asserts `ping` MCP connected via hatago | ❌ needs rootless podman |
| 1 (tracer stack unaffected) | isolated pod still boots, `time` MCP connects | integration (capability) | `harnessed test tracer-time` | ❌ needs rootless podman |
| 2 (stale comments corrected) | docs/comments match shipped behavior | static (diff review) | n/a — review the B1–B6 corrections; replacement-doc comments (D-07) untouched; no OPEN `[INFERENCE]` marker edited | ✅ zero-runtime |
| 3 (frontmatter hygiene) | every SUMMARY has well-formed frontmatter | static (parse) | `for f in .planning/phases/0*-*/0*-SUMMARY.md; do head -1 "$f"; done` (every file starts with `---`) + YAML parse | ✅ |
| regression (no behavior change) | UAT suite green | integration (UAT) | `bash tools/uat/run-uat.sh` | ❌ needs rootless podman |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

None — existing test infrastructure (capability test + UAT) covers all three criteria. No new test files, framework installs, or fixtures. `[CITED: docs/codebase/CONCERNS.md M1]`

*Existing infrastructure covers all phase requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Stale-comment corrections read accurately | Success criterion 2 | Doc/comment wording is semantic, not mechanical | Review the diff: B1–B6 corrections present; D-07 replacement-doc comments unchanged; grep diff for `[INFERENCE` → only pre-existing occurrences |

---

## Observable signals that prove each success criterion

1. **Criterion 1 (no dead code):** `harnessed test ping-time` reports `ping ✓ connected` (the `harnessed-net`-referencing service still works); a repo-wide grep for `harnessed-net` returns only references that are either LIVE, the opt-in escape hatch, or now-accurate docs.
2. **Criterion 2 (stale comments):** the diff contains the B1–B6 corrections; the replacement-doc comments (D-07) remain untouched; no OPEN `[INFERENCE]` marker was edited.
3. **Criterion 3 (frontmatter):** every `0*-SUMMARY.md` begins with `---` and contains a `# Dependency graph` header followed by `requires:`/`provides:`; YAML parses.

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
