---
status: complete
phase: 06-tech-debt-cleanup
source: [06-01-SUMMARY.md, 06-02-SUMMARY.md, 06-03-SUMMARY.md]
started: 2026-06-21T23:36:15Z
updated: 2026-06-22T00:45:43Z
---

## Current Test

[testing complete]

## Tests

### 1. SC-1 — No dead harnessed-net code (authoritative surface)
expected: Repo-wide `harnessed-net` search returns only live/opt-in/now-accurate refs in authoritative docs/code/manifests/CLI; the 6 flagged files carry zero stale bridge-as-default assertions.
result: pass
evidence: |
  git grep (excl .planning/.claude) → every surviving ref classified:
  lib/harnessed-isolated.sh:77 (:-default, live D-03), lib/harnessed-services.sh:27,29
  (ensure_named_net, live D-03), docs/harnessed-design.md:267 (opt-in context),
  tools/harnessed/assemble.py:66 (replacement-doc), docs/codebase/CONCERNS.md:32
  (historical pivot). The 6 flagged files (INTEGRATIONS.md, server.py, schema.py,
  CLAUDE.md, stack.yaml, harnessed) now describe host-gateway framing; old DNS-name
  URLs survive only as labeled HARNESSED_NET opt-in (0 orphan lines).

### 2. SC-1 residual — generated docs/codebase/* snapshots
expected: 4 stale refs in 3 generated map-codebase snapshots cleared.
result: pass
evidence: |
  Regenerated all 7 docs/codebase/* via map-codebase (4 parallel domain agents,
  2026-06-22). +1518/-711 across 7 files. The 4 stale bridge-as-default assertions
  are GONE; every surviving `harnessed-net` ref now frames it as the explicit opt-in
  (ARCHITECTURE.md:60 "opt-in bridge, not the default"; STRUCTURE.md:215 "Never
  describe a shared service as 'on harnessed-net' by default"; CONVENTIONS.md:757
  prescriptive warning). host.containers.internal now documented across all 7 docs.
  Multi-harness support (claude/omp/opencode/gemini/antigravity/codex) captured.
  Product code untouched (scope-confirmed via git status).

### 3. SC-2 — design docs + code comments reconciled (plan 06-01)
expected: design.md §3/§9/§13 document publish + host.containers.internal as PRIMARY with HARNESSED_NET opt-in; §9 operator-prereq callout present. B1-B7 comments describe host-published model. [INFERENCE] markers + D-07 replacement-docs intact.
result: pass
evidence: |
  design.md: host.containers.internal ×8, 169.254.1.2 ×1, allowed_hosts ×2,
  [INFERENCE] markers ×2, "Operator prerequisites" callout ×1. services.sh:4-6 + :68-69
  + :101-105, isolated.sh:24-27 + :141-145, service.yaml:3-4, recipe.yaml:4-7 all
  describe host-gateway model. rescan.service B7 corrected.

### 4. SC-2 — CLI help + docstrings + repo-wide docs (plan 06-03)
expected: harnessed svc-up help + section comment, schema.py ServiceDef docstring, server.py docstring, CLAUDE.md engine bullet, stack.yaml comment, INTEGRATIONS.md describe host-gateway framing. Static parse gates green.
result: pass
evidence: |
  harnessed:51-52 + :254-255 host-published framing; schema.py:144-147 ServiceDef docstring;
  server.py:6-8 module docstring; CLAUDE.md:153 engine bullet; stack.yaml:5-6 comment;
  INTEGRATIONS.md host-gateway framing. Static gates (bash -n, ast.parse, yaml.safe_load)
  per 06-VERIFICATION.md: all PASS.

### 5. SC-3 — SUMMARY frontmatter schema (plan 06-02)
expected: All 16 0*-SUMMARY.md under .planning/phases/0[1-5]-*/ open with `---` and carry exactly one `# Dependency graph` block.
result: pass
evidence: |
  All 16 SUMMARYs (01-01..03, 02-01..03, 03-01..02, 04-01..04, 05-01..04) verified:
  head -1 == "---" and grep '# Dependency graph' == 1 each.

### 6. Live capability gate — deferred runtime tests
expected: harnessed test ping-time, harnessed test tracer-time, and bash tools/uat/run-uat.sh pass — confirming zero runtime regression from the doc/comment edits. Requires rootless podman.socket active.
result: pass
evidence: |
  podman.socket brought up runtime-only (Rootless: true), then stopped after (restored
  to disabled). Three deferred legs all green:
  - harnessed test ping-time → time ✓ + ping ✓ MCP connected, time-helper ✓ skill (22.7s)
  - harnessed test tracer-time → time ✓ MCP connected, time-helper ✓ skill (19.3s)
  - bash tools/uat/run-uat.sh 4 → 16/16 tests PASS, 50/50 checks PASS (189.4s)
  The ping shared-service sidecar connected via host.containers.internal — the exact
  host-gateway model phase 6 documents — proving the comments match shipped runtime.

## Summary

total: 6
passed: 6
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

[none]
