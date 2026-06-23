---
phase: 07-fat-base-agent-images
verified: 2026-06-23T00:00:00Z
status: gaps_found
score: 0/4 must-haves verified
overrides_applied: 0
gaps:
  - truth: "harnessed-base does NOT have claude, omp, codex, or gemini CLIs"
    status: failed
    reason: >
      ROADMAP SC-1 requires codex AND gemini CLIs absent from the base image.
      base/Dockerfile.harnessed-base lines 81-82 still contain npm:@openai/codex and
      npm:@google/gemini-cli in the mise use -g block. Claude and omp CLIs are correctly
      absent, but the partial delivery leaves codex and gemini in the base, violating
      IMG-01 ("No harness CLIs in base") and ROADMAP SC-1. The PLAN acknowledged this
      as intentional (07-01-PLAN.md requirements field: "IMG-01 (partial — claude/omp
      only; codex/gemini deferred)"), but the ROADMAP contract has not been updated to
      reflect the narrowed scope, and no specific later phase is chartered to complete
      the removal.
    artifacts:
      - path: "base/Dockerfile.harnessed-base"
        issue: "Lines 81-82: npm:@openai/codex and npm:@google/gemini-cli still present in mise use -g block"
    missing:
      - >
        Decision required: either (a) update ROADMAP.md SC-1 to formally defer
        codex/gemini CLI removal to a named later phase, or (b) remove those CLIs from
        base/Dockerfile.harnessed-base and update Dockerfile.harnessed-codex and
        Dockerfile.harnessed-gemini to install them locally. The PLAN's rationale
        (those Dockerfiles state the CLIs are pre-installed in the base) is a real
        constraint — option (a) is lower risk for Phase 7; option (b) closes IMG-01
        fully but widens scope.
human_verification:
  - test: >
      Run `podman run --rm harnessed-claude:latest bash -c 'command -v claude && echo PASS || echo FAIL'`
    expected: "Prints PASS — confirms claude CLI is present in harnessed-claude (SC-2)"
    why_human: "Requires a built image and a running container; cannot verify statically"
  - test: >
      Run `podman run --rm harnessed-omp:latest omp --version`
    expected: "Exits 0 and prints version — confirms omp CLI in harnessed-omp (SC-3)"
    why_human: "Requires a built image and a running container; cannot verify statically"
  - test: >
      On a clean environment (no images present), run `harnessed build` with no stack argument
    expected: >
      Exits 0 and all four images exist: `podman image inspect harnessed-base:latest
      harnessed-claude:latest harnessed-omp:latest harnessed-hatago:latest` all exit 0 (SC-4)
    why_human: "Requires actually running the build; cannot verify exit code statically"
  - test: >
      Run `podman run --rm harnessed-base:latest mise ls`
    expected: >
      Output includes node 24.x, bun, rust, go, python entries (SC-1 partial — runtimes present)
    why_human: "Requires a built image and a running container; cannot verify statically"
---

# Phase 7: Fat Base + Agent Images Verification Report

