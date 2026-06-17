#!/usr/bin/env bash
# shellcheck shell=bash disable=SC2034 # UAT_OUT/UAT_RC are shared capture vars read by test fns
 # uat-common.sh — shared UAT harness: AAA section markers, pure-bash assertions,
# per-test pass/fail tracking, and a summary.
#
# A UAT test is a function named `test_<id>`. It is driven by `run_test <id> "<label>"`.
# Inside a test, structure the work with the three AAA markers and assert with the
# helpers below. No external deps (no bats, no grep) — matches the project's
# dependency-free ethos; pattern matching uses bash's [[ =~ ]] / [[ == *..* ]].
#
# Usage (from a phase suite script):
#   source "$HERE/uat-common.sh"
#   test_svc_up() {
#       arrange
#       uat_run "$HARNESSED" svc down ping --purge        # tolerate absence
#       act
#       uat_run "$HARNESSED" svc up ping
#       assert
#       assert_exit_zero "$UAT_RC" "svc up exits 0"
#       assert_match '0\.0\.0\.0:8080' "$UAT_OUT" "publishes its port"
#   }
#   run_test svc_up "svc up publishes port and lists"

# --- totals (do not reset between tests; summary is cumulative) ---
UAT_PASS=0
UAT_FAIL=0
UAT_SKIP=0
UAT_NUM=0
UAT_TEST_FAIL=0          # per-test flag: 1 once any assertion in the current test failed
UAT_TEST_SKIP=0          # per-test flag: 1 if the test asked to skip
UAT_FAILED_TESTS=()
UAT_SKIPPED_TESTS=()

# --- AAA section markers (purely visual; AAA is the discipline, not machinery) ---
arrange() { echo "  ▸ Arrange"; }
act()     { echo "  ▸ Act"; }
assert()  { echo "  ▸ Assert"; }

# --- outcome recorders ---
_uat_pass() { echo "    ✓ $1"; UAT_PASS=$((UAT_PASS + 1)); }
_uat_fail() { echo "    ✗ $1${2:+ :: $2}"; UAT_FAIL=$((UAT_FAIL + 1)); UAT_TEST_FAIL=1; }

# Skip the CURRENT test (call inside a test, then `return`).
skip_test() { echo "    ⊘ skip: $1"; UAT_TEST_SKIP=1; }

# --- assertions (all pure bash; record pass/fail, never abort) ---
assert_exit_zero()    { if [ "$1" -eq 0 ]; then _uat_pass "$2"; else _uat_fail "$2" "exit=$1"; fi; }
assert_exit_nonzero() { if [ "$1" -ne 0 ]; then _uat_pass "$2"; else _uat_fail "$2" "exit=0 (expected non-zero)"; fi; }

assert_eq() { # actual expected label
    if [ "$1" = "$2" ]; then _uat_pass "$3"; else _uat_fail "$3" "expected=[$2] actual=[$1]"; fi
}
assert_ne() { # actual unexpected label
    if [ "$1" != "$2" ]; then _uat_pass "$3"; else _uat_fail "$3" "actual=[$1] (expected != [$2])"; fi
}
assert_match() { # regex actual label
    if [[ $2 =~ $1 ]]; then _uat_pass "$3"; else _uat_fail "$3" "no match /$1/ in: ${2:0:160}"; fi
}
assert_not_match() { # regex actual label
    if [[ ! $2 =~ $1 ]]; then _uat_pass "$3"; else _uat_fail "$3" "unexpected match /$1/ in: ${2:0:160}"; fi
}
assert_contains() { # substring actual label
    if [[ $2 == *"$1"* ]]; then _uat_pass "$3"; else _uat_fail "$3" "missing [$1] in: ${2:0:160}"; fi
}
assert_not_contains() { # substring actual label
    if [[ $2 != *"$1"* ]]; then _uat_pass "$3"; else _uat_fail "$3" "unexpected [$1] in: ${2:0:160}"; fi
}
assert_exists()     { if [ -e "$1" ]; then _uat_pass "$2"; else _uat_fail "$2" "not found: $1"; fi; }
assert_not_exists() { if [ ! -e "$1" ]; then _uat_pass "$2"; else _uat_fail "$2" "still exists: $1"; fi; }
assert_file_contains() { # path substring label
    if [ -r "$1" ] && [[ $(cat "$1") == *"$2"* ]]; then _uat_pass "$3"; else _uat_fail "$3" "[$2] not in $1"; fi
}
assert_executable() { if [ -x "$1" ]; then _uat_pass "$2"; else _uat_fail "$2" "not executable: $1"; fi; }
# Boolean condition asserts: the LAST arg is the label; preceding args are the command.
assert_true()  { # cmd... label  (pass if cmd exits 0)
    local _lbl="${!#}"; local _cmd=("${@:1:$#-1}")
    if "${_cmd[@]}" >/dev/null 2>&1; then _uat_pass "$_lbl"; else _uat_fail "$_lbl" "condition false"; fi
}
assert_false() { # cmd... label  (pass if cmd exits non-zero)
    local _lbl="${!#}"; local _cmd=("${@:1:$#-1}")
    if ! "${_cmd[@]}" >/dev/null 2>&1; then _uat_pass "$_lbl"; else _uat_fail "$_lbl" "condition unexpectedly true"; fi
}

