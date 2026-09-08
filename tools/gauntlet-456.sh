#!/usr/bin/env bash
# Gauntlet entry point for #456 (runtime-aware --userns).
#
# One command that reruns every layer EVIDENCE.md cites, so the report is reproducible from the
# repo alone rather than from a transcript. Layers run in cost order: the three merge-gate checks
# first (seconds), then the suite, then coverage, then mutation (minutes).
#
# MERGE-GATE PARITY IS THE POINT of the first three: each is transcribed from
# .github/workflows/lint.yml VERBATIM, arguments included. `pyright src/` is not a cheaper
# `pyright` -- it is a different check over a different file set, and the difference is invisible in
# a row that reports "0 errors". If a command here drifts from the workflow, this script is wrong,
# not the workflow.
#
# FAIL CLOSED. No `|| true`, no `2>/dev/null`, no swallowed exit codes: a layer that cannot run is
# a failed layer, never a passed one. `set -euo pipefail` is what makes that true rather than
# intended.
set -euo pipefail

cd "$(dirname "$0")/.."
LOGS="${GAUNTLET_LOGS:-.old-coder/20260907-141233-issue-456-docker-userns/logs}"
mkdir -p "$LOGS"

# The base to diff against for the changed-line layers. Overridable so the script keeps working
# after the branch is rebased or renamed.
BASE="${GAUNTLET_BASE:-main}"

# Layers that failed, collected rather than aborted on — see `run`.
FAILED_LAYERS=""

run() {
  local name="$1"; shift
  printf '\n=== %s ===\n' "$name"
  # `|| rc=$?` rather than a bare call: under `set -e` a failing layer would abort the script
  # before the tail below ever printed, so a red run would name no layer and show no output. This
  # captures the code, reports it, and then returns it -- the caller is still under `set -e`, so
  # the script still stops. Fail-closed AND legible, rather than one or the other.
  local rc=0
  "$@" > "$LOGS/gauntlet-$name.log" 2>&1 || rc=$?
  printf '%s exit=%d (%s)\n' "$name" "$rc" "$LOGS/gauntlet-$name.log"
  tail -3 "$LOGS/gauntlet-$name.log"
  # RECORD the failure and CONTINUE, rather than aborting the run.
  #
  # Fail-fast was wrong here, and measured wrong three times: diff-cover going red meant the two
  # randomised-order runs and the entire mutation layer never executed, so the report could say
  # nothing about them at all. A gauntlet exists to tell you the state of EVERY layer; one that
  # stops at the first red tells you the state of one. Still fail-CLOSED — each failure is
  # remembered and the script exits nonzero at the end — just no longer fail-EARLY.
  if [ "$rc" -ne 0 ]; then
    FAILED_LAYERS="$FAILED_LAYERS $name"
  fi
  return 0
}

# --- merge gate: lint.yml ---------------------------------------------------------------------
run ruff mise exec -- uv run --extra dev ruff check src tests tools

PYEXE="$(mise exec -- uv run --extra dev python -c 'import sys; print(sys.executable)')"
run pyright mise exec -- pyright --pythonpath "$PYEXE"

# `git ls-files` rather than a glob: catalog/**/*.sh runs INSIDE recipe images as root, and those
# are the scripts most worth checking and least often read. Matches the workflow exactly.
mapfile -t SH_FILES < <(git ls-files '*.sh')
run shellcheck shellcheck "${SH_FILES[@]}"

# --- merge gate: test.yml ---------------------------------------------------------------------
# Via run-tests.sh, which CLAUDE.md mandates: it builds the per-branch venv and absorbs three traps
# that fail locally while CI stays green. The workflow's bare `uv run --extra dev pytest` is the
# same suite; the wrapper is the supported way to invoke it here.
run pytest tools/run-tests.sh

# --- coverage on CHANGED lines ------------------------------------------------------------------
# Global % is vanity. The constraint is that every line this branch touched was executed by a test,
# and --fail-under makes the layer EXIT NONZERO when it is not -- a layer that prints a percentage
# and exits 0 is a report, not a gate.
run coverage-xml mise exec -- uv run --extra dev pytest --cov=harnessed --cov-report=xml:"$LOGS/coverage.xml"
run diff-cover mise exec -- uv run --extra dev diff-cover "$LOGS/coverage.xml" \
  --compare-branch "$BASE" --fail-under 100

# --- suite health -------------------------------------------------------------------------------
# Every count above rests on the suite being deterministic. pytest-randomly reorders by default;
# these two seeds are fixed so a failure is reproducible rather than a story about one bad run.
run random-seed-1 mise exec -- uv run --extra dev pytest -p randomly -p no:cacheprovider --randomly-seed=1
run random-seed-2 mise exec -- uv run --extra dev pytest -p randomly -p no:cacheprovider --randomly-seed=2

