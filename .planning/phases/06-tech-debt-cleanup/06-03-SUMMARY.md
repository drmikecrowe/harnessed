---
phase: 06-tech-debt-cleanup
plan: 03
subsystem: infra
tags: [harnessed-net, podman, host-gateway, host.containers.internal, docs, comments, tech-debt, gap-closure]

# Dependency graph
requires:
  - phase: 04-isolated-shared-services
    provides: the shipped publish-to-0.0.0.0 + podman host-gateway (host.containers.internal) reachability model that this plan reconciles the missed docs/comments to (svc_up -p publish in lib/harnessed-services.sh, assemble.py URL rewrite, egress-firewall 169.254.1.2 allow rule)
  - phase: 06-01
    provides: the B1–B7 scoped sweep whose B1+B4 correction class this plan extends verbatim to the 6 files the original 06-RESEARCH.md Item B audit missed (lib/harnessed-services.sh:4-6 B1 wording + recipes/ping/recipe.yaml:4-7 B4 wording)
provides:
  - The 6 reconciled files (docs/codebase/INTEGRATIONS.md ×5 locations, services/ping/server.py docstring, tools/harnessed/schema.py ServiceDef docstring, CLAUDE.md Engine bullet, stacks/ping-time/stack.yaml comment, harnessed svc-up help + section comment) now state the publish-to-0.0.0.0 + host.containers.internal:<port> PRIMARY model with HARNESSED_NET as the opt-in
  - SC-1 closed at the repo-wide level for the authoritative (non-generated) docs/code/manifests/CLI surface
