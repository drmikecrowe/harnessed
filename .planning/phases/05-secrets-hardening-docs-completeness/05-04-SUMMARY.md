---
phase: 05-secrets-hardening-docs-completeness
plan: 04
subsystem: docs
tags: [readme, documentation, guides, recipes, stacks, services, troubleshooting, mcp, supply-chain, systemd]

# Dependency graph
requires:
  - phase: 05-secrets-hardening-docs-completeness
    provides: 05-01 (harnessed-tools image + token-gated snyk/socket invokers), 05-02 (opt-in secrets resolution + `harnessed auth snyk|socket` + docs/guides/secrets.md), 05-03 (online image re-scan + `harnessed rescan` + nightly systemd timer + loginctl enable-linger prerequisite) — every feature this plan documents is shipped and verified before its doc lands (design §17 cadence rule).
provides:
  - README.md (repo-root entry point) — what harnessed is, the two modes (transparent/isolated), podman-only install, first-run build + image lineage, copy-paste quickstart (transparent + isolated), the full command surface (incl. auth snyk|socket + rescan), supply-chain/security summary, guides index, container back-compat note
  - AGENTS.md (reconciled) — AI-assistant instructions that redirect to README for the harnessed surface; preserves the "do not run harnessed/container interactively" guard + Permissions.md ref (eliminates drift with README)
  - docs/guides/recipe-authoring.md — recipe.yaml schema (McpServer/FileExt), recipes/time + recipes/ping worked examples, stdio vs streamable-http transports (SSE deprecated), pnpm/uvx supply-chain rules
  - docs/guides/stacks.md — stack.yaml schema (Stack model), tracer-time + transparent + ping-time worked examples, harnessed new scaffolding, build/run/test lifecycle
  - docs/guides/service-authoring.md — service triple (service.yaml + Dockerfile + server.py), services/ping worked example, Streamable-HTTP transport, svc lifecycle + recipe attachment
  - docs/guides/troubleshooting.md — podman/rootless clarification, first-run build, ~/.claude.json onboarding, --fresh, host-persisted sessions, the SEC-04 nightly timer (loginctl enable-linger + install + diagnostics + online-vs-offline), secrets + scan-failure cross-refs
affects: []   # FINAL plan of phase 05 (and the milestone); no downstream plans

# Tech tracking
tech-stack:
  added: []  # documentation-only plan — no code/packages
  patterns:
    - "HOW-vs-WHY split: README + docs/guides/* are the HOW (worked examples, commands); docs/harnessed-design.md §1–§18 is the WHY (cross-referenced, never duplicated)"
    - "Verified worked-example contract: every guide cites a real repo file (recipes/time, recipes/ping, stacks/tracer-time, stacks/transparent, stacks/ping-time, services/ping/*) traced to source before writing"
    - "README↔AGENTS reconciliation (RESEARCH Pattern 5 anti-pattern avoided): AGENTS.md redirects to README for the surface, preserving only agent-critical guidance (don't run interactively, Permissions.md)"

key-files:
  created: [docs/guides/recipe-authoring.md, docs/guides/stacks.md, docs/guides/service-authoring.md, docs/guides/troubleshooting.md]
  modified: [README.md, AGENTS.md]

key-decisions:
  - "README is a REWRITE of the container-era README (not a brand-new file): the repo already had a container-era README with an accurate 'Where This Is Headed: harnessed' section. The rewrite makes harnessed the primary subject (what/why, two modes, install, first-run build, quickstart, command surface, guides) while preserving genuine repo content (banner, announcement, the 'which solution' comparison table, the container back-compat alias)."
  - "AGENTS.md took option (a) from the plan: redirect to README for the harnessed surface, but keep AI-assistant-specific guidance (the 'do not run harnessed/container interactively' guard, the Permissions.md ref, the conventions pointer). A one-line-only stub would have discarded the load-bearing 'don't launch an interactive shell' instruction that agents need."
  - "recipe-authoring uses recipes/time + recipes/ping (per plan) — the two real MCP shapes (stdio child vs http service-ref). It does NOT lead with greet (skill-only) since the plan specifies time+ping; greet is mentioned in the stacks guide as the multi-recipe example."
  - "troubleshooting carries BOTH 05-03 prerequisites verbatim: the loginctl enable-linger HARD prerequisite (Pitfall 5) AND the online-vs-offline scan distinction (Pitfall 6, scan-image-online vs scan-image) with the '(online)' marker as the diagnostic tell. It also carries the 05-03 operational note (rebuild harnessed-tools after a tools/harnessed/*.py upgrade — ensure_tools_image is build-if-missing, not staleness-aware)."
  - "All in-doc commands traced to the real launcher/lib surface: quickstart uses `harnessed build tracer-time && harnessed tracer-time` (verified: the isolated launcher errors on an unbuilt profile, so build-then-run is the correct/required flow, not `harnessed <stack>` auto-build)."

