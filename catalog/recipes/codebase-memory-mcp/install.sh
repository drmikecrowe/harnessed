#!/usr/bin/env bash
# install.sh — the `codebase-memory-mcp` (cbm) binary, delivered by a container build AND a host
# launch.
#
# Replaces the Dockerfile's `RUN mise use -g "github:DeusData/codebase-memory-mcp@0.9.0" &&
# mise install`, which only ever ran during `podman build` — a host launch had no binary on PATH,
# so the stdio MCP child silently resolved to nothing.
#
# cbm is a static C binary with zero runtime deps (158 tree-sitter grammars + embedded SQLite), so
# there is nothing to compile in either mode. This replicates ONLY the binary-extract step; do NOT
# run cbm's own installer (`scripts/setup.sh` / its `install` command), which auto-configures 11
# agents (.mcp.json, skills, hooks, AGENTS.md) — harnessed owns all of that.
#
# Env (emit.install_env), identical keys in both modes:
#   HARNESS  HARNESSED_MODE  HARNESSED_RECIPE_DIR  HARNESSED_CONFIG_DIR  HARNESSED_INSTALL_CACHE
set -euo pipefail

# Release tags carry a `v` prefix (v0.9.0); mise's github: backend resolves the bare version against
# them. Exact pin — the install lint rejects a floating ref here just as validate_pin did in the
# Dockerfile. Linux amd64/arm64 assets both ship at this tag.
CBM_VERSION="0.9.0"
CBM_TOOL="github:DeusData/codebase-memory-mcp@${CBM_VERSION}"

# The ONE place this recipe is not mode-symmetric, and deliberately so.
#
# Container: `mise use -g` is right — the image's global mise config IS the image, and writing the
# tool there is what puts it on PATH through the shims harnessed-base already ships.
#
# Host: `mise use -g` would edit the USER's ~/.config/mise/config.toml and add cbm to every shell
# they open — a stack-scoped install has no business doing that. `mise install <tool>@<ver>` writes
# no config, then the resolved binary is linked into the stack-scoped bin dir the launcher put
# first on PATH, so cbm is visible to this stack and to nothing else.
if [ "$HARNESSED_MODE" = container ]; then
    mise use -g "$CBM_TOOL"
    mise install
else
    # UV_TOOL_BIN_DIR is the stack bin dir (_host_run_installs). It is not part of the documented
    # install env contract — it is set alongside it, host-only — hence the hard `:?` rather than a
    # silent fallback that would drop the binary somewhere the launcher never looks.
    #
    # MISE_LOG_LEVEL=error suppresses mise's "installed but not activated — it is not in any config
    # file" WARN. mise describes the state above correctly and calls it a problem wrongly: it fires
    # on EVERY host launch (not only the first — verified by re-running an already-installed tool),
    # and the remedy it suggests is the `mise use -g` this branch exists to avoid.
    #
    # On `mise install` ONLY. `mise which` was measured and does not emit this WARN, so raising its
    # log floor would suppress nothing that exists while blinding the script to any WARN mise adds
    # there later. Install failures are unaffected either way — they report at ERROR, which this
    # floor still lets through (verified against an unresolvable bin name).
    MISE_LOG_LEVEL=error mise install "$CBM_TOOL"
    ln -sf "$(mise which --tool="$CBM_TOOL" codebase-memory-mcp)" \
        "${UV_TOOL_BIN_DIR:?install.sh (host): UV_TOOL_BIN_DIR unset}/codebase-memory-mcp"
fi
