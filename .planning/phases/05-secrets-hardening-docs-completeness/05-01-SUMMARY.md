---
phase: 05-secrets-hardening-docs-completeness
plan: 01
subsystem: infra
tags: [podman, supply-chain, pnpm, mise, node, snyk, socket, varlock, 1password, scanners]

# Dependency graph
requires:
  - phase: 03-supply-chain-gate-pnpm-everywhere
    provides: osv-scanner + pip-audit credential-free scan gate in tools/harnessed/scan.py (the _run/_scan_source_osv/_audit_pip invoker pattern this plan mirrors); lib/pnpm/config.yaml supply-chain policy
provides:
  - harnessed-tools image now carries Node@24 + pnpm@11 (mise) + varlock@1.7.1 + @varlock/1password-plugin@1.2.0 + op (1password-cli 2.34.1) + snyk@1.1305.1 + socket@1.1.122 — all INERT unless a schema/tokens exist at runtime
  - tools/pnpm-workspace.yaml — project-scoped pnpm v11 allowBuilds:{snyk:true}
  - tools/harnessed/scan.py _scan_snyk/_scan_socket env-gated invokers wired into run_source_scan
  - lib/harnessed-common.sh build_stack forwards SNYK_TOKEN/SOCKET_SECURITY_API_KEY to the scan step via a conditional TOKEN_ARGS array
  - .env.schema.example plugin pin bumped @0.3.2 → @1.2.0 (parses under varlock 1.7.1)
affects: [05-02 opt-in secrets + auth, 05-03 nightly re-scan, 05-04 docs]

# Tech tracking
tech-stack:
  added: [varlock@1.7.1, "@varlock/1password-plugin@1.2.0", "op/1password-cli@2.34.1", snyk@1.1305.1, socket@1.1.122, "mise-managed node@24", "mise-managed pnpm@11", libatomic1]
  patterns: [env-presence-gated scanner invoker (warn-and-skip), snyk exit-code-as-gate vs osv-scanner Python-over-JSON, conditional TOKEN_ARGS array under set -euo pipefail, pnpm-workspace.yaml project-scoped allowBuilds, minimumReleaseAgeExclude scoped escape hatch]

key-files:
  created: [tools/pnpm-workspace.yaml]
  modified: [tools/Dockerfile, tools/harnessed/scan.py, lib/harnessed-common.sh, .env.schema.example]

key-decisions:
  - "snyk's platform binary is fetched LAZILY at first run (snyk --version), not via a postinstall build script — so pnpm 11 strictDepBuilds never blocked the install; allowBuilds:{snyk:true} is kept as a harmless defensive entry but was not load-bearing (T-05-01 resolved cleaner than PATTERNS anticipated)"
  - "socket@1.1.122 was published <24h before the bake (2026-06-17T15:18Z), tripping minimumReleaseAge=1440 — resolved with the documented Pitfall 2 escape hatch minimumReleaseAgeExclude:[socket@1.1.122] in the inlined global config (scoped to the exact audited [OK] pin, not a blanket bypass)"
  - "Token forwarding uses the set -euo pipefail-safe `[ -n \"${VAR:-}\" ] && TOKEN_ARGS+=()` idiom (verified safe); never prompts"
  - "CLIs are discoverable in BOTH login and non-login shells (Docker ENV PATH covers the scan-step ENTRYPOINT path; /etc/profile.d/harnessed-tools.sh covers login shells for 05-02 varlock resolution)"

patterns-established:
  - "Token-gated scanner invoker: env-presence gate → warn-and-skip string; scanner exit-code drives highs vs warnings (snyk exit 1=HIGH abort, 2/3=warn, 0=clean; socket always warnings-only)"
  - "Scanner tokens cross launcher→tools-image via a conditional TOKEN_ARGS array built in build_stack and spread into the scan-step podman run — values never logged"

requirements-completed: [SEC-02]   # SEC-01 is PARTIAL here — only the CLI foundation (varlock/op baked + schema parses); the detect-and-resolve launcher wiring is plan 05-02

# Metrics
duration: 27min
completed: 2026-06-18
---

