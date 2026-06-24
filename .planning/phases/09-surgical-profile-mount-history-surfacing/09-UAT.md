---
status: complete
phase: 09-surgical-profile-mount-history-surfacing
source: 09-01-SUMMARY.md, 09-02-SUMMARY.md, 09-03-SUMMARY.md, 09-04-SUMMARY.md
started: 2026-06-24T00:00:00Z
updated: 2026-06-24T00:00:00Z
---

## Current Test

[testing complete]

## Tests

### 1. 6 harness manifests ship (auto-verified)
expected: lib/manifests/ contains claude.yaml omp.yaml antigravity.yaml opencode.yaml gemini.yaml codex.yaml — each with profile_files and history_dirs keys
result: pass

### 2. No credential paths leak into manifests (auto-verified)
expected: None of agent.db, .credentials.json, antigravity-oauth-token appear in any manifest file
result: pass

### 3. Manifest mounts helper is valid bash (auto-verified)
expected: lib/harnessed-manifest-mounts.sh exists, defines harnessed_manifest_mounts(), passes bash -n syntax check
result: pass

### 4. Launcher is wired to manifest mounts (auto-verified)
expected: lib/harnessed-isolated.sh sources harnessed-manifest-mounts.sh and calls harnessed_manifest_mounts(); the old copy-and-mount block is gone
result: pass

### 5. Assembler carries no fan-out traces (auto-verified)
expected: assemble.py and emit.py contain no syncer/LinkSyncer/harness_dir/ensure_profile_tree symbols
result: pass

### 6. UAT smoke suite passes (auto-verified)
expected: bash tools/uat/run-uat.sh phase-09 --quick → 6 passed, 0 failed, 4 skipped
result: pass

### 7. Stack assembles with flat profile layout
expected: profiles/gstack-time/ has .mcp.json at root, no .claude/ tree. Run: cd tools && mise exec -- uv run harnessed-tools assemble --build-dir .. --root .. gstack-time
result: pass

### 8. yq error propagation on malformed manifest
expected: Temporarily corrupt a manifest (e.g. add invalid YAML to lib/manifests/claude.yaml), run the mounts helper in isolation, and confirm a warning is printed + the function returns non-zero. Restore the file after. Or confirm the fix visually in lib/harnessed-manifest-mounts.sh — yq output is captured and checked; 2>/dev/null suppression is absent.
result: pass

### 9. antigravity manifest mounts only specific subdirs
expected: lib/manifests/antigravity.yaml history_dirs lists .gemini/antigravity-cli/conversations, .gemini/antigravity-cli/brain, .gemini/antigravity-cli/implicit — NOT the parent ~/.gemini/ dir (which holds OAuth tokens)
result: pass

## Summary

total: 9
passed: 9
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

[none yet]
