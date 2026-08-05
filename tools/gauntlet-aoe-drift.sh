#!/usr/bin/env bash
# Every automatable gauntlet layer for bd harnessed-cn9, in one command.
#
#   tools/gauntlet-aoe-drift.sh [logdir]
#
# Layers NOT covered here, because this project/session cannot run them:
#   - static types, lint      : none configured in this repo (no [tool.mypy]/[tool.ruff], no CI job)
#   - property-based tests    : no hypothesis; substituted by the hostile-input table in
#                               tests/test_aoe.py::TestCommandDrift::test_is_ours_rejects_*
#   - randomized suite order  : no pytest-randomly; substituted by repeat + isolated runs below
#   - integration-tree rerun  : must be run by hand from the main checkout
set -uo pipefail

cd "$(dirname "$0")/.."
LOGDIR="${1:-.old-coder/logs}"
mkdir -p "$LOGDIR"
# Keep coverage's own dotfile out of the repo root; it is a byproduct, not a result.
export COVERAGE_FILE="$LOGDIR/.coverage"
rc=0

run() { # run <label> <logfile> <cmd...>
  printf '\n=== %s ===\n' "$1"
  shift
  local log="$1"; shift
  local start; start=$SECONDS
  if "$@" >"$log" 2>&1; then
    printf 'PASS (%ss)  log: %s\n' "$((SECONDS - start))" "$log"
    tail -1 "$log"
  else
    printf 'FAIL (%ss)  log: %s\n' "$((SECONDS - start))" "$log"
    tail -15 "$log"
    rc=1
  fi
}

run "full suite + coverage" "$LOGDIR/final-suite.log" \
  tools/run-tests.sh --cov=harnessed.aoe --cov=harnessed.launcher \
  --cov-report="json:$LOGDIR/cov.json" -q

run "changed-line coverage" "$LOGDIR/changed-line-coverage.log" \
  python3 tools/changed-line-coverage.py "$LOGDIR/cov.json" main

run "mutation" "$LOGDIR/mutants.log" tools/mutants_aoe_drift.py

run "real execution (drives the real aoe)" "$LOGDIR/real-exec.log" \
  tools/real-exec-aoe-drift.py

run "suite health: repeat run" "$LOGDIR/repeat-2.log" tools/run-tests.sh -q
run "suite health: module in isolation" "$LOGDIR/isolated.log" \
  tools/run-tests.sh tests/test_aoe.py -q
run "suite health: cross-module order" "$LOGDIR/crossorder.log" \
  tools/run-tests.sh tests/test_aoe.py tests/test_launch_host.py tests/test_capmatrix.py -q

printf '\n=== gauntlet %s ===\n' "$([ $rc -eq 0 ] && echo PASSED || echo FAILED)"
exit $rc
