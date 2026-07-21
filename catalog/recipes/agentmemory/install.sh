#!/usr/bin/env bash
# install.sh — the agentmemory stdio MCP ADAPTER (`agentmemory-mcp`), delivered identically by a
# container build and a host launch.
#
# Replaces the Dockerfile's `RUN pnpm add -g "@agentmemory/mcp@0.9.27"`, which only ever ran during
# `podman build` — so `launch --host` had no `agentmemory-mcp` on PATH and the MCP entry resolved
# to nothing.
#
# This installs the ADAPTER ONLY, never the store. The store is the SERVICE
# (catalog/services/agentmemory/, REST on :3111); the adapter is a stateless proxy that reaches it
# over AGENTMEMORY_URL. A stack using this recipe must still declare `services: [agentmemory]`.
#
# Env (emit.install_env), identical keys in both modes:
#   HARNESS  HARNESSED_MODE  HARNESSED_RECIPE_DIR  HARNESSED_CONFIG_DIR  HARNESSED_INSTALL_CACHE
set -euo pipefail

# `@agentmemory/mcp` — NOT `@agentmemory/agentmemory`. Only this package ships the
# `agentmemory-mcp` binary recipe.yaml spawns; the other ships the store CLI, which belongs in the
# service image. Verified against the npm registry at 0.9.27.
#
# pnpm, never npm/npx (repo policy, and validate_install_script rejects raw npm here). Exact pin,
# no `@latest` — the pin gate reads this file, not just the Dockerfile it replaces.
AGENTMEMORY_VERSION="0.9.27"

# PNPM_HOME is what contains a global install; npm_config_prefix does NOT (bd harnessed-8px.14).
# _host_run_installs sets npm_config_prefix to the stack tools root, and this comment used to claim
# that was enough — it is not. pnpm ignores npm_config_prefix for the global bin dir and falls back
# to ~/.local/share/pnpm, so a host launch was installing into the USER'S real store, outside every
# harnessed-owned directory. Verified with `pnpm bin -g`.
#
# The PARENT, not $HARNESSED_BIN_DIR itself: pnpm's global bin dir is "$PNPM_HOME/bin", so pointing
# PNPM_HOME at the bin dir resolves one level too deep and off PATH, where pnpm hard-errors.
# Container-side this is a no-op — the base image already sets PNPM_HOME inside the image.
# No `install.cache` in recipe.yaml — the cache keys a CONTENT clone; pnpm has its own store.
PNPM_HOME="$(dirname "$HARNESSED_BIN_DIR")" pnpm add -g "@agentmemory/mcp@${AGENTMEMORY_VERSION}"
