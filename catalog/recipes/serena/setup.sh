#!/usr/bin/env bash
# Recipe setup script for: serena — runs in BOTH host (`launch --host`) and container mode.
#
# Env supplied by the launcher, identical in both modes (launcher._script_env):
#   HARNESSED_MODE=host|container   HARNESSED_PROJECT_DIR   HARNESSED_CFG_NAME
#   HARNESSED_BIN_DIR (host only, already leading PATH)
#
# Idempotent and self-gating: it runs on every launch, and every step below is a no-op once done.
set -euo pipefail

cd "$HARNESSED_PROJECT_DIR"

# 1. INSTALL (host only). In container mode the Dockerfile already baked serena into the image, so
#    there is nothing to install. This is the step `provision:` used to own — but `provision:` could
#    only install, never configure, which is why step 2 had to live in the Dockerfile and was
#    therefore missing from host mode entirely.
if [ "$HARNESSED_MODE" = host ] && ! command -v serena >/dev/null 2>&1; then
    echo "serena: installing serena-agent==${SERENA_VERSION:=1.5.3} (host, stack-scoped)"
    uv tool install -p 3.13 "serena-agent==${SERENA_VERSION}"
fi

# 2. CONFIGURE the language-server backend. `serena init` writes the global config selecting the
#    code-intelligence backend; `-b LSP` is stated explicitly so a future upstream default flip
#    cannot silently change it. Skipped once the config exists.
if [ ! -f "${HOME}/.serena/serena_config.yml" ]; then
    serena init -b LSP
fi

# 3. CONVERGE the project name on HARNESSED_CFG_NAME. Left alone, serena names the project after the
#    DIRECTORY — which in a bare+worktree checkout is the worktree folder ("main",
#    "recipe-setup-script", …), never the repo. HARNESSED_CFG_NAME derives from {repo} instead.
#
#    {repo} and NOT {gcd_db}: serena's registry (~/.serena/serena_config.yml) is keyed by PATH, not
#    by name, and its cache/memories are per-checkout by design — so unlike beads, worktree-STABLE
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
