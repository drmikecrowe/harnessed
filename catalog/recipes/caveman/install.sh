#!/usr/bin/env bash
# install.sh — caveman's skills/ + commands/ + agents/ trees, delivered IDENTICALLY by a container
# build and a host launch.
#
# This replaces the Dockerfile RUN that used to do the same thing. That RUN only ever executed
# during `podman build`, so `harnessed launch --host` shipped a profile with ZERO caveman skills or
# commands and said nothing about it (bd harnessed-8px.1).
#
# We still deliberately do NOT run upstream's bin/install.js: it delegates to per-harness plugin
# systems that bypass the assembler's harness-independent fan-out, need the harness binary at
# install time, and wire settings.json/plugin.json hooks harnessed can't express (GAP 2). The
# recipe's own `hooks:` block covers the SessionStart nudge.
#
# Env is the `install.script` contract (emit.install_env) — same keys in both modes:
#   HARNESSED_CONFIG_DIR    the agent config dir to install INTO (image ~/.claude | host home)
#   HARNESSED_INSTALL_CACHE pinned-ref content cache; empty when the recipe declares no `install.cache`
#   HARNESSED_MODE          host | container
#   HARNESSED_RECIPE_DIR    this recipe's own directory
#   HARNESS                 the harness being built/launched
#   HARNESSED_REF_CAVEMAN   the pinned ref, from `install.refs.caveman.ref` in recipe.yaml
#   HARNESSED_REPO_CAVEMAN  `owner/repo`, from `install.refs.caveman.repo`
# Deliberately NOT available: PROJECT_DIR and friends — a build has no project mounted.
set -euo pipefail

# NO PIN LITERAL HERE (Phase 3 of #329). `CAVEMAN_REF="v1.9.0"` used to live on this line and be
# kept equal to `cache: v1.9.0` in recipe.yaml by a comment asking the reader to bump both. The pin
# now lives in `install.refs:` alone and arrives as env, so there is nothing to keep in lockstep and
# `harnessed update` has exactly one place to read and write.
#
# `:?` rather than a default: an unset ref means the manifest and this script disagree about the key
# name, and a default would paper over that by cloning something arbitrary. Fail naming the variable.
: "${HARNESSED_CONFIG_DIR:?install.sh requires HARNESSED_CONFIG_DIR}"
: "${HARNESSED_REF_CAVEMAN:?install.sh requires HARNESSED_REF_CAVEMAN (install.refs.caveman.ref)}"
: "${HARNESSED_REPO_CAVEMAN:?install.sh requires HARNESSED_REPO_CAVEMAN (install.refs.caveman.repo)}"

# The manifest carries `owner/repo`, never a URL — contract rule 2. The script composes the URL, so
# switching this recipe from a git clone to a tarball fetch needs no manifest change.
CAVEMAN_REPO="https://github.com/${HARNESSED_REPO_CAVEMAN}.git"

# Cache MISS is "the directory does not exist" — harnessed creates only its parent. Populate into a
# temp sibling and rename, so an interrupted clone can never be mistaken for a populated cache.
src="${HARNESSED_INSTALL_CACHE:-}"
if [ -n "$src" ]; then
    if [ ! -d "$src" ]; then
        tmp="${src}.partial.$$"
        rm -rf "$tmp"
        git clone --quiet --depth 1 --branch "$HARNESSED_REF_CAVEMAN" "$CAVEMAN_REPO" "$tmp"
        mv "$tmp" "$src"
    fi
else
    src="$(mktemp -d)"
    trap 'rm -rf "$src"' EXIT
    git clone --quiet --depth 1 --branch "$HARNESSED_REF_CAVEMAN" "$CAVEMAN_REPO" "$src"
fi

# Trailing-slash `…/.` contents form: skills/caveman -> <config>/skills/caveman, NOT
# <config>/skills/caveman/skills/caveman — the flat layout `expect:` probes resolve against.
for dir in skills commands agents; do
    mkdir -p "$HARNESSED_CONFIG_DIR/$dir"
    cp -r "$src/$dir/." "$HARNESSED_CONFIG_DIR/$dir/"
done
