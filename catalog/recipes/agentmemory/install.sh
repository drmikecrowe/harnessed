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

# Host mode: _host_run_installs sets npm_config_prefix to the STACK-scoped tools root and puts its
# bin/ first on PATH, so `-g` lands in the stack tree rather than the user's global pnpm store.
# No `install.cache` in recipe.yaml — the cache keys a CONTENT clone; pnpm has its own store.
pnpm add -g "@agentmemory/mcp@${AGENTMEMORY_VERSION}"
