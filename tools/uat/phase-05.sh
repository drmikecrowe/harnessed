#!/usr/bin/env bash
# phase-05.sh — UAT suite for Phase 5 (secrets, hardening + docs completeness).
#
# Sourced by run-uat.sh (after uat-common.sh). Defines test_<id> functions and a
# uat_run_phase entrypoint. Every test follows Arrange → Act → Assert (AAA).
#
# Covers the AUTOMATABLE behavior of SEC-01..04 + DOC-01..03 by driving the real
# `harnessed` CLI (the project verifies behavior transitively through the running
# instance — assembler unit tests are out of scope per REQUIREMENTS.md). The live
# legs that need a 1Password desktop app / interactive browser / an overnight timer
# fire are NOT scriptable here and are tracked as manual-only in 05-HUMAN-UAT.md:
#   - SEC-01 live op:// resolution → pod env (HV-1)
#   - SEC-01 build scan with a 1Password-resolved token (HV-2)
#   - SEC-03 live snyk/socket browser-auth persistence (HV-3)
#   - SEC-04 overnight timer firing + `loginctl enable-linger` (HV-4)
#
# Heavy tests (build / rescan — they run the tools container) self-skip under `--quick`.
# Secret-resolution tests point HARNESSED_SCHEMA at a NONEXISTENT path so they exercise
# the inert / no-token paths WITHOUT touching the operator's real ~/.config/harnessed.

RT="$(uat_runtime)"   # podman | docker | "" (empty if neither present)

needs_container() { [ "$UAT_QUICK" = "true" ]; }   # true ⇒ this heavy test should skip

# A schema path that is guaranteed absent → forces resolve_secret_env's inert / no-secret
# path regardless of whether the operator has a real ~/.config/harnessed/.env.schema.
UAT_NO_SCHEMA="/nonexistent/harnessed-uat-$$/.env.schema"

# ─── Section A: Secrets & Hardening (SEC-01..04) ───────────────────────────────

# SEC-01 inertness + SEC-02 warn-and-skip, in one build (no schema, no token).
test_secrets_inert_and_skip() {
    needs_container && { skip_test "skipped (--quick) — runs the tools container"; return; }
    arrange
    act
    uat_run_env "HARNESSED_SCHEMA=$UAT_NO_SCHEMA" "$HARNESSED" build tracer-time
    assert
    assert_exit_zero "$UAT_RC" "build is non-interactive + green with no schema/token"
    # SEC-01: absent a schema, varlock is NEVER invoked (no resolution banner).
    assert_not_contains "Resolving secrets via varlock" "$UAT_OUT" "SEC-01: varlock inert when no schema"
    # SEC-02: absent a token, the scanner warns-and-skips (does not prompt, does not fail).
    assert_contains "snyk skipped (no SNYK_TOKEN)" "$UAT_OUT" "SEC-02: snyk warns-and-skips without a token"
}

# SEC-02 token-present: a token forwarded from the launcher env reaches the scan step,
# so snyk is INVOKED (not the no-token skip). A bogus token's auth failure is a WARNING,
# never an abort (the build stays green) — that is the SEC-02 non-interactive contract.
test_scanner_token_invoked() {
    needs_container && { skip_test "skipped (--quick) — runs the tools container"; return; }
    arrange
    act
    uat_run_env "HARNESSED_SCHEMA=$UAT_NO_SCHEMA SNYK_TOKEN=dummy-uat-token" "$HARNESSED" build tracer-time
    assert
    assert_exit_zero "$UAT_RC" "build stays green even when the token is bogus (auth-fail → warn, not abort)"
    assert_not_contains "snyk skipped (no SNYK_TOKEN)" "$UAT_OUT" "SEC-02: a present token is forwarded (snyk invoked, not skipped)"
}

# SEC-03 dispatch validation: `harnessed auth` accepts only snyk|socket and rejects
# anything else (and a missing tool) with a clear error — the collision-safe top-level
# command. The live browser-auth persistence is manual (HV-3).
test_auth_dispatch() {
    arrange
    act
    uat_run "$HARNESSED" auth bogus
    assert
    assert_exit_nonzero "$UAT_RC" "auth rejects an unknown tool"
    assert_contains "auth requires snyk|socket" "$UAT_OUT" "auth reports the snyk|socket contract"
    act
    uat_run "$HARNESSED" auth
    assert
    assert_exit_nonzero "$UAT_RC" "auth with no tool exits non-zero"
    assert_contains "auth requires snyk|socket" "$UAT_OUT" "auth with no tool reports the contract"
}

# SEC-04 nightly re-scan: `harnessed rescan` runs the ONLINE image scan over installed
# harnessed-* images (the timer's ExecStart). Online = contacts osv.dev for newly-disclosed
# CVEs (drops the build-time --offline flags). Clean images → exit 0.
test_rescan_online() {
    needs_container && { skip_test "skipped (--quick) — scans every harnessed image online"; return; }
    [ -n "$RT" ] || { skip_test "no container runtime"; return; }
    arrange
    act
    uat_run "$HARNESSED" rescan
    assert
    assert_exit_zero "$UAT_RC" "rescan exits 0 when no HIGH is found"
    assert_match 'online|[Ss]upply-chain|scan' "$UAT_OUT" "rescan performs an (online) image scan"
}

