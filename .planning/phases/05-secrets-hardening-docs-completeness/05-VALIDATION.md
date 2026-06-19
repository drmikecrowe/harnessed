---
phase: 05
slug: secrets-hardening-docs-completeness
status: partial
nyquist_compliant: false   # every requirement has automated coverage; 4 live legs are irreducibly manual (operator 1Password / browser / overnight) — see Manual-Only
wave_0_complete: true
created: 2026-06-18
test_suite: tools/uat/phase-05.sh
---

# Phase 05 — Validation Strategy

> Per-phase validation contract. Reconstructed from the 4 plan SUMMARYs (State B) after
> `05-VERIFICATION.md` + `05-HUMAN-UAT.md` already existed. The project verifies behavior
> **transitively through the running `harnessed` CLI** — assembler unit tests are out of scope
> (REQUIREMENTS.md "Out of Scope"), so coverage lives in the bash UAT harness, not pytest.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Dependency-free bash UAT harness (`tools/uat/uat-common.sh` — AAA markers, pure-bash asserts; no bats/pytest) |
| **Config file** | none — the harness is self-contained; driven by `tools/uat/run-uat.sh` |
| **Quick run command** | `./tools/uat/run-uat.sh 5 --quick` |
| **Full suite command** | `./tools/uat/run-uat.sh 5` |
| **Estimated runtime** | ~1s quick (5 tests) · ~157s full (8 tests; 3 build/rescan container tests) |
| **Suite file** | `tools/uat/phase-05.sh` (8 `test_<id>` functions + `uat_run_phase`) |

---

## Sampling Rate

- **Quick (no containers):** `./tools/uat/run-uat.sh 5 --quick` — dispatch + unit-file + docs checks (<1s)
- **Full (before sign-off / `/gsd-verify-work`):** `./tools/uat/run-uat.sh 5` — adds the build/rescan tests; must be green
- **Max feedback latency:** ~1s quick · ~157s full

---

## Per-Requirement Verification Map

| Requirement | Secure Behavior (automatable leg) | Test | Type | Command | Status |
|-------------|-----------------------------------|------|------|---------|--------|
| **SEC-01** | Absent a schema, varlock is NEVER invoked (inert; no resolution banner) | `secrets_inert_and_skip` | behavioral / container | `run-uat.sh 5` | ✅ green |
| **SEC-02** | No token → snyk warns-and-skips, build stays green + non-interactive | `secrets_inert_and_skip` | behavioral / container | `run-uat.sh 5` | ✅ green |
| **SEC-02** | Present token forwarded → snyk invoked (auth-fail → warn, not abort) | `scanner_token_invoked` | behavioral / container | `run-uat.sh 5` | ✅ green |
| **SEC-03** | `auth` accepts only `snyk\|socket`; unknown/missing tool → clear error | `auth_dispatch` | behavioral / fast | `run-uat.sh 5 --quick` | ✅ green |
| **SEC-04** | `harnessed rescan` runs the ONLINE image scan; clean → exit 0 | `rescan_online` | behavioral / container | `run-uat.sh 5` | ✅ green |
| **SEC-04** | Timer/service units well-formed (oneshot, daily, Persistent, `%h` ExecStart) + linger prereq | `rescan_timer_units` | artifact / fast | `run-uat.sh 5 --quick` | ✅ green |
| **DOC-01** | README documents both modes, install, first-run build, quickstart, podman-only | `doc_readme` | artifact / fast | `run-uat.sh 5 --quick` | ✅ green |
| **DOC-02** | recipe-authoring + stacks guides exist and cite **real** on-disk examples | `doc_authoring_guides` | artifact / fast | `run-uat.sh 5 --quick` | ✅ green |
| **DOC-03** | secrets (host-side model + Snyk PAT URL + headless fallback) + service-authoring + troubleshooting (linger prereq) | `doc_ops_guides` | artifact / fast | `run-uat.sh 5 --quick` | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky — full suite last run 2026-06-18: 8 passed, 38 checks, 0 failed.*

---

## Wave 0 Requirements

- [x] `tools/uat/phase-05.sh` — 8 `test_<id>` functions covering the automatable legs of SEC-01..04 + DOC-01..03
- [x] Reuses existing `tools/uat/uat-common.sh` + `run-uat.sh` (no new framework install)
- [x] Secret tests use a `HARNESSED_SCHEMA` override at a nonexistent path — the operator's real `~/.config/harnessed/.env.schema` is never touched

---

## Manual-Only Verifications

The live legs below cannot run without an interactive 1Password desktop app, a real browser TTY,
or an overnight timer fire. They are tracked in `05-HUMAN-UAT.md` (HV-1..HV-4) and were the basis
for the `human_needed` verdict in `05-VERIFICATION.md`. **HV-1/HV-2 have since been verified live**
by the maintainer after the host-side resolution fix (`81a7f3f`); HV-3/HV-4 remain operator actions.

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live `op://` resolution → pod env | SEC-01 | Needs the 1Password desktop app authorizing the calling terminal + real vault items | HV-1 in `05-HUMAN-UAT.md` (verified live, fix `81a7f3f`) |
| Build scan with a 1Password-resolved token | SEC-01 | Same — needs live 1Password resolution | HV-2 in `05-HUMAN-UAT.md` (verified live) |
| `harnessed auth snyk\|socket` browser-auth persistence | SEC-03 | Needs an interactive browser flow at a real TTY | HV-3 in `05-HUMAN-UAT.md` |
| Nightly timer fires overnight (survive-logout) | SEC-04 | Needs `loginctl enable-linger` (host policy) + an overnight wall-clock fire | HV-4 in `05-HUMAN-UAT.md` |

---

## Validation Sign-Off

- [x] Every requirement (SEC-01..04, DOC-01..03) has an automated test for its scriptable behavior
- [x] Sampling continuity: no 3 consecutive requirements without an automated check
- [x] Wave 0 covers all MISSING references (the suite was the gap; now written + green)
- [x] No watch-mode flags (single-shot bash harness; `--quick` is a subset selector, not a watcher)
- [x] Feedback latency < ~157s full / ~1s quick
- [ ] `nyquist_compliant: true` — NOT set: 4 irreducible live legs are manual-only by design (operator 1Password / browser / overnight), tracked in 05-HUMAN-UAT.md

**Approval:** validated (partial) 2026-06-18 — all automatable behavior is green; remaining gaps are manual-only by nature, not missing tests.
