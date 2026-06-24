# Phase 9: Surgical Profile Mount + History Surfacing - Context

**Gathered:** 2026-06-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Stop mounting the whole `~/.claude/` profile directory; mount only individual config files (`.mcp.json`, `settings.json`, and per-harness equivalents) so image-baked recipe skills survive. Surface per-harness project history for claude, omp, and antigravity back to the host via data-driven mount manifests.

**Key code change:** `harnessed-isolated.sh` currently does `cp -a profile_dir/.claude run_state_dir/.claude` then `-v run_state_dir/.claude:~/.claude:rw` (lines 131–138). Phase 9 eliminates this whole-directory copy-and-mount and replaces it with surgical file-level mounts and direct rw history dir mounts.

</domain>

<decisions>
## Implementation Decisions

### Mount Manifest Format (MNT2-06)

- **D-01:** Use **YAML per harness** in `lib/manifests/` — one file per harness (e.g., `lib/manifests/claude.yaml`, `lib/manifests/omp.yaml`, `lib/manifests/antigravity.yaml`). Parsed with yq (already in base image).
- **D-02:** Each manifest has **two sections only**: `profile_files` (config files to mount from the profile dir) and `history_dirs` (subdirs to rw-mount for history surfacing). Teardown logic stays in bash — the manifest declares paths, not behavior.
- **D-03:** Profile files listed by **filename only** (e.g., `.mcp.json`, `settings.json`). The launcher derives harness-specific container target paths from its own harness knowledge — avoids duplicating paths across six harness manifests.

### Claude History Surfacing (MNT2-03)

- **D-04:** Claude history surfaces to the **real host `~/.claude/`** — rw-mount the history subdirs directly from the host (not into a harnessed state dir). History is visible in Claude.ai and continuable from the host claude CLI.
- **D-05:** **All five MNT2-03 subdirs ship enabled** in Phase 9: `projects/<slug>/`, `file-history/`, `tasks/`, `session-env/`, `todos/` — all rw-mounted from `~/.claude/` on the host.
- **D-06:** **Path mirroring (MNT2-02) handles slug derivation** — set `--workdir $HOST_PWD` (identical absolute host path) so Claude inside the container derives the same project slug as on the host. No manual slug calculation needed.

### State Dir Fate (post-MNT2-01)

- **D-07:** The `~/.local/state/harnessed/<proj>/<stack>/.claude` state dir (the whole-dir copy-on-start) is **eliminated entirely**. Profile config files mount directly from `profiles/<stack>/`. History mounts directly from host `~/.claude/`.
- **D-08:** The `.claude.json` stub path (`~/.local/state/harnessed/<instance>/claude.json`) is **unchanged** — it is at a different path from the `.claude/` dir being removed and stays as-is.

### Profile Dir Breaking Change (MNT2-01 + assembler)

- **D-09:** Existing profiles built under the old model (with `profiles/<stack>/.claude/` trees) are **stale and require rebuild** — run `harnessed build <stack>`. No migration path; rebuild required.
- **D-10:** The launcher's "is built?" guard changes from `[ -d "$profile_dir/.claude" ]` to `[ -f "$profile_dir/.mcp.json" ]`.
- **D-11:** The assembler **skips the fan-out entirely** — it no longer writes skills/commands/agents/hooks/rules to `profiles/<stack>/`. Profile output = `Dockerfile.harnessed-<stack>` + `hatago.config.json` + `.mcp.json` + `settings.json` only. Skills/commands/etc. are baked into the image at build time.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements

- `.planning/REQUIREMENTS.md` §MNT2-01..MNT2-06 — Phase 9 mount requirements (the authoritative requirement set)
- `.planning/ROADMAP.md` §Phase 9 — Goal, success criteria, and dependency on Phase 8

### Existing Implementation (files to be modified)

- `lib/harnessed-isolated.sh` — main isolated launcher; lines 131–138 are the whole-dir copy-and-mount to replace; also contains the "is built?" guard (line 64) to update
- `lib/harnessed-isolated-config.sh` — auth seeding per harness; `.claude.json` stub pattern stays; other per-harness auth mounts stay
- `lib/harnessed-mounts.sh` — host-integration mounts (§4a); not changing in Phase 9

### Harness Home Folder Research

- `docs/research/home-folder-harness-history-overview.md` — may exist; REQUIREMENTS.md MNT2-07 references it as the source of truth for omp/antigravity/opencode/codex path inventories

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `harnessed_host_integration_mounts()` in `lib/harnessed-mounts.sh` — appends to `MOUNT_ARGS[]`; the per-harness manifest reader should use the same pattern (append individual file mounts to `MOUNT_ARGS`)
- `harnessed_isolated_auth_mounts()` in `lib/harnessed-isolated-config.sh` — per-harness switch/case pattern; the new manifest-driven mount function should follow the same structure

### Established Patterns

- **MOUNT_ARGS array pattern**: all mount code appends `-v` flags to `MOUNT_ARGS=()` declared by the caller. Phase 9 manifest reader must append to the same array.
- **yq parsing**: yq (mikefarah, Go) is in the base image; manifests can use `yq '.profile_files[]' lib/manifests/claude.yaml`.
- **Per-harness switch**: `harnessed-isolated.sh` and `harnessed-isolated-config.sh` both branch on `$harness` (claude/omp/opencode/gemini/antigravity/codex). The manifest loader fits naturally into this pattern.

### Integration Points

- `harnessed_isolated()` in `lib/harnessed-isolated.sh`: the primary function to modify. The whole-dir copy block (lines 131–138) is replaced by: (1) load manifest for `$harness`, (2) mount individual profile_files, (3) mount history_dirs from host `~/.claude/`.
- `harnessed build` / assembler: must stop writing skills/commands/agents/hooks/rules to `profiles/<stack>/`. The assembler's sync-plugin-links fan-out step is removed.
- Profile dir shape: `profiles/gstack-time/` after Phase 9 contains `Dockerfile.harnessed-gstack-time`, `hatago.config.json`, `.mcp.json`, `settings.json` only.

</code_context>

<specifics>
## Specific Ideas

- For the manifest loader, a new `lib/harnessed-manifest-mounts.sh` function (e.g., `harnessed_manifest_mounts "$harness" "$profile_dir"`) is the natural shape — mirrors the existing mount helper naming convention.
- The `--workdir $HOST_PWD` change (MNT2-02) means the current `-w "$CONTAINER_HOME/$relpath"` in `harnessed-isolated.sh` becomes `-w "$project_path"` (the host absolute path directly).

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 9-surgical-profile-mount-history-surfacing*
*Context gathered: 2026-06-24*
