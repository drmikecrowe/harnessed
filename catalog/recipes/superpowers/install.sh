#!/usr/bin/env bash
# install.sh — superpowers' 14 skills, delivered IDENTICALLY by a container build and a host launch.
#
# This file replaces the Dockerfile RUN that used to do the same thing. That RUN only ever executed
# during `podman build`, so `harnessed launch --host` shipped a profile with ZERO superpowers skills
# and said nothing about it (bd harnessed-8px.1). One script, two executors, one outcome.
#
# The env below is the `install.script` contract (emit.install_env) — the same keys in both modes:
#   HARNESSED_CONFIG_DIR    the agent config dir to install INTO (image ~/.claude | host home)
#   HARNESSED_INSTALL_CACHE pinned-ref content cache; empty when the recipe declares no `install.cache`
#   HARNESSED_MODE          host | container
#   HARNESSED_RECIPE_DIR    this recipe's own directory (source for `cp`)
#   HARNESS                 the harness being built/launched
# Deliberately NOT available: PROJECT_DIR and friends. Install runs at BUILD time container-side,
# where no project is mounted — anything project-shaped belongs in `setup.script`.
set -euo pipefail

# Pinned release tag. Must match `install.cache` in recipe.yaml, which keys the host content cache:
# a moving ref would make that cache permanently stale, so the schema rejects one and the script
# lint (validate_install_script) rejects a floating `--branch` here.
SUPERPOWERS_REF="v6.0.3"
SUPERPOWERS_REPO="https://github.com/obra/superpowers.git"

: "${HARNESSED_CONFIG_DIR:?install.sh requires HARNESSED_CONFIG_DIR}"

# Cache MISS is "the directory does not exist" — harnessed creates only its parent. Populate into a
# temp sibling and rename, so an interrupted clone can never be mistaken for a populated cache.
src="${HARNESSED_INSTALL_CACHE:-}"
if [ -n "$src" ]; then
    if [ ! -d "$src" ]; then
        tmp="${src}.partial.$$"
        rm -rf "$tmp"
        git clone --quiet --depth 1 --branch "$SUPERPOWERS_REF" "$SUPERPOWERS_REPO" "$tmp"
        mv "$tmp" "$src"
    fi
else
    src="$(mktemp -d)"
    trap 'rm -rf "$src"' EXIT
    git clone --quiet --depth 1 --branch "$SUPERPOWERS_REF" "$SUPERPOWERS_REPO" "$src"
fi

# Trailing-slash `…/.` form: each skill lands at <config>/skills/<name>/ with its sibling
# references/ and scripts/ subtrees intact.
mkdir -p "$HARNESSED_CONFIG_DIR/skills"
cp -r "$src/skills/." "$HARNESSED_CONFIG_DIR/skills/"
