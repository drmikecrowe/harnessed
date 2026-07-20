#!/usr/bin/env bash
# install.sh — the rtk CLI + its global Claude wiring, moved out of the recipe Dockerfile
# (bd harnessed-8px.5). Replaces both former RUN layers.
#
# Env this file may rely on (emit.install_env — same keys host and container):
#   HARNESS, HARNESSED_MODE, HARNESSED_RECIPE_DIR, HARNESSED_CONFIG_DIR, HARNESSED_INSTALL_CACHE
# PROJECT_DIR and friends are absent by design — a build has no project mounted.
set -euo pipefail

# Pin = the release tag mise resolves against. `cargo install rtk` is deliberately NOT used: another
# "rtk" ("Rust Type Kit") on crates.io would fetch the wrong package.
RTK_VERSION="0.43.0"

: "${HARNESSED_CONFIG_DIR:?install.sh requires HARNESSED_CONFIG_DIR}"

# --- 1. the binary -------------------------------------------------------------------------------
# Container: mise's `github:` backend (harnessed-base ships mise + shims on PATH). It resolves the
# arch-matched asset (musl-static on x86_64, gnu on aarch64 — no aarch64-musl is published) and
# verifies GitHub artifact attestations + SLSA provenance.
#
# Host: NOT installed, and said out loud. `mise use -g` writes the USER'S global mise config and data
# dir, which harnessed does not own or mutate; redirecting mise at the install cache instead would
# park the binary somewhere nothing puts on the agent's PATH, and rtk is a CLI the agent must be able
# to shell out to by name. The install-env contract exposes $HARNESSED_CONFIG_DIR and the cache — it
# does NOT expose the stack bin dir, so "land an executable on the host agent's PATH" is not a thing
# an install.sh can do today. That channel is `provision:` (bd harnessed-zi6.1); until rtk grows one,
# a host launch gets no rtk, and now says so instead of failing silently (bd harnessed-8px.1).
#
# If rtk IS already on the host's PATH we use it and continue to step 2, so a user who installed rtk
# themselves still gets the global wiring.
if ! command -v rtk >/dev/null 2>&1; then
    if [ "${HARNESSED_MODE:-}" != "container" ]; then
        echo "WARNING install (rtk): the rtk binary is NOT installed on a host launch — mise's" \
             "global config/data dir belongs to you, and an install.sh has no way to put an" \
             "executable on the host agent's PATH (that is 'provision:', bd harnessed-zi6.1)." \
             "Install rtk ${RTK_VERSION} yourself to get it, or run this stack in a container." >&2
        exit 0
    fi
    mise use -g "github:rtk-ai/rtk@${RTK_VERSION}"
    mise install
fi
rtk --version

# --- 2. the global wiring ------------------------------------------------------------------------
# `rtk init -g --auto-patch` bakes RTK.md + the PreToolUse hook so the agent does not have to
# discover the surface from `rtk --help` alone. It targets $HOME/.claude.
#
# Container-side $HOME/.claude IS $HARNESSED_CONFIG_DIR, so it is called directly — byte-identical to
# the `RUN rtk init -g --auto-patch` it replaces. Host-side $HOME is the USER'S home and
# $HARNESSED_CONFIG_DIR is the stack's own materialized CLAUDE_CONFIG_DIR, so a throwaway $HOME whose
# .claude symlinks to it makes "global" mean the stack's config dir. Without this a host launch would
# patch the user's real ~/.claude/settings.json — a write outside $HARNESSED_CONFIG_DIR, which a host
# launch must not do.
#
# $HARNESSED_HOME_SHIM is a harnessed-owned dir whose .claude IS $HARNESSED_CONFIG_DIR, so "global"
# means the stack's config dir in BOTH modes and this needs no branch. Container-side it is simply
# the image home (where $HOME/.claude already is the config dir), so the line is byte-equivalent to
# the `RUN rtk init -g --auto-patch` it replaces.
#
# It is also STABLE across launches. That matters because --auto-patch records a hook path in
# settings.json: under the old `mktemp -d` shim any absolute path the installer wrote died with the
# temp dir on exit (bd harnessed-8px.9, which cost gsd-core 12 broken hooks).
HOME="$HARNESSED_HOME_SHIM" rtk init -g --auto-patch
