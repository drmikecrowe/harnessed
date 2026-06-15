---
phase: 01-containerized-engine-transparent-stack
verified: 2026-06-14T00:00:00Z
status: passed
score: 9/9 requirements satisfied
---

# Phase 1: Containerized Engine + Transparent Stack Verification Report

**Phase Goal:** Stand up the dependency-free `harnessed` bash bootstrap, build the base/claude images via host `podman build`, and deliver the `transparent` stack (= today's `container`, host-mirror) as a host launcher with the `.claude.json` safety fix and zero behavioral regression. (No daemon-in-container.)
**Verified:** 2026-06-14
**Status:** passed (operator confirmed the live interactive run)

## Goal Achievement — Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `harnessed`/`container` open an interactive harness with host config + project mounted | ✓ VERIFIED | Operator ran `./harnessed transparent` → authenticated shell; non-interactive repro: attach drops to `/home/harnessed/<relpath>` |
| 2 | §4a layer (1Password/GPG/YubiKey/SSH/git/machine-id) + egress firewall present | ✓ VERIFIED | MOUNT_ARGS inspection (27 entries); firewall applied "57 IPs across 13 domains"; operator confirmed authenticated session |
| 3 | First run with only podman builds images + launches; no host Python/node/uv | ✓ VERIFIED | `podman build` of base→claude succeeded; bootstrap is pure bash; `harnessed-claude` carries node/pnpm/python in-image |
| 4 | A run never corrupts host `~/.claude.json` | ✓ VERIFIED | Unit check: host `~/.claude.json` never bind-mounted; per-instance copy-on-start file created + mounted rw; operator approved |
| 5 | Host-native attach (clean TTY) | ✓ VERIFIED | Launcher `exec`s the attach on the host; operator got an interactive shell |

**Score:** 5/5 truths verified

## Required Artifacts

| Artifact | Status | Details |
|----------|--------|---------|
| `harnessed` | ✓ EXISTS + SUBSTANTIVE | Host bootstrap: detect runtime, ensure/build images, dispatch (transparent/build/list/stop/remove/clean/--claude/--zai/--no-firewall) |
| `lib/harnessed-common.sh` | ✓ EXISTS + SUBSTANTIVE | Runtime detection, image build, lifecycle, firewall apply |
| `lib/harnessed-mounts.sh` | ✓ EXISTS + SUBSTANTIVE | §4a layer (host-absolute via host paths) |
| `lib/harnessed-transparent.sh` | ✓ EXISTS + SUBSTANTIVE | Transparent launcher (live host config + copy-on-start + attach) |
| `lib/harnessed-claude-config.sh` | ✓ EXISTS + SUBSTANTIVE | `.claude.json` copy-on-start safety |
| `lib/egress-firewall.sh` | ✓ EXISTS | Relocated from root (git mv) |
| `base/Dockerfile.harnessed-{base,claude}` | ✓ EXISTS + SUBSTANTIVE | Build succeeds; HOME=/home/harnessed; claude 2.1.177 on PATH |
| `stacks/transparent/stack.yaml` | ✓ EXISTS | `config: transparent` |
| `container` | ✓ EXISTS | Thin alias → `harnessed transparent` |
| `container.sh` | ✓ REMOVED | Clean cutover (superseded) |

## Requirements Coverage

| Requirement | Status |
|-------------|--------|
| ENG-01 bootstrap detects podman/docker, builds images first run | ✓ SATISFIED |
| ENG-02 host `podman build`/run, no DooD; podman the only host dep | ✓ SATISFIED |
| ENG-03 host-native interactive attach | ✓ SATISFIED |
| MODE-01 `harnessed transparent` host-mirror launch | ✓ SATISFIED |
| MODE-02 `container` thin alias, same behavior | ✓ SATISFIED |
| AUTH-01 transparent auth via live host config (no re-login) | ✓ SATISFIED |
| MNT-01 §4a host-integration layer | ✓ SATISFIED |
| MNT-02 project mount + egress firewall | ✓ SATISFIED |
| MNT-03 `~/.claude.json` never rw-bind-mounted (copy-on-start) | ✓ SATISFIED |

**Coverage:** 9/9 requirements satisfied

## Anti-Patterns Found

| File | Pattern | Severity | Resolution |
|------|---------|----------|------------|
| `lib/harnessed-mounts.sh` (during execution) | bare `var=$(pipeline)` under `set -euo pipefail` aborted the launcher at the YubiKey probe when no match | 🛑 Blocker (found + fixed) | Added `|| true` to fallible probes (commit `a963a69`); verified the launcher survives `set -e` |

## Gaps Summary

**No gaps.** Phase goal achieved; operator confirmed the live run. Ready to proceed to Phase 2.

## Verification Metadata

**Approach:** Goal-backward from ROADMAP success criteria + plan must-haves.
**Automated checks:** image build + claude resolution, MNT-03 copy-on-start, mount-arg construction under `set -e`, `bash -n` all scripts, bootstrap/alias/lifecycle `--help`/`--list`.
**Operator check:** live `./harnessed transparent` run — authenticated, project mounted, approved.
**Note:** the §4a `grep`-based extra-tools parse can't run under this agent's sandboxed shell (grep interception); verified by syntax + provenance (ported from `container.sh`) + the operator's live run.

---
*Verified: 2026-06-14*
*Verifier: Claude (inline) + operator confirmation*
