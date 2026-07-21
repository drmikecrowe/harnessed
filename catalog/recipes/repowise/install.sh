#!/usr/bin/env bash
# install.sh — the repowise CLI, delivered identically by a container build and a host launch.
#
# Replaces the Dockerfile's `RUN uv tool install -p 3.13 "repowise==0.31.0"` (container-only) and
# the former `provision:` block (host-only) — one file, both modes.
#
# Env (emit.install_env), identical keys in both modes:
#   HARNESS  HARNESSED_MODE  HARNESSED_RECIPE_DIR  HARNESSED_CONFIG_DIR  HARNESSED_INSTALL_CACHE
# No HARNESSED_PROJECT_DIR: a build has no project mounted. repowise's project work (`repowise init
# --index-only`) is a per-project step the README documents, not an install step.
set -euo pipefail

# Exact PyPI pin (upstream requires Python >= 3.11; -p 3.13 matches the Dockerfile it replaces).
REPOWISE_VERSION="0.31.0"

# Unconditional: re-running with the same pin is a verified no-op ("already installed", exit 0),
# and a CHANGED pin swaps the version — so the every-launch host re-run is cheap and a bump lands.
# Host mode: UV_TOOL_DIR/UV_TOOL_BIN_DIR point at the STACK-scoped tools tree (_host_run_installs),
# so this never installs into the user's global uv tools.
#
# No `install.cache` in recipe.yaml — the cache keys a CONTENT clone; uv caches wheels itself.
uv tool install -p 3.13 "repowise==${REPOWISE_VERSION}"
