#!/usr/bin/env bash
# Re-run every gauntlet layer cited in the scan-noise evidence report.
#
# One entry point, because a report whose numbers cannot be reproduced from the repo alone stops
# being evidence the moment someone relies on it INSTEAD of reading the code.
#
# Usage: tools/gauntlet-scan-noise.sh [logdir]
#
# Exit code is the count of FAILED layers, so `echo $?` is the whole summary. Layers that are
# structurally unavailable for this change (see below) print UNAVAILABLE or SUBSTITUTED and do not
# count as failures — but they are printed every run, so nobody can mistake the report for full
# coverage.
#
# THE STRUCTURAL PROBLEM THIS CHANGE HAS. The logic under test is a Python program embedded in a
# bash heredoc inside catalog/base/harnessed-scan, plus the bash around it. The project's static
# half — ruff, pyright, mutmut — all address `src/harnessed/*.py` and cannot see any of it. And
# CI's shellcheck job runs `shellcheck $(git ls-files '*.sh')`, which does not match an
# extensionless script, so the file gets no shell linting in CI either. Layer 1 runs it by path.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 2

LOGDIR="${1:-.old-coder/gauntlet-scan-noise-$(date -u +%Y%m%d-%H%M%S)}"
mkdir -p "$LOGDIR"   # BEFORE any redirect: a redirect into a missing dir runs the command not at
                     # all, leaving an EVIDENCE row citing a log path that was never written.
echo "logs -> $LOGDIR"

SCAN=catalog/base/harnessed-scan
SCAN_TESTS=(
    tests/test_scan_acknowledged.py
    tests/test_scan_osv_no_lockfiles.py
    tests/test_scan_ledger_reconciliation.py
    tests/test_scan_corepack_removed.py
    tests/test_scan_coverage_reporting.py
    tests/test_scan_socket_parser.py
    tests/test_scan.py
)

FAILED=0
pass() { printf '  PASS         %s\n' "$1"; }
fail() { printf '  FAIL         %s\n' "$1"; FAILED=$((FAILED + 1)); }
note() { printf '  %-12s %s\n' "$1" "$2"; }

# ---------------------------------------------------------------------------
echo
echo "L1  shellcheck (by path — CI's '*.sh' glob does not match this file)"
if mise exec -- shellcheck -s bash "$SCAN" >"$LOGDIR/shellcheck.log" 2>&1; then
    pass "shellcheck $SCAN: clean"
else
    fail "shellcheck $SCAN — see $LOGDIR/shellcheck.log"
fi

# NEGATIVE CONTROL. shellcheck is off-the-shelf and has earned its failure behavior, but this
# invocation is hand-written: `-s bash` on an extensionless path is exactly the sort of thing that
# silently analyses nothing. Prove the command as invoked can go red before trusting its green.
CTRL="$LOGDIR/shellcheck-negative-control.sh"
# shellcheck disable=SC2016  # the single quotes are the point: $bar must reach the control file
# LITERALLY, as the unassigned variable shellcheck is meant to flag. Expanding it here would write
# an empty string and the control would pass, which is the exact failure it exists to rule out.
printf '#!/usr/bin/env bash\nfoo="1"\necho $bar\n' >"$CTRL"
if mise exec -- shellcheck -s bash "$CTRL" >"$LOGDIR/shellcheck-control.log" 2>&1; then
    fail "shellcheck negative control PASSED on known-bad input — the layer proves nothing"
else
    pass "shellcheck negative control went red as expected"
fi

# ---------------------------------------------------------------------------
echo
echo "L2  ruff"
# `src tests tools`, verbatim from .github/workflows/lint.yml — NOT `.`. The first version of this
# layer guessed `ruff check .` and duly went red on a pre-existing S104 in catalog/services/ping
# and on markdown code blocks under .agents/plans, neither of which this change touches and
# neither of which the project gates. A guessed command produces confident, wrong evidence.
#
# `ruff format --check` is deliberately absent for the same reason: the repo does not gate
# formatting anywhere, so running it here would invent a standard and then report failing it.
if mise exec -- uv run --extra dev ruff check src tests tools >"$LOGDIR/ruff.log" 2>&1; then
    pass "ruff check src tests tools: clean"
else
    fail "ruff check — see $LOGDIR/ruff.log"
fi
note "N-A" "ruff cannot see the python inside $SCAN's heredoc"

# ---------------------------------------------------------------------------
echo
echo "L3  pyright"
# CI's exact invocation. A bare `pyright` happens to work for a developer because mise activates
# the venv and pyright inherits VIRTUAL_ENV, but that makes the result depend on shell state — and
# a number in an evidence report must not. --pythonpath pins the interpreter explicitly.
PYPATH="$(mise exec -- uv run --extra dev python -c 'import sys; print(sys.executable)')"
if mise exec -- pyright --pythonpath "$PYPATH" >"$LOGDIR/pyright.log" 2>&1; then
    pass "pyright: clean"
