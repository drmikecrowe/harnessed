---
phase: 05-secrets-hardening-docs-completeness
plan: 03
subsystem: infra
tags: [podman, supply-chain, osv-scanner, systemd, timer, nightly, cve, rootless, bash]

# Dependency graph
requires:
  - phase: 05-secrets-hardening-docs-completeness
    provides: 05-01 — the harnessed-tools image carrying osv-scanner (the run_image_scan invoker + gate()/ScanError the online variant clones); the build-time OFFLINE scan-image gate (BLD-02b) the nightly path parallels.
provides:
  - tools/harnessed/scan.py run_image_scan_online — run_image_scan MINUS the --offline / --offline-vulnerabilities flags (online osv.dev DB for post-build CVEs; keeps the exit-128 investigate-branch, the gate() HIGH check, ScanError)
  - tools/harnessed/cli.py scan-image-online subparser + _run_scan_image_online runner + main() dispatch
  - lib/harnessed-rescan.sh (NEW) — harnessed_rescan_images: iterates podman images --filter reference='harnessed-*', podman save each to a temp tar, scan-image-online in a throwaway tools container, safe per-image exit capture, temp-tar cleanup per iteration, returns non-zero if ANY image had a HIGH (without aborting the loop)
  - harnessed launcher rescan) dispatch (parse-before-fallthrough, SUB_RESCAN init) + dispatch-and-exit block + usage line + surface comment
  - systemd/harnessed-rescan.timer (NEW) — OnCalendar=daily, Persistent=true, WantedBy=timers.target, linger-prerequisite comment
  - systemd/harnessed-rescan.service (NEW) — Type=oneshot, ExecStart=%h/.local/bin/harnessed rescan
affects: [05-04 docs (troubleshooting carries the loginctl enable-linger prerequisite + the timer/service install steps)]