# SEC-04 timer units: the shipped systemd USER units are well-formed and carry the
# load-bearing fields + the linger prerequisite. (The overnight firing itself is manual, HV-4.)
test_rescan_timer_units() {
    local svc="$HARNESSED_DIR/systemd/harnessed-rescan.service"
    local tmr="$HARNESSED_DIR/systemd/harnessed-rescan.timer"
    arrange
    act
    assert
    assert_exists "$svc" "rescan.service unit ships"
    assert_exists "$tmr" "rescan.timer unit ships"
    assert_file_contains "$svc" "Type=oneshot" "service is a oneshot"
    assert_file_contains "$svc" "ExecStart=%h/.local/bin/harnessed rescan" "service ExecStart drives the rescan command (rootless %h)"
    assert_file_contains "$tmr" "OnCalendar=daily" "timer runs daily"
    assert_file_contains "$tmr" "Persistent=true" "timer catches missed runs (Persistent)"
    assert_file_contains "$tmr" "WantedBy=timers.target" "timer installs to the user timers target"
    assert_file_contains "$tmr" "enable-linger" "timer documents the loginctl enable-linger prerequisite"
}

# ─── Section B: Documentation (DOC-01..03) ─────────────────────────────────────

test_doc_readme() {
    local f="$HARNESSED_DIR/README.md"
    arrange
    act
    assert
    assert_exists "$f" "README.md ships at the repo root"
    assert_file_contains "$f" "transparent" "README documents the transparent mode"
    assert_file_contains "$f" "isolated" "README documents the isolated mode"
    assert_file_contains "$f" "harnessed build" "README documents the first-run build"
    assert_file_contains "$f" "podman" "README states the podman-only host dependency"
}

test_doc_authoring_guides() {
    local rec="$HARNESSED_DIR/docs/guides/recipe-authoring.md"
    local stk="$HARNESSED_DIR/docs/guides/stacks.md"
    arrange
    act
    assert
    assert_exists "$rec" "recipe-authoring guide ships"
    assert_exists "$stk" "stacks guide ships"
    assert_file_contains "$rec" "recipe.yaml" "recipe guide documents the recipe manifest"
    assert_file_contains "$stk" "stack.yaml" "stacks guide documents the stack manifest"
    # The worked examples the guides cite must exist on disk (no phantom references).
    assert_exists "$HARNESSED_DIR/recipes/time/recipe.yaml" "cited recipe example (recipes/time) exists"
    assert_exists "$HARNESSED_DIR/stacks/tracer-time/stack.yaml" "cited stack example (stacks/tracer-time) exists"
}

test_doc_ops_guides() {
    local sec="$HARNESSED_DIR/docs/guides/secrets.md"
    local svc="$HARNESSED_DIR/docs/guides/service-authoring.md"
    local tbl="$HARNESSED_DIR/docs/guides/troubleshooting.md"
    arrange
    act
    assert
    assert_exists "$sec" "secrets guide ships"
    assert_exists "$svc" "service-authoring guide ships"
    assert_exists "$tbl" "troubleshooting guide ships"
    # secrets.md must describe the corrected HOST-side resolution model + where to get a Snyk token.
    assert_file_contains "$sec" "on the host" "secrets guide states resolution runs on the host"
    assert_file_contains "$sec" "app.snyk.io/account/personal-access-tokens" "secrets guide links the Snyk PAT page"
    assert_file_contains "$sec" "OP_SERVICE_ACCOUNT_TOKEN" "secrets guide documents the headless fallback"
    # troubleshooting.md must carry the SEC-04 linger prerequisite + the service triple.
    assert_file_contains "$tbl" "enable-linger" "troubleshooting guide carries the linger prerequisite"
    assert_exists "$HARNESSED_DIR/services/ping/service.yaml" "cited service example (services/ping) exists"
}

# ─── entrypoint ────────────────────────────────────────────────────────────────
uat_run_phase() {
    uat_suite "Phase 5 — Secrets, Hardening + Docs Completeness"
    echo "  launcher: $HARNESSED  runtime: ${RT:-none}"
    [ -z "$RT" ] && echo "  ⚠ no container runtime found — build/rescan tests will skip/fail"
    echo "  manual-only legs (live 1Password / browser / overnight): see 05-HUMAN-UAT.md (HV-1..HV-4)"

    run_test secrets_inert_and_skip   "SEC-01 inert (no schema) + SEC-02 warn-and-skip (no token)"
    run_test scanner_token_invoked    "SEC-02 a present token is forwarded (snyk invoked, build green)"
    run_test auth_dispatch            "SEC-03 auth accepts only snyk|socket"
    run_test rescan_online            "SEC-04 rescan runs the online image scan"
    run_test rescan_timer_units       "SEC-04 timer/service units well-formed + linger prereq"
    run_test doc_readme               "DOC-01 README documents modes/install/build/quickstart"
    run_test doc_authoring_guides     "DOC-02 recipe + stack guides exist, cite real examples"
    run_test doc_ops_guides           "DOC-03 secrets/service/troubleshooting guides + host-side model"
}
