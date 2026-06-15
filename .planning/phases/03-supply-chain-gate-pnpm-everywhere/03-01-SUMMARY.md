---
phase: 03-supply-chain-gate-pnpm-everywhere
plan: 01
subsystem: infra
tags: [pnpm, supply-chain, dockerfile, mise, podman]

# Dependency graph
requires:
  - phase: 02-harnessed-assembler
    provides: harnessed base/hatago/tools images + the `harnessed build` path
provides:
  - lib/pnpm/config.yaml — single source of truth for the managed pnpm v11 policy
  - pnpm@11 pin + mise npm.package_manager=pnpm routing in harnessed-base + legacy
  - config COPY into harnessed-base + harnessed-hatago (the images that run pnpm)
affects: [03-02-scan-gate, harnessed-build, image-hardening]

# Tech tracking
tech-stack:
  added: []
  patterns:
  - "Managed supply-chain policy shipped from one auditable file (lib/) and COPY'd into each image's ~/.config/pnpm/config.yaml"
  - "pnpm@11 pinned (not @latest); mise npm: backend routed through pnpm before `mise use -g`"

key-files:
  created:
  - lib/pnpm/config.yaml
  modified:
  - base/Dockerfile.harnessed-base
  - base/Dockerfile.hatago
  - Dockerfile
  - docs/harnessed-design.md
  - CLAUDE.md

key-decisions:
  - "allowBuilds is project-scoped in pnpm v11 — it is rejected from the global config (warns + ignored). strictDepBuilds default-deny ships globally and IS honored; the curated allowlist is deferred to pnpm-workspace.yaml until a build-script package (esbuild) actually needs to run. Plan RESEARCH was wrong that allowBuilds works globally."
  - "tools image does NOT bake the pnpm config: its build context is tools/ (lib/ is outside it) and it has no JS installs. Bake the policy when node deps land."
  - "Legacy `container` image has a pre-existing mise.run build failure (line 50, before the phase-3 block) — out of the harnessed build path; flagged separately, not blocking."

patterns-established:
  - "Supply-chain config: one file in lib/, COPY'd to ~/.config/pnpm/config.yaml via root-COPY + mkdir + chown of the parent .config dir (so mise/pnpm can write ~/.config/*)"

requirements-completed: [BLD-01]

# Metrics
duration: ~45min
completed: 2026-06-15
---

# Phase 3 Plan 01: supply-chain config everywhere Summary

**Managed pnpm v11 policy (release-age quarantine + lifecycle default-deny + store integrity) shipped from one file and proven LIVE in the rebuilt harnessed-base + hatago images via `pnpm config list`; mise's npm: backend confirmed routing through pnpm.**

## Performance

- **Duration:** ~45 min (executor auto-tasks + checkpoint image rebuilds + revisions)
- **Tasks:** 2 auto + 1 human-verify checkpoint (approved via podman rebuild)
- **Files modified:** 6 (1 created + 5 modified)

## Accomplishments
- `lib/pnpm/config.yaml` — single source of truth; v11-valid keys only (no removed `onlyBuiltDependencies` family); `strictDepBuilds` default-deny live.
- `pnpm@11` pinned (was `@latest`) in harnessed-base + legacy; `mise settings set npm.package_manager pnpm` set BEFORE `mise use -g` so the global node tools (opencode-ai, codex, gemini-cli) honor the policy. Build log confirms: "Done in 11.7s using pnpm v11.6.0".
- Config COPY'd into harnessed-base + harnessed-hatago (the images that run pnpm). Rebuilt + introspected: `pnpm config list` shows `minimumReleaseAge=1440`, `minimumReleaseAgeStrict=true`, `blockExoticSubdeps=true`, `verifyStoreIntegrity=true`, `strictDepBuilds=true`, no warnings.
- design §7 corrected (`onlyBuiltDependencies` → `allowBuilds`, with the v11 project-scoping nuance); CLAUDE.md osv-scanner row corrected (no false `--min-severity` claim).

## Task Commits

1. **Task 1: managed pnpm config + base & legacy images** — `ba877f0` (feat)
2. **Task 2: hatago + tools images + design §7 + CLAUDE.md** — `9a8f9ee` (feat)
3. **Checkpoint revision: chown .config parent** — `c435bcc` (fix)
4. **Checkpoint revision: drop inert allowBuilds + defer tools** — `9ce32db` (fix)

## Files Created/Modified
- `lib/pnpm/config.yaml` — the managed pnpm v11 policy (BLD-01).
- `base/Dockerfile.harnessed-base` — pnpm@11, mise routing, config COPY (root-COPY + chown .config).
- `base/Dockerfile.hatago` — config COPY so the baked hub install honors policy.
- `Dockerfile` (legacy `container`) — identical pnpm@11 + routing + config COPY (consistency; image has a separate pre-existing build failure).
- `docs/harnessed-design.md` — §7 allowBuilds/v11-scoping correction; §14 open-question resolved.
- `CLAUDE.md` — osv-scanner row: HIGH threshold is a Python-over-JSON gate, not a native `--min-severity` flag.

