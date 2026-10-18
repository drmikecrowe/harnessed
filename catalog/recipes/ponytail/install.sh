#!/usr/bin/env bash
# install.sh — ponytail's six skills and its Claude lifecycle hook scripts, delivered identically by
# a container build and a host launch.
#
# Env is the `install.script` contract (emit.install_env), same keys in both modes:
#   HARNESSED_CONFIG_DIR    the agent config dir to install INTO
#   HARNESSED_INSTALL_CACHE pinned-ref content cache (derived from install.refs)
#   HARNESSED_REF_PONYTAIL  the pinned ref, from `install.refs.ponytail.ref`
#   HARNESSED_REPO_PONYTAIL `owner/repo`, from `install.refs.ponytail.repo`
set -euo pipefail

: "${HARNESSED_CONFIG_DIR:?install.sh requires HARNESSED_CONFIG_DIR}"
: "${HARNESSED_REF_PONYTAIL:?install.sh requires HARNESSED_REF_PONYTAIL (install.refs.ponytail.ref)}"
: "${HARNESSED_REPO_PONYTAIL:?install.sh requires HARNESSED_REPO_PONYTAIL (install.refs.ponytail.repo)}"

PONYTAIL_REPO="https://github.com/${HARNESSED_REPO_PONYTAIL}.git"

# Cache MISS is "the directory does not exist". Populate a temp sibling and rename, so an
# interrupted clone is never mistaken for a populated cache.
src="${HARNESSED_INSTALL_CACHE:-}"
if [ -n "$src" ]; then
    if [ ! -d "$src" ]; then
        tmp="${src}.partial.$$"
        rm -rf "$tmp"
        git clone --quiet --depth 1 --branch "$HARNESSED_REF_PONYTAIL" "$PONYTAIL_REPO" "$tmp"
        mv "$tmp" "$src"
    fi
else
    src="$(mktemp -d)"
    trap 'rm -rf "$src"' EXIT
    git clone --quiet --depth 1 --branch "$HARNESSED_REF_PONYTAIL" "$PONYTAIL_REPO" "$src"
fi

# Skill dirs only: upstream's skills/plugin.json is a plugin manifest, not a skill.
mkdir -p "$HARNESSED_CONFIG_DIR/skills"
for skill in "$src"/skills/ponytail*/; do
    cp -r "$skill" "$HARNESSED_CONFIG_DIR/skills/"
done

# The hook scripts `require()` siblings by relative path, so the dir is copied whole. recipe.yaml's
# `hooks:` points at this location.
mkdir -p "$HARNESSED_CONFIG_DIR/ponytail"
rm -rf "$HARNESSED_CONFIG_DIR/ponytail/hooks"
cp -r "$src/hooks" "$HARNESSED_CONFIG_DIR/ponytail/hooks"

# Upstream names the tool ("grep every caller"); stacks deny grep or route search through a code
# graph, so name the goal instead. Temp file + mv, not `sed -i`: BSD sed has no portable -i.
for f in "$HARNESSED_CONFIG_DIR"/skills/ponytail*/SKILL.md "$HARNESSED_CONFIG_DIR/ponytail/hooks/ponytail-instructions.js"; do
    sed 's/grep every caller/find every caller/g; s/grep the whole tree/search the whole tree/g' "$f" > "$f.tmp"
    mv "$f.tmp" "$f"
done

# Pre-mark ponytail's statusline offer as seen. Unmarked, SessionStart tells the agent to edit
# settings.json, which harnessed regenerates, so the edit would be lost. An empty file is the
# upstream "already nudged, declined" state (hooks/ponytail-activate.js).
: > "$HARNESSED_CONFIG_DIR/.ponytail-statusline-nudged"
