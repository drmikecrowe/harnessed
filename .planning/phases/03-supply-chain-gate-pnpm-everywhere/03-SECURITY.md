---
phase: 03
slug: supply-chain-gate-pnpm-everywhere
status: verified
threats_open: 0
asvs_level: 1
created: 2026-06-16
---

# Phase 03 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> This phase IS a security control (ASVS V10 Supply Chain + V1 Input Validation).

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Internet → build images | npm/PyPI registry + GitHub release downloads enter the built images | Package artifacts + osv-scanner Go binary (integrity-sensitive) |
| Host source → tools container | Host bind-mount of the stack's recipes/profiles crosses into the emit-only tools image for scanning | Recipe/manifest source (untrusted-by-default) |
| Host → hatago image | Built hatago image exported via `podman save` and scanned as a tar archive | Baked image filesystem (final trust surface) |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-03-01 | Tampering/Supply-chain | image JS installs | mitigate | Release-age quarantine (`minimumReleaseAge:1440` + `Strict`), lifecycle default-deny (`strictDepBuilds`), store integrity, exotic-subdep block, pinned pnpm@11. Verified: `pnpm config list` (UAT-6). | closed |
| T-03-02 | Tampering | mise npm backend | mitigate | `mise settings set npm.package_manager pnpm` set BEFORE `mise use -g` in harnessed-base + legacy. Verified: `base/Dockerfile.harnessed-base:64-69`, `Dockerfile:64-68`. | closed |
| T-03-03 | Configuration/Spoofing | pnpm policy authoring | mitigate | v11-valid keys only (no removed `onlyBuiltDependencies`); policy in `~/.config/pnpm/config.yaml`, not `.npmrc`; verified live via `pnpm config list` with no warnings (UAT-6). | closed |
| T-03-04 | Tampering/Supply-chain | baked dependencies | mitigate | osv-scanner (source/image) + pip-audit gated at CVSS≥7.0 — build aborts non-zero on HIGH. Verified: HIGH fixture aborts, sub-HIGH builds green (UAT-3/4); `scan.py gate()`. | closed |
| T-03-05 | Tampering | supply-chain scanner binary | mitigate | Pinned osv-scanner v2.3.8; checksum verified against release `SHA256SUMS` BEFORE `chmod +x`. Verified: `tools/Dockerfile:39-47`. | closed |
| T-03-06 | Elevation of privilege | malicious lifecycle script | accept | Out of plan-02 scope; default-denied by 03-01's `strictDepBuilds` (transfer to T-03-01). | closed |
| T-03-07 | Denial of service | build red-lines / network hang | mitigate | Gate on parsed CVSS only (warn on low/medium); pre-seeded offline OSV DB (no osv.dev hit at scan time); pip-audit warn-and-skips on network failure. Verified: UAT-4 (sub-HIGH green) + UAT-7 (offline). | closed |
| T-03-08 | Information disclosure | scanner token baked | accept | N/A — only credential-free scanners ship this phase (snyk/Socket.dev deferred to Phase 5); no token introduced. | closed |
| T-03-09 | Tampering/Spoofing | false-negative on manifest-less globals | mitigate | osv-scanner exit 128 treated as "investigate" (not a vacuous pass); host `scan image --archive` over `podman save` of the built image is the reliable catch. Verified: `scan.py:172-174`, `lib/harnessed-common.sh:128-133`. | closed |
| T-03-SC (03-01) | Supply-chain | new packages | accept | No new npm/pip/cargo package introduced (pnpm@11 via mise, pre-existing; hatago-mcp-hub pinned in Phase 2). | closed |
| T-03-SC (03-02) | Supply-chain | new packages | mitigate | `pip-audit==2.10.1` (PyPA-official, [OK]); osv-scanner v2.3.8 checksum-verified per T-03-05. | closed |

*Status: open · closed*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-03-01 | T-03-06 | Malicious lifecycle/postinstall script risk is out of plan-02 scope and is default-denied by plan-03-01's `strictDepBuilds` (control transfer). No additional mitigation required this phase. | secure-phase audit | 2026-06-16 |
| AR-03-02 | T-03-08 | No scanner API token is introduced this phase — only credential-free scanners (osv-scanner offline + pip-audit) ship. Token-bearing scanners (snyk, Socket.dev) are explicitly Phase 5. | secure-phase audit | 2026-06-16 |
| AR-03-03 | T-03-SC (03-01) | No new third-party package introduced by plan 03-01; pnpm@11 ships via the already-approved mise toolchain. No Package Legitimacy Gate checkpoint required. | secure-phase audit | 2026-06-16 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-06-16 | 11 | 11 | 0 | secure-phase (evidence: 03-UAT.md 8/8 passed + code inspection) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-06-16
