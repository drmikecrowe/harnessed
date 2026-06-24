# Phase 9: Surgical Profile Mount + History Surfacing — Research

**Researched:** 2026-06-24
**Domain:** Bash launcher surgery + Python assembler refactor + YAML mount manifests
**Confidence:** HIGH — all claims based on direct code reading of the existing implementation

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-01** Use YAML per harness in `lib/manifests/` — one file per harness. Parsed with yq.
**D-02** Each manifest has two sections only: `profile_files` and `history_dirs`. Teardown logic stays in bash.
**D-03** Profile files listed by filename only (e.g., `.mcp.json`, `settings.json`). Launcher derives container target paths.
**D-04** Claude history surfaces to the real host `~/.claude/` — rw-mount history subdirs directly from host.
**D-05** All five MNT2-03 subdirs ship enabled: `projects/<slug>/`, `file-history/`, `tasks/`, `session-env/`, `todos/`.
**D-06** Path mirroring (MNT2-02) handles slug derivation — set `--workdir $HOST_PWD` (identical absolute host path).
**D-07** The `~/.local/state/harnessed/<proj>/<stack>/.claude` state dir is eliminated entirely.
**D-08** The `.claude.json` stub path stays unchanged.
**D-09** Existing profiles require rebuild — no migration path.
**D-10** Launcher's is-built guard changes from `[ -d "$profile_dir/.claude" ]` to `[ -f "$profile_dir/.mcp.json" ]`.
**D-11** The assembler skips the fan-out entirely. Profile output = Dockerfile + hatago.config.json + .mcp.json + settings.json only.

### Claude's Discretion

None specified.

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MNT2-01 | Surgical config-file mount — mount individual files (.mcp.json, settings.json), not whole .claude/ dir | Assembler fan-out removal + manifest profile_files section |
| MNT2-02 | Path mirroring — container workdir = identical absolute host path | workdir flag + project volume mount change; enables slug alignment |
| MNT2-03 | Claude history surfacing — rw-mount projects/<slug>/, file-history/, tasks/, session-env/, todos/ | Claude research doc; all UUID-keyed parent dirs; D-05 ships all enabled |
| MNT2-04 | omp history surfacing — rw-mount agent/sessions/<slug>/ and optionally agent/blobs/ | omp research doc; slug from host-relative path (relpath var available) |
| MNT2-05 | antigravity history surfacing — rw-mount conversations/, brain/, implicit/ | antigravity research doc; per-conversation UUID DBs, collision-free |
| MNT2-06 | Data-driven mount manifests — per-harness YAML files in lib/manifests/ | D-01/D-02/D-03; parsed with yq already in base image |
</phase_requirements>

---

## Summary

Phase 9 is a surgical refactor with three interlocking deliverables: (1) eliminate the whole-directory `.claude/` copy-and-mount in favour of individual config file mounts, (2) surface per-harness project history to the host via rw bind-mounts on history subdirs, and (3) make the mount/teardown set data-driven via per-harness YAML manifests in `lib/manifests/`.

All research docs (`docs/research/home-folder-{claude,omp,antigravity}-requirements.md`) are already written and contain verified path inventories, keying hazards, and implementation guidance. The assembler (`tools/harnessed/assemble.py` + `tools/harnessed/emit.py`) still fans skills/commands into `profiles/<stack>/.claude/` and writes `.mcp.json`/`settings.json` inside that tree. Phase 9 removes the fan-out and moves the two config files to profile root. The launcher (`lib/harnessed-isolated.sh`) still does a whole-dir `cp -a profile_dir/.claude run_claude` then mounts `run_claude` as `~/.claude`; Phase 9 replaces those 8 lines with a manifest-driven mount function plus history dir mounts.

**Primary recommendation:** Implement in this order — (1) new manifest files, (2) new `lib/harnessed-manifest-mounts.sh` function, (3) assembler changes (emit targets + fan-out removal), (4) launcher changes (guard, mount block, workdir, attach paths, claude MCP arg). Each step is independently verifiable and the ordering prevents state where the launcher looks for `.mcp.json` at profile root before the assembler emits it there.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Config file mount (MNT2-01) | Host bash (launcher) | Python assembler | Launcher mounts; assembler determines what to emit at profile root |
| Path mirroring (MNT2-02) | Host bash (launcher) | Host bash (mounts helper) | `-w` and `-v` flags in launcher / harnessed-mounts.sh |
| History dir mounts (MNT2-03/04/05) | Host bash (launcher) | New manifest-mounts helper | Creates host dirs if absent, appends to MOUNT_ARGS |
| Mount manifest format (MNT2-06) | YAML files in lib/manifests/ | yq (already in base image) | Data-driven; parsed by new bash helper |
| Assembler fan-out removal (D-11) | Python (emit.py + assemble.py) | — | Stops writing .claude/ tree to profiles/ |
| Is-built guard update (D-10) | Host bash (harnessed-isolated.sh) | — | Single line change |
| State dir elimination (D-07) | Host bash (harnessed-isolated.sh) | — | Remove 8-line copy+mount block |

