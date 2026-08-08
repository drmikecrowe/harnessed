#!/usr/bin/env bash
# Re-run every gauntlet layer cited in the bd harnessed-1ao evidence report.
#
# One entry point, because a report whose numbers cannot be reproduced from the repo alone stops
# being evidence the moment someone relies on it INSTEAD of reading the code.
#
# Layers that need a baseline (lint, types) are non-zero on this repo by design: both tools carry a
# large pre-existing backlog and neither runs in CI, so the bar is "zero NEW findings against the
# branch point", never "exit 0". This script prints both numbers and leaves the comparison to you —
# it deliberately does not exit non-zero on a pre-existing finding, because an agent that reads that
# as failure starts deleting other people's findings to get green.
#
# Usage: tools/gauntlet-1ao.sh [logdir]
set -uo pipefail

# REFUSE TO RUN ON A DIRTY TREE. Step 5 reverts src/ to the branch point and step 7 rewrites
# pyproject; both are undone with `git checkout`, which is destructive to uncommitted edits to those
# same paths. Rather than try to preserve someone's work-in-progress, decline the run.
if ! git diff --quiet -- src pyproject.toml || ! git diff --cached --quiet -- src pyproject.toml; then
  echo "refusing to run: uncommitted changes under src/ or in pyproject.toml." >&2
  echo "This script reverts both to measure a baseline and would discard them. Commit or set them aside first." >&2
  exit 2
fi

# Two steps below deliberately mutate TRACKED files, and one MOVES new test files out of the tree.
# Each undoes itself, but only if it is reached: a Ctrl-C in between would otherwise leave the tree
# holding baseline source, a rewritten pyproject, or — worst, because it is silent — the branch's new
# tests simply missing. The trap makes every restore unconditional, and is armed before each step
# touches anything. It is idempotent and harmless when nothing was touched.
_RESTORE=""
_STASHDIR=""
_NEW_TESTS=""
_cleanup() {
  # shellcheck disable=SC2086
  [ -n "$_RESTORE" ] && git checkout HEAD -- pyproject.toml $_RESTORE 2>/dev/null
  git checkout HEAD -- pyproject.toml 2>/dev/null
  if [ -n "$_STASHDIR" ] && [ -d "$_STASHDIR" ]; then
    for f in $_NEW_TESTS; do
      [ -f "$_STASHDIR/$(basename "$f")" ] && mv "$_STASHDIR/$(basename "$f")" "$f"
    done
    rmdir "$_STASHDIR" 2>/dev/null
  fi
  return 0
}
trap _cleanup EXIT INT TERM

LOGDIR="${1:-.old-coder/gauntlet-1ao-$(date -u +%Y%m%d-%H%M%S)}"
mkdir -p "$LOGDIR"
echo "logs -> $LOGDIR"

# ONE resolved commit for everything. `$BASE...HEAD` selects files by MERGE BASE, while a bare
# `git checkout "$BASE"` takes contents from the branch TIP — so once main advances past the branch
# point, the "baseline" mixes one commit's file list with another commit's contents and the
# comparison quietly stops meaning anything.
BASE_REF_NAME="${BASE_REF:-main}"
BASE="$(git merge-base "$BASE_REF_NAME" HEAD)"
echo "baseline commit: $BASE (merge-base of $BASE_REF_NAME and HEAD)"

# Required layers must be able to FAIL the run. Without this the script reports a broken suite and
# still exits 0, which is the same false-success this whole bead is about. Lint and types are
# deliberately excluded: both carry a large pre-existing backlog, so non-zero is their normal state
# and the bar is "no NEW findings against the baseline", which a human reads below.
_FAILED=""
require() {  # require <layer-name> <exit-status>
  [ "$2" -eq 0 ] || _FAILED="$_FAILED $1"
}

say() { printf '\n=== %s ===\n' "$1"; }

say "1. full suite (project wrapper, NOT a hand-composed pytest line)"
tools/run-tests.sh >"$LOGDIR/tests.log" 2>&1
require suite $?
tail -1 "$LOGDIR/tests.log"

say "2. suite health — two fixed seeds, so 'order-independent' is a measurement"
for seed in 12345 98765; do
  tools/run-tests.sh -p randomly --randomly-seed="$seed" >"$LOGDIR/tests-seed-$seed.log" 2>&1
  require "suite-health(seed=$seed)" $?
  printf 'seed %s: %s\n' "$seed" "$(tail -1 "$LOGDIR/tests-seed-$seed.log")"
done

say "3. lint (configured command; compare against the baseline below)"
mise exec -- uv run --extra dev ruff check src tests tools >"$LOGDIR/lint.log" 2>&1
tail -1 "$LOGDIR/lint.log"

say "4. types (configured command; compare against the baseline below)"
mise exec -- pyright >"$LOGDIR/types.log" 2>&1
tail -1 "$LOGDIR/types.log"

