#!/usr/bin/env bash
# Run the harnessed test suite correctly from any worktree.
#
# Exists because three separate things make the suite fail LOCALLY while CI stays green, and each
# one costs a round trip to rediscover. All three are handled here so nobody has to remember them:
#
#   1. venvs are PER BRANCH. mise.toml sets UV_PROJECT_ENVIRONMENT to
#      ~/.local/share/harnessed/venvs/<branch>/.venv — deliberately outside the repo, so a container
#      bind-mounting the repo cannot corrupt it. A fresh worktree therefore starts with NO venv and
#      does not inherit main's.
#   2. pytest is an OPTIONAL EXTRA (`[project.optional-dependencies].dev`). A plain `uv sync`
#      installs the project without it, and `uv run pytest` then silently falls through to a system
#      pytest on a different Python, where every test errors with
#      `ModuleNotFoundError: No module named 'harnessed'` — which reads like a broken checkout.
#   3. mise refuses an untrusted config in a new worktree ("Config files ... are not trusted").
#
# FORCE_COLOR is NOT handled here — tests/conftest.py pops it at import, which is the only place
# early enough (rich reads it when a Console is constructed, and launcher.py builds its Consoles at
# module import, before any fixture runs). Documented there and in CLAUDE.md.
#
# Usage:  tools/run-tests.sh [pytest args...]
#   tools/run-tests.sh                          # whole suite, quiet
#   tools/run-tests.sh tests/test_schema.py     # one file
#   tools/run-tests.sh -k install -x            # filter, stop on first failure
set -euo pipefail

cd "$(dirname "$0")/.."

# `mise trust` is a no-op once trusted, so this is safe to run every time. Quiet unless it fails.
mise trust >/dev/null 2>&1 || {
    echo "run-tests: 'mise trust' failed — is mise installed and on PATH?" >&2
    exit 1
}

# --extra dev is the whole point (see 2 above). uv sync is a fast no-op when already in sync, so
# there is no reason to try to detect a first run and skip it.
mise exec -- uv sync --extra dev --quiet

exec mise exec -- uv run pytest "${@:--q}"