---

## Standard Stack

### Core

| Tool | Version | Purpose | Status |
|------|---------|---------|--------|
| yq (mikefarah Go) | 4.x | Parse lib/manifests/*.yaml in bash | Already in base image [VERIFIED: codebase] |
| bash | system | Launcher and mount helper functions | Host-native |
| Python 3.12 | in harnessed-tools image | Assembler (assemble.py + emit.py) | Already in image [VERIFIED: codebase] |

### No New Dependencies

This phase introduces no new external packages. All tools are already present. [VERIFIED: codebase — yq in Dockerfile, Python in harnessed-tools image]

### Package Legitimacy Audit

No external packages are installed in this phase.

---

## Architecture Patterns

### System Architecture Diagram

```
harnessed build <stack>              harnessed <stack>
       │                                    │
       ▼                                    ▼
  assemble.py                     harnessed-isolated.sh
       │                                    │
  emit .mcp.json ──────────► profiles/<stack>/.mcp.json
  emit settings.json ───────► profiles/<stack>/settings.json
  emit hatago.config.json ──► profiles/<stack>/hatago.config.json
  emit Dockerfile ──────────► profiles/<stack>/Dockerfile.harnessed-*
  emit baked-servers.json ──► profiles/<stack>/baked-servers.json
  (NO .claude/ fan-out)                    │
                                           ▼
                               harnessed_manifest_mounts()
                               reads lib/manifests/<harness>.yaml
                                    │               │
                             profile_files     history_dirs
                                    │               │
                     ┌──────────────┘     ┌─────────┘
                     ▼                    ▼
              -v profile/.mcp.json    -v $HOST/.claude/projects/<slug>:...:rw
              :CONTAINER_HOME/.mcp.json    -v $HOST/.claude/file-history:...:rw
              -v profile/settings.json     -v $HOST/.claude/tasks:...:rw
              :CONTAINER_HOME/.claude/settings.json  ... (etc.)
                     │
                     └──────────────► podman run ... (harness container)
```

### Recommended Project Structure

```
lib/
├── manifests/
│   ├── claude.yaml      # profile_files + history_dirs for claude harness
│   ├── omp.yaml         # profile_files + history_dirs for omp harness
│   ├── antigravity.yaml # profile_files + history_dirs for antigravity harness
│   ├── opencode.yaml    # profile_files only (history deferred to MNT2-07)
│   ├── gemini.yaml      # profile_files only (history deferred to MNT2-07)
│   └── codex.yaml       # profile_files only (history deferred to MNT2-07)
├── harnessed-manifest-mounts.sh  # new: reads manifests, appends to MOUNT_ARGS
├── harnessed-isolated.sh          # modified
├── harnessed-isolated-config.sh   # unchanged
└── harnessed-mounts.sh            # minor: workdir + project mount for path mirroring
tools/harnessed/
├── emit.py              # modified: .mcp.json + settings.json → profile_dir root
└── assemble.py          # modified: remove fan-out syncer calls + ensure_profile_tree
```

### Pattern 1: YAML Manifest Format

**What:** Each harness has a YAML manifest declaring the two categories of mounts.
**When to use:** Read at launch time to drive all per-harness mount decisions.

```yaml
# lib/manifests/claude.yaml
# Source: CONTEXT.md D-02 / D-03
profile_files:
  - .mcp.json
  - settings.json
history_dirs:
  - projects   # contains per-project slug subdirs; slug managed by path mirroring + mkdir -p
  - file-history
  - tasks
  - session-env
  - todos
```

```yaml
# lib/manifests/omp.yaml
profile_files:
  - .mcp.json    # omp reads Claude-canonical .mcp.json via the bridge
  - settings.json
history_dirs:
  # Mounted as agent/sessions/<omp_slug>/ — slug computed by launcher from relpath
  # See Pitfall 2: omp slug derivation requires HOST relpath, not container HOME-relative
  - agent/sessions  # sub-slug is appended by the manifest-mounts function
```

```yaml
# lib/manifests/antigravity.yaml
profile_files:
  - .mcp.json    # or equivalent per-harness config; see antigravity harness image baking
  - settings.json
history_dirs:
  - .gemini/antigravity-cli/conversations
  - .gemini/antigravity-cli/brain
  - .gemini/antigravity-cli/implicit
```

### Pattern 2: harnessed_manifest_mounts Function

**What:** New bash function in `lib/harnessed-manifest-mounts.sh`. Appends to MOUNT_ARGS.
**When to use:** Called from `harnessed_isolated()` after auth mounts, before pod creation.

```bash
# Source: CONTEXT.md §specifics + home-folder-* research docs
# Usage: harnessed_manifest_mounts "$harness" "$profile_dir" "$project_path" "$relpath"
harnessed_manifest_mounts() {
    local harness="$1" profile_dir="$2" project_path="$3" relpath="$4"
    local manifest="$HARNESSED_DIR/lib/manifests/${harness}.yaml"

    [ -f "$manifest" ] || { print_warning "No manifest for harness: $harness (skipping manifest mounts)"; return 0; }

    # Profile config files: mount each file from profile_dir into CONTAINER_HOME
    local f
    while IFS= read -r f; do
        [ -z "$f" ] && continue
        local src="$profile_dir/$f" dst="$CONTAINER_HOME/.claude/$f"
        # Harness-specific target path override for non-.claude paths goes here
        [ -f "$src" ] && MOUNT_ARGS+=( -v "$src:$dst:ro" ) || \
            print_warning "Profile file not found (stack may need rebuild): $src"
    done < <(yq '.profile_files[]' "$manifest" 2>/dev/null)

    # History dirs: rw-mount from host home to container home
    local host_home="$HOME"
    local container_home="$CONTAINER_HOME"
    while IFS= read -r d; do
        [ -z "$d" ] && continue
        # omp slug handling: agent/sessions → agent/sessions/<slug>
        # See Pitfall 2 for slug derivation
        local host_dir="$host_home/$d" container_dir="$container_home/$d"
        mkdir -p "$host_dir"
        MOUNT_ARGS+=( -v "$host_dir:$container_dir:rw" )
    done < <(yq '.history_dirs[]' "$manifest" 2>/dev/null)
}
```

**Note:** The above is a sketch. See Pitfalls section for omp slug handling and antigravity path details.

### Pattern 3: Assembler Changes (emit.py)

**What:** Move `.mcp.json` and `settings.json` emission from `harness_dir` (`.claude/`) to `profile_dir` root.
**When to use:** Remove the fan-out and the harness subdir creation.

```python
# Source: tools/harnessed/emit.py (VERIFIED: read directly)
# BEFORE (Phase 8 and earlier):
#   write_mcp_json(harness_dir)      → profiles/<stack>/.claude/.mcp.json
#   write_settings_json(harness_dir) → profiles/<stack>/.claude/settings.json
#   ensure_profile_tree(harness_dir) → creates .claude/{skills,commands,...}/
#   syncer.fan(harness_dir)          → copies skills/commands into .claude/

# AFTER (Phase 9):
#   write_mcp_json(profile_dir)      → profiles/<stack>/.mcp.json
#   write_settings_json(profile_dir) → profiles/<stack>/settings.json
#   (no ensure_profile_tree call)
#   (no syncer.fan call)
```

Changes to `assemble.py`:
- Remove the `syncer = LinkSyncer()` + `syncer.add_recipe()` + `syncer.fan()` block
- Remove the `harness_dir` variable (no longer needed)
- Change `emit.write_mcp_json(harness_dir)` → `emit.write_mcp_json(profile_dir)`
- Change `emit.write_settings_json(harness_dir, servers)` → `emit.write_settings_json(profile_dir, servers)`
- Remove `emit.ensure_profile_tree(harness_dir)` call
- Update `AssembleResult` to remove `skills` and `commands` fields (or keep for report-only)

Changes to `emit.py`:
- `write_mcp_json(path)` — `path` is now `profile_dir` not `harness_dir`; `out = path / ".mcp.json"`
- `write_settings_json(path, servers)` — same; `out = path / "settings.json"`
- `ensure_profile_tree()` can be deleted or kept as dead code (remove to keep clean)
- `PROFILE_SUBDIRS` constant can be deleted
- `reset_profile` stays unchanged (wipes and recreates profile_dir)

### Pattern 4: Launcher Changes (harnessed-isolated.sh)

**What:** Seven specific changes to `lib/harnessed-isolated.sh`.

```bash
# CHANGE 1 — D-10: is-built guard (line 64)
# BEFORE:
[ -d "$profile_dir/.claude" ] || { print_error "..."; exit 1; }
# AFTER:
[ -f "$profile_dir/.mcp.json" ] || { print_error "Stack '$stack' has no assembled profile (run: harnessed build $stack)"; exit 1; }

# CHANGE 2 — D-07/MNT2-01: Remove the state dir copy-and-mount block (lines 131-138)
# BEFORE (8 lines):
local state_project="${relpath//'/'/-}"
local run_claude="..."
mkdir -p "$(dirname "$run_claude")"
if [ "$fresh" = "true" ] || [ ! -d "$run_claude" ]; then
    rm -rf "$run_claude"
    cp -a "$profile_dir/.claude" "$run_claude"
fi
MOUNT_ARGS+=( -v "$run_claude:$CONTAINER_HOME/.claude:rw" )
# AFTER (1 call):
harnessed_manifest_mounts "$harness" "$profile_dir" "$project_path" "$relpath"

# CHANGE 3 — MNT2-02: Update claude attach command's mcp-config path
# BEFORE:
local mcp_cfg="$CONTAINER_HOME/.claude/.mcp.json"
# AFTER:
local mcp_cfg="$CONTAINER_HOME/.mcp.json"

# CHANGE 4 — MNT2-02: Path mirroring workdir in new-pod attach block
# BEFORE (all harnesses in the exec -it block):
-w "$CONTAINER_HOME/$relpath"
# AFTER:
-w "$project_path"

# CHANGE 5 — MNT2-02: Path mirroring workdir in re-attach block (lines 88-106)
# Same: -w "$CONTAINER_HOME/$relpath" → -w "$project_path" for all harness branches

# CHANGE 6 — Source new manifest-mounts helper
# Add near the top of harnessed_isolated() where other lib files are sourced:
. "$HARNESSED_DIR/lib/harnessed-manifest-mounts.sh"
```

### Pattern 5: Path Mirroring + Project Mount (MNT2-02)

**What:** The project volume mount in `harnessed-mounts.sh` currently mounts at `$CONTAINER_HOME/$relpath`. For path mirroring, the project needs to be accessible at its host absolute path inside the container.

The CONTEXT states `harnessed-mounts.sh` is "not changing in Phase 9". Two viable approaches:

**Approach A (minimal harnessed-mounts.sh change):** Update the project mount line and workdir in `harnessed_host_integration_mounts` to use host absolute path. This is the cleanest but touches the shared mount helper.

**Approach B (override in harnessed-manifest-mounts.sh):** After `harnessed_host_integration_mounts` sets the project mount, add a SECOND `podman run -v "$project_path:$project_path"` and then override workdir with `-w "$project_path"`. Since `podman run` accepts multiple `-w` flags and the last wins, this avoids changing harnessed-mounts.sh but adds a redundant bind.

The CONTEXT's Specifics note says: "the current `-w "$CONTAINER_HOME/$relpath"` in `harnessed-isolated.sh` becomes `-w "$project_path"`". This suggests the workdir fix is in harnessed-isolated.sh, not harnessed-mounts.sh. The project mount change (so the path is accessible) is the open question — flag for planner.

### Anti-Patterns to Avoid

- **Mounting history dirs before `mkdir -p`:** If the host dir doesn't exist yet (new project), podman will create it as a root-owned dir (DooD risk). Always `mkdir -p "$host_dir"` before the bind.
- **Mounting `~/.claude/` whole for history:** Defeats MNT2-01. Mount individual subdirs only.
- **Mounting `~/.omp/agent.db`:** Contains auth credentials — explicitly forbidden by MNT2-04 and omp research doc.
- **Mounting `~/.gemini/antigravity-cli/antigravity-oauth-token`:** Auth token — excluded by construction when mounting specific named subdirs.
- **Writing `.claude/` tree to profiles in assembler:** Defeats MNT2-01 — skills/commands must be baked into harness image at build time, not written to profile.
- **Hard-coded `-v` flags in launcher:** Defeats MNT2-06 — all paths must come from manifests.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| YAML parsing in bash | Custom awk/sed YAML parser | `yq '.field[]' file.yaml` | yq already in base image; handles arrays cleanly |
| Slug computation for omp | New slug algorithm | Reuse `$relpath` from `project_relpath()` | relpath = HOST $HOME-relative path; already computed; omp slug = `-${relpath//\//-}` |
| Container HOME resolution | Env var inspection | `$CONTAINER_HOME` constant in harnessed-common.sh | Already set to `/home/harnessed`; consistent across all launchers |

---

## Common Pitfalls

### Pitfall 1: .mcp.json Target Path in Claude Attach Command

**What goes wrong:** After Phase 9, `.mcp.json` is mounted at `$CONTAINER_HOME/.mcp.json` (profile root, not inside `.claude/`). The existing attach command for claude uses `--mcp-config '$mcp_cfg'` where `mcp_cfg="$CONTAINER_HOME/.claude/.mcp.json"`. If this isn't updated, claude will fail to find its MCP config.

**Why it happens:** The emit target path changes from `harness_dir/.mcp.json` to `profile_dir/.mcp.json`, which means the container-side mount target must also change.

**How to avoid:** Update `mcp_cfg` assignment to `"$CONTAINER_HOME/.mcp.json"` (or wherever the manifest-mounts function puts it). Also update the re-attach path.

**Warning signs:** claude session starts but MCP tools are unavailable; `claude mcp list` shows no servers.

### Pitfall 2: omp Slug Derivation — Container HOME vs Host HOME

**What goes wrong:** `CONTAINER_HOME=/home/harnessed`. omp derives the session slug by stripping `$HOME` from the project path. Inside the container with path mirroring, the project is at `/home/mcrowe/Programming/…` but container `$HOME=/home/harnessed`. omp cannot strip `/home/harnessed` from `/home/mcrowe/…` so it falls back to the absolute path slug `-home-mcrowe-Programming-Personal-code-container`. On the HOST, omp uses `$HOME=/home/mcrowe` and produces slug `-Programming-Personal-code-container`. These don't match.

**Why it happens:** `CONTAINER_HOME` is a custom non-matching path, not the host HOME.

**How to avoid:** In `harnessed_manifest_mounts`, compute the omp slug using the HOST `$relpath` (already computed by `project_relpath`):
```bash
# relpath = "Programming/Personal/code-container" (HOME-relative, no leading slash)
omp_slug="-${relpath//\//'-'}"   # → -Programming-Personal-code-container
host_omp_sessions="$HOME/.omp/agent/sessions/$omp_slug"
container_omp_sessions="$CONTAINER_HOME/.omp/agent/sessions/$omp_slug"
mkdir -p "$host_omp_sessions"
MOUNT_ARGS+=( -v "$host_omp_sessions:$container_omp_sessions:rw" )
```

**Warning signs:** New sessions appear at a different slug than expected; host `~/.omp/agent/sessions/` shows `-home-mcrowe-…` entries instead of `-Programming-…`.

### Pitfall 3: Claude Projects Slug and Path Mirroring

**What goes wrong:** Claude derives the project slug from the absolute working directory. If path mirroring is incomplete (workdir changed but project isn't mounted at host absolute path), the container may not find the project at `$project_path` even though workdir is set to it.

**Why it happens:** `-w $project_path` sets the workdir, but if the project is only mounted at `$CONTAINER_HOME/$relpath` (old path), accessing files at `$project_path` inside the container fails.

**How to avoid:** The project must be bind-mounted at BOTH the old path (for backward compat with other tools) OR changed to same-path → same-path: `-v "$project_path:$project_path"`. The planner must decide whether to change `harnessed_host_integration_mounts` or add a second bind in `harnessed_manifest_mounts`. The research doc for claude says path mirroring makes "DooD `-v $PWD:$PWD` works with no translation" — this implies the mount target equals the source.

**Warning signs:** `claude` starts at the right workdir but file tools fail with "no such file"; project slug differs from expected.

### Pitfall 4: Settings.json Container Path for Non-Claude Harnesses

**What goes wrong:** For harnesses like `omp` and `opencode`, `settings.json` belongs inside `~/.claude/` (they consume the Claude-canonical profile). For `gemini`, `antigravity`, and `codex`, the `settings.json` from the profile may NOT be what the harness reads at all (their native config is baked into the image).

**Why it happens:** D-03 says "launcher derives harness-specific container target paths from its own harness knowledge". The manifest lists filenames only; target paths differ by harness.

**How to avoid:** In `harnessed_manifest_mounts`, branch on `$harness` to set the correct container target:
- `claude`, `omp`, `opencode`: target is `$CONTAINER_HOME/.claude/$f`
- `gemini`, `antigravity`, `codex`: `.mcp.json` and `settings.json` may be irrelevant (baked in image) — skip or mount to a non-conflicting location

**Warning signs:** A gemini or codex harness overwrites its image-baked config with the profile's Claude-specific settings, breaking MCP wiring.

### Pitfall 5: Profile Rebuild Required After Assembler Change

**What goes wrong:** After the assembler change, `profiles/<stack>/.mcp.json` doesn't exist yet (old profiles only have `.claude/.mcp.json`). The new launcher guard `[ -f "$profile_dir/.mcp.json" ]` correctly rejects these, but if the assembler isn't updated first the rebuilt profile still writes to `.claude/`.

**Why it happens:** Two-step change; assembler and launcher must both be updated in a consistent order.

**How to avoid:** Update the assembler first (emit to profile root), rebuild all profiles (`harnessed build <stack>`), THEN update the launcher guard and mount logic. The planner should order tasks accordingly.

**Warning signs:** `[ -f "$profile_dir/.mcp.json" ]` guard fires for all stacks after launcher update.

### Pitfall 6: antigravity History Dirs Are Under ~/.gemini/antigravity-cli, NOT ~/.gemini

**What goes wrong:** Mounting `$HOME/.gemini/` wholesale for antigravity history would include `oauth_creds.json` (gemini-cli OAuth token), `history/` (gemini-cli chats), and other gemini-cli state — exposing sibling harness data to the antigravity container.

**Why it happens:** antigravity nests its home under `~/.gemini/antigravity-cli/` but the parent `~/.gemini/` belongs to gemini-cli (different tool).

**How to avoid:** Mount ONLY the three specific subdirs under `~/.gemini/antigravity-cli/`:
```
$HOME/.gemini/antigravity-cli/conversations  →  $CONTAINER_HOME/.gemini/antigravity-cli/conversations
$HOME/.gemini/antigravity-cli/brain          →  $CONTAINER_HOME/.gemini/antigravity-cli/brain
$HOME/.gemini/antigravity-cli/implicit       →  $CONTAINER_HOME/.gemini/antigravity-cli/implicit
```
Never mount `~/.gemini/antigravity-cli/antigravity-oauth-token` or parent `~/.gemini/`.

---

## Code Examples

### yq array iteration in bash [VERIFIED: codebase, yq present in image]

```bash
# Read all profile_files from a manifest
while IFS= read -r f; do
    [ -z "$f" ] && continue
    echo "file: $f"
done < <(yq '.profile_files[]' "$HARNESSED_DIR/lib/manifests/claude.yaml" 2>/dev/null)
```

### Existing MOUNT_ARGS append pattern [VERIFIED: read lib/harnessed-mounts.sh directly]

```bash
# All mount code in the harnessed codebase follows this pattern:
MOUNT_ARGS+=( -v "$src:$dst:ro" )
MOUNT_ARGS+=( -v "$src_rw:$dst_rw:rw" )
```

### project_relpath result → omp slug [VERIFIED: read harnessed-common.sh + omp research doc]

```bash
# relpath is computed by project_relpath() and is the HOST $HOME-relative path
# e.g. for /home/mcrowe/Programming/Personal/code-container → "Programming/Personal/code-container"
omp_slug="-${relpath//\//'-'}"
# → "-Programming-Personal-code-container" — matches host omp sessions dir
```

### Current copy-and-mount block to be replaced (lines 131-138, harnessed-isolated.sh) [VERIFIED: read directly]

```bash
# REMOVE this entire block in Phase 9:
local state_project="${relpath//'/'/-}"
local run_claude="${XDG_STATE_HOME:-$HOME/.local/state}/harnessed/$state_project/$stack/.claude"
mkdir -p "$(dirname "$run_claude")"
if [ "$fresh" = "true" ] || [ ! -d "$run_claude" ]; then
    rm -rf "$run_claude"
    cp -a "$profile_dir/.claude" "$run_claude"
fi
MOUNT_ARGS+=( -v "$run_claude:$CONTAINER_HOME/.claude:rw" )
# REPLACE with:
harnessed_manifest_mounts "$harness" "$profile_dir" "$project_path" "$relpath"
```

### Current assembler fan-out flow to modify (assemble.py) [VERIFIED: read directly]

```python
# REMOVE these lines from assemble():
syncer = LinkSyncer()
for recipe in recipes:
    syncer.add_recipe(recipe)
# ...
harness_dir = profile_dir / stack.harness_config_dir
emit.ensure_profile_tree(harness_dir)
syncer.fan(harness_dir)
emit.write_mcp_json(harness_dir)
emit.write_settings_json(harness_dir, servers)

# REPLACE with:
emit.write_mcp_json(profile_dir)
emit.write_settings_json(profile_dir, servers)
```

---

## Runtime State Inventory

| Category | Items Found | Action Required |
|----------|-------------|-----------------|
| Stored data | `~/.local/state/harnessed/<proj>/<stack>/.claude` — per-instance state dirs (the copy-on-start dirs, STA-01 pattern) | Eliminated by Phase 9; existing dirs become stale but are harmless (no migration needed — just stop creating new ones) |
| Live service config | None — no external services involved in mount logic | None |
| OS-registered state | None | None |
| Secrets/env vars | None — `.mcp.json`/`settings.json` contain no secrets; credentials handled by existing auth layer | None |
| Build artifacts | `profiles/<stack>/.claude/` trees in all built stacks — stale after assembler change | Eliminated on next `harnessed build <stack>`; no explicit cleanup needed (assembler calls `emit.reset_profile()` which wipes and recreates profile_dir) |

**profiles that need rebuild after Phase 9:**

Current profiles on disk: `tracer-time`, `ping-time`, `gstack-time`, `antigravity-time`, `claude-multi`, `codex-time`, `gemini-time`, `omp-time`, `opencode-time` (and others in profiles/ dir). None have a `.claude/` tree currently (they appear to have been assembled without the `syncer.fan` step or with recipes that produced no skills). All need rebuild to get `.mcp.json` and `settings.json` at profile root. [VERIFIED: read profiles/tracer-time/ and profiles/gstack-time/ directory listings]

---

## Open Questions

1. **Project volume mount for path mirroring (MNT2-02)**
   - What we know: workdir must change to `$project_path`; project mount currently at `$CONTAINER_HOME/$relpath`
   - What's unclear: whether to add `-v "$project_path:$project_path"` in harnessed-manifest-mounts OR change harnessed-mounts.sh (which CONTEXT says "not changing")
   - Recommendation: Add the same-path bind in `harnessed_manifest_mounts` as an additional mount. The old mount at `$CONTAINER_HOME/$relpath` can remain (harmless; some harness-internal tools may use the old path). Workdir override appended to MOUNT_ARGS after `harnessed_host_integration_mounts` call.

2. **Container target path for .mcp.json (MNT2-01)**
   - What we know: Claude uses `--mcp-config` to specify the `.mcp.json` path; it does NOT auto-read `~/.claude/.mcp.json` in isolated mode; it reads whatever file is passed via `--mcp-config`
   - What's unclear: The optimal container target for `.mcp.json` when mounted from `profiles/<stack>/.mcp.json`
   - Recommendation: Mount to `$CONTAINER_HOME/.mcp.json` (profile root equivalent), update `mcp_cfg` to `"$CONTAINER_HOME/.mcp.json"`. For harnesses that don't use `--mcp-config` (omp, opencode, etc.), the mount can still target `$CONTAINER_HOME/.claude/.mcp.json` to match their expected path — branch on harness in the manifest-mounts function.

3. **antigravity container HOME for history paths**
   - What we know: Host path is `$HOME/.gemini/antigravity-cli/conversations/`; container HOME is `/home/harnessed`
   - What's unclear: Whether antigravity inside the container uses `$HOME/.gemini/antigravity-cli` or a fixed path
   - Recommendation: Mount `$HOME/.gemini/antigravity-cli/conversations` → `$CONTAINER_HOME/.gemini/antigravity-cli/conversations` (mirroring container HOME convention). If antigravity keys off real `$HOME` or a fixed path, adjust.

4. **omp blobs/ mount (optional per MNT2-04)**
   - What we know: `agent/blobs/` holds pasted images referenced by transcripts; collision-free (content-addressed)
   - What's unclear: Whether to ship blobs/ mount enabled in Phase 9
   - Recommendation: Include in omp manifest but make it optional via a flag or comment it out — blobs/ is "optionally" surfaced per requirement text.

5. **Guarded teardown for history.jsonl / history.db / antigravity cache**
   - What we know: These "guarded teardown merge" operations (MNT2-03/04/05) ship disabled initially
   - What's unclear: Whether Phase 9 requires implementing disabled stubs or just documenting the future path
   - Recommendation: Phase 9 only implements the rw bind-mount layer. Teardown merges are explicitly noted as "ships disabled" in the requirements. Implement no teardown logic in Phase 9; add TODO comments.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | bash integration tests (UAT pattern, tools/uat/) |
| Config file | tools/uat/uat-common.sh + per-phase test scripts |
| Quick run command | `tools/uat/phase-09.sh` (to be created in Wave 0) |
| Full suite command | `tools/uat/run-uat.sh` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MNT2-01 | gstack-time shows gstack skills loaded | Integration (headless) | `HARNESSED_HEADLESS=true harnessed gstack-time && harnessed test gstack-time` | Wave 0 |
| MNT2-01 | profiles/gstack-time/ has no .claude/ tree | Smoke | `! test -d profiles/gstack-time/.claude` | Wave 0 |
| MNT2-02 | Container workdir == host project path | Integration | `podman exec <instance> pwd` == `$(pwd)` | Wave 0 |
| MNT2-03 | New claude session creates host-side history entries | Integration (headless) | Assert `~/.claude/projects/<slug>/` has new files | Wave 0 |
| MNT2-04 | New omp session creates host-side session files | Integration (headless) | Assert `~/.omp/agent/sessions/<slug>/` has new files | Wave 0 |
| MNT2-05 | New antigravity session creates host-side conversation DB | Integration (headless) | Assert `~/.gemini/antigravity-cli/conversations/` has new .db | Wave 0 |
| MNT2-06 | Changing a path is a one-line manifest edit | Lint/smoke | `test -f lib/manifests/claude.yaml` etc. | Wave 0 |

### Wave 0 Gaps

- [ ] `tools/uat/phase-09.sh` — covers all MNT2-01 through MNT2-06 scenarios
- [ ] `lib/manifests/claude.yaml` — Phase 9 manifest (must exist before tests run)
- [ ] `lib/manifests/omp.yaml`
- [ ] `lib/manifests/antigravity.yaml`
- [ ] `lib/manifests/opencode.yaml` (profile_files only)
- [ ] `lib/manifests/gemini.yaml` (profile_files only)
- [ ] `lib/manifests/codex.yaml` (profile_files only)
- [ ] `lib/harnessed-manifest-mounts.sh`

---

## Security Domain

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | Auth layer unchanged; credentials handled by existing harnessed-isolated-config.sh |
| V3 Session Management | No | Container lifecycle unchanged |
| V4 Access Control | Yes | History dirs mounted rw — only per-project subdirs, never credentials files |
| V5 Input Validation | Yes | yq manifest parsing — malformed YAML → no mounts (safe default) |
| V6 Cryptography | No | No crypto changes |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Auth credential exposure in history mount | Information Disclosure | Specific file/dir exclusions in manifest; never mount agent.db, antigravity-oauth-token, .credentials.json |
| Slug mismatch causing wrong project data mount | Tampering | Slug computed from HOST relpath (verified same algorithm as omp) |
| Whole-dir mount exposing sibling harness data | Information Disclosure | Manifests list specific subdirs only; parent dirs never mounted |
| Stale .claude/ tree in profile confusing guard | Elevation | New guard checks .mcp.json at profile root; rebuild enforced (D-09) |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | omp slug derivation uses `$HOME` strip + `/`→`-` map | Pitfall 2 | omp sessions surfaced to wrong dir on host |
| A2 | Container target for antigravity history is `$CONTAINER_HOME/.gemini/antigravity-cli/…` | Open Question 3 | Mounts target wrong path in container; history not written |
| A3 | `podman run` last `-w` flag wins when specified twice | Pattern 4 Approach B | Workdir stays at old CONTAINER_HOME path; slug mismatch |
| A4 | antigravity inside the container reads `$HOME/.gemini/antigravity-cli` (respects $HOME env) | Open Question 3 | History not written to mounted path |

---

## Sources

### Primary (HIGH confidence — verified by direct code reading)

- `lib/harnessed-isolated.sh` — lines 61-138: is-built guard, copy-and-mount block, MOUNT_ARGS pattern
- `lib/harnessed-mounts.sh` — lines 15-20: workdir and project volume mount pattern
- `lib/harnessed-isolated-config.sh` — per-harness auth mount switch
- `lib/harnessed-common.sh` — `CONTAINER_HOME="/home/harnessed"` definition
- `tools/harnessed/assemble.py` — full assembly flow including syncer.fan() and emit targets
- `tools/harnessed/emit.py` — write_mcp_json, write_settings_json, PROFILE_SUBDIRS, ensure_profile_tree
- `tools/harnessed/schema.py` — HARNESS_CONFIG_DIR mapping (all → ".claude")
- `docs/research/home-folder-claude-requirements.md` — Claude history paths, keying hazards, slug derivation
- `docs/research/home-folder-omp-requirements.md` — omp slug ($HOME-relative), never-mount agent.db, WAL risk
- `docs/research/home-folder-antigravity-requirements.md` — antigravity-cli subdir structure, per-conversation UUIDs
- `docs/research/home-folder-harness-history-overview.md` — cross-harness invariants, path mirroring rationale
- `.planning/phases/09-surgical-profile-mount-history-surfacing/09-CONTEXT.md` — all locked decisions D-01..D-11

### Secondary (MEDIUM confidence)

- `profiles/tracer-time/`, `profiles/gstack-time/` directory listings — confirmed no .claude/ tree in current built profiles
- `.planning/REQUIREMENTS.md` §MNT2-01..MNT2-06 — requirement text verbatim

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies; all tools verified present in codebase
- Architecture: HIGH — verified by reading all relevant source files directly
- Pitfalls: HIGH for pitfalls 1-4 (derived from code); MEDIUM for pitfall 5/6 (derived from research docs written on a different machine)
- Open questions: flagged honestly; the planner must decide on workdir/project-mount strategy and container target paths

**Research date:** 2026-06-24
**Valid until:** Until a Claude Code or omp update changes their history storage layout (check `docs/research/` docs for update dates)
