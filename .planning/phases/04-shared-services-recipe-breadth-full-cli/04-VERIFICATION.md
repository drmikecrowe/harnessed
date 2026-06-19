---
phase: 04-shared-services-recipe-breadth-full-cli
status: passed
verified: 2026-06-19
score: 9/9 requirements satisfied
source: [04-UAT.md, tools/uat/phase-04.sh]
---

# Phase 4 Verification — Shared Services + Recipe Breadth + Full CLI

**Phase goal** (ROADMAP): Concurrent service sidecars, more recipes, and the full operable
command/lifecycle surface — shared services over `harnessed-net`, recipe breadth, and every
lifecycle action by name with default persistence + clean-room `--fresh`.

> Reconciliation note: the phase was validated by the automated AAA suite recorded in
> `04-UAT.md` (status: complete, 16/16 tests, 50/50 checks) but never recorded a
> `VERIFICATION.md`, so the stats reader (`determinePhaseStatus`) defaulted the phase to
> "Executed". This file records the verdict the stats counter reads; the full suite was
> **re-run live 2026-06-19** and is green.

## Verification Method

Automated suite `tools/uat/phase-04.sh` driving the real `harnessed` CLI + podman.
**Live re-run 2026-06-19:** `./tools/uat/run-uat.sh 4` → **16 passed, 0 failed, 0 skipped;
50/50 checks passed** (~195s, podman runtime).

## Goal Achievement — Observable Truths (re-verified 2026-06-19)

| # | Truth | Status | Evidence (suite tests) |
|---|-------|--------|------------------------|
| 1 | `svc up` starts a service-scoped sidecar two instances attach to over harnessed-net | ✓ VERIFIED | `svc_up`, `svc_up_idempotent`, `shared_single_across_instance` (singular service invariant) |
| 2 | A second recipe added to a stack is exposed + verified by its capability test | ✓ VERIFIED | `recipe_breadth` (claude-multi: time + greet) |
| 3 | `list`/`stop`/`rm`, `new`, `install`/`uninstall` operate by name | ✓ VERIFIED | `list_surface`, `new_scaffold_refuse`, `new_bad_harness`, `install_uninstall`, `no_args_help`, `legacy_flags` |
| 4 | Stacks persist by default; `--fresh` yields a clean-room run; legible session slug | ✓ VERIFIED | `state_persists`, `fresh_wipes`, `legible_slug` |
| 5 | An `omp` stack runs Claude-canonical recipes via the bridge | ✓ VERIFIED | `omp_bridge` (omp-time: time via claude-hooks-bridge + pi-adapter) |
| 6 | `svc down` retains the volume; `--purge` destroys it | ✓ VERIFIED | `svc_down_retains_volume`, `svc_down_purge` |

**Score:** 6/6 truths verified (16/16 suite tests).

## Requirements Coverage

| Requirement | Status |
|-------------|--------|
| SVC-01 shared service sidecar (image/volume) | ✓ SATISFIED |
| SVC-02 concurrent attach to one shared service | ✓ SATISFIED |
| SVC-03 `harnessed svc up\|down\|list` | ✓ SATISFIED |
| STA-01 persistent by default; `--fresh` clean-room | ✓ SATISFIED |
| STA-02 session state persists host-side, legible slug | ✓ SATISFIED |
| CLI-01 `harnessed list\|stop\|rm` | ✓ SATISFIED |
| CLI-02 `harnessed new <stack> --harness --recipes` | ✓ SATISFIED |
| CLI-03 `harnessed install\|uninstall` shim | ✓ SATISFIED |
| HRN-01 one harness per stack; omp via bridge | ✓ SATISFIED |

**Coverage:** 9/9 requirements satisfied.

## Gaps Summary

**No gaps.** The two UAT-surfaced gaps (bare-`harnessed` help; legible state-dir slug) were
closed by plan 04-04 and their red tests flipped green; the full suite re-ran green 2026-06-19.

---
*Verified: 2026-06-19 (reconciliation — automated UAT promoted to canonical artifact + live full-suite re-run)*
