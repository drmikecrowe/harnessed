# Phase 9: Surgical Profile Mount + History Surfacing — Pattern Map

**Mapped:** 2026-06-24
**Files analyzed:** 11
**Analogs found:** 11 / 11

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `lib/manifests/claude.yaml` | config | transform | `stacks/tracer-time/stack.yaml` | role-match |
| `lib/manifests/omp.yaml` | config | transform | `stacks/tracer-time/stack.yaml` | role-match |
| `lib/manifests/antigravity.yaml` | config | transform | `stacks/tracer-time/stack.yaml` | role-match |
| `lib/manifests/opencode.yaml` | config | transform | `stacks/tracer-time/stack.yaml` | role-match |
| `lib/manifests/gemini.yaml` | config | transform | `stacks/tracer-time/stack.yaml` | role-match |
| `lib/manifests/codex.yaml` | config | transform | `stacks/tracer-time/stack.yaml` | role-match |
| `lib/harnessed-manifest-mounts.sh` | utility | request-response | `lib/harnessed-mounts.sh` | exact |
| `lib/harnessed-isolated.sh` | utility | request-response | itself (modification) | exact |
| `tools/harnessed/assemble.py` | service | transform | itself (modification) | exact |
| `tools/harnessed/emit.py` | utility | transform | itself (modification) | exact |
| `tools/uat/phase-09.sh` | test | request-response | `tools/uat/phase-04.sh` | exact |

---

## Pattern Assignments

### `lib/manifests/claude.yaml` (config, transform)

**Analog:** `stacks/tracer-time/stack.yaml` — same YAML config pattern; two-section manifest.

**YAML format pattern** (from D-02/D-03 and RESEARCH Pattern 1):
```yaml
# lib/manifests/claude.yaml
profile_files:
  - .mcp.json
  - settings.json
history_dirs:
  - .claude/projects
  - .claude/file-history
  - .claude/tasks
  - .claude/session-env
  - .claude/todos
```
**Note:** paths in `history_dirs` are relative to `$HOME`; the launcher mounts `$HOME/<d>` → `$CONTAINER_HOME/<d>`. Claude history lives under `.claude/`, so the `.claude/` prefix is required here.

**Stack YAML shape** (`stacks/tracer-time/stack.yaml` lines 1-7):
```yaml
name: tracer-time
harness: claude
recipes: [time]
```
Copy: simple flat YAML, comment header describing purpose, no nesting beyond what is needed.

---

### `lib/manifests/omp.yaml` (config, transform)

**Analog:** `stacks/tracer-time/stack.yaml`

**Pattern:**
```yaml
# lib/manifests/omp.yaml
# omp reads Claude-canonical .mcp.json via the claude-hooks-bridge.
# omp slug for history: "-${relpath//\//-}" (HOST $HOME-relative, NOT container HOME).
# omp history mounting is handled per-slug in harnessed_manifest_mounts() — NOT via the
# generic history_dirs loop — to avoid exposing ALL projects' sessions to the container.
# See Pitfall 2 in RESEARCH.md.
profile_files:
  - .mcp.json
  - settings.json
history_dirs: []  # omp slug bind is in harnessed_manifest_mounts bash function, not here
```
**Note:** `history_dirs` MUST be empty for omp. The generic loop would mount `~/.omp/agent/sessions/` (all projects) to the container, violating MNT2-04's per-slug isolation. The per-slug bind is hardcoded in the `if [ "$harness" = "omp" ]` block of `harnessed_manifest_mounts()`.

---

### `lib/manifests/antigravity.yaml` (config, transform)

**Analog:** `stacks/tracer-time/stack.yaml`

**Pattern:**
```yaml
# lib/manifests/antigravity.yaml
# antigravity (agy) nests history under ~/.gemini/antigravity-cli/ — NOT ~/.gemini/
# (see Pitfall 6 in RESEARCH.md: never mount parent ~/.gemini/).
profile_files:
  - .mcp.json
  - settings.json
history_dirs:
  - .gemini/antigravity-cli/conversations
  - .gemini/antigravity-cli/brain
  - .gemini/antigravity-cli/implicit
```

---

### `lib/manifests/opencode.yaml` (config, transform)

**Pattern:**
```yaml
# lib/manifests/opencode.yaml
# opencode: profile_files only; history surfacing deferred (MNT2-07).
profile_files:
  - .mcp.json
  - settings.json
history_dirs: []
```

