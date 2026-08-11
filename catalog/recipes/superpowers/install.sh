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
#   HARNESSED_REF_SUPERPOWERS   the pinned ref, from `install.refs.superpowers.ref` in recipe.yaml
#   HARNESSED_REPO_SUPERPOWERS  `owner/repo`, from `install.refs.superpowers.repo`
# Deliberately NOT available: PROJECT_DIR and friends. Install runs at BUILD time container-side,
# where no project is mounted — anything project-shaped belongs in `setup.script`.
set -euo pipefail

# NO PIN LITERAL HERE (Phase 3 of #329) — not even in a comment, which is why this paragraph
# describes the old shape without naming the version. A `SUPERPOWERS_REF=` assignment used to sit
# here, kept equal to `install.cache` in recipe.yaml by a comment asking the reader to bump both.
# The pin now lives in `install.refs:` alone and arrives as env, so there is nothing to keep in
# lockstep and `harnessed update` has exactly one place to read and write.
#
# `:?` rather than a default: an unset ref means the manifest and this script disagree about the
# key name, and a default would paper over that by cloning something arbitrary. Fail, naming it.
: "${HARNESSED_CONFIG_DIR:?install.sh requires HARNESSED_CONFIG_DIR}"
: "${HARNESSED_REF_SUPERPOWERS:?install.sh requires HARNESSED_REF_SUPERPOWERS (install.refs.superpowers.ref)}"
: "${HARNESSED_REPO_SUPERPOWERS:?install.sh requires HARNESSED_REPO_SUPERPOWERS (install.refs.superpowers.repo)}"

# The manifest carries `owner/repo`, never a URL — contract rule 2. The script composes the URL, so
# switching this recipe from a git clone to a tarball fetch needs no manifest change.
SUPERPOWERS_REPO="https://github.com/${HARNESSED_REPO_SUPERPOWERS}.git"

# Cache MISS is "the directory does not exist" — harnessed creates only its parent. Populate into a
# temp sibling and rename, so an interrupted clone can never be mistaken for a populated cache.
src="${HARNESSED_INSTALL_CACHE:-}"
if [ -n "$src" ]; then
    if [ ! -d "$src" ]; then
        tmp="${src}.partial.$$"
        rm -rf "$tmp"
        git clone --quiet --depth 1 --branch "$HARNESSED_REF_SUPERPOWERS" "$SUPERPOWERS_REPO" "$tmp"
        mv "$tmp" "$src"
    fi
else
    src="$(mktemp -d)"
    trap 'rm -rf "$src"' EXIT
    git clone --quiet --depth 1 --branch "$HARNESSED_REF_SUPERPOWERS" "$SUPERPOWERS_REPO" "$src"
fi

# Trailing-slash `…/.` form: each skill lands at <config>/skills/<name>/ with its sibling
# references/ and scripts/ subtrees intact.
mkdir -p "$HARNESSED_CONFIG_DIR/skills"
cp -r "$src/skills/." "$HARNESSED_CONFIG_DIR/skills/"
