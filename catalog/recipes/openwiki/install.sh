#!/usr/bin/env bash
# install.sh — openwiki: the CLI (with its native addon actually built) plus the integration skill.
#
# Env this file may rely on (emit.install_env — same keys host and container):
#   HARNESS, HARNESSED_MODE, HARNESSED_RECIPE_DIR, HARNESSED_CONFIG_DIR, HARNESSED_BIN_DIR
# PROJECT_DIR is absent by design — a build has no project mounted.
#
# Replaces `openwiki integrations install claude`, which harnessed cannot use: that command writes
# a skill into ~/.claude and an mcpServers entry into ~/.claude.json. In a pod the profile mount
# shadows the first, and harnessed owns MCP wiring through the hatago config, so the second would
# be dead config. Both deliverables are re-created here from the same pinned package: the skill by
# copying openwiki's own `integrations/openwiki` directory, the MCP entry by recipe.yaml.
set -euo pipefail

: "${HARNESSED_RECIPE_DIR:?install.sh requires HARNESSED_RECIPE_DIR}"
: "${HARNESSED_CONFIG_DIR:?install.sh requires HARNESSED_CONFIG_DIR}"
: "${HARNESSED_BIN_DIR:?install.sh requires HARNESSED_BIN_DIR}"

# THE ONLY PLACE THE VERSION IS WRITTEN. `harnessed update` reads literals out of an install script
# (update.discover_pins -> _opaque_pins_from_text), so this pin is visible to the pin report even
# though it is not a `tools:` entry. Do not repeat it in a comment; a second copy is a second thing
# to drift.
OPENWIKI_VERSION=0.4.3

if ! command -v pnpm >/dev/null 2>&1; then
    echo "error: install (openwiki) needs pnpm on PATH. Container images ship it; a --host launch" \
         "uses the host's own pnpm. Install pnpm, or drop this recipe from the stack." >&2
    exit 1
fi

# ~/.local in a pod, the stack's own tool tree on a host launch. `$HARNESSED_BIN_DIR` is
# `<that>/bin` in both modes (volumes.py: one volume at the common parent covers the bin dir,
# mise's installs, and $PNPM_HOME), so its parent is the right root for a sibling `share/` tree.
# Deriving it keeps this script out of the business of knowing either absolute path, and on a host
# launch it is what keeps the install stack-scoped instead of landing in the user's home.
prefix="$(dirname "$HARNESSED_BIN_DIR")/share/openwiki"

# Idempotent: the install phase is fingerprint-gated, but a re-run after a failed attempt must not
# inherit half a node_modules tree. pnpm is declarative over package.json, so the cheap correct
# thing is to let it re-resolve into a clean directory.
rm -rf "$prefix"
mkdir -p "$prefix"

# The reviewed build allowlist MUST be in place before the install resolves, or pnpm's
# default-deny (`strictDepBuilds: true`, catalog/base/pnpm/config.yaml) exits 1 on
# better-sqlite3's build script. See pnpm-workspace.yaml for why the allowlist cannot be global.
cp "$HARNESSED_RECIPE_DIR/pnpm-workspace.yaml" "$prefix/pnpm-workspace.yaml"

# A private manifest, not a global install: `pnpm add -g` ignores the project allowlist entirely,
# which is the whole reason this recipe does not use `tools:`.
cat > "$prefix/package.json" <<JSON
{
  "name": "harnessed-openwiki-install",
  "private": true,
  "dependencies": {
    "openwiki": "${OPENWIKI_VERSION}"
  }
}
JSON

pnpm --dir "$prefix" install

# The addon is the thing that actually has to exist. Without it every openwiki subcommand dies at
# "Could not locate the bindings file" with a 14-line list of paths — which reads like a broken
# Node install rather than a denied lifecycle script, so check for it by name and say so here.
if [[ -z "$(find "$prefix/node_modules" -name better_sqlite3.node -print -quit)" ]]; then
    echo "error: install (openwiki) resolved the package but better_sqlite3.node was not built." \
         "pnpm's lifecycle default-deny is the usual cause — confirm pnpm-workspace.yaml landed" \
         "at $prefix and still lists better-sqlite3 under allowBuilds." >&2
    exit 1
fi

# hatago spawns the MCP server as bare `openwiki`, so the bin has to be on PATH. A symlink, not a
# copy: the target is pnpm's own launcher and resolves its package relative to its real path.
mkdir -p "$HARNESSED_BIN_DIR"
ln -sfn "$prefix/node_modules/.bin/openwiki" "$HARNESSED_BIN_DIR/openwiki"

# The skill, from the pinned package rather than vendored into this recipe. `integrations/openwiki`
# is the exact directory `openwiki integrations install claude` copies to ~/.claude/skills/openwiki,
# so this stays byte-identical to upstream's own install and cannot drift from the pinned version.
# It also keeps third-party prose out of catalog/, which tests/test_prose_lint.py gates.
#
# `cp -RL`: pnpm's node_modules is symlinked into .pnpm, and the skill must be real files under the
# config dir — a dangling link into a tree the profile does not mount delivers nothing.
skill_src="$prefix/node_modules/openwiki/integrations/openwiki"
[[ -f "$skill_src/SKILL.md" ]] || {
    echo "error: install (openwiki) found no SKILL.md at $skill_src. Upstream moved the" \
         "integration skill; re-check the layout for openwiki ${OPENWIKI_VERSION}." >&2
    exit 1
}
rm -rf "$HARNESSED_CONFIG_DIR/skills/openwiki"
mkdir -p "$HARNESSED_CONFIG_DIR/skills"
cp -RL "$skill_src" "$HARNESSED_CONFIG_DIR/skills/openwiki"
