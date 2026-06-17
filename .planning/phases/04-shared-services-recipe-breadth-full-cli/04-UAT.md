---
status: partial
phase: 04-shared-services-recipe-breadth-full-cli
source: [04-01-SUMMARY.md, 04-02-SUMMARY.md, 04-03-SUMMARY.md]
started: 2026-06-17T09:51:23Z
updated: 2026-06-17T12:07:10Z
mode: mvp
method: automated
suite: tools/uat/phase-04.sh
user_story: "As a stack operator, I want to run concurrent harness instances that share service-scoped sidecars and operate the full stack, instance, and session lifecycle through the `harnessed` CLI, so that multiple instances can run together over a shared network, I can add more recipes to a stack, and every lifecycle action works predictably by name with default persistence and clean-room `--fresh` runs."
---

## Methodology

Phase 4 is validated by an **automated AAA (Arrange-Act-Assert) UAT suite**, not a
manual conversation. The suite drives the real `harnessed` CLI + podman, asserts on
exit codes / output / container state, and reports pass/fail per test.

- **Runner:** `./tools/uat/run-uat.sh 4` (full) · `… 4 --quick` (no heavy launches) · `… 4 <test_id>` (one test)
- **Harness:** `tools/uat/uat-common.sh` (pure-bash asserts, no bats/grep)
- **Suite:** `tools/uat/phase-04.sh` (16 AAA tests)
- **Last run:** 2026-06-17 — 14/16 tests pass, 2 fail (both are logged gaps, red by design)

## Current Test

[automated — run `./tools/uat/run-uat.sh 4`]

## Tests

| # | Test (AAA) | What it asserts | Result |
|---|------------|-----------------|--------|
| 1 | `svc_up` | svc up publishes 0.0.0.0:8080, healthy, listed | pass |
| 2 | `svc_up_idempotent` | second svc up is a no-op; exactly 1 container | pass |
| 3 | `svc_down_retains_volume` | svc down keeps the ping-data volume | pass |
| 4 | `svc_down_purge` | svc down --purge destroys the volume | pass |
| 5 | `shared_single_across_instance` | `harnessed test ping-time` passes; shared ping service stays singular (SVC-02 invariant) | pass |
| 6 | `recipe_breadth` | `harnessed test claude-multi` asserts time + greet (SC-2) | pass |
| 7 | `omp_bridge` | `harnessed test omp-time` asserts time via the bridge (SC-5) | pass |
| 8 | `no_args_help` | bare `harnessed` shows Usage, exits 0 | **fail (gap 6B)** |
| 9 | `list_surface` | `harnessed list` shows stacks + instances | pass |
| 10 | `new_scaffold_refuse` | `new` scaffolds a manifest; refuses overwrite | pass |
| 11 | `new_bad_harness` | `new` rejects an unknown harness | pass |
| 12 | `install_uninstall` | install writes an executable §13 shim; uninstall removes it | pass |
| 13 | `legacy_flags` | legacy `--list` still works (instance-only back-compat) | pass |
| 14 | `state_persists` | marker survives a non-`--fresh` recreate (STA-01) | pass |
| 15 | `fresh_wipes` | `--fresh` wipes accumulated state (clean-room) | pass |
| 16 | `legible_slug` | state-dir slug is a legible path, not an opaque hash | **fail (gap 6)** |

### Cold-start note
A full from-scratch cold start (all images wiped → rebuild → boot) is implicitly covered
— the suite rebuilds profiles/images when absent (claude-multi, omp-time were assembled
during the run). A destructive zero-image cold start remains a one-off manual check, not
part of the repeatable suite.

## Summary

total: 16
passed: 14
issues: 2
pending: 0
skipped: 0
blocked: 0
checks: 46 passed, 3 failed

## Gaps

<!-- Two open gaps. Each is encoded as a RED test in tools/uat/phase-04.sh that flips green
     when the fix lands. Root causes + fix shapes below feed /gsd-execute-phase. -->

- truth: "Running `./harnessed` with no arguments shows usage/help (not a silent transparent launch)"
  status: failed
  reason: "User reported: ./harnessed should show help by default"
  severity: major
  test: no_args_help
  red_test: "tools/uat/phase-04.sh::test_no_args_help"
  root_cause: "harnessed:75 sets STACK='transparent' as the default; with zero args the parse loop (harnessed:81 `while [[ $# -gt 0 ]]`) never runs, so dispatch launches transparent interactively. A `usage()` exists and `-h|--help` works, but there is no `$# -eq 0` guard before the loop to route bare invocation to help."
  artifacts:
    - path: "harnessed"
      issue: "No `if [ $# -eq 0 ]; then usage; exit 0; fi` before the arg-parse loop; default STACK=transparent makes bare invocation launch."
  missing:
    - "Add a no-args guard: if no args at all, print usage and exit 0 (a single bareword that is a path must still launch transparent, so guard on `$# -eq 0`, not on the STACK default)."
    - "Reconcile usage() line 41 ('default stack: transparent') if bare invocation no longer launches."
  debug_session: ""

- truth: "The host-side state dir uses a legible, path-based slug (e.g. a flattened project path), not an opaque hash"
  status: failed
  reason: "User reported: the hash works fine programmatically, but state tracking needs the path form instead, e.g. -home-mcrowe-programming-...-code-container, not harnessed-ping-time-0790e5fd"
  severity: minor
  test: legible_slug
  red_test: "tools/uat/phase-04.sh::test_legible_slug"
  root_cause: "lib/harnessed-common.sh:180 generate_instance_name() emits harnessed-<stack>-<sha1(project)[:8]>, and lib/harnessed-isolated.sh:103 keys the state dir off that SAME value. The hash was chosen for a compact, unique CONTAINER/pod name; the state dir inherited it, sacrificing legibility. project_relpath() (harnessed-common.sh:194) already computes a relpath under $HOME but is unused for the state slug."
  artifacts:
    - path: "lib/harnessed-common.sh"
      issue: "generate_instance_name() hash slug reused for both container name and state dir."
    - path: "lib/harnessed-isolated.sh"
      issue: "State dir path built from the instance (hash) slug, not a legible project path."
  missing:
    - "Decouple the state-dir slug from the container name: container/pod keeps the compact hash slug (DNS-label ≤63-char constraint); state dir uses a legible flattened project path."
    - "Decide the path form: home-relative relpath via project_relpath() (e.g. programming-personal-code-container) vs. full absolute path flattened (e.g. home-mcrowe-programming-personal-code-container) per the user's example."
    - "Handle length/collisions for deep paths; migrate or cleanly ignore any pre-existing hash-based state dirs."
  debug_session: ""
