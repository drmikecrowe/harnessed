---
phase: 9
slug: surgical-profile-mount-history-surfacing
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-24
---

# Phase 9 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | bash integration tests (tools/uat/) |
| **Config file** | tools/uat/phase-09.sh |
| **Quick run command** | `bash tools/uat/phase-09.sh quick` |
| **Full suite command** | `bash tools/uat/phase-09.sh` |
| **Estimated runtime** | ~60 seconds |

---

## Sampling Rate

- **After every task commit:** Run `bash tools/uat/phase-09.sh quick`
- **After every plan wave:** Run `bash tools/uat/phase-09.sh`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 09-01-01 | 01 | 1 | MNT2-06 | — | manifest file controls all mounts | unit | `bash tools/uat/phase-09.sh manifest` | ❌ W0 | ⬜ pending |
| 09-02-01 | 02 | 1 | MNT2-01 | — | profile dir not bind-mounted | integration | `bash tools/uat/phase-09.sh profile-mount` | ❌ W0 | ⬜ pending |
| 09-03-01 | 03 | 2 | MNT2-02 | — | claude history written to host | integration | `bash tools/uat/phase-09.sh claude-history` | ❌ W0 | ⬜ pending |
| 09-04-01 | 04 | 2 | MNT2-03 | — | omp history written to host | integration | `bash tools/uat/phase-09.sh omp-history` | ❌ W0 | ⬜ pending |
| 09-05-01 | 05 | 2 | MNT2-04 | — | antigravity history written to host | integration | `bash tools/uat/phase-09.sh antigravity-history` | ❌ W0 | ⬜ pending |
| 09-06-01 | 06 | 2 | MNT2-05 | — | gstack skills visible after session | integration | `bash tools/uat/phase-09.sh skills-visible` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tools/uat/phase-09.sh` — integration test stubs for MNT2-01 through MNT2-06
- [ ] Quick-mode gate checking manifest file existence and basic mount verification

*Existing infrastructure (tools/uat/) covers the test scaffolding approach.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| gstack skills visible in running session | MNT2-05 | Requires live container with gstack recipe | `harnessed build gstack-time && harnessed gstack-time`, run `/gsd-help` and confirm gstack skills appear |
| claude project history on host after session | MNT2-02 | Requires real session write | Launch stack, run any query, verify `~/.claude/projects/<slug>/` on host |
| omp session history on host | MNT2-03 | Requires omp session write | Launch omp stack, verify `~/.omp/agent/sessions/<slug>/` |
| antigravity conversation history on host | MNT2-04 | Requires antigravity session | Launch antigravity stack, verify `~/.gemini/antigravity-cli/conversations/` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
