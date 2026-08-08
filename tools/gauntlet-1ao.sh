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

# Two steps below deliberately mutate TRACKED files — step 5 reverts src/ to the branch point to
# measure a lint baseline, step 7 narrows mutmut's tests_dir. Both restore with `git checkout`, but
# only if they are reached: a Ctrl-C in between would otherwise leave the working tree holding
# baseline source or a rewritten pyproject, which the next `git add .` would quietly commit. The
# trap makes the restore unconditional. It is idempotent and harmless when nothing was touched.
_RESTORE=""
_cleanup() {
  # shellcheck disable=SC2086
  [ -n "$_RESTORE" ] && git checkout HEAD -- pyproject.toml $_RESTORE 2>/dev/null
  return 0
}
trap _cleanup EXIT INT TERM

LOGDIR="${1:-.old-coder/gauntlet-1ao-$(date -u +%Y%m%d-%H%M%S)}"
mkdir -p "$LOGDIR"
echo "logs -> $LOGDIR"

BASE="${BASE_REF:-main}"
say() { printf '\n=== %s ===\n' "$1"; }

say "1. full suite (project wrapper, NOT a hand-composed pytest line)"
tools/run-tests.sh >"$LOGDIR/tests.log" 2>&1
tail -1 "$LOGDIR/tests.log"

say "2. suite health — two fixed seeds, so 'order-independent' is a measurement"
for seed in 12345 98765; do
  tools/run-tests.sh -p randomly --randomly-seed="$seed" >"$LOGDIR/tests-seed-$seed.log" 2>&1
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
# checking the whole tree out at the branch point, without a second worktree.
CHANGED_SRC=$(git diff --name-only "$BASE...HEAD" -- 'src/**/*.py')
NEW_TESTS=$(git diff --name-only --diff-filter=A "$BASE...HEAD" -- 'tests/**/*.py')
STASHDIR=$(mktemp -d)
_RESTORE="$CHANGED_SRC"   # arm the trap BEFORE the tree is touched, not after
# shellcheck disable=SC2086
[ -n "$CHANGED_SRC" ] && git checkout "$BASE" -- $CHANGED_SRC
for f in $NEW_TESTS; do mv "$f" "$STASHDIR/$(basename "$f")"; done
mise exec -- uv run --extra dev ruff check src tests tools >"$LOGDIR/lint-baseline.log" 2>&1
mise exec -- pyright >"$LOGDIR/types-baseline.log" 2>&1
printf 'lint  baseline: %s\n' "$(tail -1 "$LOGDIR/lint-baseline.log")"
printf 'types baseline: %s\n' "$(tail -1 "$LOGDIR/types-baseline.log")"
# shellcheck disable=SC2086
[ -n "$CHANGED_SRC" ] && git checkout HEAD -- $CHANGED_SRC
for f in $NEW_TESTS; do mv "$STASHDIR/$(basename "$f")" "$f"; done
rmdir "$STASHDIR"

say "6. changed-line coverage"
tools/run-tests.sh --cov=src/harnessed --cov-report=xml -q >"$LOGDIR/coverage.log" 2>&1
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
HARNESSED_DIR="$PWD" mise exec -- uv run --extra dev mutmut run \
  "*_bounded*" "*_run_tagged*" "*_listing*" "*_apply_firewall*" >"$LOGDIR/mutmut.log" 2>&1
git checkout HEAD -- pyproject.toml
printf 'killed:   %s\n' "$(grep -c '🎉 harnessed' "$LOGDIR/mutmut.log")"
printf 'survived: %s\n' "$(grep -c '🙁 harnessed' "$LOGDIR/mutmut.log")"

say "8. real execution — a podman that never answers must not hang the CLI"
HANG=$(mktemp -d)
printf '#!/usr/bin/env bash\nsleep 100000\n' >"$HANG/podman"
chmod +x "$HANG/podman"
start=$SECONDS
PATH="$HANG:$PATH" mise exec -- uv run --extra dev python -m harnessed.launcher list \
  >"$LOGDIR/real-exec-hang.log" 2>&1
printf 'exit=%s elapsed=%ss (expect ~30s and a "warning:" line, NOT a hang)\n' \
  "$?" "$((SECONDS - start))"
grep -c 'warning:' "$LOGDIR/real-exec-hang.log"
rm -r "$HANG"

say "done"
echo "Layers NOT covered here: integration-tree verification (the harness forbids git operations"
echo "against the shared checkout) and adversarial review (two independent agents; see EVIDENCE)."
