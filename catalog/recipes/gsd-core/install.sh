#!/usr/bin/env bash
# install.sh — GSD Core's own upstream installer, moved out of the recipe Dockerfile
# (bd harnessed-8px.5). Replaces the single RUN layer.
#
# Env this file may rely on (emit.install_env — same keys host and container):
#   HARNESS, HARNESSED_MODE, HARNESSED_RECIPE_DIR, HARNESSED_CONFIG_DIR, HARNESSED_INSTALL_CACHE
# PROJECT_DIR and friends are absent by design — a build has no project mounted.
#
# This is a pure CONTENT recipe (commands/agents/skills under the agent config dir), so unlike rtk it
# is fully host-capable: nothing needs root, nothing needs to land on PATH.
set -euo pipefail

# Exact version pin, not a floating `@latest` (upstream ships no `stable` dist-tag beyond `latest`
# itself). Bump deliberately.
GSD_CORE_VERSION="1.6.1"

: "${HARNESSED_CONFIG_DIR:?install.sh requires HARNESSED_CONFIG_DIR}"

# Upstream's install doc says `npx @opengsd/gsd-core@latest` — an interactive installer. We substitute
# pnpm dlx (no raw npm/npx anywhere in harnessed) and pass the documented non-interactive flags
# instead of relying on prompts, since there is no TTY during `podman build`.
if ! command -v pnpm >/dev/null 2>&1; then
    echo "error: install (gsd-core) needs 'pnpm' on PATH to run the upstream installer" \
         "(@opengsd/gsd-core ${GSD_CORE_VERSION})." >&2
    exit 1
fi

# `--global` writes to os.homedir()/.claude. $HARNESSED_HOME_SHIM is a harnessed-owned dir whose
# .claude IS $HARNESSED_CONFIG_DIR, so the installer's own notion of "global" lands in the stack's
# config dir in BOTH modes — no branch, no upstream flag. Container-side the shim is the image home,
# where $HOME/.claude already is the config dir, so this is byte-equivalent to the RUN it replaces.
#
# The shim is also STABLE across launches, and that is what keeps the installer's recorded paths
# valid. gsd's installer bakes ABSOLUTE hook paths into settings.json using the $HOME it ran under;
# under the previous `mktemp -d` shim those pointed into a dir deleted on exit, so all 12 hooks
# failed from the next launch onward (bd harnessed-8px.9).
#
# Moving $HOME also moves pnpm's own default store (~/.local/share/pnpm/store), which would make this
# re-download the package on every host launch. Pin the store back at the real one through pnpm's
# `npm_config_*` config-env form rather than a CLI flag ON PURPOSE: if a pnpm version does not honour
# the key it is ignored, costing a slow download — where an unsupported flag would abort the install
# outright. Read BEFORE $HOME moves, and a no-op container-side where the shim is the real home.
store="$(pnpm store path 2>/dev/null || true)"
(
    export HOME="$HARNESSED_HOME_SHIM"
    if [ -n "$store" ]; then
        export npm_config_store_dir="$store"
    fi
    pnpm dlx "@opengsd/gsd-core@${GSD_CORE_VERSION}" --claude --global
)
