#!/usr/bin/env bash
# Mutation verdict for #456 -- reads a mutmut run log and decides pass/fail.
#
# SPLIT OUT OF gauntlet-456.sh so it can be RUN AND CONTROLLED on its own. Inline, the only way to
# exercise it was a 15-minute full gauntlet, which meant in practice it was never exercised at all
# -- and a gate nobody can cheaply run against a known-bad input is a gate nobody has proven can
# fail. It takes the log as an argument for the same reason.
#
# Usage: tools/mutation-verdict-456.sh <mutmut-run-log> [allowlist]
set -euo pipefail

LOG="${1:?usage: mutation-verdict-456.sh <mutmut-run-log> [allowlist]}"
ALLOWLIST="${2:-$(dirname "$0")/mutation-allowlist-456.txt}"
[ -r "$LOG" ] || { printf 'verdict: cannot read %s\n' "$LOG"; exit 1; }
[ -r "$ALLOWLIST" ] || { printf 'verdict: cannot read %s\n' "$ALLOWLIST"; exit 1; }

# THE MUTATION LAYER IS JUDGED HERE, NOT BY `mutmut run`'S EXIT CODE.
#
# `mutmut run` exits 0 whether every mutant died or every one survived, so the `run` wrapper above
# cannot fail this layer -- and on the first pass it did not: the script printed `all layers
# passed` over 51 survivors and five filters that had matched nothing at all. A gauntlet layer that
# cannot go red is a report, not a gate. This block is the gate.
#
# Two conditions, because each catches a different lie:
#   1. SURVIVORS -- a mutant nothing killed is a line no test actually constrains.
#   2. FILTERS THAT MATCHED NOTHING -- the silent-filter trap pyproject.toml warns about. A typo'd
#      or stale filter selects zero mutants, mutmut exits 0, and the layer looks clean precisely
#      because it measured nothing. Checked by counting what the RUN log actually executed.
printf '\n=== mutation verdict ===\n'
mutation_failed=0
# Same list the run used -- see `mutation-targets-456.txt`. Reading it here rather than repeating
# it is what stops the verdict from certifying a set of functions the run never mutated.
MUT_TARGETS="$(dirname "$0")/mutation-targets-456.txt"
mapfile -t MUT_FNS < <(sed -e 's/#.*//' -e '/^[[:space:]]*$/d' "$MUT_TARGETS")
[ "${#MUT_FNS[@]}" -gt 0 ] || { echo "no mutation targets read from $MUT_TARGETS" >&2; exit 1; }
for fn in "${MUT_FNS[@]}"
do
  killed=$(grep -c "🎉 $fn" "$LOG" || true)
  survived=$(grep -c "🙁 $fn" "$LOG" || true)
  # 🫥 is mutmut's "no tests" status. It is NOT a pass and NOT the same as a silent filter: the
  # mutant exists and was skipped because mutmut believes nothing covers it. Counted separately so
  # the verdict says which of the two happened.
  notests=$(grep -c "🫥 $fn" "$LOG" || true)
  printf '%-45s killed=%-4s survived=%-4s no-tests=%s\n' "$fn" "$killed" "$survived" "$notests"
  if [ "$((killed + survived + notests))" -eq 0 ]; then
    printf '  FAIL: filter matched no mutant at all (silent filter -- check the name)\n'
    mutation_failed=1
  fi
  if [ "$notests" -ne 0 ]; then
    printf '  FAIL: %s mutant(s) reported "no tests" -- uncovered, not passing\n' "$notests"
    mutation_failed=1
  fi
  # Survivors are checked against the CLASSIFIED allowlist, one mutant at a time. A survivor that
  # is not listed fails the layer; the allowlist is a set of individual claims with reasons, never
  # a per-function threshold.
  # `${fn}__mutmut_`, braced: `$fn__mutmut_` is the variable `fn__mutmut_`, which is unset, so the
  # pattern would match nothing and every survivor would pass unclassified. shellcheck (SC1087)
  # caught that -- a gate that silently matches nothing is the failure this whole layer is for.
  while read -r m; do
    [ -n "$m" ] || continue
    if ! grep -qx "$m" "$ALLOWLIST"; then
      printf '  FAIL: %s survived and is not classified in %s\n' "$m" "$ALLOWLIST"
      mutation_failed=1
    fi
  done < <(grep -o "🙁 ${fn}__mutmut_[0-9]*" "$LOG" | sed 's/🙁 //' | sort -u)
done

# THE ALLOWLIST IS CHECKED IN REVERSE TOO. An entry for a mutant that no longer survives is stale,
# and a stale entry is how this file decays from "classified" into "muted": the next person adds a
# test that kills the mutant, the entry stays, and it silently excuses some future survivor that
# happens to reuse the number. Fail on it, so the file can only ever describe the present.
while read -r m; do
  case "$m" in ''|\#*) continue ;; esac
  if ! grep -q "🙁 $m\$" "$LOG"; then
    # WHICH KIND of stale, because the two demand different responses and the single message sent
    # a reader after the wrong one. A mutant that still EXISTS and stopped surviving means a test
    # got stronger -- delete the entry and move on. A mutant that no longer exists at all means the
    # allowlist was written against a different source state, so every OTHER numbered entry for
    # that function is suspect too and has to be re-read, not just this one. Found on the PR #461
    # review pass: 13 `_preflight_runtime` entries reported as "no longer survives" were numbers
    # the function does not generate any more.
    mfile="mutants/src/harnessed/$(printf '%s' "$m" | cut -d. -f2).py"
    if [ -f "$mfile" ] && grep -q "def $(printf '%s' "$m" | cut -d. -f3-)(" "$mfile"; then
      printf '  FAIL: %s is allowlisted but is now KILLED -- remove the entry\n' "$m"
    else
      printf '  FAIL: %s is allowlisted but NO LONGER EXISTS -- the source moved; re-read every entry for this function\n' "$m"
    fi
    mutation_failed=1
  fi
done < "$ALLOWLIST"
if [ "$mutation_failed" -ne 0 ]; then
  printf '\nmutation layer FAILED\n'
  exit 1
fi
printf 'mutation layer passed\n'

printf '\nall layers passed\n'
