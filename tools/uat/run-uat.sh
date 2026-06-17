#!/usr/bin/env bash
# run-uat.sh — drives a phase's UAT suite.
#
# Usage:
#   ./tools/uat/run-uat.sh <phase>          # run the full phase suite
#   ./tools/uat/run-uat.sh <phase> --quick  # run only the fast (non-container) tests
#
# Each phase suite is tools/uat/phase-<NN>.sh and defines test_<id> functions plus a
# `uat_run_phase` entrypoint that calls run_test for each (honoring UAT_QUICK).
# Exit code is non-zero if any test failed.
set -uo pipefail

USAGE="usage: $0 <phase> [--quick]   (e.g. $0 4   or   $0 04 --quick)"

HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=tools/uat/uat-common.sh
. "$HERE/uat-common.sh"

PHASE=""
TEST_ONLY=""
UAT_QUICK=false
for a in "$@"; do
    case "$a" in
        --quick) UAT_QUICK=true ;;
        -h|--help)
            echo "$USAGE"
            echo "  <phase>     phase number (4, 04, or phase-04)"
            echo "  [test_id]   run only one test (e.g. svc_up); omit for the whole phase"
            echo "  --quick     skip heavy container-launch tests"
            exit 0
            ;;
        *) if [ -z "$PHASE" ]; then PHASE="$a"; else TEST_ONLY="$a"; fi ;;
    esac
done
export UAT_QUICK

if [ -z "$PHASE" ]; then
    echo "$USAGE" >&2
    exit 2
fi

# Normalize 4 / 04 / phase-04 → "04" (pure bash; no sed).
PHASE="${PHASE#phase-}"
PHASE="${PHASE#0}"
if [[ $PHASE =~ ^[0-9]+$ ]]; then PHASE="$(printf '%02d' "$PHASE")"; fi

SUITE="$HERE/phase-$PHASE.sh"
if [ ! -f "$SUITE" ]; then
    echo "error: no UAT suite for phase $PHASE ($SUITE)" >&2
    _s=""; for _f in "$HERE"/phase-*.sh; do [ -f "$_f" ] && _s+="$(basename "$_f") "; done
    echo "available: ${_s:-<none>}" >&2
    exit 2
fi

# Resolve the harnessed launcher + repo root so tests call the real CLI.
HARNESSED_DIR="$(cd "$HERE/../.." && pwd)"; export HARNESSED_DIR
export HARNESSED="$HARNESSED_DIR/harnessed"
if [ ! -x "$HARNESSED" ]; then
    echo "error: launcher not executable: $HARNESSED" >&2
    exit 2
fi

# shellcheck source=tools/uat/phase-04.sh
. "$SUITE"
if [ -n "$TEST_ONLY" ]; then
    if ! declare -F "test_$TEST_ONLY" >/dev/null 2>&1; then
        echo "error: no test '$TEST_ONLY' in phase $PHASE (no test_$TEST_ONLY function)" >&2
        exit 2
    fi
    run_test "$TEST_ONLY" "$TEST_ONLY"
else
    uat_run_phase
fi
uat_summary
