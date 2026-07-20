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

# `--global` writes to os.homedir()/.claude. Container-side that IS $HARNESSED_CONFIG_DIR, so the
# installer is called directly — byte-identical to the RUN it replaces. Host-side $HOME is the USER'S
# home, so "global" would mean the user's real ~/.claude: a write outside $HARNESSED_CONFIG_DIR that
# would survive the stack. A throwaway $HOME whose .claude symlinks to the stack's materialized
# config dir makes the installer's own notion of "global" land exactly where it belongs, with no
# upstream flag required.
# Replace every "<shim>/.claude" prefix the installer baked into settings.json with the real config
# dir. $1 = the shim home. Only the REPLACEMENT needs escaping (& and \ are special in a sed RHS, |
# is the delimiter); the pattern is a mktemp path, which is alnum-safe by construction.
_rewrite_shim_paths() {
    settings="$HARNESSED_CONFIG_DIR/settings.json"
    [ -f "$settings" ] || return 0
    esc=$(printf '%s' "$HARNESSED_CONFIG_DIR" | sed -e 's/[&|\\]/\\&/g')
    rewritten="${settings}.rewritten.$$"
    sed "s|$1/\.claude|$esc|g" "$settings" > "$rewritten"
    mv "$rewritten" "$settings"
}

if [ "$HARNESSED_CONFIG_DIR" = "${HOME:-}/.claude" ]; then
    pnpm dlx "@opengsd/gsd-core@${GSD_CORE_VERSION}" --claude --global
else
    # Moving $HOME also moves pnpm's own default store (~/.local/share/pnpm/store), which would make
    # this re-download the package on every host launch. Pin the store back at the real one through
    # pnpm's `npm_config_*` config-env form rather than a CLI flag ON PURPOSE: if a pnpm version does
    # not honour the key it is ignored, costing a slow download — where an unsupported flag would
    # abort the install outright.
    store="$(pnpm store path 2>/dev/null || true)"
    shim_home="$(mktemp -d)"
    trap 'rm -rf "$shim_home"' EXIT
    ln -s "$HARNESSED_CONFIG_DIR" "$shim_home/.claude"
    (
        export HOME="$shim_home"
        if [ -n "$store" ]; then
            export npm_config_store_dir="$store"
        fi
        pnpm dlx "@opengsd/gsd-core@${GSD_CORE_VERSION}" --claude --global
    )
    # The shim makes the installer's FILE writes land correctly (through the .claude symlink), but it
    # also records ABSOLUTE hook paths using the $HOME it ran under — so every hook command in
    # settings.json points into $shim_home, which the trap above deletes on exit. Next launch, all 12
    # hooks fail with "No such file or directory" / a node loader error (bd harnessed-8px.9).
    # Rewrite them to the real config dir while $shim_home is still known. A no-op if the installer
    # ever stops baking absolute paths.
    _rewrite_shim_paths "$shim_home"
fi