## Decisions Made
- **allowBuilds deferred (v11 reality).** pnpm 11.6.0 rejects `allowBuilds` from the global config on every run. Removed it as an active key; `strictDepBuilds` (default-deny) is the live lifecycle control. The allowlist lands in a project's `pnpm-workspace.yaml` when a build-script package actually appears. This narrows BLD-01 truth #1 from "default-deny + allowlist" to "default-deny live; allowlist deferred per v11 project-scoping" — zero practical impact today (no installed package needs a build script).
- **tools config deferred.** tools is emit-only Python with no JS installs and its build context is `tools/`, so `lib/` is outside it. Removed the COPY; bake the policy when node deps land.
- **Legacy image out of scope.** Pre-existing `mise.run` failure (`/container/ubuntu` Permission denied) at Dockerfile line 50 — precedes the phase-3 block, untouched by it, and the legacy image isn't built by `harnessed-common.sh`. Flagged separately.

## Deviations from Plan

### Auto-fixed Issues

**1. chown scope too narrow — mise could not write ~/.config/mise**
- **Found during:** Task 3 checkpoint (harnessed-base podman build failed: "Permission denied (os error 13) creating ~/.config/mise").
- **Issue:** The config COPY block did `mkdir -p ~/.config/pnpm` as root (creating `~/.config` root-owned) then `chown -R` only the `pnpm` subdir, leaving `~/.config` unwritable by the image user.
- **Fix:** Widened the chown to the parent `.config` dir in all four Dockerfiles (mirrors the proven extra-tools.txt chown scope).
- **Files modified:** base/Dockerfile.harnessed-base, Dockerfile, base/Dockerfile.hatago, tools/Dockerfile.
- **Verification:** harnessed-base + hatago rebuilt clean; mise installs succeed.
- **Committed in:** `c435bcc`.

**2. allowBuilds inert in pnpm v11 global config**
- **Found during:** Task 3 checkpoint (pnpm warned "allowBuilds ... were ignored" on every invocation).
- **Issue:** Plan RESEARCH claimed `allowBuilds` works in the global config; pnpm 11.6.0 rejects it there (project-scoped only).
- **Fix:** Removed `allowBuilds` as an active key (kept `strictDepBuilds`); documented v11 project-scoping in the config, design §7, and §14.
- **Files modified:** lib/pnpm/config.yaml, docs/harnessed-design.md.
- **Verification:** rebuilt images show no allowBuilds warning; 5 controls still live in `pnpm config list`.
- **Committed in:** `9ce32db`.

**3. tools/Dockerfile COPY broke the tools build (context mismatch)**
- **Found during:** Task 3 checkpoint (tools build failed: `stat: "/pyproject.toml"`).
- **Issue:** tools build context is `tools/` (ensure_tools_image), so `COPY lib/pnpm/config.yaml` can't resolve.
- **Fix:** Removed the COPY + mkdir/chown from tools/Dockerfile (no JS in tools today).
- **Files modified:** tools/Dockerfile.
- **Verification:** harnessed-tools rebuilds clean (STEP 13→10); CLI works.
- **Committed in:** `9ce32db`.

**4. Second `onlyBuiltDependencies` occurrence in design §14**
- **Found during:** Task 2 verify (the plan's verify asserts zero non-comment `onlyBuiltDependencies` across the whole design file; a second occurrence lived in §14 line 421).
- **Issue:** Stale removed-v11 key name in a "verify during execution" bullet.
- **Fix:** Corrected §14 (and, after the allowBuilds finding, marked the bullet resolved).
- **Files modified:** docs/harnessed-design.md.
- **Verification:** plan Task 2 verify passes.
- **Committed in:** `9a8f9ee` (then refined in `9ce32db`).

---

**Total deviations:** 4 auto-fixed (3 found at checkpoint, 1 at Task-2 verify).
**Impact on plan:** All deviations necessary for correctness — the plan's RESEARCH was wrong about pnpm v11's allowBuilds placement and the tools build context. Two narrow BLD-01 truths (allowlist, tools coverage) are deferred with documented rationale; no scope creep.

## Issues Encountered
- Legacy `container` image fails to build at `mise.run` install (line 50) — pre-existing, unrelated to phase 3 (the phase-3 block is lines 53–62), and not in the harnessed build path. Not fixed here; the phase-3 Dockerfile edits are correct and will apply once the legacy mise issue is resolved separately.

## Self-Check: PASSED
- [x] `lib/pnpm/config.yaml` parses; v11-valid keys only; no removed-v11 keys.
- [x] harnessed-base + legacy: pnpm@11, `npm.package_manager pnpm` before `mise use -g`, config COPY'd.
- [x] hatago: config COPY'd; pinned `pnpm add -g` retained.
- [x] No image uses raw `npm install`/`npx`; `pnpm@latest` appears nowhere.
- [x] REBUILT + introspected: `pnpm config list` shows the 5 live controls, no warnings; `pnpm --version` = 11.6.0.
- [x] design §7 names `allowBuilds` + the v11 project-scoping nuance; CLAUDE.md osv-scanner row corrected.

## Next Phase Readiness
- The policy-governed install base is live for the harnessed images — plan 03-02 can build the scan gate + raw-npm lint on top of it.
- tools image rebuilds clean and is ready for 03-02's osv-scanner/pip-audit additions.

---
*Phase: 03-supply-chain-gate-pnpm-everywhere*
*Completed: 2026-06-15*