# --- command runner: captures UAT_OUT / UAT_RC, echoes the command ---
uat_run() { # cmd [args...]
    echo "    ▸ $*"
    UAT_OUT=$("$@" 2>&1); UAT_RC=$?
}
# Variant that runs with extra env (e.g. HARNESSED_HEADLESS=true). Pass env as first arg.
uat_run_env() { # "ENV=val ENV2=val2" cmd [args...]
    local envs="$1"; shift
    echo "    ▸ env $envs $*"
    # shellcheck disable=SC2086,SC2034 # word-split intentional; UAT_RC read by test fns
    UAT_OUT=$(env $envs "$@" 2>&1); UAT_RC=$?
}
# Print the captured output (indented) — use when a failing assertion needs context.
uat_show() {
    if [ -n "$UAT_OUT" ]; then
        while IFS= read -r _l; do echo "      | $_l"; done <<< "$UAT_OUT"
    fi
}

# --- test driver ---
run_test() { # id label
    local id="$1" label="$2"
    UAT_NUM=$((UAT_NUM + 1))
    UAT_TEST_FAIL=0
    UAT_TEST_SKIP=0
    echo
    echo "━━━ TEST $UAT_NUM: $label  ($id) ━━━"
    "test_$id"
    if [ "$UAT_TEST_SKIP" = "1" ]; then
        echo "  → SKIP"
        UAT_SKIP=$((UAT_SKIP + 1))
        UAT_SKIPPED_TESTS+=("$id")
    elif [ "$UAT_TEST_FAIL" = "0" ]; then
        echo "  → PASS"
    else
        echo "  → FAIL"
        UAT_FAILED_TESTS+=("$id")
    fi
}

# --- suite header ---
uat_suite() { # title
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║  UAT SUITE: $1"
    echo "╚══════════════════════════════════════════════════════════════╝"
}

# --- summary (call once at the end; returns 1 if any test failed) ---
uat_summary() {
    echo
    echo "════════════════════════════════════════════════════════════════"
    local _tp=$((UAT_NUM - ${#UAT_FAILED_TESTS[@]} - ${#UAT_SKIPPED_TESTS[@]}))
    printf "  TESTS:  %d passed, %d failed, %d skipped (%d total)\n" \
        "$_tp" "${#UAT_FAILED_TESTS[@]}" "${#UAT_SKIPPED_TESTS[@]}" "$UAT_NUM"
    printf "  CHECKS: %d passed, %d failed\n" "$UAT_PASS" "$UAT_FAIL"
    if [ "${#UAT_FAILED_TESTS[@]}" -gt 0 ]; then
        echo "  FAILED: ${UAT_FAILED_TESTS[*]}"
    fi
    if [ "${#UAT_SKIPPED_TESTS[@]}" -gt 0 ]; then
        echo "  SKIPPED: ${UAT_SKIPPED_TESTS[*]}"
    fi
    echo "════════════════════════════════════════════════════════════════"
    [ "${#UAT_FAILED_TESTS[@]}" -eq 0 ]
}

# --- container helpers (no-op safely if the runtime is absent) ---
uat_runtime() { command -v podman >/dev/null 2>&1 && echo podman || echo docker; }
uat_pod_rm()  { local rt; rt="$(uat_runtime)"; [ -n "$rt" ] && "$rt" pod rm -f "$1" >/dev/null 2>&1 || true; }
# Count running containers whose NAME contains the given substring.
uat_count() { # name-substring
    local rt; rt="$(uat_runtime)"; [ -n "$rt" ] || { echo 0; return; }
    "$rt" ps --filter "name=$1" --format '{{.Names}}' 2>/dev/null | wc -l | tr -d ' '
}
