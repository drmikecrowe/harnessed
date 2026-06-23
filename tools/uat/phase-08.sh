#!/usr/bin/env bash
# phase-08.sh — UAT suite for Phase 8: Dockerfile Recipe Model + Assembler + Supply-Chain Gate.
#
# Sourced by run-uat.sh (after uat-common.sh). Defines test_<id> functions and a
# uat_run_phase entrypoint. Every test follows Arrange → Act → Assert (AAA).
#
# Fast tests (manifest / validation) always run. Heavy tests (container build + scan) self-skip
# under --quick. Heavy rejection tests (floating-test, omp-gstack-test) require the tools image
# to be built so the assembler can run inside the container.

RT="$(uat_runtime)"   # podman | docker | "" (empty if neither present)

needs_container() { [ "$UAT_QUICK" = "true" ]; }   # true ⇒ heavy test should skip

# ─── Fast tests (always run, no container) ──────────────────────────────────

test_recipe_structure() {
    arrange
    act
    assert
    # RCP2-01: gstack recipe has a Dockerfile
    assert_exists "$HARNESSED_DIR/recipes/gstack/Dockerfile" \
        "RCP2-01: gstack/Dockerfile ships"
    # RCP2-01: gstack/Dockerfile uses pnpm dlx (not npm/npx)
    assert_file_contains "$HARNESSED_DIR/recipes/gstack/Dockerfile" "pnpm dlx" \
        "RCP2-01: recipe Dockerfile uses pnpm dlx"
    # RCP2-01: gstack-time stack references gstack recipe
    assert_file_contains "$HARNESSED_DIR/stacks/gstack-time/stack.yaml" "gstack" \
        "RCP2-01: stack references gstack recipe"
    # RCP2-02: harnesses: field in recipe.yaml
    assert_file_contains "$HARNESSED_DIR/recipes/gstack/recipe.yaml" "harnesses:" \
        "RCP2-02: harnesses field present"
    # RCP2-02: gstack declares claude harness
    assert_file_contains "$HARNESSED_DIR/recipes/gstack/recipe.yaml" "claude" \
        "RCP2-02: gstack declares claude harness"
    # RCP2-03: expect: field in recipe.yaml
    assert_file_contains "$HARNESSED_DIR/recipes/gstack/recipe.yaml" "expect:" \
        "RCP2-03: expect field present"
}

test_fixtures_exist() {
    arrange
    act
    assert
    # ASM-02 fixture: floating-recipe Dockerfile ships
    assert_exists "$HARNESSED_DIR/recipes/floating-recipe/Dockerfile" \
        "ASM-02 fixture: floating-recipe Dockerfile ships"
    # ASM-02 fixture: Dockerfile contains a floating --branch ref
    assert_file_contains "$HARNESSED_DIR/recipes/floating-recipe/Dockerfile" "--branch main" \
        "ASM-02 fixture: contains floating ref"
    # ASM-02 fixture: floating-test stack ships
    assert_exists "$HARNESSED_DIR/stacks/floating-test/stack.yaml" \
        "ASM-02 fixture: floating-test stack ships"
    # ASM-01 fixture: omp-gstack-test declares omp harness
    assert_file_contains "$HARNESSED_DIR/stacks/omp-gstack-test/stack.yaml" "omp" \
        "ASM-01 fixture: omp harness declared"
}

test_rescan_filter_coverage() {
    arrange
    local derived_name="harnessed-gstack-time:latest"
    act
    # Test that the derived image name matches the harnessed-* filter pattern (SC-02).
    [[ "$derived_name" =~ ^harnessed- ]]; local match_rc=$?
    assert
    assert_exit_zero "$match_rc" \
        "SC-02: harnessed-gstack-time matches harnessed-* filter"
    # Rescan script exists
    assert_exists "$HARNESSED_DIR/lib/harnessed-rescan.sh" \
        "SC-02: rescan script ships"
    # Rescan script uses the harnessed-* filter
    assert_file_contains "$HARNESSED_DIR/lib/harnessed-rescan.sh" "harnessed-*" \
        "SC-02: rescan uses harnessed-* filter"
}

test_socket_source_scan_coverage() {
    arrange
    act
    assert
    # SC-04 comment is present in harnessed-common.sh (documents coverage rationale)
    assert_file_contains "$HARNESSED_DIR/lib/harnessed-common.sh" "SC-04" \
        "SC-04: coverage comment present in build_stack()"
    # socket scan is token-gated in scan.py (warn-and-skip behavior)
    assert_file_contains "$HARNESSED_DIR/tools/harnessed/scan.py" "SOCKET_SECURITY_API_KEY" \
        "SC-04: socket scan is token-gated warn-skip in scan.py"
    # BLD-02a socket scan is wired in build_stack()
    assert_file_contains "$HARNESSED_DIR/lib/harnessed-common.sh" "socket" \
        "SC-04: BLD-02a socket scan wired in build_stack()"
}

