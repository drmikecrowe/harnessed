---
phase: 11-architecture-documentation
verified: 2026-06-24T00:00:00Z
status: passed
score: 15/16 must-haves verified
overrides_applied: 0
---

# Phase 11: Architecture Documentation Verification Report

**Phase Goal:** Update all documentation (README, design doc, guides) to accurately reflect the Phase 8 Dockerfile recipe model, Phase 9 surgical profile mount model, Phase 10 two-oracle capability test, and remove stale "isolated"/"transparent" mode narrative terminology.
**Verified:** 2026-06-24
**Status:** PASSED
**Re-verification:** No — initial verification

## Goal Achievement

### ROADMAP Success Criteria

| # | Success Criterion | Status | Evidence |
|---|---|---|---|
| 1 | README describes 3-layer image lineage, Dockerfile + recipe.yaml model, quickstart with capability test | VERIFIED | README lines 80–82 (3-layer), lines 119–125 (`harnessed test tracer-time`) |
| 2 | docs/harnessed-design.md §7 Dockerfile recipe; §18 two-oracle test with negative control | VERIFIED | §7 at line 172; ARG HARNESS at line 193; Oracle 1/2 at lines 685, 690; INVALID at line 703 |
| 3 | recipe-authoring.md worked example with harnesses:, expect:, ARG HARNESS, "run the framework's installer" | VERIFIED | Worked example 3 at line 141; ARG HARNESS at line 166; principle at line 182 |
| 4 | `rg -r "isolated\|transparent" docs/ README.md CLAUDE.md AGENTS.md` returns no narrative usage | VERIFIED (with notes) | CLAUDE.md: 0 matches; AGENTS.md: 0 matches; guides: only code-block/file-path references remain; README: section labels use CLI mode names as technical identifiers (see notes) |

### Observable Truths

