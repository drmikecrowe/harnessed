#!/usr/bin/env bash
# install.sh — hyperpowers' skills/ + commands/ + agents/ trees, delivered IDENTICALLY by a
# container build and a host launch.
#
# This replaces the Dockerfile RUN that used to do the same thing. That RUN only ever executed
# during `podman build`, so `harnessed launch --host` shipped a profile with ZERO hyperpowers
# skills, commands, or agents and said nothing about it (bd harnessed-8px.1).
#
# Env is the `install.script` contract (emit.install_env) — same keys in both modes:
#   HARNESSED_CONFIG_DIR    the agent config dir to install INTO (image ~/.claude | host home)
#   HARNESSED_INSTALL_CACHE pinned-ref content cache; empty when the recipe declares no `install.cache`
#   HARNESSED_MODE          host | container
#   HARNESSED_RECIPE_DIR    this recipe's own directory
#   HARNESS                 the harness being built/launched
# Deliberately NOT available: PROJECT_DIR and friends — a build has no project mounted.
set -euo pipefail

# Upstream publishes NO tags/releases, so pin to the full SHA of a main commit and fetch by SHA.
# Must match `install.cache` in recipe.yaml (which keys the host content cache); a floating
# `--branch main` is rejected by the script lint (validate_install_script) either way.
HYPERPOWERS_REF="7905547b6eb0665d631dd1e4f557e3863cd7a1b4"
HYPERPOWERS_REPO="https://github.com/withzombies/hyperpowers.git"

: "${HARNESSED_CONFIG_DIR:?install.sh requires HARNESSED_CONFIG_DIR}"

fetch_ref() {  # $1 = destination dir
    git init -q "$1"
    git -C "$1" remote add origin "$HYPERPOWERS_REPO"
    git -C "$1" fetch -q --depth 1 origin "$HYPERPOWERS_REF"
    git -C "$1" checkout -q FETCH_HEAD
}

# Cache MISS is "the directory does not exist" — harnessed creates only its parent. Populate into a
# temp sibling and rename, so an interrupted fetch can never be mistaken for a populated cache.
src="${HARNESSED_INSTALL_CACHE:-}"
if [ -n "$src" ]; then
    if [ ! -d "$src" ]; then
        tmp="${src}.partial.$$"
        rm -rf "$tmp"
        fetch_ref "$tmp"
        mv "$tmp" "$src"
    fi
else
    src="$(mktemp -d)"
    trap 'rm -rf "$src"' EXIT
    fetch_ref "$src"
fi

# Trailing-slash `…/.` contents form: skills/<name>/ lands at <config>/skills/<name>/, NOT
# <config>/skills/skills/<name>/ — the layout `expect:` probes resolve against.
for dir in skills commands agents; do
    mkdir -p "$HARNESSED_CONFIG_DIR/$dir"
    cp -r "$src/$dir/." "$HARNESSED_CONFIG_DIR/$dir/"
done