patterns-established:
  - "Guide structure: What it is → schema (cite tools/harnessed/schema.py) → worked examples from real repo files → cross-reference docs/harnessed-design.md §N for the WHY → See also. Every guide follows this shape (matches docs/guides/secrets.md from 05-02)."
  - "Cross-reference discipline: relative links from docs/guides/* to ../harnessed-design.md and sibling guides; README links to docs/guides/* and docs/harnessed-design.md; AGENTS.md links to README. No absolute paths, no duplication of design rationale."

requirements-completed: [DOC-01, DOC-02, DOC-03]

# Metrics
duration: 33min
completed: 2026-06-18
---

# Phase 5 Plan 04: README + How-to Guides (Docs Completeness) Summary

**Repo-root README (two modes, podman-only install, copy-paste quickstart, full command surface incl. auth/rescan) + reconciled AGENTS.md + four verified how-to guides (recipe-authoring, stacks, service-authoring, troubleshooting) — each citing a real repo worked example and cross-referencing the design doc for the WHY.**

## Performance

- **Duration:** ~33 min
- **Tasks:** 3 (all `type="auto"`; autonomous plan, NO checkpoint)
- **Files modified:** 6 (4 created, 2 modified)

## Accomplishments
- README.md is now the harnessed entry point: what it is, the transparent/isolated modes table, podman-only install (the `install.sh` one-liner), first-run build + image lineage (base→claude/omp, hatago, harnessed-tools), a copy-paste quickstart (transparent + isolated), the full command surface (incl. the Phase 5 `auth snyk|socket` and `rescan`), a supply-chain/security summary, a guides index, and the `container` back-compat alias.
- AGENTS.md is reconciled with README (no drift): it redirects AI assistants to README for the harnessed surface while preserving the load-bearing "do not run `harnessed`/`container` interactively" guard and the Permissions.md reference. The container-era `container --build` quickstart is gone.
- Four how-to guides ship under `docs/guides/`, each with a verified worked example from the repo and a design-doc cross-reference: recipe-authoring (recipes/time + recipes/ping), stacks (tracer-time + transparent + ping-time), service-authoring (services/ping triple), troubleshooting (the full ops surface incl. the SEC-04 timer prerequisites).

## Task Commits

Each task was committed atomically (explicit `--files` pathspecs only — dirty-tree guard honored; the ~49 pre-existing `.agents/skills/*` deletions + untracked dirs were never swept in):

1. **Task 1: README.md + reconcile AGENTS.md (DOC-01)** — `108132d` (docs)
2. **Task 2: recipe-authoring + stacks guides (DOC-02)** — `95865b7` (docs)
3. **Task 3: service-authoring + troubleshooting guides (DOC-03)** — `a8f22a5` (docs)

## Files Created/Modified
- `README.md` (REWRITE) — harnessed entry point: what/why, two modes, install, first-run build, quickstart, command surface, guides, supply-chain/security, container alias; preserves banner + announcement + comparison table.
- `AGENTS.md` (REWRITE) — reconciled AI-assistant instructions redirecting to README; preserves the don't-run-interactively guard + Permissions.md ref.
- `docs/guides/recipe-authoring.md` (NEW) — recipe.yaml schema (McpServer/FileExt), recipes/time (stdio) + recipes/ping (service-ref) worked examples, stdio/streamable-http transports (SSE deprecated), pnpm/uvx rules.
- `docs/guides/stacks.md` (NEW) — stack.yaml schema (Stack model), tracer-time + transparent + ping-time worked examples, `harnessed new` scaffolding, build/run/test lifecycle.
- `docs/guides/service-authoring.md` (NEW) — service triple (service.yaml + Dockerfile + server.py), services/ping worked example, Streamable-HTTP transport, svc lifecycle + recipe attachment + rootless networking note.
- `docs/guides/troubleshooting.md` (NEW) — podman/rootless clarification, first-run build (+ rebuild-tools-after-upgrade note), ~/.claude.json onboarding, --fresh, host-persisted sessions (state-dir path), SEC-04 nightly timer (linger + install + diagnostics + online-vs-offline), secrets + scan-failure cross-refs.

