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

# --- 1. the binary: NOT here ----------------------------------------------------------------------
# `tools: [github:rtk-ai/rtk@…]` owns it (bd harnessed-1t4.3) — the same mise `github:` release
# install (arch-matched asset, GitHub artifact attestations + SLSA provenance) this script used to
# run container-side. It now runs on a host launch too: harnessed points mise at the STACK's own
# config/data dir, so the reason this section refused to install host-side — 'mise's global config
# and data dir belong to you' — no longer applies, and the shims dir is on the launch PATH.
# Keep RTK_VERSION in lockstep with that pin.
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
