---
phase: 07-fat-base-agent-images
plan: "03"
status: completed
gap_closure: true
tags: [img-01, cr-01, cr-02, hrn-01, supply-chain, dockerfile]
key-decisions:
  - "Moved npm:@openai/codex from harnessed-base to harnessed-codex — each harness image now self-contained"
  - "Moved npm:@google/gemini-cli from harnessed-base to harnessed-gemini — each harness image now self-contained"
  - "Removed mise up 2>/dev/null from .bashrc — auto-upgrades bypass the scan gate (CR-01)"
  - "Restored HRN-01: omp removed from build_images(); ensure_images() checks only claude+hatago (CR-02)"
  - "ROADMAP SC-1 marked IMG-01 complete; SC-4 updated to document HRN-01 lazy-build contract"
metrics:
  completed: "2026-06-23"
  tasks: 5
  files_modified: 5
---

# Phase 07 Plan 03: Gap Closure — SC-1, CR-01, CR-02 Summary

Closes the SC-1 IMG-01 gap identified in 07-VERIFICATION.md and fixes two code review blockers
from 07-REVIEW.md. Each harness Dockerfile is now fully self-contained for its CLI install.
The supply-chain scan guarantee is restored (no auto-upgrades at runtime). The HRN-01 lazy-build
contract for omp is restored.

## Files Modified

| File | Change |
|------|--------|
| `base/Dockerfile.harnessed-codex` | Added `RUN mise use -g npm:@openai/codex && mise install` before config block; updated header comment |
| `base/Dockerfile.harnessed-gemini` | Added `RUN mise use -g npm:@google/gemini-cli && mise install` before config block; updated header comment |
| `base/Dockerfile.harnessed-base` | Removed `npm:@openai/codex` and `npm:@google/gemini-cli` from mise use -g block; removed `mise up 2>/dev/null` from .bashrc; updated block comment to IMG-01 complete |
| `lib/harnessed-common.sh` | Removed 5-line omp build block from `build_images()`; updated function comment; fixed `ensure_images()` condition to check only CLAUDE+HATAGO |
| `.planning/ROADMAP.md` | SC-1 marked "IMG-01 complete"; SC-4 updated to reflect HRN-01 lazy-build contract for omp |

## Verification Results

All 8 plan verification checks pass:

1. `rg "@openai/codex" base/Dockerfile.harnessed-base` — exits 1 (PASS: absent)
2. `rg "@google/gemini-cli" base/Dockerfile.harnessed-base` — exits 1 (PASS: absent)
3. `rg "npm:@openai/codex" base/Dockerfile.harnessed-codex` — exits 0 (PASS: present)
4. `rg "npm:@google/gemini-cli" base/Dockerfile.harnessed-gemini` — exits 0 (PASS: present)
5. `rg "mise up" base/Dockerfile.harnessed-base` — exits 1 (PASS: absent)
6. `build_images()` — confirmed no omp build block (lines 67-97; function closes at line 97 with no OMP invocation)
7. `ensure_images()` condition — references only HARNESSED_CLAUDE_IMAGE and HARNESSED_HATAGO_IMAGE (PASS)
8. `ensure_omp_image()` lazy function — still present at line 206, unchanged (PASS)

Note: the plan's verification command for check 6 used `-A30` which spilled into `ensure_omp_image()` below `build_images()` — direct line inspection confirms `build_images()` correctly ends at line 97 with no omp block.

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1 | 2bc5dbc | install codex CLI locally in harnessed-codex (SC-1) |
| Task 2 | 024cdae | install gemini CLI locally in harnessed-gemini (SC-1) |
| Task 3 | c8b85b3 | remove codex/gemini CLIs and mise up from harnessed-base (SC-1 + CR-01) |
| Task 4 | edaeb98 | restore HRN-01 lazy-build contract for omp (CR-02) |
| Task 5 | 94a0792 | update ROADMAP Phase 7 SC-1 and SC-4 for gap closure |

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

- `base/Dockerfile.harnessed-codex` — exists and contains `mise use -g npm:@openai/codex`
- `base/Dockerfile.harnessed-gemini` — exists and contains `mise use -g npm:@google/gemini-cli`
- `base/Dockerfile.harnessed-base` — exists; codex/gemini/mise-up absent; node@24 and bun present
- `lib/harnessed-common.sh` — build_images() builds base+claude+hatago only; ensure_images() clean; ensure_omp_image() intact
- All 5 commits confirmed in git log