## Decisions Made
- **README rewrite, not a new file.** The repo already had a container-era README; the plan said "NEW at repo root" but a fresh file would have discarded genuine content (banner, announcement, the comparison table, the container alias). The rewrite makes harnessed the subject and folds in the real content — same goal, less loss.
- **AGENTS.md = option (a) + preserved guard.** The plan's recommendation was option (a) (fold into README, leave AGENTS as a stub redirect). Implemented as a focused redirect that ALSO keeps the agent-critical "don't launch an interactive shell" instruction + Permissions.md — a pure one-line stub would have removed guidance agents actually need.
- **Worked examples verified against source.** Every command/path in every guide was traced to a real file before writing: the isolated launcher requires a pre-built profile (so `build && run` is correct, not auto-build); `services/ping/server.py`'s `allowed_hosts` + `/health` route are documented as-shipped; the `scan-image-online` vs `scan-image` markers match scan.py/cli.py.

## Deviations from Plan

None — plan executed exactly as written (documentation-only, no code). The one judgment call (README as a rewrite of the existing file rather than a brand-new file) honors the plan's intent ("NEW at repo root" = the README must exist and be the entry point) while preserving genuine repo content; it is noted under Decisions, not a deviation.

## Verification (per plan `<verification>` checklist — all PASS)

Structural + content checks (the plan's `<verify><automated>` greps, run via the `search` tool — bash `grep` is blocked in this harness):

- **README.md** ✓ — `harnessed`, `transparent`, `isolated`, `podman`, `quickstart`, `harnessed build`, `docs/guides/`, `docs/harnessed-design.md` all present.
- **AGENTS.md** ✓ — reconciled (points at `README.md`, describes `harnessed`, no `container --build` container-era quickstart).
- **recipe-authoring.md** ✓ — `recipe.yaml`, `recipes/time`, `recipes/ping`, `streamable`, `pnpm`, `docs/harnessed-design.md`.
- **stacks.md** ✓ — `stack.yaml`, `tracer-time`, `transparent`, `ping-time`, `harnessed new`, `docs/harnessed-design.md`.
- **service-authoring.md** ✓ — `services/ping`, `service.yaml`, `Dockerfile`, `server.py`, `streamable`, `svc up`.
- **troubleshooting.md** ✓ — `enable-linger`, `loginctl`, `list-timers`, `journalctl`, `--fresh`, `claude.json`, `scan-image-online` (online-vs-offline), `secrets.md` cross-ref.

Worked-example existence (every cited file confirmed on disk via `find`): `recipes/time/recipe.yaml`, `recipes/ping/recipe.yaml`, `stacks/tracer-time/stack.yaml`, `stacks/transparent/stack.yaml`, `stacks/ping-time/stack.yaml`, `services/ping/{service.yaml,Dockerfile,server.py}`, `docs/harnessed-design.md`, `docs/guides/secrets.md` — all present.

Cross-references resolve: every guide links `../harnessed-design.md` (the file exists; section numbers cited as §N match the design doc's `## N.` headings); `secrets.md` is cross-referenced from README (guides index + supply-chain section) and troubleshooting (the secrets/ops sections) — the SEC-01/SEC-04 doc surface is complete. No real tokens/secrets in any example (placeholder `op(op://Private/Snyk/credential)` + dummy values only).

## Issues Encountered
None. Documentation-only plan; no code, no build, no auth gates.

## User Setup Required
None — documentation-only. (Operator-only setup from prior plans — 1Password vault items for SEC-01, scanner-token auth for SEC-03, the timer + `loginctl enable-linger` for SEC-04 — is already documented in `docs/guides/secrets.md` and `docs/guides/troubleshooting.md`.)

## Next Phase Readiness
- **Phase 05 is COMPLETE** — all four plans (05-01/02/03/04) shipped. This was the final wave (Wave 4).
- DOC-01, DOC-02, DOC-03 are satisfied; the v1 documentation surface (README + design doc + 5 guides) is complete per design §17.
- No blockers. The dirty-tree guard was honored throughout (explicit `--files` pathspecs only).

## Self-Check: PASSED

All three tasks' `<acceptance_criteria>` re-verified PASS (structural + content + worked-example-existence checks green). Plan-level `<verification>` checklist all true. `git log --oneline | grep 05-04` returns 3 production commits (`108132d`, `95865b7`, `a8f22a5`) + this summary/state/roadmap/requirements commit.

---
*Phase: 05-secrets-hardening-docs-completeness*
*Plan: 04*
*Completed: 2026-06-18*
