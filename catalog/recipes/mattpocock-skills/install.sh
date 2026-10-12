#!/usr/bin/env bash
# install.sh — mattpocock-skills' published skills, delivered identically by a container build and a
# host launch. Contract env (emit.install_env): HARNESSED_CONFIG_DIR, HARNESSED_INSTALL_CACHE, plus
# HARNESSED_REF_MATTPOCOCK / HARNESSED_REPO_MATTPOCOCK from `install.refs` in recipe.yaml.
set -euo pipefail

: "${HARNESSED_CONFIG_DIR:?install.sh requires HARNESSED_CONFIG_DIR}"
: "${HARNESSED_REF_MATTPOCOCK:?install.sh requires HARNESSED_REF_MATTPOCOCK (install.refs.mattpocock.ref)}"
: "${HARNESSED_REPO_MATTPOCOCK:?install.sh requires HARNESSED_REPO_MATTPOCOCK (install.refs.mattpocock.repo)}"

REPO_URL="https://github.com/${HARNESSED_REPO_MATTPOCOCK}.git"

# Cache MISS is "the directory does not exist". Clone into a temp sibling and rename, so an
# interrupted clone is never mistaken for a populated cache.
src="${HARNESSED_INSTALL_CACHE:-}"
if [ -n "$src" ]; then
    if [ ! -d "$src" ]; then
        tmp="${src}.partial.$$"
        rm -rf "$tmp"
        git -c advice.detachedHead=false clone --quiet --depth 1 --branch "$HARNESSED_REF_MATTPOCOCK" "$REPO_URL" "$tmp"
        mv "$tmp" "$src"
    fi
else
    src="$(mktemp -d)"
    trap 'rm -rf "$src"' EXIT
    git -c advice.detachedHead=false clone --quiet --depth 1 --branch "$HARNESSED_REF_MATTPOCOCK" "$REPO_URL" "$src"
fi

# Flatten skills/<category>/<name>/ to <config>/skills/<name>/. Only the two categories upstream's
# plugin.json publishes; the trailing `*/` skips each category's README.md. A missing category fails
# loudly: skipping it would ship a silently partial install.
mkdir -p "$HARNESSED_CONFIG_DIR/skills"
for category in engineering productivity; do
    if [ ! -d "$src/skills/$category" ]; then
        echo "install.sh: upstream $HARNESSED_REF_MATTPOCOCK has no skills/$category; its layout changed" >&2
        exit 1
    fi
    for skill in "$src/skills/$category"/*/; do
        cp -r "${skill%/}" "$HARNESSED_CONFIG_DIR/skills/"
    done
done