# Phase 5 Plan 01: Scanner Image Bake + Token-Gated snyk/socket Summary

**Node@24/pnpm@11 layer baking varlock + the 1Password plugin + op + snyk + socket into the harnessed-tools image, plus env-gated snyk/socket invokers that warn-and-skip without a token and abort only on snyk HIGH+ (exit 1).**

## Performance

- **Duration:** ~27 min
- **Started:** 2026-06-18T11:32:16Z
- **Completed:** 2026-06-18T11:59:50Z
- **Tasks:** 3 (2 auto + 1 checkpoint, auto-approved under AUTO-MODE)
- **Files modified:** 5 (1 created, 4 modified)

## Accomplishments
- The harnessed-tools image now carries the full Phase 5 toolchain: mise-managed Node@24.16.0 + pnpm@11.7.0, varlock@1.7.1, @varlock/1password-plugin@1.2.0, op (1password-cli 2.34.1), snyk@1.1305.1, socket@1.1.122 — all version-pinned, policy-governed (minimumReleaseAge/strictDepBuilds), and INERT unless a `.env.schema`/tokens exist at runtime. This is the foundational image for plans 05-02/05-03/05-04.
- `harnessed build` runs snyk (`--severity-threshold=high --json`) and socket (`scan create --json`) inside the scan step when their tokens are in the launcher env, and **warns-and-skips** otherwise — keeping the build non-interactive (SEC-02). The snyk exit-code map (1=HIGH+ abort, 2/3=warn, 0=clean) is honored, NOT treated like osv-scanner's exit-1=any-finding.
- `build_stack` forwards `SNYK_TOKEN`/`SOCKET_SECURITY_API_KEY` to the scan step via a conditional `TOKEN_ARGS` array (set -euo pipefail safe); never prompts.
- The stale `.env.schema.example` plugin pin is bumped `@0.3.2` → `@1.2.0` and verified to parse under varlock 1.7.1.

## Task Commits

Each task was committed atomically (explicit `--files` pathspecs only — dirty-tree guard honored; the 49 pre-existing `.agents/skills/*` deletions were never swept in):

1. **Task 1: Bake Node + scanner CLIs + varlock/op + bump plugin pin** — `31067bb` (feat)
2. **Task 2: Token-gated snyk/socket invokers + build_stack env forwarding** — `c38ea29` (feat)
3. **Checkpoint build fixes (Rule 3 deviations, see below):**
   - `957dfb8` (fix) — libatomic1, pnpm global-bin PATH, socket release-age exclude
   - `e04a9da` (fix) — CLI PATH for login shells via /etc/profile.d