---

### `lib/manifests/gemini.yaml` and `lib/manifests/codex.yaml` (config, transform)

**Pattern:** Same shape as `opencode.yaml` — `profile_files` only, empty `history_dirs`. Note: for `gemini` and `codex`, the profile `.mcp.json`/`settings.json` may not be mounted (launcher branches on `$harness` per D-03/Pitfall 4). The manifest lists the files; the launcher decides whether and where to mount them.

---

### `lib/harnessed-manifest-mounts.sh` (utility, request-response)

**Analog:** `lib/harnessed-mounts.sh` — exact match: same role (bash helper that appends `-v` flags to `MOUNT_ARGS`), same caller convention, same file shebang and comment style.

**Shebang + header pattern** (`lib/harnessed-mounts.sh` lines 1-11):
```bash
#!/usr/bin/env bash
# harnessed — §4a host-integration mount layer (operational: auth/signing/agents/firewall).
# Shared by EVERY stack. Host-native: the launcher runs on the host, so sources are real host
# paths ($HOME, the project path) and targets live under $CONTAINER_HOME. Appends podman/docker
# run args to the MOUNT_ARGS array (the caller declares `MOUNT_ARGS=()`).
```

**MOUNT_ARGS append pattern** (`lib/harnessed-mounts.sh` lines 16-18):
```bash
MOUNT_ARGS+=( $(rt_userns_args) --cap-add NET_ADMIN -e "TERM=xterm-256color" )
MOUNT_ARGS+=( -w "$CONTAINER_HOME/$relpath" )
MOUNT_ARGS+=( -v "$project_path:$CONTAINER_HOME/$relpath" )
```

**Conditional mount pattern** (`lib/harnessed-mounts.sh` lines 24-28):
```bash
local op_agent="$HOME/.1password/agent.sock"
if [ -S "$op_agent" ]; then
    MOUNT_ARGS+=( -v "$op_agent:$CONTAINER_HOME/.1password/agent.sock" )
    MOUNT_ARGS+=( -e "SSH_AUTH_SOCK=$CONTAINER_HOME/.1password/agent.sock" )
fi
```

**Warning pattern** (`lib/harnessed-isolated-config.sh` lines 38-40):
```bash
print_warning "No host opencode credential at $oc_auth — isolated opencode auth will be unseeded ..."
```

**Core function shape for new `lib/harnessed-manifest-mounts.sh`** (RESEARCH Pattern 2):
```bash
#!/usr/bin/env bash
# harnessed — data-driven mount helper for Phase 9 surgical profile mount + history surfacing.
# Reads lib/manifests/<harness>.yaml and appends -v flags to MOUNT_ARGS.
# Usage: harnessed_manifest_mounts "$harness" "$profile_dir" "$project_path" "$relpath"

harnessed_manifest_mounts() {
    local harness="$1" profile_dir="$2" project_path="$3" relpath="$4"
    local manifest="$HARNESSED_DIR/lib/manifests/${harness}.yaml"

    [ -f "$manifest" ] || { print_warning "No manifest for harness: $harness (skipping manifest mounts)"; return 0; }

    # Profile config files — mount each from profile_dir into the container.
    # Target path is harness-aware: claude/omp/opencode → ~/.claude/<f>
    # gemini/antigravity/codex → config is baked in image (skip or mount non-conflicting).
    local f
    while IFS= read -r f; do
        [ -z "$f" ] && continue
        local src="$profile_dir/$f"
        local dst
        case "$harness" in
            claude|omp|opencode) dst="$CONTAINER_HOME/.claude/$f" ;;
            *) continue ;;   # baked in image — do not overwrite
        esac
        if [ -f "$src" ]; then
            MOUNT_ARGS+=( -v "$src:$dst:ro" )
        else
            print_warning "Profile file not found (stack may need rebuild): $src"
        fi
    done < <(yq '.profile_files[]' "$manifest" 2>/dev/null)

    # History dirs — rw-mount from host $HOME to container $CONTAINER_HOME.
    # mkdir -p before bind to avoid root-owned dir creation (DooD pitfall).
    local d
    while IFS= read -r d; do
        [ -z "$d" ] && continue
        local host_dir="$HOME/$d"
        local container_dir="$CONTAINER_HOME/$d"
        mkdir -p "$host_dir"
        MOUNT_ARGS+=( -v "$host_dir:$container_dir:rw" )
    done < <(yq '.history_dirs[]' "$manifest" 2>/dev/null)

    # omp: history surfaced at per-project slug subdir (Pitfall 2 — slug must use HOST relpath).
    # relpath = PROJECT_HOME-relative, e.g. "Programming/Personal/code-container"
    if [ "$harness" = "omp" ]; then
        local omp_slug="-${relpath//\//'-'}"
        local host_omp="$HOME/.omp/agent/sessions/$omp_slug"
        local ctr_omp="$CONTAINER_HOME/.omp/agent/sessions/$omp_slug"
        mkdir -p "$host_omp"
        MOUNT_ARGS+=( -v "$host_omp:$ctr_omp:rw" )
    fi

    # MNT2-02 path mirroring: project must also be accessible at its host absolute path.
    MOUNT_ARGS+=( -v "$project_path:$project_path" )
}
```

