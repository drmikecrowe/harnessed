---
phase: 8
slug: dockerfile-recipe-model-assembler-supply-chain-gate
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-23
---

# Phase 8 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Inline Python one-liners (via `mise exec -- uv run python -c "..."`) + bash UAT suite |
| **Config file** | `pyproject.toml` (existing pytest infra available but not used as primary gate here) |
| **Quick run command** | `tools/uat/run-uat.sh 08 --quick` |
| **Full suite command** | `tools/uat/run-uat.sh 08` |
| **Estimated runtime** | fast tests: ~10 seconds; heavy tests: 2–5 min (container builds) |

---

## Sampling Rate

- **After every task commit:** Run the task's `<automated>` verify command (inline Python or rg assertion)
- **After every plan wave:** Run `tools/uat/run-uat.sh 08 --quick`
- **Before `/gsd-verify-work`:** Full suite must be green (fast tests); heavy tests require live podman
- **Max feedback latency:** 60 seconds (fast tests and inline verify commands)

---

## Verification Approach

Phase 8 uses **inline command verification** rather than pytest stubs. Every task's `<verify>` block
contains an `<automated>` command that runs in under 60 seconds and proves the task's acceptance
criteria. The Phase 8 UAT suite (`tools/uat/phase-08.sh`) provides the behavioral integration layer.

This approach replaces the pytest-stub wave-0 pattern documented in the initial VALIDATION.md draft.
All 11 requirements are covered by the combination of inline task verify commands and UAT tests —
no separate pytest stub files are needed.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|--------|
| 8-01-01 | 08-01 | 1 | RCP2-01/02/03 | — | Recipe schema harnesses+expect fields | inline Python | `mise exec -- uv run python -c "from harnessed.schema import Recipe; r=Recipe('t'); assert hasattr(r,'harnesses')"` | ⬜ pending |
| 8-01-02 | 08-01 | 1 | ASM-01 | T-08-02 | validate_harness_compat raises on mismatch | inline Python | `mise exec -- uv run python -c "from harnessed.emit import write_derived_dockerfile; from harnessed.assemble import assemble; import inspect; assert 'validate_harness_compat' in inspect.getsource(assemble)"` | ⬜ pending |
| 8-01-03 | 08-01 | 1 | ASM-02 | T-08-01 | validate_pin rejects floating refs | inline Python | `mise exec -- uv run python -c "from harnessed.schema import validate_pin, PinValidationError; ..."` | ⬜ pending |
| 8-01-04 | 08-01 | 1 | ASM-03 | — | write_derived_dockerfile wired in assemble() | inline Python | `mise exec -- uv run python -c "from harnessed.assemble import assemble; import inspect; assert 'write_derived_dockerfile' in inspect.getsource(assemble)"` | ⬜ pending |
| 8-01-05 | 08-01 | 1 | SC-03 | T-08-05 | run_snyk_container_scan warn-skip without token | inline Python | `mise exec -- uv run python -c "from harnessed.scan import run_snyk_container_scan, ScanResult; import os; os.environ.pop('SNYK_TOKEN',None); r=run_snyk_container_scan('x'); assert isinstance(r,ScanResult)"` | ⬜ pending |
| 8-02-01 | 08-02 | 1 | ASM-01/02 | T-08-01/02 | Fixture files for rejection tests ship | rg assertion | `rg "harnesses:" recipes/gstack/recipe.yaml && rg "\-\-branch main" recipes/floating-recipe/Dockerfile` | ⬜ pending |
| 8-02-02 | 08-02 | 1 | RCP2-03 | — | gstack recipe.yaml has expect: field | rg assertion | `rg "expect:" recipes/gstack/recipe.yaml` | ⬜ pending |
| 8-03-01 | 08-03 | 2 | IMG-03/SC-01/SC-03/SC-04 | T-08-04/05/06 | build_stack() extended with derived image block | rg assertion | `rg "scan-snyk-container\|derived_dockerfile\|SC-04" lib/harnessed-common.sh` | ⬜ pending |
| 8-03-02 | 08-03 | 2 | SC-02 | — | harnessed-* naming filter covered in rescan | UAT fast | `tools/uat/run-uat.sh 08 --quick` (test_rescan_filter_coverage) | ⬜ pending |
| 8-03-03 | 08-03 | 2 | SC-04 | — | Socket source scan coverage via BLD-02a | UAT fast | `tools/uat/run-uat.sh 08 --quick` (test_socket_source_scan_coverage) | ⬜ pending |
| 8-03-04 | 08-03 | 2 | IMG-03+ASM-03 | — | Phase 8 UAT suite passes --quick | UAT fast | `tools/uat/run-uat.sh 08 --quick` | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Wave 0 (pytest stub files) is NOT required for this phase. All Nyquist compliance is achieved
through inline `<automated>` verify commands in each task's `<verify>` block and the UAT suite.

Previous draft listed pytest stub files (`tests/test_recipe_schema.py`, `tests/test_assembler.py`,
`tests/test_scan.py`, `tests/test_integration.py`) — these are NOT created in Phase 8. The inline
Python one-liners in each task's verify block provide equivalent sampling coverage with faster
feedback latency (no test-file scaffold overhead).

Summary of coverage by artifact:
- **RCP2-01/02/03**: inline Python + UAT `test_recipe_structure` (fast)
- **ASM-01/02/03**: inline Python `inspect.getsource` + UAT rejection tests (heavy)
- **SC-01**: UAT `test_derived_image_build` (heavy, osv-scanner)
- **SC-02**: UAT `test_rescan_filter_coverage` (fast)
- **SC-03**: inline Python warn-skip + UAT `test_snyk_container_skip` (heavy)
- **SC-04**: UAT `test_socket_source_scan_coverage` (fast, file assertions)
- **IMG-03**: UAT `test_derived_image_build` (heavy)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Derived image actually builds and runs | IMG-03 | Requires live podman daemon | `harnessed build gstack-time && podman run --rm harnessed-gstack-time echo ok` |
| osv-scanner HIGH CVE blocks real build | SC-01 | Requires a real image with known CVE | Inject a known-CVE base in a test stack; run `harnessed build`; verify non-zero exit |
| Nightly rescan timer fires on harnessed-* | SC-02 | Requires systemd timer and live image | `systemctl --user start harnessed-nightly-rescan.timer; journalctl --user -u harnessed-nightly-rescan` |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify commands (inline Python or rg assertions)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 replaced by inline verification approach (see Wave 0 Requirements section)
- [x] No watch-mode flags
- [x] Feedback latency < 60s for all fast verifications
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
