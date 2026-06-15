---
phase: 03-supply-chain-gate-pnpm-everywhere
plan: 02
subsystem: infra
tags: [osv-scanner, pip-audit, supply-chain, cvss-gate, recipe-lint, podman]

# Dependency graph
requires:
  - phase: 03-supply-chain-gate-pnpm-everywhere (plan 01)
    provides: the managed pnpm v11 policy + a clean-building harnessed-tools image base
provides:
  - tools/harnessed/scan.py — CVSS>=HIGH severity gate over osv-scanner/pip-audit JSON
  - validate_no_raw_npm() — assembler fail-fast lint rejecting raw npm/npx with the pnpm equivalent
  - harnessed-tools image with osv-scanner 2.3.8 + pip-audit + pre-seeded offline PyPI+npm DBs
  - scan / scan-image CLI subcommands; scoped source scan + host image scan wired into build_stack
  - --root launcher override + npm/vuln/low fixtures in the resolver layout
affects: [harnessed-build, image-hardening, recipe-authoring]

# Tech tracking
tech-stack:
  added: [osv-scanner@2.3.8, pip-audit@2.10.1]
  patterns:
  - "Severity gate as pure Python over scanner JSON (gate() reads severity[].score, CVSS>=7.0) — never exit-code-as-high"
  - "Offline OSV DB pre-seeded per-ecosystem via XDG_CACHE_HOME (user-independent) from representative manifests"
  - "Scoped source scan (load_stack_with_recipes) so a committed fixture cannot red-line an unrelated build"
  - "Host-driven image scan (podman save → osv-scanner scan image --archive) — no daemon socket"

key-files:
  created:
  - tools/harnessed/scan.py
  - tools/test-fixtures/recipes/npm-recipe/recipe.yaml
  - tools/test-fixtures/stacks/npm-stack/stack.yaml
  - tools/test-fixtures/recipes/vuln-recipe/recipe.yaml
  - tools/test-fixtures/recipes/vuln-recipe/requirements.txt
  - tools/test-fixtures/stacks/vuln-stack/stack.yaml
  - tools/test-fixtures/recipes/low-recipe/recipe.yaml
  - tools/test-fixtures/recipes/low-recipe/requirements.txt
  - tools/test-fixtures/stacks/low-stack/stack.yaml
  modified:
  - tools/harnessed/schema.py
  - tools/harnessed/assemble.py
  - tools/harnessed/cli.py
  - tools/Dockerfile
  - tools/pyproject.toml
  - lib/harnessed-common.sh
  - harnessed
  - .gitignore

key-decisions:
  - "The HIGH threshold is Python logic over osv-scanner's --format JSON reading severity[].score (CVSS>=7.0), never the scanner exit code. osv-scanner `scan` exits 1 on ANY finding (no severity flag) — a naive exit-1-as-high gate is provably wrong (would abort the LOW fixture)."
  - "Offline DB seeded per-ecosystem via XDG_CACHE_HOME=/opt/osv-cache from representative manifests (requirements.txt→PyPI, package-lock.json→npm). osv-scanner v2.3.8 rejects a bare --download-offline-databases; the DB is fetched by a scan with --download-offline-databases, then scans use --offline --offline-vulnerabilities (network OFF)."
  - "pip-audit findings are warnings-only (its JSON carries no CVSS); the gate relies on osv-scanner for the HIGH decision. pip-audit warn-and-skips on network failure so a firewalled env never red-lines for the wrong reason."
  - "LOW fixture is mistune==0.7.4 (max CVSS 6.1), NOT the plan's urllib3==1.24.1 (CVE-2019-11324 parses to CVSS 7.5 = HIGH, not MEDIUM — would have defeated the severity proof)."

patterns-established:
  - "Scanner invocation flags must follow the v2.3.8 subcommand: `osv-scanner scan source --offline --offline-vulnerabilities -r ...` (NOT `--offline scan source`)"
  - "Fixtures live in the resolver layout (recipes/ + stacks/ under one --root) so `--root tools/test-fixtures` exercises the full path without polluting real stacks/"

requirements-completed: [BLD-02, BLD-03]

# Metrics
duration: ~90min
completed: 2026-06-15
---

# Phase 3 Plan 02: scan gate + raw-npm lint Summary