**yq iteration pattern** (RESEARCH Code Examples):
```bash
while IFS= read -r f; do
    [ -z "$f" ] && continue
    echo "file: $f"
done < <(yq '.profile_files[]' "$HARNESSED_DIR/lib/manifests/claude.yaml" 2>/dev/null)
```

---

### `lib/harnessed-isolated.sh` (utility, request-response — modification)

**Analog:** itself. Seven surgical changes; all other lines unchanged.

**Source block (lines 57-59) — sourcing pattern to copy for new helper:**
```bash
. "$HARNESSED_DIR/lib/harnessed-mounts.sh"
. "$HARNESSED_DIR/lib/harnessed-isolated-config.sh"
. "$HARNESSED_DIR/lib/harnessed-services.sh"
```
Add: `. "$HARNESSED_DIR/lib/harnessed-manifest-mounts.sh"` after line 59.

**Change 1 — is-built guard (line 64):**
```bash
# BEFORE:
[ -d "$profile_dir/.claude" ] || {
    print_error "Stack '$stack' has no assembled profile (run: harnessed build $stack)"; exit 1; }
# AFTER:
[ -f "$profile_dir/.mcp.json" ] || {
    print_error "Stack '$stack' has no assembled profile (run: harnessed build $stack)"; exit 1; }
```

**Change 2 — replace whole-dir copy-and-mount block (lines 131-138):**
```bash
# REMOVE lines 131-138:
local state_project="${relpath//'/'/-}"
local run_claude="${XDG_STATE_HOME:-$HOME/.local/state}/harnessed/$state_project/$stack/.claude"
mkdir -p "$(dirname "$run_claude")"
if [ "$fresh" = "true" ] || [ ! -d "$run_claude" ]; then
    rm -rf "$run_claude"
    cp -a "$profile_dir/.claude" "$run_claude"
fi
MOUNT_ARGS+=( -v "$run_claude:$CONTAINER_HOME/.claude:rw" )

# REPLACE WITH (one call):
harnessed_manifest_mounts "$harness" "$profile_dir" "$project_path" "$relpath"
```

**Change 3 — mcp_cfg path (line 240):**
```bash
# BEFORE:
local mcp_cfg="$CONTAINER_HOME/.claude/.mcp.json"
# AFTER:
local mcp_cfg="$CONTAINER_HOME/.mcp.json"
```

**Changes 4 and 5 — workdir in both exec blocks (re-attach lines 89-106 and new-pod attach lines 242-269):**
```bash
# BEFORE (every harness branch):
-w "$CONTAINER_HOME/$relpath"
# AFTER:
-w "$project_path"
```

**Per-harness exec branch pattern** (`lib/harnessed-isolated.sh` lines 88-109):
```bash
if [ "$harness" = "omp" ]; then
    "$CONTAINER_RUNTIME" exec -it -e "TERM=xterm-256color" -w "$CONTAINER_HOME/$relpath" "$instance" \
        bash -l -c "$mise_init && omp --profile \"$instance\""
elif [ "$harness" = "opencode" ]; then
    ...
else
    "$CONTAINER_RUNTIME" exec -it -e "TERM=xterm-256color" -w "$CONTAINER_HOME/$relpath" "$instance" \
        bash -l -c "$mise_init && claude"
fi
```

---

### `tools/harnessed/assemble.py` (service, transform — modification)