# ─── Heavy tests (self-skip under --quick) ──────────────────────────────────

test_derived_image_build() {
    needs_container && { skip_test "skipped (--quick) — builds harnessed-gstack-time derived image"; return; }
    [ -z "$RT" ] && { skip_test "no container runtime found"; return; }
    arrange
    # Clean up stale image if present
    "$RT" rmi harnessed-gstack-time:latest 2>/dev/null || true
    act
    uat_run "$HARNESSED" build gstack-time
    assert
    assert_exit_zero "$UAT_RC" \
        "IMG-03: harnessed build gstack-time exits 0"
    assert_true "$RT" image inspect harnessed-gstack-time:latest \
        "IMG-03: harnessed-gstack-time:latest image exists"
    assert_exists "$HARNESSED_DIR/profiles/gstack-time/Dockerfile.harnessed-gstack-time" \
        "ASM-03: derived Dockerfile emitted"
    assert_file_contains "$HARNESSED_DIR/profiles/gstack-time/Dockerfile.harnessed-gstack-time" "ARG HARNESS" \
        "ASM-03: ARG HARNESS in derived Dockerfile"
}

test_snyk_container_skip() {
    needs_container && { skip_test "skipped (--quick) — requires built image"; return; }
    [ -z "$RT" ] && { skip_test "no container runtime found"; return; }
    arrange
    # Ensure gstack-time is built as a precondition (silent)
    "$HARNESSED" build gstack-time >/dev/null 2>&1 || true
    act
    uat_run env -u SNYK_TOKEN "$HARNESSED" build gstack-time
    assert
    assert_exit_zero "$UAT_RC" \
        "SC-03: build succeeds (snyk warns-and-skips without SNYK_TOKEN)"
    assert_contains "SNYK_TOKEN" "$UAT_OUT" \
        "SC-03: output mentions SNYK_TOKEN when skipping"
}

test_pin_validation_rejection() {
    needs_container && { skip_test "skipped (--quick) — requires tools image for assembler"; return; }
    [ -z "$RT" ] && { skip_test "no container runtime found"; return; }
    arrange
    act
    uat_run "$HARNESSED" build floating-test
    assert
    assert_exit_nonzero "$UAT_RC" \
        "ASM-02: floating ref rejected (build exits nonzero)"
    assert_contains "floating ref" "$UAT_OUT" \
        "ASM-02: error message names the floating ref"
    # Dockerfile must NOT have been emitted (rejection is pre-emission)
    assert_not_exists "$HARNESSED_DIR/profiles/floating-test/Dockerfile.harnessed-floating-test" \
        "ASM-02: Dockerfile NOT emitted on rejection"
}

test_harness_compat_rejection() {
    needs_container && { skip_test "skipped (--quick) — requires tools image for assembler"; return; }
    [ -z "$RT" ] && { skip_test "no container runtime found"; return; }
    arrange
    act
    uat_run "$HARNESSED" build omp-gstack-test
    assert
    assert_exit_nonzero "$UAT_RC" \
        "ASM-01: incompatible harness rejected (build exits nonzero)"
    assert_contains "gstack" "$UAT_OUT" \
        "ASM-01: error message names the recipe"
    # Dockerfile must NOT have been emitted (rejection is pre-emission)
    assert_not_exists "$HARNESSED_DIR/profiles/omp-gstack-test/Dockerfile.harnessed-omp-gstack-test" \
        "ASM-01: Dockerfile NOT emitted on rejection"
}

# ─── entrypoint ─────────────────────────────────────────────────────────────

uat_run_phase() {
    uat_suite "Phase 8 — Dockerfile Recipe Model + Assembler + Supply-Chain Gate"
    echo "  launcher: $HARNESSED  runtime: ${RT:-none}"
    [ "$UAT_QUICK" = "true" ] && echo "  --quick: only fast manifest/validation tests run (heavy tests skip)"

    run_test recipe_structure \
        "RCP2-01/02/03: gstack recipe structure (fast, no container)"
    run_test fixtures_exist \
        "ASM-01/02 fixtures: rejection test files ship (fast, no container)"
    run_test rescan_filter_coverage \
        "SC-02: harnessed-* filter covers harnessed-gstack-time (fast)"
    run_test socket_source_scan_coverage \
        "SC-04: socket source scan covers recipe dirs via BLD-02a (fast)"
    run_test derived_image_build \
        "IMG-03+ASM-03+SC-01: harnessed build gstack-time → image + Dockerfile (heavy)"
    run_test snyk_container_skip \
        "SC-03: snyk warns-and-skips without SNYK_TOKEN (heavy)"
    run_test pin_validation_rejection \
        "ASM-02: floating ref rejected before emission (heavy)"
    run_test harness_compat_rejection \
        "ASM-01: incompatible harness rejected before emission (heavy)"
}
