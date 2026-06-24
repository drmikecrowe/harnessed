---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Phases
status: ready_to_plan
last_updated: 2026-06-24T15:29:42.725Z
last_activity: 2026-06-24 -- Phase 09 execution started
progress:
  total_phases: 11
  completed_phases: 2
  total_plans: 10
  completed_plans: 10
  percent: 18
stopped_at: Phase 09 complete (4/4) — ready to discuss Phase 10
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-14)

**Core value:** Compose a named stack and launch an isolated, authenticated instance that exposes exactly the skills/commands/MCP/services it declares — nothing from host config — reproducibly, podman the only host dependency.
**Current focus:** Phase 10 — opencode/codex investigation + combined capability test

## Current Position

Phase: 10
Plan: Not started
Phase: 08 — not yet started
Last activity: 2026-06-24

## Performance Metrics

**Velocity:**

- Total plans completed: 14
- Average duration: — min
- Total execution time: 0.0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 2 | 3 | - | - |
| 03 | 2 | - | - |
| 06 | 3 | - | - |
| 09 | 4 | - | - |

**Recent Trend:**

- Last 5 plans: —
- Trend: —

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table. Recent decisions affecting current work:

- Init: One engine, two config modes (transparent/isolated); same base image/mounts/auth, differ only on config source
- Init: Compose stacks at runtime in a podman pod (FROM can't union sibling systems)
- Init: Single containerized Python tool image; host bash is a thin bootstrap (podman the only host dep)
- 05-02: resolve_secret_env is opt-in via a single `[ -f $HARNESSED_SCHEMA ]` test (no schema → varlock NEVER invoked, no behavior change); throwaway tools container with -e HOME=$CONTAINER_HOME so op resolves the mounted agent socket; resolved env reaches pod/build via mode-0600 --env-file (unlinked after launch). Quote-stripping sed needed because podman --env-file treats varlock's `KEY="value"` literally
- 05-02: auth_scanner drives snyk auth / socket login in a --rm -it tools container with -e HOME=$CONTAINER_HOME + ~/.config rw-mounted → token persists to host config (e.g. ~/.config/configstore/snyk.json), never an image layer (T-05-07)
- 05-02: mise shims break under the non-native HOME ($CONTAINER_HOME=/home/harnessed vs the tools image's native /home/tools); fixed by prepending /home/tools/.local/share/mise/installs/node/latest/bin to PATH inside the throwaway resolve/auth containers so the pnpm-global CLIs (varlock/snyk/socket) find node directly
- 05-02: SEC-01 + SEC-03 marked complete (code + INERTNESS + structure verified; live op resolution + interactive snyk auth = operator-confirmed — needs 1Password desktop app + browser flow)
- 05-03: run_image_scan_online is run_image_scan MINUS the --offline/--offline-vulnerabilities flags (the build-time gate stays offline-deterministic; the nightly is online-fresh — Pitfall 6). Keeps exit-128 investigate-branch + gate() HIGH check + ScanError. scan-image-online CLI subcommand exposes it
- 05-03: harnessed rescan iterates podman images --filter reference='harnessed-*', podman save each, scan-image-online per image in a throwaway tools container; safe exit capture (`|| img_rc=$?`) so a finding on one image sets rc=1 but does NOT abort scanning the rest (each image independent). Process-substitution loop so rc mutations escape the body
- 05-03: systemd USER units (rootless; not system units) — timer OnCalendar=daily + Persistent=true, service Type=oneshot ExecStart=%h/.local/bin/harnessed rescan. loginctl enable-linger $USER is a HARD prerequisite (Pitfall 5; Linger=no on host) — documented in unit comments + carried to 05-04 troubleshooting
- 05-03: SEC-04 marked complete (all 6 checkpoint steps verified real: rescan exit 0 on 6 images online; online-vs-offline contrast proves online sees Debian ecosystem the offline DB lacks; timer scheduled; service journal shows full path; build-time offline scan unchanged). Operational note: rebuild harnessed-tools after a tools/harnessed/*.py upgrade (ensure_tools_image is build-if-missing, not staleness-aware)

### Pending Todos

- Persist agy auth via in-pod keyring (`.planning/todos/pending/2026-06-21-persist-agy-auth-via-in-pod-keyring.md`) — antigravity OAuth persistence (Option 2; host-keyring mount rejected)

### Blockers/Concerns

- Phase 1: Verify `CLAUDE_CONFIG_DIR` relocates `.claude.json` (top-level file) vs only `.claude/` — choose copy-on-start otherwise (research flag)
- Phase 2: RESOLVED — the `.claude.json` stub field set (hasCompletedOnboarding, firstStartTime, numStartups, oauthAccount, userID) is proven sufficient for a headless no-prompt boot (gate 2: `claude -p` returned success with no prompt). Pin as a snapshot fixture in a later phase.
- Phase 6 (SC-1 gap): verification found stale bridge-as-default `harnessed-net` assertions in files plan 06-01 did NOT cover (its `files_modified` listed 6; 06-RESEARCH Item B grep wasn't truly repo-wide). Confirmed against HEAD: `services/ping/server.py:6-7` (docstring contradicts its own :19-25 impl), `tools/harnessed/schema.py:128-131` (ServiceDef docstring — same B1+B4 pattern fixed in 3 peer files but left here), `CLAUDE.md:153` ("pod on harnessed-net" vs pasta default), plus `docs/codebase/INTEGRATIONS.md` (:100,:103,:112-113,:270). Root cause = planning under-inclusion, NOT executor error. Close via `/gsd-plan-phase 6 --gaps` → gap_closure plans → `/gsd-execute-phase 6 --gaps-only`.

## Deferred Items

Items acknowledged and carried forward from previous milestone close:

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| *(none)* | | | |

## Session Continuity

Last session: 2026-06-24T11:53:03.969Z
Stopped at: Phase 09 context gathered
Resume file: .planning/phases/09-surgical-profile-mount-history-surfacing/09-CONTEXT.md