**Analog:** itself. Remove fan-out block; redirect emit targets.

**Imports pattern** (`tools/harnessed/assemble.py` lines 14-32): unchanged — keep all imports as-is.

**Fan-out block to REMOVE** (`tools/harnessed/assemble.py` lines 100-113):
```python
# REMOVE these 4 lines and the syncer reference:
syncer = LinkSyncer()
for recipe in recipes:
    syncer.add_recipe(recipe)
# ...
harness_dir = profile_dir / stack.harness_config_dir
emit.ensure_profile_tree(harness_dir)
syncer.fan(harness_dir)
emit.write_mcp_json(harness_dir)
emit.write_settings_json(harness_dir, servers)
```

**REPLACE WITH** (RESEARCH Pattern 3):
```python
emit.write_mcp_json(profile_dir)
emit.write_settings_json(profile_dir, servers)
```

**`AssembleResult` dataclass** (`tools/harnessed/assemble.py` lines 36-43): remove `skills` and `commands` fields (or keep as empty for backward compat with CLI display). The `syncer` import from `.synclinks` can be removed.

**Return value pattern** (`tools/harnessed/assemble.py` lines 120-128):
```python
return AssembleResult(
    stack=stack,
    recipes=recipes,
    profile_dir=profile_dir,
    servers=servers,
    baked=baked,
    skills=sorted(syncer.skills),   # REMOVE or keep empty
    commands=sorted(syncer.commands), # REMOVE or keep empty
)
```

---

### `tools/harnessed/emit.py` (utility, transform — modification)

**Analog:** itself. Two function signatures change; two functions deleted.

**`write_mcp_json` signature change** (`tools/harnessed/emit.py` lines 51-61):
```python
# BEFORE: parameter name is `harness_dir`, path target is harness_dir / ".mcp.json"
def write_mcp_json(harness_dir: Path) -> Path:
    out = harness_dir / ".mcp.json"

# AFTER: rename parameter to `profile_dir` (or keep name, change call site in assemble.py).
# The function body is UNCHANGED — only the caller now passes profile_dir instead of harness_dir.
def write_mcp_json(profile_dir: Path) -> Path:
    out = profile_dir / ".mcp.json"
    _write_json(out, {"mcpServers": {HATAGO_MCP_KEY: {"type": "http", "url": HATAGO_ENDPOINT}}})
    return out
```

**`write_settings_json` signature change** (`tools/harnessed/emit.py` lines 64-77):
```python
# Same rename: harness_dir → profile_dir; function body unchanged.
def write_settings_json(profile_dir: Path, servers: list[McpServer]) -> Path:
    ...
    out = profile_dir / "settings.json"
```

**Functions to DELETE** (`tools/harnessed/emit.py` lines 40-43, 30):
```python
# DELETE:
PROFILE_SUBDIRS = ("skills", "commands", "agents", "hooks", "rules")

def ensure_profile_tree(harness_dir: Path) -> None:
    """Create the harness-native subdir skeleton ..."""
    for sub in PROFILE_SUBDIRS:
        (harness_dir / sub).mkdir(parents=True, exist_ok=True)
```

**`_write_json` helper** (lines 46-48) — keep unchanged:
```python
def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
```

**`reset_profile` function** (lines 33-37) — keep unchanged:
```python
def reset_profile(profile_dir: Path) -> None:
    """Wipe and recreate the profile dir so emission is fully reproducible."""
    if profile_dir.exists():
        shutil.rmtree(profile_dir)
    profile_dir.mkdir(parents=True)
```

---

### `tools/uat/phase-09.sh` (test, request-response)

**Analog:** `tools/uat/phase-04.sh` — exact match: same test function naming convention, same AAA pattern, same `run_test` + `uat_run_phase` entrypoint.

**Shebang + header pattern** (`tools/uat/phase-04.sh` lines 1-12):
```bash
#!/usr/bin/env bash
# phase-04.sh — UAT suite for Phase 4 (shared services + recipe breadth + full CLI).
#
# Sourced by run-uat.sh (after uat-common.sh). Defines test_<id> functions and a
# uat_run_phase entrypoint. Every test follows Arrange → Act → Assert (AAA).
```

