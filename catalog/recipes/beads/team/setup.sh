#!/usr/bin/env bash
# setup.sh — initialize this project's beads workspace against its beads-server.
#
# Gated by `setup.confirm` in recipe.yaml, which is what makes automating this acceptable: `bd init`
# in TEAM placement creates and COMMITS files into a shared repo, and that is the user's decision to
# make. The launcher shows the warning and runs this only on an explicit yes; it never runs without
# a terminal. See launcher._confirm_setup.
#
# Runs in BOTH modes (host launch and inside the container before attach), which is the whole reason
# this is a `script:` and not the legacy host-only `run:`. Connection details arrive by environment
# from the beads-server service's `client_env` — never hardcoded here, and never written into
# metadata.json, which is bd's TRACKED surface (BEADS.md §4/D6).
set -euo pipefail

# Self-gating, because a `setup.script` runs on every launch by contract. `setup.condition` gates the
# CONFIRM prompt; this gates the work itself, so an already-initialized workspace is a no-op even if
# something upstream changes.
if [ -f "${BEADS_DIR:?}/metadata.json" ]; then
    echo "setup(beads-team): ${BEADS_DIR} already initialized — nothing to do."
    exit 0
fi

# The `:?` guard IS the check that the service is attached: the published port does not exist until
# the sidecar is running, so an unset value here means the stack is missing `services:
# [beads-server]` — a far better failure than bd falling back to a server of its own.
: "${BEADS_DOLT_SERVER_PORT:?beads-server not attached — add services:[beads-server] to the stack}"

# --external is the load-bearing flag: it is what stops bd from EVER auto-starting its own dolt.
# Without it bd starts a server chdir'd into its data dir with no --data-dir, which initializes that
# directory as a database and makes the project database permanently unreachable (BEADS.md §10).
bd init --server --external --server-port "${BEADS_DOLT_SERVER_PORT}"

echo "setup(beads-team): initialized ${BEADS_DIR} against beads-server on port ${BEADS_DOLT_SERVER_PORT}"
echo "setup(beads-team): run 'bd setup <harness> --project' once to wire the bd prime workflow in."
