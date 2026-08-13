#!/usr/bin/env bash
# install.sh — gstack's skill suite, installed by running upstream's OWN `./setup`, identically in a
# container build and on a host launch.
#
# STRADDLES the install/system line, which is why this recipe still has a Dockerfile:
#   * CONTENT  — fetch the pinned commit into <config>/skills/gstack and run `./setup`. THIS FILE.
#     Previously a Dockerfile RUN, so `harnessed launch --host` shipped ZERO gstack skills and said
#     nothing about it (bd harnessed-8px.1).
#   * SYSTEM   — `bunx playwright install-deps chromium` needs `USER root` + apt. That STAYS in the
#     Dockerfile and is declared via `install.system:` in recipe.yaml, so a host launch prints the
#     reason and skips it instead of failing or silently pretending. harnessed never sudos.
#
# Env is the `install.script` contract (emit.install_env) — same keys in both modes:
#   HARNESSED_CONFIG_DIR    the agent config dir to install INTO (image ~/.claude | host home)
#   HARNESSED_INSTALL_CACHE pinned-ref content cache; empty when the recipe declares no `install.cache`
#   HARNESSED_REF_GSTACK    the pinned commit, from `install.refs.gstack.ref` in recipe.yaml
#   HARNESSED_REPO_GSTACK   `owner/repo`, from `install.refs.gstack.repo`
#   HARNESSED_MODE          host | container
#   HARNESSED_RECIPE_DIR    this recipe's own directory
#   HARNESS                 the harness being built/launched
# Deliberately NOT available: PROJECT_DIR and friends — a build has no project mounted.
set -euo pipefail

# NO PIN LITERAL HERE (Phase 3 of #329) — not even in a comment, which is why this paragraph
# describes the old shape without naming the commit. A `GSTACK_REF=` assignment used to sit here,
# kept equal to `install.cache` in recipe.yaml by a comment asking the reader to bump both. The pin
# now lives in `install.refs:` alone and arrives as env, so there is nothing to keep in lockstep and
# `harnessed update` has exactly one place to read and write.
#
# `:?` rather than a default: an unset ref means the manifest and this script disagree about the key
# name, and a default would paper over that by fetching the default branch — a floating fetch
# wearing a pinned recipe's clothes. Fail, naming the variable. These come FIRST, before the bun
# preflight, so a misconfigured manifest is reported as itself rather than as a missing tool.
: "${HARNESSED_CONFIG_DIR:?install.sh requires HARNESSED_CONFIG_DIR}"
: "${HARNESSED_REF_GSTACK:?install.sh requires HARNESSED_REF_GSTACK (install.refs.gstack.ref)}"
: "${HARNESSED_REPO_GSTACK:?install.sh requires HARNESSED_REPO_GSTACK (install.refs.gstack.repo)}"

# The manifest carries `owner/repo`, never a URL — contract rule 2. The script composes the URL, so
# switching this recipe from a git fetch to a tarball download needs no manifest change.
GSTACK_REPO="https://github.com/${HARNESSED_REPO_GSTACK}.git"

# gstack's own ./setup shells out to bun (`bun install`, `playwright install chromium`). bun ships in
# the harnessed base image, so a container build always has it; a host launch may not. Say so
# explicitly rather than let ./setup die with an opaque error — failing LOUDLY is the whole point of
# bd harnessed-8px.1.
if ! command -v bun >/dev/null 2>&1; then
    echo "gstack install: 'bun' was not found on PATH. gstack's upstream ./setup requires it." >&2
    echo "Install bun (https://bun.sh) or run this stack in a container, which ships bun." >&2
    exit 1
fi

fetch_ref() {  # $1 = destination dir
    git init -q "$1"
    git -C "$1" remote add origin "$GSTACK_REPO"
    git -C "$1" fetch -q --depth 1 origin "$HARNESSED_REF_GSTACK"
    git -C "$1" checkout -q FETCH_HEAD
}

# The cache holds the pinned SOURCE only, never ./setup's output: ./setup builds node_modules under
# the installed tree and is the step that must run against the live config dir. Cache MISS is "the
# directory does not exist" — populate a temp sibling and rename so an interrupted fetch is never
# mistaken for a hit.
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

target="$HARNESSED_CONFIG_DIR/skills/gstack"
rm -rf "$target"
mkdir -p "$(dirname "$target")"
cp -r "$src" "$target"

# Authoring a Dockerfile recipe = run the project's OWN documented install commands. gstack's docs
# say "git clone + ./setup", so that is exactly what runs here — the same as a user would on a host.
cd "$target"
./setup
./bin/gstack-config set redact_prepush_hook true -- /ship
