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
#   HARNESSED_MODE          host | container
#   HARNESSED_RECIPE_DIR    this recipe's own directory
#   HARNESS                 the harness being built/launched
# Deliberately NOT available: PROJECT_DIR and friends — a build has no project mounted.
set -euo pipefail

# Upstream publishes no release tags, so pin to an exact commit and shallow fetch by SHA. Must match
# `install.cache` in recipe.yaml; use the full 40-char SHA and bump both together.
GSTACK_REF="11de390be1be6849eb9a15f91ff4922dd16c589a"
GSTACK_REPO="https://github.com/garrytan/gstack.git"

: "${HARNESSED_CONFIG_DIR:?install.sh requires HARNESSED_CONFIG_DIR}"

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
    git -C "$1" fetch -q --depth 1 origin "$GSTACK_REF"
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
