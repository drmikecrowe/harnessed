#!/usr/bin/env bash
# phase-04.sh — UAT suite for Phase 4 (shared services + recipe breadth + full CLI).
#
# Sourced by run-uat.sh (after uat-common.sh). Defines test_<id> functions and a
# uat_run_phase entrypoint. Every test follows Arrange → Act → Assert (AAA).
#
# Two tests encode KNOWN GAPS as red regression checks (go green when the fix lands):
#   - no_args_help     (UAT gap 6B): bare `harnessed` should show usage, not launch transparent
#   - legible_slug     (UAT gap 6) : state-dir slug should be a legible path, not a hash
#
# Heavy tests (container launches) self-skip under `--quick`.

RT="$(uat_runtime)"   # podman | docker | "" (empty if neither present)

# ─── suite helpers ──────────────────────────────────────────────────────────────
uat_vol_exists()  { [ -n "$RT" ] && "$RT" volume exists "$1" >/dev/null 2>&1; }
# Count running SERVICE containers by their harnessed-service label (excludes instance members).
uat_svc_count()   { [ -n "$RT" ] || { echo 0; return; }
                    "$RT" ps --filter "label=harnessed-service=$1" --format '{{.Names}}' 2>/dev/null | wc -l | tr -d ' '; }
# Pod/instance name = generate_instance_name (hash form; unchanged by the planned slug fix).
uat_instance_name() { local h; h="$(printf '%s' "${2%/}" | shasum | cut -c1-8)"; echo "harnessed-${1}-${h}"; }
# Newest state dir for a stack (robust to the slug formula — finds by mtime + stack name).
uat_newest_state_dir() { # state_root stack
    local root="$1" stack="$2" d found=""
    for d in "$root"/*"$stack"*; do
        [ -d "$d" ] || continue
        if [ -z "$found" ] || [ "$d" -nt "$found" ]; then found="$d"; fi
    done
    echo "$found"
}
needs_container() { [ "$UAT_QUICK" = "true" ]; }   # true ⇒ this test should skip
# Tear down any transparent pods/containers left by the (currently buggy) bare invocation.
uat_clean_transparent() {
    [ -n "$RT" ] || return
    local c
    for c in $("$RT" ps -a --format '{{.Names}}' 2>/dev/null); do
        [[ $c == *transparent* ]] && "$RT" rm -f "$c" >/dev/null 2>&1
    done
    local p
    for p in $("$RT" pod ls --format '{{.Name}}' 2>/dev/null); do
        [[ $p == *transparent* ]] && "$RT" pod rm -f "$p" >/dev/null 2>&1
    done
}

# ─── Section A: shared services (svc) ──────────────────────────────────────────

test_svc_up() {
    arrange
    "$HARNESSED" svc down ping --purge >/dev/null 2>&1 || true
    act
    uat_run "$HARNESSED" svc up ping
    assert
    assert_exit_zero "$UAT_RC" "svc up ping exits 0"
    assert_contains "is up" "$UAT_OUT" "reports the service is up"
    assert_match '0\.0\.0\.0:8080' "$("$RT" ps --filter 'name=ping' --format '{{.Ports}}' 2>/dev/null)" "publishes its port to 0.0.0.0"
    uat_run "$HARNESSED" svc list
    assert_contains "ping" "$UAT_OUT" "svc list shows the ping service"
    "$HARNESSED" svc down ping --purge >/dev/null 2>&1 || true
}

test_svc_up_idempotent() {
    arrange
    "$HARNESSED" svc down ping --purge >/dev/null 2>&1 || true
    "$HARNESSED" svc up ping >/dev/null 2>&1 || true
    act
    uat_run "$HARNESSED" svc up ping
    assert
    assert_exit_zero "$UAT_RC" "second svc up exits 0"
    assert_contains "already running" "$UAT_OUT" "reports already running (no-op)"
    assert_eq "1" "$(uat_svc_count ping)" "exactly one ping service container (no duplicate)"
    "$HARNESSED" svc down ping --purge >/dev/null 2>&1 || true
}

test_svc_down_retains_volume() {
    arrange
    "$HARNESSED" svc up ping >/dev/null 2>&1 || true
    act
    uat_run "$HARNESSED" svc down ping
    assert
    assert_exit_zero "$UAT_RC" "svc down exits 0"
    assert_contains "kept" "$UAT_OUT" "reports the volume is kept"
    assert_true uat_vol_exists ping-data "ping-data volume survives svc down"
    "$HARNESSED" svc down ping --purge >/dev/null 2>&1 || true
}

test_svc_down_purge() {
    arrange
    "$HARNESSED" svc up ping >/dev/null 2>&1 || true
    act
    uat_run "$HARNESSED" svc down ping --purge
    assert
    assert_exit_zero "$UAT_RC" "svc down --purge exits 0"
    assert_contains "purged" "$UAT_OUT" "reports the volume is purged"
    assert_false uat_vol_exists ping-data "ping-data volume is destroyed by --purge"
}

test_shared_single_across_instance() {
    needs_container && { skip_test "skipped (--quick)"; return; }
    arrange
    "$HARNESSED" svc down ping --purge >/dev/null 2>&1 || true
    act
    uat_run "$HARNESSED" test ping-time
    assert
    assert_exit_zero "$UAT_RC" "harnessed test ping-time passes (time + ping connected)"
    assert_contains "ping" "$UAT_OUT" "capability report references the ping service"
    assert_eq "1" "$(uat_svc_count ping)" "one shared ping service (instance attached, did not duplicate it)"
    "$HARNESSED" svc down ping --purge >/dev/null 2>&1 || true
}

# ─── Section B: recipe breadth + omp bridge ────────────────────────────────────

test_recipe_breadth() {
    needs_container && { skip_test "skipped (--quick)"; return; }
    act
    uat_run "$HARNESSED" test claude-multi
    assert
    assert_exit_zero "$UAT_RC" "harnessed test claude-multi passes"
    assert_contains "greet" "$UAT_OUT" "second recipe (greet-helper) is asserted"
}

test_omp_bridge() {
    needs_container && { skip_test "skipped (--quick)"; return; }
    act
    uat_run "$HARNESSED" test omp-time
    assert
    assert_exit_zero "$UAT_RC" "harnessed test omp-time passes"
    assert_contains "time" "$UAT_OUT" "omp stack exposes the time capability via the bridge"
}

# ─── Section C: CLI surface ────────────────────────────────────────────────────

test_no_args_help() {
    arrange
    uat_clean_transparent
    act
    # Desired (gap 6B): bare invocation shows usage and exits 0. Today it launches
    # transparent (interactive) — bounded by `timeout` so it cannot hang the suite.
    echo "    ▸ timeout 12 $HARNESSED  (no args)"
    UAT_OUT=$(timeout 12 "$HARNESSED" 2>&1); UAT_RC=$?
    assert
    assert_exit_zero "$UAT_RC" "bare harnessed exits 0"
    assert_contains "Usage" "$UAT_OUT" "shows usage/help (not a silent transparent launch)"
    uat_clean_transparent
}

test_list_surface() {
    act
    uat_run "$HARNESSED" list
    assert
    assert_exit_zero "$UAT_RC" "list exits 0"
    assert_contains "Stacks:" "$UAT_OUT" "lists authored stacks"
    assert_contains "ping-time" "$UAT_OUT" "ping-time stack is listed"
}

test_new_scaffold_refuse() {
    arrange
    rm -rf "$HARNESSED_DIR/stacks/uatdemo"
    act
    uat_run "$HARNESSED" new uatdemo --harness claude --recipes time
    assert
    assert_exit_zero "$UAT_RC" "new scaffolds a stack"
    assert_exists "$HARNESSED_DIR/stacks/uatdemo/stack.yaml" "stack.yaml written"
    assert_file_contains "$HARNESSED_DIR/stacks/uatdemo/stack.yaml" "time" "manifest records the recipe"
    # refuse overwrite
    act
    uat_run "$HARNESSED" new uatdemo --harness claude --recipes time
    assert
    assert_exit_nonzero "$UAT_RC" "new refuses to overwrite an existing stack"
    assert_contains "already exists" "$UAT_OUT" "reports the stack already exists"
    rm -rf "$HARNESSED_DIR/stacks/uatdemo"
}

test_new_bad_harness() {
    arrange
    rm -rf "$HARNESSED_DIR/stacks/uatdemo2"
    act
    uat_run "$HARNESSED" new uatdemo2 --harness bogus
    assert
    assert_exit_nonzero "$UAT_RC" "new rejects an unknown harness"
    assert_contains "unknown harness" "$UAT_OUT" "reports the harness is unknown"
    assert_not_exists "$HARNESSED_DIR/stacks/uatdemo2/stack.yaml" "no stack written for a bad harness"
    rm -rf "$HARNESSED_DIR/stacks/uatdemo2"
}

test_install_uninstall() {
    arrange
    rm -rf "$HARNESSED_DIR/stacks/uatdemo"
    "$HARNESSED" new uatdemo --harness claude --recipes time >/dev/null 2>&1 || true
    local bin; bin="$(mktemp -d)"
    act
    uat_run_env "HARNESSED_BIN_DIR=$bin" "$HARNESSED" install uatdemo
    assert
    assert_exit_zero "$UAT_RC" "install exits 0"
    assert_exists "$bin/uatdemo" "launcher shim written"
    assert_executable "$bin/uatdemo" "shim is executable"
    assert_file_contains "$bin/uatdemo" "exec" "shim uses the exec template"
    assert_file_contains "$bin/uatdemo" "uatdemo" "shim targets the uatdemo stack"
    act
    uat_run_env "HARNESSED_BIN_DIR=$bin" "$HARNESSED" uninstall uatdemo
    assert
    assert_not_exists "$bin/uatdemo" "uninstall removes the shim"
    rm -rf "$bin" "$HARNESSED_DIR/stacks/uatdemo"
}

test_legacy_flags() {
    act
    uat_run "$HARNESSED" --list
    assert
    assert_exit_zero "$UAT_RC" "legacy --list exits 0"
    assert_contains "instance" "$UAT_OUT" "legacy --list lists instances (instance-only back-compat)"
}

# ─── Section D: state persistence + legible slug ───────────────────────────────

test_state_persists() {
    needs_container && { skip_test "skipped (--quick)"; return; }
    local proj="/tmp/uat-persist-$$" inst sd
    inst="$(uat_instance_name ping-time "$proj")"
    arrange
    "$HARNESSED" svc down ping --purge >/dev/null 2>&1 || true
    uat_pod_rm "$inst"; rm -rf "${XDG_STATE_HOME:-$HOME/.local/state}/harnessed/$inst"
    mkdir -p "$proj"
    # establish accumulated state: first create + a marker, then tear the pod down
    uat_run_env "HARNESSED_HEADLESS=true" "$HARNESSED" ping-time "$proj"
    assert_exit_zero "$UAT_RC" "first headless create exits 0" || { uat_pod_rm "$inst"; rm -rf "$proj"; return; }
    sd="${XDG_STATE_HOME:-$HOME/.local/state}/harnessed/$inst/.claude"
    echo "u4t" > "$sd/UAT_MARKER"
    uat_pod_rm "$inst"
    act
    uat_run_env "HARNESSED_HEADLESS=true" "$HARNESSED" ping-time "$proj"   # NOT --fresh
    assert
    assert_exit_zero "$UAT_RC" "recreate (no --fresh) exits 0"
    assert_exists "$sd/UAT_MARKER" "marker survives a normal recreate (state persists by default)"
    uat_pod_rm "$inst"; rm -rf "${XDG_STATE_HOME:-$HOME/.local/state}/harnessed/$inst" "$proj"
    "$HARNESSED" svc down ping --purge >/dev/null 2>&1 || true
}

test_fresh_wipes() {
    needs_container && { skip_test "skipped (--quick)"; return; }
    local proj="/tmp/uat-fresh-$$" inst sd
    inst="$(uat_instance_name ping-time "$proj")"
    arrange
    "$HARNESSED" svc down ping --purge >/dev/null 2>&1 || true
    uat_pod_rm "$inst"; rm -rf "${XDG_STATE_HOME:-$HOME/.local/state}/harnessed/$inst"
    mkdir -p "$proj"
    uat_run_env "HARNESSED_HEADLESS=true" "$HARNESSED" ping-time "$proj"
    assert_exit_zero "$UAT_RC" "first headless create exits 0" || { uat_pod_rm "$inst"; rm -rf "$proj"; return; }
    sd="${XDG_STATE_HOME:-$HOME/.local/state}/harnessed/$inst/.claude"
    echo "u4t" > "$sd/UAT_MARKER"
    uat_pod_rm "$inst"
    act
    uat_run_env "HARNESSED_HEADLESS=true" "$HARNESSED" ping-time "$proj" --fresh
    assert
    assert_exit_zero "$UAT_RC" "recreate (--fresh) exits 0"
    assert_not_exists "$sd/UAT_MARKER" "--fresh wipes accumulated state (clean-room)"
    uat_pod_rm "$inst"; rm -rf "${XDG_STATE_HOME:-$HOME/.local/state}/harnessed/$inst" "$proj"
    "$HARNESSED" svc down ping --purge >/dev/null 2>&1 || true
}

test_legible_slug() {
    needs_container && { skip_test "skipped (--quick)"; return; }
    local proj="$HOME/.cache/uat-legible-$$" state_root found inst
    inst="$(uat_instance_name ping-time "$proj")"   # pod name (hash; unchanged by the slug fix)
    state_root="${XDG_STATE_HOME:-$HOME/.local/state}/harnessed"
    arrange
    "$HARNESSED" svc down ping --purge >/dev/null 2>&1 || true
    mkdir -p "$proj"
    act
    uat_run_env "HARNESSED_HEADLESS=true" "$HARNESSED" ping-time "$proj"
    assert
    assert_exit_zero "$UAT_RC" "headless launch exits 0"
    found="$(uat_newest_state_dir "$state_root" ping-time)"
    assert_match 'uat-legible' "$(basename "$found")" "state slug is legible (path-based, not an opaque hash)"
    uat_pod_rm "$inst"; rm -rf "$found" "$proj"
    "$HARNESSED" svc down ping --purge >/dev/null 2>&1 || true
}

# ─── entrypoint ────────────────────────────────────────────────────────────────
uat_run_phase() {
    uat_suite "Phase 4 — Shared Services + Recipe Breadth + Full CLI"
    echo "  launcher: $HARNESSED  runtime: ${RT:-none}"
    [ -z "$RT" ] && { echo "  ⚠ no container runtime found — container tests will fail"; }

    run_test svc_up                 "svc up publishes port and lists"
    run_test svc_up_idempotent      "svc up is idempotent (no duplicate)"
    run_test svc_down_retains_volume "svc down keeps the volume"
    run_test svc_down_purge         "svc down --purge destroys the volume"
    run_test shared_single_across_instance "shared service is singular across an instance attach"
    run_test recipe_breadth         "recipe breadth — second recipe asserted"
    run_test omp_bridge             "omp stack runs the recipe via the bridge"
    run_test no_args_help           "bare harnessed shows help (gap 6B)"
    run_test list_surface           "list shows stacks + instances"
    run_test new_scaffold_refuse    "new scaffolds + refuses overwrite"
    run_test new_bad_harness        "new rejects an unknown harness"
    run_test install_uninstall      "install/uninstall launcher shim"
    run_test legacy_flags           "legacy --list back-compat"
    run_test state_persists         "state persists across a normal recreate"
    run_test fresh_wipes            "--fresh wipes state (clean-room)"
    run_test legible_slug           "state-dir slug is legible (gap 6)"
}