## Files Created/Modified
- `tools/pnpm-workspace.yaml` (NEW) — project-scoped pnpm v11 lifecycle allowlist `allowBuilds: {snyk: true}`; pnpm v11 reads it here, not from the global config.yaml.
- `tools/Dockerfile` — added the 1Password apt repo (`1password-cli`, not the desktop app) with GPG keyring + signed-by; a mise Node@24/pnpm@11 layer; the five pnpm policy keys inlined (build context is tools/, so lib/pnpm/config.yaml isn't COPY-able); `pnpm add -g varlock@1.7.1 @varlock/1password-plugin@1.2.0 snyk@1.1305.1 socket@1.1.122` with version pins + smoke tests; `libatomic1` (pnpm loader dep); PNPM_HOME + global-bin PATH; `/etc/profile.d` PATH for login shells; `minimumReleaseAgeExclude: [socket@1.1.122]`.
- `tools/harnessed/scan.py` — `_scan_snyk(target, highs, warnings)` (env-gated on SNYK_TOKEN; snyk exit-code map) + `_scan_socket(target, warnings)` (env-gated on SOCKET_SECURITY_API_KEY|TOKEN; warnings-only; warn-and-skip on network/quota); `_snyk_vuln_ids`/`_socket_alerts` helpers; `import os`; both called inside `run_source_scan`'s per-target loop.
- `lib/harnessed-common.sh` — `build_stack` builds a conditional `TOKEN_ARGS` array and spreads `"${TOKEN_ARGS[@]}"` into the scan-step `podman run`.
- `.env.schema.example` — plugin pin `@varlock/1password-plugin@0.3.2` → `@1.2.0` (line 11); rest unchanged.

## Decisions Made
- **snyk postinstall (T-05-01) resolved cleanly.** The plan/PATTERNS flagged snyk's postinstall (`wrapper_dist/bootstrap.js exec`) vs pnpm 11 `strictDepBuilds` as the highest-risk integration point. Empirically: snyk@1.1305.1 installed under `strictDepBuilds: true` with **no** build-script failure, and fetched its platform binary **lazily at first `snyk --version` invocation** (shasum-verified: actual == expected). So `strictDepBuilds` never blocked it; `allowBuilds: {snyk:true}` (kept defensively) was not load-bearing. The fallback (standalone installer / temp-project-dir) was NOT needed.
- **socket freshness escape hatch.** `socket@1.1.122` was published 2026-06-17T15:18Z — inside the 24h `minimumReleaseAge` cutoff at bake time. Resolved with the documented Pitfall 2 escape hatch `minimumReleaseAgeExclude: [socket@1.1.122]` in the inlined global config (the package is audited `[OK]` per RESEARCH; the exclude is scoped to the exact pinned version, not a blanket bypass).
- **Token-args idiom verified.** The `[ -n "${VAR:-}" ] && TOKEN_ARGS+=()` form was tested under `set -euo pipefail` (unset → 0 elements, set → appends) before use.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] mise pnpm binary needs libatomic.so.1**
- **Found during:** Task 3 checkpoint (image build)
- **Issue:** `pnpm add -g` failed: `pnpm: error while loading shared libraries: libatomic.so.1: cannot open shared object file`. `python:3.13-slim` lacks it (the base image gets it transitively via build-essential).
- **Fix:** Added `libatomic1` to the apt-get install line.
- **Files modified:** tools/Dockerfile
- **Verification:** Image builds; `snyk --version`/`socket --version`/`varlock --version` resolve.
- **Committed in:** 957dfb8

**2. [Rule 3 - Blocking] pnpm global-bin dir not on PATH**
- **Found during:** Task 3 checkpoint (image build)
- **Issue:** `pnpm add -g` refused: `[ERROR] The configured global bin directory "/home/tools/.local/share/pnpm/bin" is not in PATH`.
- **Fix:** Set `PNPM_HOME=/home/tools/.local/share/pnpm` and added `/home/tools/.local/share/pnpm/bin` (the actual global bin) to PATH.
- **Files modified:** tools/Dockerfile
- **Verification:** Global packages link; CLIs are on PATH.
- **Committed in:** 957dfb8

**3. [Rule 3 - Blocking] socket@1.1.122 blocked by minimumReleaseAge**
- **Found during:** Task 3 checkpoint (image build)
- **Issue:** `[ERR_PNPM_NO_MATURE_MATCHING_VERSION] socket@1.1.122 was published ... within the minimumReleaseAge cutoff` (published <24h before the bake).
- **Fix:** Added `minimumReleaseAgeExclude: [socket@1.1.122]` (the documented Pitfall 2 escape hatch) to the inlined global pnpm config — scoped to the exact audited pin.
- **Files modified:** tools/Dockerfile
- **Verification:** socket@1.1.122 installs; `socket --version` → 1.1.122.
- **Committed in:** 957dfb8

**4. [Rule 3 - Blocking] pnpm-global CLIs invisible to login shells**
- **Found during:** Task 3 checkpoint (step 2)
- **Issue:** `/etc/profile` rewrites PATH for login shells (`bash -lc`), dropping the Docker ENV PATH — so varlock/snyk/socket were `command not found` under `bash -lc` (the ENTRYPOINT/non-login path used by the scan step worked fine).
- **Fix:** Added `/etc/profile.d/harnessed-tools.sh` re-exporting PNPM_HOME + the pnpm-bin/mise-shims PATH. (Both entry modes now resolve the CLIs.)
- **Files modified:** tools/Dockerfile
- **Verification:** `bash -lc 'varlock/snyk/socket/op --version'` all print.
- **Committed in:** e04a9da