# --- mutation ------------------------------------------------------------------------------------
# Does a test FAIL when the code is broken, or does it merely execute the line? Coverage cannot
# tell those apart, which is why a 100%-covered change can still be untested.
#
# SCOPE IS DERIVED, NOT TYPED: the changed source files come from `git diff --name-only`, so the
# glue is mutated along with the new logic. `mutmut` names mutants
# `harnessed.<module>.x_<function>__mutmut_N`, and a filter that matches nothing is SILENT -- it
# exits 0, builds the tree, and reports every mutant `not checked`, which reads exactly like a
# clean run. The `results` call below is what distinguishes those two.
#
# HARNESSED_DIR is required: `harnessed_home()` resolves through the `src/harnessed/catalog`
# symlink, which does not exist in the mutants tree (pyproject.toml documents this).
printf '\n=== mutation scope (derived) ===\n'
git diff --name-only "$BASE"...HEAD -- 'src/harnessed/*.py' | tee "$LOGS/mutation-scope.txt"

# `mutmut run` with the committed `tests_dir = ["tests/"]` cannot even establish a baseline here:
# mutmut's copy DEREFERENCES symlinks, so `.agents/skills/harnessed-catalog` arrives in the mutants
# tree as a real directory and `test_dynstack.py::test_the_default_recipe_ships_the_authoring_skill`
# fails on `link.is_symlink()`. The runner then reports `failed to collect stats` and no mutant is
# ever executed. This is a PRE-EXISTING repo limitation, documented in pyproject.toml's own
# [tool.mutmut] comment, which prescribes narrowing `tests_dir` for a targeted run -- not something
# this change introduced.
#
# mutmut 3 exposes no `--tests-dir`, so the narrowing has to be written into pyproject.toml. Doing
# it HERE, with a trap, rather than by hand: EVIDENCE has to cite a command that reproduces, and a
# report whose mutation row depends on an undocumented manual edit does not reproduce. The trap
# restores the file on every exit path, including a failed layer or a Ctrl-C.
MUT_TESTS='tests_dir = ["tests/test_docker_userns.py", "tests/test_userns_mapping.py", "tests/test_userns_properties.py", "tests/test_persist_allowlist.py", "tests/test_exec_verbs.py", "tests/test_launch_parity.py"]'
cp pyproject.toml "$LOGS/pyproject.toml.orig"
restore_pyproject() { cp "$LOGS/pyproject.toml.orig" pyproject.toml; }
trap restore_pyproject EXIT INT TERM
python3 - "$MUT_TESTS" <<'EOF'
import sys, pathlib
p = pathlib.Path("pyproject.toml")
s = p.read_text()
old = 'tests_dir = ["tests/"]'
assert s.count(old) == 1, f"expected exactly one {old!r}, found {s.count(old)}"
p.write_text(s.replace(old, sys.argv[1]))
EOF

# THE MUTANTS TREE IS DELETED FIRST, DELIBERATELY. mutmut caches its test->function mapping in
# `mutants/`, and a stale tree reports newly-covered functions as `🫥 no tests` -- it does not
# re-collect stats for tests that did not exist when the tree was built. Measured here: 30 mutants
# across `_detect_runtime` and `_probe_docker_rootless` sat at `no tests` through two full runs
# with passing tests calling them directly, and only a fresh tree attributed them. A cache that
# reports "nothing tests this" when something does is a fail-open in the layer that exists to
# catch fail-opens.
if [ -d mutants ]; then rm -r mutants; fi

# One filter per CHANGED function, derived from the diff above rather than from where the logic
# feels like it lives. mutmut names mutants `harnessed.<module>.x_<function>__mutmut_N`; a filter
# matching nothing is SILENT (exit 0, every mutant `not checked`), which is why `mutmut results`
# runs unconditionally afterwards and its output is read, not just its exit code.
run mutmut env HARNESSED_DIR="$PWD" mise exec -- uv run --extra dev mutmut run \
  'harnessed.paths.x__detect_runtime*' \
  'harnessed.paths.x_userns_args*' \
  'harnessed.paths.x__probe_docker_rootless*' \
  'harnessed.paths.x_pod_host_uid*' \
  'harnessed.persist.x_guard_ownership*' \
  'harnessed.ctrquery.x__runtime*' \
  'harnessed.launcher.x__preflight_runtime*' \
  'harnessed.launcher.x__without_userns*'

run mutmut-results env HARNESSED_DIR="$PWD" mise exec -- uv run --extra dev mutmut results

restore_pyproject
trap - EXIT INT TERM

run mutation-verdict "$(dirname "$0")/mutation-verdict-456.sh" "$LOGS/gauntlet-mutmut.log"

if [ -n "$FAILED_LAYERS" ]; then
  printf '\nFAILED LAYERS:%s\n' "$FAILED_LAYERS"
  exit 1
fi
printf '\nall layers passed\n'