# Tech tracking
tech-stack:
  added: []  # no new packages — reuses the 05-01-baked osv-scanner + harnessed-tools image
  patterns:
    - online-vs-offline scan twin (run_image_scan_online is run_image_scan with the two build-time DB flags dropped — the build-time gate stays deterministic/offline; the nightly sees fresh advisories)
    - independent-image rescan loop with safe exit capture (`|| img_rc=$?` under set -euo pipefail; a finding on one image sets rc=1 but does NOT abort scanning the rest)
    - process-substitution image iteration (`while read < <(podman images --filter ...)`) — rc mutations escape the loop body (a pipe would run the body in a subshell)
    - static systemd USER units (rootless, scoped to the user's UID — no system unit, no root) + a thin `harnessed rescan` subcommand the timer's ExecStart calls

key-files:
  created: [lib/harnessed-rescan.sh, systemd/harnessed-rescan.timer, systemd/harnessed-rescan.service]
  modified: [tools/harnessed/scan.py, tools/harnessed/cli.py, harnessed]

key-decisions:
  - "run_image_scan_online is a deliberate near-clone of run_image_scan — the ONLY difference is the absence of --offline / --offline-vulnerabilities. Pitfall 6 (RESEARCH) is the whole point: the build-time gate MUST be offline (deterministic, reproducible), but the nightly MUST be online or it sees nothing new forever (the vacuous '0 findings' warning sign). Keeping the exit-128 investigate-branch in the online variant guards against the failure mode where a scan silently reports no packages."
  - "Each image is scanned INDEPENDENTLY — a HIGH finding on one sets the overall rc=1 but does NOT abort scanning the remaining images. This is the SEC-04 contract: a single newly-vulnerable image surfaces without blinding the operator to the rest of the fleet. The `|| img_rc=$?` safe capture under set -euo pipefail (Constraint 9 / a963a69) is load-bearing."
  - "The units are SYSTEMD USER units (~/.config/systemd/user/), NOT system units — rootless, scoped to the user's UID, consistent with rootless podman (T-05-14). `loginctl enable-linger $USER` is a HARD prerequisite (Pitfall 5; Linger=no on the host at execution time) documented in the timer comments + carried to 05-04 troubleshooting."
  - "ExecStart=%h/.local/bin/harnessed rescan assumes the operator has the launcher on PATH at that path (the launcher's symlink-resolution logic finds HARNESSED_DIR from a symlink there). The unit is a static template the operator copies into place — not auto-installed by harnessed."
  - "The docstring of run_image_scan_online deliberately avoids the literal token '--offline' so the plan's static verify (`'--offline' not in online_fn`) genuinely catches a forgotten flag in the invocation, rather than tripping on the docstring's prose. The rationale is still expressed in words ('drops the two build-time DB flags')."

patterns-established:
  - "Scan-twin pattern: an online and an offline variant of the same scanner invocation, sharing gate()/ScanError/exit-128-investigate but differing ONLY in the network/DB flags. The build path stays offline-deterministic; the nightly path is online-fresh. Never collapse them — the determinism/freshness tradeoff is the point."
  - "Top-level launcher subcommand + systemd user-unit ExecStart: the timer's ExecStart is a plain `harnessed <subcommand>` call, so the manual trigger (`harnessed rescan`) and the nightly trigger exercise the IDENTICAL code path. No separate timer-only entrypoint."
  - "Rescan-loop safe-exit idiom: `img_rc=0; <scan> || img_rc=$?; rm -f "$tar"; [ "$img_rc" -ne 0 ] && rc=1` — per-image exit captured without aborting the loop (set -euo pipefail safe); temp resource cleaned per iteration; overall rc tracks any failure."

requirements-completed: [SEC-04]

# Metrics
duration: 22min
completed: 2026-06-18
---

# Phase 5 Plan 03: Nightly Image Re-scan Timer Summary

**`run_image_scan_online` (online osv.dev DB) + `scan-image-online` CLI + `harnessed rescan` (iterates installed harnessed images, scans each online, a finding on one surfaces without aborting the rest) + static systemd user-timer units (OnCalendar=daily) — SEC-04 closes the time-of-check/time-of-use gap.**

## Performance

- **Duration:** ~22 min
- **Tasks:** 3 (2 auto + 1 checkpoint, auto-approved under AUTO-MODE)
- **Files modified:** 6 (3 created, 3 modified)

## Accomplishments
- The build-time OFFLINE scan gate (Phase 3 BLD-02b) now has a nightly ONLINE twin: `run_image_scan_online` (scan.py) drops the `--offline` / `--offline-vulnerabilities` flags so osv-scanner queries osv.dev for newly-disclosed CVEs — the whole point of SEC-04 (Pitfall 6: a stale-DB nightly would see nothing new forever). The exit-128 investigate-branch, the `gate()` CVSS>=HIGH check, and `ScanError` are all preserved.
- `harnessed rescan` iterates every installed harnessed-labelled image (`podman images --filter reference='harnessed-*'`), `podman save`s each to a temp tar, and runs `scan-image-online` in a throwaway tools container per image. A HIGH finding on one image surfaces (non-zero exit) WITHOUT aborting the scan of the remaining images — each is scanned independently.
- The static systemd USER units (`systemd/harnessed-rescan.{timer,service}`) are ready to copy to `~/.config/systemd/user/`. The timer (`OnCalendar=daily`, `Persistent=true`) drives `harnessed-rescan.service` (`Type=oneshot`, `ExecStart=%h/.local/bin/harnessed rescan`). `loginctl enable-linger $USER` is documented as a HARD prerequisite (Pitfall 5).
- The build-time offline gate is UNCHANGED (regression-verified both in code and behaviorally): `build_stack` still calls `scan-image` (offline); only the nightly path is online.

## Task Commits

Each task was committed atomically (explicit `--files` pathspecs only — dirty-tree guard honored; the ~49 pre-existing `.agents/skills/*` deletions were never swept in):

1. **Task 1: scan.py run_image_scan_online + cli.py scan-image-online subcommand** — `92b4c26` (feat)
2. **Task 2: lib/harnessed-rescan.sh + harnessed rescan dispatch + systemd units** — `ae3a2ab` (feat)

## Files Created/Modified
- `tools/harnessed/scan.py` — added `run_image_scan_online(archive_tar)`: `run_image_scan` with the two `--offline*` flags dropped from the `osv-scanner scan image` invocation. Same signature, docstring structure, return path, exit-128 investigate-branch, `gate()` HIGH check, `ScanError` raise — only the scanner flags differ.
- `tools/harnessed/cli.py` — extended the `.scan` import to include `run_image_scan_online`; added the `scan-image-online` subparser (one positional `archive`, mirrors `scan-image`); added `_run_scan_image_online` runner (mirrors `_run_scan_image`, prints the "(online)" marker); added the `main()` dispatch line.
- `lib/harnessed-rescan.sh` (NEW) — `harnessed_rescan_images()`: the per-image rescan loop (podman images --filter reference='harnessed-*' → save → scan-image-online → safe exit capture → tar cleanup → rc tracking).
- `harnessed` (launcher) — `rescan)` parse case (before the stack-name fallthrough, mirrors `list)`/`auth)` ordering); `SUB_RESCAN=false` init; dispatch-and-exit block (sources the rescan lib, calls `harnessed_rescan_images`, exits — under set -e a HIGH propagates as the launcher's exit code); usage line + top-of-file surface comment.
- `systemd/harnessed-rescan.timer` (NEW) — static user-unit template (`OnCalendar=daily`, `Persistent=true`, `WantedBy=timers.target`, linger-prerequisite comment).
- `systemd/harnessed-rescan.service` (NEW) — the oneshot service the timer activates (`Type=oneshot`, `ExecStart=%h/.local/bin/harnessed rescan`).

## Decisions Made
- **Online variant is a near-clone, not a refactor.** The plan called for `run_image_scan_online` to be `run_image_scan` minus the `--offline*` flags. A shared helper would have obscured the one load-bearing difference (the flags) and made the determinism/freshness contract less visible. The clone is intentional: the diff between the two functions IS the specification of SEC-04.
- **Docstring reworded to avoid the literal `--offline` token.** The plan's static verify (`'--offline' not in online_fn`) is over-broad (it scans the whole function body, not just the invocation). A docstring that named the dropped flags would trip it on prose. Reworded to "drops the two build-time DB flags" so the check now genuinely catches a forgotten flag in the `_run([...])` invocation.
- **Image iteration via process substitution, not a pipe.** `while read < <(podman images ...)` keeps the loop body in the current shell so `rc=1` mutations escape; a `podman images | while read` pipeline would run the body in a subshell and lose the rc.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Stale harnessed-tools image rejected scan-image-online**
- **Found during:** Task 3 checkpoint step 1 (first `./harnessed rescan` run)
- **Issue:** The installed `harnessed-tools:latest` was built during 05-01 and did NOT contain the new `scan-image-online` subcommand. `ensure_tools_image` only builds when MISSING, not when stale — so the rescan loop ran correctly (iterated all 6 images, saved each, captured exit safely per-image without aborting, cleaned up, returned rc=1) but every scan failed with `invalid choice: 'scan-image-online' (choose from assemble, test, scan, scan-image)`. The rescan machinery was correct; the image was stale.
- **Fix:** Rebuilt `harnessed-tools:latest` (`podman build -t harnessed-tools:latest -f tools/Dockerfile tools/`) so the image picks up the new scan.py + cli.py. snyk's platform binary re-fetched + shasum-verified at smoke time (expected). No Dockerfile change — the image just needed rebuilding against the updated Python source.
- **Files modified:** none (image rebuild only — no source change)
- **Verification:** After rebuild, `podman run --rm harnessed-tools:latest --help` lists `scan-image-online`; `./harnessed rescan` then ran all 6 images online and exited 0 (clean).
- **Committed in:** (no commit — image artifact, not source)

---

**Total deviations:** 1 auto-fixed (1 × Rule 3 blocking). **Impact on plan:** A build artifact freshness issue, not a code defect. The rescan loop, dispatch, and units were all correct as written; the image simply needed rebuilding to carry the new entrypoint. No scope creep. (Operational note for 05-04 troubleshooting: after a `harnessed` upgrade that touches tools/harnessed/*.py, the operator must rebuild harnessed-tools before the rescan picks up the change — `ensure_tools_image` is a build-if-missing guard, not a staleness guard.)

## Issues Encountered
None beyond the one deviation above.

## Checkpoint Verification (Task 3 — auto-approved under AUTO-MODE; all 6 steps run for real)

Host: podman 5.8.3, harnessed-tools:latest rebuilt (post-deviation), 6 `localhost/harnessed-*` images present (tools, omp, ping, claude, hatago, base), `systemctl --user` available, network present.

| Step | Command | Result |
|------|---------|--------|
| 1 | `./harnessed rescan` | **VERIFIED** — iterates all 6 harnessed images (`harnessed-tools`, `-omp`, `-ping`, `-claude`, `-hatago`, `-base`), `podman save`s each, runs `scan-image-online` per image. All 6 returned `Supply-chain image scan clean (HIGH < CVSS 7.0; online)`. Exit **0** (no newly-disclosed HIGHs). After the deviation fix (image rebuild), the loop's safe-exit + independent-image semantics were already proven by the FIRST run (which correctly captured each per-image failure without aborting, cleaned tars, returned rc=1). |
| 2 | Online-mode proof (Pitfall 6) | **VERIFIED (code + behavior)**. Code: `inspect.getsource(run_image_scan_online)` inside the rebuilt image shows `_run(["osv-scanner", "scan", "image", "--archive", ...])` with NO `--offline`; assert `'--offline' not in online_fn` PASSED. Behavior (direct osv-scanner contrast on harnessed-ping:latest): OFFLINE stderr shows `Loaded PyPI local db from /opt/osv-cache/osv-scanner/PyPI/all.zip` + `could not load db for Debian ecosystem: ... no offline version of the OSV database is available` → 2 result blocks (Debian missing); ONLINE stderr has neither message → **3 result blocks** (Debian included via osv.dev). The online nightly catches Debian-ecosystem CVEs the offline build-time DB structurally cannot — exactly Pitfall 6. |
| 3 | Timer install: `cp systemd/harnessed-rescan.{timer,service} ~/.config/systemd/user/ && systemctl --user daemon-reload && systemctl --user enable --now harnessed-rescan.timer` | **VERIFIED** — created `timers.target.wants/harnessed-rescan.timer` symlink; `systemctl --user list-timers harnessed-rescan.timer` shows `NEXT: Fri 2026-06-19 00:00:00 EDT` (OnCalendar=daily → midnight). Scheduled. |
| 4 | Linger: `loginctl show-user $USER --property=Linger` | **Linger=no** (OFF on the host). Per the plan, `loginctl enable-linger $USER` is the documented HARD prerequisite (Pitfall 5) — stated in the timer unit comments + carried to 05-04 troubleshooting. NOT flipped during execution (operator setup decision; it changes user-session behavior). Without it the timer will not fire while the user is logged out. |
| 5 | `systemctl --user start harnessed-rescan.service && journalctl --user -u harnessed-rescan.service` | **VERIFIED** — service start exit 0; journal shows the full timer→service→rescan path: per-image `podman save` → throwaway tools container (`container create ... image=localhost/harnessed-tools:latest`) → `Supply-chain image scan clean (HIGH < CVSS 7.0; online)` → `[SUCCESS] Re-scan complete — all installed harnessed images clean (online)` → `Finished Re-scan installed harnessed images for newly-disclosed CVEs.` (systemd oneshot complete; 1m51s CPU / 1m35s wall). ExecStart `%h/.local/bin/harnessed rescan` resolved via a symlinked launcher (the launcher's symlink-following logic finds HARNESSED_DIR). |
| 6 | Regression: `./harnessed build tracer-time` | **VERIFIED** — build-time scan still uses `scan-image` (OFFLINE). Code: `lib/harnessed-common.sh:162` calls `scan-image "$img_tar"`; `scan.py:326` `run_image_scan` still passes `--offline --offline-vulnerabilities`. Behavior: build output shows `Supply-chain image scan clean (HIGH < CVSS 7.0)` — NO "(online)" suffix (the offline runner omits it; the online runner adds "; online"). Build exit 0. The build-time offline gate is unchanged. |

**Requirement status: SEC-04 — SATISFIED.** All six checkpoint steps verified with real observed output. `harnessed rescan` re-scans installed harnessed images ONLINE (fresh DB for post-build CVEs), each image scanned independently (a finding surfaces without aborting the rest), the timer installs and schedules, and the build-time offline gate is unchanged (regression clear). The one operator-only item is `loginctl enable-linger $USER` (documented; carried to 05-04 troubleshooting).

## User Setup Required

Operator-only setup (the timer unit + the linger prerequisite — cannot be auto-applied as policy):

1. **Install the timer + service units** (one-time): `mkdir -p ~/.config/systemd/user && cp systemd/harnessed-rescan.{timer,service} ~/.config/systemd/user/ && systemctl --user daemon-reload && systemctl --user enable --now harnessed-rescan.timer`.
2. **Enable lingering** (HARD prerequisite — Pitfall 5): `loginctl enable-linger $USER`. Without it the user systemd instance is torn down on logout and the timer never fires overnight. (Currently `Linger=no` on the host.)
3. **Place the launcher on PATH** at `~/.local/bin/harnessed` (the service ExecStart path). The `harnessed` launcher's symlink-resolution logic finds HARNESSED_DIR from a symlink there: `ln -sf /path/to/harnessed ~/.local/bin/harnessed`.
4. **Rebuild harnessed-tools after a harnessed upgrade** that touches `tools/harnessed/*.py` (see deviation 1): `podman build -t harnessed-tools:latest -f tools/Dockerfile tools/`. `ensure_tools_image` is build-if-missing, not staleness-aware.

These will be carried into `docs/guides/troubleshooting.md` (plan 05-04).

## Next Phase Readiness
- SEC-04 is code-complete and verified end-to-end (manual rescan + timer→service→rescan path). The nightly re-scan layer is ready for 05-04 (the troubleshooting doc carries the linger prerequisite, the unit-install steps, and the rebuild-after-upgrade note).
- No blockers. The stale-image issue was a one-time build-artifact freshness gap (resolved by rebuilding), not a code defect; it does surface an operational note (rebuild harnessed-tools after a tools/*.py upgrade) that 05-04's troubleshooting doc should carry.

## Self-Check: PASSED

All Task 1 + Task 2 `<acceptance_criteria>` re-verified PASS (static checks green: `bash -n lib/harnessed-rescan.sh harnessed` clean; `python3 -m py_compile tools/harnessed/*.py` clean; the plan's structural asserts all pass). Plan-level `<verification>` checklist all true (online variant omits --offline; cli subparser+runner+dispatch present; rescan iterates harnessed-* images with safe exit capture + per-iteration tar cleanup + non-zero-on-any-HIGH; rescan parsed before fallthrough; timer has OnCalendar=daily + Persistent=true + linger comment; service has Type=oneshot + the ExecStart; build-time offline scan unchanged). Checkpoint steps 1-6 all VERIFIED with real observed output. `git log --oneline | grep 05-03` returns 2 production commits (`92b4c26`, `ae3a2ab`) + this summary commit.

---
*Phase: 05-secrets-hardening-docs-completeness*
*Plan: 03*
*Completed: 2026-06-18*
