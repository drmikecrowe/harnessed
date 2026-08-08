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
# `rtk init -g` bakes RTK.md + the CLAUDE.md `@RTK.md` include so the agent does not have to discover
# the surface from `rtk --help` alone. DOCS ONLY — the PreToolUse hook that actually makes rtk fire
# is declared in recipe.yaml `hooks:`, where the assembler emits it into the generated settings.json.
#
# Deliberately NOT `--auto-patch`. That flag also patches settings.json, and the patch does not
# survive: the assembler owns that file and regenerates it after install.sh runs, silently dropping
# the installer-written hook. `rtk init -g` without the flag leaves settings.json untouched and just
# prints the snippet, so the two mechanisms no longer fight over one file.
#
# Both env vars are pinned rather than inherited, because rtk resolves its target config dir from
# $CLAUDE_CONFIG_DIR FIRST and only falls back to $HOME/.claude — so setting $HOME alone does not
# steer it. Pinning both makes "global" mean the stack's config dir in BOTH modes with no branch:
#   - CLAUDE_CONFIG_DIR: the direct target, correct even if the ambient value is unset or foreign.
#   - HOME=$HARNESSED_HOME_SHIM: a harnessed-owned dir whose .claude IS $HARNESSED_CONFIG_DIR, held
#     for the fallback path. Without it a host launch could write into the USER'S real ~/.claude —
#     outside $HARNESSED_CONFIG_DIR, which a host launch must not do. The shim is also STABLE across
#     launches, unlike the old `mktemp -d` (bd harnessed-8px.9, which cost gsd-core 12 broken hooks).
HOME="$HARNESSED_HOME_SHIM" CLAUDE_CONFIG_DIR="$HARNESSED_CONFIG_DIR" rtk init -g
