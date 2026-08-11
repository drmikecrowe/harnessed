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

# NO VERSION LITERAL HERE (AC-1, #329) — not even in a comment, which is why the sentence below
# says `@<version>` instead of the number. The pin lives in recipe.yaml's `tools:` entry and nowhere
# else, so there is no second copy to drift and `harnessed update` can see it. A comment that
# repeats the version is the "kept in sync by a comment" failure this epic exists to delete; it just
# fails more quietly than a shell variable. This file invokes whatever `tools:` installed.

: "${HARNESSED_CONFIG_DIR:?install.sh requires HARNESSED_CONFIG_DIR}"

# Upstream's install doc says `npx @opengsd/gsd-core@latest` — an interactive installer run through
# a package-manager fetch. `tools:` does the fetch now, so this resolves the installed bin on PATH
# instead: `@opengsd/gsd-core` ships `gsd-core` as its default bin, and that bin IS the installer
# (bin/install.js) that `pnpm dlx` executed before. The documented non-interactive flags are still
# passed rather than relying on prompts, since there is no TTY during `podman build`.
#
# The guard is on `gsd-core`, not on pnpm: pnpm is no longer this script's dependency, and a guard
# naming the wrong binary sends whoever hits it to the wrong fix. Both executors install `tools:`
# BEFORE any `install.script`, so reaching this line without the bin means the tools install failed
# or was skipped — loud is right.
if ! command -v gsd-core >/dev/null 2>&1; then
    echo "error: install (gsd-core) needs the 'gsd-core' bin on PATH — it comes from this recipe's" \
         "\`tools: npm:@opengsd/gsd-core@<version>\`, installed before this script runs." >&2
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
# The pnpm store pin that used to sit here is GONE with the `pnpm dlx` it protected. It existed for
# one reason: moving $HOME moved pnpm's default store (~/.local/share/pnpm/store), so the dlx fetch
# re-downloaded the package on every host launch. Nothing in this script downloads any more — mise
# fetched the package during the `tools:` step, under the real $HOME, before this ran.
#
# Stated because it is NOT proven: if the upstream installer itself shells out to a package manager,
# the moved $HOME would re-point that child's store the same way. Nothing observed suggests it does
# (it writes skills/agents into ~/.claude), but confirming needs a real build — see the PR.
(
    export HOME="$HARNESSED_HOME_SHIM"
    gsd-core --claude --global
)
