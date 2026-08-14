#!/usr/bin/env bash
# Re-run every gauntlet layer cited in the bd harnessed-1ao evidence report.
#
# One entry point, because a report whose numbers cannot be reproduced from the repo alone stops
# being evidence the moment someone relies on it INSTEAD of reading the code.
#
# Layers that need a baseline (lint, types) are non-zero on this repo by design: both tools carry a
# large pre-existing backlog and neither runs in CI, so the bar is "zero NEW findings against the
# branch point", never "exit 0". This script performs a finding-level diff — normalising each
# finding to "file RULE message" (line numbers dropped) — and exits nonzero if any findings were
# ADDED. Removed findings are reported as wins. A finding that merely shifted line because of an
# unrelated insertion is NOT counted as new.
#
# Usage: tools/gauntlet-1ao.sh [logdir]
set -uo pipefail

# REFUSE TO RUN ON A DIRTY TREE. Step 5 reverts src/ to the branch point and step 7 rewrites
# pyproject; both are undone with `git checkout`, which is destructive to uncommitted edits to those
# same paths. Rather than try to preserve someone's work-in-progress, decline the run.
if ! git diff --quiet -- src tests tools pyproject.toml \
  || ! git diff --cached --quiet -- src tests tools pyproject.toml; then
  echo "refusing to run: uncommitted changes under src/, tests/, tools/, or pyproject.toml." >&2
  echo "This script reverts those paths to measure a baseline and would discard them. Commit or set them aside first." >&2
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
    # Restore by REPO-RELATIVE path, mirroring how they were stashed. Keyed on basename these
    # would collide across directories (tests/foo.py vs tools/foo.py) and silently lose a file.
    for f in $_NEW_TESTS; do
      if [ -f "$_STASHDIR/$f" ]; then
        mkdir -p "$(dirname "$f")"
        mv "$_STASHDIR/$f" "$f"
      fi
    done
    # `rm -r`, not `rmdir`: the stash now has nested parent dirs, so rmdir would always fail and
    # leak the temp tree. Bounded — $_STASHDIR is only ever assigned from `mktemp -d` above.
    rm -r "$_STASHDIR" 2>/dev/null
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

say "3. lint (HEAD; finding-level diff computed in step 5)"
# ruff exits 0 = no findings, 1 = findings found (both are normal); 2+ = crash (hard error).
_lint_exit=0
mise exec -- uv run --extra dev ruff check --output-format=json src tests tools \
  >"$LOGDIR/lint.json" 2>"$LOGDIR/lint-err.log" || _lint_exit=$?
if [ "$_lint_exit" -gt 1 ]; then
  echo "ruff CRASHED (exit $_lint_exit) — hard failure, not a lint finding:" >&2
  cat "$LOGDIR/lint-err.log" >&2
  require lint "$_lint_exit"
else
  _norm_exit=0
  mise exec -- uv run --extra dev python tools/lint-findings.py normalize ruff "$LOGDIR/lint.json" \
    >"$LOGDIR/lint-normalized.txt" 2>&1 || _norm_exit=$?
  if [ "$_norm_exit" -ne 0 ]; then
    echo "lint normalization FAILED (exit $_norm_exit):" >&2
    cat "$LOGDIR/lint-normalized.txt" >&2
    require lint-normalize "$_norm_exit"
  else
    printf 'lint HEAD: %s findings\n' "$(wc -l <"$LOGDIR/lint-normalized.txt")"
  fi
fi

say "4. types (HEAD; finding-level diff computed in step 5)"
# pyright exits 0 = no errors, 1 = errors found (both are normal); 2+ = crash (hard error).
_types_exit=0
mise exec -- pyright --outputjson \
  >"$LOGDIR/types.json" 2>"$LOGDIR/types-err.log" || _types_exit=$?
if [ "$_types_exit" -gt 1 ]; then
  echo "pyright CRASHED (exit $_types_exit) — hard failure:" >&2
  cat "$LOGDIR/types-err.log" >&2
  require types "$_types_exit"
else
  _norm_exit=0
  mise exec -- uv run --extra dev python tools/lint-findings.py normalize pyright "$LOGDIR/types.json" \
    >"$LOGDIR/types-normalized.txt" 2>&1 || _norm_exit=$?
  if [ "$_norm_exit" -ne 0 ]; then
    echo "types normalization FAILED (exit $_norm_exit):" >&2
    cat "$LOGDIR/types-normalized.txt" >&2
    require types-normalize "$_norm_exit"
  else
    printf 'types HEAD: %s findings\n' "$(wc -l <"$LOGDIR/types-normalized.txt")"
  fi
fi

