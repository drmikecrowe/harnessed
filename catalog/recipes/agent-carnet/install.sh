#!/usr/bin/env bash
# install.sh — agent-carnet CLI + bundled Claude skill (BOTH modes).
#
# Two deliverables, both via this script in both modes:
#   1. `pnpm add -g agent-carnet@<VER>` — the CLI. PNPM_HOME redirect lands the binary in
#      HARNESSED_BIN_DIR: the stack bin dir on a host launch, ~/.local/bin during a container build
#      (emit.install_env). The assembler includes this file as RUN bash install.sh in the image.
#   2. Copy the bundled skill into HARNESSED_CONFIG_DIR/skills/agent-carnet.
# The skill is fetched from the SAME immutable npm artifact that (1) installs, straight from the
# registry — not via `pnpm root -g`, which only resolves after (1) has run.
# One version literal, two consumers, no second source and no floating ref.
#
# Env is the `install.script` contract (emit.install_env) — same keys in both modes:
#   HARNESSED_CONFIG_DIR    the agent config dir to install INTO (image ~/.claude | host home)
#   HARNESSED_INSTALL_CACHE pinned-ref content cache; empty when the recipe declares no `install.cache`
#   HARNESSED_BIN_DIR       the stack bin dir (host) or base image ~/.local/bin (container)
#   HARNESSED_MODE          host | container
#   HARNESSED_RECIPE_DIR    this recipe's own directory
#   HARNESS                 the harness being built/launched
# Deliberately NOT available: PROJECT_DIR and friends — a build has no project mounted.
set -euo pipefail

# Must match `install.cache` in recipe.yaml — bump both together, which also yields a fresh cache dir.
AGENT_CARNET_VERSION="0.1.5"

# --- CLI install (both modes) ---------------------------------------------------------------------
# HARNESSED_BIN_DIR = stack bin dir on host, base image ~/.local/bin on container.
#
# PNPM_HOME is the PARENT, not $HARNESSED_BIN_DIR itself: pnpm's global bin dir is "$PNPM_HOME/bin",
# so pointing PNPM_HOME straight at the bin dir resolves to "$HARNESSED_BIN_DIR/bin" — one level too
# deep, and NOT on PATH. pnpm then hard-errors ("The configured global bin directory ... is not in
# PATH") rather than installing. Verified against pnpm directly with `pnpm bin -g`.
#
# This relies on HARNESSED_BIN_DIR ending in `/bin`, which holds in both modes (host:
# <tools_root>/bin from _stack_tools_dirs; container: /home/harnessed/.local/bin). Using the
# config-env form rather than a `--global-bin-dir` flag ON PURPOSE, matching gsd-core: an
# unsupported env key is ignored, where an unsupported flag aborts the install outright.
#
# NOTE: a bare `pnpm add -g` does NOT stay inside the stack host-side. pnpm ignores
# npm_config_prefix for the global bin dir and falls back to ~/.local/share/pnpm — see
# bd harnessed-8px.14. The redirect below is what actually contains it.
PNPM_HOME="$(dirname "$HARNESSED_BIN_DIR")" pnpm add -g "agent-carnet@${AGENT_CARNET_VERSION}"
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
