#!/usr/bin/env bash
# install.sh — the Claude skill agent-carnet BUNDLES in its npm tarball, delivered IDENTICALLY by a
# container build and a host launch.
#
# PARTIAL migration, on purpose. This recipe's Dockerfile had two halves:
#   1. `pnpm add -g agent-carnet@<VER>`  — puts the CLI on PATH. STAYS in the Dockerfile.
#   2. copy the bundled skill into ~/.claude/skills/agent-carnet — CONTENT. That is this file.
# Only (2) was broken on `--host` (bd harnessed-8px.1). (1) is not moved here because a host launch
# runs install.sh against the USER'S real machine, and `pnpm add -g` there would write into their
# global pnpm store — outside every harnessed-owned directory. Getting the CLI onto PATH host-side
# is `provision:`'s job (bd harnessed-zi6.1), not this script's. On a host launch you therefore get
# the skill but not the `agent-carnet` binary; in a container you get both.
#
# The skill is fetched from the SAME immutable npm artifact the Dockerfile pins, straight from the
# registry — not via `pnpm root -g`, which only exists container-side after half (1) has run.
# One version literal, two consumers, no second source and no floating ref.
#
# Env is the `install.script` contract (emit.install_env) — same keys in both modes:
#   HARNESSED_CONFIG_DIR    the agent config dir to install INTO (image ~/.claude | host home)
#   HARNESSED_INSTALL_CACHE pinned-ref content cache; empty when the recipe declares no `install.cache`
#   HARNESSED_MODE          host | container
#   HARNESSED_RECIPE_DIR    this recipe's own directory
#   HARNESS                 the harness being built/launched
# Deliberately NOT available: PROJECT_DIR and friends — a build has no project mounted.
set -euo pipefail

# Must match both `install.cache` in recipe.yaml and AGENT_CARNET_VERSION in the Dockerfile — bump
# all three together, which also yields a fresh cache dir.
AGENT_CARNET_VERSION="0.1.5"
AGENT_CARNET_TARBALL="https://registry.npmjs.org/agent-carnet/-/agent-carnet-${AGENT_CARNET_VERSION}.tgz"

: "${HARNESSED_CONFIG_DIR:?install.sh requires HARNESSED_CONFIG_DIR}"

fetch_pkg() {  # $1 = destination dir; leaves the tarball's `package/` root inside it
    mkdir -p "$1"
    curl -fsSL "$AGENT_CARNET_TARBALL" -o "$1/agent-carnet.tgz"
    tar -xzf "$1/agent-carnet.tgz" -C "$1"
    rm -f "$1/agent-carnet.tgz"
}

# Cache MISS is "the directory does not exist" — harnessed creates only its parent. Populate into a
# temp sibling and rename, so an interrupted download can never be mistaken for a populated cache.
src="${HARNESSED_INSTALL_CACHE:-}"
if [ -n "$src" ]; then
    if [ ! -d "$src" ]; then
        tmp="${src}.partial.$$"
        rm -rf "$tmp"
        fetch_pkg "$tmp"
        mv "$tmp" "$src"
    fi
else
    src="$(mktemp -d)"
    trap 'rm -rf "$src"' EXIT
    fetch_pkg "$src"
fi

# npm tarballs always root at `package/`; the skill ships at package/skills/agent-carnet/
# (SKILL.md + references/{cookbook,frontmatter}.md).
mkdir -p "$HARNESSED_CONFIG_DIR/skills"
rm -rf "$HARNESSED_CONFIG_DIR/skills/agent-carnet"
cp -rL "$src/package/skills/agent-carnet" "$HARNESSED_CONFIG_DIR/skills/agent-carnet"
# Fail loudly rather than ship an empty skill dir — the exact failure mode bd harnessed-8px.1 was.
test -f "$HARNESSED_CONFIG_DIR/skills/agent-carnet/SKILL.md"
