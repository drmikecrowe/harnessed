---
phase: 03-supply-chain-gate-pnpm-everywhere
status: passed
verified: 2026-06-19
score: 3/3 requirements satisfied
source: [03-UAT.md, 03-01-SUMMARY.md, 03-02-SUMMARY.md]
---

# Phase 3 Verification — Supply-Chain Gate + pnpm-Everywhere

**Phase goal** (ROADMAP): `harnessed build` enforces pnpm-everywhere managed config and a
credential-free HIGH-severity scan gate, so no dependency with a high-severity vulnerability is
committed or baked into an image.

> Reconciliation note: the phase was validated under `03-UAT.md` (status: complete, 8/8 tests,
> all green with evidence) at execution time but never recorded a `VERIFICATION.md`, so the
> stats reader (`determinePhaseStatus`) defaulted the phase to "Executed". This file records the
> verification verdict the stats counter reads; the load-bearing outcomes were **re-run live
> 2026-06-19** (below) and remain green.

## Goal Achievement — Observable Truths (re-verified 2026-06-19)

| # | Truth | Status | Evidence (live re-run) |
|---|-------|--------|------------------------|
| 1 | A HIGH-severity dependency aborts `harnessed build` BEFORE any image is baked | ✓ VERIFIED | `./harnessed build vuln-stack --root tools/test-fixtures` → **exit 1**; `supply-chain source scan found 1 HIGH+ finding (CVSS >= 7.0): GHSA-x84v-xcm2-53pg`; aborts pre-bake |
| 2 | The gate is severity-driven (CVSS≥7.0), not exit-1-on-any-finding | ✓ VERIFIED | `./harnessed build low-stack --root tools/test-fixtures` (mistune 0.7.4, max CVSS 6.1) → **exit 0** (findings = warnings, build green) |
| 3 | A recipe using raw `npm`/`npx` is rejected, naming the pnpm equivalent | ✓ VERIFIED | `./harnessed build npm-stack --root tools/test-fixtures` → **exit 1**; `recipe 'npm-recipe': MCP server 'npx-server' uses raw 'npx'. Use the pnpm equivalent 'pnpm dlx'` |
| 4 | All JS installs route through pnpm with managed supply-chain config | ✓ VERIFIED | `03-UAT.md` test 6 evidence: `pnpm config list` shows minimumReleaseAge=1440, minimumReleaseAgeStrict=true, blockExoticSubdeps=true, verifyStoreIntegrity=true, strictDepBuilds=true; pnpm 11.6.0 |
| 5 | The scan is credential-free + offline at build time | ✓ VERIFIED | `03-UAT.md` test 7 evidence: `scan.py` uses `--offline --offline-vulnerabilities`; pre-seeded `XDG_CACHE_HOME=/opt/osv-cache`; image scan via `podman save` tar (ro), no socket mount |

**Score:** 5/5 truths verified.

## Requirements Coverage

| Requirement | Status |
|-------------|--------|
| BLD-01 pnpm-everywhere managed supply-chain config | ✓ SATISFIED |
| BLD-02 credential-free osv-scanner/pip-audit HIGH-severity gate | ✓ SATISFIED |
| BLD-03 raw npm/npx recipe lint with pnpm equivalent | ✓ SATISFIED |

**Coverage:** 3/3 requirements satisfied.

## Gaps Summary

**No gaps.** All 8 `03-UAT.md` tests passed at execution; the three load-bearing outcomes
(HIGH abort, severity-correct green, raw-npm lint) were re-run live 2026-06-19 and remain green.

---
*Verified: 2026-06-19 (reconciliation — UAT-recorded verification promoted to canonical artifact + live re-run)*
