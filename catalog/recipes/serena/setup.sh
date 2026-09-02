#!/usr/bin/env bash
# Recipe setup script for: serena — runs in BOTH host (`launch --host`) and container mode.
#
# PROJECT-shaped work ONLY. The CLI install and `serena init -b LSP` (the global language-server
# backend config) used to be split across a `HARNESSED_MODE = host` branch here and the recipe
# Dockerfile — one half per mode, neither complete on its own. Both now live in install.sh, which
# runs in BOTH modes and BEFORE this script. What is left is what install.sh structurally cannot do:
# the install env carries no HARNESSED_PROJECT_DIR, because a build has no project mounted.
#
# Env supplied by the launcher, identical in both modes (launcher._script_env):
#   HARNESSED_MODE=host|container   HARNESSED_PROJECT_DIR   HARNESSED_CFG_NAME
#   HARNESSED_BIN_DIR (host only, already leading PATH)
#
# Idempotent and self-gating: it runs on every launch, and every step below is a no-op once done.
set -euo pipefail

cd "$HARNESSED_PROJECT_DIR"

# CONVERGE the project name on HARNESSED_CFG_NAME. Left alone, serena names the project after the
#    DIRECTORY — which in a bare+worktree checkout is the worktree folder ("main",
#    "recipe-setup-script", …), never the repo. HARNESSED_CFG_NAME derives from {repo} instead.
#
#    {repo} and NOT {gcd_db}: serena's registry (~/.serena/serena_config.yml) is keyed by PATH, not
#    by name, and its cache/memories are per-checkout by design — so a worktree-STABLE
#    identity is explicitly not wanted here. The name is a human label; the path is the key.
#
#    Two branches, because `serena project create` REFUSES an existing project ("Error: Project
#    already exists") — so creation alone can never repair a project.yml that was generated earlier
#    with the directory-derived name. Rewriting in place is the only path for those.
if [ ! -f .serena/project.yml ]; then
    serena project create --name "$HARNESSED_CFG_NAME" --index .
else
    current=$(sed -n 's/^project_name:[[:space:]]*"\{0,1\}\([^"]*\)"\{0,1\}[[:space:]]*$/\1/p' \
        .serena/project.yml | head -1)
    if [ -z "$current" ]; then
        # Key absent entirely (hand-edited or an older serena) — add it.
        printf 'project_name: "%s"\n' "$HARNESSED_CFG_NAME" >> .serena/project.yml
    elif [ "$current" != "$HARNESSED_CFG_NAME" ]; then
        echo "serena: correcting project_name '${current}' -> '${HARNESSED_CFG_NAME}'"
        sed -i "s|^project_name:.*|project_name: \"${HARNESSED_CFG_NAME}\"|" .serena/project.yml
    fi
fi
