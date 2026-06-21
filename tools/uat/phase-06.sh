#!/usr/bin/env bash
# phase-06.sh — UAT suite for the HARNESS MATRIX (one proof stack per supported harness).
#
# Sourced by run-uat.sh (after uat-common.sh). Defines test_<id> functions and a
# uat_run_phase entrypoint. Every test follows Arrange → Act → Assert (AAA).
#
# This is the SYSTEMATIC cross-harness test: every supported harness ships a `<harness>-time`
# proof stack (the same Claude-canonical `time` recipe — one stdio MCP server + one skill — run on
# that harness). Each heavy test drives the real `harnessed test <stack>` capability run end to end:
# build → launch the pod --fresh headless → introspect the live instance (hatago `hatago://servers`
# MCP resource + mounted-profile filesystem, both harness-independent) → assert the `time` MCP
# server is connected and the `time-helper` skill is present → teardown. A green matrix proves the
# single Claude-canonical profile + the hatago hub light up identically on every harness.
#
# Heavy tests (build + pod launch) self-skip under `--quick`; the fast `manifests` test validates the
# whole matrix (stack manifests + harness validation) WITHOUT a container so it always runs.
#
# `harnessed test` is pointed at a NONEXISTENT secrets schema so the build/launch legs run
# non-interactively (inert secrets path) regardless of the operator's ~/.config/harnessed.
#
# NOTE (provider portability): `harnessed test` exercises the ISOLATED path, which is currently
# podman-pod based. On Docker / Apple `container` these heavy tests will fail until the runtime layer
# is provider-agnostic — the matrix is the regression gate that will prove that port when it lands.

RT="$(uat_runtime)"   # podman | docker | "" (empty if neither present)

needs_container() { [ "$UAT_QUICK" = "true" ]; }   # true ⇒ this heavy test should skip

UAT_NO_SCHEMA="/nonexistent/harnessed-uat-$$/.env.schema"

# The harness matrix: each supported harness → its proof stack. Keep in sync with HARNESS_CONFIG_DIR
# (tools/harnessed/schema.py) and the stacks/ proof stacks.
UAT_MATRIX=(
    "claude:tracer-time"
    "omp:omp-time"
    "opencode:opencode-time"
    "gemini:gemini-time"
    "antigravity:antigravity-time"
    "codex:codex-time"
)

# Shared heavy leg: run the real capability test for one stack and assert the time slice is live.
_uat_harness_capability() { # harness stack
    local harness="$1" stack="$2"
    needs_container && { skip_test "skipped (--quick) — builds + launches the $harness pod"; return; }
    [ -z "$RT" ] && { skip_test "no container runtime found"; return; }
    arrange
    act
    uat_run_env "HARNESSED_SCHEMA=$UAT_NO_SCHEMA" "$HARNESSED" test "$stack"
    assert
    assert_exit_zero "$UAT_RC" "$harness: 'harnessed test $stack' is green"
    # The capability report asserts internally + sets the exit code; corroborate the visible report
    # rows so a regression that silently empties the report is still caught.
    assert_contains "time" "$UAT_OUT" "$harness: report lists the 'time' MCP server"
    assert_contains "connected" "$UAT_OUT" "$harness: the 'time' MCP server is connected via hatago"
    assert_contains "time-helper" "$UAT_OUT" "$harness: the 'time-helper' skill is present in the profile"
}

# ─── Fast leg (always runs, no container): the matrix is well-formed ────────────

# Every harness in the matrix has a proof stack whose manifest declares that harness, and the
# scaffolder/validator accepts each matrix harness while rejecting an unknown one.
test_matrix_manifests() {
    arrange
    local pair harness stack
    act
    assert
    for pair in "${UAT_MATRIX[@]}"; do
        harness="${pair%%:*}"; stack="${pair##*:}"
        assert_exists "$HARNESSED_DIR/stacks/$stack/stack.yaml" "matrix: stacks/$stack manifest ships"
        local declared
        declared="$(sed -n 's/^harness:[[:space:]]*//p' "$HARNESSED_DIR/stacks/$stack/stack.yaml" | tr -d '[:space:]' | sed 's/#.*//')"
        assert_eq "$declared" "$harness" "matrix: $stack declares harness '$harness'"
    done
    # The validator accepts every matrix harness (scaffold to a throwaway name, then clean up).
    for pair in "${UAT_MATRIX[@]}"; do
        harness="${pair%%:*}"
        uat_run "$HARNESSED" new "__uat_probe_${harness}" --harness "$harness"
        assert_exit_zero "$UAT_RC" "validator accepts harness '$harness'"
        rm -rf "$HARNESSED_DIR/stacks/__uat_probe_${harness}" 2>/dev/null || true
    done
    # …and rejects an unknown harness.
    uat_run "$HARNESSED" new "__uat_probe_bogus" --harness notaharness
    assert_exit_nonzero "$UAT_RC" "validator rejects an unknown harness"
    rm -rf "$HARNESSED_DIR/stacks/__uat_probe_bogus" 2>/dev/null || true
}

# ─── Heavy legs (one per harness; self-skip under --quick) ──────────────────────
test_harness_claude()      { _uat_harness_capability claude tracer-time; }
test_harness_omp()         { _uat_harness_capability omp omp-time; }
test_harness_opencode()    { _uat_harness_capability opencode opencode-time; }
test_harness_gemini()      { _uat_harness_capability gemini gemini-time; }
test_harness_antigravity() { _uat_harness_capability antigravity antigravity-time; }
test_harness_codex()       { _uat_harness_capability codex codex-time; }

# ─── entrypoint ────────────────────────────────────────────────────────────────
uat_run_phase() {
    uat_suite "Phase 6 — Harness Matrix (capability test per supported harness)"
    echo "  launcher: $HARNESSED  runtime: ${RT:-none}"
    [ -z "$RT" ] && echo "  ⚠ no container runtime found — heavy per-harness tests will skip"
    [ "$UAT_QUICK" = "true" ] && echo "  --quick: only the manifest matrix runs (heavy per-harness capability tests skip)"

    run_test matrix_manifests     "matrix manifests + harness validation (fast, no container)"
    run_test harness_claude       "claude — capability test (tracer-time) green"
    run_test harness_omp          "omp — capability test (omp-time) green"
    run_test harness_opencode     "opencode — capability test (opencode-time) green"
    run_test harness_gemini       "gemini — capability test (gemini-time) green"
    run_test harness_antigravity  "antigravity — capability test (antigravity-time) green"
    run_test harness_codex        "codex — capability test (codex-time) green"
}
