#!/usr/bin/env bash
# install.sh — bake the `bd` CLI (https://github.com/gastownhall/beads), identically in a container
# build and a host launch. Replaces the Dockerfile that used to do only this.
#
# NO `install.system` on this recipe. The old Dockerfile carried two `USER root` lines, but every
# statement between them was a COMMENT — the actual install (`mise use -g` + `bd --version`) ran as
# `USER harnessed`. There is no root-level step here to skip, so a host launch is fully equivalent
# to a container build and warns about nothing.
#
# Env is the `install:` contract (emit.install_env), same keys in both modes: HARNESS,
# HARNESSED_MODE, HARNESSED_RECIPE_DIR, HARNESSED_CONFIG_DIR, HARNESSED_INSTALL_CACHE.
# PROJECT_DIR is deliberately absent — a build has no project mounted. Everything project-shaped
# for this recipe (`bd init`, `bd setup`) already lives in recipe.yaml's `setup:`, which is the
# phase that HAS a project. This script only puts a binary on PATH.
#
# No `install.cache`: mise keeps its own content-addressed tool store, so the per-launch re-run is
# already cheap and a second cache would be duplicate bookkeeping.
set -euo pipefail

# Pin the exact release (no @latest / :latest / --branch — the script lint rejects floating refs).
BEADS_VERSION="1.1.0"

# Idempotence. The host home is rebuilt every launch, so this script runs every launch; without
# this gate it would re-write the user's global mise config on each one.
if command -v bd >/dev/null 2>&1; then
    have="$(bd --version 2>/dev/null || true)"
    case "$have" in
        *"$BEADS_VERSION"*)
            echo "install(beads-team): bd $BEADS_VERSION already present — nothing to do."
            exit 0
            ;;
    esac
    # A DIFFERENT bd is already on PATH. Container-side that cannot happen (fresh image), so this is
    # a host launch against a machine where the user manages bd themselves. harnessed does not
    # overwrite a tool it did not install — say what the mismatch is and use theirs.
    if [ "${HARNESSED_MODE:-}" = "host" ]; then
        echo "install(beads-team): WARNING — bd already on PATH (${have:-unknown version}), which is" >&2
        echo "  not the ${BEADS_VERSION} this recipe pins. Leaving your installation untouched." >&2
        exit 0
    fi
fi

# harnessed-base ships mise + shims on PATH; a host may not have it. mise's `github:` backend
# resolves the right release asset per arch AND verifies GitHub artifact attestations — a stronger
# supply-chain guarantee than a hand-rolled curl + sha256sum.
if ! command -v mise >/dev/null 2>&1; then
    echo "install(beads-team): mise is required to install bd but is not on PATH." >&2
    echo "  Install mise (https://mise.jdx.dev) or install bd ${BEADS_VERSION} yourself, then relaunch." >&2
    exit 1
fi

mise use -g "github:gastownhall/beads@${BEADS_VERSION}"
mise install
# Smoke test: a runnable binary also catches an arch mismatch mise's attestation check wouldn't.
bd --version
