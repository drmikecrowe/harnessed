#!/usr/bin/env bash
# phase-09.sh — UAT suite for Phase 9 (surgical profile mount + history surfacing).
#
# Sourced by run-uat.sh (after uat-common.sh). Defines test_<id> functions and a
# uat_run_phase entrypoint. Every test follows Arrange → Act → Assert (AAA).
#
# Smoke tests (no container required) always run and verify structural invariants:
#   - manifests exist and contain required keys
#   - no credential paths leak into manifests
#   - manifest-mounts helper exists and is syntactically valid
#   - launcher sources the helper and guards on .mcp.json
#   - assembler carries no fan-out (syncer/LinkSyncer/harness_dir/ensure_profile_tree)
#   - profile shape after build: .mcp.json at root, no .claude/ tree
#
# Integration tests (history surfacing, path mirroring) require --no-quick and
# the relevant stacks (gstack-time, omp-time, antigravity-time) to be built.

RT="$(uat_runtime)"   # podman | docker | "" (empty if neither present)

# ─── suite helpers ──────────────────────────────────────────────────────────────
skip_if_quick() { [ "$UAT_QUICK" = "true" ]; }   # true ⇒ this test should skip (WR-02: renamed from needs_container)
uat_instance_name() { local h; h="$(printf '%s' "${2%/}" | shasum | cut -c1-8)"; echo "harnessed-${1}-${h}"; }

# ─── Section A: Smoke tests (no container required) ─────────────────────────────

test_manifests_exist() {
    arrange
    act
    assert
    assert_exists "$HARNESSED_DIR/lib/manifests/claude.yaml"       "claude manifest ships"
    assert_exists "$HARNESSED_DIR/lib/manifests/omp.yaml"          "omp manifest ships"
    assert_exists "$HARNESSED_DIR/lib/manifests/antigravity.yaml"  "antigravity manifest ships"
    assert_exists "$HARNESSED_DIR/lib/manifests/opencode.yaml"     "opencode manifest ships"
    assert_exists "$HARNESSED_DIR/lib/manifests/gemini.yaml"       "gemini manifest ships"
    assert_exists "$HARNESSED_DIR/lib/manifests/codex.yaml"        "codex manifest ships"
    assert_file_contains "$HARNESSED_DIR/lib/manifests/claude.yaml" "profile_files" \
        "claude manifest has profile_files key"
    assert_file_contains "$HARNESSED_DIR/lib/manifests/claude.yaml" "history_dirs" \
        "claude manifest has history_dirs key"
    assert_file_contains "$HARNESSED_DIR/lib/manifests/antigravity.yaml" "antigravity-cli" \
        "antigravity manifest references antigravity-cli subdir"
}

test_manifest_no_credentials() {
    arrange
    local all_manifests
    all_manifests=$(cat "$HARNESSED_DIR/lib/manifests/"*.yaml 2>/dev/null)
    act
    assert
    assert_not_contains "agent.db" "$all_manifests" \
        "no manifest contains agent.db credential path"
    assert_not_contains "antigravity-oauth-token" "$all_manifests" \
        "no manifest contains antigravity-oauth-token"
    assert_not_contains ".credentials.json" "$all_manifests" \
        "no manifest contains .credentials.json credential path"
}

test_manifest_mounts_helper_exists() {
    arrange
    act
    assert
    assert_exists "$HARNESSED_DIR/lib/harnessed-manifest-mounts.sh" \
        "manifest mounts helper file ships"
    assert_file_contains "$HARNESSED_DIR/lib/harnessed-manifest-mounts.sh" \
        "harnessed_manifest_mounts" \
        "helper defines the harnessed_manifest_mounts function"
    # bash -n is a pure-syntax check (no container needed)
    bash -n "$HARNESSED_DIR/lib/harnessed-manifest-mounts.sh" >/dev/null 2>&1
    assert_exit_zero "$?" "bash -n on manifest mounts helper exits 0 (no syntax errors)"
}

test_launcher_uses_manifest_mounts() {
    arrange
    act
    assert
    assert_file_contains "$HARNESSED_DIR/lib/harnessed-isolated.sh" \
        "harnessed-manifest-mounts.sh" \
        "launcher sources the manifest mounts helper"
    assert_file_contains "$HARNESSED_DIR/lib/harnessed-isolated.sh" \
        "harnessed_manifest_mounts" \
        "launcher calls harnessed_manifest_mounts"
    assert_file_contains "$HARNESSED_DIR/lib/harnessed-isolated.sh" \
        "profile_dir/.mcp.json" \
        "launcher guard uses profile_dir/.mcp.json (MNT2-01)"
}