else
    fail "pyright — see $LOGDIR/pyright.log"
fi
note "N-A" "pyright cannot see the python inside $SCAN's heredoc"

# ---------------------------------------------------------------------------
echo
echo "L4  full test suite"
tools/run-tests.sh >"$LOGDIR/tests-full.log" 2>&1
# The repo carries 3 PRE-EXISTING failures in tests/test_aoe_real.py at the branch point. The bar
# is zero NEW failures, never exit 0 — so count them by name rather than trusting the exit code.
NEWFAIL=$(grep -c '^FAILED' "$LOGDIR/tests-full.log" 2>/dev/null || true)
OLDFAIL=$(grep -c '^FAILED tests/test_aoe_real.py' "$LOGDIR/tests-full.log" 2>/dev/null || true)
note "INFO" "$(tail -1 "$LOGDIR/tests-full.log")"
if [[ "$NEWFAIL" == "$OLDFAIL" ]]; then
    pass "zero NEW failures ($OLDFAIL pre-existing in tests/test_aoe_real.py)"
else
    fail "$((NEWFAIL - OLDFAIL)) NEW failure(s) — see $LOGDIR/tests-full.log"
fi

# ---------------------------------------------------------------------------
echo
echo "L5  changed-line coverage"
# UNAVAILABLE, and not for want of a tool. diff-cover is declared and works, but it maps a coverage
# report onto the branch diff by FILE PATH. Every changed line here lives either in bash or in a
# python heredoc that only becomes a .py file when a test extracts it to a temp path, so there is
# no path for either coverage.py or diff-cover to bind to. Building a mapping from heredoc offsets
# back to file lines would be a checker I wrote, which is the one thing this loop forbids.
#
# The mutation layer below is the substitute, and is strictly stronger where it reaches: coverage
# proves a line RAN, a killed mutant proves a test ASSERTS on it. Its blind spot is the difference
# between the two — mutation only covers lines someone chose to mutate, where coverage would have
# enumerated every line mechanically. That is why the mutant list is audited against the diff
# hunks rather than just counted.
note "UNAVAIL" "diff-cover/coverage.py cannot bind to bash or to heredoc'd python"
note "SUBST" "mutation (L6) — covers assertion strength, NOT line enumeration"

# ---------------------------------------------------------------------------
echo
echo "L6  mutation"
note "SUBST" "mutmut is declared but generates from src/ ASTs; it cannot reach a bash heredoc"
if tools/mutants_scan_noise.py >"$LOGDIR/mutation.log" 2>&1; then
    pass "$(tail -1 "$LOGDIR/mutation.log")"
else
    fail "mutation survivors — see $LOGDIR/mutation.log"
fi

# ---------------------------------------------------------------------------
echo
echo "L7  suite health (randomized order)"
HEALTH_OK=1
for seed in 1 2 3; do
    if ! tools/run-tests.sh "${SCAN_TESTS[@]}" -q -p randomly \
            -p "no:cacheprovider" --randomly-seed=$seed \
            >"$LOGDIR/health-seed$seed.log" 2>&1; then
        HEALTH_OK=0
        note "INFO" "seed $seed FAILED"
    fi
done
if [[ $HEALTH_OK -eq 1 ]]; then
    pass "scan suite green under 3 distinct random orders (seeds 1/2/3)"
else
    fail "order-dependent test — see $LOGDIR/health-seed*.log"
fi

# ---------------------------------------------------------------------------
echo
echo "L8  real execution"
# The layer that has actually found things here. A green suite says the code does what the tests
# say; running the real script says what an operator will see.
if tools/scan-real-run.sh "$LOGDIR" >"$LOGDIR/real-run.log" 2>&1; then
    pass "real harnessed-scan run produced the expected summary"
else
    fail "real run — see $LOGDIR/real-run.log"
fi

# ---------------------------------------------------------------------------
echo
echo "L9  supply chain"
note "N-A" "this change adds no dependency (pyproject.toml untouched)"
if mise exec -- uv run --extra dev pip-audit >"$LOGDIR/pip-audit.log" 2>&1; then
    pass "pip-audit: clean"
else
    note "INFO" "pip-audit non-zero — see $LOGDIR/pip-audit.log (pre-existing, not gated here)"
fi

echo
echo "=========================================================="
echo "  $FAILED layer(s) FAILED"
echo "  logs -> $LOGDIR"
exit "$FAILED"
