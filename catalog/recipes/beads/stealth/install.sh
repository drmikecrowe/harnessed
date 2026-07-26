#!/usr/bin/env bash
# install.sh — bake the `bd` CLI (https://github.com/gastownhall/beads), identically in a container
# build and a host launch. Replaces the Dockerfile that used to do only this.
#
# NO `install.system` on this recipe. The old Dockerfile carried a `USER root` line, but every
# statement under it was a COMMENT — the actual install (`mise use -g` + `bd --version`) ran as
# `USER harnessed`. There is no root-level step here to skip, so a host launch is fully equivalent
# to a container build and warns about nothing. (`ENV BEADS_DIR` had already moved to recipe.yaml's
# `env:` — the one deliverable no script can provide, since bd re-reads it on every invocation.)
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

# --- the workspace-resolving `bd` wrapper -------------------------------------------------------
# Installed BEFORE the version gate below on purpose: that gate exits early when bd is already the
# pinned version, and the shim still has to be (re)placed — the host home and the stack tools dir
# are rebuilt on every launch. See bd-shim.sh for what it does and why.
#
# Its OWN dir rather than $HARNESSED_BIN_DIR itself, because the recipe's `init:` prepends this dir
# to PATH so the wrapper beats mise's `bd` shim: a dir holding exactly one file shadows exactly one
# tool, which is the difference between fixing bd's resolution and reordering everything harnessed
# ever installed.
shim_dir="${HARNESSED_BIN_DIR:?}/bd-shim"
mkdir -p "$shim_dir"
install -m 0755 "${HARNESSED_RECIPE_DIR:?}/bd-shim.sh" "$shim_dir/bd"

# Pin the exact release (no @latest / :latest / --branch — the script lint rejects floating refs).
BEADS_VERSION="1.1.0"

# Idempotence. The host home is rebuilt every launch, so this script runs every launch; without
# this gate it would re-write the user's global mise config on each one.
if command -v bd >/dev/null 2>&1; then
    have="$(bd --version 2>/dev/null || true)"
    case "$have" in
        *"$BEADS_VERSION"*)
            echo "install(beads-stealth): bd $BEADS_VERSION already present — nothing to do."
            exit 0
            ;;
    esac
    # A DIFFERENT bd is already on PATH. Container-side that cannot happen (fresh image), so this is
    # a host launch against a machine where the user manages bd themselves. harnessed does not
    # overwrite a tool it did not install — say what the mismatch is and use theirs.
    if [ "${HARNESSED_MODE:-}" = "host" ]; then
        echo "install(beads-stealth): WARNING — bd already on PATH (${have:-unknown version}), which is" >&2
        echo "  not the ${BEADS_VERSION} this recipe pins. Leaving your installation untouched." >&2
        exit 0
    fi
fi

# harnessed-base ships mise + shims on PATH; a host may not have it. mise's `github:` backend
# resolves the right release asset per arch AND verifies GitHub artifact attestations — a stronger
# supply-chain guarantee than a hand-rolled curl + sha256sum.
if ! command -v mise >/dev/null 2>&1; then
    echo "install(beads-stealth): mise is required to install bd but is not on PATH." >&2
    echo "  Install mise (https://mise.jdx.dev) or install bd ${BEADS_VERSION} yourself, then relaunch." >&2
    exit 1
fi

mise use -g "github:gastownhall/beads@${BEADS_VERSION}"
mise install
# Smoke test: a runnable binary also catches an arch mismatch mise's attestation check wouldn't.
bd --version