test_assembler_no_fanout() {
    arrange
    act
    assert
    # rg exits 1 (no match) when none of the fan-out traces are present — that is a PASS.
    assert_false rg -q 'syncer|LinkSyncer|harness_dir|ensure_profile_tree' \
        "$HARNESSED_DIR/tools/harnessed/assemble.py" \
        "$HARNESSED_DIR/tools/harnessed/emit.py" \
        "assembler files contain no fan-out traces (syncer/LinkSyncer/harness_dir/ensure_profile_tree)"
}

test_profile_shape_after_build() {
    arrange
    # Skip if gstack-time has not been assembled yet (plan 09-02 must have run).
    if [ ! -d "$HARNESSED_DIR/profiles/gstack-time" ]; then
        skip_test "skipped — profiles/gstack-time does not exist (run: harnessed build gstack-time)"
        return
    fi
    act
    assert
    assert_not_exists "$HARNESSED_DIR/profiles/gstack-time/.claude" \
        "gstack-time has no .claude/ tree (profile is flat, not nested)"
    assert_exists "$HARNESSED_DIR/profiles/gstack-time/.mcp.json" \
        "gstack-time has .mcp.json at profile root (MNT2-01)"
    assert_exists "$HARNESSED_DIR/profiles/gstack-time/settings.json" \
        "gstack-time has settings.json at profile root"
}

# ─── Section B: Integration tests (history surfacing + path mirroring) ──────────
# All integration tests skip under UAT_QUICK=true and also skip if the relevant
# stack is not built (profile .mcp.json absent).

test_path_mirroring() {
    skip_if_quick && { skip_test "skipped (--quick)"; return; }
    [ -z "$RT" ] && { skip_test "no container runtime found"; return; }
    if [ ! -f "$HARNESSED_DIR/profiles/gstack-time/.mcp.json" ]; then
        skip_test "skipped — gstack-time not built (run: harnessed build gstack-time)"
        return
    fi
    arrange
    local proj="/tmp/uat-mirror-$$"
    local inst; inst="$(uat_instance_name gstack-time "$proj")"
    mkdir -p "$proj"
    uat_pod_rm "$inst"
    act
    uat_run_env "HARNESSED_HEADLESS=true" "$HARNESSED" gstack-time "$proj"
    assert
    assert_exit_zero "$UAT_RC" "headless gstack-time launch exits 0 (MNT2-02)"
    # Verify the project directory is accessible at its host absolute path inside the container
    # (MNT2-02 path mirroring: the bind mount makes $proj accessible at the same absolute path).
    local check
    check="$("$RT" exec "$inst" bash -c "test -d '$proj' && echo EXISTS" 2>/dev/null || echo "MISSING")"
    assert_eq "EXISTS" "$check" "host project path accessible at same absolute path in container (MNT2-02)"
    # Also verify the container working directory is set to the project path.
    local ctr_pwd
    ctr_pwd="$("$RT" exec -w "$proj" "$inst" bash -c 'pwd' 2>/dev/null || echo "EXEC_FAILED")"
    assert_eq "$proj" "$ctr_pwd" "container pwd at project path matches host path (MNT2-02)"
    # Teardown
    uat_pod_rm "$inst"
    rm -rf "$proj"
}

test_claude_history_surfaced() {
    skip_if_quick && { skip_test "skipped (--quick)"; return; }
    [ -z "$RT" ] && { skip_test "no container runtime found"; return; }
    if [ ! -f "$HARNESSED_DIR/profiles/gstack-time/.mcp.json" ]; then
        skip_test "skipped — gstack-time not built (run: harnessed build gstack-time)"
        return
    fi
    arrange
    local proj="/tmp/uat-claude-hist-$$"
    local inst; inst="$(uat_instance_name gstack-time "$proj")"
    mkdir -p "$proj"
    uat_pod_rm "$inst"
    act
    # Brief headless session: enough to start the container, which creates the history mount.
    uat_run_env "HARNESSED_HEADLESS=true" "$HARNESSED" gstack-time "$proj"
    assert
    assert_exit_zero "$UAT_RC" "headless gstack-time launch exits 0"
    assert_exists "$HOME/.claude/projects" \
        "host ~/.claude/projects dir is accessible after session (history surfaced, MNT2-03)"
    # Teardown
    uat_pod_rm "$inst"
    rm -rf "$proj"
}