say "5. baselines at $BASE — finding-level diff for layers 3 and 4"
# Measured by reverting only the touched files: both tools are per-file, so this is equivalent to
# checking the whole tree out at the branch point, without a second worktree. `$BASE` is the
# resolved merge-base, so file SELECTION and file CONTENTS come from the same commit.
#
# IMPORTANT: the revert covers src/, tests/, AND tools/ — not just src/.  Reverting src/ only
# allows a new finding in tests/ or tools/ to appear identically in both runs and cancel against
# itself, making it structurally invisible to the gate (#327 blind spot 2).
# ADDED files are split out from CHANGED here, and the split is load-bearing rather than tidy.
# An added file does not exist at $BASE, so naming it in `git checkout "$BASE" -- ...` makes git
# abort the WHOLE command with "pathspec did not match" and check out NOTHING — not merely skip
# that one path. Measured, not assumed: `git checkout <base> -- src/harnessed/paths.py
# tools/lint-findings.py` left paths.py identical to HEAD.
#
# So a single added .py anywhere under these patterns silently disabled the entire baseline revert.
# Baseline then analysed the HEAD tree, baseline == head, and the finding diff reported
# "+0 added -0 removed" — a permanent all-clear from a gate that had stopped comparing anything.
# That is the exact fail-open this script exists to prevent, and it was live: `tools/lint-findings.py`
# is itself an added file on the branch that introduced this diff.
#
# `--diff-filter=a` (lower-case = EXCLUDE added) leaves only paths that exist at $BASE and are
# therefore checkout-able; `--diff-filter=A` collects the added ones, which get moved aside instead.
# Both cover src/ AND tests/ AND tools/ — reverting src/ only lets a new finding in tests/ or tools/
# appear identically in both runs and cancel against itself (#327 blind spot 2).
CHANGED_SRC=$(git diff --name-only --diff-filter=a "$BASE" HEAD -- 'src/**/*.py' 'tests/*.py' 'tools/*.py')
NEW_FILES=$(git diff --name-only --diff-filter=A "$BASE" HEAD -- 'src/**/*.py' 'tests/*.py' 'tools/*.py')
STASHDIR=$(mktemp -d)
# Arm the trap BEFORE the tree is touched, not after — that ordering is the whole point.
_RESTORE="$CHANGED_SRC"
_STASHDIR="$STASHDIR"
_NEW_TESTS="$NEW_FILES"
# Fail CLOSED. A revert that half-happened produces a baseline that is neither HEAD nor $BASE, and
# every number downstream would be quietly wrong rather than obviously broken.
# shellcheck disable=SC2086
if [ -n "$CHANGED_SRC" ] && ! git checkout "$BASE" -- $CHANGED_SRC; then
  echo "baseline revert FAILED (git checkout $BASE) — refusing to report a comparison" >&2
  exit 2
fi
# Stash under the file's REPO-RELATIVE path, not its basename: tests/foo.py and tools/foo.py share a
# basename, and a basename-keyed stash silently overwrites the first with the second, then restores
# the wrong content to one path and leaves the other deleted. Losing a source file to the measuring
# instrument is worse than any finding it could report.
for f in $NEW_FILES; do
  mkdir -p "$STASHDIR/$(dirname "$f")"
  mv "$f" "$STASHDIR/$f"
done

_baseline_lint_exit=0
_baseline_types_exit=0
mise exec -- uv run --extra dev ruff check --output-format=json src tests tools \
  >"$LOGDIR/lint-baseline.json" 2>"$LOGDIR/lint-baseline-err.log" || _baseline_lint_exit=$?
mise exec -- pyright --outputjson \
  >"$LOGDIR/types-baseline.json" 2>"$LOGDIR/types-baseline-err.log" || _baseline_types_exit=$?

_cleanup           # restore via the same path the trap uses, so both are exercised every run
_RESTORE=""; _STASHDIR=""; _NEW_TESTS=""

# --- lint diff ---
if [ "$_baseline_lint_exit" -gt 1 ]; then
  echo "ruff CRASHED in baseline run (exit $_baseline_lint_exit) — hard failure" >&2
  require lint-baseline "$_baseline_lint_exit"
else
  _norm_exit=0
  mise exec -- uv run --extra dev python tools/lint-findings.py normalize ruff \
    "$LOGDIR/lint-baseline.json" >"$LOGDIR/lint-baseline-normalized.txt" 2>&1 || _norm_exit=$?
  if [ "$_norm_exit" -ne 0 ]; then
    echo "lint baseline normalization FAILED (exit $_norm_exit):" >&2
    cat "$LOGDIR/lint-baseline-normalized.txt" >&2
    require lint-baseline-normalize "$_norm_exit"
  else
    printf 'lint baseline: %s findings\n' "$(wc -l <"$LOGDIR/lint-baseline-normalized.txt")"
    echo "Lint finding-level diff (HEAD vs baseline):"
    _lint_diff_exit=0
    mise exec -- uv run --extra dev python tools/lint-findings.py diff \
      "$LOGDIR/lint-baseline-normalized.txt" "$LOGDIR/lint-normalized.txt" \
      || _lint_diff_exit=$?
    if [ "$_lint_diff_exit" -gt 0 ]; then
      require "lint(added-findings)" 1
    fi
  fi
fi

# --- types diff ---
if [ "$_baseline_types_exit" -gt 1 ]; then
  echo "pyright CRASHED in baseline run (exit $_baseline_types_exit) — hard failure" >&2
  require types-baseline "$_baseline_types_exit"
else
  _norm_exit=0
  mise exec -- uv run --extra dev python tools/lint-findings.py normalize pyright \
    "$LOGDIR/types-baseline.json" >"$LOGDIR/types-baseline-normalized.txt" 2>&1 || _norm_exit=$?
  if [ "$_norm_exit" -ne 0 ]; then
    echo "types baseline normalization FAILED (exit $_norm_exit):" >&2
    cat "$LOGDIR/types-baseline-normalized.txt" >&2
    require types-baseline-normalize "$_norm_exit"
  else
    printf 'types baseline: %s findings\n' "$(wc -l <"$LOGDIR/types-baseline-normalized.txt")"
    echo "Types finding-level diff (HEAD vs baseline):"
    _types_diff_exit=0
    mise exec -- uv run --extra dev python tools/lint-findings.py diff \
      "$LOGDIR/types-baseline-normalized.txt" "$LOGDIR/types-normalized.txt" \
      || _types_diff_exit=$?
    if [ "$_types_diff_exit" -gt 0 ]; then
      require "types(added-findings)" 1
    fi
  fi
fi

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
  echo "Lint and types gate on ADDED findings (finding-level diff, line numbers ignored)." >&2
  echo "Removed findings are wins. Pre-existing findings do not fail the gate." >&2
  exit 1
fi
echo "All required layers passed. Lint/types: no findings were added against the baseline."