---

**Total deviations:** 4 auto-fixed (4 × Rule 3 blocking). **Impact on plan:** All are build/runtime-correctness fixes needed for the planned CLIs to actually install and be reachable; no scope creep. The snyk/strictDepBuilds fallback the plan anticipated was NOT needed (cleaner resolution).

## Issues Encountered
None beyond the four deviations above. The image build is deterministic (cached layers rebuild only on the changed layer).

## Checkpoint Verification (Task 3 — auto-approved under AUTO-MODE; all steps run for real)

Host: podman 5.8.3, libatomic/varlock/snyk/socket/op/pnpm/uv present. `python3 -m py_compile tools/harnessed/scan.py tools/harnessed/cli.py` → clean.

| Step | Command | Result |
|------|---------|--------|
| 1 | `podman build -t harnessed-tools:latest -f tools/Dockerfile tools/` | **VERIFIED** — builds cleanly (after the 4 deviations); snyk binary fetched + shasum-verified at smoke time. |
| 2 | `podman run --rm --entrypoint bash harnessed-tools:latest -lc 'varlock/snyk/socket/op --version'` | **VERIFIED** — varlock 1.7.1 · snyk 1.1305.1 · socket 1.1.122 · op 2.34.1. |
| 3 | `varlock load --format shell` on `.env.schema.example` (mounted ro) | **VERIFIED** — schema PARSES under `@1.2.0`: plugin + `@initOp` decorators recognized; only errors are the expected "cannot connect to 1Password app" (no agent socket mounted). Zero plugin/parse/decorator errors. varlock exits 1 on op-resolution (expected, no socket). |
| 4 | `env -u SNYK_TOKEN -u SOCKET_SECURITY_API_KEY ./harnessed build tracer-time` | **VERIFIED GREEN** — renders `warning: snyk skipped (no SNYK_TOKEN) …` + `warning: socket skipped (no SOCKET_SECURITY_API_KEY) …`; build succeeds. |
| 5 | `./harnessed build vuln-stack --root tools/test-fixtures` | **VERIFIED ABORT** — `supply-chain source scan found 1 HIGH+ finding(s) (CVSS >= 7.0): GHSA-x84v-xcm2-53pg`, exit 1. Baseline gate unchanged (regression clear). |
| 6 | `SNYK_TOKEN=dummy` → `_scan_snyk` in-image (no fixture has a package.json, so the CLI path was exercised directly) | **VERIFIED** — snyk IS invoked (token present); dummy-token auth failure = snyk exit 2 → mapped to a WARNING (not HIGH); `highs` empty so the build does NOT abort on a snyk auth failure. (Only exit 1 = HIGH+ would abort.) |

**Requirement status:** SEC-02 fully satisfied (warn-and-skip + token-present both exercised). SEC-01 is **PARTIAL** — only the CLI foundation (varlock/op baked, schema parses under 1.2.0); the launcher detect-and-resolve wiring (`resolve_secret_env` + `--env-file`) is plan 05-02. SEC-01 is therefore NOT marked complete.

## User Setup Required
None for this plan. (SEC-02 is opt-in via env tokens; SEC-01's `.env.schema` opt-in is 05-02.)

## Next Phase Readiness
- The foundational tools image is ready for 05-02 (opt-in varlock resolution — varlock/op present, schema parses; the login-shell PATH export preempts the `--entrypoint bash` varlock-resolve invocation), 05-03 (snyk/socket + osv online re-scan), and 05-04 (docs).
- No blockers. The snyk-under-pnpm and socket-freshness integration points (the two highest-risk items flagged in PATTERNS/RESEARCH) are resolved and verified.

## Self-Check: PASSED

All Task 1 + Task 2 `<acceptance_criteria>` re-verified PASS after the iterations; plan-level `<verification>` checklist all true; checkpoint steps 1-6 all VERIFIED; `git log --oneline | grep 05-01` returns 4 commits.

---
*Phase: 05-secrets-hardening-docs-completeness*
*Plan: 01*
*Completed: 2026-06-18*