test_omp_history_surfaced() {
    skip_if_quick && { skip_test "skipped (--quick)"; return; }
    [ -z "$RT" ] && { skip_test "no container runtime found"; return; }
    if [ ! -f "$HARNESSED_DIR/profiles/omp-time/.mcp.json" ]; then
        skip_test "skipped — omp-time not built (run: harnessed build omp-time)"
        return
    fi
    arrange
    local proj; proj="$(pwd)"
    # Replicate production project_relpath() exactly (lib/harnessed-common.sh:389-392):
    # use basename as fallback for paths outside $HOME, not realpath --relative-to which
    # emits ../ prefixes and diverges from the slug the production code computes (WR-03).
    local p="${proj%/}"
    local relpath
    if [[ "$p" == "$HOME/"* ]]; then
        relpath="${p#"$HOME"/}"
    else
        relpath="$(basename "$p")"
    fi
    local omp_slug="-${relpath//\//'-'}"
    local inst; inst="$(uat_instance_name omp-time "$proj")"
    act
    uat_run_env "HARNESSED_HEADLESS=true" "$HARNESSED" omp-time "$proj"
    assert
    assert_exit_zero "$UAT_RC" "headless omp-time launch exits 0"
    assert_exists "$HOME/.omp/agent/sessions/$omp_slug" \
        "host omp session dir exists at computed slug (MNT2-04)"
    # Teardown
    uat_pod_rm "$inst"
}

test_antigravity_history_surfaced() {
    skip_if_quick && { skip_test "skipped (--quick)"; return; }
    [ -z "$RT" ] && { skip_test "no container runtime found"; return; }
    if [ ! -f "$HARNESSED_DIR/profiles/antigravity-time/.mcp.json" ]; then
        skip_test "skipped — antigravity-time not built (run: harnessed build antigravity-time)"
        return
    fi
    arrange
    local proj; proj="$(pwd)"
    local inst; inst="$(uat_instance_name antigravity-time "$proj")"
    act
    uat_run_env "HARNESSED_HEADLESS=true" "$HARNESSED" antigravity-time "$proj"
    assert
    assert_exit_zero "$UAT_RC" "headless antigravity-time launch exits 0"
    assert_exists "$HOME/.gemini/antigravity-cli/conversations" \
        "host antigravity conversations dir exists after session (MNT2-05)"
    # Teardown
    uat_pod_rm "$inst"
}

# ─── entrypoint ─────────────────────────────────────────────────────────────────
uat_run_phase() {
    uat_suite "Phase 9 — Surgical Profile Mount + History Surfacing"
    echo "  launcher: $HARNESSED  runtime: ${RT:-none}"
    [ "$UAT_QUICK" = "true" ] && echo "  --quick: smoke tests run; integration tests (history surfacing, path mirroring) skip"
    [ "$UAT_QUICK" != "true" ] && echo "  Integration tests (history surfacing, path mirroring) require --no-quick and relevant stacks built"

    # Smoke tests — no container required, always run
    run_test manifests_exist              "MNT2-01: all 6 harness manifests ship (fast)"
    run_test manifest_no_credentials      "MNT2-01: no credential paths in manifests (fast)"
    run_test manifest_mounts_helper_exists "MNT2-06: manifest-mounts helper ships and is valid bash (fast)"
    run_test launcher_uses_manifest_mounts "MNT2-01/MNT2-06: launcher sources and calls manifest-mounts helper (fast)"
    run_test assembler_no_fanout          "MNT2-06: assembler has no fan-out traces (fast)"
    run_test profile_shape_after_build    "MNT2-01: profile has .mcp.json at root, no .claude/ tree (fast)"

    # Integration tests — skip under --quick; require relevant stacks built
    run_test path_mirroring              "MNT2-02: path mirroring — container pwd matches host (heavy)"
    run_test claude_history_surfaced     "MNT2-03: claude history surfaced at ~/.claude/projects (heavy)"
    run_test omp_history_surfaced        "MNT2-04: omp history surfaced at per-project slug (heavy)"
    run_test antigravity_history_surfaced "MNT2-05: antigravity history surfaced at ~/.gemini/antigravity-cli (heavy)"
}