**Credential-free CVSS>=HIGH scan gate (osv-scanner offline + pip-audit) + raw-npm/npx recipe lint wired into `harnessed build`, proven by a HIGH-abort fixture AND a sub-HIGH fixture that builds green — the only test that distinguishes a real CVSS gate from exit-1-as-high.**

## Performance

- **Duration:** ~90 min (executor auto-tasks + checkpoint image rebuild + osv CLI investigation + revisions)
- **Tasks:** 3 auto + 1 human-verify checkpoint (approved via podman rebuild + 5 proof checks)
- **Files:** 17 (9 created + 8 modified)

## Accomplishments
- `validate_no_raw_npm()` in schema.py + fail-fast call in assemble.py — recipes using `npm`/`npx` abort before emit with the exact pnpm equivalent (`npx`→`pnpm dlx`, etc.). Word-boundaried so `npmlog` is not flagged. (BLD-03)
- `tools/harnessed/scan.py` (new) — severity-driven gate: `HIGH = 7.0`, pure `gate(osv_json)` reads `severity[].score` (CVSS v3 vector parse + label fallback) and returns HIGH+ ids; `run_source_scan` is SCOPED via `load_stack_with_recipes`; `run_image_scan` for archives. Swallows osv-scanner exit 1 (any-finding), warns on exit 128 (no packages) and exit 127 (missing DB). pip-audit warn-and-skips on network failure. (BLD-02)
- osv-scanner v2.3.8 (checksum-verified) + pip-audit 2.10.1 baked into the tools image; offline PyPI+npm DBs pre-seeded under `XDG_CACHE_HOME=/opt/osv-cache` (owned by uid 1000, found at run time regardless of user).
- `scan`/`scan-image` CLI subcommands; `build_stack` runs the scoped source scan (after assemble) + host image scan (`podman save` → `scan-image`, after the hatago build) with safe `|| rc=$?` exit capture under `set -euo pipefail`; `print_success` only after both pass.
- `--root` launcher override (HARNESSED_ROOT) lets fixtures exercise the full wired path. npm/vuln/low fixtures in the resolver layout.

## Task Commits

1. **Task 1: raw npm/npx recipe lint** — `1d564f7` (feat)
2. **Task 2: scan gate + tools image + scan subcommands** — `754173e` (feat)
3. **Task 3: build_stack wiring + launcher --root + fixtures** — `1cff898` (feat)
4. **Checkpoint revision: osv-scanner offline invocation** — `a7c0fd3` (fix)

## Files Created/Modified
- `tools/harnessed/scan.py` (NEW) — the CVSS>=HIGH gate + scoped source/image scan invokers.
- `tools/harnessed/schema.py` — `RecipeLintError` + `validate_no_raw_npm(recipe)`.
- `tools/harnessed/assemble.py` — calls `validate_no_raw_npm` per recipe before emit.
- `tools/harnessed/cli.py` — `scan`/`scan-image` subcommands; `RecipeLintError` → exit 1.
- `tools/Dockerfile` — osv-scanner 2.3.8 (checksum-verified) + pip-audit + `XDG_CACHE_HOME` + PyPI+npm offline DB seed.
- `tools/pyproject.toml` — `pip-audit==2.10.1`.
- `lib/harnessed-common.sh` — build_stack: scoped source scan + host image scan wiring; `--root` forwarding.
- `harnessed` (launcher) — `--root` → `HARNESSED_ROOT`.
- `.gitignore` — `tools/test-fixtures/profiles/`.
- `tools/test-fixtures/recipes|stacks/{npm,vuln,low}-*` — the fixtures.

## Decisions Made
- **Severity gate, not exit-code gate.** osv-scanner `scan` exits 1 on any finding with no severity flag; the HIGH threshold is Python over `--format json` `severity[].score`. Proven by the LOW fixture building green while the vuln fixture aborts.
- **Offline DB via XDG_CACHE_HOME.** osv-scanner v2.3.8's offline model: the DB is seeded per-ecosystem by a scan with `--download-offline-databases` against real manifests, cached under XDG_CACHE_HOME; scans use `--offline --offline-vulnerabilities`. A fixed `/opt/osv-cache` (owned by uid 1000) makes the DB user-independent at run time.
- **pip-audit = warnings only.** Its JSON has no CVSS, so it can't drive the HIGH decision; it surfaces findings as warnings and warn-and-skips on network failure.
- **LOW fixture = mistune==0.7.4.** The plan's urllib3==1.24.1 is CVSS 7.5 (HIGH), not MEDIUM — would have aborted and defeated the severity proof.