**Phase Goal:** Rebuild `harnessed-base` as a fat toolchain image (all runtimes pre-installed, no harness CLIs) and create the `agents/` directory with standalone cached images for the claude and omp harness CLIs.
**Verified:** 2026-06-23
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (from ROADMAP.md Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|---------|
| 1 | `harnessed-base` has bun, rust, go, node@24, python, pnpm@11; does NOT have claude, omp, codex, or gemini CLIs | PARTIAL FAIL | node@24/bun/rust/go present (lines 73-82); claude/omp absent (comment line 65 confirms). BUT: `npm:@openai/codex` (line 81) and `npm:@google/gemini-cli` (line 82) still in mise use -g block — violates "NOT have... codex, or gemini CLIs" |
| 2 | `harnessed-claude` builds `FROM harnessed-base` and passes `claude --version` without re-downloading runtimes | UNCERTAIN | FROM harnessed-base:latest confirmed (Dockerfile.harnessed-claude line 4). `claude --version` requires live container — human verification required |
| 3 | `harnessed-omp` builds `FROM harnessed-base` and passes `omp --version` inside the container | UNCERTAIN | FROM harnessed-base:latest confirmed (Dockerfile.harnessed-omp line 11). `omp --version` requires live container — human verification required |
| 4 | `harnessed build` (bare) produces harnessed-base, harnessed-claude, harnessed-omp, and hatago without error | UNCERTAIN | Code is fully wired: build_images() has all four build blocks (lines 81-100); ensure_images() checks all four (line 201). Actual build execution requires live run — human verification required |

**Score:** 0/4 truths fully verified (1 FAILED, 3 UNCERTAIN/human-needed)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `base/Dockerfile.harnessed-base` | Fat toolchain with node@24, bun, rust, go; no claude/omp CLIs | PARTIAL — codex/gemini gap | node@24 (line 73), bun (line 76), rust (line 77), go (line 78) present; claude/omp CLIs absent; but npm:@openai/codex (line 81) and npm:@google/gemini-cli (line 82) still installed |
| `agents/claude/agent.yaml` | type: agent descriptor with dockerfile ref | VERIFIED | type: agent, harness: claude, dockerfile: base/Dockerfile.harnessed-claude — all fields correct |
| `agents/omp/agent.yaml` | type: agent descriptor with dockerfile ref | VERIFIED | type: agent, harness: omp, dockerfile: base/Dockerfile.harnessed-omp — all fields correct |
| `lib/harnessed-common.sh` | build_images() includes omp build block; ensure_images() checks omp | VERIFIED | omp block lines 91-95; ensure_images condition line 201 includes HARNESSED_OMP_IMAGE; ensure_omp_image() lazy fallback still present at line 211 |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `base/Dockerfile.harnessed-base` | `base/Dockerfile.harnessed-claude` | FROM harnessed-base | WIRED | Dockerfile.harnessed-claude line 4: `FROM harnessed-base:latest` |
| `base/Dockerfile.harnessed-base` | `base/Dockerfile.harnessed-omp` | FROM harnessed-base | WIRED | Dockerfile.harnessed-omp line 11: `FROM harnessed-base:latest` |
| `agents/claude/agent.yaml` | `base/Dockerfile.harnessed-claude` | dockerfile field reference | WIRED | agent.yaml line 4: `dockerfile: base/Dockerfile.harnessed-claude` |
| `agents/omp/agent.yaml` | `base/Dockerfile.harnessed-omp` | dockerfile field reference | WIRED | agent.yaml line 4: `dockerfile: base/Dockerfile.harnessed-omp` |
| `lib/harnessed-common.sh build_images()` | `HARNESSED_OMP_IMAGE` | ensure_omp_image call or inline build | WIRED | Lines 91-95: `"$CONTAINER_RUNTIME" build -t "$HARNESSED_OMP_IMAGE" -f "$HARNESSED_DIR/base/Dockerfile.harnessed-omp"` |

### Data-Flow Trace (Level 4)

Not applicable — this phase produces Dockerfile and shell build scripts, not components rendering dynamic data.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| node@24 in Dockerfile | `rg "node@24" base/Dockerfile.harnessed-base` | exits 0, line 73 | PASS |
| bun/rust/go in Dockerfile | `rg "bun\|rust\|go" base/Dockerfile.harnessed-base` | exits 0, lines 76-78 | PASS |
| opencode-ai absent | `rg "opencode-ai" base/Dockerfile.harnessed-base` | exits 1 (absent) | PASS |
| node@22 absent | `rg "node@22" base/Dockerfile.harnessed-base` | exits 1 (absent) | PASS |
| codex/gemini still present | `rg "@openai/codex\|@google/gemini-cli" base/Dockerfile.harnessed-base` | exits 0, lines 81-82 | FAIL (violates SC-1) |
| agents/claude/agent.yaml exists with type:agent | `rg "type: agent" agents/claude/agent.yaml` | exits 0 | PASS |
| agents/omp/agent.yaml exists with type:agent | `rg "type: agent" agents/omp/agent.yaml` | exits 0 | PASS |
| build_images() omp block | `rg "HARNESSED_OMP_IMAGE" lib/harnessed-common.sh \| rg "build -t"` | lines 91-94 | PASS |
| ensure_images() OMP check | `rg "HARNESSED_OMP_IMAGE" lib/harnessed-common.sh \| rg "image_exists"` | line 201 | PASS |
| commits b2b6273, 4495204, 3c30d48 | `git log --oneline <hashes>` | all three present | PASS |

### Probe Execution

No probe scripts declared or found in `scripts/*/tests/probe-*.sh`.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|---------|
| IMG-01 | 07-01-PLAN.md (partial) | Fat harnessed-base with all runtimes; No harness CLIs in base | PARTIAL | node@24/bun/rust/go/python added; claude/omp removed; codex/gemini STILL present — requirement not fully met |
| IMG-02 | 07-02-PLAN.md | agents/ directory with type:agent entries; harnessed-claude and harnessed-omp buildable | SATISFIED (code) | agents/claude/agent.yaml and agents/omp/agent.yaml created; build_images() updated; runtime verification deferred to human check |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `base/Dockerfile.harnessed-base` | 99 | `mise up 2>/dev/null` baked into .bashrc — silently upgrades all tools at every interactive shell session, post-scan | Warning | Breaks the supply-chain scan guarantee (tools may upgrade past the scanned version); flagged as CR-01 in 07-REVIEW.md |
| `base/Dockerfile.harnessed-base` | 75-78 | `python@latest`, `bun`, `rust`, `go` unpinned | Warning | Non-reproducible image identity; two builds on different days may produce different tool sets; flagged as WR-01 in 07-REVIEW.md |

No `TBD`, `FIXME`, or `XXX` markers found in phase-modified files.

Note: 07-REVIEW.md (code review artifact) also flags CR-02 — that `build_images()` including omp violates the pre-existing HRN-01 lazy-build contract (claude-only users are now forced to build omp on first run). This is a real design tension between ROADMAP SC-4 (which requires omp in bare build) and the HRN-01 contract. The PLAN chose SC-4; the implementation delivers it. This is a pre-existing design conflict, not a new anti-pattern introduced by Phase 7.

### Human Verification Required

### 1. claude --version in harnessed-claude container

**Test:** `podman run --rm harnessed-claude:latest bash -c 'command -v claude && echo PASS || echo FAIL'`
**Expected:** Prints PASS — confirms the Claude Code CLI is present in the claude harness image (SC-2)
**Why human:** Requires a built harnessed-claude image and container execution

### 2. omp --version in harnessed-omp container

**Test:** `podman run --rm harnessed-omp:latest omp --version`
**Expected:** Exits 0 and prints omp version string (SC-3)
**Why human:** Requires a built harnessed-omp image and container execution

### 3. harnessed build (bare) produces all four images

**Test:** On a clean environment with no images, run `harnessed build` with no stack argument
**Expected:** Exits 0; `podman image inspect harnessed-base:latest harnessed-claude:latest harnessed-omp:latest harnessed-hatago:latest` all exit 0 (SC-4)
**Why human:** Requires actually running the build pipeline end-to-end

### 4. harnessed-base runtime inventory

**Test:** `podman run --rm harnessed-base:latest mise ls`
**Expected:** Output includes node 24.x, bun, rust, go, python entries; no claude, omp entries
**Why human:** Requires a built harnessed-base image and container execution

### Gaps Summary

**One BLOCKER gap** prevents full phase goal achievement:

**SC-1 is only partially satisfied.** ROADMAP success criterion 1 requires `harnessed-base` to NOT have "claude, omp, codex, or gemini CLIs." The base correctly removes claude and omp CLIs. However, `npm:@openai/codex` (line 81) and `npm:@google/gemini-cli` (line 82) remain in `base/Dockerfile.harnessed-base`. This was an intentional partial delivery documented in 07-01-PLAN.md (requirements field: "IMG-01 (partial — claude/omp only; codex/gemini deferred)") with sound rationale: `Dockerfile.harnessed-codex` and `Dockerfile.harnessed-gemini` depend on these CLIs being pre-installed in the base.

The ROADMAP contract has not been updated to reflect this narrowing, and no specific later phase is chartered to complete the codex/gemini CLI removal. The developer must make an explicit decision:

- **Option A (lower risk):** Update ROADMAP.md Phase 7 SC-1 to read "does NOT have claude or omp CLIs" and create Phase 8+ work to remove codex/gemini from base after those Dockerfiles are updated to install them locally.
- **Option B (complete IMG-01 now):** Update `Dockerfile.harnessed-codex` and `Dockerfile.harnessed-gemini` to install their CLIs locally, then remove them from `Dockerfile.harnessed-base`.

The three UNCERTAIN truths (SC-2, SC-3, SC-4) have correct code implementations and are blocked only by the need to run containers for verification. These are expected to pass once the live environment is available.

---

_Verified: 2026-06-23_
_Verifier: Claude (gsd-verifier)_
