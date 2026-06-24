---
phase: "09"
slug: surgical-profile-mount-history-surfacing
status: verified
threats_open: 0
asvs_level: 1
created: 2026-06-24
---

# Phase 09 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Manifest YAML → mount decisions | yq parses committed repo files; output drives -v flags | Filesystem paths (low sensitivity — repo-committed) |
| Host $HOME → container via history rw-mounts | rw bind allows container writes to land on host | Session history (medium — conversation data) |
| profile_dir → container ro-mounts | Profile files (mcp.json, settings.json) mounted read-only | Tool config (low sensitivity) |
| Python assembler → profile dir | Assembler writes mcp.json/settings.json to profiles/<stack>/ | Tool config (low sensitivity) |
| Launcher → container | All -v and -w flags derive from launcher code | Filesystem paths |
| UAT tests → host filesystem | Tests read host dirs to assert history surfacing | Test-scope only; no production data written |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-09-01 | Information Disclosure | history dir rw-mounts (MNT2-03/04/05) | mitigate | Manifests list specific named subdirs only; parent dirs (.claude/, .omp/, .gemini/) never in history_dirs; auth files explicitly excluded — verified: 0 credential path matches in manifests | closed |
| T-09-02 | Tampering | omp slug derivation | mitigate | Slug computed from HOST $relpath (same algorithm as omp); host dir pre-created with mkdir -p before bind; verified: relpath parameter wired in harnessed_manifest_mounts | closed |
| T-09-03 | Information Disclosure | antigravity history paths | mitigate | Manifests mount only .gemini/antigravity-cli/{conversations,brain,implicit} — never .gemini/ proper; verified: antigravity.yaml history_dirs confirmed correct | closed |
| T-09-04 | Tampering | malformed manifest YAML | mitigate | Originally accepted (no-mounts-on-error); upgraded to mitigate by CR-01 fix — yq errors now propagate as warnings + return 1 instead of silent skip; verified: return 1 present in harnessed-manifest-mounts.sh | closed |
| T-09-SC-1 | Tampering | npm/pip/cargo installs (plan 01) | accept | No new packages installed | closed |
| T-09-A01 | Tampering | emit.py write target | mitigate | write_mcp_json(profile_dir) targets profile root; verified: rg confirms single match emit.write_mcp_json(profile_dir) in assemble.py | closed |
| T-09-A02 | Information Disclosure | residual .claude/ tree in profiles | mitigate | reset_profile() calls shutil.rmtree(profile_dir) on every build; verified: function present in emit.py, called from assemble.py | closed |
| T-09-A03 | Tampering | removed skills fan-out | accept | Skills baked into harness images (Phase 8); removing fan-out reduces not expands attack surface | closed |
| T-09-SC-2 | Tampering | npm/pip/cargo installs (plan 02) | accept | No new packages installed | closed |
| T-09-B01 | Information Disclosure | residual .claude/ mounts from old copy block | mitigate | Old copy-and-mount block removed; harnessed_manifest_mounts mounts only manifest-listed paths; verified: rg 'cp -a' returns 0 matches in harnessed-isolated.sh | closed |
| T-09-B02 | Tampering | mcp_cfg path update | mitigate | mcp_cfg updated to $CONTAINER_HOME/.mcp.json (ro-mounted from profile); claude --mcp-config points to ro file; verified: rg confirms correct path in harnessed-isolated.sh | closed |
| T-09-B03 | Tampering | workdir set to $project_path | accept | $project_path derives from $PWD (user-controlled); exposure equals existing project bind mount already in place | closed |
| T-09-B04 | Elevation | stale profile passes new is-built guard | mitigate | Guard checks [ -f "$profile_dir/.mcp.json" ]; stale profiles (with .claude/ tree but no root .mcp.json) fail and force rebuild; verified: guard present in harnessed-isolated.sh | closed |
| T-09-SC-3 | Tampering | npm/pip/cargo installs (plan 03) | accept | No new packages installed | closed |
| T-09-C01 | Tampering | UAT teardown deleting real history | mitigate | Integration tests assert dir existence only; teardown calls uat_pod_rm (container only); verified: rg finds 0 rm -rf of host history dirs in phase-09.sh | closed |
| T-09-C02 | Information Disclosure | omp slug assertion reads real session paths | accept | Test only asserts existence at computed slug path; no file contents read or logged | closed |
| T-09-C03 | Tampering | test_manifest_no_credentials false negative | mitigate | UAT test uses explicit rg patterns (agent.db, antigravity-oauth-token, .credentials.json); pattern list reviewed at authoring time; verified: patterns present and smoke test passes | closed |
| T-09-SC-4 | Tampering | npm/pip/cargo installs (plan 04) | accept | No new packages installed | closed |

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-09-01 | T-09-A03 | Skills fan-out removal reduces not expands surface; skills now baked at image build time (Phase 8 Dockerfile recipe model) | phase author | 2026-06-24 |
| AR-09-02 | T-09-B03 | workdir set to $project_path: identical exposure to the existing project bind mount; no new host filesystem segments exposed | phase author | 2026-06-24 |
| AR-09-03 | T-09-C02 | omp slug test only asserts directory existence; no session content is read or logged | phase author | 2026-06-24 |
| AR-09-04 | T-09-SC-1..4 | No new npm/pip/cargo packages installed across all 4 plans; supply-chain surface unchanged | phase author | 2026-06-24 |

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-06-24 | 18 | 18 | 0 | gsd-secure-phase (orchestrator direct — register_authored_at_plan_time: true, threats_open: 0 short-circuit) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-06-24