say "5. baselines at $BASE, for layers 3 and 4"
# Measured by reverting only the touched files: both tools are per-file, so this is equivalent to
# checking the whole tree out at the branch point, without a second worktree. `$BASE` is the
# resolved merge-base, so file SELECTION and file CONTENTS come from the same commit.
CHANGED_SRC=$(git diff --name-only "$BASE" HEAD -- 'src/**/*.py')
NEW_TESTS=$(git diff --name-only --diff-filter=A "$BASE" HEAD -- 'tests/**/*.py')
STASHDIR=$(mktemp -d)
# Arm the trap BEFORE the tree is touched, not after — that ordering is the whole point.
_RESTORE="$CHANGED_SRC"
_STASHDIR="$STASHDIR"
_NEW_TESTS="$NEW_TESTS"
# shellcheck disable=SC2086
[ -n "$CHANGED_SRC" ] && git checkout "$BASE" -- $CHANGED_SRC
for f in $NEW_TESTS; do mv "$f" "$STASHDIR/$(basename "$f")"; done
mise exec -- uv run --extra dev ruff check src tests tools >"$LOGDIR/lint-baseline.log" 2>&1
mise exec -- pyright >"$LOGDIR/types-baseline.log" 2>&1
printf 'lint  baseline: %s\n' "$(tail -1 "$LOGDIR/lint-baseline.log")"
printf 'types baseline: %s\n' "$(tail -1 "$LOGDIR/types-baseline.log")"
_cleanup           # restore via the same path the trap uses, so both are exercised every run
_RESTORE=""; _STASHDIR=""; _NEW_TESTS=""

say "6. changed-line coverage"
tools/run-tests.sh --cov=src/harnessed --cov-report=xml -q >"$LOGDIR/coverage.log" 2>&1
require coverage-suite $?
mise exec -- uv run --extra dev diff-cover coverage.xml --compare-branch="$BASE" \
  >"$LOGDIR/diff-cover.log" 2>&1
cat "$LOGDIR/diff-cover.log"

say "7. mutation on the timeout seam"
# Two documented workarounds from [tool.mutmut], both required and neither optional:
#   HARNESSED_DIR=$PWD — harnessed_home() resolves through the src/harnessed/catalog symlink, which
#     does not exist in the mutants tree.
#   tests_dir narrowed — mutmut DEREFERENCES symlinks, so catalog/*.local arrive as real dirs and
#     the tests asserting a link IS a link fail at collection, which aborts the stats pass and
#     reports every mutant as survived for want of a runnable suite.
# pyproject is restored with `git checkout` below, so no backup copy is needed — and a backup here
# would be a second source of truth for a file git already tracks.
python3 - <<'PY'
import pathlib
p = pathlib.Path("pyproject.toml")
# The narrowed set must include EVERY file that can kill a mutant in the targeted functions, or the
# survivor count is an artefact of the narrowing rather than a fact about the tests: mutating the
# firewall argv to None "survived" until test_launcher_install (which asserts that argv) was added.
p.write_text(p.read_text().replace(
    'tests_dir = ["tests/"]',
    'tests_dir = ["tests/test_launcher_timeouts.py", "tests/test_subprocess_timeout_audit.py",'
    ' "tests/test_launcher_install.py", "tests/test_setup_notice.py"]',
))
PY
_RESTORE=" "   # arm the trap for pyproject before mutmut can be interrupted
HARNESSED_DIR="$PWD" mise exec -- uv run --extra dev mutmut run \
  "*_bounded*" "*_run_tagged*" "*_listing*" "*_apply_firewall*" >"$LOGDIR/mutmut.log" 2>&1
require mutation $?
git checkout HEAD -- pyproject.toml
_RESTORE=""
printf 'killed:   %s\n' "$(grep -c '🎉 harnessed' "$LOGDIR/mutmut.log")"
printf 'survived: %s\n' "$(grep -c '🙁 harnessed' "$LOGDIR/mutmut.log")"

say "8. real execution — a podman that never answers must not hang the CLI"
HANG=$(mktemp -d)
printf '#!/usr/bin/env bash\nsleep 100000\n' >"$HANG/podman"
chmod +x "$HANG/podman"
start=$SECONDS
PATH="$HANG:$PATH" mise exec -- uv run --extra dev python -m harnessed.launcher list \
  >"$LOGDIR/real-exec-hang.log" 2>&1
rc=$?
elapsed=$((SECONDS - start))
printf 'exit=%s elapsed=%ss (expect ~30s and a "warning:" line, NOT a hang)\n' "$rc" "$elapsed"
# The probe PASSES by coming back on its own deadline with a warning. A run that took minutes, or
# printed no warning, means the deadline did not fire — which is the whole bead failing silently.
if [ "$elapsed" -gt 90 ] || ! grep -q 'warning:' "$LOGDIR/real-exec-hang.log"; then
  require real-execution 1
fi
rm -r "$HANG"

say "done"
echo "Layers NOT covered here: integration-tree verification (the harness forbids git operations"
echo "against the shared checkout) and adversarial review (three independent agents; see EVIDENCE)."

if [ -n "$_FAILED" ]; then
  echo >&2
  echo "GAUNTLET FAILED — required layer(s):$_FAILED" >&2
  echo "Lint and types are excluded by design: both have a large pre-existing backlog, so the bar" >&2
  echo "is 'no NEW findings against the printed baseline', which only a human can judge." >&2
  exit 1
fi
echo "All required layers passed. Lint/types: compare each against its baseline above."