## Deviations from Plan

### Auto-fixed Issues

**1. osv-scanner offline invocation wrong for v2.3.8**
- **Found during:** Task 4 checkpoint (tools image build failed: `osv-scanner --download-offline-databases` → "databases can only be downloaded when running in offline mode", exit 127; scan.py's `--offline scan source` mis-parsed → "stat /tmp/scan").
- **Issue:** The plan/RESEARCH assumed `osv-scanner --download-offline-databases` seeds the DB and `--offline scan` uses it. v2.3.8 requires the DB be seeded by a SCAN with `--download-offline-databases` against real manifests, and scan flags must follow the subcommand.
- **Fix:** Dockerfile sets `XDG_CACHE_HOME=/opt/osv-cache` and seeds PyPI+npm from a manifests dir; scan.py uses `scan source --offline --offline-vulnerabilities ...` (and `scan image ...`). Verified on-host against the real CLI before fixing.
- **Files modified:** tools/Dockerfile, tools/harnessed/scan.py.
- **Verification:** rebuilt tools image seeds both DBs ("Loaded npm local db" + "Loaded PyPI local db"); all 5 proof checks pass.
- **Committed in:** `a7c0fd3`.

**2. LOW fixture (urllib3==1.24.1) is actually HIGH**
- **Found during:** Task 3 (executor parsed the CVSS vector: CVE-2019-11324 = CVSS:3.0/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:H/A:N = 7.5; urllib3 1.24.1 has 19 findings, multiple HIGH).
- **Issue:** The plan assumed urllib3==1.24.1 is MEDIUM; it is HIGH — would have aborted and defeated the "sub-HIGH builds green" proof.
- **Fix:** Swapped the LOW fixture to mistune==0.7.4 (8 MODERATE findings, max CVSS 6.1 < 7.0). HIGH fixture (requests==2.19.0) unchanged.
- **Files modified:** tools/test-fixtures/recipes/low-recipe/requirements.txt.
- **Verification:** checkpoint check 3 — `scan low-stack` exits 0 with the mistune findings as warnings.
- **Committed in:** `1cff898`.

---

**Total deviations:** 2 auto-fixed (1 at checkpoint, 1 at Task 3).
**Impact on plan:** Both necessary for correctness — the plan's RESEARCH was wrong about both osv v2.3.8's offline CLI and urllib3's CVSS. No scope creep; the gate's design intent (severity-driven, scoped, credential-free) is fully realized.

## Issues Encountered
- None beyond the two deviations above. The host-driven image scan (`podman save` + `scan image --archive`) of the hatago image ran clean (npm DB seeded → functional; no HIGH in hatago's deps).

## Self-Check: PASSED
Checkpoint verification (rebuilt tools image + 5 proof checks):
- [x] tools image: osv-scanner 2.3.8, PyPI+npm offline DBs seeded.
- [x] HIGH-abort: `scan vuln-stack` → exit 1, `GHSA-x84v-xcm2-53pg` (CVE-2018-18074, CVSS 7.5).
- [x] LOW-green: `scan low-stack` → exit 0, mistune findings as warnings (the severity-gate proof).
- [x] npm-lint: `assemble npm-stack` → exit 1, "Use the pnpm equivalent 'pnpm dlx'".
- [x] clean regression: `./harnessed build tracer-time` → exit 0 (scoped source scan skips the fixtures; hatago image scan clean).
- [x] nothing mounts a daemon socket or drives podman from inside the image; pip-audit warn-and-skips on network failure.

## Next Phase Readiness
- `harnessed build` now vetoes bad input (raw npm/npx) and bad dependencies (HIGH+ vulns) before anything is committed or baked.
- The scan gate is credential-free, non-interactive, deterministic (offline DB), and scoped to the built stack; the host stays podman-only.
- Phase 4+ can layer recipe breadth / shared services on a trustworthy build base.

---
*Phase: 03-supply-chain-gate-pnpm-everywhere*
*Completed: 2026-06-15*