affects: [/gsd-verify-work live-test gate (deferred), future doc passes, docs/codebase/* regenerated snapshots (residual — see Deviations)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Doc/comment reconciliation mirrors shipped in-repo prose (lib/harnessed-services.sh:4-6 B1 + recipes/ping/recipe.yaml:4-7 B4 + design.md §9 PRIMARY framing) verbatim instead of authoring fresh networking wording"
    - "Stash-and-pop commit hygiene for a multi-task plan on a dirty tree: `git stash push -- <dirty paths>` before editing, `git add` (mine-only) per task, commit, `git stash pop` to restore the user's WIP layered onto the committed corrections — the 3-way pop merges cleanly because the plan's comment-only edits and the user's multi-harness WIP occupy disjoint regions"

key-files:
  created:
    - .planning/phases/06-tech-debt-cleanup/06-03-SUMMARY.md
  modified:
    - docs/codebase/INTEGRATIONS.md
    - services/ping/server.py
    - tools/harnessed/schema.py
    - CLAUDE.md
    - stacks/ping-time/stack.yaml
    - harnessed

key-decisions:
  - "Mirrored the B1+B4+design-§9 vocabulary verbatim — authored NO new networking prose (same discipline as 06-01)."
  - "Used `git stash push -- <4 dirty paths>` + pop (not 06-01's `git update-index --cacheinfo`) to keep the user's pre-existing uncommitted multi-harness WIP out of the 06-03 commits while leaving the working tree correct (WIP + my corrections layered). Pop merged cleanly: the plan's comment-only edits and the WIP's multi-harness additions occupy disjoint regions of each file."
  - "Did NOT hand-edit the 4 residual stale refs in 3 generated `docs/codebase/*` map-codebase snapshots (ARCHITECTURE.md:314, CONVENTIONS.md:599, STRUCTURE.md:173/248). They are regenerable artifacts not flagged by 06-VERIFICATION.md's SC-1 audit and outside this plan's `files_modified`. Documented as a finding (Rule 4: no unapproved scope expansion; generated artifacts should be regenerated, not hand-patched)."

patterns-established:
  - "Repo-wide SC grep now treats `docs/codebase/*` (map-codebase snapshots) as a separate regenerable stratum distinct from authoritative docs/code/manifests/CLI"

requirements-completed: [SC-1]

# Metrics
duration: ~25min
completed: 2026-06-21
---

# Plan 06-03: SC-1 repo-wide gap closure — harnessed-net sweep Summary

**Closed ROADMAP SC-1 at the repo-wide level by extending the B1+B4 correction (plan 06-01) to the 6 files the original `06-RESEARCH.md` Item B audit missed — comment/docstring/doc/help-string edits only (D-12 zero runtime risk), mirroring shipped `host.containers.internal` + `HARNESSED_NET` opt-in vocabulary verbatim.**

## Performance

- **Duration:** ~25 min
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- `docs/codebase/INTEGRATIONS.md` — 5 stale locations corrected: §"HTTP service sidecars" body + canonical-example resolved URL, §"Shared Services" heading + body, and the §"Summary" ASCII diagram edge. The old `http://ping:8080/mcp` URL survives only as the labeled `HARNESSED_NET` opt-in bridge form (mirroring B4).
- `services/ping/server.py` — module docstring (lines 6–8) now matches the file's own accurate `host.containers.internal` + `allowed_hosts` body (lines 19–25) that design §9 cites as canonical; the body and all functions untouched.
- `tools/harnessed/schema.py` — `ServiceDef` docstring mirrors B1 (host-published port + host.containers.internal) + B4 (host-gateway resolved URL, DNS-name form labeled as the `HARNESSED_NET` opt-in); no dataclass field or type changed.
- `CLAUDE.md` — Engine bullet now states rootless (pasta) networking by default + host-gateway reachability + `HARNESSED_NET` opt-in (mirrors `lib/harnessed-isolated.sh:121-135`).
- `stacks/ping-time/stack.yaml` — sidecar comment now states host-gateway proxy (`HARNESSED_NET` opt-in); YAML keys/values unchanged.
- `harnessed` — `svc up` help string + service-lifecycle section comment now state host-published sidecar framing; the `if [ -n "$SVC_ACTION" ]; then` dispatch gate and all control flow untouched; usage-block column alignment preserved.

## Task Commits

Each task was committed atomically:

1. **Task 1: HIGH-confidence corrections (G1–G4: INTEGRATIONS.md ×5, server.py docstring, schema.py ServiceDef docstring, CLAUDE.md Engine bullet)** - `f39790b` (docs)
2. **Task 2: MEDIUM-confidence corrections (G5–G6: stack.yaml comment, harnessed help string + section comment)** - `4f925e7` (docs)

## Files Created/Modified
- `docs/codebase/INTEGRATIONS.md` - §HTTP service sidecars (body + resolved URL), §Shared Services (heading + body), §Summary diagram edge reconciled to host-gateway + HARNESSED_NET opt-in.
- `services/ping/server.py` - module docstring converged to its own accurate `host.containers.internal` body.
- `tools/harnessed/schema.py` - `ServiceDef` docstring mirrors B1+B4.
- `CLAUDE.md` - Engine bullet states pasta-by-default + host-gateway + opt-in.
- `stacks/ping-time/stack.yaml` - sidecar comment states host-gateway proxy (HARNESSED_NET opt-in).
- `harnessed` - `svc up` help string + section comment state host-published framing.

## Decisions Made
- Followed the plan's CONTEXT decisions D-01..D-07 and the `<action>` wording exactly; authored no new networking prose (mirrored shipped B1/B4/design-§9 verbatim).
- Chose `git stash`/pop over 06-01's `git update-index --cacheinfo` for commit hygiene (see Deviations) — same hygiene outcome (mine-only commits, user's WIP preserved), cleaner for a multi-file multi-task flow, and leaves the working tree correct (WIP layered on committed corrections).
- See Deviations for the working-tree-WIP handling and the residual generated-docs finding.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Blocker] Working-tree contamination: pre-existing uncommitted multi-harness WIP in 4 of the 6 in-scope files**
- **Found during:** Pre-execution git-state check (before Task 1).
- **Issue:** The working tree carried substantial UNCOMMITTED multi-harness feature work (opencode/gemini/antigravity/codex harness additions, new profiles/recipes/stacks/Dockerfiles, lib/harnessed-runtime.sh, etc.) in 4 of the 6 in-scope files (`docs/codebase/INTEGRATIONS.md`, `tools/harnessed/schema.py`, `CLAUDE.md`, `harnessed`). A plain `git add <file> && git commit` would have swept that unrelated WIP into the "atomic" 06-03 commits — the same contamination 06-01 hit (06-01 Deviation 1).
- **Fix:** `git stash push -m "phase06-03-wip-preserve" -- <the 4 dirty paths>` to set those files to HEAD, then edit all 6 files on the clean base, `git add` (mine-only) + commit per task, then `git stash pop` to restore the WIP layered onto the committed corrections. The pop 3-way-merged all 4 files cleanly because the plan's comment-only edits and the WIP's multi-harness additions occupy disjoint regions (separated by 5–60+ unchanged lines).
- **Files modified:** docs/codebase/INTEGRATIONS.md, tools/harnessed/schema.py, CLAUDE.md, harnessed (staging method only; final committed content = HEAD + my edits only).
- **Verification:** post-pop `git status` shows the 4 files modified (the WIP delta) and all 8 stale phrases I fixed are GONE from the working tree (python check) — the WIP did not re-add them. Committed HEAD for all 6 files = HEAD + my edits only.
- **Committed in:** f39790b / 4f925e7 (both task commits are mine-only; WIP excluded).

**2. [Rule 4 - Scope] Residual stale `harnessed-net` refs in 3 generated `docs/codebase/*` map-codebase snapshots — NOT corrected (out of scope)**
- **Found during:** Post-execution SC-1 repo-wide grep (Closeout).
- **Issue:** A repo-wide `git grep 'harnessed-net'` (excluding `.planning/`/`.claude/`) still returns 4 stale assertions in 3 *generated* codebase-mapping artifacts not flagged by `06-VERIFICATION.md`'s SC-1 audit and not in this plan's `files_modified`: `docs/codebase/ARCHITECTURE.md:314` ("on `harnessed-net` (or, rootless, reached via host gateway)"), `docs/codebase/CONVENTIONS.md:599` ("on `harnessed-net`, with a lifecycle"), `docs/codebase/STRUCTURE.md:173` ("global by name on `harnessed-net`") and `:248` ("starts the container on `harnessed-net`"). These are outputs of the `map-codebase` skill (dated 2026-06-17), i.e. regenerable snapshots, not authoritative hand-authored docs.
- **Fix:** Did NOT hand-edit them. Rationale: (a) Rule 4 — correcting files outside `files_modified` is a scope change requiring user approval; (b) hand-editing generated artifacts is an anti-pattern (they should be regenerated via `map-codebase` once the authoritative surface is reconciled); (c) `06-VERIFICATION.md`'s SC-1 audit — the scope authority — did not flag them (it scoped SC-1 to authoritative docs/code/manifests/CLI and treated `docs/codebase/*` as a regenerable stratum). The 6 authoritative files in this plan ARE fully corrected.
- **Files modified:** none (intentional non-action).
- **Verification:** flagged here + in STATE.md for the user/verifier to adjudicate. If a future verifier re-scopes SC-1 to include generated docs, regenerate `docs/codebase/*` rather than hand-patch.
- **Committed in:** n/a (finding only).

---

**Total deviations:** 2 (1 blocker WIP-contamination-remediation via stash/pop, 1 scope finding deferred to user).
**Impact on plan:** Deviation 1 was necessary for commit atomicity and produced a strictly better outcome than 06-01's cacheinfo approach (working tree left correct). Deviation 2 is a documented non-action respecting plan scope. No scope creep — final committed content matches the plan's intent exactly.

## Issues Encountered
- **Working-tree contamination** (Deviation 1): pre-existing uncommitted multi-harness WIP in 4 of the 6 in-scope files. Resolved via stash/pop; the user's WIP is preserved uncommitted in the working tree, layered onto the committed corrections. Flagged so the multi-harness work can be tracked/committed separately by its owner.
- **Residual generated-doc refs** (Deviation 2): 4 stale `harnessed-net` assertions in 3 `docs/codebase/*` map-codebase snapshots. Documented as a finding; not hand-edited (regenerable artifacts).

## Verification

Plan-level integration gate (D-11/D-12) — static checks load-bearing for this comment/doc-only plan (zero runtime risk per D-12). Run against committed HEAD:

- `bash -n` on committed `harnessed` (`git show HEAD:harnessed | bash -n`) — **PASS** (the `svc up` help-string + service-lifecycle comment edits did not break shell parsing).
- `python3 ast.parse` on committed `services/ping/server.py` + `tools/harnessed/schema.py` — **PASS** (the docstring edits did not break Python parse).
- `yaml.safe_load` on committed `stacks/ping-time/stack.yaml` — **PASS** (`{'name': 'ping-time', ...}`; the comment edit did not break YAML; keys/values unchanged).
- **SC-1 repo-wide grep** (committed HEAD, excluding `.planning/`/`.claude/`): the 6 in-scope files now carry ZERO literal `harnessed-net` refs (only the `HARNESSED_NET` underscore opt-in framing remains). The surviving `harnessed-net` refs are all LIVE/opt-in/now-accurate: `design.md:267` (opt-in context), `lib/harnessed-isolated.sh:77` (`:-harnessed-net` default, D-03), `lib/harnessed-services.sh:27/29` (`ensure_named_net harnessed-net`, D-03), `tools/harnessed/assemble.py:66` (D-07 replacement-doc), `docs/codebase/CONCERNS.md:32` (historical pivot context). **Exception:** 4 residual refs in 3 generated `docs/codebase/*` snapshots — see Deviation 2.
- **Old-URL-is-opt-in-only** (G1/G2/G3 retain the old DNS-name URL only as the labeled `HARNESSED_NET` opt-in, mirroring B4): `http://ping:8080/mcp` survives at `INTEGRATIONS.md:106` and `server.py:8` ONLY with the `HARNESSED_NET` qualifier; `http://<name>:<port>/mcp` survives at `schema.py:133` ONLY as the labeled opt-in form. 0 orphan old-URL lines.
- **D-06 integrity:** both `[INFERENCE]` markers intact in `docs/harnessed-design.md` (working-tree :450, :490 — line-shifted by the user's multi-harness WIP, markers untouched).
- **D-07 integrity:** the 4 replacement-documenting comments untouched by 06-03 (`tools/harnessed/assemble.py`, `lib/harnessed-services.sh`, `lib/harnessed-isolated.sh`, `docs/guides/service-authoring.md` — `git diff HEAD~2 HEAD` empty for each).
- **D-12 integrity:** 06-03 changed exactly 6 files (26 insertions, 15 deletions); all edits are comment/docstring/doc/help-string/prose. No executable Python, no dataclass field/type, no bash control flow/dispatch/function, no YAML key/value changed.

**DEFERRED (per D-11/D-12):** `harnessed test ping-time`, `harnessed test tracer-time`, and `bash tools/uat/run-uat.sh`. Rootless `podman.socket` is inactive on the verification host, AND the working tree carries the uncommitted multi-harness WIP in files under test — so a live run would exercise the user's WIP, not isolate this plan's comment-only edits. Per D-12 (doc/comment edits are zero-runtime-risk; only the live capability/UAT legs defer), these legs defer to `/gsd-verify-work` once the tree is committable and rootless podman is available.

## Self-Check: PASSED
- All 6 in-scope files corrected (G1–G6: INTEGRATIONS.md ×5, server.py docstring, schema.py ServiceDef docstring, CLAUDE.md Engine bullet, stack.yaml comment, harnessed help + section comment); `[INFERENCE]` markers (D-06) and the 4 replacement-docs (D-07) untouched; opt-in code preserved (D-03); `bash -n` + `ast.parse` + `yaml.safe_load` green on committed blobs; both task commits + this SUMMARY are atomic and contain only 06-03 edits (pre-existing multi-harness WIP excluded via stash/pop).

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Plan 06-03 complete (SC-1 closed at the repo-wide level for the authoritative docs/code/manifests/CLI surface).
- **Open item for the user (Deviation 2):** 4 residual stale `harnessed-net` refs in 3 generated `docs/codebase/*` snapshots (ARCHITECTURE.md, CONVENTIONS.md, STRUCTURE.md). Regenerate via `map-codebase` (preferred) or hand-patch if a future verifier re-scopes SC-1 to include generated docs.
- **Open item for the user:** the pre-existing uncommitted multi-harness (opencode/gemini/antigravity/codex) work remains in the working tree, layered onto the committed 06-03 corrections — to be committed/tracked separately by its owner.
- With 06-01/06-02/06-03 all complete, the orchestrator can now run phase-06 verification (gsd-verifier) and, on `passed`, mark the phase + milestone complete.

---
*Phase: 06-tech-debt-cleanup*
*Completed: 2026-06-21*