**Test function pattern** (`tools/uat/phase-04.sh` lines 43-55):
```bash
test_svc_up() {
    arrange
    "$HARNESSED" svc down ping --purge >/dev/null 2>&1 || true
    act
    uat_run "$HARNESSED" svc up ping
    assert
    assert_exit_zero "$UAT_RC" "svc up ping exits 0"
    assert_contains "is up" "$UAT_OUT" "reports the service is up"
}
```

**Container-test skip guard** (`tools/uat/phase-04.sh` line 39 + usage on line 95):
```bash
needs_container() { [ "$UAT_QUICK" = "true" ]; }
# Inside a test:
needs_container && { skip_test "skipped (--quick)"; return; }
```

**`uat_run_phase` entrypoint pattern** (`tools/uat/phase-04.sh` lines 326-350):
```bash
uat_run_phase() {
    uat_suite "Phase 4 — Shared Services + Recipe Breadth + Full CLI"
    echo "  launcher: $HARNESSED  runtime: ${RT:-none}"
    [ -z "$RT" ] && { echo "  ⚠ no container runtime found — container tests will fail"; }

    run_test svc_up                 "svc up publishes port and lists"
    run_test ...
}
```

**Phase 9 tests to implement** (from RESEARCH Validation Architecture):
```bash
test_profile_no_claude_tree()    # ! test -d profiles/gstack-time/.claude
test_mcp_json_at_profile_root()  # test -f profiles/gstack-time/.mcp.json
test_manifests_exist()           # test -f lib/manifests/claude.yaml (etc.)
test_path_mirroring()            # podman exec <instance> pwd == $HOST_PWD (headless)
test_claude_history_surfaced()   # ~/.claude/projects/<slug>/ has new files (headless)
test_omp_history_surfaced()      # ~/.omp/agent/sessions/<slug>/ has new files (headless)
test_antigravity_history()       # ~/.gemini/antigravity-cli/conversations/ has new .db (headless)
```

**File-level assertion helpers available in uat-common.sh:**
```bash
assert_exists "$path" "label"
assert_not_exists "$path" "label"
assert_file_contains "$path" "text" "label"
assert_not_contains "text" "$content" "label"
assert_match 'regex' "$str" "label"
```

---

## Shared Patterns

### MOUNT_ARGS Append
**Source:** `lib/harnessed-mounts.sh` (all lines)
**Apply to:** `lib/harnessed-manifest-mounts.sh`

The array is declared by the CALLER (`local MOUNT_ARGS=()`); the helper function appends with `MOUNT_ARGS+=( ... )`. Never declare `MOUNT_ARGS` inside a helper — it would shadow the caller's array.

### `print_warning` / `print_error` / `print_info`
**Source:** `lib/harnessed-isolated-config.sh` lines 38, 56, 65, 88
**Apply to:** `lib/harnessed-manifest-mounts.sh`

Use `print_warning` for non-fatal conditions (missing optional files, unseeded auth). Use `print_error` + `return 1` for fatal conditions. Never use `echo` directly.

### Per-Harness Case/Branch
**Source:** `lib/harnessed-isolated-config.sh` lines 33-82 (if-elif chain) and `lib/harnessed-isolated.sh` lines 88-109, 241-269
**Apply to:** `lib/harnessed-manifest-mounts.sh` (target path derivation for profile_files)

Both files use `if [ "$harness" = "X" ]; then ... elif ...` — not a `case` statement. Match this style in the new helper.

### `mkdir -p` Before Bind Mount
**Source:** `lib/harnessed-isolated-config.sh` line 94 (`mkdir -p "$state_dir"`)
**Apply to:** `lib/harnessed-manifest-mounts.sh` history_dirs loop

Always `mkdir -p` the host dir before `MOUNT_ARGS+=( -v ... )`. Podman creates missing bind-mount source dirs as root-owned in DooD mode.

### Python `_write_json` Helper
**Source:** `tools/harnessed/emit.py` lines 46-48
**Apply to:** Any new emit functions in `emit.py`

All JSON emission goes through `_write_json(path, data)` — never call `path.write_text(json.dumps(...))` directly.

---

## No Analog Found

All files have close analogs. No entries here.

---

## Metadata

**Analog search scope:** `lib/`, `tools/harnessed/`, `tools/uat/`, `stacks/`
**Files scanned:** 6 (harnessed-mounts.sh, harnessed-isolated-config.sh, harnessed-isolated.sh, assemble.py, emit.py, phase-04.sh)
**Pattern extraction date:** 2026-06-24