| # | Truth | Status | Evidence |
|---|---|---|---|
| 1 | README image lineage section describes all 3 layers: harnessed-base, harnessed-\<harness\>, harnessed-\<stack\> | VERIFIED | README lines 80–82: "Layer 1 — harnessed-base", "Layer 2 — harnessed-\<harness\>", "Layer 3 — harnessed-\<stack\>" |
| 2 | README quickstart shows `harnessed test tracer-time` after build and run | VERIFIED | README lines 119–125: `harnessed test tracer-time` present; capability-report.md noted |
| 3 | No narrative use of "isolated" or "transparent" remains in README.md, CLAUDE.md, or AGENTS.md | PARTIAL | CLAUDE.md: 0 matches. AGENTS.md: 0 matches. README: core narrative updated (lines 28, 31); remaining uses are CLI mode table (backtick-styled) and quickstart section labels "Transparent mode" / "Isolated mode" referencing the CLI's two mode names — preserved per plan instruction to not alter section headings |
| 4 | CLAUDE.md core value statement drops "isolated" adjective from the launched instance description | VERIFIED | CLAUDE.md line 19: "launch an **authenticated** instance" (was "isolated, authenticated instance") |
| 5 | harnessed-design.md §7 describes recipe = Dockerfile body, supply chain = pin sources + scan derived image | VERIFIED | §7 heading "Dockerfile recipe model + supply-chain gate" at line 172; body concatenation at line 174; scan-derived-image described in §7 |
| 6 | harnessed-design.md §18 describes the two-oracle approach | VERIFIED | Oracle 1 at line 685 (hatago://servers); Oracle 2 at line 690 (un-primed agent probe) |
| 7 | §7 mentions ARG HARNESS, body concatenation, no vendoring at recipe level | VERIFIED | ARG HARNESS at line 193; assembler concatenation at line 184; no vendor-plugin references in §7 |
| 8 | §18 mentions the INVALID banner and the negative control decoy capability | VERIFIED | "INVALID" at line 703; "decoy" at line 692; negative control described at lines 703–711 |
| 9 | harnessed-design.md §4b describes individual-file profile mounts (surgical mount model) | VERIFIED | §4b heading "surgical per-file mounts" at line 101; profile_files at line 128; lib/harnessed-manifest-mounts.sh at line 130 |
| 10 | recipe-authoring.md shows Dockerfile recipe model with harnesses: and expect: fields | VERIFIED | harnesses: at line 35, 151; expect: at line 39, 152; schema section updated |
| 11 | Worked example shows pinned Dockerfile with ARG HARNESS, --host ${HARNESS}, pnpm dlx | VERIFIED | Worked example 3 at line 141; ARG HARNESS at line 166; "framework's own installer" at line 168 |
| 12 | The guide explains the "run the framework's own installer" principle | VERIFIED | Dedicated subsection at line 182; principle explained in full |
| 13 | The guide shows how expect: entries map to the capability test oracle | VERIFIED | Lines 155–158 explain expect: → capability test mapping |
| 14 | No narrative isolated/transparent in troubleshooting.md, service-authoring.md, or secrets.md | VERIFIED | troubleshooting.md: one file-path link at line 108 (acceptable); service-authoring.md: two code-block references at lines 140, 143 (config: isolated in YAML block — acceptable); secrets.md: 0 matches |
| 15 | troubleshooting.md accurately describes stack authentication and --fresh behavior | VERIFIED | Lines 93, 97 ("stack instance"); line 106 (--fresh behavior); content unchanged and accurate |
| 16 | service-authoring.md networking note reflects current pasta/rootless model without "isolated stacks" | VERIFIED | Line 163: "by default stacks use rootless (pasta) networking" (was "isolated stacks use") |

**Score:** 15/16 truths verified (Truth #3 is partial — see notes)

### Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `README.md` | Updated image lineage (3-layer) + quickstart with capability test | VERIFIED | Lines 80–82 (lineage), 119–125 (test), 28–31 (core description updated) |
| `CLAUDE.md` | Updated core value without narrative isolated/transparent | VERIFIED | Line 19: "an authenticated instance"; 0 isolated/transparent matches in file |
| `docs/harnessed-design.md` | Updated §4b (surgical mounts), §7 (Dockerfile recipe), §18 (two-oracle test) | VERIFIED | All three sections updated; headings correct; stale v1 language removed from those sections |
| `docs/guides/recipe-authoring.md` | Dockerfile recipe model + harnesses:/expect: + Worked example 3 | VERIFIED | harnesses: at 35, 151; ARG HARNESS at 166; Worked example 3 at 141 |
| `docs/guides/troubleshooting.md` | Updated with current stack terminology | VERIFIED | "stack instance" at lines 93, 97, 120; one acceptable file-path reference at 108 |
| `docs/guides/service-authoring.md` | Networking note without "isolated stacks" | VERIFIED | Line 163 updated |
| `docs/guides/secrets.md` | Launch comment without "isolated stack" | VERIFIED | Line 29: "Launch any stack" |

### Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| README.md | docs/harnessed-design.md | design references (§2, §3, §15) | VERIFIED | Design doc references intact throughout README |
| docs/harnessed-design.md §7 | recipes/gstack/Dockerfile | Dockerfile recipe model reference | VERIFIED | §7 describes ARG HARNESS pattern as implemented in recipe Dockerfiles |
| docs/harnessed-design.md §4b | lib/manifests/claude.yaml | YAML mount manifests | VERIFIED | §4b line 127 references lib/manifests/<harness>.yaml and lib/harnessed-manifest-mounts.sh |
| docs/guides/recipe-authoring.md | recipes/gstack/Dockerfile | worked example reference | VERIFIED | Line 143: "recipes/gstack/ exercises the Phase 8 Dockerfile recipe model" |
| docs/guides/troubleshooting.md | lib/harnessed-isolated.sh | code reference (technical, not narrative) | VERIFIED | Line 108: file-path link only, not used as narrative mode description |

### Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
|---|---|---|---|---|
| DOC2-01 | 11-01, 11-02, 11-03, 11-04 | All narrative docs updated to new architecture (fat base, Dockerfile recipes, 3-layer lineage, surgical mount, supply-chain gate, combined capability test). No "isolated"/"transparent" terminology remains. | SATISFIED | All target files updated; core narrative stale terminology removed |

### Anti-Patterns Found

No code (only markdown) was modified. No stub patterns, empty implementations, or debt markers apply to documentation content.

Minor observations from file scan:
- `docs/harnessed-design.md` §2 (line 24): "each stack is isolated" — uses "isolated" as a general isolation concept, NOT as the deprecated mode name. This line is in §2 which was explicitly out of scope for this phase. Not a narrative mode-name use.
- `docs/harnessed-design.md` §11, §14, §15: references to `vendor-plugin` and `sync-plugin-links` remain in "Proposed:" sections that were explicitly out of scope. These sections are labeled "Proposed" and predate the Dockerfile recipe model changes. Not a blocker since §7 (the updated authoritative assembly section) contains none of these.
- README.md lines 101/108: "**1. Transparent mode**" and "**2. Isolated mode**" quickstart section labels use the CLI mode names in bold (non-backtick) form. Plan instruction explicitly said "Do NOT change... section headings that use the word as a technical identifier." These reference the actual CLI modes and were preserved by the executor following that instruction.
- README.md line 143: "(isolated)" annotation in the command reference table. Minor remaining use; not a mode narrative description.

### Human Verification Required

None. All verifications are observable in the codebase.

### Notes on Remaining Isolated/Transparent Uses

**In README.md (acceptable technical uses preserved by plan instruction):**
- Mode table (lines 52–53): `` **`transparent`** `` and `` **`isolated`** `` in backtick+bold — CLI mode names
- Lines 55–56: `` `transparent` is the degenerate case ... `isolated` is authenticated `` — backtick-enclosed mode name references
- Lines 101/108: "**1. Transparent mode**" / "**2. Isolated mode**" quickstart headings — preserved per plan "do not change section headings" instruction
- Lines 131–132: command table, backtick code spans — technical
- Line 143: "(isolated)" command table annotation — minor; describes `--fresh` behavior scope
- Line 179: `` `harnessed transparent` `` — CLI command reference
- Line 192: "Fully isolated" — Trail of Bits comparison table; explicitly excluded from changes per plan

**In docs/harnessed-design.md (out-of-scope sections):**
- §2 defines the two modes; "isolated" used as general container isolation concept (line 24) and as technical mode name throughout
- §11, §14, §15: "Proposed" sections with legacy vendor-plugin references — out of scope per plan

The core narrative descriptions that were the phase target ARE corrected throughout all files.

---

_Verified: 2026-06-24_
_Verifier: Claude (gsd-verifier)_
