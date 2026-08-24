#!/usr/bin/env bash
# Run every gate CI runs, in CI's order, before you push.
#
# WHY THIS EXISTS: `tools/run-tests.sh` runs pytest and nothing else, but it is what the run-tests
# skill documents as "how to verify" — so a green suite gets reported as "verified" and the branch
# goes red on a gate nobody ran. That happened on PR #431: two RUF005 findings, invisible locally,
# with pytest fully green.
#
# The gates live in THREE separate workflows, which is why running one proves so little:
#
#   .github/workflows/test.yml       pytest (3.12 and 3.13)
#   .github/workflows/lint.yml       ruff -> pyright -> shellcheck
#   .github/workflows/pin-check.yml  harnessed update --check
#
# ORDER MATTERS, and not for cosmetic reasons. lint.yml has no `continue-on-error` and ruff is its
# first step, so on CI a ruff finding means pyright and shellcheck NEVER RAN — a red lint job
# understates how much is still unverified. This script keeps that same order deliberately, so what
# you see locally is what CI would have told you, but it reports every layer it skipped by name so
# the understatement is explicit rather than silent.
#
# Usage:  tools/preflight.sh [--all] [--no-tests]
#   tools/preflight.sh              # pytest + ruff + pyright + shellcheck
#   tools/preflight.sh --all        # also the catalog pin check (network, slow)
#   tools/preflight.sh --no-tests   # lint layers only, for a docs- or shell-only change
#
# The pin check is opt-in on purpose: it queries upstream release feeds, so it is slow, needs the
# network, and is irrelevant to any change that does not touch `catalog/`. CI runs it on every PR
# regardless; add --all before pushing a catalog change.
set -uo pipefail

# `|| exit` because this script deliberately runs without `set -e` (every gate must run even
# after an earlier one fails), so a failed cd would otherwise lint the wrong tree.
cd "$(dirname "$0")/.." || exit 1

run_all=false
run_tests=true
for arg in "$@"; do
    case "$arg" in
        --all)      run_all=true ;;
        --no-tests) run_tests=false ;;
        -h|--help)  sed -n '2,27p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)          echo "preflight: unknown argument '$arg'" >&2; exit 2 ;;
    esac
done

# Same three worktree hazards `run-tests.sh` documents: per-branch venv outside the repo, pytest as
# an optional extra, and mise refusing an untrusted config. `mise trust` is a no-op once trusted.
mise trust >/dev/null 2>&1 || {
    echo "preflight: 'mise trust' failed — is mise installed and on PATH?" >&2
    exit 1
}
mise exec -- uv sync --extra dev --quiet || {
    echo "preflight: 'uv sync --extra dev' failed — cannot run any gate without it" >&2
    exit 1
}

failed=()
skipped=()

# Every gate runs even after an earlier one fails. That is the ONE deliberate divergence from CI:
# CI stops and leaves you guessing how much else is broken, and the point of a preflight is to hand
# you the whole list in one pass.
gate() {
    local name="$1"; shift
    printf '\n\033[1m=== %s ===\033[0m\n' "$name"
    if "$@"; then
        return 0
    fi
    printf '\033[1;31m%s FAILED\033[0m\n' "$name"
    failed+=("$name")
    return 1
}

if [ "$run_tests" = true ]; then
    gate "pytest" mise exec -- uv run pytest -q || true
else
    skipped+=("pytest (--no-tests)")
fi

# Exactly the argv from lint.yml. Keep them identical: a preflight that checks a different set of
# paths than CI is a preflight that lies.
gate "ruff" mise exec -- uv run --extra dev ruff check src tests tools || true

# --pythonpath is NOT optional. mise.toml puts the venv outside the repo
# (UV_PROJECT_ENVIRONMENT=~/.local/share/harnessed/venvs/<branch>/.venv), so a bare `pyright`
# resolves none of the installed packages and reports hundreds of phantom reportMissingImports on a
# tree that is genuinely clean. Asked for explicitly, from the same source of truth uv uses.
if command -v pyright >/dev/null 2>&1; then
    py=$(mise exec -- uv run --extra dev python -c 'import sys; print(sys.executable)' 2>/dev/null)
    if [ -n "$py" ]; then
        gate "pyright" pyright --pythonpath "$py" || true
    else
        skipped+=("pyright (could not resolve the venv interpreter)")
    fi
else
    skipped+=("pyright (not installed — \`npm i -g pyright\`)")
fi

# `catalog/**` is included on purpose, matching CI: those install scripts run inside recipe images
# as root, so a quoting bug there is a build that fails opaquely or, worse, succeeds wrongly.
if command -v shellcheck >/dev/null 2>&1; then
    # shellcheck disable=SC2046  # word splitting is wanted: one argument per tracked script
    gate "shellcheck" shellcheck $(git ls-files '*.sh') || true
else
    skipped+=("shellcheck (not installed)")
fi

if [ "$run_all" = true ]; then
    gate "pin check" mise exec -- uv run --extra dev harnessed update --check || true
else
    skipped+=("pin check (--all to include; CI runs it regardless)")
fi

printf '\n\033[1m=== preflight summary ===\033[0m\n'
for s in ${skipped+"${skipped[@]}"}; do
    printf '  \033[33mskipped\033[0m  %s\n' "$s"
done

if [ ${#failed[@]} -eq 0 ]; then
    if [ ${#skipped[@]} -eq 0 ]; then
        printf '  \033[32mall gates passed\033[0m\n'
    else
        # Never print a bare "all clear" while a layer was skipped — that is the exact
        # overstatement this script exists to prevent.
        printf '  \033[32mevery gate that ran passed\033[0m (see skipped above)\n'
    fi
    exit 0
fi

printf '  \033[1;31mfailed:\033[0m %s\n' "${failed[*]}"
exit 1
